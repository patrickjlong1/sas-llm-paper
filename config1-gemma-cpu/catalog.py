r"""
catalog.py
==========
Local, offline accumulation of records.py's output across every program
you've run document_sas.py on. Three JSONL files, one per table shape.
Re-running document_sas.py on a program you've already documented UPSERTS
(replaces that program's rows) rather than duplicating them.

No SAS/network connection needed for any of this -- push_to_oda.py is the
only piece that talks to SAS, and it just reads these files.
"""

import json
import os

TABLES = ("program_summary", "macro_params", "data_dictionary", "column_metadata")

# Tables with exactly one row per program (replaced outright on upsert) vs.
# tables with many rows per program (existing rows for that program are
# dropped, then the new rows are appended).
_SINGLE_ROW_TABLES = {"program_summary"}


def _path(catalog_dir, table):
    return os.path.join(catalog_dir, table + ".jsonl")


def load(catalog_dir, table):
    p = _path(catalog_dir, table)
    if not os.path.exists(p):
        return []
    with open(p) as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _save(catalog_dir, table, rows):
    os.makedirs(catalog_dir, exist_ok=True)
    with open(_path(catalog_dir, table), "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def upsert_table(catalog_dir, table, program_name, rows):
    """Replace any existing rows for program_name in one table with `rows`
    (a single dict for a one-row-per-program table like program_summary, or
    a list of dicts otherwise)."""
    existing = [r for r in load(catalog_dir, table) if r["program_name"] != program_name]
    if table in _SINGLE_ROW_TABLES:
        existing.append(rows)
    else:
        existing.extend(rows)
    _save(catalog_dir, table, existing)


def upsert_program(catalog_dir, program_name, program_summary_row, macro_rows, dict_rows,
                   column_metadata_rows=None):
    """Replace any existing rows for program_name across program_summary,
    macro_params, and data_dictionary with the newly parsed ones.
    column_metadata_rows (the ground-truth harvest from sas_metadata.py) is
    optional and upserted separately if given -- it has no doc.md
    counterpart to parse it out of."""
    upsert_table(catalog_dir, "program_summary", program_name, program_summary_row)
    upsert_table(catalog_dir, "macro_params", program_name, macro_rows)
    upsert_table(catalog_dir, "data_dictionary", program_name, dict_rows)
    if column_metadata_rows is not None:
        upsert_table(catalog_dir, "column_metadata", program_name, column_metadata_rows)


if __name__ == "__main__":
    import sys
    d = sys.argv[1] if len(sys.argv) > 1 else "catalog"
    for t in TABLES:
        rows = load(d, t)
        print("%s: %d rows" % (t, len(rows)))
