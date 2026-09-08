r"""
04_oda_harvest.py
=================
Runs each generated program on SAS OnDemand for Academics via SASPy and harvests
REAL metadata from dictionary.columns, so 03_evaluate.py can score against what
SAS actually created rather than against the generator's spec.

This is the step that makes the experiment credible: the hallucination metric is
measured against a live SAS session, not against my own JSON.

Colab prerequisites (one cell, before this script):

    !apt-get -qq install default-jdk > /dev/null
    !pip -q install saspy
    # SASPy ships the encryption jars; ODA needs them on the classpath since 9.4M7.

Then drop config/sascfg_personal.py into the saspy install dir, e.g.:

    import saspy, os, shutil
    shutil.copy('config/sascfg_personal.py', os.path.dirname(saspy.__file__))

...and write ~/.authinfo (chmod 600) containing one line:

    oda user YOUR_ODA_EMAIL password YOUR_ODA_PASSWORD

Use Colab Secrets to inject those, never literals in the notebook.

Two lines in sascfg_personal.py are the only ones you should need to touch:
the iomhost list (must match YOUR ODA region) and the java path.

    python 04_oda_harvest.py --sas-dir ../data/eval_sas --out ../data/oda_metadata.json

Licence note: ODA is for academic / non-commercial use. Run synthetic programs
only, and check current terms before putting anything work-adjacent on it.
"""

import argparse
import json
import os
import re

import saspy


def output_datasets(program_text):
    """Datasets the program writes to WORK or to &lb (which we bind to work)."""
    out = set()
    out |= set(re.findall(r"^data\s+&lb\.\.(\w+)", program_text, flags=re.M | re.I))
    out |= set(re.findall(r"output\s+out=(\w+)", program_text, flags=re.I))
    return {d.lower() for d in out}


def macro_params(program_text):
    m = re.search(r"%macro\s+\w+\s*\(([^)]*)\)", program_text, flags=re.I)
    if not m:
        return set()
    return {p.split("=")[0].strip().lower() for p in m.group(1).split(",") if p.strip()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sas-dir", default="../data/eval_sas")
    ap.add_argument("--out", default="../data/oda_metadata.json")
    args = ap.parse_args()

    sas = saspy.SASsession()          # reads SAS_config_names=['oda']
    print(sas)

    records = []
    for fname in sorted(os.listdir(args.sas_dir)):
        if not fname.endswith(".sas"):
            continue
        text = open(os.path.join(args.sas_dir, fname)).read()

        sas.submit("proc datasets lib=work kill nolist; quit;")
        res = sas.submit(text)

        log = res["LOG"]
        if re.search(r"^ERROR", log, flags=re.M):
            print("ERRORS in", fname, "-- skipping")
            print("\n".join(l for l in log.split("\n") if l.startswith("ERROR"))[:500])
            continue

        meta = sas.sd2df(sas.submit(
            "proc sql; create table _meta as "
            "select memname, name, type, length, label, format "
            "from dictionary.columns where libname='WORK' "
            "and memname not like '\\_%' escape '\\'; quit;"
        ) and sas.sasdata("_meta", "work"))

        vars_by_ds = {}
        for _, row in meta.iterrows():
            vars_by_ds.setdefault(row["memname"].lower(), set()).add(row["name"].upper())

        wanted = output_datasets(text)
        records.append({
            "program_name": fname,
            "datasets": sorted(wanted & set(vars_by_ds)),
            "params": sorted(macro_params(text)),
            "vars": {k: sorted(v) for k, v in vars_by_ds.items() if k in wanted},
            "lineage": re.findall(r"data\s+_t(\d+)", text, flags=re.I),
        })
        print("harvested", fname, "->", list(records[-1]["vars"]))

    # 03_evaluate.py expects sets; json gives lists, so normalise on load there.
    with open(args.out, "w") as fh:
        for r in records:
            r["datasets"] = set(r["datasets"])
            r["params"] = set(r["params"])
            r["vars"] = {k: set(v) for k, v in r["vars"].items()}
        json.dump([{**r,
                    "datasets": sorted(r["datasets"]),
                    "params": sorted(r["params"]),
                    "vars": {k: sorted(v) for k, v in r["vars"].items()}}
                   for r in records], fh, indent=2)

    sas.endsas()
    print("wrote", args.out)


if __name__ == "__main__":
    main()
