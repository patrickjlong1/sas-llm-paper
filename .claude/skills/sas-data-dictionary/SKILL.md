---
name: sas-data-dictionary
description: 'Use when asked to build, refresh, or improve a data dictionary or documentation for a real SAS program -- especially poorly-documented legacy SAS with cryptic variable names and no header comments. Produces a frontier-model-authored (Claude-authored) data dictionary, grounded in real SAS metadata pulled via PROC CONTENTS / dictionary.columns / dictionary.tables through saspy, cross-checked against a static source scan, and persisted as real SAS datasets. Triggers on: "SAS data dictionary", "document this SAS program", "what does this SAS code do", "proc contents", "dictionary.columns", "data dictionary from SAS code", or a request to explain/catalog a SAS program''s variables.'
---

# SAS data dictionary (frontier-model version -- Config 3)

Builds a data dictionary + documentation for a real SAS program by having
**you** (not a small local model, and not a fine-tuned one) read the code
and write the dictionary, after gathering real ground truth from SAS itself
-- so your inferences about cryptic legacy variable names stay anchored to
what SAS actually knows about the data, not just what the identifier name
suggests.

This is one of three configs in this project (see the repo root README.md):
Config 1 (`config1-gemma-cpu/`) zero-shot prompts a small local Ollama model
with no tool access; Config 2 (`config2-qlora-gpu/`) QLoRA-fine-tunes that
same base model; this one gives the model (you) real ground-truth tool
access instead of more parameters or training. All three are prompted for
and scored against the exact same JSON schema (`schema.py`, identical copy
in every config folder) -- that's what makes the three-way comparison fair.
State the asymmetry explicitly when reporting results: config 3's advantage
here is tool access, not necessarily model quality.

All scripts referenced below live in `config3-frontier-skills/` in this
repo. Run saspy-dependent ones (`sas_metadata.py`, and the push step) with
`/internal/venvs/main/bin/python3`, not plain `python3` -- that venv has
`saspy`/`pandas` installed, the system interpreter doesn't.

## Output schema

Exactly `config3-frontier-skills/schema.py`'s shape (see that file for the
full field-by-field contract and `PROMPT_SCHEMA_BLOCK` for the prompt text
config1/config2 are also given):

```json
{
  "program_summary": {
    "description": "1-2 plain-English sentences",
    "input_datasets": ["LIBREF.MEMBER", ...],
    "output_datasets": ["LIBREF.MEMBER", ...]
  },
  "macro_reference": [
    {
      "name": "dostep1",
      "positional_params": ["p"],
      "keyword_params": [{"name": "lb", "default": "work"}],
      "purpose": "1 sentence",
      "called_by": ["<program file name(s) that invoke this macro>"]
    }
  ],
  "variable_dictionary": [
    {
      "name": "ESTID",
      "dataset": "LIBREF.MEMBER",
      "type": "char" | "num",
      "length": 12,
      "label": "short label -- use a real SAS LABEL if the code has one",
      "derivation": "1 sentence: how this value is computed or where it comes from"
    }
  ]
}
```

## Workflow

### 1. Gather ground truth from SAS itself

This is the anti-hallucination backbone -- real column names, types,
lengths, formats, informats, and labels, straight from SAS's own
`dictionary.columns`/`dictionary.tables`. Read
`references/sas_dictionary_tables.md` before this step the first time you do
it -- it covers the exact query shape, the `type` 1/2 -> char/num gotcha,
why NOT to default-exclude underscore-prefixed names, and when `--no-run` is
the safer choice.

```bash
/internal/venvs/main/bin/python3 config3-frontier-skills/sas_metadata.py path/to/program.sas \
    --out /tmp/column_metadata.json
```

