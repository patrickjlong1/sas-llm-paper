r"""
claude_driver.py
=================
Config3, driven through the Anthropic API instead of an interactive Claude
Code session: Claude reads a real SAS program, calls the same ground-truth
tools the `sas-data-dictionary` skill calls by hand, and writes the
dictionary JSON (`schema.py`'s shape). This is the script SETUP.md used to
leave as a stub, and it is what makes config3 runnable unattended -- over
all 20 eval programs in one command.

Run it with an interpreter that has `anthropic`, and -- for the SAS
ground-truth tool only -- one that can also import `saspy`. On this box
that is the same venv for both:

    /internal/venvs/main/bin/python3 claude_driver.py ...

Config3 needs no local compute (the model is remote), so it runs anywhere
with a network connection and an API key, Colab included; the notebook
handles the Colab bootstrap. What it needs for the FULL config is a live
SASPy/ODA connection and Java for it (`../jre/`, `~/.authinfo`, saspy),
already provisioned here. Without those, `--no-sas-tool` is the honest
run: same model and prompt, no ground truth -- the plan's fairer isolate,
and a different results row. Colab is where config1/config2 want to be,
for free CPU/GPU; config3 just needs somewhere to stand.

What stays the same as the interactive path (deliberately, so the results
row still describes the same config):

  * the model is a frontier model (default `claude-opus-5`), not a local one;
  * the prompt's schema contract is `schema.PROMPT_SCHEMA_BLOCK` -- byte for
    byte the block configs 1 and 2 are prompted with, so the three-way
    comparison is not confounded by three different prompts;
  * the authoring rules are SKILL.md's step-4 rules, quoted in the system
    prompt below;
  * TOOL ACCESS is real, not pre-baked. Claude decides when to call
    `sas_column_metadata` (SASPy -> `dictionary.columns`/`dictionary.tables`
    via sas_metadata.py), `header_comments` (header_extract.py),
    `static_identifier_scan` (extract.py) and `grep_source`. That agency is
    the config -- handing it a pre-harvested blob would make config3 "a
    bigger model with a better prompt", which is precisely the claim the
    plan says NOT to make.

What is better than the interactive path: `elapsed_sec` is measured rather
than remembered, and `cost_usd` is computed from the API's own usage fields
(per turn, at the price of the model that actually served that turn) instead
of left unrecorded. Both land in the `.meta.json` the results table reads.

Usage:
    # one program, end to end (authoring only)
    python3 claude_driver.py ../eval-programs/programs/prog900_estab.sas

    # one program, plus catalog + scoreable prediction
    python3 claude_driver.py ../eval-programs/programs/prog900_estab.sas \
        --catalog catalog/ --preds-out ../results/preds/config3-frontier-skills

    # all 20, unattended (use the saspy interpreter so the SAS tool works)
    /internal/venvs/main/bin/python3 claude_driver.py --dir ../eval-programs/programs \
        --catalog catalog/ --preds-out ../results/preds/config3-frontier-skills

    # the plan's fairer isolate: same model, NO ground-truth tool
    python3 claude_driver.py --dir ../eval-programs/programs --no-sas-tool \
        --preds-out ../results/preds/config3-frontier-skills-nogt

Credentials: `ANTHROPIC_API_KEY` in the environment -- export it in your
shell, or let the notebook's Setup 2 cell prompt for it into the kernel's
environment. The SDK also accepts an `ant auth login` profile. Never
hardcode the key here, and never paste it into a saved cell.

Why a hand-written tool loop rather than `client.beta.messages.tool_runner`:
the runner is a beta helper whose shape can drift, and this file is a paper
artifact that has to keep running unchanged; the loop also needs per-turn
usage accounting for the cost column. Neither is a complaint about the
runner -- prefer it in ordinary application code.
"""

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import tempfile
import time

import anthropic

import extract
import header_extract
import schema

HERE = os.path.dirname(os.path.abspath(__file__))

