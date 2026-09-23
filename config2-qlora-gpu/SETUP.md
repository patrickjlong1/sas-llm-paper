# Config 2 setup: QLoRA fine-tune, GPU (free Colab), ODA credentials

Config 2 asks: does a modest fine-tuning run on the SAME base model as
config1 close the gap to the frontier config, while staying air-gapped
(no data leaves the building once trained)? This needs a GPU config1
doesn't have -- a free Colab T4 is enough.

`config2_qlora_gpu.ipynb` in this folder is a runnable copy of this file
and its section numbers match. Everything here runs on Colab, including
section 6.

## 0. Get the whole repo

Sections 3, 5 and 6 read `../eval-programs/` (the held-out 20 + gold) and
`../results/` (`score.py`, `run_eval.py`) as siblings of this folder.
Pull the whole repo, not just this directory -- `npx degit
.../config2-qlora-gpu` and friends leave every `../...` path failing with
"No such file or directory":

```bash
git clone --depth 1 https://github.com/patrickjlong1/sas-llm-paper.git
cd sas-llm-paper/config2-qlora-gpu
```

The notebook's first cell does this automatically when it detects Colab.

## 1. Get a free GPU

**Google Colab (recommended, no cost):**

1. Go to https://colab.research.google.com and sign in with any Google
   account.
2. New notebook -> Runtime -> Change runtime type -> Hardware accelerator:
   **T4 GPU** -> Save. Free tier gives you a T4 (16 GB VRAM) with usage
   limits that reset over time. Note that this corpus needs `--maxlen 4096`
   (section 4), not 2048, and no one has yet run the 4B at that length on a
   free T4 end to end -- if it OOMs, an A100/L4 runtime is the fallback.
3. Either open `config2_qlora_gpu.ipynb` from GitHub (File -> Open
   notebook -> GitHub) or `git clone` as in section 0. Mount Google Drive
   if you want the adapter output to persist across sessions -- Colab's
   local disk is wiped when the runtime recycles.

Everything from section 4 on needs CUDA: QLoRA's 4-bit quantization comes
from `bitsandbytes`, whose kernels are GPU-only. The notebook checks this
before the install rather than after.

Record what the check prints. `torch.cuda.is_bf16_supported()` is **False**
on a free T4, so a run reporting True was on something bigger -- that one
line is the difference between an honest and a misleading hardware claim.

**Alternatives if Colab's free tier is unavailable/rate-limited:**

- **Kaggle Notebooks** -- free 30 hrs/week of a P100 or T4x2 GPU, similar
  workflow (Settings -> Accelerator -> GPU).
- **Lightning AI Studios** -- free tier includes some GPU hours.
- Any of these work the same way: install the requirements, generate the
  training data, run the two scripts below.

## 2. Install dependencies (in the Colab/Kaggle session, one cell)

```bash
!pip -q install -r requirements.txt
```

`trl>=0.24` is a hard floor, not just a version bump -- `qlora_finetune.py`
uses the current `trl` API (`SFTConfig` + `assistant_only_loss` over a
`"messages"`-shaped dataset). See `requirements.txt` for why pinning `trl`
low is not an option on this Python.

## 3. Generate training data (disjoint from the 20 held-out eval programs)

```bash
python3 generate_training_corpus.py --n 600 --out-dir ../data
```

A synthetic corpus from `corpus_gen.py` with a disjoint seed and id range
from `eval-programs/` (which reserves ids 900-919). It automatically runs
`check_no_leakage.py` at the end -- on program name *and* on exact
source-text hash -- and refuses to proceed on any overlap. **This is the
plan's hard constraint: never point `--train` at anything derived from
`eval-programs/` -- the scores are meaningless if you do.**

It writes two jsonl files:

