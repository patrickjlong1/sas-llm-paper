# Config 3 setup: frontier model with skills (using Claude)

Config 3 is the live-demo configuration: instead of more parameters or
training, the model gets **tool access** -- it can run PROC CONTENTS /
query `dictionary.columns` through SASPy to get real types, lengths, and
labels instead of guessing. That's a different axis of improvement from
configs 1 and 2 (model size / fine-tuning), and the plan asks you to state
that asymmetry explicitly rather than present it as "config 3 just has a
smarter model."

## 1. The model: Claude, two ways to drive it

"The frontier model" here is Claude. There are two ways to run it, and they
are the same config -- say which one produced the numbers you report.

### a. Interactively, in a Claude Code session

Nothing to configure: the session you are typing in IS the model. Ask it to
"document `eval-programs/programs/prog900_estab.sas` using the
sas-data-dictionary skill" and the skill triggers, runs the scripts in this
folder, and writes the dictionary JSON. Best for one program you want to
interrogate as it is written. Cost is `not recorded` (an interactive session
has no metered per-call cost -- which is NOT the same as `$0`), and
`--elapsed-sec` is whatever you timed by hand.

### b. Unattended, through the Anthropic API -- `claude_driver.py`

This is what the notebook (`config3_frontier_skills.ipynb`) runs, **on this
box**. Config3 needs no local compute -- the model is remote -- but it does
need a live SASPy/ODA connection and Java for it, and all of that is
already provisioned here:

| need | here |
|---|---|
| `saspy` + `pandas` + `anthropic` | `/internal/venvs/main` |
| Java for SASPy's IOM connection | `../jre/` (portable JDK 17, gitignored) |
| ODA credentials | `~/.authinfo` |
| outputs | in the repo, persistent |

Use that one interpreter for everything, so the driver and the SAS tool it
shells out to agree on what is importable:

```bash
PY=/internal/venvs/main/bin/python3
$PY -m pip install anthropic          # saspy + pandas are already there
```

1. Get an API key at https://console.anthropic.com. This task is a handful
   of short requests per program.
2. `export ANTHROPIC_API_KEY=sk-ant-...` in your shell -- never paste it
   into a chat session or commit it. An `ant auth login` profile also
   works, and the notebook's Setup 2 cell will prompt for the key into the
   kernel's environment if neither is set. The driver checks credentials
   with one free metadata call before the first program, so a missing or
   rejected key fails immediately and bills nothing.
3. Run it:

```bash
# one program, with catalog + scoreable prediction
$PY claude_driver.py ../eval-programs/programs/prog900_estab.sas \
    --catalog catalog/ --preds-out ../results/preds/config3-frontier-skills

# all 20, unattended -- budget ~a minute per program, most of it SAS
$PY claude_driver.py --dir ../eval-programs/programs \
    --catalog catalog/ --preds-out ../results/preds/config3-frontier-skills

# the plan's fairer isolate: same model, ground-truth tool withheld
# (no SAS sessions at all, so much faster)
$PY claude_driver.py --dir ../eval-programs/programs --no-sas-tool \
    --out claude-runs-nogt \
    --preds-out ../results/preds/config3-frontier-skills-nogt
```

**Running it in Colab instead is possible but pointless:** you would
reinstall saspy, `apt-get install default-jdk` (the repo's `jre/` is 136 MB
and gitignored, so a fresh clone lacks it), re-enter the ODA credentials
from the Secrets panel, and zip the outputs off before the runtime
recycles -- in exchange for free compute this config never uses. Colab is
for `config1-gemma-cpu/` (free CPU) and `config2-qlora-gpu/` (free T4).
The notebook's last section lists what to change if you must.

Model is `claude-opus-5` by default (`--model` to change it), with
`output_config.effort` at `high` (`--effort low|medium|high|xhigh|max`).