# USD per 1,000,000 tokens (input, output), Anthropic first-party API rates.
# Cache writes bill at 1.25x input, cache reads at 0.10x input. Checked
# 2026-09-22; if you run this later, re-check console.anthropic.com/pricing
# before quoting the cost column in a paper -- an unknown model id makes
# cost_usd null (honest) rather than wrong.
PRICES = {
    "claude-opus-5":    (5.00, 25.00),
    "claude-opus-4-8":  (5.00, 25.00),
    "claude-sonnet-5":  (2.00, 10.00),
    "claude-haiku-4-5": (1.00,  5.00),
    "claude-fable-5-1": (10.00, 50.00),
}

SYSTEM_PROMPT = """You are documenting a real, poorly-documented legacy SAS program: you
produce a data dictionary and program summary as structured JSON.

You have tools that reach the SAS metadata itself. Use them before you
write anything:

- `sas_column_metadata` runs the program in a live SAS session and returns
  SAS's own `dictionary.columns`/`dictionary.tables` -- the real name, type,
  length, format, informat and label of every column. This is ground truth.
  It can legitimately fail (no SAS session reachable, or the program's
  hardcoded paths don't resolve); if it does, keep going with the other
  tools and say so in `program_summary.description`.
- `header_comments` returns any leading header-comment block and any inline
  `/* ... */` glosses on variable-defining lines. `header_found: false` is
  the normal result on this corpus, not an error.
- `static_identifier_scan` returns every dataset / macro-parameter /
  variable-like name that demonstrably appears in the source text. It is
  your fallback allow-list, and the ONLY source of macro parameter names --
  SAS metadata has no concept of those.
- `grep_source` searches the source text so you can confirm a name really
  appears before you write it down.

Hard rules while writing:

- Never name a dataset, variable, or macro parameter that is not in the
  ground-truth column metadata OR the static scan. If unsure, grep first.
- Prefer a real `label` from ground truth over your own guess. When ground
  truth gives a non-empty label, that IS the documented meaning -- use it
  (lightly cleaned up) as `label`, and let `derivation` describe how the
  value is actually computed in the code. Those are two different fields.
- Ground truth beats a name's surface reading: a variable named `v1`
  labelled "Sampling weight, final" is a sampling weight, not "value 1".
  An ABSENT label plus a terse name means genuinely infer from usage (what
  it is assigned from, what it is summed or compared against, what a
  downstream step does with it) and say so plainly in `derivation` instead
  of inventing confidence you do not have.
- `type`, `length` and `label` come from ground truth whenever ground truth
  states them for that exact variable -- do not re-derive them.
- One `variable_dictionary` row per variable per *output* dataset (written
  to a permanent library, a report, or an external file) -- not every
  intermediate `_t1`/`_tmp` step. Only the code's control flow tells you
  which is which.
- `called_by` is every program file name that invokes the macro; for a
  single self-contained program that is just that program's own file name.

%s""" % schema.PROMPT_SCHEMA_BLOCK


def _tool_defs(offer_sas_tool):
    """Deliberately NOT `strict: true`: these tools have optional parameters
    (`libname`, `run`, `ignore_case`), and strict mode requires every
    property to be required."""
    tools = [
        {
            "name": "header_comments",
            "description": "Return the program's leading header-comment block (if any) plus "
                           "inline /* comment */ glosses found on variable-defining lines. "
                           "No arguments: it always reads the program under documentation.",
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "static_identifier_scan",
            "description": "Regex scan of the program source. Returns the datasets, macro "
                           "parameters and variable-like identifiers that demonstrably appear "
                           "in the text -- the allow-list you must stay inside, and the only "
                           "source of macro parameter names. No arguments.",
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "grep_source",
            "description": "Search the program source with a Python regular expression. "
                           "Returns matching lines with line numbers (capped at 60 lines). "
                           "Use it to confirm an identifier really appears before writing it.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Python regex."},
                    "ignore_case": {"type": "boolean",
                                    "description": "Case-insensitive match. Default true."},
                },
                "required": ["pattern"],
            },
        },
    ]
    if offer_sas_tool:
        tools.insert(0, {
            "name": "sas_column_metadata",
            "description": "Ground truth from SAS itself: submit the program in a live SAS "
                           "session (SASPy), then return dictionary.columns/dictionary.tables "
                           "for the resulting library -- real name, type, length, format, "
                           "informat, label and observation counts. Slow (tens of seconds) "
                           "and may fail if no SAS session is reachable; call it once, early. "
                           "A non-empty run_errors list with usable columns is a partial "
                           "success worth keeping, not a failure.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "libname": {"type": "string",
                                "description": "Library to harvest. Default WORK."},
                    "run": {"type": "boolean",
                            "description": "Submit the program first (default true). Pass "
                                           "false to query an existing library without "
                                           "re-executing the program."},
                },
            },
        })
    return tools


