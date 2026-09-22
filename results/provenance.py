r"""
provenance.py
==============
Makes a `.scores.jsonl` self-describing: what eval corpus it was scored
against, what predictions it scored, and when.

Why this exists: on 2026-09-21 the 20 files in `eval-programs/` were
rewritten by hand (see that folder's README). The `.scores.jsonl` files
already committed in `outputs/` had been produced on 2026-09-17 against the
PREVIOUS corpus, and nothing in the repo said so -- config3's committed row
read "1.00 variable F1" while the same predictions re-scored against the
current gold read 0.79. A results table that silently mixes a new corpus
with old numbers is worse than no table, so every scoring run now drops a
`<prefix>.provenance.json` sidecar, and `run_eval.py --table` refuses to
print a row as clean if that sidecar is missing or no longer matches what's
on disk.

The fingerprint is deliberately dumb and total: sha256 of every gold file
and every .sas file, plus the schema module both sides are validated
against. Any edit to any of them -- reordering a variable, fixing a typo in
a gold label, regenerating the corpus -- changes it.

Usage from Python (run_eval.py does this for you):

    import provenance
    fp = provenance.corpus_fingerprint("../eval-programs/gold",
                                       "../eval-programs/programs")
    provenance.write("outputs/config1.provenance.json", fp,
                     pred_dir="preds/config1-gemma-cpu", config="config1-gemma-cpu")

    rec = provenance.load_for_scores("outputs/config1.scores.jsonl")
    problems = provenance.compare(rec, fp)      # [] means the row is current
"""

import datetime
import glob
import hashlib
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))

PROVENANCE_SUFFIX = ".provenance.json"
_SCORES_SUFFIX = ".scores.jsonl"


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _dir_fingerprint(directory, pattern):
    """{basename: sha256} for every matching file, plus one rolled-up digest
    over the sorted (name, digest) pairs so a single string identifies the
    whole set."""
    files = {}
    for path in sorted(glob.glob(os.path.join(directory, pattern))):
        files[os.path.basename(path)] = _sha256_file(path)
    roll = hashlib.sha256()
    for name in sorted(files):
        roll.update(name.encode())
        roll.update(files[name].encode())
    return files, roll.hexdigest()


def corpus_fingerprint(gold_dir, source_dir):
    """Identifies the eval corpus a score run was computed against."""
    gold_files, gold_digest = _dir_fingerprint(gold_dir, "*.gold.json")
    src_files, src_digest = _dir_fingerprint(source_dir, "*.sas")
    return {
        "gold_dir": os.path.relpath(os.path.abspath(gold_dir), HERE),
        "source_dir": os.path.relpath(os.path.abspath(source_dir), HERE),
        "n_gold": len(gold_files),
        "n_source": len(src_files),
        "gold_digest": gold_digest,
        "source_digest": src_digest,
        "schema_sha256": _sha256_file(os.path.join(HERE, "schema.py")),
        "gold_files": gold_files,
        "source_files": src_files,
    }


def predictions_fingerprint(pred_dir):
    """Identifies the prediction set that was scored. Kept separate from the
    corpus fingerprint: a re-run of the same config against the same corpus
    SHOULD change this and not that."""
    pred_files, pred_digest = _dir_fingerprint(pred_dir, "*.pred.json")
    return {
        "pred_dir": os.path.relpath(os.path.abspath(pred_dir), HERE),
        "n_pred": len(pred_files),
        "pred_digest": pred_digest,
        "pred_files": pred_files,
    }


def for_scores_path(scores_path):
    """outputs/x.scores.jsonl -> outputs/x.provenance.json"""
    if scores_path.endswith(_SCORES_SUFFIX):
        return scores_path[: -len(_SCORES_SUFFIX)] + PROVENANCE_SUFFIX
    return os.path.splitext(scores_path)[0] + PROVENANCE_SUFFIX


def write(path, corpus, predictions=None, config=None, notes=None):
    record = {
        "written_utc": datetime.datetime.now(datetime.timezone.utc)
                               .replace(microsecond=0).isoformat(),
        "config": config,
        "corpus": corpus,
        "predictions": predictions,
        "notes": notes,
    }
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(record, fh, indent=2)
    return record


def load_for_scores(scores_path):
    """Returns the provenance record beside a .scores.jsonl, or None."""
    path = for_scores_path(scores_path)
    if not os.path.exists(path):
        return None
    with open(path) as fh:
        return json.load(fh)


def compare(record, current_corpus):
    """Returns a list of human-readable problems. Empty list == this scores
    file was computed against exactly the corpus that is on disk now."""
    if record is None:
        return ["no %s sidecar -- cannot tell which eval corpus this was scored "
                "against (re-run through run_eval.py to stamp one)" % PROVENANCE_SUFFIX]

    problems = []
    recorded = record.get("corpus") or {}

    if recorded.get("n_gold") != current_corpus["n_gold"]:
        problems.append("gold file count changed: scored against %s, now %s"
                        % (recorded.get("n_gold"), current_corpus["n_gold"]))
    if recorded.get("n_source") != current_corpus["n_source"]:
        problems.append("source file count changed: scored against %s, now %s"
                        % (recorded.get("n_source"), current_corpus["n_source"]))

    if recorded.get("gold_digest") != current_corpus["gold_digest"]:
        changed = _changed_names(recorded.get("gold_files"), current_corpus["gold_files"])
        problems.append("gold/ has changed since this was scored%s" % _suffix(changed))
    if recorded.get("source_digest") != current_corpus["source_digest"]:
        changed = _changed_names(recorded.get("source_files"), current_corpus["source_files"])
        problems.append("programs/ has changed since this was scored%s" % _suffix(changed))
    if recorded.get("schema_sha256") != current_corpus["schema_sha256"]:
        problems.append("results/schema.py has changed since this was scored "
                        "(schema validity may not be comparable)")
    return problems


def _changed_names(old_files, new_files):
    if not isinstance(old_files, dict):
        return []
    names = set(old_files) | set(new_files)
    return sorted(n for n in names if old_files.get(n) != new_files.get(n))


def _suffix(changed):
    if not changed:
        return ""
    shown = ", ".join(changed[:4])
    more = " (+%d more)" % (len(changed) - 4) if len(changed) > 4 else ""
    return ": %s%s" % (shown, more)


def main():
    import argparse
    ap = argparse.ArgumentParser(
        description="Print the current eval corpus fingerprint, or check a "
                    ".scores.jsonl against it.")
    ap.add_argument("--gold-dir", default=os.path.join(HERE, "..", "eval-programs", "gold"))
    ap.add_argument("--source-dir", default=os.path.join(HERE, "..", "eval-programs", "programs"))
    ap.add_argument("--check", nargs="*", default=None,
                    help=".scores.jsonl file(s) to check against the current corpus")
    args = ap.parse_args()

    current = corpus_fingerprint(args.gold_dir, args.source_dir)
    print("current corpus: %d gold / %d source | gold_digest=%s source_digest=%s"
          % (current["n_gold"], current["n_source"],
             current["gold_digest"][:12], current["source_digest"][:12]))

    if args.check is None:
        return
    bad = 0
    for scores_path in args.check:
        problems = compare(load_for_scores(scores_path), current)
        if problems:
            bad += 1
            print("\nSTALE: %s" % scores_path)
            for p in problems:
                print("   - %s" % p)
        else:
            print("\nOK:    %s (scored against the corpus currently on disk)" % scores_path)
    raise SystemExit(1 if bad else 0)


if __name__ == "__main__":
    main()
