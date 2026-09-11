r"""
records.py
==========
Flattens one config's structured JSON output (schema.py's shape) into the
three flat row shapes pushed to SAS as datasets. No markdown parsing here --
every config in this project now authors the schema JSON directly (config1
via a JSON-mode prompt to Gemma, config3 via Claude authoring it by hand),
so this is just a straight flatten + join-lists-into-strings step for SAS's
flat-column datasets.
"""

import datetime


def parse_full(program_name, doc_json, guardrail_report, model, source_path=None):
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    schema_valid = bool(doc_json is not None and not guardrail_report.get("schema_errors"))
    ps = doc_json.get("program_summary", {}) if (doc_json and schema_valid) else {}
    if not isinstance(ps, dict):
        ps = {}

    program_summary = {
        "program_name": program_name,
        "description": (ps.get("description") or "")[:2000],
        "input_datasets": "; ".join(ps.get("input_datasets", []) or []),
        "output_datasets": "; ".join(ps.get("output_datasets", []) or []),
        "model": model,
        "generated_at": now,
        "source_path": source_path or "",
        "schema_valid": schema_valid,
        "n_flagged": len(guardrail_report.get("flagged", [])),
    }

    # A schema-INVALID payload (small models fail this often -- see plan
    # section 3) may have any shape at all in its would-be macro/variable
    # lists -- string entries instead of objects, missing keys, etc. Don't
    # try to flatten garbage; report the failure via schema_valid above and
    # leave macro_rows/dict_rows empty rather than raising.
    if not schema_valid:
        return program_summary, [], []

    flagged = set(guardrail_report.get("flagged", []))
    macro_rows = []
    for m in doc_json.get("macro_reference", []):
        if not isinstance(m, dict):
            continue
        name = m.get("name", "")
        called_by = "; ".join(x for x in m.get("called_by", []) if isinstance(x, str))
        for p in m.get("positional_params", []):
            if not isinstance(p, str):
                continue
            macro_rows.append({
                "program_name": program_name, "macro_name": name, "param_name": p,
                "kind": "positional", "default_value": "", "purpose": m.get("purpose", ""),
                "called_by": called_by,
                "guardrail_flagged": ("macro:%s" % p) in flagged or ("param:%s" % p) in flagged,
            })
        for kp in m.get("keyword_params", []):
            if not isinstance(kp, dict):
                continue
            pname = kp.get("name", "")
            macro_rows.append({
                "program_name": program_name, "macro_name": name, "param_name": pname,
                "kind": "keyword", "default_value": kp.get("default", ""), "purpose": m.get("purpose", ""),
                "called_by": called_by,
                "guardrail_flagged": ("param:%s" % pname) in flagged,
            })
        if not m.get("positional_params") and not m.get("keyword_params"):
            macro_rows.append({
                "program_name": program_name, "macro_name": name, "param_name": "",
                "kind": "", "default_value": "", "purpose": m.get("purpose", ""),
                "called_by": called_by, "guardrail_flagged": False,
            })

    dict_rows = []
    for v in doc_json.get("variable_dictionary", []):
        if not isinstance(v, dict):
            continue
        var = (v.get("name") or "").upper()
        dict_rows.append({
            "program_name": program_name,
            "output_dataset": v.get("dataset", "UNSPECIFIED"),
            "variable_name": var,
            "type": v.get("type", ""),
            "length": v.get("length"),
            "label": v.get("label", ""),
            "derivation": v.get("derivation", ""),
            "guardrail_flagged": ("variable:%s" % var) in flagged,
        })

    return program_summary, macro_rows, dict_rows
