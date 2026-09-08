r"""
extract.py
==========
Static, regex-based scan of a *real* SAS program to build an allow-list of
identifiers that demonstrably appear in the source: dataset/table names,
macro parameter names, and variable names.

This is the hallucination guardrail for arbitrary SAS programs where there is
no ground-truth spec (unlike seasug-paper's synthetic corpus, where the spec
IS the ground truth). It can't know what a real SAS session would actually
materialize -- for that you'd need 04_oda_harvest.py's approach of running the
program -- but it catches the common failure mode: the model naming a variable
or dataset that never appears anywhere in the file.

Deliberately over-inclusive (better to under-flag than to cry wolf on real
identifiers the regexes didn't anticipate).
"""

import re


def _clean(name):
    return name.strip().strip(".").upper()


def _strip_balanced_parens(s):
    """Drop every parenthesized chunk, including nested ones (e.g. a dataset
    option like `(rename=(_mx=mx2 _mn=mn2))`). A naive `\\(.*?\\)` regex
    applied per whitespace-split token breaks on the inner space *before* the
    parens are stripped, splitting one dataset reference into garbage
    fragments -- this removes parens first, irrespective of nesting depth, so
    the later whitespace split only ever sees bare dataset names."""
    out = []
    depth = 0
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(ch)
    return "".join(out)


def extract_datasets(text):
    ds = set()
    # data <name>; / data <lib>.<name>;
    for m in re.finditer(r"^\s*data\s+([\w.]+(?:\s*\([^)]*\))?)\s*;", text, re.I | re.M):
        ds.add(_clean(m.group(1).split("(")[0]))
    # set/merge <name(s)>
    for m in re.finditer(r"^\s*(?:set|merge)\s+([^;]+);", text, re.I | re.M):
        body = _strip_balanced_parens(m.group(1))
        for tok in re.split(r"\s+", body):
            if tok:
                ds.add(_clean(tok))
    # out=<name> / output out=<name>
    for m in re.finditer(r"\bout\s*=\s*([\w.]+)", text, re.I):
        ds.add(_clean(m.group(1)))
    # proc sql: create table <name>
    for m in re.finditer(r"create\s+table\s+([\w.]+)", text, re.I):
        ds.add(_clean(m.group(1)))
    # proc <x> data=<name>
    for m in re.finditer(r"\bdata\s*=\s*([\w.]+)", text, re.I):
        ds.add(_clean(m.group(1)))
    ds.discard("")
    return {d.split(".")[-1] for d in ds}


def extract_macro_params(text):
    params = set()
    for m in re.finditer(r"%macro\s+\w+\s*\(([^)]*)\)", text, re.I):
        for p in m.group(1).split(","):
            p = p.split("=")[0].strip()
            if p:
                params.add(p.lower())
    return params


_VAR_STMTS = ("length", "input", "var", "by", "class", "keep", "drop",
              "rename", "format", "label", "id", "output")


def extract_variables(text):
    variables = set()

    for stmt in _VAR_STMTS:
        for m in re.finditer(r"^\s*%s\s+([^;]+);" % stmt, text, re.I | re.M):
            body = m.group(1)
            if stmt in ("rename", "format", "label"):
                body = re.sub(r"=[^\s(]*(\([^)]*\))?", " ", body)
            for tok in re.findall(r"[A-Za-z_]\w*", body):
                if tok.lower() not in ("dsd", "truncover", "missing"):
                    variables.add(tok.upper())

    # simple assignment: IDENT = expr;  (also catches derived vars)
    for m in re.finditer(r"^\s*([A-Za-z_]\w*)\s*=\s*[^=;][^;]*;", text, re.M):
        variables.add(m.group(1).upper())

    # proc sql select list: "a.foo as bar" / "b.baz as baz_b"
    for m in re.finditer(r"\bas\s+([A-Za-z_]\w*)", text, re.I):
        variables.add(m.group(1).upper())
    for m in re.finditer(r"select\s+(.*?)\bfrom\b", text, re.I | re.S):
        for tok in re.findall(r"[A-Za-z_]\w*\.([A-Za-z_]\w*)", m.group(1)):
            variables.add(tok.upper())

    return variables


def scan(text):
    """Return the allow-list dict used to check a generated doc against."""
    return {
        "datasets": extract_datasets(text),
        "params": extract_macro_params(text),
        "variables": extract_variables(text),
    }


if __name__ == "__main__":
    import sys
    result = scan(open(sys.argv[1]).read())
    for k, v in result.items():
        print("%s (%d): %s" % (k, len(v), ", ".join(sorted(v))))