- `../data/train.jsonl` -- what `--train` reads.
- `../data/train_holdout.jsonl` -- 20 examples split OFF the training set
  (`--holdout N` to change) for `--eval`, so the eval loss printed at each
  epoch is measured on examples the optimizer never saw. Without it,
  `qlora_finetune.py` falls back to the last 20 rows of the *training* set
  and says so loudly, because that eval curve cannot show overfitting.
  Either way this is a training diagnostic only; the scoring set is always
  `../eval-programs/`.

If you have real (non-synthetic) internal SAS programs with existing
documentation, those make better training pairs than the synthetic corpus
-- format them as `{"program_name":..., "sas":..., "gold": {...schema.py
shape...}}` per line in a `.jsonl` and pass that as `--train` instead.

**What the eval set is deliberately not measuring.** Since 2026-09-21 the
20 `eval-programs/` files are hand-rewritten rather than `corpus_gen.py`
output (see `../eval-programs/README.md`): different macros, parameter
names, join idioms and intermediate datasets from the templates this
training corpus renders. So config2 is tested out-of-*template*, not just
out-of-sample. That is the harder and more honest test, and a
template-trained adapter may transfer less well than a same-template
holdout would suggest -- report that gap as a finding rather than a bug.

## 4. Fine-tune

```bash
python3 qlora_finetune.py --train ../data/train.jsonl \
    --eval ../data/train_holdout.jsonl \
    --model google/gemma-3-4b-it --maxlen 4096 --epochs 2 \
    --out ../adapters/sasdoc-lora
```

**`--maxlen 4096` is the floor for this corpus, and it is load-bearing.**
One training example is the schema block + a SAS program + its indented gold
JSON, which measures ~2400-2800 tokens -- so *not one example* fits in 2048.
Both halves of that have already bitten this repo:

* Before the length filter was fixed it compared `len()` of a `BatchEncoding`
  (i.e. `2`) against `maxlen` and so never fired, and every example trained
  **truncated** at 2048 -- each target cut off mid-dictionary, exactly what
  the filter existed to prevent. The 2026-09-21 adapter is from such a run.
* With the filter working, `--maxlen 2048` dropped 579/580 training examples
  and all 20 holdout examples, and the run died on
  `StopIteration` in `trl/trainer/sft_trainer.py::_prepare_dataset`, which is
  just `next(iter(dataset))` over the now-empty eval set.

`qlora_finetune.py` now prints measured token `p50/p90/p99/max` for each
split, exits with an explicit message (naming the `--maxlen` to use) if more
than 20% of the training corpus does not fit, and passes `eval_dataset=None`
with `eval_strategy="no"` rather than handing trl an empty dataset. Raise
`--maxlen`, don't lower it: if it OOMs, drop
`per_device_train_batch_size` or raise `gradient_accumulation_steps` instead.

`google/gemma-3-4b-it` is Gemma weights on Hugging Face and is **gated** --
you must (a) accept the license on the model's HF page while logged in, and
(b) run `huggingface-cli login` (or set the `HF_TOKEN` secret in Colab)
before this will download. Keep the base model matched to config1's
`--backend hf` default (the same repo id) -- that's what makes "config1 vs
config2" a fine-tuning comparison rather than a different-model comparison.

**Do not use `google/gemma-4-E2B-it`** even though the name reads like a
small model -- that's Google's Gemma 3n E2B, a *multimodal* checkpoint that
bundles vision + audio encoders (10+ GB of weights). QLoRA's 4-bit
quantization mostly skips those encoders, and `prepare_model_for_kbit_training`
upcasting them to fp32 has been observed to blow past a free T4's VRAM
(`CUDA out of memory` inside `prepare_model_for_kbit_training`). This
project's own `/internal/e2b-gemma/README.md` independently hit the same
model failing to even load on CPU, for the same reason. `gemma-3-4b-it` is
Google's actual text-only 4B Gemma 3 and is what this script is built for.

