# sas-doc-gen — Status & Next Steps

_Last updated: 2026-09-07_

## Where this fits

Two separate projects now exist:

- **`seasug-paper/`** — the original research pipeline: generate a synthetic
  SAS+doc corpus, QLoRA-fine-tune a model, evaluate hallucination rate against
  ground truth. Needs a GPU (Colab T4); **cannot run on this server** (no
  `nvidia-smi`, AMD APU, 4.7 GB RAM).
- **`sas-doc-gen/`** (new, this session) — a practical tool that runs *today*
  on this server: zero-shot prompts the local `gemma3:1b` (Ollama, CPU,
  already running) to document a real SAS program, with a static-analysis
  guardrail against invented identifiers.

## What's built and working

```
sas-doc-gen/
├── extract.py       regex scan of real SAS source -> allow-list of
│                     datasets / macro params / variables
├── prompts.py        system prompt + message builder (zero-shot format
│                     matches 02_qlora_finetune.py's training shape)
├── guardrail.py       parses model's claimed identifiers, flags anything
│                     not found by extract.py
├── document_sas.py    CLI: sas file in -> doc.md + guardrail.json out
└── README.md          full writeup of design decisions and limitations
```

Usage: `python3 document_sas.py path/to/program.sas`

## Validated this session (not just written — actually run and checked)

| # | Test | Result |
|---|---|---|
| 1 | Zero-shot on `estab`-domain program | Correct format, 5/5 documented variables real, 0 guardrail flags |
| 2 | Guardrail vs. a doc with 2 invented datasets | Correctly flagged `_Y1`/`_Y2` as not in source |
| 3 | Few-shot (multi-turn), 1 exemplar | **Failed** — model fabricated an entirely different, fictional SAS program |
| 4 | Few-shot (single-turn), 1 exemplar | **Failed** — model degenerated into repetition, hit token cap, produced nothing parseable |
| 5 | Zero-shot on `hhold`-domain program (2nd, different program) | Caught a genuine hallucinated dataset (`d4`, doesn't exist) and a truncation-induced repetition loop — guardrail flagged both correctly |

## Bugs found and fixed along the way

1. **Guardrail false-clean**: parser only recognized `## Heading` markdown; a
   chatty/bold-formatted response parsed to zero sections and was reported as
   "no flags" — indistinguishable from actually clean. Fixed: emits an
   explicit `parse_warning` when nothing was parsed.
2. **Fence-stripping truncation bug**: a naive non-greedy regex for stripping
   a wrapping ` ```markdown ` fence latched onto a *nested* code sample's
   closing backticks instead, silently dropping everything after it (often
   the Data Dictionary). Fixed: only strips fence markers at the literal
   start/end of the response.
3. **Few-shot fabrication**: alternating synthetic user/assistant turns for
   exemplars caused the 1B model to lose the thread and invent a fictional
   program. Root-caused to context/coherence limits, not a prompt bug.
4. **Zero-shot regression**: my first fix for #3 added a `"### Now document
   this program"` framing line to *all* prompts, including zero-shot, which
   made the model treat it as a heading to imitate and echo the prompt back
   in a loop. Reverted zero-shot to the minimal `` ```sas ... ``` `` format.

## Hard findings about the model itself

- **`gemma3:1b` zero-shot is a genuine "best guess," not a reliable one.**
  It gets real identifiers' *meanings* wrong even on toy synthetic input
  (e.g. `WGTF`, a sampling weight, guessed as "Work Time"). The guardrail
  only catches invented names, never wrong meanings — every dictionary entry
  needs a human glance.
- **Few-shot makes this specific model worse, not better**, tested twice,
  two different failure modes (fabrication, then repetition-loop). `--fewshot`
  defaults to `0` for this reason.
- **Performance on this CPU-only box**: ~11 tok/s prompt eval, ~4.5 tok/s
  generation → 2-9 minutes per document. This is a batch tool, not
  interactive, here.

## Next steps (not yet done)

1. **Run it on a real, non-synthetic SAS program** you actually have —
   everything so far has used the synthetic corpus's own eval set, which is
   the easiest possible case since it's exactly the style the corpus was
   designed around. Real legacy SAS will stress `extract.py`'s regexes
   (under-flagging risk) more than anything tested yet.
2. **Decide if `gemma3:1b` quality is good enough to use as-is**, or if it's
   worth trying `gemma3:4b` (already Ollama-installable, not yet tested here
   — expect roughly 4x slower, and RAM is tight at 4.7 GB total).
3. **If neither 1B nor 4B quality is acceptable**, the real fix is finishing
   the paper's plan: run `seasug-paper/scripts/02_qlora_finetune.py` on a
   free Colab T4 (per your original note — swap the base model to a 4B Gemma
   variant there, since the script currently defaults to Qwen2.5-Coder-3B),
   push the adapter to Hugging Face, then merge + convert to GGUF and serve
   it through this same local Ollama install (`ollama create`) — documented
   in `sas-doc-gen/README.md`'s "Upgrade path" section.
4. **Batch mode**: `document_sas.py` currently takes one file at a time;
   trivial to add a `--dir` flag to loop over a folder of real programs if
   you want to run this against a whole legacy codebase overnight.