class Tools(object):
    """The four tools, plus the bookkeeping the results row needs: whether
    ground truth was actually obtained, and how many times Claude called
    what. SAS harvests are cached per (libname, run) -- Claude occasionally
    re-asks, and each call is a real SAS session."""

    def __init__(self, sas_file, source, sas_python, offer_sas_tool, prefetched_metadata=None):
        self.sas_file = sas_file
        self.source = source
        self.sas_python = sas_python
        self.offer_sas_tool = offer_sas_tool
        self.calls = {}
        self._sas_cache = {}
        self.column_metadata = None      # the harvest Claude actually got, if any
        if prefetched_metadata is not None:
            self._sas_cache[("work", True)] = json.dumps(prefetched_metadata, indent=2)
            self.column_metadata = prefetched_metadata

    def run(self, name, args):
        """Returns (content_string, is_error)."""
        self.calls[name] = self.calls.get(name, 0) + 1
        try:
            return getattr(self, "_" + name)(args or {})
        except AttributeError:
            return "Error: no such tool %r." % name, True
        except Exception as exc:                      # a tool crash is Claude's to route around
            return "Error: %s: %s" % (type(exc).__name__, exc), True

    def _header_comments(self, args):
        return json.dumps(header_extract.extract(self.source), indent=2), False

    def _static_identifier_scan(self, args):
        scan = extract.scan(self.source)
        return json.dumps({k: sorted(v) for k, v in scan.items()}, indent=2), False

    def _grep_source(self, args):
        pattern = args.get("pattern", "")
        flags = re.I if args.get("ignore_case", True) else 0
        try:
            rx = re.compile(pattern, flags)
        except re.error as exc:
            return "Error: bad regex %r: %s" % (pattern, exc), True
        hits = ["%5d: %s" % (i, line)
                for i, line in enumerate(self.source.splitlines(), 1) if rx.search(line)]
        if not hits:
            return "no match for %r" % pattern, False
        capped = hits[:60]
        if len(hits) > len(capped):
            capped.append("... %d more matching lines (narrow the pattern)" % (len(hits) - len(capped)))
        return "\n".join(capped), False

    def _sas_column_metadata(self, args):
        libname = str(args.get("libname") or "work").lower()
        run = bool(args.get("run", True))
        key = (libname, run)
        if key in self._sas_cache:
            return self._sas_cache[key], False

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as fh:
            out_path = fh.name
        cmd = [self.sas_python, os.path.join(HERE, "sas_metadata.py"), self.sas_file,
               "--libname", libname, "--out", out_path]
        if not run:
            cmd.append("--no-run")
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0 or not os.path.getsize(out_path):
            os.unlink(out_path)
            tail = (proc.stderr or proc.stdout or "")[-1200:]
            return ("Error: sas_metadata.py exited %d -- no SAS session, or the harvest "
                    "failed. Proceed WITHOUT ground truth and say so in the description.\n%s"
                    % (proc.returncode, tail)), True

        payload = json.load(open(out_path))
        os.unlink(out_path)
        if not payload.get("columns"):
            # A reachable session that materialized nothing is not ground truth.
            text = json.dumps(payload, indent=2)
            self._sas_cache[key] = text
            return ("The SAS session was reachable but no columns materialized (see "
                    "run_errors). Treat this as NO ground truth.\n" + text), False

        if self.column_metadata is None or run:
            self.column_metadata = payload
        text = json.dumps(payload, indent=2)
        self._sas_cache[key] = text
        return text, False


