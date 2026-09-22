# sas-doc-gen: LLM-generated documentation for legacy SAS code

Implements `PLAN.md` end to end: three ways to generate a variable
dictionary + macro reference + program summary for undocumented legacy SAS,
scored against a 20-program held-out eval set with mostly-automatic
metrics. Every config is prompted for and produces the exact same JSON
schema (`eval-programs/schema.py`) -- only the model and its access to
ground truth differ, so the three-way comparison is fair.

## Layout

```
sas-doc-gen-project/
├── PLAN.md                     the design doc this project implements
├── jre/                          shared portable JRE (SASPy's IOM connection
│                                needs Java; no sudo/system Java on this box).
│                                Not project code -- runtime infra, like
│                                /internal/e2b-gemma/ below.
├── .claude/skills/
│   └── sas-data-dictionary/     the Claude Code skill config3 runs as
│
├── config1-gemma-cpu/            Config 1: Gemma, CPU-only, zero-shot.
│                                Model runtime lives at /internal/e2b-gemma/
│                                (Ollama + weights, ~9.6 GB -- infra, not
│                                code, so not duplicated here).
│                                See SETUP.md for the model + ODA setup.
│
├── config2-qlora-gpu/            Config 2: QLoRA fine-tune of the SAME base
│                                model, on a free GPU (Colab T4 or similar).
│                                See SETUP.md for the free-GPU + ODA setup.
│
├── config3-frontier-skills/      Config 3: frontier model (Claude) with
│                                skills -- real PROC CONTENTS/dictionary.
│                                columns ground truth via SASPy.
│                                See SETUP.md for the ODA + API/Code setup.
│
├── eval-programs/                20 held-out SAS programs (bad names, no
│                                headers, on purpose) + gold JSON. Built by
│                                corpus_gen.py from one spec, then rewritten
│                                by hand on 2026-09-21 so the eval set does
│                                not share templates with config2's training
│                                corpus -- see its README.
│
└── results/                      Scoring: schema validity, F1s, hallucination
                                 rate, LLM-judge description scores, bootstrap
                                 CI, difficulty tags, corpus provenance, and
                                 the final results table.
```

## Where this currently stands

**There are no current results in the repo.** The 20 eval programs were
rewritten by hand on 2026-09-21 (`eval-programs/README.md`), which
invalidated every score computed before then; those are quarantined under
`results/outputs/stale-2026-09-17/` with a writeup of what went wrong.
Config2's QLoRA adapter has been trained but never scored. Read
`results/README.md` before quoting any number from this repo.

Scoring now stamps a fingerprint of the eval corpus next to every
`.scores.jsonl` (`results/provenance.py`), and the results table marks a
row **STALE** instead of printing numbers that no longer describe the
corpus on disk.

## Quickstart

Each config's notebook runs the whole thing end to end, including on a
free Colab runtime -- that's the shortest path:

| notebook | runtime |
|---|---|
| `config1-gemma-cpu/config1_gemma_cpu.ipynb` | Colab **CPU** (or this box's Ollama server) |
| `config2-qlora-gpu/config2_qlora_gpu.ipynb` | Colab **T4 GPU** |
| `config3-frontier-skills/config3_frontier_skills.ipynb` | a Claude Code session (the model *is* the config) |

Each opens with a bootstrap cell that clones the whole repo and `cd`s into
its own folder -- pulling a single config folder on its own leaves every
`../eval-programs/...` and `../results/...` path broken.

From a shell instead:

```bash
# 1. (Re)generate the eval set -- NOT a maintenance step: it overwrites the
#    hand-authored programs/ and gold/ with template output. See
#    eval-programs/README.md.
cd eval-programs && python3 corpus_gen.py --n 20 --seed 777 --id-offset 900 \
    --sas-out programs --gold-out gold

# 2. Run config1 (Gemma, CPU) over all 20 -- see config1-gemma-cpu/SETUP.md first.
#    --backend ollama needs a local Ollama server; --backend hf needs none.
cd ../config1-gemma-cpu && python3 document_sas.py --dir ../eval-programs/programs \
    --backend ollama --out ../results/preds/config1-gemma-cpu \
    --catalog ../results/catalog/config1-gemma-cpu

# 3. Run config2 (QLoRA) -- needs a GPU, see config2-qlora-gpu/SETUP.md.
# 4. Run config3 (Claude + skills) -- see config3-frontier-skills/SETUP.md,
#    or just ask Claude Code to "document these SAS programs" from the repo root.

# 5. Score each config (also writes the corpus-provenance sidecar):
cd ../results
python3 run_eval.py --config config1-gemma-cpu \
    --pred-dir preds/config1-gemma-cpu --out-prefix outputs/config1-gemma-cpu

# 6. Print the plan's results table -- one call, all rows:
python3 run_eval.py --table --rows rows.example.json
```

See each folder's own `README.md`/`SETUP.md` for the full walkthrough --
they're written to be self-contained (each config folder carries its own
copy of the small shared modules -- `schema.py`, `extract.py` -- so you can
hand any single folder to someone else and it still runs).

## On SAS OnDemand for Academics (ODA) credentials

Every config's SETUP.md covers this, but the shape is the same everywhere:
create `~/.authinfo` yourself (never paste credentials into a chat
session; on Colab use its Secrets panel and let the notebook write the
file into the ephemeral session), and the `iomhost` region list in each
`sascfg_personal.py` is already filled in for a confirmed US-region/usw2
account. ODA is free for academic/non-commercial use.

**Java.** `jre/` at the repo root is a portable JRE so this box needs no
system Java or sudo -- but it is 136 MB and **gitignored**, so a fresh
clone (Colab included) does not have it. Each `sascfg_personal.py` uses
the bundled JRE when it exists and falls back to whatever `java` is on
`PATH` otherwise; on Colab, `apt-get install default-jdk` in a cell (it
runs as root) and the fallback takes over.

## History

This project folder previously held two separate, overlapping efforts
(`sas-doc-gen/`'s local zero-shot pipeline and `seasug-paper/`'s QLoRA
research pipeline) that grew organically and duplicated a fair amount of
logic under different schemas. It's been reorganized into the three-config
structure above, with one unified JSON schema all three configs share --
see `PLAN.md` for the design this restructuring follows.
