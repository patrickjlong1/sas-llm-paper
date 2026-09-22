r"""
bootstrap_ci.py
================
Unit of analysis is the PROGRAM, not the variable (plan section 3: "With 20
programs, the unit of analysis is the program"). Given N per-program score
rows (from score.py, one config/run at a time), reports the mean plus a
bootstrap 95% CI, resampling programs ~1000 times with replacement.

Also supports pooling multiple repeated runs of the SAME config (plan:
"Run each config three times so you can separate model variance from
program difficulty") -- pass --runs run1.jsonl run2.jsonl run3.jsonl and
each bootstrap resample draws one (program, run) pair per program per
resample, so the CI reflects both sources of variance.

Usage:
    python3 bootstrap_ci.py --runs outputs/config1-gemma-cpu_run1.scores.jsonl \
        outputs/config1-gemma-cpu_run2.scores.jsonl outputs/config1-gemma-cpu_run3.scores.jsonl \
        --metric variable_f1
    python3 bootstrap_ci.py --runs outputs/config1-gemma-cpu_run*.scores.jsonl --all-metrics
"""

import argparse
import glob
import json
import os
import random
from statistics import mean

METRICS = ("schema_valid", "variable_f1", "macro_param_f1", "io_dataset_f1",
          "hallucination_rate", "type_length_accuracy", "macro_posk_accuracy",
          "macro_default_exact", "called_by_f1")


def matching_paths(patterns):
    """Expand score-file patterns to real paths.

    A pattern that matches nothing is skipped rather than opened as a literal
    filename -- run_eval.py --table is routinely pointed at a rows.json
    listing all four configs when only some of them have been run yet, and a
    FileNotFoundError traceback there says much less than an empty row."""
    paths = []
    for pattern in patterns or []:
        hits = sorted(glob.glob(pattern))
        if hits:
            paths.extend(hits)
        elif os.path.exists(pattern):
            paths.append(pattern)
    return paths


def load_runs(patterns):
    """Returns {program_name: [row_run1, row_run2, ...]}."""
    by_program = {}
    for path in matching_paths(patterns):
        with open(path) as fh:
            for line in fh:
                if not line.strip():
                    continue
                row = json.loads(line)
                by_program.setdefault(row["program_name"], []).append(row)
    return by_program


def bootstrap_mean_ci(by_program, metric, n_resamples=1000, seed=20260910):
    """Each resample: for each of the N programs, sample a program WITH
    replacement, then sample one of its repeated runs uniformly -- this is
    what lets the interval reflect both program difficulty and model/run
    variance rather than just one or the other."""
    rng = random.Random(seed)
    programs = list(by_program)
    n = len(programs)
    if n == 0:
        return {"mean": None, "ci_low": None, "ci_high": None, "n_programs": 0}

    point = mean(mean(float(row[metric]) for row in by_program[p]) for p in programs)

    resample_means = []
    for _ in range(n_resamples):
        picks = [rng.choice(programs) for _ in range(n)]
        vals = [float(rng.choice(by_program[p])[metric]) for p in picks]
        resample_means.append(mean(vals))
    resample_means.sort()
    lo = resample_means[int(0.025 * n_resamples)]
    hi = resample_means[min(n_resamples - 1, int(0.975 * n_resamples))]

    return {"mean": point, "ci_low": lo, "ci_high": hi, "n_programs": n,
            "n_resamples": n_resamples}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", required=True,
                    help="one or more score.py output files (globs OK) -- pass all "
                         "repeated runs of ONE config to pool run variance into the CI")
    ap.add_argument("--metric", default="variable_f1", choices=METRICS)
    ap.add_argument("--all-metrics", action="store_true")
    ap.add_argument("--n-resamples", type=int, default=1000)
    args = ap.parse_args()

    by_program = load_runs(args.runs)
    if not by_program:
        raise SystemExit("no rows loaded from %s" % args.runs)

    n_runs_per_program = {p: len(rows) for p, rows in by_program.items()}
    print("programs: %d | runs/program: %s" % (len(by_program), sorted(set(n_runs_per_program.values()))))

    metrics = METRICS if args.all_metrics else (args.metric,)
    for m in metrics:
        r = bootstrap_mean_ci(by_program, m, n_resamples=args.n_resamples)
        print("%-24s mean=%.3f  95%% CI [%.3f, %.3f]  (n=%d programs, %d resamples)"
              % (m, r["mean"], r["ci_low"], r["ci_high"], r["n_programs"], r["n_resamples"]))


if __name__ == "__main__":
    main()