**Runtime, and what has actually been measured.** On a free T4 with
`gemma-3-1b-it`: ~50s/optimizer-step observed, 150 steps total (600
examples / effective batch 8 / 2 epochs), so **1.5-2.5 hours** -- the
30-90 min in earlier drafts of this doc was optimistic. For
`gemma-3-4b-it` (the current default) an adapter has been trained once,
on 2026-09-21: `../adapters/sasdoc-lora/run_config.json` records
`maxlen=2048, epochs=2, lr=2e-4, bf16=true`. **That `maxlen=2048` means it
was trained on truncated targets (see above) -- retrain it at `--maxlen 4096`
before any of its scores go in the paper.** `bf16=true` comes from
`torch.cuda.is_bf16_supported()`, which is False on a T4 -- so **that run
was not on a free T4, and neither its GPU nor its wall clock was
recorded**. There is still no T4 end-to-end number for the 4B. Record
yours, and note it is a **one-time training cost**, separate from the
per-program inference cost in the results table (plan: "cost per program"
is about *running* the model, not training it).

`requirements.txt` only pins a floor (`trl>=0.24`), and `trl`'s `SFTConfig`
has shed/renamed fields across releases -- if you see
`WARNING: this trl's SFTConfig does not accept: <field> -- using its
defaults for them` at startup, that's expected and non-fatal (the script
filters its kwargs against whatever `SFTConfig` your resolved `trl` actually
has); only worth a second look if the dropped field is one you specifically
need control over (e.g. `assistant_only_loss` itself).

Colab's local disk does **not** survive a runtime recycle, and the adapter
(~130 MB for rank 32 on a 4B base) is over GitHub's 100 MB limit, so it is
gitignored. Mount Drive and point `--out` at it, push it to the Hub
(`--push <repo-id>`), or download it before the session ends:

```python
from google.colab import files
import shutil
shutil.make_archive("sasdoc-lora", "zip", "../adapters/sasdoc-lora")
files.download("sasdoc-lora.zip")
```

The notebook also has a commented-out cell for the reverse: re-uploading
that zip after a recycle, so you can resume at section 5 without
retraining.

## 5. Generate predictions for scoring

```bash
python3 infer.py --out ../results/preds/config2-base --gpu-usd-per-hour 0.0
python3 infer.py --adapter ../adapters/sasdoc-lora \
    --out ../results/preds/config2-tuned --gpu-usd-per-hour 0.0
```

Both read `../eval-programs/programs/*.sas` (the held-out 20, never trained
on) and write `.pred.json` + `.meta.json` per program in the same shape
config1 and config3 use, so `results/score.py` scores all three identically.
Greedy decoding, so base-vs-tuned isn't a sampling artifact. Run both so
the paper can report base-vs-tuned on identical inputs -- `config2-base` is
also the cleaner control for "what did fine-tuning do", since
config2-vs-config1 additionally changes the serving stack (bitsandbytes
4-bit on GPU vs Ollama GGUF on CPU) and the default parameter count.

Each `.meta.json` records per-program wall clock, the **actual GPU name**
read from `torch.cuda.get_device_properties` (not a prose description),
and the truncation record described next.

### Truncation: check this before you read any score

A generation cut off at `--max-new` stops mid-JSON. It does not parse, so
no `.pred.json` is written, so `results/score.py` counts that program as
**"no output produced"**: 0.00 on every metric, hallucination pinned to
1.00. In the results table that is indistinguishable from a model that had
nothing to say -- and it is a completely different finding.

This is not hypothetical. The 2026-09-22 tuned run hit it on **15 of 20
programs** at the old `--max-new 1200`, which dragged that row to 0.24
variable F1 while the 5 programs it did finish scored ~0.97. The cause is
specific to fine-tuning: the adapter learned to reproduce the training
corpus's verbose gold format, and the eval programs carry more variables
(12-15) than the training programs did (7-12), so the JSON runs longer
than the base model's ever did.

`infer.py` now handles it in three steps:

