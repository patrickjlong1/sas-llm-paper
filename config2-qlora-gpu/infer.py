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

Truncation, and why it gets three lines of defence
--------------------------------------------------
A run cut off at --max-new stops mid-JSON, `json.loads` fails, no
.pred.json is written, and results/score.py counts the program as "no
output produced" -- 0.00 on every metric and hallucination pinned to 1.00.
That is indistinguishable, in the results table, from a model that had
nothing to say. It is not the same finding at all, and it is what a
2026-09-22 tuned run hit on 15 of 20 programs at the old --max-new 1200:
fine-tuning taught the model to reproduce the training corpus's verbose
gold format, while the eval programs carry MORE variables (12-15) than the
training programs did (7-12), so the JSON ran past the cap.

So, in order:

1. `--max-new` defaults to 2400, not 1200. Generation is streamed-length,
   so an unused budget costs nothing.
2. `--retry-on-truncation` (ON by default) notices the cap was hit and
   re-generates that one program once at `--retry-factor` x the budget.
   The model writes the whole answer itself; nothing is patched.
3. `--salvage-truncated` (OFF by default) closes a still-truncated JSON at
   its last complete element so a mostly-finished dictionary scores as
   partial credit instead of zero. This one is a HARNESS intervention:
   config1 has no equivalent, so turning it on makes the schema-validity
   column incomparable with config1's. Say so if you report it. Salvaged
   predictions are stamped `"salvaged": true` in their .meta.json.

Every one of these is recorded per program, so a row that needed a retry
is never silently equated with one that did not.
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


