r"""
push_to_oda.py
===============
Reads the local, offline catalog (catalog.py's three JSONL files, built up by
running document_sas.py over however many programs) and writes them to SAS
OnDemand for Academics as three real SAS datasets, via SASPy:

    PROGRAM_SUMMARY   -- one row per documented program
    MACRO_PARAMS      -- one row per macro parameter (where the model
                         rendered one; often a free-text fallback row instead)
    DATA_DICTIONARY   -- one row per documented variable

Each run REPLACES all three datasets in the target library with the full,
current contents of the local catalog (the catalog itself is already
upserted per-program by document_sas.py, so this script doesn't need its own
merge logic -- it just mirrors the catalog state to SAS).

Libref: defaults to SASUSER, not WORK. ODA auto-assigns both at session
start -- WORK is wiped when the session ends, SASUSER is permanent storage
tied to your account and survives across sessions with zero extra setup
(no LIBNAME statement, no path to know). That's what "save as SAS datasets"
means in practice on ODA, so it's the default rather than something you have
to opt into. Pass --libname/--libpath only if you want a different,
custom-path library instead.

Setup this needs before it can run (see config/sascfg_personal.py, NONE of
this is done yet on this box):
  1. Fill in the CHANGE ME iomhost list in config/sascfg_personal.py for your
     ODA region.
  2. Create ~/.authinfo (chmod 600): "oda user YOUR_EMAIL password YOUR_PW"

Run (must use the venv with saspy installed):
    /internal/venvs/main/bin/python3 push_to_oda.py --catalog catalog/
    # custom library instead of the default SASUSER:
    /internal/venvs/main/bin/python3 push_to_oda.py --catalog catalog/ \
        --libname mylib --libpath '/home/youruser/casuser/sasdocgen'
"""

import argparse
import os
import sys

import pandas as pd

import catalog

CFGFILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "config", "sascfg_personal.py")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default="catalog")
    ap.add_argument("--libname", default="sasuser",
                    help="SAS libref to write to. 'sasuser' (default) is "
                         "ODA's auto-assigned permanent per-account library -- "
                         "persists across sessions with no extra setup. 'work' "
                         "is also auto-assigned but wiped when the session "
                         "ends. Any other libref needs --libpath.")
    ap.add_argument("--libpath", default=None,
                    help="filesystem path on the ODA server for --libname, "
                         "required unless --libname is 'sasuser' or 'work' "
                         "(both already auto-assigned by every ODA session).")
    ap.add_argument("--cfgfile", default=CFGFILE)
    args = ap.parse_args()

    try:
        import saspy
    except ImportError:
        sys.exit("saspy not installed in this interpreter. Run this with:\n"
                 "  /internal/venvs/main/bin/python3 push_to_oda.py ...")

    AUTO_LIBREFS = ("work", "sasuser")     # pre-assigned by every ODA session
    if args.libname.lower() not in AUTO_LIBREFS and not args.libpath:
        sys.exit("--libname %r isn't one of ODA's auto-assigned libraries "
                 "(%s) -- pass --libpath too." % (args.libname, ", ".join(AUTO_LIBREFS)))

    tables = {t: catalog.load(args.catalog, t) for t in catalog.TABLES}
    for t, rows in tables.items():
        print("%s: %d row(s) in local catalog" % (t, len(rows)))
    if not any(tables.values()):
        sys.exit("Nothing in the local catalog yet -- run document_sas.py first.")

    sas = saspy.SASsession(cfgfile=args.cfgfile)
    print(sas)

    if args.libname.lower() not in AUTO_LIBREFS:
        sas.submit("libname %s '%s';" % (args.libname, args.libpath))

    dataset_names = {
        "program_summary": "PROGRAM_SUMMARY",
        "macro_params": "MACRO_PARAMS",
        "data_dictionary": "DATA_DICTIONARY",
    }

    for table, rows in tables.items():
        sasname = dataset_names[table]
        if not rows:
            print("skipping %s (no rows)" % sasname)
            continue
        df = pd.DataFrame(rows)
        sas.df2sd(df, table=sasname, libref=args.libname)
        print("wrote %s.%s (%d rows, %d cols)"
              % (args.libname, sasname, len(df), len(df.columns)))

    sas.endsas()
    print("done")


if __name__ == "__main__":
    main()