class Ledger(object):
    """Per-turn usage and cost. Cost is priced at the model that actually
    served each turn (`response.model`), which is not necessarily the one
    requested -- see --fallbacks. An unpriced model makes the whole cost
    null rather than silently wrong."""

    def __init__(self):
        self.input = self.output = self.cache_write = self.cache_read = 0
        self.cost = 0.0
        self.unpriced = set()
        self.models = []

    def add(self, response):
        u = response.usage
        served = getattr(response, "model", None) or "unknown"
        if served not in self.models:
            self.models.append(served)
        i = u.input_tokens or 0
        o = u.output_tokens or 0
        cw = getattr(u, "cache_creation_input_tokens", 0) or 0
        cr = getattr(u, "cache_read_input_tokens", 0) or 0
        self.input += i
        self.output += o
        self.cache_write += cw
        self.cache_read += cr
        price = self._price(served)
        if price is None:
            self.unpriced.add(served)
            return
        pin, pout = price
        self.cost += (i * pin + cw * pin * 1.25 + cr * pin * 0.10 + o * pout) / 1e6

    @staticmethod
    def _price(model):
        if model in PRICES:
            return PRICES[model]
        for known, price in PRICES.items():      # tolerate a dated snapshot suffix
            if model.startswith(known):
                return price
        return None

    @property
    def cost_usd(self):
        return None if self.unpriced else round(self.cost, 6)

    def as_dict(self):
        return {"input_tokens": self.input, "output_tokens": self.output,
                "cache_creation_input_tokens": self.cache_write,
                "cache_read_input_tokens": self.cache_read,
                "models_served": self.models,
                "unpriced_models": sorted(self.unpriced)}


def _final_text(response):
    texts = [b.text for b in response.content if b.type == "text"]
    return texts[-1].strip() if texts else ""


def _parse_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"```\s*$", "", text).strip()
    try:
        return json.loads(text), None
    except json.JSONDecodeError as exc:
        return None, str(exc)


