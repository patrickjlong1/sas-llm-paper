r"""
document_sas.py
================
CLI: given a real, arbitrary SAS program, generate a variable dictionary +
macro reference + program summary as structured JSON (schema.py). Zero-shot:
no fine-tuning happens here (that's config2). Two interchangeable backends,
picked with --backend:

- `ollama` (default): the local gemma3:1b/gemma3:4b model served by Ollama
  on THIS box (see /internal/e2b-gemma/README.md and this folder's
  SETUP.md). Ollama's `format: "json"` constrains decoding to valid JSON
  syntax, which helps a lot on a small model.
- `hf`: `transformers` running `google/gemma-3-4b-it` directly, in
  bfloat16, on CPU -- no Ollama server, no /internal/e2b-gemma. This is
  what lets config1 run on a bare Colab CPU runtime using the SAME base
  model config2 fine-tunes, so config1-vs-config2 is a fine-tuning
  comparison rather than a different-model comparison. See this folder's
  SETUP.md, "Running on Colab" section. No JSON-mode decoding constraint
  here (transformers has no equivalent of Ollama's `format: "json"`), so
  expect more schema-invalid output than the `ollama` backend -- schema.py's
  validate() still checks the CONTENT shape either way.

Every run also parses (records.py) and upserts (catalog.py) into a local,
offline JSONL catalog -- program_summary / macro_params / data_dictionary --
keyed by program name. push_to_oda.py later writes that catalog to SAS as
real datasets; this script itself never touches SAS/network beyond Ollama
(the `ollama` backend) or the one-time Hugging Face model download (the
`hf` backend).

Also writes a `.meta.json` sidecar (elapsed_sec, model, cost_usd=0.0) next to
each `.pred.json`, in the shape results/run_eval.py expects for the "Time
per program" / "Cost per program" columns of the paper's results table.

Usage:
    python document_sas.py path/to/program.sas
    python document_sas.py path/to/program.sas --model gemma3:4b --num-ctx 8192
    python document_sas.py path/to/program.sas --catalog my_catalog/
    python document_sas.py path/to/program.sas --backend hf   # Colab, no Ollama

Batch mode -- every *.sas file in a directory, one program at a time (no
GPU, no request batching either backend, so "batch" means "in sequence,
take a while"; expect several minutes per program on CPU-only hardware,
more with --backend hf's larger 4B model -- see SETUP.md for measured
numbers). A per-file failure (bad file, Ollama hiccup, timeout, OOM) is
logged and skipped rather than aborting the run:

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


def _generate_ollama(messages, model, num_ctx, num_predict, timeout):
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


def _generate_hf(messages, model, num_predict, revision, dtype):
    # Imported lazily so the `ollama` backend (this box's default) never
    # needs torch/transformers installed -- see requirements.txt.
    import hf_backend
    return hf_backend.generate(messages, model, num_predict, revision=revision, dtype=dtype)


def generate(messages, args):
    if args.backend == "hf":
        return _generate_hf(messages, args.model, args.num_predict, args.revision, args.dtype)
    return _generate_ollama(messages, args.model, args.num_ctx, args.num_predict, args.timeout)


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
    raw, done_reason = generate(messages, args)
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
        json.dump({"model": args.model, "backend": args.backend,
                  "elapsed_sec": round(elapsed, 2), "cost_usd": 0.0,
                  "hardware": "CPU (Ollama/this box)" if args.backend == "ollama"
                              else "CPU (transformers, dtype=%s -- see SETUP.md's "
                                   "'Running on Colab' section)" % args.dtype,
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

    n_total = len(files)
    if args.limit:
        files = files[: args.limit]
        print("*** --limit %d: documenting %d of %d file(s). This is a PARTIAL run -- "
              "scoring it will count the other %d programs as 'no output produced'. ***\n"
              % (args.limit, len(files), n_total, n_total - len(files)))

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
    ap.add_argument("--backend", choices=("ollama", "hf"), default="ollama",
                    help="'ollama' (default): this box's local Ollama server -- see "
                         "SETUP.md's section 1. 'hf': transformers running "
                         "google/gemma-3-4b-it directly in bfloat16 on CPU, no Ollama "
                         "server needed -- use this on Colab (SETUP.md's 'Running on "
                         "Colab' section), where /internal/e2b-gemma doesn't exist.")
    ap.add_argument("--model", default=None,
                    help="Ollama backend: gemma3:4b is actually a MULTIMODAL checkpoint "
                         "(vision encoder included, not text-only) and was observed to "
                         "time out loading (13m47s, Ollama's own load-timeout killed it) "
                         "on this box's 4.7GB RAM under swap pressure -- see SETUP.md. "
                         "gemma3:1b (this backend's default) is text-only, confirmed "
                         "working here, and is what the timing numbers elsewhere in this "
                         "project were actually measured against; passing gemma3:4b "
                         "yourself restores exact base-model-size parity with config2's "
                         "4B fine-tune, memory permitting. HF backend: defaults to "
                         "google/gemma-3-4b-it, the SAME weights as config2 (gated -- "
                         "needs huggingface-cli login/HF_TOKEN, see SETUP.md); overriding "
                         "this away from that breaks config1-vs-config2 model parity.")
    ap.add_argument("--revision", default="main",
                    help="hf backend only: HF Hub revision of --model.")
    ap.add_argument("--dtype", choices=("auto", "bfloat16", "float32"), default="auto",
                    help="hf backend only. 'auto' (= bfloat16) is what makes the 4B "
                         "default fit free Colab's ~12.7GB CPU RAM at all. 'float32' "
                         "is faster per token on CPUs without AVX512-BF16 (most free "
                         "Colab instances) but only fits a ~1B base -- pair it with "
                         "--model google/gemma-3-1b-it, and say so if you report that "
                         "run, since it breaks base-model parity with config2. "
                         "Ignored by --backend ollama, which serves a GGUF build.")
    ap.add_argument("--num-ctx", type=int, default=8192,
                    help="ollama backend only (context window). Ignored by --backend hf.")
    ap.add_argument("--num-predict", type=int, default=1600,
                    help="cap generation length (max new tokens for both backends) -- "
                         "CPU-only generation, so an unbounded response can run long")
    ap.add_argument("--timeout", type=int, default=900,
                    help="ollama backend only (HTTP request timeout, seconds). Ignored "
                         "by --backend hf, which has no separate request/generate split.")
    ap.add_argument("--out", default="out")
    ap.add_argument("--catalog", default="catalog",
                    help="local dir accumulating program_summary/macro_params/"
                         "data_dictionary .jsonl across every program you run this "
                         "on. Push to SAS later with push_to_oda.py.")
    ap.add_argument("--no-catalog", action="store_true", help="skip catalog update")
    ap.add_argument("--limit", type=int, default=None,
                    help="batch mode: stop after this many .sas files (first N in "
                         "sorted order). For smoke-testing a slow backend before "
                         "committing to all 20 -- a --backend hf run of the 4B model "
                         "on a free Colab CPU is hours per handful of programs, so "
                         "measure one or two first and extrapolate. NOT for producing "
                         "results: results/score.py scores against all 20 gold files "
                         "and counts every missing prediction as a failed program.")
    args = ap.parse_args()

    if args.model is None:
        args.model = "google/gemma-3-4b-it" if args.backend == "hf" else "gemma3:1b"

    if bool(args.sas_file) == bool(args.dir):
        sys.exit("pass exactly one of: a single .sas file, or --dir for batch mode")

    if args.dir:
        run_batch(args)
    else:
        process_one(args.sas_file, args)


if __name__ == "__main__":
    main()
