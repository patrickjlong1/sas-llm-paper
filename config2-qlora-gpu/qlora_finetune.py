r"""
qlora_finetune.py
==================
QLoRA fine-tune of the SAME base model config1 uses (Gemma), on the SAME
prompt/output schema (schema.py) as every other config in this project --
the plan's Config 2: "the model is trained on pairs of SAS programs and
their documentation... does a modest training run close the gap to the
frontier while staying air-gapped." Needs a GPU; a free Colab T4 is enough
for a 1B-4B-class base at MAXLEN<=2048 -- see this folder's SETUP.md.

HARD CONSTRAINT (plan section 2): the 20 eval-programs/ programs must be
held out of training entirely, or the scores are meaningless. This script's
training data must come from generate_training_corpus.py's OWN id range
(disjoint from eval-programs/'s id-offset 900) -- never point --train at
eval-programs/, and double check with:

    python3 check_no_leakage.py --train ../data/train.jsonl --eval ../eval-programs/gold

Colab setup (run once, in a cell, before this script):

    !pip -q install "transformers>=4.44" "trl>=0.24" "peft>=0.12" \
                    "bitsandbytes>=0.43" "datasets>=2.20" "accelerate>=0.33"

Hardware reality check (plan: report hardware honestly):
  * free T4 (16 GB, no bf16, no flash-attn): gemma-3-1b-it in 4-bit at
    MAXLEN=2048 works comfortably; ~30-90 min for 600 samples x 2 epochs
    (observed ~50s/step, 150 steps -- see this folder's SETUP.md).
  * gemma-3-4b-it (this project's current default, matching config1's
    gemma3:4b) is expected to fit a free T4 in 4-bit at MAXLEN=2048 too --
    4B params in nf4 is roughly 2-2.5 GB of weights plus LoRA/optimizer
    state/activations, well inside 16 GB -- but this has NOT actually been
    run end-to-end on a T4 yet in this repo; expect noticeably slower
    steps than the 1B numbers above and budget accordingly. Report real
    numbers here once you've run it.
  * Colab Pro L4 / A100: MAXLEN=4096-8192, bf16, faster still.
MAXLEN is the real constraint, not parameter count -- a real legacy program
plus its documentation JSON must fit in one window.

What has actually been run: an adapter trained with these defaults exists at
`../adapters/sasdoc-lora` (2026-09-21). Its `run_config.json` records
`model=google/gemma-3-4b-it, maxlen=2048, epochs=2, lr=2e-4, bf16=true` --
and `bf16=true` comes from `torch.cuda.is_bf16_supported()`, which is False
on a T4, so that run was NOT on a free T4. Neither the GPU model nor the
wall-clock time was recorded. Record both for the paper; the table's
"cost per program" is inference only and does not include this.

Run (note --eval is a TRAIN-time holdout, never eval-programs/ -- pointing
--eval at the scoring set is exactly the leak this config must not have):
    python3 qlora_finetune.py --train ../data/train.jsonl \
        --eval ../data/train_holdout.jsonl \
        --model google/gemma-3-4b-it --maxlen 2048 --epochs 2
"""

import argparse
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
    ap.add_argument("--maxlen", type=int, default=2048)
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
    # experiment fails.
    def fits(rec):
        ids = tok.apply_chat_template(to_chat(rec, tok)["messages"], tokenize=True)
        return len(ids) <= args.maxlen

    kept = [r for r in train_recs if fits(r)]
    print("train: kept %d / %d at maxlen=%d" % (len(kept), len(train_recs), args.maxlen))
    if len(kept) < 0.8 * len(train_recs):
        print("WARNING: >20%% dropped. Raise --maxlen or shorten the target JSON.")

    ds_train = Dataset.from_list([to_chat(r, tok) for r in kept])
    ds_eval = Dataset.from_list([to_chat(r, tok) for r in eval_recs if fits(r)])

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
        eval_strategy="epoch",
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
    accepted = inspect.signature(SFTConfig.__init__).parameters
    dropped = {k: v for k, v in targs_kwargs.items() if k not in accepted}
    if dropped:
        print("WARNING: this trl's SFTConfig does not accept: %s -- using its defaults for them"
              % ", ".join(dropped))
    targs = SFTConfig(**{k: v for k, v in targs_kwargs.items() if k in accepted})

    trainer = SFTTrainer(
        model=model, args=targs, processing_class=tok,
        train_dataset=ds_train, eval_dataset=ds_eval,
    )
    trainer.train()

    os.makedirs(args.out, exist_ok=True)
    trainer.model.save_pretrained(args.out)      # adapter only, tens of MB
    tok.save_pretrained(args.out)

    with open(os.path.join(args.out, "run_config.json"), "w") as fh:
        json.dump({**vars(args), "bf16": bf16_ok}, fh, indent=2)

    if args.push:
        trainer.model.push_to_hub(args.push)
        tok.push_to_hub(args.push)
        print("pushed adapter to", args.push)


if __name__ == "__main__":
    main()
