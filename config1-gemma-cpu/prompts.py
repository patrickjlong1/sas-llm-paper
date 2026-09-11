r"""
prompts.py
==========
System prompt for config1 -- Gemma, CPU-only, zero-shot, no fine-tuning.
Same output schema as config2 and config3 (schema.py's PROMPT_SCHEMA_BLOCK),
so all three configs are genuinely comparable: only the model and its access
to ground truth differ, per the plan.

Zero-shot only (no --fewshot): tested against gemma3:1b and found to make
output WORSE, not better -- with even one exemplar in context, the model
lost coherence and fabricated an entirely fictional SAS program instead of
documenting the real one. That's a coherence ceiling of a small model, not a
prompt bug; kept here as history, not as a knob to reach for on this model.
"""

from schema import PROMPT_SCHEMA_BLOCK

SYSTEM = (
    "You document legacy SAS production code for a data analyst who has never "
    "seen this program before. You will be given one SAS program.\n\n"
    "Hard rules:\n"
    "- Never name a variable, dataset, or macro parameter that does not appear "
    "in the program text.\n"
    "- Document only OUTPUT datasets (written to a permanent library, or the "
    "program's final result) -- not every intermediate/temp dataset.\n\n"
    + PROMPT_SCHEMA_BLOCK
)


def build_messages(sas_text):
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "```sas\n%s\n```" % sas_text},
    ]
