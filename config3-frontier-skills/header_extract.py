r"""
header_extract.py
==================
Best-effort extraction of human-authored context from a SAS program: a
leading header comment block (if the shop has one) plus scattered inline
comments elsewhere in the file. This is a *secondary* signal, not the
primary one -- real legacy SAS is frequently undocumented (the bundled
demo_programs/ have zero header comments and single-letter variable names
like v1/c1), so this script is written to degrade gracefully to "found
nothing" rather than to guess.

Ground truth about the DATA (types, lengths, real labels/formats) comes from
sas_metadata.py querying dictionary.columns/dictionary.tables instead --
that's real SAS metadata, not a text-pattern guess. This script only helps
with the MEANING side: whatever a human already wrote down, in whatever
inconsistent format they wrote it in.

Two things it looks for:

1. Header block -- the run of comments (/* ... */ blocks and/or leading
   "* ...;" statement comments) that sits before the first executable/macro
   statement. Within that block, pulls out "Key: value" style fields for a
   generous list of common header field names (Program, Title, Author,
   Purpose, Description, Input(s), Output(s), Owner, Contact, Version,
   Date/Created/Modified, Notes) -- case-insensitive, tolerant of ":" or "-"
   as the separator, and tolerant of a value that continues on following
   comment lines until the next recognized field or a blank line.
2. Inline glosses -- trailing "/* comment */" text that sits on the same
   line as a variable-defining statement (an assignment, or a LENGTH/INPUT/
   LABEL statement), keyed by the identifier that line defines. This is
   often the ONLY documentation in terse legacy code, e.g.:
       nv2 = (v2 - mn2) / (mx2 - mn2);   /* min-max normalized v2 */
   catches {"NV2": "min-max normalized v2"}.

Usage:
    python3 header_extract.py path/to/program.sas
    python3 header_extract.py path/to/program.sas --json-only   # no pretty print
"""

import json
import re

_FIELD_NAMES = (
    "program", "title", "system", "author", "owner", "contact", "version",
    "created", "date", "modified", "last modified", "updated",
    "purpose", "description", "summary", "overview",
    "input", "inputs", "output", "outputs", "dependencies", "dependency",
    "notes", "note", "assumptions", "warning", "warnings",
)
_FIELD_PATTERN = re.compile(
    r"^\s*(?:\*+|/\*+)?\s*(%s)\s*[:\-]\s*(.*)$"
    % "|".join(re.escape(f) for f in sorted(_FIELD_NAMES, key=len, reverse=True)),
    re.I,
)
_BLANK_COMMENT_LINE = re.compile(r"^\s*[\*/]*\s*$")

_STATEMENT_KEYWORDS = re.compile(
    r"^\s*(data|proc|%macro|%let|libname|filename|options|title\d?)\b",
    re.I,
)


def _strip_comment_markers(line):
    line = re.sub(r"^\s*/\*+", "", line)
    line = re.sub(r"\*+/\s*$", "", line)
    line = re.sub(r"^\s*\*+", "", line)
    line = re.sub(r";\s*$", "", line)
    return line.strip()


def _leading_comment_block(text):
    """Return the raw text of every comment (/* */ or leading '* ;' style)
    that appears before the first real statement keyword. Stops at the first
    line that looks like DATA/PROC/%MACRO/%LET/etc outside a comment."""
    lines = text.split("\n")
    out = []
    in_block_comment = False
    for line in lines:
        stripped = line.strip()
        if in_block_comment:
            out.append(line)
            if "*/" in line:
                in_block_comment = False
            continue
        if stripped.startswith("/*"):
            out.append(line)
            if "*/" not in stripped:
                in_block_comment = True
            continue
        if stripped.startswith("*") and stripped.endswith(";"):
            out.append(line)
            continue
        if stripped == "":
            out.append(line)
            continue
        if _STATEMENT_KEYWORDS.match(stripped):
            break
        # Anything else non-comment this early means there's no clean header
        # block (e.g. a bare statement without a keyword we recognize) --
        # stop rather than risk pulling in program body text.
        break
    return "\n".join(out)


def parse_header(text):
    block = _leading_comment_block(text)
    if not block.strip():
        return {"header_found": False, "fields": {}, "raw_header_text": ""}

    lines = [_strip_comment_markers(l) if not l.strip().startswith("/*") and not l.strip().endswith("*/")
             else l for l in block.split("\n")]

    fields = {}
    current_key = None
    for raw in block.split("\n"):
        line = _strip_comment_markers(raw)
        if not line:
            current_key = None
            continue
        m = _FIELD_PATTERN.match(raw)
        if m:
            key = m.group(1).strip().lower()
            key = {"inputs": "input", "outputs": "output", "last modified": "modified",
                   "note": "notes", "dependency": "dependencies", "warning": "warnings"}.get(key, key)
            val = m.group(2).strip()
            fields[key] = val
            current_key = key
        elif current_key and line:
            fields[current_key] = (fields[current_key] + " " + line).strip()

    found = any(fields.values())
    return {
        "header_found": found,
        "fields": fields,
        "raw_header_text": block.strip(),
    }


_INLINE_DEFN = re.compile(
    r"^\s*(?:length\s+)?([A-Za-z_]\w*)\s*(?:\$?\s*\d*\s*)?=?\s*[^;]*;\s*/\*(.*?)\*/\s*$",
    re.I,
)


def parse_inline_glosses(text):
    """One-line '<code>; /* comment */' pairs, keyed by the first identifier
    on the line. Deliberately simple (single-line only, first ident only) --
    this is a hint source, not a parser; multi-line statements or comments
    are just skipped rather than guessed at."""
    glosses = {}
    for line in text.split("\n"):
        m = _INLINE_DEFN.match(line)
        if not m:
            continue
        ident, comment = m.group(1), m.group(2).strip()
        if not comment or ident.lower() in ("run", "quit", "then", "else", "do", "end"):
            continue
        glosses[ident.upper()] = comment
    return glosses


def extract(text):
    result = parse_header(text)
    result["inline_glosses"] = parse_inline_glosses(text)
    return result


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("sas_file")
    ap.add_argument("--json-only", action="store_true")
    args = ap.parse_args()

    result = extract(open(args.sas_file).read())
    if args.json_only:
        print(json.dumps(result))
    else:
        print(json.dumps(result, indent=2))
