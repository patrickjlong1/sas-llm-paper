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
        --run-judge --out-prefix outputs/config1-gemma-cpu_run1

    python3 run_eval.py --table --scores outputs/config1-gemma-cpu_run*.scores.jsonl \
        --judge outputs/config1-gemma-cpu_run*.judge.jsonl --meta-dir preds/config1-gemma-cpu \
        --label "Config 1: Gemma 2B, CPU"

    # all three configs in ONE table (a --table call prints its own header,
    # so pass every row at once rather than concatenating separate calls):
    python3 run_eval.py --table --rows rows.example.json

Honesty rules baked into the table (see results/README.md, "Reading the
table honestly"):

  * Every scoring run stamps a <prefix>.provenance.json recording the exact
    eval corpus it scored against. --table re-checks that against what is on
    disk now and marks any row STALE rather than printing numbers that no
    longer refer to the repo's eval set.
  * "Cost/program" distinguishes a measured $0 (local compute) from a cost
    nobody recorded -- it never prints $0 for a metered API model just
    because the field was left null.
  * A timing column where every program reports the identical value is
    flagged as a placeholder rather than presented as a measurement.
  * Coverage (how many of the N programs actually produced parseable output)
    is printed under the table, because a config can score 0.00 either by
    being wrong or by emitting nothing, and those are different findings.
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
import provenance  # noqa: E402
from bootstrap_ci import load_runs, matching_paths, bootstrap_mean_ci  # noqa: E402


def _extra_source_for(extra_source_dir, base):
    """config3/config2 can score against real SAS metadata as an additional
    valid source for the hallucination check (plan section 3: "For config 3,
    PROC CONTENTS output also counts as a valid source"). Accepts either
    <base>.txt (oda_harvest.py's per-program text blob) or <base>.json."""
    if not extra_source_dir:
        return None
    for ext in (".txt", ".json"):
        path = os.path.join(extra_source_dir, base + ext)
        if os.path.exists(path):
            return open(path).read()
    return None


def score_and_judge(config, gold_dir, source_dir, pred_dir, out_prefix, run_judge,
                    judge_model, extra_source_dir=None):
    scores_path = out_prefix + ".scores.jsonl"
    rows = []
    n_extra = 0
    for gold_path in sorted(glob.glob(os.path.join(gold_dir, "*.gold.json"))):
        base = os.path.basename(gold_path)[: -len(".gold.json")]
        gold = json.load(open(gold_path))
        pred_path = os.path.join(pred_dir, base + ".pred.json")
        source_path = os.path.join(source_dir, base + ".sas")
        pred = json.load(open(pred_path)) if os.path.exists(pred_path) else None
        source_text = open(source_path).read() if os.path.exists(source_path) else ""
        extra = _extra_source_for(extra_source_dir, base)
        if extra:
            n_extra += 1
        rows.append(score_mod.score_one(gold, pred, source_text, extra))
    os.makedirs(os.path.dirname(os.path.abspath(scores_path)), exist_ok=True)
    with open(scores_path, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    print("[%s] wrote %s (%d programs)" % (config, scores_path, len(rows)))

    # Stamp what this was scored against, so --table can detect later drift.
    notes = None
    if extra_source_dir:
        notes = ("hallucination check also allowed %d/%d programs' real SAS metadata "
                 "from %s as a valid source" % (n_extra, len(rows), extra_source_dir))
    record = provenance.write(
        provenance.for_scores_path(scores_path),
        provenance.corpus_fingerprint(gold_dir, source_dir),
        predictions=provenance.predictions_fingerprint(pred_dir),
        config=config, notes=notes)
    print("[%s] wrote %s (corpus gold_digest=%s)"
          % (config, provenance.for_scores_path(scores_path),
             record["corpus"]["gold_digest"][:12]))
    if notes:
        print("[%s] %s" % (config, notes))

    judge_path = None
    if run_judge:
        judge_path = out_prefix + ".judge.jsonl"
        subprocess.run([sys.executable, os.path.join(HERE, "llm_judge.py"),
                        "--gold-dir", gold_dir, "--pred-dir", pred_dir,
                        "--model", judge_model, "--out", judge_path], check=True)
    return scores_path, judge_path


def _meta_rows(pred_dir):
    metas = []
    for meta_path in sorted(glob.glob(os.path.join(pred_dir, "*.meta.json"))):
        try:
            metas.append(json.load(open(meta_path)))
        except (OSError, ValueError):
            continue
    return metas


def _time_cell(metas):
    """Mean wall-clock per program, or an honest reason there isn't one."""
    if not metas:
        return "no meta"
    times = [m["elapsed_sec"] for m in metas if m.get("elapsed_sec") is not None]
    if not times:
        return "not recorded"
    mean = statistics.mean(times)
    # A column of identical times is a filled-in placeholder, not a
    # measurement -- config3's hand-authored runs are the usual source.
    if len(times) > 1 and len(set(times)) == 1:
        return "%.1fs (placeholder*)" % mean
    return "%.1fs" % mean


def _cost_cell(metas):
    """Never print $0 for a model nobody metered. 'local' only when the
    config actually recorded a measured zero."""
    if not metas:
        return "no meta"
    costs = [m["cost_usd"] for m in metas if m.get("cost_usd") is not None]
    if not costs:
        return "not recorded*"
    if len(costs) < len(metas):
        return "$%.4f (%d/%d recorded)" % (statistics.mean(costs), len(costs), len(metas))
    if all(c == 0 for c in costs):
        return "$0.00 (local)"
    return "$%.4f" % statistics.mean(costs)


def _coverage(by_program):
    """(n_programs, n_scored_rows, n_with_output, n_schema_valid).

    A 0.00 F1 from 'emitted nothing' and a 0.00 F1 from 'emitted the wrong
    thing' are different findings and the table should not hide which one
    happened. n_scored_rows counts programs x repeated runs, so it exceeds
    n_programs once a config has been run more than once."""
    n_programs = len(by_program)
    no_output = 0
    valid = 0
    total_rows = 0
    for rows in by_program.values():
        for row in rows:
            total_rows += 1
            if row.get("schema_errors") == ["no output produced"]:
                no_output += 1
            if row.get("schema_valid"):
                valid += 1
    return n_programs, total_rows, total_rows - no_output, valid


def build_table(rows, gold_dir=None, source_dir=None):
    """rows: list of {label, scores_patterns, judge_patterns, meta_dir}."""
    gold_dir = gold_dir or os.path.join(HERE, "..", "eval-programs", "gold")
    source_dir = source_dir or os.path.join(HERE, "..", "eval-programs", "programs")
    current = provenance.corpus_fingerprint(gold_dir, source_dir)

    header = ("| Config | Schema validity | Variable F1 | Macro F1 | I/O F1 | "
              "Hallucination rate | Description score | Time/program | Cost/program |")
    sep = "|---|---|---|---|---|---|---|---|---|"
    print("eval corpus on disk: %d gold / %d programs (gold_digest %s)\n"
          % (current["n_gold"], current["n_source"], current["gold_digest"][:12]))
    print(header)
    print(sep)

    footnotes = []
    stale_rows = []
    for row in rows:
        label = row["label"]
        by_program = load_runs(row["scores_patterns"])
        if not by_program:
            print("| %s | (no scores found) | | | | | | | |" % label)
            continue

        # --- is this row still about the corpus that's in the repo? --------
        problems = []
        for path in matching_paths(row["scores_patterns"]):
            for p in provenance.compare(provenance.load_for_scores(path), current):
                problems.append("%s: %s" % (os.path.basename(path), p))
        if problems:
            label = "**STALE** " + label
            stale_rows.append((row["label"], problems))

        def m(metric):
            r = bootstrap_mean_ci(by_program, metric, n_resamples=1000)
            return "%.2f [%.2f, %.2f]" % (r["mean"], r["ci_low"], r["ci_high"])

        desc_score = "not run"
        if row.get("judge_patterns"):
            scores = []
            for pattern in row["judge_patterns"]:
                for path in glob.glob(pattern):
                    for line in open(path):
                        j = json.loads(line)
                        if j.get("score") is not None:
                            scores.append(j["score"])
            desc_score = "%.2f / 2 (n=%d)" % (sum(scores) / len(scores), len(scores)) \
                if scores else "not run"

        metas = _meta_rows(row["meta_dir"]) if row.get("meta_dir") else []
        t_str, c_str = _time_cell(metas), _cost_cell(metas)
        if "placeholder" in t_str or "not recorded" in c_str:
            footnotes.append(row["label"])

        print("| %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            label, m("schema_valid"), m("variable_f1"), m("macro_param_f1"),
            m("io_dataset_f1"), m("hallucination_rate"), desc_score, t_str, c_str))

    # ---- everything the table itself cannot say in a cell -------------------
    print()
    for row in rows:
        by_program = load_runs(row["scores_patterns"])
        if not by_program:
            continue
        n_programs, total_rows, with_output, valid = _coverage(by_program)
        runs_per_program = sorted({len(v) for v in by_program.values()})
        print("%s: %d program(s), %s run(s) each; %d/%d scored outputs parsed as JSON, "
              "%d/%d passed schema.validate()."
              % (row["label"], n_programs, runs_per_program, with_output, total_rows,
                 valid, total_rows))
        if runs_per_program == [1]:
            print("    NOTE: 1 run only. PLAN.md asks for 3 runs per config to separate "
                  "model variance from program difficulty -- the CI below reflects "
                  "program difficulty alone.")

    if footnotes:
        print("\n* Time/cost caveats: a 'placeholder' time means every program in that "
              "run reported the identical elapsed_sec, i.e. it was filled in by hand "
              "rather than measured. 'not recorded' means no meta file carried a "
              "cost_usd -- it is NOT a measured $0. Affected: %s."
              % ", ".join(sorted(set(footnotes))))

    if stale_rows:
        print("\n*** STALE ROWS -- DO NOT PUBLISH THESE NUMBERS ***")
        for label, problems in stale_rows:
            print("  %s" % label)
            for p in problems:
                print("     - %s" % p)
        print("  These were scored against a different eval corpus than the one in "
              "eval-programs/ right now. Re-generate the predictions against the "
              "current corpus and re-run this config's scoring step.")

    print("\nHallucination rate convention: a program that produced no parseable "
          "output is scored 1.00 (worst case), not skipped -- see score.py's "
          "docstring. Check the coverage line above before reading that column as "
          "'the model invented things'.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", action="store_true", help="combine already-scored runs into the results table")
    # single-config scoring mode
    ap.add_argument("--config", default=None)
    ap.add_argument("--gold-dir", default="../eval-programs/gold")
    ap.add_argument("--source-dir", default="../eval-programs/programs")
    ap.add_argument("--pred-dir", default=None)
    ap.add_argument("--extra-source-dir", default=None,
                    help="directory of per-program real-SAS-metadata dumps "
                         "(<program>.txt or .json, e.g. config2's oda_harvest.py "
                         "output or config3's sas_metadata.py output). Counts as a "
                         "valid source for the hallucination check, per plan "
                         "section 3. Recorded in the provenance sidecar so a row "
                         "scored WITH ground truth is never silently compared "
                         "against one scored without it.")
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
            rows_dir = os.path.dirname(os.path.abspath(args.rows))
            for r in rows:
                r["scores_patterns"] = [p if os.path.isabs(p) else os.path.join(rows_dir, p)
                                        for p in r["scores_patterns"]]
                if r.get("judge_patterns"):
                    r["judge_patterns"] = [p if os.path.isabs(p) else os.path.join(rows_dir, p)
                                           for p in r["judge_patterns"]]
                if r.get("meta_dir") and not os.path.isabs(r["meta_dir"]):
                    r["meta_dir"] = os.path.join(rows_dir, r["meta_dir"])
        else:
            if not (args.scores and args.label):
                sys.exit("--table needs either --rows FILE.json or --scores + --label")
            rows = [{"label": args.label, "scores_patterns": args.scores,
                    "judge_patterns": args.judge, "meta_dir": args.meta_dir}]
        build_table(rows, args.gold_dir, args.source_dir)
    else:
        if not (args.config and args.pred_dir and args.out_prefix):
            sys.exit("scoring mode needs --config --pred-dir --out-prefix")
        score_and_judge(args.config, args.gold_dir, args.source_dir, args.pred_dir,
                        args.out_prefix, args.run_judge, args.judge_model,
                        extra_source_dir=args.extra_source_dir)


if __name__ == "__main__":
    main()
