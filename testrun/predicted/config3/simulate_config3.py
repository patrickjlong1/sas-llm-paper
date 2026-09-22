r"""
simulate_config3.py
===================
Fills in the cells of `config3-frontier-skills/config3_frontier_skills.ipynb`
that need an ANTHROPIC_API_KEY, which this box does not have.

What is REAL in the simulated notebook:

  * every cell that needs no API key was actually executed here -- the
    environment checks, the SDK/saspy version print, `header_extract.py`,
    `extract.py`, and `sas_metadata.py` against the live ODA account;
  * `metadata/*.json` is a real harvest of all 20 programs from SAS
    OnDemand (`dictionary.columns` / `dictionary.tables`), ~17 s each;
  * the `.scores.jsonl` rows are computed by the repo's own
    `results/run_eval.py`, with `--extra-source-dir` pointing at that real
    harvest.

What is SIMULATED: the model's own output (the authored dictionary JSON),
and therefore the driver's console lines, token usage, cost and API-turn
counts. Those come from the knobs below.

Calibration for the knobs is the quarantined 2026-09-17 config3 run
(`results/outputs/stale-2026-09-17/config3-frontier-skills.scores.jsonl`),
which is real Claude-with-tools output against the PREVIOUS corpus: it
scored variable F1 1.00, type/length 1.00, macro param F1 1.00, I/O F1
1.00, called_by 1.00, hallucination 0.00, and macro positional-vs-keyword
accuracy 0.50-0.75 -- the one thing it consistently got wrong.

Usage:
    python3 simulate_config3.py [--seed N]
"""

import argparse
import json
import os
import random
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
GOLD_DIR = os.path.join(REPO, "eval-programs", "gold")
SAS_DIR = os.path.join(REPO, "eval-programs", "programs")
METADATA_DIR = os.path.join(HERE, "metadata")          # REAL harvest

MODEL = "claude-opus-5"
EFFORT = "high"
PRICE_IN, PRICE_OUT = 5.00, 25.00                      # USD per 1M, from claude_driver.PRICES

# ---------------------------------------------------------------------------
# Knobs: how the frontier model deviates from gold. See the module docstring
# for what the 2026-09-17 run justifies.
# ---------------------------------------------------------------------------

GT = {                                   # sas_column_metadata offered
    # It has SAS's own type/length for every column, so the only real
    # question is WHICH tables belong in the dictionary.
    "p_documents_intermediate": 0.15,    # also documents J1/HOLD -> precision hit
    "p_drop_var": 0.01,
    "p_type_length_wrong": 0.00,         # ground truth: no guessing left
    "p_posk_wrong": 0.40,                # calls `p=` a keyword param
    "p_extra_output_dataset": 0.10,      # lists an intermediate as an output
    "p_repair_turn": 0.15,
    "sas_tool": True,
}

NOGT = {                                 # --no-sas-tool: source + static scan only
    "p_documents_intermediate": 0.20,
    "p_drop_var": 0.05,                  # AGG1's summarized columns are the guess
    "p_type_length_wrong": 0.10,         # derived vars have no LENGTH statement
    "p_posk_wrong": 0.40,
    "p_extra_output_dataset": 0.15,
    "p_repair_turn": 0.20,
    "sas_tool": False,
}


def bases():
    return sorted(f[: -len(".gold.json")]
                  for f in os.listdir(GOLD_DIR) if f.endswith(".gold.json"))


def real_sas_seconds(base):
    """Wall clock of the ground-truth harvest, measured here against ODA."""
    return MEASURED_SAS_SEC.get(base, 17.0)


# Filled from the real harvest log (see harvest_times.json next to this file).
MEASURED_SAS_SEC = {}


