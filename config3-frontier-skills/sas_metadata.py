r"""
sas_metadata.py
================
Ground-truth column/table metadata for a SAS program, pulled from SAS
ITSELF via SASPy -- `dictionary.columns` and `dictionary.tables` (the
PROC SQL "dictionary" views; the same underlying metadata PROC CONTENTS
prints, but structured and filterable). This is the anti-hallucination
backbone of the frontier-model dictionary pipeline: a variable's real name,
type, length, format, informat, and label come from here, not from a
model's guess.

Two modes:

  --run (default)     Submit the program's own source in the target SAS
                       session first (so it actually materializes its
                       output datasets), then harvest metadata for
                       everything left in --libname (default WORK).
                       Reports any ERROR lines from the SAS log without
                       aborting -- a program can partially fail (e.g. a
                       later proc step errors out) and still have
                       materialized useful earlier datasets worth
                       documenting.

  --no-run             Skip submitting the program; just query
                       dictionary.columns/dictionary.tables against
                       --libname as it already stands (the datasets were
                       already built by a previous run, or you're
                       connecting to a permanent library where they already
                       live). Use this for "poor" legacy code that's
                       unsafe or infeasible to blindly re-execute (hardcoded
                       prod paths, external dependencies not present in your
                       sandbox, etc).

Why dictionary.columns/tables over PROC CONTENTS directly: PROC CONTENTS is
built for a human reading one report at a time; the dictionary.* views are
plain tables you can filter/join/select with ordinary PROC SQL and pull
straight into a dataframe with sas.sd2df, in one query covering every
dataset in a library at once. See references in the sas-data-dictionary
skill for the fuller PROC CONTENTS vs dictionary.* writeup, incl. when
PROC CONTENTS' interactive output still earns its keep.

Usage:
    /internal/venvs/main/bin/python3 sas_metadata.py program.sas
    /internal/venvs/main/bin/python3 sas_metadata.py program.sas --libname sasuser --no-run
    /internal/venvs/main/bin/python3 sas_metadata.py program.sas --out column_metadata.json

Output: JSON to stdout (or --out), shape:
    {
      "program_name": "program",
      "libname": "WORK",
      "run_attempted": true,
      "run_errors": [...],           # raw ERROR lines from the SAS log, [] if clean
      "tables": {"D1": {"nobs": 4, "nvars": 5, "table_label": ""}, ...},
      "columns": [
        {"program_name": "program", "libname": "WORK", "memname": "D1",
         "variable_name": "ESTID", "type": "char", "length": 12,
         "format": "", "informat": "", "label": "", "varnum": 1}, ...
      ]
    }

`columns` is already the flat row shape catalog.py's "column_metadata"
table expects -- pass this file straight to write_dictionary.py
--column-metadata.
"""

import argparse
import json
import os
import re
import sys

CFGFILE_DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "config", "sascfg_personal.py")


def _require_saspy():
    try:
        import saspy
    except ImportError:
        sys.exit("saspy not installed in this interpreter. Run this with:\n"
                 "  /internal/venvs/main/bin/python3 sas_metadata.py ...")
    return saspy


def _str_or_blank(v):
    """SAS blank char values come back from sd2df() as NaN (a float), not
    None or "" -- `v or ""` is truthy for NaN and then crashes on
    .strip(), so check the type directly instead of truthiness."""
    return v.strip() if isinstance(v, str) else ""


