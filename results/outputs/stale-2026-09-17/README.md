# Quarantined: scored against the PRE-REWRITE eval corpus (2026-09-17)

**Do not publish or cite the numbers in this folder.** They are kept only
so the mistake is visible and traceable, not because they are usable.

## What happened

The 20 programs in `eval-programs/` were rewritten by hand on 2026-09-21
(see `eval-programs/README.md`, "Note (2026-09)"): same inputs, derivations
and outputs, but different macros, parameter names, join idioms (PROC SQL
instead of sort+merge) and intermediate datasets, so that config2's
template-generated training corpus could not resemble the eval set.

The `.scores.jsonl` files here were produced on 2026-09-17, four days
*before* that rewrite. The predictions they score
(`../../preds/stale-2026-09-17/`) document programs that no longer exist in
this repo -- e.g. `prog900_estab.pred.json` documents a macro called
`dostep1`, while the current `prog900_estab.gold.json` has `est_report`.

Nothing in the repo recorded which corpus a scores file belonged to, so the
drift was silent. The numbers looked fine:

| what | committed number (stale) | same predictions, current gold |
|---|---|---|
| config3 Variable F1 | 1.00 | 0.79 |
| config3 Macro F1 | 1.00 | 0.00 |
| config3 hallucination rate | 0.00 | 0.14 |

## What changed so it cannot happen silently again

`results/provenance.py` now fingerprints the whole eval corpus (sha256 of
every `gold/*.gold.json` and every `programs/*.sas`, plus `schema.py`), and
every scoring run through `run_eval.py` / `score.py --out` writes a
`<prefix>.provenance.json` sidecar next to its `.scores.jsonl`.
`run_eval.py --table` re-checks that sidecar against what is on disk and
prints the row as `**STALE**` with a per-file diff instead of presenting the
numbers as current.

The two sidecars in this folder were reconstructed after the fact from git
`HEAD` (9b6974d), which still holds the pre-rewrite corpus. That is why
`written_utc` in them is marked approximate. Run:

```bash
cd results
python3 provenance.py --check outputs/stale-2026-09-17/*.scores.jsonl
```

to see the check report them as stale, against the corpus currently on disk.

## To replace these with real numbers

1. Re-generate predictions against the **current** `eval-programs/`:
   - config1: `config1-gemma-cpu/document_sas.py --dir ../eval-programs/programs --out ../results/preds/config1-gemma-cpu ...`
   - config2: `config2-qlora-gpu/infer.py --out ../results/preds/config2-tuned ...`
   - config3: re-author per program via the skill, then `save_prediction.py`
2. Score them: `python3 run_eval.py --config <name> --pred-dir preds/<name> --out-prefix outputs/<name>`
3. Confirm `provenance.py --check outputs/<name>.scores.jsonl` says `OK`.
4. Delete this folder.