def _strip_fence(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    return text.strip()


def _parse_json(text):
    try:
        return json.loads(_strip_fence(text)), None
    except json.JSONDecodeError as e:
        return None, str(e)


def _salvage_json(text):
    """Recover the longest valid prefix of a JSON object that was cut off
    mid-generation.

    Walks the text tracking string state and bracket depth, remembers every
    point where a nested value had just closed (so the document could be cut
    there without landing inside a half-written element), then truncates at
    the latest such point, drops a dangling comma and appends the closers the
    bracket stack still needs. Tries progressively earlier cut points until
    one parses.

    Returns (obj, note) or (None, reason). The caller decides whether to use
    it -- this is a repair, not a parse, and it must be recorded as one."""
    s = _strip_fence(text)
    start = s.find("{")
    if start < 0:
        return None, "no JSON object started"
    s = s[start:]

    cuts, stack, in_str, esc = [], [], False, False
    for i, ch in enumerate(s):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if stack:
                stack.pop()
            if stack:                       # a nested value just closed
                cuts.append((i + 1, list(stack)))

    for cut, open_stack in reversed(cuts[-200:]):
        head = s[:cut].rstrip().rstrip(",")
        closers = "".join("}" if b == "{" else "]" for b in reversed(open_stack))
        try:
            return json.loads(head + closers), (
                "salvaged: cut at char %d of %d, closed %d open container(s)"
                % (cut, len(s), len(open_stack)))
        except json.JSONDecodeError:
            continue
    return None, "no cut point produced parseable JSON"


def _generate(model, tok, enc, prompt_len, max_new, tok_eos):
    """One greedy generation. Returns (text, n_new_tokens, hit_cap, seconds)."""
    t0 = time.time()
    with torch.no_grad():
        gen = model.generate(**enc, max_new_tokens=max_new,
                             do_sample=False, pad_token_id=tok_eos)
    elapsed = time.time() - t0
    n_new = gen.shape[-1] - prompt_len
    return (tok.decode(gen[0][prompt_len:], skip_special_tokens=True),
            n_new, n_new >= max_new, elapsed)


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
    ap.add_argument("--max-new", type=int, default=2400,
                    help="generation budget per program. Was 1200, which truncated 15 of "
                         "20 programs on the tuned model (see this module's docstring): "
                         "the fine-tune reproduces the training corpus's verbose gold "
                         "format, and the eval programs have more variables than the "
                         "training ones did. Generation stops at the model's own EOS, so "
                         "headroom you do not use costs nothing.")
    ap.add_argument("--retry-on-truncation", dest="retry_on_truncation",
                    action="store_true", default=True,
                    help="if a program hits the cap, re-generate that one program once at "
                         "--retry-factor x the budget (default: on). The model writes the "
                         "whole answer itself; nothing is patched afterwards, so this "
                         "removes an artifact rather than adding an advantage.")
    ap.add_argument("--no-retry-on-truncation", dest="retry_on_truncation",
                    action="store_false")
    ap.add_argument("--retry-factor", type=float, default=2.0,
                    help="budget multiplier for that one retry.")
    ap.add_argument("--salvage-truncated", action="store_true",
                    help="if the output is STILL truncated after the retry, close the JSON "
                         "at its last complete element so a nearly-finished dictionary "
                         "scores as partial credit instead of as 'no output produced'. OFF "
                         "by default because it is a harness intervention config1 has no "
                         "equivalent of -- turning it on makes the schema-validity column "
                         "incomparable with config1's, so declare it if you report it. "
                         "Salvaged predictions carry \"salvaged\": true in their .meta.json.")
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

    outcomes = []
    for path in sas_files:
        base = os.path.splitext(os.path.basename(path))[0]
        source = open(path).read()
        msgs = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": "```sas\n" + source + "\n```"}]
        enc = tok.apply_chat_template(msgs, add_generation_prompt=True,
                                      return_dict=True,
                                      return_tensors="pt").to(model.device)
        prompt_len = enc["input_ids"].shape[-1]

        budget = args.max_new
        raw, n_new, truncated, elapsed = _generate(model, tok, enc, prompt_len,
                                                   budget, tok.eos_token_id)
        attempts = [{"max_new": budget, "new_tokens": n_new, "truncated": truncated}]
        retried = False

        # 1) The model ran out of room, not out of things to say. Give it more
        #    and let it write the whole answer itself.
        if truncated and args.retry_on_truncation:
            budget = int(budget * args.retry_factor)
            print("   %s hit the %d-token cap -- retrying once at %d"
                  % (base, attempts[0]["max_new"], budget), flush=True)
            raw, n_new, truncated, again = _generate(model, tok, enc, prompt_len,
                                                     budget, tok.eos_token_id)
            elapsed += again
            attempts.append({"max_new": budget, "new_tokens": n_new, "truncated": truncated})
            retried = True

        doc_json, parse_err = _parse_json(raw)

        # 2) Still cut off. Optionally close what it did write, so a
        #    mostly-complete dictionary is not scored as silence.
        salvaged, salvage_note = False, None
        if doc_json is None and truncated and args.salvage_truncated:
            doc_json, salvage_note = _salvage_json(raw)
            salvaged = doc_json is not None
            if salvaged:
                print("   %s: %s" % (base, salvage_note), flush=True)

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
                      "hardware": hardware, "max_new_tokens": budget,
                      "truncated": truncated, "retried_after_truncation": retried,
                      "attempts": attempts, "salvaged": salvaged,
                      "salvage_note": salvage_note,
                      "parse_error": parse_err}, fh, indent=2)

        if doc_json is None:
            status = ", TRUNCATED -- no usable JSON" if truncated else ", PARSE ERROR"
        elif salvaged:
            status = ", TRUNCATED then SALVAGED"
        elif retried:
            status = ", ok after retry"
        else:
            status = ""
        print("done %s (%.1fs, %d tok%s)" % (base, elapsed, n_new, status), flush=True)
        outcomes.append({"program": base, "parsed": doc_json is not None,
                         "truncated": truncated, "retried": retried,
                         "salvaged": salvaged})

    _summarize(outcomes, args)


def _summarize(outcomes, args):
    """A run whose failures are all truncation is a budget problem, not a
    model finding. Say which one this was, before anyone scores it."""
    n = len(outcomes)
    parsed = sum(o["parsed"] for o in outcomes)
    retried = sum(o["retried"] for o in outcomes)
    salvaged = sum(o["salvaged"] for o in outcomes)
    lost = [o["program"] for o in outcomes if not o["parsed"]]
    lost_to_truncation = [o["program"] for o in outcomes
                          if not o["parsed"] and o["truncated"]]

    print("\n%d/%d produced parseable JSON (%d needed the retry, %d salvaged)"
          % (parsed, n, retried, salvaged))
    if lost:
        print("no prediction for: %s" % ", ".join(lost))
        print("  results/score.py counts each of these as 'no output produced': "
              "0.00 on every metric and hallucination pinned to 1.00.")
    if lost_to_truncation:
        print("  %d of them were still TRUNCATED at --max-new %d. Raise it (or add "
              "--salvage-truncated) and re-run those before reading the scores as a "
              "statement about the model." % (len(lost_to_truncation), args.max_new))
    if salvaged:
        print("  %d prediction(s) were SALVAGED from truncated output (--salvage-truncated). "
              "That is a harness repair config1 has no equivalent of -- report it, and do "
              "not compare this run's schema-validity column with config1's." % salvaged)


if __name__ == "__main__":
    main()
