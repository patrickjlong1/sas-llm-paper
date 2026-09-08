r"""
records.py
==========
Turns one generated doc.md (+ its guardrail report) into the three flat
record shapes that get pushed to SAS as datasets:

  program_summary   -- one row per program
  macro_params      -- one row per macro parameter (often empty: a small
                        untuned model rarely renders this as a clean table)
  data_dictionary   -- one row per documented variable

Deliberately tolerant of messy model output: gemma3:1b's "Macro Reference"
section, for example, is usually a free-text sentence, not the table the
system prompt asked for. Where structure isn't there, the raw text is kept
in a fallback field instead of silently dropping it.
"""

import datetime
import re

from guardrail import _headings, _strip_wrapper


def _section(md, name):
    for head, body in _headings(_strip_wrapper(md)):
        if head.strip().lower().startswith(name.lower()):
            return body.strip()
    return None


def _table_rows(body):
    """Yield tuples of cell text for each '| a | b | c |' row, skipping the
    header and the separator row (plain '---' or markdown-alignment
    ':---'/'---:'/':---:')."""
    if not body:
        return
    for line in body.split("\n"):
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip().strip("`") for c in line.strip("|").split("|")]
        if not cells:
            continue
        if all(re.fullmatch(r":?-+:?", c) for c in cells):
            continue                                    # separator row
        if cells[0].lower() in ("variable", "parameter", ""):
            continue                                    # header row
        yield cells


def parse_full(program_name, doc_md, guardrail_report, model, source_path=None):
    now = datetime.datetime.utcnow().isoformat() + "Z"

    purpose = (_section(doc_md, "purpose") or "").replace("\n", " ").strip()
    macro_body = _section(doc_md, "macro reference") or ""
    macro_rows = list(_table_rows(macro_body))

    macro_name_match = re.search(r"[`%]?(\w+)\s*\(", macro_body)
    macro_name = macro_name_match.group(1) if macro_name_match else ""

    program_summary = {
        "program_name": program_name,
        "macro_name": macro_name,
        "purpose": purpose[:2000],
        "model": model,
        "generated_at": now,
        "source_path": source_path or "",
        "parsed_sections": guardrail_report.get("parsed_sections", 0),
        "truncated": bool(guardrail_report.get("truncated")),
        "parse_warning": bool(guardrail_report.get("parse_warning")),
        "n_flagged_datasets": len(guardrail_report.get("flagged_datasets", [])),
        "n_flagged_params": len(guardrail_report.get("flagged_params", [])),
        "n_flagged_variables": len(guardrail_report.get("flagged_variables", [])),
    }

    flagged_params = set(guardrail_report.get("flagged_params", []))
    macro_params = []
    if len(macro_rows) >= 1 and len(macro_rows[0]) >= 2:
        for row in macro_rows:
            if len(row) < 2:
                continue
            pname = row[0].lstrip("%&").strip()
            macro_params.append({
                "program_name": program_name,
                "macro_name": macro_name,
                "param_name": pname,
                "default_value": row[1] if len(row) > 1 else "",
                "meaning": row[2] if len(row) > 2 else "",
                "guardrail_flagged": pname.lower() in flagged_params,
            })
    elif macro_body:
        macro_params.append({
            "program_name": program_name,
            "macro_name": macro_name,
            "param_name": "",
            "default_value": "",
            "meaning": macro_body[:2000],
            "guardrail_flagged": False,
        })

    outputs_body = _section(doc_md, "outputs") or ""
    output_datasets = re.findall(r"`([A-Za-z_][\w.]*)`", outputs_body)
    primary_output = output_datasets[0] if output_datasets else "UNSPECIFIED"

    flagged_vars = set(guardrail_report.get("flagged_variables", []))
    dict_body = _section(doc_md, "data dictionary") or ""
    data_dictionary = []
    for row in _table_rows(dict_body):
        if len(row) < 2 or not row[0]:
            continue
        var = row[0].upper()
        data_dictionary.append({
            "program_name": program_name,
            "output_dataset": primary_output,
            "variable_name": var,
            "inferred_meaning": row[1] if len(row) > 1 else "",
            "sas_type": row[2] if len(row) > 2 else "",
            "notes": row[3] if len(row) > 3 else "",
            "guardrail_flagged": var in flagged_vars,
        })

    return program_summary, macro_params, data_dictionary
