r"""
run_eval.py
===========
Ties score.py + llm_judge.py + timing/cost metadata into the final results
table (plan section 3's "Results table"):

    rows    = the three configs
    columns = Schema validity, Variable F1, Macro F1, Input/output F1,
              Hallucination rate, Description score, Time per program,
              Cost per program

Expected layout per config (see each config's own script for how these are
produced -- config1's document_sas.py, config2's infer.py, config3's
write_dictionary.py all write this same shape):

    preds/<config>/<program>.pred.json    the JSON output itself
    preds/<config>/<program>.meta.json    {"elapsed_sec": .., "cost_usd": ..}

Run once per config to get its scored + judged rows, then again with --table
to combine everything already computed:

    python3 run_eval.py --config config1-gemma-cpu --gold-dir ../eval-programs/gold \
        --source-dir ../eval-programs/programs --pred-dir preds/config1-gemma-cpu \
        --run-judge --out-prefix outputs/config1_run1

    python3 run_eval.py --table --scores outputs/config1_run*.scores.jsonl \
        --judge outputs/config1_run*.judge.jsonl --meta-dir preds/config1-gemma-cpu \
        --label "Config 1: Gemma 2B, CPU"
"""

import argparse
import glob
import json
import os
import statistics
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import score as score_mod  # noqa: E402
from bootstrap_ci import load_runs, bootstrap_mean_ci  # noqa: E402


def score_and_judge(config, gold_dir, source_dir, pred_dir, out_prefix, run_judge, judge_model):
    scores_path = out_prefix + ".scores.jsonl"
    rows = []
    for gold_path in sorted(glob.glob(os.path.join(gold_dir, "*.gold.json"))):
        base = os.path.basename(gold_path)[: -len(".gold.json")]
        gold = json.load(open(gold_path))
        pred_path = os.path.join(pred_dir, base + ".pred.json")
        source_path = os.path.join(source_dir, base + ".sas")
        pred = json.load(open(pred_path)) if os.path.exists(pred_path) else None
        source_text = open(source_path).read() if os.path.exists(source_path) else ""
        rows.append(score_mod.score_one(gold, pred, source_text))
    with open(scores_path, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    print("[%s] wrote %s (%d programs)" % (config, scores_path, len(rows)))

    judge_path = None
    if run_judge:
        judge_path = out_prefix + ".judge.jsonl"
        subprocess.run([sys.executable, os.path.join(HERE, "llm_judge.py"),
                        "--gold-dir", gold_dir, "--pred-dir", pred_dir,
                        "--model", judge_model, "--out", judge_path], check=True)
    return scores_path, judge_path


def _mean_cost_time(pred_dir):
    times, costs = [], []
    for meta_path in glob.glob(os.path.join(pred_dir, "*.meta.json")):
        meta = json.load(open(meta_path))
        if "elapsed_sec" in meta:
            times.append(meta["elapsed_sec"])
        if "cost_usd" in meta:
            costs.append(meta["cost_usd"])
    t = statistics.mean(times) if times else None
    c = statistics.mean(costs) if costs else None
    return t, c


def build_table(rows):
    """rows: list of {label, scores_patterns, judge_patterns, meta_dir}."""
    header = ("| Config | Schema validity | Variable F1 | Macro F1 | I/O F1 | "
              "Hallucination rate | Description score | Time/program | Cost/program |")
    sep = "|---|---|---|---|---|---|---|---|---|"
    print(header)
    print(sep)
    for row in rows:
        by_program = load_runs(row["scores_patterns"])
        if not by_program:
            print("| %s | (no scores found) | | | | | | | |" % row["label"])
            continue

        def m(metric):
            r = bootstrap_mean_ci(by_program, metric, n_resamples=1000)
            return "%.2f [%.2f, %.2f]" % (r["mean"], r["ci_low"], r["ci_high"])

        desc_score = "n/a"
        if row.get("judge_patterns"):
            scores = []
            for pattern in row["judge_patterns"]:
                for path in glob.glob(pattern):
                    for line in open(path):
                        j = json.loads(line)
                        if j.get("score") is not None:
                            scores.append(j["score"])
            if scores:
                desc_score = "%.2f / 2" % (sum(scores) / len(scores))

        t, c = (None, None)
        if row.get("meta_dir"):
            t, c = _mean_cost_time(row["meta_dir"])
        t_str = "%.1fs" % t if t is not None else "n/a"
        c_str = "$%.4f" % c if c is not None else "$0 (local)"

        print("| %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            row["label"], m("schema_valid"), m("variable_f1"), m("macro_param_f1"),
            m("io_dataset_f1"), m("hallucination_rate"), desc_score, t_str, c_str))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", action="store_true", help="combine already-scored runs into the results table")
    # single-config scoring mode
    ap.add_argument("--config", default=None)
    ap.add_argument("--gold-dir", default="../eval-programs/gold")
    ap.add_argument("--source-dir", default="../eval-programs/programs")
    ap.add_argument("--pred-dir", default=None)
    ap.add_argument("--out-prefix", default=None)
    ap.add_argument("--run-judge", action="store_true")
    ap.add_argument("--judge-model", default="gemma3:1b")
    # table mode
    ap.add_argument("--rows", default=None,
                    help="JSON file: list of {label, scores_patterns, judge_patterns, meta_dir}. "
                         "If omitted in --table mode, pass --scores/--judge/--meta-dir/--label once.")
    ap.add_argument("--scores", nargs="+", default=None)
    ap.add_argument("--judge", nargs="+", default=None)
    ap.add_argument("--meta-dir", default=None)
    ap.add_argument("--label", default=None)
    args = ap.parse_args()

    if args.table:
        if args.rows:
            rows = json.load(open(args.rows))
        else:
            if not (args.scores and args.label):
                sys.exit("--table needs either --rows FILE.json or --scores + --label")
            rows = [{"label": args.label, "scores_patterns": args.scores,
                    "judge_patterns": args.judge, "meta_dir": args.meta_dir}]
        build_table(rows)
    else:
        if not (args.config and args.pred_dir and args.out_prefix):
            sys.exit("scoring mode needs --config --pred-dir --out-prefix")
        score_and_judge(args.config, args.gold_dir, args.source_dir, args.pred_dir,
                        args.out_prefix, args.run_judge, args.judge_model)


if __name__ == "__main__":
    main()
