r"""
prompts.py
==========
System prompt and few-shot exemplar selection for the local, un-tuned
gemma3:1b model. No fine-tuning happens on this box (no GPU here) -- this is
in-context learning: a handful of (SAS -> doc) pairs from seasug-paper's
synthetic corpus, shown to the base model so it imitates the target doc
format on a *real* program it has never seen.

If a QLoRA adapter is ever trained on Colab and converted to GGUF for local
Ollama serving, this few-shot scaffolding becomes optional (the fine-tuned
model has the format baked in) but is harmless to keep as a belt-and-braces
nudge.
"""

import json
import os

CORPUS_DEFAULT = "/internal/seasug-paper/scripts/train.jsonl"

SYSTEM = (
    "You document legacy SAS production code for a data analyst who has never "
    "seen this program before. Given a SAS program, return markdown with these "
    "sections in order: Purpose, Inputs, Outputs, Macro reference, Processing "
    "sequence, Lineage, Side effects and cautions, Data dictionary.\n\n"
    "Hard rules:\n"
    "- Never name a variable, dataset, or macro parameter that does not appear "
    "in the program text.\n"
    "- If you are guessing what a variable or abbreviation MEANS (as opposed to "
    "quoting its literal name), mark that guess with [INFERRED].\n"
    "- The Data dictionary must be one markdown table per output dataset with "
    "columns: Variable, Inferred meaning, Type, Notes.\n"
    "- Keep the Lineage section to a short arrow chain of dataset/step names "
    "actually present in the program.\n\n"
    "Output format -- follow exactly, no exceptions:\n"
    "- Output ONLY the markdown document. No preamble, no code fence around the "
    "whole thing, no closing remarks or offers to refine.\n"
    "- Each of the 8 sections MUST start with a level-2 heading exactly like "
    "'## Purpose' (two hash marks, one space, the exact section name). Do not "
    "use bold text as a substitute for a heading."
)


def load_fewshot(n=2, domains=None, corpus_path=CORPUS_DEFAULT, max_sas_chars=1500):
    """Pick n short, domain-diverse examples from the synthetic corpus to use
    as few-shot exemplars. Short examples keep the prompt (and CPU latency)
    down on a 1B model."""
    if not os.path.exists(corpus_path):
        return []

    by_domain = {}
    with open(corpus_path) as fh:
        for line in fh:
            rec = json.loads(line)
            if len(rec["sas"]) > max_sas_chars:
                continue
            by_domain.setdefault(rec["spec"]["domain"], []).append(rec)

    chosen = []
    doms = domains or sorted(by_domain)
    for d in doms:
        pool = by_domain.get(d, [])
        if pool:
            chosen.append(min(pool, key=lambda r: len(r["sas"])))
        if len(chosen) >= n:
            break
    return chosen[:n]


def build_messages(sas_text, fewshot=None):
    """Zero-shot (the default -- see README's "Why zero-shot, not few-shot")
    uses the exact same minimal user-turn shape as 02_qlora_finetune.py's
    to_chat(): just the program in a ```sas fence, nothing else. That is both
    what was empirically observed to work on gemma3:1b here (adding a
    "### Now document this program" framing line caused the model to treat it
    as a heading to imitate and echo the whole prompt back instead of
    answering) and what keeps this tool's prompt shape compatible with a
    future fine-tuned adapter trained on that same format.

    If fewshot exemplars are requested anyway, they go in the SAME single
    user turn (not alternating synthetic user/assistant turns -- that was
    tested and caused gemma3:1b to fabricate a fictional program instead of
    documenting the real one, see README). Even the single-turn form was
    observed to make a 1B model's output worse, not better; --fewshot 0 stays
    the default for a reason."""
    if not fewshot:
        return [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": "```sas\n%s\n```" % sas_text},
        ]

    parts = []
    for i, ex in enumerate(fewshot, start=1):
        parts.append(
            "Example %d -- SAS program:\n```sas\n%s\n```\n\n"
            "Example %d -- documentation for that program:\n%s" % (i, ex["sas"], i, ex["doc"])
        )
    parts.append("```sas\n%s\n```" % sas_text)
    user_content = "\n\n---\n\n".join(parts)
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": user_content},
    ]
