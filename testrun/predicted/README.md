# Predicted run outputs for config1 and config2

**Nothing in this folder is a measurement of model output.** The two
notebooks in `testrun/` were interrupted before their scoring cells ran, so
the `.scores.jsonl` files those runs *would* have produced do not exist.
These are the best reconstruction of them from what the notebooks did
capture plus the repo's own code.

The `.scores.jsonl` numbers here are *computed*, not invented: simulated
`.pred.json` files are scored by the repo's real `results/run_eval.py`
against the real, current `eval-programs/gold/`. The guesswork is confined
to one place — how each config's predictions are degraded away from gold
(`predict_run_outputs.py`, the `BASE` / `TUNED` knob dicts).

Do not merge any of this into `results/outputs/`, and do not put a number
from here in the paper. Re-run the notebooks for that.

---

## Files

| file | what it is |
|---|---|
| `config1-gemma-cpu.scores.jsonl` | predicted config1 (all 20 programs) |
| `config1-gemma-cpu-partial12.scores.jsonl` | same run, stopped after 12 programs — the likelier Colab outcome |
| `config2-base.scores.jsonl` | predicted config2 base model, no adapter |
| `config2-tuned.scores.jsonl` | predicted config2 QLoRA-tuned |
| `*.provenance.json` | real corpus fingerprint + `"simulated_predictions": true` |
| `preds/<config>/*.pred.json` | the simulated predictions that were scored |
| `preds/<config>/*.meta.json` | timings — **measured** for config2 (copied from the notebook), extrapolated for config1 |
| `results-table.predicted.txt` | `run_eval.py --table` over all six rows, config1/2/3 together |
| `*.scoring.log` | what each notebook's scoring cell would have printed |
| `predict_run_outputs.py` | the generator; every assumption is a named constant in it |
| `config3/` | the same treatment for config3, plus a **real** 20-program SAS ground-truth harvest and a filled-in copy of its notebook — see `config3/README.md` |

Regenerate: `python3 predict_run_outputs.py` (add `--seed N` to re-draw).

---

## What the notebooks actually establish

These are the anchors, and they are not negotiable in the simulation.

**config1 (`config1_gemma_cpu.ipynb`)**

- Model is `google/gemma-3-4b-it` via `transformers`, bf16, CPU, greedy
  (`hf_backend.py` passes `do_sample=False`), `--num-predict 1600`.
- `prog900_estab` completed twice (2619.8 s single-file, 2590.2 s in the
  batch run). Both printed *"no guardrail flags — all claimed identifiers
  were found in the source"*, which `document_sas.py` only reaches when
  `schema.validate()` passed **and** `guardrail.check()` flagged nothing.
- Its catalog line: **"4 macro row(s), 10 dictionary row(s)"** → exactly 10
  variable rows, and 4 macro-param rows for a 3-parameter macro, which
  `records.py` only produces if a second, parameter-less `macro_reference`
  entry was emitted.
- Cell 12: 873.3 min (14.6 h) projected for all 20. The batch cell shows
  headers for `[1/20]` and `[2/20]` and then stops — it never finished, and
  on free Colab it cannot (≈12 h ceiling, ~90 min idle cut-off).

**config2 (`config2_qlora_gpu.ipynb`)**

- Trained on an **A100-40GB**, not the free T4 the notebook is written for
  (cell 4). 580 train / 20 holdout, 2 epochs, 146 steps, 19.6 min
  (21.1 min wall), final `train_loss` 0.031, `eval_loss` 0.0106,
  `eval_mean_token_accuracy` 0.9956 — a very tight fit to the
  `corpus_gen.py` template.
- `infer.py` base run: **all 20 parsed**, 73.1–106.2 s each.
- `infer.py` tuned run: **15 of 20 said `PARSE ERROR`**, 162.0–185.3 s each.
  The 5 that parsed: `prog900_estab`, `prog910_estab`, `prog914_hhold`,
  `prog918_hhold`, `prog919_estab`.
- `infer.py` writes **no `.pred.json`** on a parse error, so those 15 are
  scored as `"no output produced"` — that part is mechanical, not a guess.
- The `config2-outputs.zip` / `config2-preds.zip` already in `testrun/` are
  from an earlier session: preds is empty apart from `.gitkeep`, and its
  `config2-base`/`config2-tuned` `.scores.jsonl` are 20 × "no output
  produced" (they also predate `hallucination_basis`, so they were written
  by an older `score.py`). They are not results of the runs above.

---

## How the predictions are built

`pred = degrade(gold, per-config error model)`, then score with the repo's
scorer. The error models:

### config1 and config2-base share one model

