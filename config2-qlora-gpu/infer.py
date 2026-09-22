r"""
infer.py
========
Generates documentation JSON for each of the 20 held-out eval-programs/
using the QLoRA-tuned model (or the bare base model, for a base-vs-tuned
comparison). Writes one <program>.pred.json + <program>.meta.json per
program into --out, in the SAME shape config1's document_sas.py writes --
so results/score.py and run_eval.py work identically across configs.

Run it TWICE -- once with --adapter and once without -- so the paper
reports base vs QLoRA-tuned on identical inputs, both scored against
eval-programs/gold/, which this script never trains on (see
check_no_leakage.py).

    python3 infer.py --out preds/config2-base
    python3 infer.py --adapter ../adapters/sasdoc-lora --out preds/config2-tuned

Greedy decoding (do_sample=False) so base-vs-tuned is not a sampling
artifact. Also records wall-clock time per program (GPU) into the .meta.json
sidecar for the plan's "time per program" column -- note this is generation
time only, not the one-time training cost; report the training cost
separately (see SETUP.md).
"""

import argparse
import glob
import json
import os
import time

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

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


def _parse_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        return json.loads(text), None
    except json.JSONDecodeError as e:
        return None, str(e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval-sas-dir", default="../eval-programs/programs")
    ap.add_argument("--model", default="google/gemma-3-4b-it")
    ap.add_argument("--revision", default="main")
    ap.add_argument("--adapter", default=None,
                    help="path/hub-id of the QLoRA adapter from qlora_finetune.py. "
                         "Omit to run the bare base model (config2's own base-model "
                         "baseline, distinct from config1's Ollama/CPU serving of the "
                         "same weights -- useful for isolating fine-tuning's effect "
                         "from serving-stack differences).")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-new", type=int, default=1200)
    ap.add_argument("--gpu-usd-per-hour", type=float, default=0.0,
                    help="price of the GPU this runs on, so the results table's "
                         "'cost per program' column is a measured number rather than "
                         "a hardcoded 0. 0.0 (the default) is correct for Colab's "
                         "FREE tier and is what makes the plan's air-gap sentence "
                         "true; set it to what you actually pay on a Pro/paid runtime. "
                         "Inference only -- the one-time training cost is separate "
                         "(see SETUP.md section 4).")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)

    sas_files = sorted(glob.glob(os.path.join(args.eval_sas_dir, "*.sas")))
    if not sas_files:
        raise SystemExit("no .sas files found in %r -- this almost certainly means the path "
                         "is wrong (e.g. eval-programs/ wasn't pulled into this session), not "
                         "that the directory is genuinely empty. Pass --eval-sas-dir to point "
                         "at the real eval-programs/programs." % args.eval_sas_dir)

    # PLAN.md: "Record wall-clock time, hardware, and cost per program."
    # Read the hardware rather than describing it in prose -- a results table
    # that says "GPU (see SETUP.md)" cannot be checked by a reader.
    if torch.cuda.is_available():
        hardware = "GPU: %s (%.1f GB)" % (
            torch.cuda.get_device_name(0),
            torch.cuda.get_device_properties(0).total_memory / 1e9)
    else:
        hardware = ("CPU -- no CUDA device visible. infer.py loads the base model "
                    "in 4-bit via bitsandbytes, whose kernels need a CUDA GPU; on "
                    "Colab set Runtime -> Change runtime type -> T4 GPU.")
    print(hardware)

    tok = AutoTokenizer.from_pretrained(args.model, revision=args.revision)
    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                             bnb_4bit_compute_dtype=torch.float16)
    model = AutoModelForCausalLM.from_pretrained(
        args.model, revision=args.revision, quantization_config=bnb, device_map="auto")
    if args.adapter:
        model = PeftModel.from_pretrained(model, args.adapter)
    model.eval()

    for path in sas_files:
        base = os.path.splitext(os.path.basename(path))[0]
        source = open(path).read()
        msgs = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": "```sas\n" + source + "\n```"}]
        ids = tok.apply_chat_template(msgs, add_generation_prompt=True,
                                      return_tensors="pt").to(model.device)

        t0 = time.time()
        with torch.no_grad():
            gen = model.generate(ids, max_new_tokens=args.max_new,
                                 do_sample=False, pad_token_id=tok.eos_token_id)
        elapsed = time.time() - t0

        raw = tok.decode(gen[0][ids.shape[-1]:], skip_special_tokens=True)
        doc_json, parse_err = _parse_json(raw)

        with open(os.path.join(args.out, base + ".raw.txt"), "w") as fh:
            fh.write(raw)
        if doc_json is not None:
            with open(os.path.join(args.out, base + ".pred.json"), "w") as fh:
                json.dump(doc_json, fh, indent=2)
        with open(os.path.join(args.out, base + ".meta.json"), "w") as fh:
            json.dump({"model": args.model, "adapter": args.adapter,
                      "elapsed_sec": round(elapsed, 2),
                      "cost_usd": round(elapsed / 3600.0 * args.gpu_usd_per_hour, 6),
                      "gpu_usd_per_hour": args.gpu_usd_per_hour,
                      "hardware": hardware, "max_new_tokens": args.max_new,
                      "truncated": gen.shape[-1] - ids.shape[-1] >= args.max_new,
                      "parse_error": parse_err}, fh, indent=2)

        print("done", base, "(%.1fs%s)" % (elapsed, ", PARSE ERROR" if parse_err else ""))


if __name__ == "__main__":
    main()
