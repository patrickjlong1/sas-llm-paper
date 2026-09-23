r"""
qlora_finetune.py
==================
QLoRA fine-tune of the SAME base model config1 uses (Gemma), on the SAME
prompt/output schema (schema.py) as every other config in this project --
the plan's Config 2: "the model is trained on pairs of SAS programs and
their documentation... does a modest training run close the gap to the
frontier while staying air-gapped." Needs a GPU -- see this folder's SETUP.md.

HARD CONSTRAINT (plan section 2): the 20 eval-programs/ programs must be
held out of training entirely, or the scores are meaningless. This script's
training data must come from generate_training_corpus.py's OWN id range
(disjoint from eval-programs/'s id-offset 900) -- never point --train at
eval-programs/, and double check with:

    python3 check_no_leakage.py --train ../data/train.jsonl --eval ../eval-programs/gold

Colab setup (run once, in a cell, before this script):

    !pip -q install "transformers>=4.44" "trl>=0.24" "peft>=0.12" \
                    "bitsandbytes>=0.43" "datasets>=2.20" "accelerate>=0.33"

MAXLEN is the real constraint here, not parameter count: one training example
is the schema block + a SAS program + its indented gold JSON, which measures
~2400-2800 tokens for this corpus. MAXLEN=2048 therefore does not fit a
SINGLE example, and the 2026-09-21 run in this repo hit both halves of that:
  * with the old length filter (which compared len() of a BatchEncoding, i.e.
    2, against maxlen and so never fired) everything trained TRUNCATED at
    2048 -- every target cut off mid-dictionary, which is precisely what the
    filter existed to prevent;
  * with the filter fixed, the same maxlen=2048 dropped 579/580 training
    examples and all 20 holdout examples, and the run died with a bare
    StopIteration from inside trl's _prepare_dataset on the empty eval set.
So: --maxlen 4096 is the floor for this corpus, and the script now prints the
measured p50/p90/p99/max and refuses to start if >20% of the corpus does not
fit. Do not lower it back to 2048 to save memory.

Hardware reality check (plan: report hardware honestly):
  * A100 40 GB, gemma-3-4b-it in 4-bit at MAXLEN=4096, batch 1 x grad-accum 8
    with gradient checkpointing: fits with room to spare.
  * free T4 (16 GB, no bf16, no flash-attn): the 4B base in nf4 is only
    ~2-2.5 GB of weights, but MAXLEN=4096 activations (not weights) are what
    decides this, and it has NOT been run end-to-end on a T4 in this repo.
    Verify before quoting a T4 number in the paper.
  * Colab Pro L4 / A100: MAXLEN=4096-8192, bf16.

What has actually been run: an adapter exists at `../adapters/sasdoc-lora`
(2026-09-21), but its `run_config.json` records `maxlen=2048`, so it was
trained on truncated targets per the first bullet above -- RETRAIN IT at
--maxlen 4096 before using its scores for anything. `bf16=true` there comes
from `torch.cuda.is_bf16_supported()`, which is False on a T4, so that run
was not on a free T4; neither the GPU model nor the wall clock was recorded.
Record both for the paper; the table's "cost per program" is inference only
and does not include this.

Run (note --eval is a TRAIN-time holdout, never eval-programs/ -- pointing
--eval at the scoring set is exactly the leak this config must not have):
    python3 qlora_finetune.py --train ../data/train.jsonl \
        --eval ../data/train_holdout.jsonl \
        --model google/gemma-3-4b-it --maxlen 4096 --epochs 2
"""

import argparse
import dataclasses
import inspect
import json
import os

import torch
from datasets import Dataset
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from trl import SFTConfig, SFTTrainer

from schema import PROMPT_SCHEMA_BLOCK

SYSTEM = (
    "You document legacy SAS production code for a data analyst who has never "
    "seen this program before. You will be given one SAS program.\n\n"
    "Hard rules:\n"
    "- Never name a variable, dataset, or macro parameter that does not appear "
    "in the program text.\n"
    "- Document only OUTPUT datasets (written to a permanent library, or the "
    "program's final result) -- not every intermediate/temp dataset.\n\n"
    + PROMPT_SCHEMA_BLOCK
)


def load_jsonl(path):
    with open(path) as fh:
        return [json.loads(line) for line in fh]


