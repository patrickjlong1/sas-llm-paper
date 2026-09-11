r"""
score.py
========
Per-program, machine-checkable scoring of one config's JSON output against
the gold JSON for the same program (see eval-programs/schema.py for the
schema both sides follow). No LLM involved here -- see llm_judge.py for the
one metric (free-text description quality) that needs a judge model.

Metrics computed per program (plan section 3):
    schema_valid          bool -- did the output parse and validate at all
    variable_precision/recall/f1     uppercase exact match, keyed by (dataset, name)
    type_length_accuracy  accuracy on TYPE and LENGTH, restricted to matched variables
    macro_param_f1         F1 on macro parameter names (pooled across all macros)
    macro_posk_accuracy    accuracy of positional-vs-keyword classification, on matched params
    macro_default_exact    exact match on defaults (whitespace-normalized), on matched keyword params
    io_dataset_f1           F1 on the union of input_datasets + output_datasets
    called_by_f1            F1 on macro_reference[*].called_by, pooled
    hallucination_rate      fraction of ALL emitted names (vars, datasets, macro names,
                            params, called_by entries) that do not appear anywhere in the
                            source text (or, when given, an extra ground-truth source
                            such as config3's PROC CONTENTS output)

Usage:
    python3 score.py --gold ../eval-programs/gold/prog900_estab.gold.json \
        --pred preds/config1/prog900_estab.pred.json \
        --source ../eval-programs/programs/prog900_estab.sas

    # a whole run directory at once (one *.pred.json per program):
    python3 score.py --gold-dir ../eval-programs/gold --pred-dir preds/config1 \
        --source-dir ../eval-programs/programs --out outputs/config1_run1.scores.jsonl
"""

import argparse
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import schema  # noqa: E402


def _norm_ws(s):
    return re.sub(r"\s+", " ", (s or "").strip())


def _prf1(gold_set, pred_set):
    if not gold_set and not pred_set:
        return 1.0, 1.0, 1.0
    tp = len(gold_set & pred_set)
    precision = tp / len(pred_set) if pred_set else (1.0 if not gold_set else 0.0)
    recall = tp / len(gold_set) if gold_set else (1.0 if not pred_set else 0.0)
    f1 = 0.0 if (precision + recall) == 0 else 2 * precision * recall / (precision + recall)
    return precision, recall, f1


def _var_key(row):
    return ((row.get("dataset") or "").upper(), (row.get("name") or "").upper())