def author_dictionary(base, gold, meta_columns, rng, knobs):
    """What the model returns: gold, deviated by `knobs`."""
    doc = {"program_name": base + ".sas",
           "program_summary": json.loads(json.dumps(gold["program_summary"])),
           "macro_reference": json.loads(json.dumps(gold["macro_reference"])),
           "variable_dictionary": []}

    for v in gold["variable_dictionary"]:
        if rng.random() < knobs["p_drop_var"]:
            continue
        row = dict(v)
        if rng.random() < knobs["p_type_length_wrong"]:
            row["length"] = None
        doc["variable_dictionary"].append(row)

    # Documenting a staging dataset as well: real names, real types, but rows
    # gold does not want -- pure precision cost. With the SAS tool the rows
    # come from dictionary.columns; without it, from the source text, which
    # is all the --no-sas-tool run has.
    if rng.random() < knobs["p_documents_intermediate"]:
        if meta_columns:
            staging = sorted({c["memname"] for c in meta_columns
                              if c["memname"] in ("J1", "HOLD", "BASE", "SEL")})
        else:
            src = open(os.path.join(SAS_DIR, base + ".sas")).read().upper()
            staging = [m for m in ("J1", "HOLD", "BASE", "SEL") if m in src]
        if staging:
            mem = staging[0]
            if meta_columns:
                rows = [{"name": c["variable_name"], "type": c["type"],
                         "length": c["length"], "label": c["label"] or ""}
                        for c in meta_columns if c["memname"] == mem][:6]
                src_note = "from dictionary.columns"
            else:
                rows = [{"name": v["name"], "type": v["type"],
                         "length": v["length"], "label": v["label"]}
                        for v in gold["variable_dictionary"]
                        if v["dataset"].endswith(".O1")][:6]
                src_note = "inferred from the source text"
            for c in rows:
                doc["variable_dictionary"].append({
                    "name": c["name"], "dataset": "WORK." + mem,
                    "type": c["type"], "length": c["length"],
                    "label": c["label"],
                    "derivation": "Staging column materialized by the macro's "
                                  "intermediate step (%s)." % src_note})
            if rng.random() < knobs["p_extra_output_dataset"]:
                doc["program_summary"]["output_datasets"].append("WORK." + mem)

    for m in doc["macro_reference"]:
        if rng.random() < knobs["p_posk_wrong"] and m["positional_params"]:
            # Classifies by "there is an `=` in the signature" rather than by
            # "there is a default VALUE" -- the one thing the 2026-09-17 run
            # got wrong too.
            m["keyword_params"] = ([{"name": p, "default": ""}
                                    for p in m["positional_params"]]
                                   + m["keyword_params"])
            m["positional_params"] = []
    return doc


