r"""
guardrail.py
============
Hallucination guardrail for config1's structured JSON output (no markdown
round-trip needed anymore -- the model is prompted for the schema directly,
see prompts.py). Checks every name the model claimed against extract.py's
static regex scan of the REAL source. Anything claimed but never found in
the program text is flagged as unverified/likely hallucinated.

This is a heuristic safety net, not proof of correctness: extract.py's
regexes can miss real identifiers (under-flagging is possible), and a model
can also just be wrong about MEANING while getting the literal name right
(this catches invented names, not bad inferences).
"""

from extract import scan
import schema


def check(doc_json, source_text):
    ok, errors = schema.validate(doc_json) if doc_json is not None else (False, ["no output produced"])
    if not ok:
        return {"schema_valid": False, "schema_errors": errors, "flagged": [],
                "n_claimed": 0, "n_flagged": 0}

    allowed = scan(source_text)
    flagged = []

    for v in doc_json["variable_dictionary"]:
        name = (v.get("name") or "").upper()
        if name and name not in allowed["variables"] and name not in allowed["datasets"]:
            flagged.append("variable:%s" % name)

    for d in doc_json["program_summary"].get("input_datasets", []) + doc_json["program_summary"].get("output_datasets", []):
        member = d.split(".")[-1].upper()
        if member and member not in allowed["datasets"]:
            flagged.append("dataset:%s" % member)

    for m in doc_json["macro_reference"]:
        for p in m.get("positional_params", []):
            if p.lower() not in allowed["params"]:
                flagged.append("param:%s" % p)
        for kp in m.get("keyword_params", []):
            pname = kp.get("name", "")
            if pname.lower() not in allowed["params"]:
                flagged.append("param:%s" % pname)

    n_claimed = (len(doc_json["variable_dictionary"])
                + sum(len(m.get("positional_params", [])) + len(m.get("keyword_params", []))
                     for m in doc_json["macro_reference"]))

    return {"schema_valid": True, "schema_errors": [], "flagged": sorted(set(flagged)),
            "n_claimed": n_claimed, "n_flagged": len(set(flagged))}