| | default | what it does |
|---|---|---|
| `--max-new` | **2400** (was 1200) | generation stops at the model's own EOS, so unused headroom costs nothing |
| `--retry-on-truncation` | **on** | a program that hits the cap is re-generated once at `--retry-factor` (2.0) x the budget. The model writes the whole answer itself |
| `--salvage-truncated` | **off** | closes a still-truncated JSON at its last complete element, so a nearly-finished dictionary scores as partial credit instead of zero |

Keep `--salvage-truncated` off for a headline number. It is a harness
repair that config1's `document_sas.py` has no equivalent of, so a run
using it cannot have its schema-validity column compared with config1's.
Salvaged predictions carry `"salvaged": true` and a `salvage_note` in
their `.meta.json`, and the run prints a warning saying exactly this.

The end of every run now prints a coverage line:

```
20/20 produced parseable JSON (3 needed the retry, 0 salvaged)
```

If that line shows programs lost to truncation, raise `--max-new` and
re-run **before** scoring. A truncation-limited row is a budget artifact,
not a measurement of the model.

`--gpu-usd-per-hour` turns the results table's "cost per program" into a
measured number instead of a hardcoded zero. `0.0` is correct on Colab's
free tier and is what makes the plan's air-gap sentence ("...at Y cost...")
true; set it to what you actually pay on a paid runtime. If you ran on a
paid runtime and left it at 0, the cost column is wrong.

## 5b. Score the predictions

`results/run_eval.py` is the actual pipeline entry point -- it wraps
`score.py` (+ `llm_judge.py` if you ask for `--run-judge`) and writes the
`.scores.jsonl` that both this per-config step and the final cross-config
results table read:

```bash
python3 ../results/run_eval.py --config config2-base \
    --pred-dir ../results/preds/config2-base \
    --out-prefix ../results/outputs/config2-base
python3 ../results/run_eval.py --config config2-tuned \
    --pred-dir ../results/preds/config2-tuned \
    --out-prefix ../results/outputs/config2-tuned
```

(`--gold-dir`/`--source-dir` default to `../eval-programs/gold` /
`../eval-programs/programs`, matching this folder's layout, so they're
omitted above.)

Scoring also writes a `.provenance.json` sidecar recording exactly which
eval corpus was scored. `--table` marks a row **STALE** rather than
printing numbers that no longer describe the corpus on disk -- see
`../results/outputs/stale-2026-09-17/README.md` for the run that made that
necessary.

`--run-judge` is deliberately omitted on Colab: the default judge is a
local Ollama model and Colab has none. The table prints `not run` for
Description score rather than inventing one; run the judge later on a box
that has a server.

Then print the table. One `--table` call prints one header, so pass every
row at once rather than concatenating separate invocations:

```bash
python3 ../results/run_eval.py --table --rows ../results/rows.example.json
```

Each line of a `.scores.jsonl` file is one program's metrics (schema
validity, variable/macro/IO precision-recall-F1, hallucination rate -- see
`results/score.py`'s docstring for the full list); `--table` prints the
plan's actual results-table row (bootstrapped mean + CI per metric), plus
coverage and the time/cost caveats underneath.

## 6. Ground truth from SAS OnDemand for Academics (ODA) -- optional

Not needed for the base-vs-tuned comparison above. What it buys you is a
**fairer hallucination rate**: `oda_harvest.py` actually runs each eval
program on ODA and reads back `dictionary.columns`, so the scorer can
count a column SAS really materialized as a valid source even when
`extract.py`'s static regex scan missed it. Per `PLAN.md` section 3 that
counts as a valid source -- and section 5b scores without it, so a name
config2 got *right* can currently be flagged as invented.

All of this runs in the Colab/Kaggle session.

1. **Get a free ODA account** if you don't have one (SAS OnDemand for
   Academics signup -- no cost, academic/non-commercial use).

