r"""
build_simulated_notebook.py
===========================
Writes `config3_frontier_skills.SIMULATED.ipynb` next to this script: the
repo's config3 notebook with every cell filled in.

Each filled cell's output starts with a provenance marker:

    [REAL ...]       the cell was actually executed on this box
    [SIMULATED ...]  the cell needs an API key (or would write to the live
                     SAS account); its output is reconstructed

Run `simulate_config3.py` first -- this script reads the console transcripts
and scoring logs it produces.
"""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
SRC_NB = os.path.join(REPO, "config3-frontier-skills", "config3_frontier_skills.ipynb")
OUT_NB = os.path.join(HERE, "config3_frontier_skills.SIMULATED.ipynb")

REAL = "[REAL OUTPUT -- executed on this box, 2026-09-22]"
SIM = "[SIMULATED OUTPUT -- needs ANTHROPIC_API_KEY; see README.md]"

BANNER = """\
> ## ⚠️ This is a SIMULATED copy of the notebook
>
> The repo's own `config3-frontier-skills/config3_frontier_skills.ipynb`
> is unchanged. This copy was filled in on 2026-09-22 with
> `testrun/predicted/config3/`, because this box has **no
> `ANTHROPIC_API_KEY`** — so no cell that calls the model could actually
> run.
>
> Every cell output below is marked:
>
> - **`[REAL OUTPUT ...]`** — the cell was genuinely executed here. That
>   covers all the environment checks, `header_extract.py`, `extract.py`,
>   `sas_metadata.py` against the **live ODA account**, and every
>   `run_eval.py` scoring cell.
> - **`[SIMULATED OUTPUT ...]`** — reconstructed. That is Setup 2's model
>   check, the three `claude_driver.py` cells, and the `push_to_oda.py`
>   cell (not run: it writes to your live SAS library).
>
> The ground-truth harvest under `testrun/predicted/config3/metadata/` is
> **real**: all 20 programs were submitted to SAS OnDemand and their
> `dictionary.columns` read back. The scoring cells are the real scorer
> over simulated predictions — the numbers are arithmetic on made-up
> model output, so do not publish them.
>
> Paths in the driver/scoring output were rewritten to the notebook's own
> (`../results/preds/...`); the files themselves live under
> `testrun/predicted/config3/` so nothing fake lands in `results/`.
"""


def stream(text, marker):
    body = marker + "\n" + text.rstrip("\n") + "\n"
    return [{"output_type": "stream", "name": "stdout", "text": body.splitlines(True)}]


def read(name):
    return open(os.path.join(HERE, name)).read()


def rewrite_paths(text):
    return (text.replace(HERE + "/preds/", "../results/preds/")
                .replace(HERE + "/metadata", "claude-runs/metadata")
                .replace(HERE + "/", "../results/outputs/")
                .replace(os.path.join(REPO, "eval-programs"), "../eval-programs"))


CELL2 = """\
  ../eval-programs/programs                OK
  ../eval-programs/gold                    OK
  ../results                               OK
  ../.claude/skills/sas-data-dictionary    OK

interpreter:       /internal/venvs/main/bin/python3
  saspy:           True
  anthropic:       True (installed in the next cell if False)
java:              /internal/sas-doc-gen-project/jre/bin/java
~/.authinfo:       found
ANTHROPIC_API_KEY: set"""

CELL4 = """\
anthropic 1.7.0 | saspy 5.108.7 | pandas 3.0.1"""

CELL7 = """\
model:   claude-opus-5 | Claude Opus 5
context: 200000 in / 64000 out"""

CELL10 = """\
prog900_estab -> ../eval-programs/programs/prog900_estab.sas"""

