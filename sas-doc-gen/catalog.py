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

TABLES = ("program_summary", "macro_params", "data_dictionary")


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


def upsert_program(catalog_dir, program_name, program_summary_row, macro_rows, dict_rows):
    """Replace any existing rows for program_name in all three tables with
    the newly parsed ones."""
    existing_summary = [r for r in load(catalog_dir, "program_summary")
                        if r["program_name"] != program_name]
    existing_summary.append(program_summary_row)
    _save(catalog_dir, "program_summary", existing_summary)

    existing_macro = [r for r in load(catalog_dir, "macro_params")
                      if r["program_name"] != program_name]
    existing_macro.extend(macro_rows)
    _save(catalog_dir, "macro_params", existing_macro)

    existing_dict = [r for r in load(catalog_dir, "data_dictionary")
                     if r["program_name"] != program_name]
    existing_dict.extend(dict_rows)
    _save(catalog_dir, "data_dictionary", existing_dict)


if __name__ == "__main__":
    import sys
    d = sys.argv[1] if len(sys.argv) > 1 else "catalog"
    for t in TABLES:
        rows = load(d, t)
        print("%s: %d rows" % (t, len(rows)))
