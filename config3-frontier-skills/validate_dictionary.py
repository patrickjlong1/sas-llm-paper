r"""
validate_dictionary.py
=======================
Hallucination guardrail for a dictionary Claude authored directly (as
schema.py's structured JSON). Checks every dataset/variable/macro-param
name in the authored dictionary against two allow-lists, in order of trust:

  1. Ground-truth column metadata (sas_metadata.py's harvest of
     dictionary.columns/dictionary.tables) -- real SAS metadata, the
     strongest signal available. Used when --column-metadata is given. This
     is the asymmetry the plan calls out explicitly: config3 gets to check
     itself against ground truth the other two configs don't have.
  2. extract.py's static regex scan of the source -- always available,
     used as a fallback/supplement since ground-truth metadata can be
     incomplete (program only partially ran, --no-run mode against a
     library that doesn't have every dataset, etc).

Anything in the dictionary that appears in NEITHER is flagged. Macro
parameters are always checked against extract.py only -- SAS metadata
tables have no concept of a macro parameter.

Usage (as a module, from write_dictionary.py):
    from validate_dictionary import validate
    report = validate(dictionary, source_text, column_metadata=cm_or_None)

Usage (standalone):
    python3 validate_dictionary.py --dictionary dict.json --source program.sas \
        [--column-metadata column_metadata.json]
"""

import json

import schema


def _allowed_from_column_metadata(cm):
    datasets, variables = set(), set()
    for row in cm.get("columns", []):
        datasets.add(row["memname"].upper())
        variables.add(row["variable_name"].upper())
    return datasets, variables


def validate(dictionary, source_text, column_metadata=None):
    from extract import scan

    ok, schema_errors = schema.validate(dictionary)

    static = scan(source_text)
    gt_datasets, gt_variables = set(), set()
    ground_truth_used = column_metadata is not None
    if column_metadata:
        gt_datasets, gt_variables = _allowed_from_column_metadata(column_metadata)

    allowed_datasets = static["datasets"] | gt_datasets
    allowed_variables = static["variables"] | gt_variables
    allowed_params = static["params"]

    flagged_datasets = set()
    flagged_variables = set()
    if ok:
        for row in dictionary.get("variable_dictionary", []):
            ds_member = (row.get("dataset") or "").split(".")[-1].upper()
            var = (row.get("name") or "").upper()
            if ds_member and ds_member != "UNSPECIFIED" and ds_member not in allowed_datasets:
                flagged_datasets.add(ds_member)
            if var and var not in allowed_variables and var not in allowed_datasets:
                flagged_variables.add(var)

    flagged_params = set()
    if ok:
        for m in dictionary.get("macro_reference", []):
            for p in m.get("positional_params", []):
                if p.strip().lower() not in allowed_params:
                    flagged_params.add(p.strip().lower())
            for kp in m.get("keyword_params", []):
                p = (kp.get("name") or "").strip().lower()
                if p and p not in allowed_params:
                    flagged_params.add(p)

    return {
        "schema_valid": ok,
        "schema_errors": schema_errors,
        "ground_truth_used": ground_truth_used,
        "flagged_datasets": sorted(flagged_datasets),
        "flagged_variables": sorted(flagged_variables),
        "flagged_params": sorted(flagged_params),
        "n_flagged_datasets": len(flagged_datasets),
        "n_flagged_variables": len(flagged_variables),
        "n_flagged_params": len(flagged_params),
    }


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--dictionary", required=True)
    ap.add_argument("--source", required=True)
    ap.add_argument("--column-metadata", default=None)
    args = ap.parse_args()

    dictionary = json.load(open(args.dictionary))
    source_text = open(args.source).read()
    column_metadata = json.load(open(args.column_metadata)) if args.column_metadata else None

    report = validate(dictionary, source_text, column_metadata)
    print(json.dumps(report, indent=2))
    if not report["ground_truth_used"]:
        print("\n*** No --column-metadata given -- this check ran against the "
              "static source scan ONLY. Run sas_metadata.py first for a real "
              "ground-truth check. ***")
