r"""
check_no_leakage.py
====================
Enforces the plan's hard constraint on Config 2: "the 20 evaluation programs
must be held out of training entirely, or the scores are meaningless."

Checks --train (generate_training_corpus.py's output) against --eval-gold
(eval-programs/gold/) on TWO signals, since program_name alone isn't a
strong enough guarantee if someone regenerates the corpus with overlapping
--id-offset ranges by mistake:

  1. program_name collision
  2. exact SAS source-text collision (paranoid check -- catches a rename
     that reused the same underlying spec/seed)

Exits non-zero (fails loudly) if either check finds an overlap -- run this
right after generating training data and before kicking off a training job.

Usage:
    python3 check_no_leakage.py --train ../data/train.jsonl --eval-gold ../eval-programs/gold
"""

import argparse
import glob
import hashlib
import json
import os
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", required=True, help="train.jsonl from generate_training_corpus.py")
    ap.add_argument("--eval-gold", default="../eval-programs/gold")
    ap.add_argument("--eval-sas", default="../eval-programs/programs")
    args = ap.parse_args()

    eval_names = {os.path.basename(p)[: -len(".gold.json")] + ".sas"
                 for p in glob.glob(os.path.join(args.eval_gold, "*.gold.json"))}
    if not eval_names:
        sys.exit("*** found 0 eval programs in %r -- this almost certainly means the path "
                 "is wrong (e.g. eval-programs/ wasn't pulled into this session), not that "
                 "there's nothing to check. Refusing to report 'clean' against an empty set. "
                 "Pass --eval-gold to point at the real eval-programs/gold." % args.eval_gold)
    eval_hashes = set()
    for p in glob.glob(os.path.join(args.eval_sas, "*.sas")):
        eval_hashes.add(hashlib.sha256(open(p, "rb").read()).hexdigest())

    name_collisions, hash_collisions = [], []
    with open(args.train) as fh:
        for line in fh:
            rec = json.loads(line)
            name = rec.get("program_name")
            if name in eval_names:
                name_collisions.append(name)
            h = hashlib.sha256(rec["sas"].encode()).hexdigest()
            if h in eval_hashes:
                hash_collisions.append(name)

    if name_collisions or hash_collisions:
        print("*** LEAKAGE DETECTED -- DO NOT TRAIN ON THIS DATA ***")
        if name_collisions:
            print("program_name collisions (%d): %s" % (len(name_collisions), name_collisions[:10]))
        if hash_collisions:
            print("identical-source collisions (%d): %s" % (len(hash_collisions), hash_collisions[:10]))
        sys.exit(1)

    print("no leakage found: %d eval programs, training set clean." % len(eval_names))


if __name__ == "__main__":
    main()
