r"""
generate_training_corpus.py
============================
Thin wrapper around corpus_gen.py (copied into this folder so config2 is
runnable on its own) with defaults set for TRAINING data: a disjoint id
range and seed from eval-programs/'s held-out 20 (id-offset 900), so the
two sets can never collide by construction. Always run check_no_leakage.py
after this, before training, as a second independent guarantee.

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
    args = ap.parse_args()

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

    subprocess.run([sys.executable, os.path.join(HERE, "check_no_leakage.py"),
                    "--train", jsonl_out], check=True)
    print("\ntraining corpus ready at", jsonl_out, "-- verified clean against eval-programs/gold")


if __name__ == "__main__":
    main()
