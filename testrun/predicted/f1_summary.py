r"""Print the F1 summary table from the predicted .scores.jsonl files.

    python3 f1_summary.py            # to the terminal
    python3 f1_summary.py > f1-summary.txt
"""
import json, os, statistics as st

HERE = os.path.dirname(os.path.abspath(__file__))
RUNS = [
    ("Config 1: Gemma CPU zero-shot (4b)",  "config1-gemma-cpu.scores.jsonl"),
    ("Config 1: partial, 12/20 programs",   "config1-gemma-cpu-partial12.scores.jsonl"),
    ("Config 2: base, no adapter",          "config2-base.scores.jsonl"),
    ("Config 2: QLoRA-tuned",               "config2-tuned.scores.jsonl"),
    ("Config 3: Claude + SAS ground truth", "config3/config3-frontier-skills.scores.jsonl"),
    ("Config 3: Claude, --no-sas-tool",     "config3/config3-frontier-skills-nogt.scores.jsonl"),
]
COLS = [("Variable", "variable_f1"), ("Macro param", "macro_param_f1"),
        ("I/O ds", "io_dataset_f1"), ("called_by", "called_by_f1")]

hdr = "%-38s %8s %11s %8s %10s %9s" % ("run", "Variable", "Macro param", "I/O ds", "called_by", "mean F1")
print("F1 summary -- mean over all 20 eval programs")
print("(a program that produced no output scores 0.00)")
print()
print(hdr)
print("-" * len(hdr))
for label, path in RUNS:
    rows = [json.loads(l) for l in open(os.path.join(HERE, path))]
    m = [st.mean(r[k] for r in rows) for _, k in COLS]
    print("%-38s %8.2f %11.2f %8.2f %10.2f %9.2f" % (label, *m, st.mean(m)))
print()
print("Source: testrun/predicted/*.scores.jsonl (predicted runs; see README.md).")