def document_one(client, sas_file, args):
    """Run the tool loop for one program. Returns (dictionary, meta)."""
    source = open(sas_file).read()
    program = os.path.splitext(os.path.basename(sas_file))[0]
    prefetched = json.load(open(args.metadata_json)) if args.metadata_json else None
    tools = Tools(sas_file, source, args.sas_python, not args.no_sas_tool, prefetched)
    tool_defs = _tool_defs(not args.no_sas_tool)

    # System prompt + tool list are byte-identical across every program in a
    # batch, so this prefix is cacheable. It may sit under the model's
    # minimum cacheable prefix, in which case nothing is cached and nothing
    # breaks -- check cache_read_input_tokens in the .run.json to know.
    system = [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]

    ask = ("Document the SAS program `%s` (file: %s). Gather ground truth with your tools "
           "first, then return the JSON object described in your instructions -- nothing "
           "else. Source follows.\n\n```sas\n%s\n```" % (program, sas_file, source))
    messages = [{"role": "user", "content": ask}]

    output_config = {"effort": args.effort}
    if args.structured_output:
        output_config["format"] = {"type": "json_schema", "schema": _json_schema()}

    request = dict(model=args.model, max_tokens=args.max_tokens, system=system,
                   messages=messages, tools=tool_defs,
                   thinking={"type": "adaptive"}, output_config=output_config)
    if args.fallbacks:
        # A safety decline on a SAS-documentation prompt is unlikely, but a
        # refused request otherwise just stops. `"default"` routes by refusal
        # category, so there is no fallback model list to maintain -- and the
        # ledger prices whichever model actually answered.
        request.update(betas=["server-side-fallback-2026-07-01"], fallbacks="default")
    messages_api = client.beta.messages if args.fallbacks else client.messages

    ledger = Ledger()
    t0 = time.time()
    turns = repairs = 0
    dictionary = None
    refusal = None

    while True:
        turns += 1
        if turns > args.max_turns:
            raise RuntimeError("gave up after %d turns without a valid dictionary "
                               "(raise --max-turns if this is a genuinely big program)"
                               % args.max_turns)
        request["messages"] = messages
        with messages_api.stream(**request) as stream:
            response = stream.get_final_message()
        ledger.add(response)

        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            refusal = getattr(details, "category", None) or "unspecified"
            raise RuntimeError("model refused (category=%s)" % refusal)
        if response.stop_reason == "max_tokens":
            raise RuntimeError("response hit --max-tokens (%d) mid-answer; raise it"
                               % args.max_tokens)

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "pause_turn":
            continue                       # no server tools here, but cheap to survive

        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if tool_uses:
            results = []
            for block in tool_uses:
                content, is_error = tools.run(block.name, block.input)
                result = {"type": "tool_result", "tool_use_id": block.id, "content": content}
                if is_error:
                    result["is_error"] = True
                results.append(result)
            messages.append({"role": "user", "content": results})   # all results, one message
            continue

        candidate, parse_err = _parse_json(_final_text(response))
        errors = [parse_err] if parse_err else None
        if candidate is not None:
            ok, schema_errors = schema.validate(candidate)
            errors = None if ok else schema_errors
        if errors is None:
            dictionary = candidate
            break

        if repairs >= args.max_repairs:
            raise RuntimeError("output still did not match schema.py after %d repair "
                               "attempts: %s" % (repairs, "; ".join(errors)))
        repairs += 1
        messages.append({"role": "user", "content":
                         "That output does not satisfy the required schema:\n- "
                         + "\n- ".join(errors)
                         + "\nReturn the corrected, complete JSON object only."})

    elapsed = time.time() - t0
    dictionary.setdefault("program_name", os.path.basename(sas_file))
    meta = {
        "program_name": program,
        "requested_model": args.model,
        "effort": args.effort,
        "structured_output": bool(args.structured_output),
        "sas_tool_offered": not args.no_sas_tool,
        "ground_truth_used": tools.column_metadata is not None,
        "elapsed_sec": round(elapsed, 2),
        "cost_usd": ledger.cost_usd,
        "api_turns": turns,
        "repair_turns": repairs,
        "tool_calls": tools.calls,
        "usage": ledger.as_dict(),
    }
    return dictionary, meta, tools.column_metadata


def _json_schema():
    """Only used with --structured-output. Off by default on purpose: configs
    1 and 2 get the schema as prompt TEXT with no decoding constraint, so
    constraining config3's decoding would hand it a free 1.00 on the
    schema-validity metric and make that column measure the harness rather
    than the model. Turn it on for a production pipeline; report it if you
    turn it on for a results row."""
    return {
        "type": "object",
        "properties": {
            "program_summary": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "input_datasets": {"type": "array", "items": {"type": "string"}},
                    "output_datasets": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["description", "input_datasets", "output_datasets"],
                "additionalProperties": False,
            },
            "macro_reference": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "positional_params": {"type": "array", "items": {"type": "string"}},
                        "keyword_params": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {"name": {"type": "string"},
                                               "default": {"type": "string"}},
                                "required": ["name", "default"],
                                "additionalProperties": False,
                            },
                        },
                        "purpose": {"type": "string"},
                        "called_by": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["name", "positional_params", "keyword_params",
                                 "purpose", "called_by"],
                    "additionalProperties": False,
                },
            },
            "variable_dictionary": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "dataset": {"type": "string"},
                        "type": {"type": "string", "enum": ["char", "num"]},
                        "length": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                        "label": {"type": "string"},
                        "derivation": {"type": "string"},
                    },
                    "required": ["name", "dataset", "type", "length", "label", "derivation"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["program_summary", "macro_reference", "variable_dictionary"],
        "additionalProperties": False,
    }


def _default_sas_python():
    """sas_metadata.py needs saspy. On this box that is a separate venv; on
    Colab it is the notebook kernel after `pip install -r requirements.txt`."""
    venv = "/internal/venvs/main/bin/python3"
    for candidate in (venv, sys.executable):
        try:
            if subprocess.run([candidate, "-c", "import saspy"],
                              capture_output=True).returncode == 0:
                return candidate
        except OSError:
            continue
    return sys.executable


