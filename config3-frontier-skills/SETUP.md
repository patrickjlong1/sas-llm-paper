# Config 3 setup: frontier model with skills (using Claude)

Config 3 is the live-demo configuration: instead of more parameters or
training, the model gets **tool access** -- it can run PROC CONTENTS /
query `dictionary.columns` through SASPy to get real types, lengths, and
labels instead of guessing. That's a different axis of improvement from
configs 1 and 2 (model size / fine-tuning), and the plan asks you to state
that asymmetry explicitly rather than present it as "config 3 just has a
smarter model."

## 1. The model: this Claude Code session itself

There is no separate model download or API call to configure for the
*writing* step -- "the frontier model" here is whichever Claude Code (or
Claude via the API) session you're running this skill in. If you're
following this in Claude Code already, skip to step 2.

**If you want to drive this via the Anthropic API instead of Claude Code**
(e.g., to script config3 as a batch job rather than interactively):

1. Get an API key at https://console.anthropic.com (a low-cost pay-as-you-go
   key works fine -- this task is a handful of short requests per program).
2. `export ANTHROPIC_API_KEY=sk-ant-...` in your shell (never paste it into
   a chat session or commit it to this repo).
3. Write a small driver script that sends the SAS source + the ground-truth
   JSON from `sas_metadata.py`/`header_extract.py`/`extract.py` (steps 1-3
   in the skill workflow) to the Messages API with
   `schema.PROMPT_SCHEMA_BLOCK` as part of the system prompt, and saves the
   response via `save_prediction.py`. See `../results/llm_judge.py` for a
   worked example of the request shape (same API, different purpose).
   Record the actual per-call cost from the API response's usage fields for
   the results table's "cost per program" column -- don't estimate it.

## 2. The skill

The actual workflow lives in `.claude/skills/sas-data-dictionary/SKILL.md`
at the **repo root** (not in this folder) -- that's a Claude Code
convention: skills are discovered relative to where the project root is,
not per-subfolder. This folder (`config3-frontier-skills/`) holds the
scripts that skill calls (`sas_metadata.py`, `extract.py`,
`header_extract.py`, `validate_dictionary.py`, `write_dictionary.py`,
`push_to_oda.py`, `save_prediction.py`).

If you're using Claude Code, the skill triggers automatically on requests
like "document this SAS program" or "build a data dictionary for X.sas".
Otherwise, read `SKILL.md` directly and follow its numbered steps by hand.

## 3. Python dependencies

```bash
pip install -r requirements.txt   # saspy + pandas
```

Only needed for steps 1 (`sas_metadata.py`) and 6 (`push_to_oda.py`) of the
skill -- the actual authoring step needs nothing beyond Claude reading the
file.

## 4. Setting up your SAS OnDemand for Academics (ODA) credentials

This is the step config3 benefits from MOST -- it's what supplies the
ground truth (`dictionary.columns`/`dictionary.tables`) that gives config3
its accuracy advantage over configs 1/2. Running config3 without it still
works (falls back to the static source scan only, same as configs 1/2 have),
but then the "tool access" story the plan wants to tell isn't actually
being exercised -- do this step if you want a real config3 result.

1. **Get a free ODA account** if you don't have one: sign up at SAS's
   OnDemand for Academics site -- no cost, academic/non-commercial use.
2. **Create `~/.authinfo` yourself** -- do this in your own terminal, don't
   paste credentials into a chat session:
   ```bash
   echo "oda user YOUR_ODA_EMAIL password YOUR_ODA_PASSWORD" >> ~/.authinfo
   chmod 600 ~/.authinfo
   ```
3. **Check your ODA region** matches `config/sascfg_personal.py`'s
   `iomhost` list -- already filled in for US-region/usw2. If your account
   is Europe or Asia Pacific, replace it (see config1's `SETUP.md` for the
   other two regions' host names, or find yours on your ODA dashboard).
4. **Run the ground-truth harvest** (needs the venv with `saspy`):
   ```bash
   /internal/venvs/main/bin/python3 sas_metadata.py path/to/program.sas --out /tmp/column_metadata.json
   ```
   No Java install needed -- a portable JRE is bundled at the repo root
   (`../jre/`, shared by every config that talks to SAS) and
   `config/sascfg_personal.py` points at it automatically.
5. **Push results** (after authoring + validating a dictionary, per the
   skill's steps 4-5):
   ```bash
   /internal/venvs/main/bin/python3 push_to_oda.py --catalog catalog/
   ```

**Licence note:** ODA is for academic/non-commercial use -- check current
terms before pushing anything work-adjacent there.

## The asymmetry to report honestly

Config 3's PROC CONTENTS / `dictionary.columns` access is real ground truth
the other two configs structurally cannot get (config1 has no SAS
connection at all by design; config2's fine-tuning happens offline, with no
live SAS session at inference time either). If config3 scores much higher
on `type_length_accuracy` or `hallucination_rate`, that may be measuring
"has ground truth" more than "is a better model" -- say so in the writeup,
and consider also reporting a config3-without-ground-truth run (skip step
4, `write_dictionary.py --dictionary ... ` with no `--column-metadata`) as
a fairer isolate of model quality alone.
