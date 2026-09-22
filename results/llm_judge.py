r"""
llm_judge.py
============
The one metric in the plan that isn't pure set comparison: scoring free-text
descriptions (program_summary.description, macro purpose, variable
derivation) against the gold version on a 0-2 rubric:

    0 = wrong or misleading
    1 = vague or partially correct
    2 = correct and specific

Judge model: local Ollama (default gemma3:1b, already running in this repo's
config1 for exactly this reason -- see /internal/e2b-gemma/README.md). This
is a DIFFERENT model family from config3 (the frontier model / Claude doing
the actual documentation), which is what the plan requires ("use a different
model family from config3 to avoid self-grading bias"). Swap --model to
anything else you have (a bigger local Gemma, GPT-4o-mini via a different
client, etc.) if you want a stronger judge -- just keep it off the config3
family.

Two run modes:

  --calibrate   Blind-sample ~30 (config, program, field) description pairs
                across all three configs, hide the config label, and print
                them one at a time for YOU to score by hand (plan: "You
                blind-score a random sample of about 30 descriptions").
                Writes your scores next to the judge's own scores of the
                same sample so you can compute agreement before trusting the
                judge on the rest.

  (default)     Score every generated description in a run directory against
                gold, non-interactively, via the judge model.

Usage:
    python3 llm_judge.py --gold-dir ../eval-programs/gold --pred-dir preds/config1-gemma-cpu \
        --out outputs/config1-gemma-cpu_run1.judge.jsonl

    python3 llm_judge.py --gold-dir ../eval-programs/gold \
        --pred-dirs preds/config1-gemma-cpu preds/config2-tuned preds/config3-frontier-skills \
        --calibrate --n 30 --out outputs/calibration_sample.jsonl
"""

import argparse
import glob
import json
import os
import random
import sys

import requests

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")

RUBRIC_PROMPT = """You are grading a short technical description against a reference
("gold") description of the same thing. Score the CANDIDATE on this rubric:

  0 = wrong or misleading (contradicts the gold description, or describes something else)
  1 = vague or partially correct (not wrong, but misses specifics the gold description has)
  2 = correct and specific (captures the same meaning and level of detail as gold)

Gold description:
\"\"\"{gold}\"\"\"

Candidate description:
\"\"\"{cand}\"\"\"

Respond with ONLY a single JSON object: {{"score": 0|1|2, "reason": "<one short sentence>"}}
No markdown fences, no other text.
"""


def judge_one(gold_text, cand_text, model, timeout=120):
    if not cand_text:
        return {"score": 0, "reason": "no candidate text produced"}
    prompt = RUBRIC_PROMPT.format(gold=gold_text, cand=cand_text)
    resp = requests.post(
        "%s/api/chat" % OLLAMA_URL,
        json={"model": model, "messages": [{"role": "user", "content": prompt}],
              "stream": False, "options": {"temperature": 0.0, "num_predict": 200}},
        timeout=timeout,
    )
    resp.raise_for_status()
    text = resp.json()["message"]["content"].strip()
    text = text.strip("`")
    if text.lower().startswith("json"):
        text = text[4:]
    try:
        parsed = json.loads(text)
        score = int(parsed.get("score", 0))
        return {"score": max(0, min(2, score)), "reason": parsed.get("reason", "")}
    except (ValueError, json.JSONDecodeError):
        return {"score": None, "reason": "judge output unparsable: %r" % text[:200]}


def _fields_to_grade(gold, pred):
    """(field_label, gold_text, pred_text) tuples for every free-text field
    the plan asks the judge to score."""
    out = []
    out.append(("program_summary.description",
               gold["program_summary"]["description"],
               (pred or {}).get("program_summary", {}).get("description", "")))
    gold_macros = {m["name"].lower(): m for m in gold["macro_reference"]}
    pred_macros = {m["name"].lower(): m for m in (pred or {}).get("macro_reference", [])}
    for name, gm in gold_macros.items():
        pm = pred_macros.get(name, {})
        out.append(("macro_reference[%s].purpose" % name, gm["purpose"], pm.get("purpose", "")))
    gold_vars = {(v["dataset"].upper(), v["name"].upper()): v for v in gold["variable_dictionary"]}
    pred_vars = {(v.get("dataset", "").upper(), v.get("name", "").upper()): v
                for v in (pred or {}).get("variable_dictionary", [])}
    for key, gv in gold_vars.items():
        pv = pred_vars.get(key, {})
        out.append(("variable_dictionary[%s.%s].derivation" % key, gv["derivation"], pv.get("derivation", "")))
    return out