def _persist(program, sas_file, dictionary, meta, column_metadata, args):
    """Hand the authored JSON to the same two scripts the interactive path
    uses, so there is exactly one implementation of validation, cataloguing
    and prediction-writing."""
    os.makedirs(args.out, exist_ok=True)
    dict_path = os.path.join(args.out, program + ".dictionary.json")
    with open(dict_path, "w") as fh:
        json.dump(dictionary, fh, indent=2)
    with open(os.path.join(args.out, program + ".run.json"), "w") as fh:
        json.dump(meta, fh, indent=2)

    # Ground truth goes to its own directory, named <program>.json, because that
    # is exactly the layout results/run_eval.py --extra-source-dir reads (plan
    # section 3: "for config 3, PROC CONTENTS output also counts as a valid
    # source"). No renaming step later.
    meta_path = None
    if column_metadata is not None:
        os.makedirs(args.metadata_out, exist_ok=True)
        meta_path = os.path.join(args.metadata_out, program + ".json")
        with open(meta_path, "w") as fh:
            json.dump(column_metadata, fh, indent=2)

    if args.catalog:
        cmd = [sys.executable, os.path.join(HERE, "write_dictionary.py"),
               "--program-name", program, "--source", sas_file,
               "--dictionary", dict_path, "--catalog", args.catalog,
               "--generated-by", meta["requested_model"]]
        if meta_path:
            cmd += ["--column-metadata", meta_path]
        subprocess.run(cmd, check=True)

    if args.preds_out:
        cmd = [sys.executable, os.path.join(HERE, "save_prediction.py"),
               "--program-name", program, "--dictionary", dict_path,
               "--elapsed-sec", str(meta["elapsed_sec"]),
               "--model", (meta["usage"]["models_served"] or [meta["requested_model"]])[0],
               "--out", args.preds_out]
        if meta["cost_usd"] is not None:
            cmd += ["--cost-usd", str(meta["cost_usd"])]
        if meta["ground_truth_used"]:
            cmd.append("--used-proc-contents")
        subprocess.run(cmd, check=True)
    return dict_path