Same weights, same system prompt (`prompts.py`'s `SYSTEM` and `infer.py`'s
`SYSTEM` are the same text), same greedy decode. The only differences are
bf16-on-CPU vs 4-bit-NF4-on-GPU and a 1600 vs 1200 token cap. So the
generator draws each program's *systematic* behaviour once — whether the
libref gets resolved, whether the PROC SUMMARY dataset is documented, how
macro params are classified, which schema-invalidity mode fires — and lets
only token-level details differ, on 35% of programs. **Predicting a real
gap between config1 and config2-base would have been the wrong call**; the
two rows come out within noise of each other, which is itself the
prediction.

What the base model is assumed to do, and why:

| knob | value | reasoning |
|---|---|---|
| parses as JSON | 20/20 | measured for config2-base at a *tighter* token cap; config1 has 400 more tokens of headroom |
| `p_work_prefix` | 0.45 | the scored key is `(DATASET, NAME)` and gold says `WORK.O1`. The program writes `data &lb..o1;`, so the model must resolve `&lb` → `work` → `WORK.O1`. A 4B model does this inconsistently; this is **the single biggest driver of Variable F1 and I/O F1** |
| `p_documents_agg1` | 0.35 | `agg1` is born inside `output out=agg1(...)`, not a DATA step; zero-shot the model usually documents only the DATA-step output |
| `p_keep_var` | 0.88 | prog900: 10 rows emitted for a 12-row gold |
| `p_all_keyword` | 0.60 | the prompt's rule ("classify by whether a default VALUE is present, not by whether `=` appears") is exactly the rule a small model ignores — costs `macro_posk_accuracy`, not `macro_param_f1` |
| `p_hallucinated_name` | 0.10 | the model copies names out of the source; config1's guardrail flagged nothing on prog900 |
| schema-invalid | ~15% | no JSON-mode decoding on either path (`README`/`document_sas.py` both say so); modelled as `"type": "numeric"` instead of `"num"`, or a row missing `length` |
| `called_by` | always empty | **not a knob — a fact.** `build_messages()` sends the SAS text and nothing else, so neither config can know the file name. `called_by_f1 = 0.00` for all three runs. Config3 scores 1.00 there purely because it is handed the file |

### config2-tuned

15 programs have no prediction at all (measured). For the 5 that parsed,
the adapter is assumed to be close to gold, because it was trained on 580
`corpus_gen.py` pairs whose gold uses the same `WORK.O1` / `WORK.AGG1`
conventions and nearly the same derivation phrasing as the hand-written
eval gold — at `eval_mean_token_accuracy` 0.9956 it reproduces that format
rather than inventing one. Variables are kept at 97% on the sort+merge
programs (in-template) and 85% on the PROC SQL one (`prog900`, the join
idiom it never saw). `called_by` gets a plausible *wrong* file name
(`prog<100-699>_<domain>.sas`) — the shape it was trained to emit, applied
to a program whose name it cannot see.

**Why 15 failed is inferred, not observed.** The likeliest cause is the
1200-token cap: the tuned model reproduces the full verbose training
format, and eval gold runs 12–15 variables against training's 7–12, so the
JSON gets cut mid-string. That fits the flat ~184 s wall clock on the
failures (a fixed token budget spent in full). It does not fully explain
`prog914`/`prog918` parsing *at* 185 s, so trailing text after a complete
object (`json.loads` → "Extra data") may be the mechanism on some. Either
way the scoring outcome is identical. The `.meta.json` files here record
`"truncated": true` for the 15, which is the truncation reading.

One pattern worth checking against the raw output if it is ever recovered:
4 of the 5 that parsed are sort+merge programs (in-template) and 10 of the
11 PROC SQL programs failed — 4/9 vs 1/11. Small n, but it points at
out-of-template input rather than at length alone.

---

## Predicted results

```
| Config                                        | Schema validity   | Variable F1       | Macro F1          | I/O F1            | Hallucination     | Time/prog |
| Config 1: Gemma CPU zero-shot (gemma-3-4b-it) | 0.85 [0.70, 1.00] | 0.32 [0.15, 0.50] | 0.84 [0.69, 0.99] | 0.35 [0.17, 0.54] | 0.16 [0.01, 0.31] |   2595.5s |
| Config 1: same run, stopped at 12/20          | 0.55 [0.35, 0.80] | 0.17 [0.04, 0.34] | 0.54 [0.33, 0.77] | 0.18 [0.04, 0.36] | 0.46 [0.21, 0.66] |   2626.0s |
| Config 2: base, no adapter (4-bit, A100)      | 0.85 [0.70, 1.00] | 0.33 [0.16, 0.50] | 0.84 [0.69, 0.99] | 0.35 [0.17, 0.54] | 0.16 [0.01, 0.31] |     87.2s |
| Config 2: QLoRA-tuned (+ sasdoc-lora, A100)   | 0.25 [0.10, 0.45] | 0.24 [0.09, 0.43] | 0.25 [0.10, 0.45] | 0.25 [0.10, 0.45] | 0.75 [0.55, 0.90] |    182.6s |
```