def run_scoring(gold_dir, pred_dir, model, out_path):
    rows = []
    for gold_path in sorted(glob.glob(os.path.join(gold_dir, "*.gold.json"))):
        base = os.path.basename(gold_path)[: -len(".gold.json")]
        gold = json.load(open(gold_path))
        pred_path = os.path.join(pred_dir, base + ".pred.json")
        pred = json.load(open(pred_path)) if os.path.exists(pred_path) else None

        for field, gold_text, pred_text in _fields_to_grade(gold, pred):
            r = judge_one(gold_text, pred_text, model)
            rows.append({"program_name": base, "field": field, **r})
        print("judged", base)

    with open(out_path, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    scored = [r["score"] for r in rows if r["score"] is not None]
    print("wrote %d row(s) to %s | mean score (of %d parsable): %.2f / 2"
          % (len(rows), out_path, len(scored), (sum(scored) / len(scored)) if scored else 0.0))


def run_calibration(gold_dir, pred_dirs, model, n, out_path, seed=42):
    """Blind sample across configs: pick n (config, program, field) triples,
    strip the config label, and print gold+candidate for a human to score
    alongside the judge -- so you can measure agreement before trusting the
    judge on everything else."""
    rng = random.Random(seed)
    pool = []
    for pred_dir in pred_dirs:
        config_label = os.path.basename(os.path.normpath(pred_dir))
        for gold_path in sorted(glob.glob(os.path.join(gold_dir, "*.gold.json"))):
            base = os.path.basename(gold_path)[: -len(".gold.json")]
            gold = json.load(open(gold_path))
            pred_path = os.path.join(pred_dir, base + ".pred.json")
            pred = json.load(open(pred_path)) if os.path.exists(pred_path) else None
            for field, gold_text, pred_text in _fields_to_grade(gold, pred):
                pool.append({"config": config_label, "program_name": base, "field": field,
                            "gold": gold_text, "candidate": pred_text})

    sample = rng.sample(pool, min(n, len(pool)))
    rng.shuffle(sample)  # blind order -- config label kept in the record but not shown below

    results = []
    for i, item in enumerate(sample, start=1):
        print("\n" + "=" * 70)
        print("[%d/%d] field: %s" % (i, len(sample), item["field"]))
        print("-- gold " + "-" * 60)
        print(item["gold"])
        print("-- candidate " + "-" * 55)
        print(item["candidate"] or "(empty)")
        human = input("Your score (0/1/2, blank to skip): ").strip()
        judge = judge_one(item["gold"], item["candidate"], model)
        results.append({**item, "human_score": int(human) if human else None,
                       "judge_score": judge["score"], "judge_reason": judge["reason"]})

    with open(out_path, "w") as fh:
        for r in results:
            fh.write(json.dumps(r) + "\n")

    scored = [r for r in results if r["human_score"] is not None and r["judge_score"] is not None]
    if scored:
        agree = sum(1 for r in scored if r["human_score"] == r["judge_score"]) / len(scored)
        within1 = sum(1 for r in scored if abs(r["human_score"] - r["judge_score"]) <= 1) / len(scored)
        print("\ncalibration: exact agreement %.0f%%, within-1 agreement %.0f%% (n=%d)"
              % (agree * 100, within1 * 100, len(scored)))
    print("wrote %d row(s) to %s" % (len(results), out_path))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold-dir", required=True)
    ap.add_argument("--pred-dir", default=None)
    ap.add_argument("--pred-dirs", nargs="+", default=None, help="calibration mode only")
    ap.add_argument("--model", default="gemma3:1b",
                    help="judge model -- keep this a DIFFERENT family from config3 "
                         "(the frontier model actually being graded)")
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if args.calibrate:
        if not args.pred_dirs:
            sys.exit("--calibrate needs --pred-dirs (one per config)")
        run_calibration(args.gold_dir, args.pred_dirs, args.model, args.n, args.out)
    else:
        if not args.pred_dir:
            sys.exit("need --pred-dir (or --calibrate --pred-dirs)")
        run_scoring(args.gold_dir, args.pred_dir, args.model, args.out)


if __name__ == "__main__":
    main()