**Tool access is real, not pre-baked.** The driver gives Claude four tools
and lets it decide when to call them: `sas_column_metadata` (this folder's
`sas_metadata.py` -- SAS's own `dictionary.columns`/`dictionary.tables`),
`header_comments` (`header_extract.py`), `static_identifier_scan`
(`extract.py`), and `grep_source` (regex over the source, so a name can be
checked before it is written). Handing the model a pre-harvested metadata
blob instead would make config3 "a bigger model with a better prompt",
which is precisely the claim `PLAN.md` says not to make.

The prompt's schema contract is `schema.PROMPT_SCHEMA_BLOCK` -- byte for
byte the block configs 1 and 2 get -- plus SKILL.md's step-4 authoring
rules. Decoding is NOT schema-constrained by default: `--structured-output`
will do that, but it makes schema validity trivially 1.00 and so makes that
column measure the harness rather than the model. Declare it if you use it.

What it writes per program:

| path | contents |
|---|---|
| `<out>/<program>.dictionary.json` | the authored dictionary (`schema.py`'s shape) |
| `<out>/<program>.run.json` | api turns, repair turns, tool-call counts, token usage, measured cost |
| `<out>/metadata/<program>.json` | the harvested SAS ground truth, in the layout `run_eval.py --extra-source-dir` reads |

With `--catalog` it then runs `write_dictionary.py` (validation + guardrail
flags + catalog upsert) and with `--preds-out` it runs `save_prediction.py`,
both as subprocesses -- so there is exactly one implementation of those
steps, shared with the interactive path. `elapsed_sec` is measured and
`cost_usd` comes from the API's own usage fields, priced per turn at the
model that actually served it (`PRICES` in `claude_driver.py`, checked
2026-09-22; an unrecognized model id yields a null cost rather than a wrong
one). A per-program failure is logged and skipped, not fatal to the batch.

Two flags worth knowing: `--max-repairs` (default 2) re-asks with the
validation errors when the JSON misses the schema, and records
`repair_turns`; `--no-fallbacks` disables the server-side refusal fallback
if you would rather a policy decline fail loudly than be answered by a
different model (`usage.models_served` records who answered either way).

## 2. The skill

The actual workflow lives in `.claude/skills/sas-data-dictionary/SKILL.md`
at the **repo root** (not in this folder) -- that's a Claude Code
convention: skills are discovered relative to where the project root is,
not per-subfolder. This folder (`config3-frontier-skills/`) holds the
scripts that skill calls (`sas_metadata.py`, `extract.py`,
`header_extract.py`, `validate_dictionary.py`, `write_dictionary.py`,
`push_to_oda.py`, `save_prediction.py`), plus `claude_driver.py`, which
hands a Claude model the first three of those as tools and then runs the
rest itself.

If you're using Claude Code, the skill triggers automatically on requests
like "document this SAS program" or "build a data dictionary for X.sas".
Otherwise, read `SKILL.md` directly and follow its numbered steps by hand.

## 3. Python dependencies

On this box everything runs under one interpreter, the venv that already
has saspy:

```bash
/internal/venvs/main/bin/python3 -m pip install anthropic   # saspy, pandas already present
```

Off this box: `pip install -r requirements.txt` (anthropic + saspy +
pandas) into whichever interpreter you will run the scripts with.

`anthropic` is only for `claude_driver.py` (the API path, section 1b);
`saspy` + `pandas` are only for steps 1 (`sas_metadata.py`) and 6
(`push_to_oda.py`) of the skill. The interactive authoring step needs
neither -- nothing beyond Claude reading the file.

**Which interpreter.** The notebook and `claude_driver.py` both detect it
the same way: `/internal/venvs/main/bin/python3` when `import saspy`
succeeds there, otherwise the current kernel/interpreter
(`claude_driver.py --sas-python` overrides). Steps 2-5 and 7 need no saspy
and run under anything.

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
  the table says so. The API path (`claude_driver.py`) fills both columns
  itself -- `elapsed_sec` measured, `cost_usd` computed per turn from the
  response's own usage fields -- which is the plan's "actual cost, not an
  estimate.

Scoring writes a `.provenance.json` sidecar recording exactly which eval
corpus was scored, and `--table` marks a row **STALE** rather than
printing numbers that no longer describe the corpus on disk. Config3's own
2026-09-17 run is why: it read `1.00` on every metric, while the same
predictions scored against the current gold read `0.79` variable F1 and
`0.00` macro F1. See `../results/outputs/stale-2026-09-17/README.md`.

Per the plan, also score config3 **twice** -- once with the
`sas_metadata.py` ground truth allowed as a hallucination-check source
(`--extra-source-dir`), once without -- and report the pair, rather than a
single number that silently includes the tool-access advantage. The API
path makes the second run a flag: `claude_driver.py --no-sas-tool` simply
does not offer the ground-truth tool, and writes to its own preds
directory so the two can't be pooled by accident. `--extra-source-dir`
reads `<out>/metadata/` from the first run as-is.


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
