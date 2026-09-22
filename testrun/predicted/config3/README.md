# Config 3, run cell by cell — what's real and what isn't

`config3_frontier_skills.SIMULATED.ipynb` here is the repo's config3
notebook with every cell filled in. The repo's own copy at
`config3-frontier-skills/config3_frontier_skills.ipynb` was **not
modified**.

This box has no `ANTHROPIC_API_KEY`, so nothing that calls the model could
actually run. Everything else could, and did.

## Cell by cell

| cell | status | what happened |
|---|---|---|
| Setup 0 — environment check | **real** | ran it; only the `ANTHROPIC_API_KEY` line is shown as it would read with the key exported (it actually prints "not set") |
| Setup 1 — `pip install anthropic` + versions | **real** | `anthropic 1.7.0 \| saspy 5.108.7 \| pandas 3.0.1` |
| Setup 2 — key + `models.retrieve` | simulated | needs the key |
| `sas_metadata.py` on prog900 | **real** | live ODA session, 18.5 s, 39 columns across 6 tables, zero SAS errors |
| `header_extract.py` + `extract.py` | **real** | `header_found: false`; 6 datasets, 3 params, 16 variables |
| `claude_driver.py` — one program | simulated | |
| `claude-runs/*.run.json` dump | simulated | |
| `claude_driver.py --dir` — all 20 | simulated | |
| `claude_driver.py --no-sas-tool` — all 20 | simulated | |
| `run_eval.py` scoring (both runs) | **real scorer, simulated predictions** | the `.scores.jsonl` numbers are arithmetic over made-up model output |
| `run_eval.py --table` | **real** | same caveat |
| `push_to_oda.py` | simulated | deliberately **not** run — it writes datasets into your live SASUSER library |

## The ground truth is real, and it validates the gold

`metadata/*.json` is a genuine harvest: all 20 eval programs were submitted
to SAS OnDemand and their `dictionary.columns` / `dictionary.tables` read
back. 20/20 succeeded, mean **16.2 s** per program, 324 s total, zero
`run_errors`, and every program materialized the datasets its gold file
documents.

That makes one useful check possible, and it is not a simulation:

> **251 of 251 gold variable rows — name, dataset, type and length — are
> confirmed by live SAS.** Zero mismatches across all 20 programs.

So the hand-rewritten gold from 2026-09-21 agrees exactly with what SAS
actually builds. It also explains why config3's predicted numbers are so
high: `sas_column_metadata` hands the model the very fields
`type_length_accuracy` and the variable F1 key are scored on.

## What the simulation assumes

Calibrated against the quarantined 2026-09-17 config3 run
(`results/outputs/stale-2026-09-17/`), which is *real* Claude-with-tools
output — against the previous corpus, but the same model, prompt and
tools. It scored variable F1 1.00, type/length 1.00, macro param F1 1.00,
I/O F1 1.00, called_by 1.00, hallucination 0.00, and positional-vs-keyword
accuracy 0.50–0.75.

| knob | GT run | `--no-sas-tool` | reasoning |
|---|---|---|---|
| `p_posk_wrong` | 0.40 | 0.40 | classifying `p=` (no default value) as a keyword param is the one thing the real run got wrong, repeatedly |
| `p_type_length_wrong` | 0.00 | 0.10 | with `dictionary.columns` there is nothing left to guess; without it, the derived `*R` variables have no LENGTH statement to read |
| `p_documents_intermediate` | 0.15 | 0.20 | documenting `WORK.J1`/`WORK.HOLD` as well — pure precision cost. It did not fire on any GT program in this draw, which matches the real run's 1.00 precision |
| `p_drop_var` | 0.01 | 0.05 | AGG1's summarized columns are the ones you have to reason about rather than read |
| `p_repair_turn` | 0.15 | 0.20 | the driver re-asks on a schema miss and records it |

Timing is **half measured**: each program's `elapsed_sec` is its real
harvest time from `harvest_times.json` plus a simulated 26–58 s of model
time. Cost is fully simulated, priced from `claude_driver.PRICES`
($5/$25 per Mtok) against simulated token counts.

## Predicted result

```
| Config 3                          | Schema | Var F1 | Macro F1 | I/O F1 | Halluc | Time/prog | Cost/prog |
| Claude + SAS ground truth         |  1.00  |  0.99  |   1.00   |  1.00  |  0.00  |   61.7s   |  $0.1281  |
| Claude, --no-sas-tool             |  1.00  |  0.94  |   1.00   |  1.00  |  0.00  |   48.3s   |  $0.0940  |
```

Simulated total spend for both runs: **$4.29** ($2.56 + $1.73).

The interesting part is the pair, which is what cell 21 exists for. The gap
is **narrow, and concentrated in exactly one metric**:

- `type_length_accuracy` **1.00 → 0.88**. That is the tool doing the work.
- variable F1 0.99 → 0.94, entirely from documenting a staging dataset on
  4 of 20 programs without SAS to tell it which tables are real.
- Macro F1, I/O F1, called_by and hallucination are **identical** — a
  frontier model reads `%macro est_report(p=, lb=work, thr=0)` and
  `data &lb..o1;` correctly with or without a SAS session.

If that holds on a real run, the honest sentence for the paper is narrower
than "tool access wins": on *this* corpus, ground truth buys you type and
length, and little else — because the programs carry explicit `length`
statements a good reader can use. It would buy much more on real legacy
code where types come from a dozen upstream datasets.

## Do not use these files for

- **Description quality / `llm_judge.py`.** The simulated dictionaries
  carry gold's own `description`, `purpose` and `derivation` text, so a
  judge would score them ~2.00 and mean nothing.
- **Anything in `results/`.** Nothing here was copied there. Both
  `.provenance.json` sidecars carry `"simulated_predictions": true`.

## To make it real

```bash
export ANTHROPIC_API_KEY=sk-ant-...
cd config3-frontier-skills
/internal/venvs/main/bin/python3 claude_driver.py --dir ../eval-programs/programs \
    --model claude-opus-5 --effort high \
    --out claude-runs --catalog catalog/ --preds-out ../results/preds/config3-frontier-skills
```

The harvest in `metadata/` can be reused as-is to skip the SAS sessions —
pass `--metadata-json metadata/<program>.json` per program, or just let the
driver re-harvest (it costs 16 s each, and it worked 20/20 today).

## Files

| file | |
|---|---|
| `config3_frontier_skills.SIMULATED.ipynb` | the filled-in notebook |
| `metadata/*.json` | **real** SAS ground truth, 20 programs |
| `harvest_times.json` | **real** per-program harvest wall clock |
| `config3-frontier-skills.scores.jsonl` | predicted scores, GT run |
| `config3-frontier-skills-nogt.scores.jsonl` | predicted scores, no-tool run |
| `preds/`, `claude-runs/`, `claude-runs-nogt/` | the simulated predictions and run records |
| `cell*-console.txt`, `cell*-scoring.txt`, `cell26-table.txt` | the per-cell transcripts the notebook embeds |
| `simulate_config3.py`, `build_simulated_notebook.py` | the generators; all assumptions are named constants |
