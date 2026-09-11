r"""
write_dictionary.py
====================
Validates and catalogs a dictionary that Claude authored directly (as
schema.py's structured JSON), for a real SAS program. This is the
frontier-model counterpart to config1's document_sas.py -- there is no local
model API call here, because the caller (Claude, following the
sas-data-dictionary skill, see the repo root's .claude/skills/) IS the model
doing the writing. This script's job is just: check what was written against
ground truth, then persist it to the same local JSONL catalog push_to_oda.py
already knows how to push to SAS.

Expected --dictionary JSON: exactly schema.py's shape (program_summary /
macro_reference / variable_dictionary) -- see the skill file for the
field-by-field authoring contract, including when to set a variable's
derivation from a real SAS `label` vs. your own inference from usage.

Usage:
    python3 write_dictionary.py --program-name d1_prog --source path/to/d1_prog.sas \
        --dictionary dictionary.json --column-metadata column_metadata.json \
        --catalog catalog/

--column-metadata is optional but strongly recommended -- without it,
validation falls back to the static source scan only (see
validate_dictionary.py). When given, its "columns" rows are ALSO upserted
into the catalog's column_metadata table so the ground truth persists to
SAS alongside your inferred dictionary (push_to_oda.py writes it as
COLUMN_METADATA).
"""

import argparse
import json
import os
import sys

import catalog
from records import parse_full
from validate_dictionary import validate


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--program-name", required=True)
    ap.add_argument("--source", required=True, help="path to the .sas source file")
    ap.add_argument("--dictionary", required=True,
                    help="JSON file matching schema.py's shape, authored directly by Claude")
    ap.add_argument("--column-metadata", default=None,
                    help="JSON output of sas_metadata.py -- ground truth column info")
    ap.add_argument("--generated-by", default="claude")
    ap.add_argument("--catalog", default="catalog")
    args = ap.parse_args()

    if not os.path.exists(args.source):
        sys.exit("source not found: %s" % args.source)
    source_text = open(args.source).read()

    dictionary = json.load(open(args.dictionary))
    for key in ("program_summary", "macro_reference", "variable_dictionary"):
        dictionary.setdefault(key, {} if key == "program_summary" else [])

    column_metadata = None
    if args.column_metadata:
        column_metadata = json.load(open(args.column_metadata))

    report = validate(dictionary, source_text, column_metadata)

    if not report["schema_valid"]:
        sys.exit("--dictionary does not match schema.py's shape:\n  "
                 + "\n  ".join(report["schema_errors"]))

    unified_flagged = (["variable:%s" % v for v in report["flagged_variables"]]
                       + ["dataset:%s" % d for d in report["flagged_datasets"]]
                       + ["param:%s" % p for p in report["flagged_params"]])
    guardrail_report = {"flagged": unified_flagged, "schema_errors": []}

    program_summary_row, macro_rows, dict_rows = parse_full(
        args.program_name, dictionary, guardrail_report, args.generated_by,
        source_path=os.path.abspath(args.source))
    program_summary_row["ground_truth_used"] = report["ground_truth_used"]

    column_metadata_rows = None
    if column_metadata:
        column_metadata_rows = column_metadata.get("columns", [])
        for row in column_metadata_rows:
            row.setdefault("program_name", args.program_name)

    catalog.upsert_program(args.catalog, args.program_name, program_summary_row,
                           macro_rows, dict_rows, column_metadata_rows=column_metadata_rows)

    print("catalog: %s -> program_summary=1, macro_params=%d, data_dictionary=%d%s (%s)"
          % (args.catalog, len(macro_rows), len(dict_rows),
             ", column_metadata=%d" % len(column_metadata_rows) if column_metadata_rows is not None else "",
             args.program_name))

    if not report["ground_truth_used"]:
        print("\n*** No column metadata supplied -- validated against the static "
              "source scan only. Run sas_metadata.py first and pass "
              "--column-metadata for a real ground-truth check: the static scan "
              "can MISS real identifiers (e.g. an assignment inside an `if ... "
              "then` branch), so a flag here may be a real variable the regex "
              "missed, not a hallucination -- verify by hand before assuming "
              "either way. ***")

    if report["n_flagged_datasets"] or report["n_flagged_variables"] or report["n_flagged_params"]:
        print("\n*** GUARDRAIL FLAGS (claimed but not found in %s) ***"
              % ("ground truth or the static source scan" if report["ground_truth_used"]
                 else "the static source scan"))
        if report["flagged_datasets"]:
            print("  datasets: ", ", ".join(report["flagged_datasets"]))
        if report["flagged_variables"]:
            print("  variables:", ", ".join(report["flagged_variables"]))
        if report["flagged_params"]:
            print("  params:   ", ", ".join(report["flagged_params"]))
    elif report["ground_truth_used"]:
        print("no guardrail flags.")


if __name__ == "__main__":
    main()