CELL12 = """\
Using SAS Config named: oda
SAS Connection established. Subprocess id is 3124172

connected: Access Method         = IOM
SAS Config name       = oda
SAS Config file       = /internal/sas-doc-gen-project/config3-frontier-skills/config/sascfg_personal.py
WORK Path             = /saswork/SAS_work96F70001CB65_odaws02-usw2.oda.sas.com/SAS_workF1640001CB65_odaws02-usw2.oda.sas.com/
SAS Version           = 9.04.01M8P02222023
SASPy Version         = 5.108.7
Teach me SAS          = False
Batch                 = False
Results               = Pandas
SAS Session Encoding  = utf-8
Python Encoding value = utf-8
SAS process Pid value = 117605
SASsession started    = Tue Sep 22 10:16:29 2026


SAS Connection terminated. Subprocess id was 3124172
wrote /tmp/column_metadata.json (39 column rows across 6 table(s))
tables:  ['AGG1', 'D1', 'D2', 'HOLD', 'J1', 'O1']
columns: 39 | labelled: 0
errors:  none
[
 {
  "program_name": "prog900_estab",
  "libname": "WORK",
  "memname": "AGG1",
  "variable_name": "ST",
  "type": "char",
  "length": 2,
  "format": "",
  "informat": "",
  "label": "",
  "varnum": 1
 },
 {
  "program_name": "prog900_estab",
  "libname": "WORK",
  "memname": "AGG1",
  "variable_name": "SEP",
  "type": "num",
  "length": 8,
  "format": "",
  "informat": "",
  "label": "",
  "varnum": 2
 },
 {
  "program_name": "prog900_estab",
  "libname": "WORK",
  "memname": "AGG1",
  "variable_name": "HIR",
  "type": "num",
  "length": 8,
  "format": "",
  "informat": "",
  "label": "",
  "varnum": 3
 }
]"""

CELL14 = """\
{
  "header_found": false,
  "fields": {},
  "raw_header_text": "",
  "inline_glosses": {}
}
datasets (6): AGG1, D1, D2, HOLD, J1, O1
params (3): lb, p, thr
variables (16): AGG1, DROP, EMPL, ESTID, HIR, JO, OUT, PER, SELECT, SEP, SEPR, ST, SUM, WGTF, _FREQ_, _TYPE_"""

CELL28 = """\
column_metadata.jsonl  data_dictionary.jsonl  macro_params.jsonl  program_summary.jsonl
program_summary: 20 row(s) in local catalog
macro_params: 60 row(s) in local catalog
data_dictionary: 254 row(s) in local catalog
column_metadata: 741 row(s) in local catalog
Using SAS Config named: oda
SAS Connection established. Subprocess id is 3142118
wrote SASUSER.PROGRAM_SUMMARY (20 rows, 9 cols)
wrote SASUSER.MACRO_PARAMS (60 rows, 8 cols)
wrote SASUSER.DATA_DICTIONARY (254 rows, 8 cols)
wrote SASUSER.COLUMN_METADATA (741 rows, 10 cols)
done
SAS Connection terminated. Subprocess id was 3142118"""


def cell17_output():
    run = json.load(open(os.path.join(HERE, "claude-runs", "prog900_estab.run.json")))
    doc = open(os.path.join(HERE, "claude-runs", "prog900_estab.dictionary.json")).read()
    return (json.dumps(run, indent=2)
            + "\n\n--- authored dictionary (first 60 lines) ---\n"
            + "\n".join(doc.splitlines()[:60]))


def main():
    nb = json.load(open(SRC_NB))
    cells = nb["cells"]

    def put(i, text, marker):
        cells[i]["outputs"] = stream(text, marker)
        cells[i]["execution_count"] = put.n
        put.n += 1
    put.n = 1

    put(2, CELL2, REAL + " -- the ANTHROPIC_API_KEY line is shown as it reads with the key exported")
    put(4, CELL4, REAL)
    cells[6]["outputs"] = []            # sets env vars, prints nothing
    cells[6]["execution_count"] = put.n
    put.n += 1
    put(7, CELL7, SIM)
    put(10, CELL10, REAL)
    put(12, CELL12, REAL + " -- live SAS OnDemand session, 18.5 s")
    put(14, CELL14, REAL)
    put(16, rewrite_paths(read("cell16-console.txt")), SIM)
    put(17, cell17_output(), SIM)
    put(20, rewrite_paths(read("cell20-console.txt")), SIM)
    put(22, rewrite_paths(read("cell22-console.txt")), SIM)
    put(24, rewrite_paths(read("cell24-scoring.txt")),
        REAL + " -- the real scorer, over SIMULATED predictions and the REAL SAS harvest")
    put(25, rewrite_paths(read("cell25-scoring.txt")),
        REAL + " -- the real scorer, over SIMULATED predictions")
    put(26, rewrite_paths(read("cell26-table.txt")),
        REAL + " -- the real table builder, over SIMULATED predictions")
    put(28, CELL28, SIM + " -- NOT run: this writes to your live SASUSER library")

    cells.insert(1, {"cell_type": "markdown", "metadata": {},
                     "source": BANNER.splitlines(True)})
    json.dump(nb, open(OUT_NB, "w"), indent=1)
    print("wrote", OUT_NB)
    subprocess.run([sys.executable, "-c",
                    "import json,sys;json.load(open(sys.argv[1]));print('valid notebook JSON')",
                    OUT_NB], check=True)


if __name__ == "__main__":
    main()
