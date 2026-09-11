# Config 2 setup: QLoRA fine-tune, GPU (free Colab), ODA credentials

Config 2 asks: does a modest fine-tuning run on the SAME base model as
config1 close the gap to the frontier config, while staying air-gapped
(no data leaves the building once trained)? This needs a GPU config1
doesn't have -- a free Colab T4 is enough.

## 1. Get a free GPU

**Google Colab (recommended, no cost):**

1. Go to https://colab.research.google.com and sign in with any Google
   account.
2. New notebook -> Runtime -> Change runtime type -> Hardware accelerator:
   **T4 GPU** -> Save. Free tier gives you a T4 (16 GB VRAM) with usage
   limits that reset over time; that's enough for a 1-2B model in 4-bit at
   `--maxlen 2048`.
3. Upload this `config2-qlora-gpu/` folder to the Colab session (drag-drop
   into the Files pane, or `git clone`/`gdown` your own copy of this repo),
   or mount Google Drive if you want the adapter output to persist across
   sessions (Colab's local disk is wiped when the runtime recycles).

**Alternatives if Colab's free tier is unavailable/rate-limited:**

- **Kaggle Notebooks** -- free 30 hrs/week of a P100 or T4x2 GPU, similar
  workflow (Settings -> Accelerator -> GPU).
- **Lightning AI Studios** -- free tier includes some GPU hours.
- Any of these work the same way: install the requirements, upload/generate
  the training data, run the two scripts below.

## 2. Install dependencies (in the Colab/Kaggle session, one cell)

```bash
!pip -q install -r requirements.txt
```

## 3. Generate training data (disjoint from the 20 held-out eval programs)

```bash
python3 generate_training_corpus.py --n 600 --out-dir ../data
```

This is a synthetic corpus (same generator eval-programs/ uses, different
seed and id range) -- see `corpus_gen.py`'s docstring. It automatically
runs `check_no_leakage.py` at the end and refuses to proceed if it finds any
overlap with `../eval-programs/gold/`. **This is the plan's hard
constraint: never point `--train` at anything derived from `eval-programs/`
-- the scores are meaningless if you do.** If you have real (non-synthetic)
internal SAS programs with existing documentation, those make even better
training pairs than the synthetic corpus -- format them as
`{"program_name":..., "sas":..., "gold": {...schema.py shape...}}` per line
in a `.jsonl` and pass that as `--train` to the next step instead.

## 4. Fine-tune

```bash
python3 qlora_finetune.py --train ../data/train.jsonl --model google/gemma-3-1b-it \
    --maxlen 2048 --epochs 2 --out ../adapters/sasdoc-lora
```

`google/gemma-3-1b-it` is Gemma weights on Hugging Face and is **gated** --
you must (a) accept the license on the model's HF page while logged in, and
(b) run `huggingface-cli login` (or set the `HF_TOKEN` secret in Colab)
before this will download. Keep the base model matched to config1's
`gemma3:1b` (Ollama's GGUF build of the same weights) -- that's what makes
"config1 vs config2" a fine-tuning comparison rather than a different-model
comparison.

Expect roughly 30-90 minutes on a free T4 for 600 examples x 2 epochs at
`--maxlen 2048`. Record the actual wall-clock time and note it's a
**one-time training cost**, separate from the per-program inference cost in
the results table (plan: "cost per program" is about *running* the model,
not training it).

## 5. Generate predictions for scoring

```bash
python3 infer.py --out ../results/preds/config2-base                          # base model, no adapter
python3 infer.py --adapter ../adapters/sasdoc-lora --out ../results/preds/config2-tuned   # fine-tuned
```

Both read `../eval-programs/programs/*.sas` (the held-out 20, never trained
on) and write `.pred.json` + `.meta.json` per program in the same shape
config1 and config3 use, so `results/score.py` scores all three identically.
Run both so the paper can report base-vs-tuned on identical inputs, not just
tuned-vs-config1/config3.

## 6. Setting up your SAS OnDemand for Academics (ODA) credentials

Optional -- only needed for `oda_harvest.py` (scoring against what SAS
actually materializes, rather than the generator's own spec) or if you want
to push results to SAS. Same account/credential setup as config1 and
config3:

1. **Get a free ODA account** if you don't have one (SAS OnDemand for
   Academics signup -- no cost, academic/non-commercial use).
2. **In the Colab/Kaggle session** (never paste your password into a
   notebook cell that gets saved/shared -- use Colab Secrets):
   ```python
   import os
   os.environ["ODA_USER"] = "YOUR_ODA_EMAIL"          # or read from Colab Secrets
   os.environ["ODA_PASS"] = "YOUR_ODA_PASSWORD"
   with open(os.path.expanduser("~/.authinfo"), "w") as f:
       f.write("oda user %s password %s\n" % (os.environ["ODA_USER"], os.environ["ODA_PASS"]))
   os.chmod(os.path.expanduser("~/.authinfo"), 0o600)
   ```
3. **Install Java + saspy** (one cell):
   ```bash
   !apt-get -qq install default-jdk > /dev/null
   !pip -q install saspy
   ```
4. Copy `sascfg_personal.py` (in this folder) next to your saspy install --
   its `iomhost` list is already filled in for US-region/usw2; if your
   account is a different region, see config1's `SETUP.md` for the other
   two regions' host names:
   ```python
   import saspy, shutil, os
   shutil.copy("sascfg_personal.py", os.path.dirname(saspy.__file__))
   ```
5. Run the harvest:
   ```bash
   python3 oda_harvest.py --sas-dir ../eval-programs/programs --out ../data/oda_metadata.json
   ```

**Licence note:** ODA is for academic/non-commercial use, and running the
generated programs there is fine (they're synthetic) -- check current terms
before putting anything work-adjacent on it.
