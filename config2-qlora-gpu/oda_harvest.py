r"""
oda_harvest.py
================
Runs each eval program on SAS OnDemand for Academics via SASPy and harvests
REAL metadata from dictionary.columns -- lets results/score.py's
hallucination check count a real SAS-materialized column as a valid source
even if extract.py's static regex scan missed it (same idea as config3's
sas_metadata.py, standalone here so this folder doesn't depend on
config3-frontier-skills/ to run).

Writes, per program, a small text blob of "MEMNAME.VARNAME type length
label" lines -- pass that file as `--extra-source` to results/score.py so
config2's hallucination rate isn't measured against the static scan alone.

Colab prerequisites (one cell, before this script) -- see SETUP.md:

    !apt-get -qq install default-jdk > /dev/null
    !pip -q install saspy

...then drop sascfg_personal.py (this folder) next to your saspy install,
and write ~/.authinfo (chmod 600) -- see SETUP.md for both, via Colab
Secrets, never literals in the notebook.

    python3 oda_harvest.py --sas-dir ../eval-programs/programs --out ../data/oda_metadata

Licence note: ODA is for academic/non-commercial use. These are synthetic
programs, which is fine, but check current terms before putting anything
work-adjacent on it.
"""

import argparse
import json
import os
import re
import sys

CFGFILE_DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sascfg_personal.py")


def harvest_one(sas, program_name, source_text, libname="work"):
    sas.submit("proc datasets lib=%s kill nolist; quit;" % libname)
    res = sas.submit(source_text)
    log = res["LOG"]
    run_errors = [l for l in log.split("\n") if l.startswith("ERROR")]

    sql = ("proc sql noprint; create table work._sdgcols as "
          "select memname, name, type, length, label from dictionary.columns "
          "where libname='%s'; quit;" % libname.upper())
    sas.submit(sql)
    df = sas.sd2df("_sdgcols", libref="work")
    sas.submit("proc datasets lib=work nolist; delete _sdgcols; quit;")

    columns = []
    for _, row in df.iterrows():
        columns.append({
            "memname": row["memname"].strip(),
            "variable_name": row["name"].strip(),
            "type": "char" if str(row["type"]).strip() == "1" else "num",
            "length": int(row["length"]) if row["length"] == row["length"] else None,
            "label": (row["label"] or "").strip() if row["label"] else "",
        })
    return {"program_name": program_name, "run_errors": run_errors, "columns": columns}


def as_text(harvest):
    lines = []
    for c in harvest["columns"]:
        lines.append("%s.%s %s %s %s" % (c["memname"].upper(), c["variable_name"].upper(),
                                         c["type"], c["length"], c["label"]))
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sas-dir", default="../eval-programs/programs")
    ap.add_argument("--out", default="../data/oda_metadata",
                    help="directory: writes <program>.json and <program>.txt per program")
    ap.add_argument("--cfgfile", default=CFGFILE_DEFAULT)
    args = ap.parse_args()

    try:
        import saspy
    except ImportError:
        sys.exit("saspy not installed. pip install -r requirements.txt first.")

    os.makedirs(args.out, exist_ok=True)
    sas = saspy.SASsession(cfgfile=args.cfgfile)
    print(sas)

    for fname in sorted(os.listdir(args.sas_dir)):
        if not fname.endswith(".sas"):
            continue
        program_name = os.path.splitext(fname)[0]
        text = open(os.path.join(args.sas_dir, fname)).read()

        harvest = harvest_one(sas, program_name, text)
        if harvest["run_errors"]:
            print("*** ERRORS in", fname, "-- harvesting whatever DID materialize ***")
            for e in harvest["run_errors"][:10]:
                print(" ", e)

        with open(os.path.join(args.out, program_name + ".json"), "w") as fh:
            json.dump(harvest, fh, indent=2)
        with open(os.path.join(args.out, program_name + ".txt"), "w") as fh:
            fh.write(as_text(harvest))
        print("harvested", fname, "->", len(harvest["columns"]), "column(s)")

    sas.endsas()
    print("wrote per-program JSON + text to", args.out)


if __name__ == "__main__":
    main()
