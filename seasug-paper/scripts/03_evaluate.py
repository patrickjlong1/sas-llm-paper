r"""
03_evaluate.py
==============
Scores generated documentation against ground truth WITHOUT an LLM judge.

Five metrics, all machine-checkable, all defensible in a paper:

  dataset_recall      fraction of real output datasets that were documented
  param_recall        fraction of macro parameters documented (name + default)
  variable_recall     fraction of real output variables listed in the dictionary
  hallucination_rate  fraction of documented variables that DO NOT EXIST
  lineage_exact       1.0 if the lineage chain matches the true step order

hallucination_rate is the headline number. It is the one your reviewers and
your agency audience will care about, and it is the one a 3B model fails on.

Ground truth comes from either:
  --truth ../data/eval.jsonl          (the spec that generated the program), or
  --truth ../data/oda_metadata.json   (dictionary.columns harvested from a real
                                       SAS session -- see 04_oda_harvest.py)

Run:
    python 03_evaluate.py --truth ../data/eval.jsonl --pred ../data/preds_tuned.jsonl
    python 03_evaluate.py --truth ../data/eval.jsonl --pred ../data/preds_base.jsonl

--pred is jsonl of {"program_name": ..., "doc": "<model output markdown>"}.
"""

import argparse
import json
import re
from statistics import mean


def parse_doc(md):
    """Pull structured claims out of generated markdown. Deliberately lenient on
    formatting, strict on content."""
    out = {"datasets": set(), "params": set(), "vars": {}, "lineage": []}

    sect = re.split(r"^##\s+", md, flags=re.M)
    for s in sect:
        head = s.split("\n", 1)[0].strip().lower()
        body = s[len(head):]

        if head.startswith("outputs"):
            out["datasets"] |= set(re.findall(r"`([A-Za-z_][\w.]*)`", body))

        elif head.startswith("macro reference"):
            for row in re.findall(r"^\|\s*`?(\w+)`?\s*\|", body, flags=re.M):
                if row.lower() not in ("parameter", "---"):
                    out["params"].add(row.lower())

        elif head.startswith("lineage"):
            out["lineage"] = re.findall(r"_t(\d+)", body)

        elif head.startswith("data dictionary"):
            cur = None
            for line in body.split("\n"):
                m = re.match(r"^###\s+`?(\w+)`?", line)
                if m:
                    cur = m.group(1)
                    out["vars"].setdefault(cur, set())
                    continue
                m = re.match(r"^\|\s*`?(\w+)`?\s*\|", line)
                if m and cur and m.group(1).lower() not in ("variable", "---"):
                    out["vars"][cur].add(m.group(1).upper())
    return out


def truth_from_record(rec):
    spec = rec["spec"]
    return {
        "program_name": spec["program_name"],
        "datasets": {o["member"] for o in spec["outputs"]},
        "params": {p["name"].lower() for p in spec["macro"]["params"]},
        "vars": {o["member"]: {v[1].upper() for v in o["vars"]} for o in spec["outputs"]},
        "lineage": [str(s["n"]) for s in spec["steps"]],
    }


def score(truth, pred):
    dsr = len(truth["datasets"] & pred["datasets"]) / max(1, len(truth["datasets"]))
    prr = len(truth["params"] & pred["params"]) / max(1, len(truth["params"]))

    all_true_vars = set().union(*truth["vars"].values()) if truth["vars"] else set()
    all_pred_vars = set().union(*pred["vars"].values()) if pred["vars"] else set()

    vrec = len(all_true_vars & all_pred_vars) / max(1, len(all_true_vars))
    hall = len(all_pred_vars - all_true_vars) / max(1, len(all_pred_vars))
    lin = 1.0 if pred["lineage"] == truth["lineage"] else 0.0

    return {"dataset_recall": dsr, "param_recall": prr, "variable_recall": vrec,
            "hallucination_rate": hall, "lineage_exact": lin,
            "invented": sorted(all_pred_vars - all_true_vars)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--truth", required=True)
    ap.add_argument("--pred", required=True)
    ap.add_argument("--per-program", action="store_true")
    args = ap.parse_args()

    truths = {}
    for line in open(args.truth):
        rec = json.loads(line)
        if "spec" in rec:
            t = truth_from_record(rec)
        else:                                    # ODA-harvested metadata
            t = rec
        truths[t["program_name"]] = t

    rows = []
    for line in open(args.pred):
        p = json.loads(line)
        t = truths.get(p["program_name"])
        if not t:
            print("no ground truth for", p["program_name"])
            continue
        r = score(t, parse_doc(p["doc"]))
        r["program_name"] = p["program_name"]
        rows.append(r)
        if args.per_program:
            print(json.dumps(r, indent=2))

    keys = ["dataset_recall", "param_recall", "variable_recall",
            "hallucination_rate", "lineage_exact"]
    print("\nn = %d" % len(rows))
    for k in keys:
        print("%-20s %.3f" % (k, mean(r[k] for r in rows)))

    invented = sorted({v for r in rows for v in r["invented"]})
    if invented:
        print("\ninvented identifiers (%d unique): %s"
              % (len(invented), ", ".join(invented[:25])))


if __name__ == "__main__":
    main()
