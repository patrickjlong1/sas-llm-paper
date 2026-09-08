r"""
02_qlora_finetune.py
====================
QLoRA fine-tune of a small open-weight model to turn undocumented SAS into
documentation + a data dictionary. Written to run in a single Colab session.

Colab setup (run once, in a cell, before this script):

    !pip -q install "transformers>=4.44" "trl>=0.9" "peft>=0.12" \
                    "bitsandbytes>=0.43" "datasets>=2.20" "accelerate>=0.33"

Hardware reality check before you start:
  * free T4 (16 GB, no bf16, no flash-attn):  4B in 4-bit at MAXLEN=2048 works,
    MAXLEN=4096 is borderline, expect ~2-4 h for 600 samples x 2 epochs.
  * Colab Pro L4 / A100:                      MAXLEN=8192, bf16, ~30-60 min.
MAXLEN is the constraint that actually decides this experiment, not parameter
count -- a real legacy program plus its documentation must fit in one window.

Run:
    python 02_qlora_finetune.py --train ../data/train.jsonl --eval ../data/eval.jsonl \
        --model Qwen/Qwen2.5-Coder-3B-Instruct --maxlen 2048 --epochs 2
"""

import argparse
import json
import os

import torch
from datasets import Dataset
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from transformers import (AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig,
                          TrainingArguments)
from trl import SFTTrainer, DataCollatorForCompletionOnlyLM

SYSTEM = (
    "You document legacy SAS production code. Given a SAS program, return "
    "markdown with these sections in order: Purpose, Inputs, Outputs, "
    "Macro reference, Processing sequence, Lineage, Side effects and cautions, "
    "Data dictionary. Never name a variable or dataset that does not appear in "
    "the program. Mark anything you could not verify from the code with "
    "[INFERRED]."
)


def load_jsonl(path):
    with open(path) as fh:
        return [json.loads(line) for line in fh]


def to_chat(rec, tok):
    """One training example: program in, documentation out."""
    msgs = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "```sas\n" + rec["sas"] + "\n```"},
        {"role": "assistant", "content": rec["doc"]},
    ]
    return {"text": tok.apply_chat_template(msgs, tokenize=False)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", default="../data/train.jsonl")
    ap.add_argument("--eval", default="../data/eval.jsonl")
    ap.add_argument("--model", default="Qwen/Qwen2.5-Coder-3B-Instruct")
    ap.add_argument("--revision", default="main",
                    help="PIN THIS to a commit sha for a reproducible paper")
    ap.add_argument("--maxlen", type=int, default=2048)
    ap.add_argument("--epochs", type=float, default=2.0)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--out", default="../adapters/sasdoc-lora")
    ap.add_argument("--push", default=None, help="hub repo id, e.g. patlongcodes/sasdoc-lora")
    args = ap.parse_args()

    bf16_ok = torch.cuda.is_bf16_supported()

    tok = AutoTokenizer.from_pretrained(args.model, revision=args.revision)
    tok.pad_token = tok.pad_token or tok.eos_token
    tok.padding_side = "right"

    train_recs = load_jsonl(args.train)
    eval_recs = load_jsonl(args.eval)

    # Drop anything that will not fit -- silent truncation of the assistant turn
    # teaches the model to stop mid-dictionary, which is the single most common
    # way this experiment fails.
    def fits(rec):
        return len(tok(to_chat(rec, tok)["text"]).input_ids) <= args.maxlen

    kept = [r for r in train_recs if fits(r)]
    print("train: kept %d / %d at maxlen=%d" % (len(kept), len(train_recs), args.maxlen))
    if len(kept) < 0.8 * len(train_recs):
        print("WARNING: >20%% dropped. Raise --maxlen or shorten the doc template.")

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
    resp_template = "<|im_start|>assistant\n"      # Qwen ChatML; change per model
    collator = DataCollatorForCompletionOnlyLM(response_template=resp_template, tokenizer=tok)

    targs = TrainingArguments(
        output_dir=args.out,
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

    trainer = SFTTrainer(
        model=model, args=targs,
        train_dataset=ds_train, eval_dataset=ds_eval,
        dataset_text_field="text", max_seq_length=args.maxlen,
        data_collator=collator, packing=False,
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