Coverage, which the table's own footer insists on: config1 20/20 parsed and
17/20 schema-valid; config2-base 20/20 and 17/20; config2-tuned **5/20 and
5/20**. Cost/program is `$0.00 (local)` for all four — correct for config1
(CPU) and for how the notebook invoked `infer.py` (`--gpu-usd-per-hour
0.0`), though that flag is what makes the A100 row read as free.

On the tuned run, the two halves pull in opposite directions and the mean
hides it:

- on the 5 programs it answered: variable precision **1.00**, recall
  **0.95**, macro param F1 **1.00**, I/O F1 **1.00**, hallucination
  **0.00**;
- on the other 15: nothing, scored 0.00 across the board with
  hallucination pinned to 1.00 by `score.py`'s worst-case convention.

That is the honest headline: **fine-tuning raised per-answer quality well
above the base model and destroyed coverage**, and a mean of 0.24 Variable
F1 for tuned vs 0.33 for base describes those two facts at once rather than
"tuning made it worse".

---

## How much to trust each number

| claim | confidence | why |
|---|---|---|
| config2-tuned: 15/20 "no output produced", 5/20 valid | **high** | measured; `infer.py`'s file-writing behaviour is mechanical |
| config2 timings and hardware | **high** | copied from the notebook's own stdout |
| `called_by_f1 = 0.00` for config1 and config2 | **high** | the prompt never contains the file name |
| config1 ≈ config2-base on every metric | **high** | same weights, prompt and decode |
| config2-tuned's per-answer quality being near-gold on the 5 | **medium-high** | training loss/token accuracy + identical output conventions |
| config1/base schema validity ≈ 0.85 | **medium** | one measured program (valid), plus "no JSON-mode decoding" |
| Variable F1 / I/O F1 ≈ 0.3 for config1 and base | **low-medium** | dominated by the `&lb..o1` → `WORK.O1` coin flip; see below |
| config1 finishing all 20 at all | **low** | 14.6 h projected vs Colab's ceiling — the partial row is the likelier one |

Seed sensitivity (same knobs, different draws):

| seed | config1 valid | config1 Var F1 | config1 Macro F1 | config2-base Var F1 |
|---|---|---|---|---|
| 20260922 (default) | 17/20 | 0.32 | 0.84 | 0.33 |
| 1 | 19/20 | 0.29 | 0.93 | 0.30 |
| 7 | 15/20 | 0.25 | 0.72 | 0.21 |
| 42 | 15/20 | 0.34 | 0.73 | 0.35 |
| 2026 | 15/20 | 0.29 | 0.72 | 0.28 |

So read the base-model rows as **Variable F1 0.2–0.35, Macro F1 0.7–0.95,
schema validity 0.75–0.95**, not as the printed two decimals.

The largest single unknown is one bit per program: does the model write
`"dataset": "WORK.O1"` or `"o1"` / `"&lb..o1"`? Gold keys variables by
`(DATASET, NAME)`, so that bit alone moves a program's Variable F1 between
~0.9 and 0.0. Note this even applies to `prog900`, where the row *count*
(10) is pinned by the notebook but the dataset spelling is not: the default
seed happened to draw "resolved", which is why `prog900` shows Variable F1
0.91 in `config1-gemma-cpu.scores.jsonl`. If the real run wrote bare `o1`,
that row is 0.00.

## Replacing these with real numbers

1. config2 is the cheap one: the adapter is already trained and zipped
   (`testrun/sasdoc-lora.zip`, and `adapters/sasdoc-lora/` in the repo).
   Re-run `infer.py` with `--max-new 2400` on both base and tuned and the
   tuned coverage question answers itself in ~2 GPU-hours.
2. config1 at 43 min/program is the expensive one. The notebook's own cell
   12 offers the two honest ways out: `--limit N` and report the run as
   partial (that is what `config1-gemma-cpu-partial12.scores.jsonl` here
   models), or the `gemma-3-1b-it` + float32 path, which is faster but
   breaks base-model parity with config2 and weakens the config1-vs-config2
   row.
3. Either way, re-run `results/run_eval.py --config ... --out-prefix
   ../results/outputs/...` and delete this folder rather than reconciling
   it with the real numbers.
