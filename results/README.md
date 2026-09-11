# Results: scoring, judging, and the final table

Everything here is scoring/analysis code plus its outputs -- no config's
own generation logic lives here. Implements the plan's section 3
("Low-effort evaluation") end to end.

## Pipeline

1. **Get predictions.** Each config writes `<program>.pred.json` +
   `<program>.meta.json` per eval program into its own `preds/<config>/`
   directory here (see each config's own script/SETUP.md):
   - `config1-gemma-cpu/document_sas.py --dir ../eval-programs/programs --out ../results/preds/config1-gemma-cpu`
   - `config2-qlora-gpu/infer.py --out ../results/preds/config2-qlora-gpu`
   - `config3-frontier-skills/save_prediction.py` (once per program, after authoring by hand)

2. **Score structurally** (no LLM, no human -- pure set comparison):
   ```bash
   python3 score.py --gold-dir ../eval-programs/gold --pred-dir preds/config1-gemma-cpu \
       --source-dir ../eval-programs/programs --out outputs/config1_run1.scores.jsonl
   ```
   Repeat per config, and 3x per config (plan: "run each config three times
   so you can separate model variance from program difficulty") into
   `..._run1/2/3.scores.jsonl`.

3. **Judge free-text descriptions** (the one metric that needs a model):
   ```bash
   python3 llm_judge.py --gold-dir ../eval-programs/gold --pred-dir preds/config1-gemma-cpu \
       --out outputs/config1_run1.judge.jsonl
   ```
   Default judge is the local `gemma3:1b` (a different model family from
   config3/Claude, per the plan's anti-self-grading-bias requirement).

4. **Calibrate the judge once** (~30 blind-scored examples, ~1 hour):
   ```bash
   python3 llm_judge.py --gold-dir ../eval-programs/gold \
       --pred-dirs preds/config1-gemma-cpu preds/config2-qlora-gpu preds/config3-frontier-skills \
       --calibrate --n 30 --out outputs/calibration_sample.jsonl
   ```
   Prints agreement (%) between your blind scores and the judge's. High
   agreement -> trust the judge on the rest.

5. **Tag difficulty** (once, not per-run):
   ```bash
   python3 difficulty_tags.py --sas-dir ../eval-programs/programs --out outputs/difficulty.json
   ```

6. **Bootstrap CI per metric**, unit of analysis = program (plan: "with 20
   programs, the unit of analysis is the program"):
   ```bash
   python3 bootstrap_ci.py --runs outputs/config1_run*.scores.jsonl --all-metrics
   ```

7. **Build the final results table**:
   ```bash
   python3 run_eval.py --table --scores outputs/config1_run*.scores.jsonl \
       --judge outputs/config1_run*.judge.jsonl --meta-dir preds/config1-gemma-cpu \
       --label "Config 1: Gemma 2B, CPU"
   ```
   Or pass `--rows rows.json` (a list of `{label, scores_patterns,
   judge_patterns, meta_dir}`) to print all three configs' rows in one call
   -- see `run_eval.py`'s docstring.

## What "hallucination" means here

Per program: any variable/dataset/macro-param name the model emitted that
does not appear anywhere in the source text (case-insensitive word-boundary
search) is counted as hallucinated, whether or not it happens to be the
RIGHT kind of name for the context. For config3, also pass
`--extra-source` (the PROC CONTENTS/`dictionary.columns` dump) to `score.py`
-- per the plan, that counts as a valid source too, so a config3 answer
grounded in real SAS metadata isn't unfairly flagged for citing a real
column the static regex scan missed.

## Files

- `schema.py` -- canonical copy of the shared output schema (see
  `../eval-programs/schema.py`).
- `score.py` -- per-program structural scoring: schema validity, variable/
  macro/I-O F1, type/length accuracy, hallucination rate.
- `llm_judge.py` -- 0-2 rubric scoring of free-text descriptions, plus the
  blind-calibration mode.
- `difficulty_tags.py` -- structural difficulty tiers (length, macro count,
  nesting depth) per eval program.
- `bootstrap_ci.py` -- program-level bootstrap 95% CI over repeated runs.
- `run_eval.py` -- orchestrates the above into the final results table
  (Schema validity / Variable F1 / Macro F1 / I-O F1 / Hallucination rate /
  Description score / Time per program / Cost per program).
- `outputs/` -- where scored/judged/tagged output lands (gitignored except
  for a `.gitkeep`).
