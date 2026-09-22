# Results: scoring, judging, and the final table

Everything here is scoring/analysis code plus its outputs -- no config's
own generation logic lives here. Implements the plan's section 3
("Low-effort evaluation") end to end.

## Current state of the numbers (read this first)

**There are no current results in this repo.** `outputs/` holds only
`difficulty.json` and a quarantine folder:

- `outputs/stale-2026-09-17/` -- config1's and config3's scores from
  2026-09-17, which were computed against the eval corpus as it stood
  *before* `eval-programs/` was rewritten by hand on 2026-09-21. They are
  kept as an audit trail and are **not usable**; see that folder's
  `README.md` for what went wrong and the side-by-side of how much the
  numbers moved.
- `preds/stale-2026-09-17/` -- the predictions those scores came from
  (local only; `preds/` is gitignored).
- config2 has never been scored at all: the QLoRA adapter exists
  (`adapters/sasdoc-lora/`, trained 2026-09-21 on `google/gemma-3-4b-it`)
  but `infer.py` has not been run against the current eval set.

To produce real numbers, run each config's notebook against the current
`eval-programs/` and score it (steps below). `provenance.py --check` tells
you whether a given `.scores.jsonl` is current.

## Pipeline

1. **Get predictions.** Each config writes `<program>.pred.json` +
   `<program>.meta.json` per eval program into its own `preds/<config>/`
   directory here (see each config's own script/SETUP.md):
   - `config1-gemma-cpu/document_sas.py --dir ../eval-programs/programs --out ../results/preds/config1-gemma-cpu`
   - `config2-qlora-gpu/infer.py --out ../results/preds/config2-tuned`
   - `config3-frontier-skills/save_prediction.py` (once per program, after authoring by hand)

2. **Score structurally** (no LLM, no human -- pure set comparison):
   ```bash
   python3 score.py --gold-dir ../eval-programs/gold --pred-dir preds/config1-gemma-cpu \
       --source-dir ../eval-programs/programs --out outputs/config1-gemma-cpu_run1.scores.jsonl
   ```
   Repeat per config, and 3x per config (plan: "run each config three times
   so you can separate model variance from program difficulty") into
   `..._run1/2/3.scores.jsonl`. Every run also writes a
   `..._run1.provenance.json` sidecar -- don't delete it, that's what keeps
   the table honest (see "Provenance" below).

3. **Judge free-text descriptions** (the one metric that needs a model):
   ```bash
   python3 llm_judge.py --gold-dir ../eval-programs/gold --pred-dir preds/config1-gemma-cpu \
       --out outputs/config1-gemma-cpu_run1.judge.jsonl
   ```
   Default judge is the local `gemma3:1b` over Ollama (a different model
   family from config3/Claude, per the plan's anti-self-grading-bias
   requirement). **On Colab there is no Ollama server**, so either point
   `OLLAMA_URL` at one you can reach or skip `--run-judge` there and run the
   judge later on a box that has one; the table prints `not run` rather than
   inventing a description score.

4. **Calibrate the judge once** (~30 blind-scored examples, ~1 hour):
   ```bash
   python3 llm_judge.py --gold-dir ../eval-programs/gold \
       --pred-dirs preds/config1-gemma-cpu preds/config2-tuned preds/config3-frontier-skills \
       --calibrate --n 30 --out outputs/calibration_sample.jsonl
   ```
   Prints agreement (%) between your blind scores and the judge's. High
   agreement -> trust the judge on the rest.

5. **Tag difficulty** (once per corpus -- re-run it if `eval-programs/`
   changes, which it did on 2026-09-21):
   ```bash
   python3 difficulty_tags.py --sas-dir ../eval-programs/programs --out outputs/difficulty.json
   ```

6. **Bootstrap CI per metric**, unit of analysis = program (plan: "with 20
   programs, the unit of analysis is the program"):
   ```bash
   python3 bootstrap_ci.py --runs outputs/config1-gemma-cpu_run*.scores.jsonl --all-metrics
   ```

7. **Build the final results table.** A `--table` call prints its own
   header, so pass every row in one call rather than concatenating separate
   invocations:
   ```bash
   python3 run_eval.py --table --rows rows.example.json
   ```
   `rows.example.json` lists the five comparable rows (config1 on each
   backend, config2 base, config2 tuned, config3); rows with no scores yet
   print `(no scores found)` instead of failing, so this is also how you
   check where the comparison currently stands. A ground-truth-assisted
   re-score (`--extra-source-dir`, e.g. `config2-tuned-gt`) is deliberately
   NOT in that file: its hallucination rate is measured against a different
   set of allowed sources, so it belongs beside its own baseline, not in the
   same column as rows scored without it. The single-row form is how to
   print such a pair:
   ```bash
   python3 run_eval.py --table --scores outputs/config1-gemma-cpu_run*.scores.jsonl \
       --judge outputs/config1-gemma-cpu_run*.judge.jsonl --meta-dir preds/config1-gemma-cpu \
       --label "Config 1: Gemma, CPU"
   ```

## Provenance: which corpus a number belongs to

`provenance.py` fingerprints the eval corpus (sha256 of every
`gold/*.gold.json`, every `programs/*.sas`, and `schema.py`). Every scoring
run writes that fingerprint to `<prefix>.provenance.json`, and
`run_eval.py --table` re-checks it against what's on disk:

```bash
python3 provenance.py                                   # current corpus digest
python3 provenance.py --check outputs/*.scores.jsonl    # are these current?
```

A row whose corpus no longer matches is printed as `**STALE**` with a list
of which files changed, plus a `DO NOT PUBLISH THESE NUMBERS` block. This
exists because it already happened once -- see
`outputs/stale-2026-09-17/README.md`.

## Reading the table honestly

The table deliberately refuses to round awkward facts away:

- **`not recorded*` in Cost/program** means no `.meta.json` carried a
  `cost_usd`. It is *not* a measured $0. Only a config that actually wrote
  `cost_usd: 0.0` (config1 and config2, which run locally) prints
  `$0.00 (local)`. Config3 driven through the Anthropic API should record
  the real per-call cost from the response's usage fields --
  `save_prediction.py --cost-usd`.
- **`(placeholder*)` in Time/program** means every program in that run
  reported the *identical* `elapsed_sec`, which means it was typed in, not
  measured. Config3's 2026-09-17 run had 90.0s for all 20 programs.
- **Coverage lines under the table** give, per config, how many programs
  produced parseable JSON and how many passed `schema.validate()`. A 0.00
  F1 from "emitted nothing" and a 0.00 F1 from "emitted the wrong thing"
  are different findings.
- **`1 run only`** is called out where the plan asks for 3, because a CI
  from a single run reflects program difficulty only, not model variance.
- **`not run` in Description score** means the LLM judge has not been run,
  not that it scored zero.

## What "hallucination" means here

Per program: any variable/dataset/macro-param name the model emitted that
does not appear anywhere in the source text (case-insensitive word-boundary
search) is counted as hallucinated, whether or not it happens to be the
RIGHT kind of name for the context. Each scored row carries
`hallucination_basis`:

- `emitted_names` -- actually measured, `n_hallucinated / n_emitted_names`.
- `no_output_worst_case` -- the program produced no parseable/valid output,
  so nothing was emitted and the true rate is undefined. It is pinned to
  1.0 so a config cannot improve its hallucination number by failing to
  answer. Always read it next to the coverage line.

Per the plan, real SAS metadata counts as a valid source too, so a config3
answer grounded in `dictionary.columns` isn't unfairly flagged for citing a
real column the static regex scan missed. Pass it as a directory of
per-program `<program>.txt`/`.json` dumps:

```bash
python3 run_eval.py --config config2-tuned --pred-dir preds/config2-tuned \
    --extra-source-dir ../data/oda_metadata --out-prefix outputs/config2-tuned
```

(`config2-qlora-gpu/oda_harvest.py` and `config3-frontier-skills/sas_metadata.py`
both produce that shape.) Whether a run used it is recorded per row
(`used_extra_source`) and in the provenance sidecar's `notes`, so a
ground-truth-assisted hallucination rate is never silently compared against
one measured without it.

## Files

- `schema.py` -- canonical copy of the shared output schema (see
  `../eval-programs/schema.py`).
- `score.py` -- per-program structural scoring: schema validity, variable/
  macro/I-O F1, type/length accuracy, hallucination rate.
- `provenance.py` -- eval-corpus fingerprinting + the staleness check.
- `llm_judge.py` -- 0-2 rubric scoring of free-text descriptions, plus the
  blind-calibration mode.
- `difficulty_tags.py` -- structural difficulty tiers (length, macro count,
  nesting depth) per eval program.
- `bootstrap_ci.py` -- program-level bootstrap 95% CI over repeated runs.
- `run_eval.py` -- orchestrates the above into the final results table
  (Schema validity / Variable F1 / Macro F1 / I-O F1 / Hallucination rate /
  Description score / Time per program / Cost per program).
- `rows.example.json` -- the four-row spec for `run_eval.py --table --rows`.
- `outputs/` -- where scored/judged/tagged output lands (gitignored except
  for a `.gitkeep`, the committed `difficulty.json`, and the
  `stale-2026-09-17/` quarantine).