def harvest(sas, program_name, libname, run_attempted, exclude_pattern=None):
    """Query dictionary.columns/dictionary.tables for everything currently
    in `libname`. Assumes the caller already submitted the program (if
    --run) so its output datasets exist in this session."""
    lib_upper = libname.upper()

    exclude_clause = ""
    if exclude_pattern:
        exclude_clause = " and memname not like '%s' escape '\\'" % exclude_pattern.replace("'", "''")

    sql = (
        "proc sql noprint;"
        "create table work._sdgcols as "
        "select memname, name, type, length, format, informat, label, varnum "
        "from dictionary.columns "
        "where libname='%s'%s "
        "order by memname, varnum;"
        "create table work._sdgtabs as "
        "select memname, nobs, nvar, memlabel as table_label "
        "from dictionary.tables "
        "where libname='%s' and memtype='DATA'%s;"
        "quit;" % (lib_upper, exclude_clause, lib_upper, exclude_clause)
    )
    res = sas.submit(sql)
    if re.search(r"^ERROR", res["LOG"], flags=re.M):
        errs = [l for l in res["LOG"].split("\n") if l.startswith("ERROR")]
        raise RuntimeError("dictionary query failed:\n" + "\n".join(errs))

    cols_df = sas.sd2df("_sdgcols", libref="work")
    tabs_df = sas.sd2df("_sdgtabs", libref="work")
    sas.submit("proc datasets lib=work nolist; delete _sdgcols _sdgtabs; quit;")

    tables = {}
    for _, row in tabs_df.iterrows():
        tables[row["memname"].strip()] = {
            "nobs": int(row["nobs"]) if row["nobs"] == row["nobs"] else None,  # NaN check
            "nvars": int(row["nvar"]) if row["nvar"] == row["nvar"] else None,
            "table_label": _str_or_blank(row["table_label"]),
        }

    columns = []
    for _, row in cols_df.iterrows():
        memname = row["memname"].strip()
        columns.append({
            "program_name": program_name,
            "libname": lib_upper,
            "memname": memname,
            "variable_name": row["name"].strip(),
            "type": "char" if str(row["type"]).strip() == "1" else
                    ("num" if str(row["type"]).strip() == "2" else str(row["type"]).strip()),
            "length": int(row["length"]) if row["length"] == row["length"] else None,
            "format": _str_or_blank(row["format"]),
            "informat": _str_or_blank(row["informat"]),
            "label": _str_or_blank(row["label"]),
            "varnum": int(row["varnum"]) if row["varnum"] == row["varnum"] else None,
        })

    return {
        "program_name": program_name,
        "libname": lib_upper,
        "run_attempted": run_attempted,
        "tables": tables,
        "columns": columns,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sas_file")
    ap.add_argument("--libname", default="work",
                    help="library to harvest metadata from after (optionally) "
                         "running the program. 'work' (default) is where an "
                         "ordinary DATA step lands unless it names a libref.")
    ap.add_argument("--run", dest="run", action="store_true", default=True,
                    help="submit the program before harvesting (default).")
    ap.add_argument("--no-run", dest="run", action="store_false",
                    help="skip submitting the program; query --libname as-is "
                         "(use when the code shouldn't/can't be re-executed "
                         "in this session -- hardcoded prod paths, missing "
                         "external inputs, etc).")
    ap.add_argument("--exclude-pattern", default=None,
                    help="SQL LIKE pattern (with backslash as escape char) of "
                         "memnames to exclude, e.g. 'SDG\\_%%' -- default: "
                         "exclude nothing, since legacy code often "
                         "underscore-prefixes its real outputs too.")
    ap.add_argument("--cfgfile", default=CFGFILE_DEFAULT)
    ap.add_argument("--out", default=None, help="write JSON here instead of stdout")
    args = ap.parse_args()

    saspy = _require_saspy()
    program_name = os.path.splitext(os.path.basename(args.sas_file))[0]
    source = open(args.sas_file).read()

    # sascfg_personal.py's __file__ gets relocated to a tempdir by saspy's
    # cfgfile-override import, so it can't find the repo root on its own --
    # tell it explicitly, from OUR __file__ (this script isn't relocated).
    os.environ.setdefault(
        "SAS_DOC_GEN_PROJECT_ROOT",
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    sas = saspy.SASsession(cfgfile=args.cfgfile)
    print("connected:", sas, file=sys.stderr)

    run_errors = []
    if args.run:
        if args.libname.lower() == "work":
            sas.submit("proc datasets lib=work kill nolist; quit;")
        res = sas.submit(source)
        run_errors = [l for l in res["LOG"].split("\n") if l.startswith("ERROR")]
        if run_errors:
            print("*** %d ERROR line(s) in SAS log -- program partially or "
                  "fully failed; harvesting whatever DID materialize ***" % len(run_errors),
                  file=sys.stderr)
            for e in run_errors[:20]:
                print(" ", e, file=sys.stderr)

    result = harvest(sas, program_name, args.libname, args.run, args.exclude_pattern)
    result["run_errors"] = run_errors

    sas.endsas()

    out_text = json.dumps(result, indent=2)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(out_text)
        print("wrote", args.out, "(%d column rows across %d table(s))"
              % (len(result["columns"]), len(result["tables"])), file=sys.stderr)
    else:
        print(out_text)


if __name__ == "__main__":
    main()
