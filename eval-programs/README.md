# Eval programs: 20 held-out SAS programs + gold JSON

Twenty synthetic-but-realistic legacy SAS programs (`programs/*.sas`), each
with a hand-verifiable "gold" documentation JSON (`gold/*.gold.json`) in the
exact schema every config is prompted for (`schema.py`). This is the
held-out evaluation set every config (`config1-gemma-cpu/`,
`config2-qlora-gpu/`, `config3-frontier-skills/`) is scored against.

## What's deliberately bad about the .sas files (on purpose)

- **No header comments, no inline comments.** Real legacy SAS is frequently
  undocumented -- these match that.
- **Cryptic variable names.** True names are lossy-abbreviated
  (`employment_level` -> `EMPL`, `weight_final` -> `WGTF`) the way real
  shops actually write SAS, not randomly scrambled -- the abbreviation is
  learnable, which is what makes the documentation task meaningful rather
  than impossible.
- **Cryptic macro parameters** (`p`, `lb`, `thr`, `dbg`) with no comments
  explaining them.
- **Bad habits baked in**: `options nomprint nosymbolgen;` (suppresses the
  log detail that would otherwise help a human debug it), hardcoded paths
  and reference periods, `_`-prefixed throwaway intermediate datasets.

## Why the JSON is "perfect"

Both sides (the ugly `.sas` and the gold JSON) are rendered from the SAME
machine-readable spec (`corpus_gen.py`'s `build_spec` -> `render_sas` +
`render_gold`) -- the gold documentation is correct by construction, not
guessed by a human or another model. That's what makes automatic
precision/recall/F1 scoring possible with zero human labeling effort (plan
section 3: "since you're building the 20 gold JSON files, give them exactly
the same schema as the model output... most of the scoring becomes set
comparison in Python").

## Regenerating

```bash
python3 corpus_gen.py --n 20 --seed 777 --id-offset 900 --sas-out programs --gold-out gold
```

**Do not change `--seed` or `--id-offset` casually** -- config2's training
corpus (`../config2-qlora-gpu/generate_training_corpus.py`) reserves the
100-899 id range specifically so it can never collide with this set's
900-919 range. If you regenerate this set with different parameters, also
re-run `../config2-qlora-gpu/check_no_leakage.py` against any existing
training data before training anything on it.

## Files

- `corpus_gen.py` -- the spec generator + both renderers (ugly SAS, gold
  JSON). Canonical copy; identical copies live in `config2-qlora-gpu/` (for
  generating training data with different seed/id-offset) so that folder
  stays runnable on its own.
- `schema.py` -- the JSON schema + validator + the exact prompt text every
  config is given (`PROMPT_SCHEMA_BLOCK`). Canonical copy; identical copies
  live in `config1-gemma-cpu/`, `config2-qlora-gpu/`, `config3-frontier-skills/`,
  and `../results/`.
- `programs/*.sas` -- the 20 held-out programs.
- `gold/*.gold.json` -- the 20 gold documentation files, one per program.
