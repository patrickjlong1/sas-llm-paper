r"""
document_sas.py
================
CLI: given a real, arbitrary SAS program, generate a variable dictionary +
macro reference + program summary as structured JSON (schema.py), using the
local gemma3:1b model (Ollama, CPU-only -- see /internal/e2b-gemma/README.md
and this folder's SETUP.md). Zero-shot: no fine-tuning happens here (that's
config2, which needs a GPU). Ollama's `format: "json"` constrains decoding to
valid JSON syntax, which helps a lot on a 1B model -- schema.py's validate()
still checks the CONTENT shape on top of that.

Every run also parses (records.py) and upserts (catalog.py) into a local,
offline JSONL catalog -- program_summary / macro_params / data_dictionary --
keyed by program name. push_to_oda.py later writes that catalog to SAS as
real datasets; this script itself never touches SAS/network beyond Ollama.

Also writes a `.meta.json` sidecar (elapsed_sec, model, cost_usd=0.0) next to
each `.pred.json`, in the shape results/run_eval.py expects for the "Time
per program" / "Cost per program" columns of the paper's results table.

Usage:
    python document_sas.py path/to/program.sas
    python document_sas.py path/to/program.sas --model gemma3:1b --num-ctx 8192
    python document_sas.py path/to/program.sas --catalog my_catalog/

Batch mode -- every *.sas file in a directory, one program at a time (this
box has no GPU and no request batching, so "batch" means "in sequence, take
a while"; expect a few minutes per program on CPU-only hardware). A per-file
failure (bad file, Ollama hiccup, timeout) is logged and skipped rather than
aborting the run:

    python document_sas.py --dir path/to/programs/ --out out/ --catalog catalog/
"""

import argparse
import glob
import json
import os
import sys
import time

import requests

import catalog
from guardrail import check
from prompts import build_messages
from records import parse_full

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")


def generate(messages, model, num_ctx, num_predict, timeout):
    resp = requests.post(
        "%s/api/chat" % OLLAMA_URL,
        json={
            "model": model,
            "messages": messages,
            "format": "json",   # constrain decoding to valid JSON syntax
            "stream": False,
            "options": {"num_ctx": num_ctx, "num_predict": num_predict, "temperature": 0.2},
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    body = resp.json()
    return body["message"]["content"], body.get("done_reason")


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


def process_one(sas_file, args):
    """Document one .sas file. Returns the guardrail report dict on success.
    Raises on failure -- callers decide whether that should abort a run
    (single-file mode) or just get logged and skipped (batch mode)."""
    source = open(sas_file).read()
    messages = build_messages(source)

    t0 = time.time()
    raw, done_reason = generate(messages, args.model, args.num_ctx, args.num_predict, args.timeout)
    elapsed = time.time() - t0

    doc_json, parse_err = _parse_json(raw)
    report = check(doc_json, source)
    if parse_err:
        report["schema_valid"] = False
        report["schema_errors"] = [parse_err] + report.get("schema_errors", [])
    report["truncated"] = (done_reason == "length")

    base = os.path.splitext(os.path.basename(sas_file))[0]
    os.makedirs(args.out, exist_ok=True)
    raw_path = os.path.join(args.out, base + ".raw.txt")
    pred_path = os.path.join(args.out, base + ".pred.json")
    meta_path = os.path.join(args.out, base + ".meta.json")
    report_path = os.path.join(args.out, base + ".guardrail.json")

    with open(raw_path, "w") as fh:
        fh.write(raw)
    if doc_json is not None:
        with open(pred_path, "w") as fh:
            json.dump(doc_json, fh, indent=2)
    with open(meta_path, "w") as fh:
        json.dump({"model": args.model, "elapsed_sec": round(elapsed, 2), "cost_usd": 0.0,
                  "hardware": "CPU (see this folder's SETUP.md for the measured box)",
                  "truncated": report["truncated"]}, fh, indent=2)
    with open(report_path, "w") as fh:
        json.dump(report, fh, indent=2)

    print("model: %s | %.1fs" % (args.model, elapsed))
    print("wrote", pred_path if doc_json is not None else raw_path, "(raw kept at %s)" % raw_path)
    print("wrote", meta_path)
    print("wrote", report_path)

    if not report["schema_valid"]:
        print("\n*** SCHEMA INVALID: %s ***" % "; ".join(report["schema_errors"][:5]))
    elif report["n_flagged"]:
        print("\n*** GUARDRAIL FLAGS (claimed but not found by static scan): %s ***"
              % ", ".join(report["flagged"]))
        print("These may be real identifiers the regex scan missed, or model "
              "inventions -- check by hand before trusting the dictionary.")
    else:
        print("no guardrail flags -- all claimed identifiers were found in the source.")
    if report["truncated"]:
        print("\n*** TRUNCATED: response hit --num-predict (%d tokens) before finishing. "
              "Re-run with a higher --num-predict. ***" % args.num_predict)

    if not args.no_catalog:
        prog_row, macro_rows, dict_rows = parse_full(
            base, doc_json, report, args.model, source_path=os.path.abspath(sas_file))
        catalog.upsert_program(args.catalog, base, prog_row, macro_rows, dict_rows)
        print("catalog: %s -> %d macro row(s), %d dictionary row(s) (%s)"
              % (args.catalog, len(macro_rows), len(dict_rows), base))

    return report


def run_batch(args):
    files = sorted(glob.glob(os.path.join(args.dir, "*.sas")))
    if not files:
        sys.exit("no .sas files found in %s" % args.dir)

    print("batch: %d file(s) in %s\n" % (len(files), args.dir))
    ok, failed, flagged = [], [], []
    for i, f in enumerate(files, start=1):
        print("=" * 60)
        print("[%d/%d] %s" % (i, len(files), f))
        print("=" * 60)
        try:
            report = process_one(f, args)
            ok.append(f)
            if not report["schema_valid"] or report["n_flagged"] or report.get("truncated"):
                flagged.append(f)
        except Exception as e:
            print("FAILED: %s: %s" % (f, e), file=sys.stderr)
            failed.append(f)
        print()

    print("=" * 60)
    print("batch done: %d ok, %d failed, %d flagged for review"
          % (len(ok), len(failed), len(flagged)))
    if failed:
        print("failed:", ", ".join(failed))
    if flagged:
        print("flagged:", ", ".join(flagged))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sas_file", nargs="?", default=None,
                    help="single .sas file to document. Omit and use --dir instead "
                         "for batch mode.")
    ap.add_argument("--dir", default=None,
                    help="batch mode: document every *.sas file in this directory "
                         "instead of a single file. Continues past per-file failures.")
    ap.add_argument("--model", default="gemma3:1b")
    ap.add_argument("--num-ctx", type=int, default=8192)
    ap.add_argument("--num-predict", type=int, default=1600,
                    help="cap generation length -- this is a CPU-only model, so an "
                         "unbounded response can run long")
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--out", default="out")
    ap.add_argument("--catalog", default="catalog",
                    help="local dir accumulating program_summary/macro_params/"
                         "data_dictionary .jsonl across every program you run this "
                         "on. Push to SAS later with push_to_oda.py.")
    ap.add_argument("--no-catalog", action="store_true", help="skip catalog update")
    args = ap.parse_args()

    if bool(args.sas_file) == bool(args.dir):
        sys.exit("pass exactly one of: a single .sas file, or --dir for batch mode")

    if args.dir:
        run_batch(args)
    else:
        process_one(args.sas_file, args)


if __name__ == "__main__":
    main()
