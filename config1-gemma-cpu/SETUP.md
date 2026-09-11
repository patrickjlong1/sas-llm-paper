# Config 1 setup: Gemma, CPU-only, zero-shot

This is the floor of the three-config comparison: an off-the-shelf small
open-weight model, no fine-tuning, no tool access, running entirely on
ordinary CPU hardware -- the air-gapped baseline.

## 1. The model runtime (already set up on this box)

The actual model weights + Ollama server live OUTSIDE this folder, at
`/internal/e2b-gemma/` -- that's infrastructure (a 9.6 GB directory of model
blobs and platform binaries), not project code, so it isn't duplicated here.
See `/internal/e2b-gemma/README.md` for the full writeup; short version:

```bash
# start the server (already running on this box -- only needed after a reboot):
nohup /internal/e2b-gemma/serve.sh > /internal/e2b-gemma/server.log 2>&1 &
disown

# confirm it's up:
curl -s http://127.0.0.1:11434/api/version
```

**On a different machine**, install Ollama yourself (no sudo required --
see Ollama's docs for the tarball install) and pull the model:

```bash
ollama pull gemma3:1b
```

That's the entire "model setup" step -- `gemma3:1b` (815 MB, text-only) is
what config1 uses by default. It ran end-to-end on this box's CPU-only
AMD A8-6410 APU, 4.7 GB RAM: ~11 tok/s prompt processing, ~4.5 tok/s
generation, roughly 3-6 minutes per program in JSON mode. Budget accordingly
-- this is a batch/offline tool, not an interactive one, on hardware like
this.

## 2. Python dependencies

```bash
pip install -r requirements.txt
```

Just `requests` for the Ollama HTTP API. The ODA push step needs `saspy` +
`pandas` too (see step 4) -- those are already installed into
`/internal/venvs/main` on this box.

## 3. Run it

```bash
python3 document_sas.py path/to/program.sas
# or, against the whole eval set:
python3 document_sas.py --dir ../eval-programs/programs --out /tmp/config1_out --catalog /tmp/config1_catalog
```

Writes `<name>.pred.json` (the structured dictionary), `<name>.meta.json`
(timing, for the results table), `<name>.raw.txt` (the model's raw response
-- kept even when it fails to parse as JSON, for debugging), and
`<name>.guardrail.json` (hallucination check against the static source
scan) per program.

## 4. Setting up your SAS OnDemand for Academics (ODA) credentials

This step is OPTIONAL -- only needed if you want to push the generated
dictionary into SAS as real datasets (`push_to_oda.py`), or if you want to
harvest ground-truth `dictionary.columns` metadata for a *different* check
than the one config1 actually uses (config1 deliberately has no ground-truth
access -- that's config3's job). Skip this section entirely if you only want
`document_sas.py`'s local JSON/CSV output.

**Get a free ODA account** (if you don't have one): sign up at SAS's
OnDemand for Academics site with an email address -- no cost, academic/
non-commercial use. This gives you a personal cloud SAS session with a
`SASUSER` library that persists across sessions.

**Steps:**

1. **Create `~/.authinfo` yourself** -- do this in your own terminal, don't
   paste credentials into a chat session:
   ```bash
   echo "oda user YOUR_ODA_EMAIL password YOUR_ODA_PASSWORD" >> ~/.authinfo
   chmod 600 ~/.authinfo
   ```
2. **Check your ODA region** matches `config/sascfg_personal.py`'s
   `iomhost` list. It's already filled in for US-region/usw2 (confirmed
   working for the account this was set up under). If your account is a
   different region, find your host names on your ODA dashboard (Support ->
   "SAS OnDemand for Academics" connection info, or the region picker at
   signup) and replace the `iomhost` list -- the three regions SAS publishes
   are:
   - US: `odaws0{1,2,3,4}-usw2.oda.sas.com`
   - Europe: `odaws0{1,2}-euw1.oda.sas.com`
   - Asia Pacific: `odaws0{1,2}-apse1.oda.sas.com`
3. **Run the push** (needs the venv with `saspy` installed):
   ```bash
   /internal/venvs/main/bin/python3 push_to_oda.py --catalog /tmp/config1_catalog
   ```
   Writes `PROGRAM_SUMMARY`, `MACRO_PARAMS`, `DATA_DICTIONARY` into your
   `SASUSER` library (SAS's auto-assigned, persistent-across-sessions
   library -- no `LIBNAME` statement or path to know). Pass `--libname`/
   `--libpath` only if you want a different, custom-path library instead.

No Java install needed -- a portable JRE is already bundled at the repo
root (`../jre/`, shared by every config that talks to SAS) and
`config/sascfg_personal.py` points at it automatically.

**Licence note:** ODA is for academic/non-commercial use -- check current
terms before pushing anything work-adjacent there.

## Why zero-shot, not few-shot or fine-tuned

Tested in-context learning (showing the model 1-2 example SAS->JSON pairs)
here and it made output WORSE, not better: with even one exemplar in
context, `gemma3:1b` lost coherence and fabricated an entirely fictional SAS
program instead of documenting the real one. That's a genuine capability
ceiling of a 1B-parameter model on this task, not a prompt bug -- if you
want few-shot or fine-tuned quality, that's config2
(`../config2-qlora-gpu/`).

## Known limitations (report these honestly in the results)

- Small-model JSON-mode output frequently fails `schema.py`'s structural
  validation outright (missing keys, wrong types, a list entry that's a
  bare string instead of an object). `document_sas.py` does NOT crash on
  this -- it records `schema_valid: false` in the catalog/meta output and
  moves on, exactly so `results/score.py` can report schema validity as its
  own honest metric rather than one bad program aborting a batch run.
- Even when schema-valid, meanings/types are genuinely best-guess and were
  observed wrong on toy synthetic input (e.g. calling a sampling weight
  "Work Time"). The guardrail only catches INVENTED names, never wrong
  MEANINGS -- read every entry, don't just trust an absence of flags.
- `extract.py`'s regex scan is a heuristic on arbitrary real SAS syntax --
  it can miss real identifiers written in forms it doesn't anticipate,
  which under-flags (reports clean when it isn't).
