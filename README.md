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
│                                headers, on purpose) + perfect gold JSON,
│                                both rendered from the same spec so gold
│                                is correct by construction.
│
└── results/                      Scoring: schema validity, F1s, hallucination
                                 rate, LLM-judge description scores, bootstrap
                                 CI, difficulty tags, and the final results
                                 table.
```

## Quickstart

```bash
# 1. Generate the eval set (already done once -- only needed to regenerate):
cd eval-programs && python3 corpus_gen.py --n 20 --seed 777 --id-offset 900 \
    --sas-out programs --gold-out gold

# 2. Run config1 (Gemma, CPU) over all 20 -- see config1-gemma-cpu/SETUP.md first:
cd ../config1-gemma-cpu && python3 document_sas.py --dir ../eval-programs/programs \
    --out ../results/preds/config1-gemma-cpu --catalog /tmp/config1_catalog

# 3. Run config2 (QLoRA) -- needs a GPU, see config2-qlora-gpu/SETUP.md.
# 4. Run config3 (Claude + skills) -- see config3-frontier-skills/SETUP.md,
#    or just ask Claude Code to "document these SAS programs" from the repo root.

# 5. Score everything:
cd ../results
python3 score.py --gold-dir ../eval-programs/gold --pred-dir preds/config1-gemma-cpu \
    --source-dir ../eval-programs/programs --out outputs/config1_run1.scores.jsonl
python3 bootstrap_ci.py --runs outputs/config1_run1.scores.jsonl --all-metrics
```

See each folder's own `README.md`/`SETUP.md` for the full walkthrough --
they're written to be self-contained (each config folder carries its own
copy of the small shared modules -- `schema.py`, `extract.py` -- so you can
hand any single folder to someone else and it still runs).

## On SAS OnDemand for Academics (ODA) credentials

Every config's SETUP.md covers this, but the shape is the same everywhere:
create `~/.authinfo` yourself (never paste credentials into a chat
session), the `iomhost` region list in each `config/sascfg_personal.py` is
already filled in for a confirmed US-region/usw2 account, and a portable
JRE at `jre/` (shared, repo root) means no system Java or sudo is needed.
ODA is free for academic/non-commercial use.

## History

This project folder previously held two separate, overlapping efforts
(`sas-doc-gen/`'s local zero-shot pipeline and `seasug-paper/`'s QLoRA
research pipeline) that grew organically and duplicated a fair amount of
logic under different schemas. It's been reorganized into the three-config
structure above, with one unified JSON schema all three configs share --
see `PLAN.md` for the design this restructuring follows.
