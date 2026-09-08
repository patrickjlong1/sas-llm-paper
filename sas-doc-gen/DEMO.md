# Demo: hand this to another user

This is the "give it to someone else" walkthrough. Full design rationale
lives in `README.md`; this file is just the runnable path.

## What you're demonstrating

Two related things live in this repo:

- **`sas-doc-gen/`** (this dir) -- documents a real SAS program *today*,
  zero-shot, using a small local model over Ollama. No GPU, no SAS account
  needed to run it. This is what the demo actually runs.
- **`seasug-paper/`** -- the QLoRA fine-tuning pipeline that would make the
  documentation meaningfully better, if run end-to-end on a GPU (a free
  Colab T4 is enough). **No adapter has been trained yet** -- this is a
  pipeline someone can run, not a finished model you're handing over. See
  "If they want to actually run the QLoRA side" below.

## 1. Run the demo (no ODA account needed)

```bash
cd /internal/sas-doc-gen
./run_demo.sh
```

This documents the three bundled example programs in `demo_programs/`
(two synthetic estab/hhold-style programs, one an arbitrary ad-hoc SAS
program with no domain structure at all -- a decent stress test for the
regex-based guardrail) and writes results to `demo_out/` +
`demo_catalog/`. Takes roughly 5-25 minutes total on CPU-only hardware
like this box (~2-9 min/program, see README.md's measured throughput);
budget more on a busier or weaker machine.

Prerequisites the script checks for you and fails loudly if missing:
Ollama reachable, the `gemma3:1b` model pulled, `requests` importable by
plain `python3`.

## 2. Bring your own SAS programs instead

```bash
./run_demo.sh --dir /path/to/your/sas/programs
```

Any `*.sas` files in that directory get documented the same way. This is
real, arbitrary SAS -- not limited to the synthetic corpus's style.
Read the "Known limitations" section of `README.md` before trusting the
output unread: the guardrail catches *invented* identifiers, not wrong
*meanings*.

## 3. Optionally push results into SAS as real datasets

This step needs a SAS OnDemand for Academics (ODA) account -- **yours,
not something you get from me.** Nothing in this repo asks for or stores
a password:

```bash
# one-time setup, in your own terminal:
echo "oda user YOUR_ODA_EMAIL password YOUR_ODA_PASSWORD" >> ~/.authinfo
chmod 600 ~/.authinfo
# edit config/sascfg_personal.py: fill in the CHANGE ME iomhost list for
# your ODA region (US/EU/APAC differ -- check your ODA dashboard)

# then:
./run_demo.sh --push
```

Writes `PROGRAM_SUMMARY`, `MACRO_PARAMS`, `DATA_DICTIONARY` into your
`SASUSER` library (persists across your ODA sessions). `--libname`/
`--libpath` on `run_demo.sh` pass through if you want a different,
custom-path library instead.

## Why this doesn't run "from inside SAS" on ODA

The natural next ask is "can the SAS program itself kick this off,"
i.e. a SAS `X` statement shelling out to `document_sas.py`. **This does
not work on ODA** -- ODA runs in a locked-down container with the `X`
statement / `XCMD` disabled; there's no shell to escape to. That's a
platform restriction, not something this project can configure around.

So the direction here is Python driving SAS (via `saspy`), not SAS
driving Python -- `run_demo.sh` / `push_to_oda.py` connect *out* to your
ODA session to write results, the same direction `seasug-paper`'s
`04_oda_harvest.py` already uses to read real `dictionary.columns`
metadata back for scoring.

If your demo audience has access to a **full licensed SAS install**
(SAS 9 desktop/server or a Viya compute context with `XCMD` enabled --
not ODA), `sas_side/run_pipeline.sas` shows the other direction: SAS
shelling out via `X`, then reading the result back into a SAS dataset in
the same session. It's a self-check-and-abort script (checks
`getoption(xcmd)` first) so it fails with a clear message instead of a
cryptic one if run somewhere without shell access. Treat it as a
reference/education artifact for that audience, not something to point
at ODA users.

## If they want to actually run the QLoRA side

That's `seasug-paper/scripts/`, and it needs a GPU this repo doesn't
have access to -- a free Colab T4 works. Point them at
`seasug-paper/scripts/02_qlora_finetune.py`'s docstring for the Colab
setup cell, then:

```
01_generate_corpus.py   -> synthetic train/eval data (already generated,
                            scripts/train.jsonl + eval.jsonl, 600/20 recs)
02_qlora_finetune.py    -> QLoRA fine-tune on Colab, produces an adapter
03a_infer.py            -> generate docs with/without the adapter
04_oda_harvest.py       -> score against real dictionary.columns from ODA
                            (needs their own ODA account + ~/.authinfo,
                            same as above)
03_evaluate.py          -> hallucination/coverage metrics, base vs tuned
```

Once they have a trained adapter, `sas-doc-gen/README.md`'s "Upgrade
path" section covers merging it into a GGUF and serving it through this
same Ollama-based `document_sas.py` -- so the demo they already ran in
step 1 gets a straight quality upgrade without changing how it's invoked.

## On credentials

Don't paste ODA (or any) credentials into a chat session with an
assistant, here or elsewhere -- `~/.authinfo` is a local file precisely
so that never has to happen. If you want help getting the ODA connection
working, run the setup commands yourself (or via `!command` in a Claude
Code session, which executes locally rather than being sent as chat
text) and share the *error output*, not the credentials.