def main():
    ap = argparse.ArgumentParser(description="Drive config3 (frontier model + SAS tool "
                                            "access) through the Anthropic API.")
    ap.add_argument("sas_file", nargs="?", default=None)
    ap.add_argument("--dir", default=None, help="document every *.sas in this directory")
    ap.add_argument("--limit", type=int, default=None,
                    help="with --dir: stop after N programs (smoke test). A partial run is "
                         "NOT a result -- score.py counts every un-predicted program as a "
                         "failure.")
    ap.add_argument("--model", default="claude-opus-5")
    ap.add_argument("--effort", default="high", choices=("low", "medium", "high", "xhigh", "max"),
                    help="output_config.effort -- thinking depth and token spend. 'high' is "
                         "the default; 'max' costs more for marginal gain on this task.")
    ap.add_argument("--max-tokens", type=int, default=32000,
                    help="per-response cap (streamed, so a large value costs nothing unless "
                         "it is used).")
    ap.add_argument("--max-turns", type=int, default=16,
                    help="hard stop on the tool loop, so a stuck run cannot bill forever.")
    ap.add_argument("--max-repairs", type=int, default=2,
                    help="re-ask attempts when the JSON misses schema.py's shape.")
    ap.add_argument("--no-sas-tool", action="store_true",
                    help="withhold the ground-truth tool: the plan's fairer isolate of model "
                         "quality. Write it to a DIFFERENT --preds-out than the normal run.")
    ap.add_argument("--metadata-json", default=None,
                    help="pre-harvested sas_metadata.py JSON to serve the tool from, instead "
                         "of opening a SAS session (useful offline; the model still has to "
                         "ask for it).")
    ap.add_argument("--sas-python", default=None,
                    help="interpreter that can import saspy (default: auto-detect).")
    ap.add_argument("--structured-output", action="store_true",
                    help="constrain decoding to the JSON schema. Off by default: configs 1/2 "
                         "get no such constraint, so this would make the schema-validity "
                         "column incomparable. Say so if you use it.")
    ap.add_argument("--no-fallbacks", dest="fallbacks", action="store_false", default=True,
                    help="disable the server-side refusal fallback. On by default so a "
                         "policy decline retries on another model instead of failing the "
                         "run; the .run.json records which model actually served each run.")
    ap.add_argument("--out", default="claude-runs",
                    help="where the authored dictionary + per-run metadata land.")
    ap.add_argument("--metadata-out", default=None,
                    help="where each program's harvested SAS ground truth is written, as "
                         "<program>.json -- the layout run_eval.py --extra-source-dir reads. "
                         "Default: <out>/metadata.")
    ap.add_argument("--catalog", default=None,
                    help="also validate and upsert into this local catalog "
                         "(runs write_dictionary.py).")
    ap.add_argument("--preds-out", default=None,
                    help="also write the scoreable .pred.json/.meta.json pair here "
                         "(runs save_prediction.py).")
    args = ap.parse_args()

    if bool(args.sas_file) == bool(args.dir):
        sys.exit("pass exactly one of: a .sas file, or --dir DIRECTORY")
    if args.sas_python is None:
        args.sas_python = _default_sas_python()
    if args.metadata_out is None:
        args.metadata_out = os.path.join(args.out, "metadata")
    client = anthropic.Anthropic()

    # Fail before the first program rather than mid-batch: one free metadata
    # call proves the credentials resolve AND that --model is a real id. An
    # unresolvable credential surfaces as a TypeError at request-build time,
    # which is not obviously an auth problem from the traceback.
    try:
        client.models.retrieve(args.model)
    except TypeError:
        sys.exit("no Anthropic credentials resolved. Set ANTHROPIC_API_KEY in the "
                 "environment (or run `ant auth login`); the notebook's Setup 2 cell "
                 "does this. Nothing was billed.")
    except anthropic.AuthenticationError:
        sys.exit("the API rejected these credentials (check ANTHROPIC_API_KEY).")
    except anthropic.NotFoundError:
        sys.exit("model %r does not exist or is not available to this account. "
                 "Pass a --model you have access to." % args.model)
    except anthropic.APIConnectionError as exc:
        sys.exit("cannot reach the Anthropic API: %s" % exc)
    files = ([args.sas_file] if args.sas_file
             else sorted(glob.glob(os.path.join(args.dir, "*.sas")))[:args.limit])
    if not files:
        sys.exit("no .sas files found")

    total_cost, priced, failures = 0.0, 0, []
    for i, sas_file in enumerate(files, 1):
        program = os.path.splitext(os.path.basename(sas_file))[0]
        print("\n=== [%d/%d] %s ===" % (i, len(files), program), flush=True)
        try:
            dictionary, meta, column_metadata = document_one(client, sas_file, args)
        except (anthropic.APIError, RuntimeError, ValueError) as exc:
            # One bad program should not abandon the other 19 -- same policy as
            # config1's document_sas.py batch mode.
            print("FAILED %s: %s: %s" % (program, type(exc).__name__, exc), file=sys.stderr)
            failures.append(program)
            continue
        _persist(program, sas_file, dictionary, meta, column_metadata, args)
        cost = meta["cost_usd"]
        if cost is not None:
            total_cost += cost
            priced += 1
        print("%s: %.1fs, %s, %d api turn(s), tools=%s, ground truth=%s"
              % (program, meta["elapsed_sec"],
                 ("$%.4f" % cost) if cost is not None else "cost unpriced",
                 meta["api_turns"], meta["tool_calls"] or "{}", meta["ground_truth_used"]))

    print("\n%d/%d documented%s" % (len(files) - len(failures), len(files),
                                    (" -- FAILED: " + ", ".join(failures)) if failures else ""))
    if priced:
        print("measured cost: $%.4f total, $%.4f mean per program (%d priced)"
              % (total_cost, total_cost / priced, priced))
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
