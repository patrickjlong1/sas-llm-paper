r"""
generate_training_corpus.py
============================
Thin wrapper around corpus_gen.py (copied into this folder so config2 is
runnable on its own) with defaults set for TRAINING data: a disjoint id
range and seed from eval-programs/'s held-out 20 (id-offset 900), so the
two sets can never collide by construction. Always run check_no_leakage.py
after this, before training, as a second independent guarantee.

Writes THREE files into --out-dir:

    train.jsonl           what qlora_finetune.py --train reads
    train_holdout.jsonl   what qlora_finetune.py --eval reads: --holdout
                          examples split off the same corpus and REMOVED
                          from train.jsonl, so the eval loss printed each
                          epoch is measured on examples the optimizer never
                          saw. (Without this file qlora_finetune.py falls
                          back to the last 20 rows of the training set,
                          which are in the training set -- an eval curve
                          that cannot show overfitting.) This is a
                          train-time diagnostic only; the real scoring set
                          is eval-programs/, which neither file touches.
    train_sas/, train_gold/   the rendered corpus both jsonl files come from

Usage:
    python3 generate_training_corpus.py --n 600 --out-dir ../data
"""

import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=600)
    ap.add_argument("--seed", type=int, default=20260903)
    ap.add_argument("--id-offset", type=int, default=100,
                    help="disjoint from eval-programs/'s id-offset 900 -- do not change "
                         "this to 900+ or you risk training on the held-out set")
    ap.add_argument("--out-dir", default="../data")
    ap.add_argument("--holdout", type=int, default=20,
                    help="examples split off train.jsonl into train_holdout.jsonl "
                         "for qlora_finetune.py --eval. Held out of training, not "
                         "of scoring -- the scoring set is always eval-programs/.")
    args = ap.parse_args()

    if args.holdout >= args.n:
        sys.exit("--holdout %d must be smaller than --n %d" % (args.holdout, args.n))

    if args.id_offset + args.n > 900:
        sys.exit("id-offset %d + n %d = %d overlaps eval-programs/'s reserved 900-919 range -- "
                 "pick a smaller --n or --id-offset" % (args.id_offset, args.n, args.id_offset + args.n))

    os.makedirs(args.out_dir, exist_ok=True)
    sas_out = os.path.join(args.out_dir, "train_sas")
    gold_out = os.path.join(args.out_dir, "train_gold")
    jsonl_out = os.path.join(args.out_dir, "train.jsonl")

    subprocess.run([sys.executable, os.path.join(HERE, "corpus_gen.py"),
                    "--n", str(args.n), "--seed", str(args.seed), "--id-offset", str(args.id_offset),
                    "--sas-out", sas_out, "--gold-out", gold_out, "--jsonl", jsonl_out], check=True)

    # Split a real holdout OFF the training file, rather than letting
    # qlora_finetune.py fall back to re-using its own last 20 rows as "eval".
    holdout_out = os.path.join(args.out_dir, "train_holdout.jsonl")
    with open(jsonl_out) as fh:
        lines = [l for l in fh if l.strip()]
    train_lines, holdout_lines = lines[: -args.holdout], lines[-args.holdout:]
    with open(jsonl_out, "w") as fh:
        fh.writelines(train_lines)
    with open(holdout_out, "w") as fh:
        fh.writelines(holdout_lines)
    print("split %d train / %d holdout (holdout removed from %s)"
          % (len(train_lines), len(holdout_lines), os.path.basename(jsonl_out)),
          flush=True)

    for path in (jsonl_out, holdout_out):
        subprocess.run([sys.executable, os.path.join(HERE, "check_no_leakage.py"),
                        "--train", path], check=True)
    print("\ntraining corpus ready at", jsonl_out, "(+", holdout_out,
          ") -- verified clean against eval-programs/gold")


if __name__ == "__main__":
    main()
