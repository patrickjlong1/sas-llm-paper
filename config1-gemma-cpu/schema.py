r"""
schema.py
=========
The ONE JSON output schema all three configs (Gemma-CPU, QLoRA, frontier-
with-skills) are prompted for and scored against. Identical copy lives in
config1-gemma-cpu/, config3-frontier-skills/, and results/ so each folder
stays runnable on its own -- this file is the canonical source; if you edit
the schema, copy the change to the other three.

    {
      "program_name": "prog900_estab.sas",
      "program_summary": {
        "description": "<1-2 sentences>",
        "input_datasets": ["WORK.D1", ...],     // libref.member
        "output_datasets": ["WORK.O1", ...]      // libref.member
      },
      "macro_reference": [
        {
          "name": "dostep1",
          "positional_params": ["p"],
          "keyword_params": [{"name": "lb", "default": "work"}],
          "purpose": "<1 sentence>",
          "called_by": ["prog900_estab.sas"]       // programs that invoke this macro
        }
      ],
      "variable_dictionary": [
        {
          "name": "ESTID",
          "dataset": "WORK.O1",                    // libref.member it appears in
          "type": "char" | "num",
          "length": 12,                             // int or null if unknown
          "label": "Establishment identifier",
          "derivation": "<1 sentence: how this value comes to be>"
        }
      ]
    }

No 3rd-party jsonschema dependency -- this is a small, fixed shape and a
hand-rolled check keeps every config's requirements.txt short (and lets
config1 run fully air-gapped with nothing but `requests`).
"""

REQUIRED_TOP_KEYS = ("program_summary", "macro_reference", "variable_dictionary")
_SUMMARY_KEYS = ("description", "input_datasets", "output_datasets")
_MACRO_KEYS = ("name", "positional_params", "keyword_params", "purpose", "called_by")
_VAR_KEYS = ("name", "dataset", "type", "length", "label", "derivation")


def _err(errors, path, msg):
    errors.append("%s: %s" % (path, msg))


def validate(obj):
    """Returns (is_valid, errors). Deliberately structural (right keys, right
    types) not semantic -- semantic correctness (real names, right meanings)
    is what score.py's F1/hallucination checks are for."""
    errors = []
    if not isinstance(obj, dict):
        return False, ["root: not a JSON object"]

    for k in REQUIRED_TOP_KEYS:
        if k not in obj:
            _err(errors, "root", "missing required key %r" % k)
    if errors:
        return False, errors

    ps = obj["program_summary"]
    if not isinstance(ps, dict):
        _err(errors, "program_summary", "not an object")
    else:
        for k in _SUMMARY_KEYS:
            if k not in ps:
                _err(errors, "program_summary", "missing key %r" % k)
        if "description" in ps and not isinstance(ps["description"], str):
            _err(errors, "program_summary.description", "not a string")
        for k in ("input_datasets", "output_datasets"):
            if k in ps and not (isinstance(ps[k], list) and all(isinstance(x, str) for x in ps[k])):
                _err(errors, "program_summary.%s" % k, "not a list of strings")

    mr = obj["macro_reference"]
    if not isinstance(mr, list):
        _err(errors, "macro_reference", "not a list")
    else:
        for i, m in enumerate(mr):
            p = "macro_reference[%d]" % i
            if not isinstance(m, dict):
                _err(errors, p, "not an object")
                continue
            for k in _MACRO_KEYS:
                if k not in m:
                    _err(errors, p, "missing key %r" % k)
            if "name" in m and not isinstance(m["name"], str):
                _err(errors, p + ".name", "not a string")
            if "positional_params" in m and not (isinstance(m["positional_params"], list)
                    and all(isinstance(x, str) for x in m["positional_params"])):
                _err(errors, p + ".positional_params", "not a list of strings")
            if "keyword_params" in m:
                if not isinstance(m["keyword_params"], list):
                    _err(errors, p + ".keyword_params", "not a list")
                else:
                    for j, kp in enumerate(m["keyword_params"]):
                        if not (isinstance(kp, dict) and "name" in kp and "default" in kp):
                            _err(errors, "%s.keyword_params[%d]" % (p, j),
                                 "must be an object with 'name' and 'default'")
            if "called_by" in m and not (isinstance(m["called_by"], list)
                    and all(isinstance(x, str) for x in m["called_by"])):
                _err(errors, p + ".called_by", "not a list of strings")

    vd = obj["variable_dictionary"]
    if not isinstance(vd, list):
        _err(errors, "variable_dictionary", "not a list")
    else:
        for i, v in enumerate(vd):
            p = "variable_dictionary[%d]" % i
            if not isinstance(v, dict):
                _err(errors, p, "not an object")
                continue
            for k in _VAR_KEYS:
                if k not in v:
                    _err(errors, p, "missing key %r" % k)
            if "name" in v and not isinstance(v["name"], str):
                _err(errors, p + ".name", "not a string")
            if "dataset" in v and not isinstance(v["dataset"], str):
                _err(errors, p + ".dataset", "not a string")
            if "type" in v and v["type"] not in ("char", "num", None):
                _err(errors, p + ".type", "must be 'char', 'num', or null")
            if "length" in v and not (v["length"] is None or isinstance(v["length"], int)):
                _err(errors, p + ".length", "must be an int or null")

    return (len(errors) == 0), errors


PROMPT_SCHEMA_BLOCK = """Return ONLY a single JSON object (no markdown fences, no prose before or
after it) with exactly this shape:

{
  "program_summary": {
    "description": "<1-2 plain-English sentences: what this program does>",
    "input_datasets": ["<LIBREF.MEMBER>", ...],
    "output_datasets": ["<LIBREF.MEMBER>", ...]
  },
  "macro_reference": [
    {
      "name": "<macro name>",
      "positional_params": ["<param with no default, required at call time>", ...],
      "keyword_params": [{"name": "<param>", "default": "<its default value, as written>"}],
      "purpose": "<1 sentence>",
      "called_by": ["<program file name(s) that invoke this macro>"]
    }
  ],
  "variable_dictionary": [
    {
      "name": "<VARIABLE NAME, uppercase>",
      "dataset": "<LIBREF.MEMBER this variable appears in>",
      "type": "char" or "num",
      "length": <integer, or null if you cannot determine it>,
      "label": "<short label -- use a real SAS LABEL if the code has one>",
      "derivation": "<1 sentence: how this value is computed or where it comes from>"
    }
  ]
}

Hard rules:
- Never name a variable, dataset, or macro parameter that does not appear in the program text.
- One variable_dictionary row per variable per OUTPUT dataset (a dataset written to a
  permanent library, or the program's final result) -- not every intermediate/temp dataset.
- If unsure of a value, use your best inference from the code rather than omitting the field,
  except "length": use null there if truly unknown.
"""
