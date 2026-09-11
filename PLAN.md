# Plan: LLM-Generated Documentation for Legacy SAS Code

_Verbatim design doc this project implements. See the root `README.md` for
how the folders below map to each section._

**1. Documentation scope**

The scope is narrow on purpose. Each program gets three artifacts, and each
is emitted as structured JSON so it can land back in SAS datasets.

- **Variable dictionary.** Covers every column created or kept in the
  program's output datasets. Each entry has the name, dataset, type/length
  where it can be determined, label, and a one-line description of how the
  variable is derived.
- **Macro reference.** Covers every macro defined or called. Each entry has
  positional parameters, keyword parameters with defaults, a short purpose
  statement, and the programs that call it. For compiled macros stored with
  `/STORE DES=`, the description is already in the catalog, so it's
  retrieved directly rather than generated.
- **Program summary.** Gives a description plus the input and output
  datasets (libref.member). If a header comment exists, its description and
  input/output listing are used as a starting point, but they're also
  checked against the code, because headers drift out of date.

Out of scope: line-by-line commentary, refactoring suggestions, and
codebase-wide lineage graphs.

**2. Three configurations**

All three use the same prompt and output schema. Only the model and its
access change.

- **Config 1: Gemma 2B, CPU only.** This is an off-the-shelf small
  open-weight model with no fine-tuning. It sets the floor by testing
  whether the workflow can run air-gapped on ordinary hardware. Expect
  reasonable extraction of explicit structure (macro signatures, DATA/SET
  statements) and weaker descriptions.
- **Config 2: QLoRA fine-tune of the same base, with GPU.** The model is
  trained on pairs of SAS programs and their documentation. The question is
  whether a modest training run closes the gap to the frontier while
  staying air-gapped. One hard constraint: the 20 evaluation programs must
  be held out of training entirely, or the scores are meaningless. Training
  pairs need to come from elsewhere, such as other internal programs,
  public SAS code, or config 3 outputs that you've reviewed.
- **Config 3: Frontier model with skills.** This is the live-demo
  configuration. The model can invoke skills, such as running PROC CONTENTS
  to get real types, lengths, and labels instead of guessing, or reading
  macro catalogs. It gets ground-truth metadata the other two don't. That
  asymmetry is part of the finding (tool access vs. model size), but state
  it explicitly in the paper.

**3. Low-effort evaluation**

The key design choice: since you're building the 20 gold JSON files, give
them exactly the same schema as the model output. Then most of the scoring
becomes set comparison in Python with no human involvement.

*Automatic scoring of structured fields (no human work)*

- **Variable names:** precision, recall, and F1 per dataset against gold,
  using uppercase exact match.
- **Type/length:** accuracy on matched variables.
- **Macro parameters:**
  - F1 on parameter names.
  - Accuracy on classifying each parameter as positional or keyword.
  - Exact match on defaults after whitespace normalization.
- **Calling programs and input/output datasets:** F1.
- **Schema validity:** the percentage of outputs that parse and validate.
  Small models fail here often, so report it separately.

*Hallucination rate (automatic)*

Any variable, macro, parameter, or dataset name in the output that doesn't
appear anywhere in the source text is flagged as a hallucination. For
config 3, PROC CONTENTS output also counts as a valid source. A simple text
search against the source does this check. This is likely the number your
audience cares about most, and it hands you the hallucination example for
the demo.

*Free-text descriptions (about an hour of human work)*

- **LLM judge.** A judge model scores each generated description against
  the gold version on a 0-2 rubric: 0 means wrong or misleading, 1 means
  vague or partially correct, and 2 means correct and specific. Use a
  different model family from config 3 to avoid self-grading bias.
- **Calibration.** Calibrate the judge once. You blind-score a random
  sample of about 30 descriptions, mixed across configs with the labels
  hidden, then compute your agreement with the judge. If agreement is high,
  trust the judge on the rest.

*Sampling and uncertainty (your "can we sample this?" question)*

- **Unit of analysis.** With 20 programs, the unit of analysis is the
  program, not the variable. Report per-program scores with bootstrap 95%
  confidence intervals, resampling programs about 1,000 times.
- **Repeated runs.** Run each config three times so you can separate model
  variance from program difficulty.
- **Difficulty tags.** Tag each program by difficulty (length, macro count,
  nesting depth) so you can show where the small models break down.
- **Honest reporting.** If the confidence intervals overlap between
  configs, report that as a result.

*Also record*

Record wall-clock time, hardware, and cost per program. The air-gap
argument comes down to one sentence: "Config 2 reaches X% of config 3's
accuracy at Y cost with no data leaving the building."

**Results table**

The rows are the three configs. The columns are:

- Schema validity
- Variable F1
- Macro F1
- Input/output F1
- Hallucination rate
- Description score
- Time per program
- Cost per program