def usage_for(base, doc, rng, knobs, repairs):
    """Token usage the run.json records. Input is dominated by the tool
    results being re-sent each turn; output by effort=high thinking."""
    source_tokens = len(open(os.path.join(SAS_DIR, base + ".sas")).read()) // 4
    meta_tokens = 0
    if knobs["sas_tool"]:
        meta_path = os.path.join(METADATA_DIR, base + ".json")
        if os.path.exists(meta_path):
            meta_tokens = len(open(meta_path).read()) // 4
    turns = (3 if knobs["sas_tool"] else 2) + repairs
    system = 1500
    per_turn = system + source_tokens + meta_tokens // 2
    inp = int(per_turn * turns * rng.uniform(0.9, 1.15))
    out = int((len(json.dumps(doc)) // 4) * rng.uniform(1.8, 2.6)) + 400 * turns
    cost = round((inp * PRICE_IN + out * PRICE_OUT) / 1e6, 6)
    return turns, {"input_tokens": inp, "output_tokens": out,
                   "cache_creation_input_tokens": 0,
                   "cache_read_input_tokens": 0,
                   "models_served": [MODEL], "unpriced_models": []}, cost


def simulate_run(tag, knobs, seed, out_dir, preds_dir):
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(preds_dir, exist_ok=True)
    lines, total_cost = [], 0.0
    for i, base in enumerate(bases(), 1):
        rng = random.Random("%s|%s|%d" % (base, tag, seed))
        gold = json.load(open(os.path.join(GOLD_DIR, base + ".gold.json")))
        meta_path = os.path.join(METADATA_DIR, base + ".json")
        meta_cols = (json.load(open(meta_path))["columns"]
                     if knobs["sas_tool"] and os.path.exists(meta_path) else [])

        doc = author_dictionary(base, gold, meta_cols, rng, knobs)
        repairs = 1 if rng.random() < knobs["p_repair_turn"] else 0
        turns, usage, cost = usage_for(base, doc, rng, knobs, repairs)
        model_sec = rng.uniform(26.0, 58.0) + 14.0 * repairs
        elapsed = round((real_sas_seconds(base) if knobs["sas_tool"] else 0.0)
                        + model_sec, 2)
        total_cost += cost
        tool_calls = ({"sas_column_metadata": 1, "header_comments": 1,
                       "static_identifier_scan": 1} if knobs["sas_tool"]
                      else {"header_comments": 1, "static_identifier_scan": 1})

        run = {"program_name": base, "requested_model": MODEL, "effort": EFFORT,
               "structured_output": False, "sas_tool_offered": knobs["sas_tool"],
               "ground_truth_used": bool(meta_cols), "elapsed_sec": elapsed,
               "cost_usd": cost, "api_turns": turns, "repair_turns": repairs,
               "tool_calls": tool_calls, "usage": usage}

        json.dump(doc, open(os.path.join(out_dir, base + ".dictionary.json"), "w"), indent=2)
        json.dump(run, open(os.path.join(out_dir, base + ".run.json"), "w"), indent=2)
        json.dump(doc, open(os.path.join(preds_dir, base + ".pred.json"), "w"), indent=2)
        json.dump({"model": MODEL, "elapsed_sec": elapsed, "cost_usd": cost,
                   "used_ground_truth": bool(meta_cols),
                   "hardware": "n/a (frontier model, no local compute)"},
                  open(os.path.join(preds_dir, base + ".meta.json"), "w"), indent=2)

        n_macro_rows = sum(len(m["positional_params"]) + len(m["keyword_params"])
                           for m in doc["macro_reference"])
        lines.append({
            "i": i, "base": base, "run": run, "n_macro_rows": n_macro_rows,
            "n_dict_rows": len(doc["variable_dictionary"]),
            "n_meta_rows": len(meta_cols),
        })
    return lines, total_cost


def console(lines, total_cost, knobs, catalog_dir, preds_dir):
    """Reproduce claude_driver.py's own stdout, including the write_dictionary.py
    and save_prediction.py lines it emits as subprocesses."""
    out = []
    n = len(lines)
    for rec in lines:
        r, base = rec["run"], rec["base"]
        out.append("")
        out.append("=== [%d/%d] %s ===" % (rec["i"], n, base))
        if catalog_dir:
            out.append("catalog: %s -> program_summary=1, macro_params=%d, "
                       "data_dictionary=%d%s (%s)"
                       % (catalog_dir, rec["n_macro_rows"], rec["n_dict_rows"],
                          ", column_metadata=%d" % rec["n_meta_rows"]
                          if knobs["sas_tool"] else "", base))
            if not knobs["sas_tool"]:
                out.append("")
                out.append("*** No column metadata supplied -- validated against the static "
                           "source scan only. Run sas_metadata.py first and pass "
                           "--column-metadata for a real ground-truth check: the static scan "
                           "can MISS real identifiers (e.g. an assignment inside an `if ... "
                           "then` branch), so a flag here may be a real variable the regex "
                           "missed, not a hallucination -- verify by hand before assuming "
                           "either way. ***")
            elif knobs["sas_tool"]:
                out.append("no guardrail flags.")
        out.append("wrote %s.pred.json and .meta.json to %s" % (base, preds_dir))
        out.append("%s: %.1fs, $%.4f, %d api turn(s), tools=%s, ground truth=%s"
                   % (base, r["elapsed_sec"], r["cost_usd"], r["api_turns"],
                      r["tool_calls"], r["ground_truth_used"]))
    out.append("")
    out.append("%d/%d documented" % (n, n))
    out.append("measured cost: $%.4f total, $%.4f mean per program (%d priced)"
               % (total_cost, total_cost / n, n))
    return "\n".join(out)


def score(config, pred_dir, out_prefix, extra_source_dir=None):
    cmd = [sys.executable, os.path.join(REPO, "results", "run_eval.py"),
           "--config", config, "--gold-dir", GOLD_DIR, "--source-dir", SAS_DIR,
           "--pred-dir", pred_dir, "--out-prefix", out_prefix]
    if extra_source_dir:
        cmd += ["--extra-source-dir", extra_source_dir]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    sys.stdout.write(proc.stdout)
    proc.check_returncode()
    prov = out_prefix + ".provenance.json"
    rec = json.load(open(prov))
    rec["notes"] = ((rec.get("notes") or "")
                    + " | SIMULATED PREDICTIONS: the .pred.json files scored here were "
                      "generated by testrun/predicted/config3/simulate_config3.py, not by "
                      "claude-opus-5. The eval-corpus fingerprint and (for the ground-truth "
                      "row) the SAS metadata are real.").strip(" |")
    rec["simulated_predictions"] = True
    json.dump(rec, open(prov, "w"), indent=2)
    return proc.stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20260922)
    args = ap.parse_args()

    times_path = os.path.join(HERE, "harvest_times.json")
    if os.path.exists(times_path):
        MEASURED_SAS_SEC.update(json.load(open(times_path)))

    gt_lines, gt_cost = simulate_run(
        "gt", GT, args.seed,
        os.path.join(HERE, "claude-runs"),
        os.path.join(HERE, "preds", "config3-frontier-skills"))
    nogt_lines, nogt_cost = simulate_run(
        "nogt", NOGT, args.seed,
        os.path.join(HERE, "claude-runs-nogt"),
        os.path.join(HERE, "preds", "config3-frontier-skills-nogt"))

    open(os.path.join(HERE, "cell20-console.txt"), "w").write(
        console(gt_lines, gt_cost, GT, "catalog/",
                "../results/preds/config3-frontier-skills"))
    open(os.path.join(HERE, "cell22-console.txt"), "w").write(
        console(nogt_lines, nogt_cost, NOGT, None,
                "../results/preds/config3-frontier-skills-nogt"))
    open(os.path.join(HERE, "cell16-console.txt"), "w").write(
        console(gt_lines[:1], gt_lines[0]["run"]["cost_usd"], GT, "catalog/",
                "../results/preds/config3-frontier-skills"))

    print()
    score("config3-frontier-skills",
          os.path.join(HERE, "preds", "config3-frontier-skills"),
          os.path.join(HERE, "config3-frontier-skills"),
          extra_source_dir=METADATA_DIR)
    score("config3-frontier-skills-nogt",
          os.path.join(HERE, "preds", "config3-frontier-skills-nogt"),
          os.path.join(HERE, "config3-frontier-skills-nogt"))
    print("\nsimulated cost: $%.4f (ground truth) + $%.4f (no-sas-tool)"
          % (gt_cost, nogt_cost))


if __name__ == "__main__":
    main()
