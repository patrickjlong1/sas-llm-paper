r"""
difficulty_tags.py
===================
Tags each eval program by difficulty (plan section 3: "length, macro count,
nesting depth ... so you can show where the small models break down").
Purely structural, no model calls.

Usage:
    python3 difficulty_tags.py --sas-dir ../eval-programs/programs --out outputs/difficulty.json
"""

import argparse
import glob
import json
import os
import re


def tag_one(text):
    n_lines = len(text.splitlines())
    n_macros = len(re.findall(r"^\s*%macro\s+\w+", text, re.M | re.I))
    n_macro_calls = len(re.findall(r"%\w+\s*\(", text)) - n_macros  # rough: calls minus defs
    n_datasteps = len(re.findall(r"^\s*data\s+\S+\s*;", text, re.M | re.I))
    n_procs = len(re.findall(r"^\s*proc\s+\w+", text, re.M | re.I))

    # nesting depth: max concurrent %do / %if-%then %do blocks
    depth = 0
    max_depth = 0
    for m in re.finditer(r"%do\b|%end\b", text, re.I):
        if m.group(0).lower() == "%do":
            depth += 1
            max_depth = max(max_depth, depth)
        else:
            depth = max(0, depth - 1)

    n_outputs = len(re.findall(r"\bout\s*=\s*\w+", text, re.I)) + len(re.findall(r"^\s*data\s+&\w+\.\.\w+", text, re.M | re.I))

    score = n_lines / 20.0 + n_macros * 2 + max(0, n_macro_calls) * 0.5 + max_depth * 2 + n_procs * 0.5
    if score < 8:
        tier = "easy"
    elif score < 16:
        tier = "medium"
    else:
        tier = "hard"

    return {
        "n_lines": n_lines,
        "n_macros": n_macros,
        "n_macro_calls": max(0, n_macro_calls),
        "n_datasteps": n_datasteps,
        "n_procs": n_procs,
        "max_macro_nesting_depth": max_depth,
        "n_output_refs": n_outputs,
        "difficulty_score": round(score, 2),
        "difficulty_tier": tier,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sas-dir", default="../eval-programs/programs")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    tags = {}
    for path in sorted(glob.glob(os.path.join(args.sas_dir, "*.sas"))):
        name = os.path.basename(path)
        tags[name] = tag_one(open(path).read())

    text = json.dumps(tags, indent=2)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w") as fh:
            fh.write(text)
        print("wrote", args.out)
    else:
        print(text)

    tiers = {}
    for t in tags.values():
        tiers[t["difficulty_tier"]] = tiers.get(t["difficulty_tier"], 0) + 1
    print("tier counts:", tiers)


if __name__ == "__main__":
    main()