2. **Credentials.** Never paste your password into a notebook cell that
   gets saved or shared -- use Colab Secrets (key icon, left sidebar:
   `ODA_USER`, `ODA_PASS`) and write `~/.authinfo` into the ephemeral
   session:
   ```python
   import os
   from google.colab import userdata
   with open(os.path.expanduser("~/.authinfo"), "w") as f:
       f.write("oda user %s password %s\n"
               % (userdata.get("ODA_USER"), userdata.get("ODA_PASS")))
   os.chmod(os.path.expanduser("~/.authinfo"), 0o600)
   ```

3. **Java + saspy** (one cell). Colab has no system Java, and this repo's
   portable `jre/` is 136 MB and gitignored, so it is not in the clone --
   install one. Colab runs as root, so no sudo:
   ```bash
   !apt-get -qq install default-jdk > /dev/null
   !pip -q install saspy pandas
   ```
   This folder's `sascfg_personal.py` already points `java` at whatever is
   on `PATH`, for exactly this reason. (config1's and config3's copies
   prefer the bundled `jre/` when it exists and fall back to `PATH`
   otherwise.)

4. **Region.** `sascfg_personal.py`'s `iomhost` list is filled in for
   US-region/usw2. If your ODA account is Europe or Asia Pacific, edit it
   -- config1's `SETUP.md` lists those host names.

   You do **not** need to copy `sascfg_personal.py` next to your saspy
   install: `oda_harvest.py` already passes it as `--cfgfile`. Earlier
   drafts of this doc said to copy it; that step was redundant.

5. **Preflight (the notebook does this for you).** Two things break the
   harvest on Colab:

   * **`NoClassDefFoundError: org/omg/CORBA/COMM_FAILURE`**, followed by
     `SAS Connection failed` and `SAS process has terminated unexpectedly`.
     Cause: a hand-built `"classpath"` in `sascfg_personal.py` listing only
     `saspy/java/iomclient/*.jar`. SAS's IOM protocol needs
     `org.omg.CORBA.*`, which the JDK carried through Java 8 and dropped in
     JEP 320 -- so on the JDK `apt-get` installs, the Java helper cannot
     start. saspy's own default classpath includes the CORBA back-port it
     ships in `java/thirdparty/`; that old list also named `log4j.jar` and
     `sas.rutil.jar`, which current saspy builds do not ship at all. Fix:
     do not set `classpath`. Fixed in this folder's `sascfg_personal.py`;
     if you hit it anyway you are running an older clone --
     `git -C /content/sas-llm-paper pull`, restart the runtime, re-run.
     (The notebook's preflight cell strips the key from a stale clone
     automatically.)
   * **An empty `java/thirdparty/`** in the installed saspy: no classpath
     can fix that one, `pip install -U saspy`.

6. **Run the harvest.** `--out` is a **directory** -- one
   `<program>.json` and one `<program>.txt` per program:
   ```bash
   python3 oda_harvest.py --sas-dir ../eval-programs/programs \
       --out ../data/oda_metadata
   ```
   A program that partially fails still gets its materialized datasets
   harvested, and any `ERROR` lines are printed rather than swallowed.
   Read them: a program that errored out contributes less ground truth
   than one that didn't.

7. **Re-score against it.** This is the step that makes section 6 worth
   running -- without it the harvest sits in `../data/oda_metadata/` and
   changes nothing:
   ```bash
   python3 ../results/run_eval.py --config config2-tuned-gt \
       --pred-dir ../results/preds/config2-tuned \
       --extra-source-dir ../data/oda_metadata \
       --out-prefix ../results/outputs/config2-tuned-gt
   ```
   Note the separate `-gt` prefix. A hallucination rate measured with real
   SAS metadata as an allowed source is **not comparable** to one measured
   without it, so the two must not overwrite each other or share a table
   row -- print them as a labelled pair. `run_eval.py` records which was
   which in the provenance sidecar's `notes` and per-row
   `used_extra_source`, and the plan asks for the tool-access asymmetry to
   be stated explicitly rather than folded into the headline number.

**Licence note:** ODA is for academic/non-commercial use, and running the
generated programs there is fine (they're synthetic) -- check current terms
before putting anything work-adjacent on it.
