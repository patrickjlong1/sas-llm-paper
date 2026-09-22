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

**Which interpreter runs those two steps.** On this box `saspy` lives in a
separate venv (`/internal/venvs/main`) rather than in the notebook kernel,
which is why the commands below name it explicitly. That path exists
nowhere else, so the notebook detects it instead: it picks the venv when
`import saspy` succeeds there and this notebook's own kernel otherwise.
Off this box, just use whichever interpreter you ran the `pip install`
with. Steps 2-5 and 7 need no saspy at all and run under any interpreter.

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
4. **Run the ground-truth harvest** (needs the interpreter with `saspy`):
   ```bash
   /internal/venvs/main/bin/python3 sas_metadata.py path/to/program.sas --out /tmp/column_metadata.json
   ```
   `config/sascfg_personal.py` resolves `java` itself: the portable JRE
   bundled at the repo root (`../jre/`, shared by every config that talks
   to SAS) when it exists, otherwise whatever `java` is on `PATH`. `jre/`
   is 136 MB and gitignored, so a fresh clone does not have it -- there,
   install a JDK (`apt-get install default-jdk`, or your platform's
   equivalent) and `PATH` resolution takes over. Do NOT hand-build a
   `classpath` in that file: SAS's IOM protocol needs `org.omg.CORBA.*`,
   which the JDK dropped in JEP 320, and saspy's own default classpath
   already carries the back-port.
5. **Push results** (after authoring + validating a dictionary, per the
   skill's steps 4-5):
   ```bash
   /internal/venvs/main/bin/python3 push_to_oda.py --catalog catalog/
   ```
   `push_to_oda.py` mirrors whatever catalog you point it at into SAS, so
   check what is in `catalog/` first. The catalog built before the
   2026-09-21 rewrite of `../eval-programs/` has been moved aside to
   `catalog-stale-2026-09-17/`; pushing that one would put documentation
   for programs that no longer exist into `SASUSER` under the current
   program names.

**Licence note:** ODA is for academic/non-commercial use -- check current
terms before pushing anything work-adjacent there.

## 5. Scoring a config3 run

After step 7 of the skill has written all 20 `.pred.json` files:

```bash
python3 ../results/run_eval.py --config config3-frontier-skills \
    --pred-dir ../results/preds/config3-frontier-skills \
    --out-prefix ../results/outputs/config3-frontier-skills
python3 ../results/run_eval.py --table --rows ../results/rows.example.json
```

Two things config3 in particular has to get right here:

- **`--elapsed-sec` must be measured.** `save_prediction.py` takes it
  per program, and the 2026-09-17 run filled in a flat `90.0` for all 20.
  The table now detects an identical-for-every-program time and prints it
  as `(placeholder*)` instead of as a measurement.
- **Cost is `not recorded`, not `$0`.** An interactive Claude Code session
  has no metered per-call cost, so leaving `--cost-usd` off is correct and
  the table says so. If you drive config3 through the Anthropic API,
  record the real number from the response's usage fields -- the plan asks
  for actual cost, not an estimate.

Scoring writes a `.provenance.json` sidecar recording exactly which eval
corpus was scored, and `--table` marks a row **STALE** rather than
printing numbers that no longer describe the corpus on disk. Config3's own
2026-09-17 run is why: it read `1.00` on every metric, while the same
predictions scored against the current gold read `0.79` variable F1 and
`0.00` macro F1. See `../results/outputs/stale-2026-09-17/README.md`.

Per the plan, also score config3 **twice** -- once with the
`sas_metadata.py` ground truth allowed as a hallucination-check source
(`--extra-source-dir`), once without -- and report the pair, rather than a
single number that silently includes the tool-access advantage.


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
