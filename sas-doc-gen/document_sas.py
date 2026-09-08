r"""
document_sas.py
================
CLI: given a real, arbitrary SAS program, generate documentation + a
best-guess data dictionary using the local gemma3:1b model (Ollama, CPU-only,
already running on this box -- see /internal/e2b-gemma/README.md) with a
few-shot prompt built from seasug-paper's synthetic corpus.

No fine-tuning happens here: this box has no GPU, so the QLoRA training in
seasug-paper/scripts/02_qlora_finetune.py must run on a free Colab T4
instead. This tool gets a usable "best guess" TODAY via in-context learning,
plus a static hallucination guardrail (extract.py + guardrail.py) since there
is no ground-truth spec for a real program the way there is for the
synthetic corpus.

Every run also parses (records.py) and upserts (catalog.py) into a local,
offline JSONL catalog -- program_summary / macro_params / data_dictionary --
keyed by program name. That catalog is what push_to_oda.py later writes to
SAS as real datasets; this script itself never touches SAS/network beyond
Ollama.

Usage:
    python document_sas.py path/to/program.sas
    python document_sas.py path/to/program.sas --fewshot 3 --out out/
    python document_sas.py path/to/program.sas --model gemma3:1b --num-ctx 8192
    python document_sas.py path/to/program.sas --catalog my_catalog/

Batch mode -- every *.sas file in a directory, one program at a time (this
box has no GPU and no request batching, so "batch" means "in sequence, take
a while"; expect ~2-9 min per program per README.md's measured throughput).
A per-file failure (bad file, Ollama hiccup, timeout) is logged and skipped
rather than aborting the run -- meant to be left running unattended:

    python document_sas.py --dir path/to/programs/
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
from prompts import build_messages, load_fewshot
from records import parse_full

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")


def generate(messages, model, num_ctx, num_predict, timeout):
    resp = requests.post(
        "%s/api/chat" % OLLAMA_URL,
        json={
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"num_ctx": num_ctx, "num_predict": num_predict, "temperature": 0.2},
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    body = resp.json()
    return body["message"]["content"], body.get("done_reason")


def process_one(sas_file, args):
    """Document one .sas file. Returns the guardrail report dict (with a
    'truncated' key added) on success. Raises on failure -- callers decide
    whether that should abort a run (single-file mode) or just get logged and
    skipped (batch mode)."""
    source = open(sas_file).read()
    fewshot_kwargs = {"n": args.fewshot}
    if args.corpus:
        fewshot_kwargs["corpus_path"] = args.corpus
    fewshot = load_fewshot(**fewshot_kwargs)
    if args.fewshot and not fewshot:
        print("WARNING: no few-shot exemplars loaded (corpus missing?) -- "
              "falling back to zero-shot.", file=sys.stderr)

    messages = build_messages(source, fewshot)

    t0 = time.time()
    doc, done_reason = generate(messages, args.model, args.num_ctx, args.num_predict, args.timeout)
    elapsed = time.time() - t0

    report = check(doc, source)
    report["truncated"] = (done_reason == "length")

    base = os.path.splitext(os.path.basename(sas_file))[0]
    os.makedirs(args.out, exist_ok=True)
    doc_path = os.path.join(args.out, base + ".doc.md")
    report_path = os.path.join(args.out, base + ".guardrail.json")

    with open(doc_path, "w") as fh:
        fh.write(doc)
    with open(report_path, "w") as fh:
        json.dump(report, fh, indent=2)

    print("model: %s | fewshot: %d | %.1fs" % (args.model, len(fewshot), elapsed))
    print("wrote", doc_path)
    print("wrote", report_path)

    if not args.no_catalog:
        prog_row, macro_rows, dict_rows = parse_full(
            base, doc, report, args.model, source_path=os.path.abspath(sas_file))
        catalog.upsert_program(args.catalog, base, prog_row, macro_rows, dict_rows)
        print("catalog: %s -> %d macro row(s), %d dictionary row(s) (%s)"
              % (args.catalog, len(macro_rows), len(dict_rows), base))

    if report["truncated"]:
        print("\n*** TRUNCATED: response hit --num-predict (%d tokens) before finishing. "
              "Later sections (often Data Dictionary) may be missing entirely -- "
              "re-run with a higher --num-predict. ***" % args.num_predict)
    if report["parse_warning"]:
        print("\n*** GUARDRAIL COULD NOT RUN: %s ***" % report["parse_warning"])
    elif report["n_flagged_vars"] or report["flagged_datasets"] or report["flagged_params"]:
        print("\n*** GUARDRAIL FLAGS (claimed but not found by static scan) ***")
        if report["flagged_datasets"]:
            print("  datasets:", ", ".join(report["flagged_datasets"]))
        if report["flagged_params"]:
            print("  params:  ", ", ".join(report["flagged_params"]))
        if report["flagged_variables"]:
            print("  variables (%d/%d claimed):" % (report["n_flagged_vars"], report["n_claimed_vars"]),
                  ", ".join(report["flagged_variables"]))
        print("These may be real identifiers the regex scan missed, or model "
              "inventions -- check them by hand before trusting the dictionary.")
    else:
        print("no guardrail flags -- all claimed identifiers were found in the source.")

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
            if report["parse_warning"] or report["truncated"] or report["n_flagged_vars"] \
                    or report["flagged_datasets"] or report["flagged_params"]:
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
    ap.add_argument("--fewshot", type=int, default=0,
                    help="number of synthetic-corpus exemplars to prepend. Default 0: "
                         "on this box, gemma3:1b was observed to lose coherence with "
                         "even ONE exemplar in context (fabricated a fictional SAS "
                         "program instead of documenting the real one) -- zero-shot "
                         "was reliably more accurate. Raise this only if testing a "
                         "larger/different model.")
    ap.add_argument("--corpus", default=None,
                    help="override path to seasug-paper train.jsonl")
    ap.add_argument("--num-ctx", type=int, default=8192)
    ap.add_argument("--num-predict", type=int, default=1600,
                    help="cap generation length -- this CPU runs ~4-5 tok/s, so an "
                         "unbounded response can run long")
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--out", default="out")
    ap.add_argument("--catalog", default="catalog",
                    help="local dir accumulating program_summary/macro_params/"
                         "data_dictionary .jsonl across every program you run this "
                         "on. Push to SAS later with push_to_oda.py -- this step "
                         "itself needs no SAS connection.")
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