Needs a working SASPy connection (`config3-frontier-skills/config/
sascfg_personal.py` + `~/.authinfo` -- see `config3-frontier-skills/
SETUP.md`). If genuinely no SAS session is reachable, you can still proceed
to step 4 on the static scan alone, but say so explicitly in the output and
in `program_summary.description` -- the dictionary is meaningfully less
trustworthy without this step, not equally good, and this materially changes
what the hallucination-rate comparison against configs 1/2 means (per the
plan: "for config 3, PROC CONTENTS output also counts as a valid source" --
if you skipped this step, don't claim that source).

If the program hardcodes paths/librefs that won't resolve outside its
original production environment (very common for "poor" legacy code),
expect `run_errors` in the output -- that's fine, harvest whatever DID
materialize rather than treating a partial failure as nothing to document.
If NOTHING materializes and you have reason to believe the target datasets
already exist in a permanent, already-assigned library, retry with
`--no-run --libname <libref>` instead of giving up.

### 2. Gather human-authored context (often nothing -- that's expected)

```bash
python3 config3-frontier-skills/header_extract.py path/to/program.sas
```

Pulls a leading header-comment block's fields (Program/Author/Purpose/
Input/Output/etc, whatever the shop's convention actually used) plus any
inline `/* comment */` glosses sitting on variable-defining lines. Real
legacy SAS is frequently undocumented -- this project's own eval set
(`eval-programs/programs/`) has zero header comments and terse variable
names on purpose, matching what config1/config2 see too.
`header_found: false` is a normal, common result, not a failure. When it IS
found, prefer it over your own inference for the program description, and
treat inline glosses as a strong hint for that specific variable's meaning.

### 3. Gather the static identifier allow-list

```bash
python3 config3-frontier-skills/extract.py path/to/program.sas
```

Regex scan of the source for every dataset/macro-param/variable-like name
that demonstrably appears in the text. This is your fallback allow-list
when ground truth is incomplete, and your ONLY source for macro parameter
names (SAS metadata tables have no concept of those).

### 4. Read the source, then author the dictionary yourself

Read the actual `.sas` file. Combine it with the outputs of steps 1-3 to
write a dictionary JSON matching the schema above (`write_dictionary.py`
expects exactly this shape).

Hard rules while writing this:

- **Never name a dataset, variable, or macro parameter that isn't in the
  ground-truth column metadata OR the static scan.** If you're not sure a
  name is real, grep the source yourself before writing it down.
- **Prefer a real `label` from ground truth over your own guess.** If
  `column_metadata.json` gives a variable a non-empty `label`, that IS the
  documented meaning -- use it verbatim (or lightly cleaned up) as `label`,
  and let `derivation` describe how the value is actually computed/sourced
  in the code (these are two different fields now -- don't conflate "what
  it's called" with "how it's derived").
- **Ground truth beats a name's surface reading.** A variable named `v1`
  with label `"Sampling weight, final"` is a sampling weight, not "value 1"
  -- don't let a terse name pull your inference away from an available
  label. Conversely, an *absent* label plus a terse name (`v1`, `c1`, `s1`)
  means genuinely infer from usage (what it's assigned from, what it's
  summed/compared against, what a downstream step does with it) and say so
  plainly in `derivation` rather than inventing false confidence.
- **`type`, `length`, `label` come from ground truth when you have it** --
  don't re-derive or guess these when `column_metadata.json` already states
  them for that exact variable.
- One `variable_dictionary` row per variable per output dataset that's
  actually a program *output* (written to a permanent library, a report, or
  an external file) -- not every intermediate `_t1`/`_tmp` step. Use
  judgment from reading the code for what counts as an output; ground truth
  won't tell you this, only the code's control flow will.
- `macro_reference[*].positional_params` are parameters with NO default at
  the `%macro name(...)` signature; `keyword_params` are the rest, with
  their literal default as written. `called_by` is every program file name
  that invokes this macro -- for a single self-contained program that's
  just that program's own name.

### 5. Validate, then persist to the local catalog

```bash
python3 config3-frontier-skills/write_dictionary.py \
    --program-name <name> --source path/to/program.sas \
    --dictionary /tmp/dictionary.json \
    --column-metadata /tmp/column_metadata.json \
    --catalog config3-frontier-skills/catalog/
```

This cross-checks every identifier you wrote against ground truth + the
static scan (`validate_dictionary.py`), stamps any misses as
`guardrail_flagged`, and upserts into the local JSONL catalog
(`program_summary` / `macro_params` / `data_dictionary` / `column_metadata`
-- the last one is the ground-truth harvest itself, persisted so it travels
to SAS alongside your inferred dictionary for side-by-side comparison). If
it reports flags, don't just push anyway -- go back and check whether you
mis-typed a real identifier or actually invented one, and fix the JSON
before re-running this step.

### 6. Push to SAS as real datasets

```bash
/internal/venvs/main/bin/python3 config3-frontier-skills/push_to_oda.py --catalog config3-frontier-skills/catalog/
```

Writes/replaces `PROGRAM_SUMMARY`, `MACRO_PARAMS`, `DATA_DICTIONARY`, and
`COLUMN_METADATA` in the target SAS library (default `SASUSER` on ODA --
see `config3-frontier-skills/SETUP.md` for `--libname`/`--libpath` if you
want a different, permanent, custom-path library instead). Each run mirrors
the CURRENT full contents of the local catalog, so this is safe to re-run
after documenting more programs -- it doesn't append duplicates.

### 7. If scoring this run against the eval set

```bash
python3 config3-frontier-skills/save_prediction.py --program-name <name> \
    --dictionary /tmp/dictionary.json --elapsed-sec <how long you took> \
    --out ../results/preds/config3-frontier-skills
```

Drops your authored JSON into the shape `results/score.py` expects (same
`.pred.json`/`.meta.json` layout config1 and config2 write) so it's scored
identically. Record `--elapsed-sec` honestly -- the plan wants wall-clock
time per program for the results table's "time per program" column.

## Batch use

For a whole directory of legacy programs (or the 20-program eval set), loop
steps 1-5 per file yourself (there's no single CLI that does steps 1/4/5
together, since step 4 is you reading and writing, not a subprocess) and run
step 6 once at the end against the accumulated catalog.

## Don't confuse this with config1

`config1-gemma-cpu/document_sas.py` is a separate, independent pipeline
(local Ollama model, JSON-mode prompting, its own regex guardrail, no
ground-truth SAS metadata at all) used to establish the CPU/air-gapped floor
for comparison. Don't mix the two catalogs by hand-editing; they write to
different `catalog/` directories under their own config folders by design,
specifically so config1 and config3 runs never clobber each other.
