r"""
guardrail.py
============
Pulls identifier claims out of a generated markdown doc (same shape of parser
as seasug-paper's 03_evaluate.py) and checks them against extract.py's static
scan of the actual source. Anything claimed but never found in the program
text gets flagged as unverified/likely hallucinated.

This is a heuristic safety net, not proof of correctness: extract.py's regexes
can miss real identifiers (under-flagging is possible), and a model can also
just be wrong about MEANING while getting the literal name right (this catches
invented names, not bad inferences). Read the flagged list, don't just trust
its absence.
"""

import re


def _strip_wrapper(md):
    """Models (especially small/untuned ones) sometimes wrap the whole answer
    in a ```markdown fence. Strip ONLY a fence marker that opens the very
    first line / closes the very last line -- do not try to pair up an
    opening and closing ``` by regex, since a genuine nested code sample
    (e.g. a ```sas snippet in the Macro reference section) has its own closing
    fence that a naive non-greedy match will latch onto instead, truncating
    everything after it."""
    text = md.strip()
    text = re.sub(r"^```(?:markdown|md)?[ \t]*\n", "", text)
    text = re.sub(r"\n```[ \t]*$", "", text)
    return text


_SECTION_PATTERN = re.compile(
    r"^(?:##\s*|\*\*)\s*"
    r"(Purpose|Inputs|Outputs|Macro Reference|Processing Sequence|Lineage|"
    r"Side Effects(?: and Cautions)?|Data Dictionary)"
    r"\**:?[ \t]*",
    re.M | re.I,
)


def _headings(md):
    """Section boundaries, matched by known section NAME rather than by
    markup style -- a small model may render 'Purpose' as '## Purpose',
    '**Purpose:**', or mix styles with stray extra headings (e.g. a made-up
    title) in between. Only text between two recognized section names counts
    as a section body, so junk headings don't get treated as sections and
    don't get absorbed into a real section's body either."""
    matches = list(_SECTION_PATTERN.finditer(md))
    sections = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(md)
        sections.append((m.group(1), md[start:end]))
    return sections


def parse_doc(md):
    out = {"datasets": set(), "params": set(), "vars": set(), "parsed_sections": 0}

    md = _strip_wrapper(md)
    sections = _headings(md)
    out["parsed_sections"] = len(sections)
    for head, body in sections:
        head = head.strip().lower()

        if head.startswith("outputs"):
            out["datasets"] |= set(re.findall(r"`([A-Za-z_][\w.]*)`", body))

        elif head.startswith("macro reference"):
            for row in re.findall(r"^\|\s*`?(\w+)`?\s*\|", body, flags=re.M):
                if row.lower() not in ("parameter", "---"):
                    out["params"].add(row.lower())

        elif head.startswith("data dictionary"):
            for line in body.split("\n"):
                m = re.match(r"^\|\s*`?(\w+)`?\s*\|", line)
                if m and m.group(1).lower() not in ("variable", "---"):
                    out["vars"].add(m.group(1).upper())

    return out


def check(doc_md, source_text):
    from extract import scan
    allowed = scan(source_text)
    claimed = parse_doc(doc_md)

    flagged_ds = sorted(d.upper() for d in claimed["datasets"]
                        if d.upper() not in allowed["datasets"])
    flagged_params = sorted(p for p in claimed["params"]
                            if p not in allowed["params"])
    flagged_vars = sorted(v for v in claimed["vars"]
                          if v not in allowed["variables"] and v not in allowed["datasets"])

    return {
        "flagged_datasets": flagged_ds,
        "flagged_params": flagged_params,
        "flagged_variables": flagged_vars,
        "n_claimed_vars": len(claimed["vars"]),
        "n_flagged_vars": len(flagged_vars),
        "parsed_sections": claimed["parsed_sections"],
        "parse_warning": ("could not find any '## Section' headings -- the model "
                          "likely ignored the format instructions; this report "
                          "covers nothing and should NOT be read as \"clean\"")
                         if claimed["parsed_sections"] == 0 else None,
    }