def to_chat(rec, tok):
    """One training example: program in, gold documentation JSON out.
    Same schema/prompt as config1 and config3 -- only the model and its
    access to ground truth differ, per the plan."""
    target = json.dumps(rec["gold"], indent=2) if "gold" in rec else json.dumps(rec["dict"], indent=2)
    msgs = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "```sas\n" + rec["sas"] + "\n```"},
        {"role": "assistant", "content": target},
    ]
    return {"messages": msgs}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", default="../data/train.jsonl",
                    help="output of generate_training_corpus.py -- MUST NOT overlap "
                         "eval-programs/ (see check_no_leakage.py)")
    ap.add_argument("--eval", default="../data/train_holdout.jsonl",
                    help="a small slice of TRAINING data held out for eval-during-training "
                         "loss curves only -- NOT the 20 eval-programs/ (those are for "
                         "results/score.py after training, never seen here)")
    ap.add_argument("--model", default="google/gemma-3-4b-it",
                    help="same base as config1's gemma3:4b (Ollama serves the GGUF "
                         "conversion of this same model) -- keep these matched so the "
                         "config1 vs config2 comparison is actually base-vs-fine-tuned, "
                         "not base-model-vs-base-model. Gemma weights are gated on HF: "
                         "accept the license on the model page and set HF_TOKEN first.")
    ap.add_argument("--revision", default="main",
                    help="PIN THIS to a commit sha for a reproducible paper")
    ap.add_argument("--maxlen", type=int, default=4096,
                    help="a schema block + one SAS program + its indented gold JSON is "
                         "~2400-2800 tokens for this corpus, so 2048 drops essentially "
                         "every example -- measured p50/p90/max are printed below")
    ap.add_argument("--epochs", type=float, default=2.0)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--out", default="../adapters/sasdoc-lora")
    ap.add_argument("--push", default=None, help="hub repo id, e.g. yourname/sasdoc-lora")
    args = ap.parse_args()

    bf16_ok = torch.cuda.is_bf16_supported()

    tok = AutoTokenizer.from_pretrained(args.model, revision=args.revision)
    tok.pad_token = tok.pad_token or tok.eos_token
    tok.padding_side = "right"

    train_recs = load_jsonl(args.train)
    if os.path.exists(args.eval):
        eval_recs = load_jsonl(args.eval)
        train_names = {r.get("program_name") for r in train_recs}
        overlap = [r.get("program_name") for r in eval_recs if r.get("program_name") in train_names]
        if overlap:
            print("WARNING: %d of %d --eval examples are also in --train (%s...). The "
                  "eval loss below cannot show overfitting. generate_training_corpus.py "
                  "splits a clean train_holdout.jsonl -- regenerate with it."
                  % (len(overlap), len(eval_recs), ", ".join(overlap[:3])))
    else:
        # Last resort so a training run never dies on a missing file -- but say
        # plainly what the resulting eval curve is and isn't worth.
        eval_recs = train_recs[-20:]
        print("WARNING: --eval %s not found; falling back to the LAST 20 TRAINING "
              "examples. Those are in the training set, so the eval loss printed each "
              "epoch measures memorization, not generalization. Run "
              "generate_training_corpus.py (it writes train_holdout.jsonl) to get a "
              "real train-time holdout. Neither file is the scoring set -- that is "
              "always eval-programs/." % args.eval)

    # Drop anything that will not fit -- silent truncation of the assistant turn
    # teaches the model to stop mid-dictionary, the single most common way this
    # experiment fails. But a silent *drop* is worse than a loud one: at
    # maxlen=2048 this filter threw away 579 of 580 training examples and all 20
    # holdout examples, and the only symptom was a StopIteration from inside
    # trl's _prepare_dataset on the empty eval set. So measure every example,
    # print the distribution, and refuse to train on a corpus this has gutted.
    def n_tokens(rec):
        # return_dict=True explicitly: newer transformers default to it anyway,
        # and a bare len() over the returned BatchEncoding counts keys (2), not
        # tokens, which silently disables this filter.
        enc = tok.apply_chat_template(to_chat(rec, tok)["messages"], tokenize=True,
                                      return_dict=True)
        return len(enc["input_ids"])

    def split_by_len(recs, name):
        """Keep what fits, and always say what the lengths actually were --
        'kept 1 / 580' is only actionable next to the number to raise --maxlen to."""
        measured = [(r, n_tokens(r)) for r in recs]
        kept = [r for r, n in measured if n <= args.maxlen]
        lens = sorted(n for _, n in measured)
        if lens:
            pct = lambda q: lens[min(len(lens) - 1, int(q * len(lens)))]
            print("%s: kept %d / %d at maxlen=%d (example tokens: p50=%d p90=%d "
                  "p99=%d max=%d)" % (name, len(kept), len(recs), args.maxlen,
                                      pct(0.5), pct(0.9), pct(0.99), lens[-1]))
        return kept, lens

    kept, train_lens = split_by_len(train_recs, "train")
    eval_kept, _ = split_by_len(eval_recs, "eval")

    # Round the longest example up to the next multiple of 512 -- the number to
    # pass next run.
    suggest = (max(train_lens or [args.maxlen]) + 511) // 512 * 512
    if not kept:
        raise SystemExit(
            "FATAL: every one of the %d training examples is longer than --maxlen %d, "
            "so there is nothing to train on -- one example is the schema block + a "
            "SAS program + its indented gold JSON, which does not fit. Re-run with "
            "--maxlen %d." % (len(train_recs), args.maxlen, suggest))
    if len(kept) < 0.8 * len(train_recs):
        raise SystemExit(
            "FATAL: %d of %d training examples (%.0f%%) are longer than --maxlen %d. "
            "Training on the short tail is not a fine-tune of this task -- it is a "
            "fine-tune of whichever programs happened to be small. Re-run with "
            "--maxlen %d, or shorten the target JSON."
            % (len(train_recs) - len(kept), len(train_recs),
               100.0 * (len(train_recs) - len(kept)) / len(train_recs), args.maxlen, suggest))

    ds_train = Dataset.from_list([to_chat(r, tok) for r in kept])
    ds_eval = Dataset.from_list([to_chat(r, tok) for r in eval_kept]) if eval_kept else None
    if ds_eval is None:
        print("WARNING: no --eval example fits maxlen=%d -- training with eval "
              "disabled. There will be no eval-loss curve for the paper." % args.maxlen)

    bnb = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.bfloat16 if bf16_ok else torch.float16,
    )

    model = AutoModelForCausalLM.from_pretrained(
        args.model, revision=args.revision, quantization_config=bnb, device_map="auto",
    )
    model.config.use_cache = False
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)

    lora = LoraConfig(
        r=32, lora_alpha=64, lora_dropout=0.05, bias="none", task_type="CAUSAL_LM",
        # attention + MLP. MLP matters here: the task is heavy on surface-form
        # mapping (alias -> meaning), which lives largely in the MLP blocks.
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
    )
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()

    # Loss on the assistant turn only. Without this the model spends capacity
    # learning to reproduce SAS programs, which is not the task.
    targs_kwargs = dict(
        output_dir=args.out,
        max_length=args.maxlen,
        packing=False,
        assistant_only_loss=True,
        num_train_epochs=args.epochs,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=8,
        gradient_checkpointing=True,
        learning_rate=args.lr,
        lr_scheduler_type="cosine",
        warmup_ratio=0.03,
        logging_steps=10,
        eval_strategy="epoch" if ds_eval is not None else "no",
        save_strategy="epoch",
        bf16=bf16_ok,
        fp16=not bf16_ok,
        optim="paged_adamw_8bit",
        report_to="none",
        seed=20260903,
    )
    # requirements.txt only pins a floor (trl>=0.24) -- the resolved trl's
    # SFTConfig field names can drift out from under this script. Filter
    # against the live signature instead of crashing on a kwarg it dropped.
    accepted = set(inspect.signature(SFTConfig.__init__).parameters)
    accepted |= {f.name for f in dataclasses.fields(SFTConfig)}  # dataclass w/ custom __init__
    if "warmup_ratio" not in accepted and "warmup_steps" in accepted:
        # Don't silently train without warmup because the field was renamed --
        # a 2e-4 LoRA LR with no warmup spikes the loss on the first steps.
        total = -(-len(ds_train) // (targs_kwargs["per_device_train_batch_size"]
                                     * targs_kwargs["gradient_accumulation_steps"]))
        total = int(total * args.epochs)
        targs_kwargs["warmup_steps"] = max(1, round(targs_kwargs.pop("warmup_ratio") * total))
        print("NOTE: this trl's SFTConfig has no warmup_ratio -- using warmup_steps=%d "
              "(3%% of %d steps) instead" % (targs_kwargs["warmup_steps"], total))
    dropped = {k: v for k, v in targs_kwargs.items() if k not in accepted}
    if dropped:
        print("WARNING: this trl's SFTConfig does not accept: %s -- using its defaults for them"
              % ", ".join(dropped))
    targs = SFTConfig(**{k: v for k, v in targs_kwargs.items() if k in accepted})

    # eval_dataset=None, never an empty Dataset: trl's _prepare_dataset does
    # next(iter(dataset)) to sniff the column layout, so an empty one comes back
    # as a bare StopIteration with nothing naming the dataset that was empty.
    trainer = SFTTrainer(
        model=model, args=targs, processing_class=tok,
        train_dataset=ds_train, eval_dataset=ds_eval,
    )
    trainer.train()

    os.makedirs(args.out, exist_ok=True)
    trainer.model.save_pretrained(args.out)      # adapter only, tens of MB
    tok.save_pretrained(args.out)

    with open(os.path.join(args.out, "run_config.json"), "w") as fh:
        json.dump({**vars(args), "bf16": bf16_ok,
                   "train_examples_used": len(ds_train),
                   "train_examples_total": len(train_recs),
                   "eval_examples_used": len(ds_eval) if ds_eval is not None else 0,
                   "train_tokens_p50": train_lens[len(train_lens) // 2],
                   "train_tokens_max": train_lens[-1]}, fh, indent=2)

    if args.push:
        trainer.model.push_to_hub(args.push)
        tok.push_to_hub(args.push)
        print("pushed adapter to", args.push)


if __name__ == "__main__":
    main()
