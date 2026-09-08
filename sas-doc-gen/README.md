# sas-doc-gen

Generates best-guess documentation + a data dictionary for a real, arbitrary
SAS program, using the local `gemma3:1b` model that's already running on this
box via Ollama (see `/internal/e2b-gemma/README.md`), plus a static-analysis
guardrail against invented variable/dataset names.

This is a *separate, lighter-weight project* from `/internal/seasug-paper/`.
The paper's pipeline QLoRA-fine-tunes a model to do this task well; that
requires a GPU this box does not have (`nvidia-smi`: not found, AMD APU, 4.7 GB
RAM) and can only run on something like a free Colab T4. This tool instead
uses the base model with **zero-shot prompting** to get a usable result today,
with no training step.

## Why zero-shot, not few-shot

The original plan was in-context learning: show the model 1-2 example
(SAS -> doc) pairs from `seasug-paper/scripts/train.jsonl` so it imitates the
target format on a programs it hasn't seen. That was tested and **rejected**:
with even one exemplar in context, `gemma3:1b` lost coherence and fabricated
an entirely fictional SAS program (invented variables/macros/dataset names
that don't exist anywhere in the source or the exemplar) instead of
documenting the real target. Zero-shot, with a much shorter prompt, stayed
coherent and only invented content at the margins (still not zero -- see
Known limitations).

This is a real capability ceiling of a 1B-parameter model, not a prompt bug.
If you want few-shot (or fine-tuned) quality, that means either a bigger
model on beefier hardware, or actually running
`seasug-paper/scripts/02_qlora_finetune.py` on Colab and serving the result
(see "Upgrade path" below). `--fewshot` still exists as a CLI flag in case you
want to re-test it against a different/larger model.

## Usage

```bash
cd /internal/sas-doc-gen
python3 document_sas.py path/to/program.sas
```

Writes `out/<name>.doc.md` and `out/<name>.guardrail.json`. Useful flags:

```bash
--model gemma3:1b       # any model already pulled into this Ollama instance
--num-predict 1600      # generation token cap; raise if TRUNCATED shows up
--num-ctx 4096           # KV-cache size; only needs to exceed prompt+response tokens
--out somedir/
```

### Batch mode

```bash
python3 document_sas.py --dir path/to/programs/
```

Documents every `*.sas` file in the directory, one at a time (no GPU/request
batching here -- "batch" means "in sequence"). A per-file failure (bad file,
Ollama hiccup, timeout) is logged and skipped rather than aborting the whole
run, and a summary (ok/failed/flagged-for-review counts) prints at the end --
meant to be left running unattended overnight against a real codebase.

## Performance on this box (measured, not estimated)

CPU-only, 4 cores, AMD A8-6410 APU:

| stage | throughput |
|---|---|
| prompt processing | ~11 tokens/sec |
| generation | ~4.5 tokens/sec |

A zero-shot doc for a ~1.2 KB SAS program took **~2-5 minutes** wall clock
depending on how much the model writes before stopping. Budget accordingly --
this is a batch/offline tool, not an interactive one, on this hardware.

## The hallucination guardrail

`extract.py` regex-scans the *real* source for dataset names, macro
parameters, and variable-like identifiers (`length`, `input`, `var`, `by`,
`class`, assignments, `proc sql` aliases, etc). `guardrail.py` parses the
model's claimed identifiers out of its generated markdown and flags any that
never appear in that static scan.

This is deliberately conservative in one direction and loose in the other:

- It **will** catch a model naming a dataset/variable that is nowhere in the
  program (confirmed: caught `_Y1`/`_Y2`, two datasets a zero-shot run
  invented that don't exist in the source).
- It will **not** catch the model getting a real identifier's *meaning* or
  *type* wrong (e.g. gemma3:1b called `WGTF` "Work Time" when the synthetic
  spec says it's `weight_final`, a sampling weight -- same literal name,
  wrong inference). Guardrail silence means "no invented names found," not
  "the documentation is correct." Read the dictionary yourself.
- The report includes `parse_warning` (the model ignored the `## Heading`
  format badly enough that nothing could be checked -- do not read a report
  with a warning as "clean") and `truncated` (the response hit
  `--num-predict` before finishing, so whole sections, often the Data
  Dictionary, may be silently missing).

## Persisting to SAS (ODA) as real datasets

Every `document_sas.py` run also parses the doc into three flat record
shapes (`records.py`) and upserts them into a local, offline JSONL catalog
(`catalog.py`, default dir `catalog/`) keyed by program name -- no SAS
connection needed for this step:

- `program_summary` -- one row per program (purpose, macro name, guardrail
  flag counts, truncation/parse-warning status, timestamp).
- `macro_params` -- one row per macro parameter where the model rendered a
  real table; falls back to one free-text row when it didn't (common for
  `gemma3:1b` -- see Known limitations).
- `data_dictionary` -- one row per documented variable, tagged
  `guardrail_flagged` if `guardrail.py` couldn't find it in the source.

`push_to_oda.py` reads that catalog and writes it to SAS OnDemand for
Academics via SASPy as three real datasets (`PROGRAM_SUMMARY`,
`MACRO_PARAMS`, `DATA_DICTIONARY`), replacing them with the catalog's current
full contents each run. Default library is `SASUSER` -- ODA auto-assigns it
per account, and unlike `WORK` it persists across sessions with no extra
setup (no `LIBNAME` statement, no path to know):

```bash
/internal/venvs/main/bin/python3 push_to_oda.py --catalog catalog/
# custom-path library instead of the default SASUSER:
/internal/venvs/main/bin/python3 push_to_oda.py --catalog catalog/ \
    --libname mylib --libpath '/home/youruser/casuser/sasdocgen'
```

**Infrastructure already set up this session, all without sudo:**
- `saspy` installed into the existing `/internal/venvs/main` venv (had
  pandas already).
- A portable Temurin 17 JRE at `sas-doc-gen/jre/` (SASPy's ODA connection
  needs Java; there's no system Java and no sudo on this box).
- `config/sascfg_personal.py`, adapted from `seasug-paper/scripts/
  sascfg_personal.py` (also fixed a typo there: `sascfg_presonal.py` ->
  `sascfg_personal.py`, needed for SASPy's config auto-discovery), pointed at
  the bundled JRE.

**Still needed from you before this can actually connect** (verified missing,
not guessed -- `push_to_oda.py` was run and confirmed it gets exactly this
far and no further):
1. Fill in the `CHANGE ME` `iomhost` list in `config/sascfg_personal.py` for
   your ODA region (US/EU/APAC host names differ).
2. Create `~/.authinfo` yourself (don't paste credentials into a chat
   session): `oda user YOUR_ODA_EMAIL password YOUR_ODA_PASSWORD`, then
   `chmod 600 ~/.authinfo`.

That's it -- the default library (`SASUSER`) needs no further setup or
decision from you; only pass `--libname`/`--libpath` if you specifically want
a different, custom-path library instead.

## Known limitations

- 1B params + no fine-tuning means meanings/types in the dictionary are
  genuinely best-guess and were observed to be wrong even on the toy
  synthetic corpus (right variable, wrong meaning). Treat every entry as
  needing a human check, not just the guardrail-flagged ones.
- `extract.py`'s regex scan is a heuristic on arbitrary real SAS syntax --
  it can miss real identifiers written in forms it doesn't anticipate,
  which would make the guardrail under-flag (report clean when it isn't).
- Few-shot is currently off by default (see above) because it made quality
  *worse*, not better, on this model.

## Upgrade path

If/when `02_qlora_finetune.py` is actually run on a Colab T4 and an adapter
is pushed to Hugging Face:

1. Merge the LoRA adapter into the base weights on Colab (`merge_and_unload`).
2. Convert to GGUF and quantize with llama.cpp (there is no GPU here to run
   the PEFT/bitsandbytes adapter directly).
3. `ollama create sasdoc -f Modelfile` pointing `FROM` the resulting `.gguf`,
   reusing the Ollama install already set up in `/internal/e2b-gemma/`.
4. Point `document_sas.py --model sasdoc` at it and drop `--fewshot` back to
   0 -- a properly fine-tuned model shouldn't need in-context examples at
   all, which sidesteps the coherence problem seen here entirely.

## Files

- `extract.py` -- static identifier scan of a real SAS program.
- `prompts.py` -- system prompt + (currently unused by default) few-shot
  loader from `seasug-paper/scripts/train.jsonl`.
- `guardrail.py` -- parses generated markdown, cross-checks against
  `extract.py`, reports flagged/invented identifiers.
- `records.py` -- turns one doc.md + guardrail report into the three flat
  row shapes used by the catalog / SAS datasets.
- `catalog.py` -- local, offline JSONL accumulation of records.py's output
  across every program you run, upserted per program name.
- `document_sas.py` -- CLI entry point; also updates the local catalog.
- `push_to_oda.py` -- pushes the local catalog to SAS ODA as three real
  datasets via SASPy. Run with `/internal/venvs/main/bin/python3`, not plain
  `python3` (saspy/pandas live in that venv).
- `config/sascfg_personal.py` -- SASPy ODA connection config; still needs
  your region's host list and `~/.authinfo`, see above.
- `jre/` -- portable Temurin 17 JRE (no sudo/system Java needed for SASPy's
  IOM connection to ODA).
