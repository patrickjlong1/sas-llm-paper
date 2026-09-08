r"""
03a_infer.py
============
Generates documentation for each held-out program and writes preds jsonl for
03_evaluate.py. Run it TWICE -- once with --adapter and once without -- so the
paper reports base vs tuned on identical inputs.

    python 03a_infer.py --eval ../data/eval.jsonl --out ../data/preds_base.jsonl
    python 03a_infer.py --eval ../data/eval.jsonl --adapter ../adapters/sasdoc-lora \
                        --out ../data/preds_tuned.jsonl

greedy decoding (do_sample=False) so the comparison is not a sampling artifact.
"""

import argparse
import json

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

SYSTEM = (
    "You document legacy SAS production code. Given a SAS program, return "
    "markdown with these sections in order: Purpose, Inputs, Outputs, "
    "Macro reference, Processing sequence, Lineage, Side effects and cautions, "
    "Data dictionary. Never name a variable or dataset that does not appear in "
    "the program. Mark anything you could not verify from the code with "
    "[INFERRED]."
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", default="../data/eval.jsonl")
    ap.add_argument("--model", default="Qwen/Qwen2.5-Coder-3B-Instruct")
    ap.add_argument("--revision", default="main")
    ap.add_argument("--adapter", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-new", type=int, default=1400)
    args = ap.parse_args()

    tok = AutoTokenizer.from_pretrained(args.model, revision=args.revision)
    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                             bnb_4bit_compute_dtype=torch.float16)
    model = AutoModelForCausalLM.from_pretrained(
        args.model, revision=args.revision, quantization_config=bnb, device_map="auto")
    if args.adapter:
        model = PeftModel.from_pretrained(model, args.adapter)
    model.eval()

    with open(args.out, "w") as fh:
        for line in open(args.eval):
            rec = json.loads(line)
            msgs = [{"role": "system", "content": SYSTEM},
                    {"role": "user", "content": "```sas\n" + rec["sas"] + "\n```"}]
            ids = tok.apply_chat_template(msgs, add_generation_prompt=True,
                                          return_tensors="pt").to(model.device)
            with torch.no_grad():
                gen = model.generate(ids, max_new_tokens=args.max_new,
                                     do_sample=False, pad_token_id=tok.eos_token_id)
            doc = tok.decode(gen[0][ids.shape[-1]:], skip_special_tokens=True)
            fh.write(json.dumps({"program_name": rec["spec"]["program_name"],
                                 "doc": doc}) + "\n")
            print("done", rec["spec"]["program_name"])


if __name__ == "__main__":
    main()