def score_one(gold, pred, source_text, extra_source_text=None):
    result = {"program_name": gold.get("program_name")}

    ok, errors = schema.validate(pred) if pred is not None else (False, ["no output produced"])
    result["schema_valid"] = ok
    result["schema_errors"] = errors[:10]
    if not ok:
        # everything downstream is undefined for an invalid/missing payload --
        # report zeros rather than crash, per plan: "report [schema validity]
        # separately" precisely because small models fail here often.
        zero = dict(result, variable_precision=0.0, variable_recall=0.0, variable_f1=0.0,
                    type_length_accuracy=0.0, macro_param_f1=0.0, macro_posk_accuracy=0.0,
                    macro_default_exact=0.0, io_dataset_f1=0.0, called_by_f1=0.0,
                    hallucination_rate=1.0, n_hallucinated=0, hallucinated=[])
        return zero

    # ---- variable dictionary: precision/recall/F1 by (dataset, name) -------
    gold_vars = {_var_key(v): v for v in gold["variable_dictionary"]}
    pred_vars = {_var_key(v): v for v in pred["variable_dictionary"]}
    vp, vr, vf1 = _prf1(set(gold_vars), set(pred_vars))
    result["variable_precision"] = vp
    result["variable_recall"] = vr
    result["variable_f1"] = vf1

    matched = set(gold_vars) & set(pred_vars)
    correct_type_len = 0
    for k in matched:
        g, p = gold_vars[k], pred_vars[k]
        if g.get("type") == p.get("type") and g.get("length") == p.get("length"):
            correct_type_len += 1
    result["type_length_accuracy"] = (correct_type_len / len(matched)) if matched else 1.0
    result["n_variables_matched"] = len(matched)
    result["n_variables_gold"] = len(gold_vars)

    # ---- macro reference -----------------------------------------------------
    gold_macros = {m["name"].lower(): m for m in gold["macro_reference"]}
    pred_macros = {m["name"].lower(): m for m in pred["macro_reference"]}

    gold_pos = {(mn, p.lower()) for mn, m in gold_macros.items() for p in m.get("positional_params", [])}
    pred_pos = {(mn, p.lower()) for mn, m in pred_macros.items() for p in m.get("positional_params", [])}
    gold_kw = {(mn, kp["name"].lower()): kp.get("default") for mn, m in gold_macros.items()
               for kp in m.get("keyword_params", [])}
    pred_kw = {(mn, kp["name"].lower()): kp.get("default") for mn, m in pred_macros.items()
               for kp in m.get("keyword_params", [])}

    gold_all_params = set(gold_pos) | set(gold_kw)
    pred_all_params = set(pred_pos) | set(pred_kw)
    _, _, param_f1 = _prf1(gold_all_params, pred_all_params)
    result["macro_param_f1"] = param_f1

    matched_params = gold_all_params & pred_all_params
    if matched_params:
        correct_kind = sum(1 for k in matched_params
                           if (k in gold_pos) == (k in pred_pos))
        result["macro_posk_accuracy"] = correct_kind / len(matched_params)
    else:
        result["macro_posk_accuracy"] = 1.0

    matched_kw = set(gold_kw) & set(pred_kw)
    if matched_kw:
        exact = sum(1 for k in matched_kw if _norm_ws(gold_kw[k]) == _norm_ws(pred_kw[k]))
        result["macro_default_exact"] = exact / len(matched_kw)
    else:
        result["macro_default_exact"] = 1.0

    gold_called_by = {(mn, c) for mn, m in gold_macros.items() for c in m.get("called_by", [])}
    pred_called_by = {(mn, c) for mn, m in pred_macros.items() for c in m.get("called_by", [])}
    _, _, called_f1 = _prf1(gold_called_by, pred_called_by)
    result["called_by_f1"] = called_f1

    # ---- I/O datasets ----------------------------------------------------------
    gold_io = {d.upper() for d in gold["program_summary"].get("input_datasets", [])} | \
              {d.upper() for d in gold["program_summary"].get("output_datasets", [])}
    pred_io = {d.upper() for d in pred["program_summary"].get("input_datasets", [])} | \
              {d.upper() for d in pred["program_summary"].get("output_datasets", [])}
    _, _, io_f1 = _prf1(gold_io, pred_io)
    result["io_dataset_f1"] = io_f1

    # ---- hallucination: any emitted name absent from the source text(s) --------
    hay = (source_text or "") + "\n" + (extra_source_text or "")
    hay_upper = hay.upper()

    def in_source(token):
        if not token:
            return True
        return bool(re.search(r"\b%s\b" % re.escape(token.upper()), hay_upper))

    emitted = set()
    for v in pred["variable_dictionary"]:
        emitted.add(("variable", v.get("name", "")))
        emitted.add(("dataset", (v.get("dataset") or "").split(".")[-1]))
    for d in pred["program_summary"].get("input_datasets", []) + pred["program_summary"].get("output_datasets", []):
        emitted.add(("dataset", d.split(".")[-1]))
    for m in pred["macro_reference"]:
        emitted.add(("macro", m.get("name", "")))
        for p in m.get("positional_params", []):
            emitted.add(("param", p))
        for kp in m.get("keyword_params", []):
            emitted.add(("param", kp.get("name", "")))

    hallucinated = sorted("%s:%s" % (kind, name) for kind, name in emitted if name and not in_source(name))
    result["n_emitted_names"] = len(emitted)
    result["n_hallucinated"] = len(hallucinated)
    result["hallucinated"] = hallucinated
    result["hallucination_rate"] = (len(hallucinated) / len(emitted)) if emitted else 0.0

    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold")
    ap.add_argument("--pred")
    ap.add_argument("--source")
    ap.add_argument("--extra-source", default=None,
                    help="e.g. config3's PROC CONTENTS/dictionary.columns dump -- counts as "
                         "a valid source for the hallucination check per plan section 3")
    ap.add_argument("--gold-dir")
    ap.add_argument("--pred-dir")
    ap.add_argument("--source-dir")
    ap.add_argument("--out", default=None, help="write one JSON-lines row per program here")
    args = ap.parse_args()

    rows = []
    if args.gold_dir:
        for gold_path in sorted(glob.glob(os.path.join(args.gold_dir, "*.gold.json"))):
            base = os.path.basename(gold_path)[: -len(".gold.json")]
            gold = json.load(open(gold_path))
            pred_path = os.path.join(args.pred_dir, base + ".pred.json")
            source_path = os.path.join(args.source_dir, base + ".sas")
            pred = json.load(open(pred_path)) if os.path.exists(pred_path) else None
            source_text = open(source_path).read() if os.path.exists(source_path) else ""
            rows.append(score_one(gold, pred, source_text))
    else:
        gold = json.load(open(args.gold))
        pred = json.load(open(args.pred)) if args.pred and os.path.exists(args.pred) else None
        source_text = open(args.source).read() if args.source else ""
        extra = open(args.extra_source).read() if args.extra_source else None
        rows.append(score_one(gold, pred, source_text, extra))

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        print("wrote %d row(s) to %s" % (len(rows), args.out))
    else:
        for r in rows:
            print(json.dumps(r, indent=2))


if __name__ == "__main__":
    main()
