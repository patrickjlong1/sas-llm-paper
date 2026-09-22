r"""
predict_run_outputs.py
======================
PREDICTED (simulated) run outputs for config1-gemma-cpu, config2-base and
config2-tuned against the CURRENT eval corpus.

Nothing here is a measurement of model output. The two notebooks in
`testrun/` (`config1_gemma_cpu.ipynb`, `config2_qlora_gpu.ipynb`) were
interrupted before their scoring cells ran, so `results/outputs/` has no
`.scores.jsonl` for these three runs. This script reconstructs what those
files would most likely have contained, by:

  1. taking the notebook's *observed* stdout as hard anchors (see ANCHORS
     below) -- which programs produced parseable JSON, how many catalog
     rows config1 wrote for prog900, per-program wall clock, hardware;
  2. degrading each program's gold JSON with an explicit, per-config error
     model (the DEGRADATION KNOBS section) that encodes what each model can
     and cannot do given its prompt and its training;
  3. writing the resulting `.pred.json` / `.meta.json` files and then
     running the repo's REAL scorer over them (`results/run_eval.py`), so
     the `.scores.jsonl` rows are computed, not invented.

Only step 2 is guesswork. Steps 1 and 3 are evidence and repo code.

Usage:
    python3 predict_run_outputs.py                 # writes preds/ + .scores.jsonl
    python3 predict_run_outputs.py --seed 7        # re-draw the stochastic knobs

Read README.md next to this file for the reasoning behind every knob and
for how much of each number to trust.
"""

import argparse
import copy
import json
import os
import random
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
GOLD_DIR = os.path.join(REPO, "eval-programs", "gold")
SAS_DIR = os.path.join(REPO, "eval-programs", "programs")
PRED_ROOT = os.path.join(HERE, "preds")

# ---------------------------------------------------------------------------
# ANCHORS -- straight out of the two notebooks' captured cell output.
# ---------------------------------------------------------------------------

# config1_gemma_cpu.ipynb, cells 11/12/14. The single-file run and the first
# program of the batch run both completed; the batch was cut off during
# [2/20]. Both runs reported prog900 as schema-valid with zero guardrail
# flags, and wrote "4 macro row(s), 10 dictionary row(s)" to the catalog.
C1_MODEL = "google/gemma-3-4b-it"
C1_ELAPSED_OBSERVED = {"prog900_estab": 2590.2}          # batch run, cell 14
C1_ELAPSED_MEAN = 2600.0                                  # cells 11/14: 2619.8 / 2590.2
C1_PROG900_DICT_ROWS = 10
C1_PROG900_MACRO_ROWS = 4          # 3 params + 1 param-less macro entry
C1_HARDWARE = ("CPU (transformers, dtype=auto -- see SETUP.md's "
               "'Running on Colab' section)")
# Programs a surviving free-Colab session gets through before the runtime
# cap, at the measured 2590.2 s/program (see the partial run below).
C1_PARTIAL_N = 12

# config2_qlora_gpu.ipynb, cells 18/19: per-program wall clock, and which
# programs came back as parseable JSON. A "PARSE ERROR" program gets NO
# .pred.json from infer.py, so score.py sees it as "no output produced".
C2_HARDWARE = "GPU: NVIDIA A100-SXM4-40GB (42.4 GB)"
C2_BASE_ELAPSED = {
    "prog900_estab": 85.2, "prog901_hhold": 84.3, "prog902_estcost": 96.5,
    "prog903_estcost": 78.8, "prog904_hhold": 75.7, "prog905_estcost": 79.1,
    "prog906_estcost": 92.7, "prog907_estcost": 102.2, "prog908_estcost": 87.5,
    "prog909_hhold": 76.5, "prog910_estab": 77.8, "prog911_estab": 87.7,
    "prog912_estab": 97.5, "prog913_estab": 87.9, "prog914_hhold": 73.1,
    "prog915_estab": 88.6, "prog916_estab": 105.4, "prog917_hhold": 106.2,
    "prog918_hhold": 76.9, "prog919_estab": 84.3,
}
C2_TUNED_ELAPSED = {
    "prog900_estab": 178.1, "prog901_hhold": 183.3, "prog902_estcost": 183.2,
    "prog903_estcost": 184.1, "prog904_hhold": 182.6, "prog905_estcost": 183.8,
    "prog906_estcost": 184.1, "prog907_estcost": 183.8, "prog908_estcost": 184.0,
    "prog909_hhold": 183.9, "prog910_estab": 162.0, "prog911_estab": 183.8,
    "prog912_estab": 184.1, "prog913_estab": 184.4, "prog914_hhold": 185.1,
    "prog915_estab": 184.8, "prog916_estab": 184.9, "prog917_hhold": 185.2,
    "prog918_hhold": 185.3, "prog919_estab": 181.4,
}
# Observed: no PARSE ERROR on any of the 20 base-model programs.
C2_BASE_PARSE_OK = set(C2_BASE_ELAPSED)
# Observed: only these 5 tuned programs came back without "PARSE ERROR".
C2_TUNED_PARSE_OK = {"prog900_estab", "prog910_estab", "prog914_hhold",
                     "prog918_hhold", "prog919_estab"}

# ---------------------------------------------------------------------------
# DEGRADATION KNOBS -- the guesswork, all in one place. See README.md.
# ---------------------------------------------------------------------------

BASE = {
    # P(the model resolves `data &lb..o1;` to the scored form "WORK.O1"
    # rather than writing "o1" / "&lb..o1" / the staging dataset name).
    "p_work_prefix": 0.45,
    # P(the program's PROC SUMMARY output dataset gets documented at all --
    # the prompt says "output datasets", and zero-shot the model usually
    # documents only the one written with a DATA step).
    "p_documents_agg1": 0.35,
    # P(keep) per gold variable of the main output dataset.
    "p_keep_var": 0.88,
    # P(one extra row for a real-but-not-in-the-output variable, e.g. a
    # staging column -- costs precision, is NOT a hallucination).
    "p_extra_var": 0.35,
    "p_type_right": 0.90,
    "p_length_right": 0.60,
    "p_param_listed": 0.95,
    # P(the model classifies params by "is there an `=`" instead of the
    # prompt's "is there a default VALUE" rule -> everything keyword).
    "p_all_keyword": 0.60,
    "p_default_exact": 0.80,
    # P(an extra, param-less macro_reference entry -- anchored TRUE for
    # prog900, where the catalog shows 4 macro rows for a 3-param macro).
    "p_extra_macro_entry": 0.25,
    # P(a name the static scan would not find: the base model is heavily
    # copy-driven, and config1's guardrail flagged nothing on prog900).
    "p_hallucinated_name": 0.10,
    # Schema-invalidity modes for a model with no JSON-mode decoding.
    "p_type_word": 0.10,      # "numeric"/"character" instead of num/char
    "p_missing_key": 0.05,    # a variable row missing "length"
    # Share of programs where 4-bit NF4 (config2-base) diverges from
    # config1's bf16 decode of the same weights + same prompt.
    "p_quant_divergence": 0.35,
}

TUNED = {
    # The adapter was trained on corpus_gen.py output, whose gold uses
    # WORK.O1/WORK.AGG1 and the same derivation phrasing -- so where it
    # answers at all it answers in-format.
    "p_work_prefix": 1.0,
    "p_documents_agg1": 1.0,
    "p_keep_var_merge": 0.97,   # in-template (sort+merge) programs
    "p_keep_var_sql": 0.85,     # out-of-template (PROC SQL join) programs
    "p_extra_var": 0.15,
    "p_type_right": 0.98,
    "p_length_right": 0.95,
    "p_param_listed": 1.0,
    "p_all_keyword": 0.05,
    "p_default_exact": 0.95,
    "p_extra_macro_entry": 0.0,
    "p_hallucinated_name": 0.05,
}


def load_gold(base):
    return json.load(open(os.path.join(GOLD_DIR, base + ".gold.json")))


def source_of(base):
    return open(os.path.join(SAS_DIR, base + ".sas")).read()


def program_bases():
    return sorted(f[: -len(".gold.json")]
                  for f in os.listdir(GOLD_DIR) if f.endswith(".gold.json"))


def is_sql_join(base):
    return "proc sql" in source_of(base).lower()


def _dataset_as_written(dotted, use_work_prefix, rng):
    """How the model writes a dataset reference. Gold is 'WORK.O1'."""
    member = dotted.split(".")[-1]
    if use_work_prefix:
        return "WORK." + member.upper()
    return rng.choice([member.lower(), "&lb.." + member.lower(), member.upper()])


def _short_label(gold_label):
    """A zero-shot model paraphrases rather than reproducing the gold label
    verbatim. Labels are not scored by score.py (only llm_judge.py reads
    them, and it was not run), so this is cosmetic realism."""
    return gold_label.split(" (")[0]


def _plain_derivation(var, gold_row):
    d = gold_row.get("derivation", "")
    if "round(" in d:
        return d
    if "join key" in d:
        return "Key variable read from the input data and carried through the join."
    if "PROC SUMMARY" in d:
        return "Aggregated value produced by the PROC SUMMARY step."
    if "backfilled" in d:
        return "Taken from the input; filled from the macro parameter when blank."
    return "Read from the input data and carried through to the output dataset."


def make_base_pred(base, gold, rng, knobs, anchor_prog900=False, style=None):
    """Zero-shot google/gemma-3-4b-it, greedy, schema in the system prompt.
    Same weights + same prompt for config1 (bf16/CPU) and config2-base
    (4-bit/GPU), so one generator covers both.

    `style` carries the decisions that are a property of the weights + the
    prompt rather than of the arithmetic they run in -- whether this program's
    output datasets get the WORK. libref resolved, whether the PROC SUMMARY
    dataset is documented at all, how the macro params are classified, and
    which schema-invalidity mode (if any) fires. config1 and config2-base
    share those; only the token-level details below are re-drawn, which is
    what 4-bit NF4 quantization actually perturbs."""
    src_upper = source_of(base).upper()
    style = style or base_style(base, rng, knobs)
    use_prefix = style["use_prefix"]
    main_ds = gold["program_summary"]["output_datasets"][0]        # WORK.O1
    agg_ds = next((d for d in gold["program_summary"]["output_datasets"]
                   if d.upper().endswith("AGG1")), None)
    include_agg = bool(agg_ds) and style["include_agg"]

    rows = []
    for v in gold["variable_dictionary"]:
        is_main = v["dataset"].upper() == main_ds.upper()
        if not is_main and not include_agg:
            continue
        if is_main and rng.random() > knobs["p_keep_var"]:
            continue
        row = {
            "name": v["name"],
            "dataset": _dataset_as_written(v["dataset"], use_prefix, rng),
            "type": v["type"] if rng.random() < knobs["p_type_right"]
                    else ("char" if v["type"] == "num" else "num"),
            "length": v["length"] if rng.random() < knobs["p_length_right"]
                      else (8 if v["type"] == "char" else None),
            "label": _short_label(v["label"]),
            "derivation": _plain_derivation(v["name"], v),
        }
        rows.append(row)

    # An extra row for a staging column that is in the source but not in the
    # documented output dataset -- precision cost, not a hallucination.
    if rng.random() < knobs["p_extra_var"]:
        for cand in ("I1", "I2", "_TYPE_", "V1"):
            if cand in src_upper:
                rows.append({"name": cand,
                             "dataset": _dataset_as_written(main_ds, use_prefix, rng),
                             "type": "num", "length": 8,
                             "label": "Merge/flag column",
                             "derivation": "Intermediate column used by the merge step."})
                break

    if rng.random() < knobs["p_hallucinated_name"]:
        rows.append({"name": "OBSDATE",
                     "dataset": _dataset_as_written(main_ds, use_prefix, rng),
                     "type": "char", "length": 8,
                     "label": "Observation date",
                     "derivation": "Date the record was produced."})

    gm = gold["macro_reference"][0]
    positional, keyword = [], []
    all_keyword = style["all_keyword"]
    for p in gm["positional_params"]:
        if rng.random() > knobs["p_param_listed"]:
            continue
        (keyword if all_keyword else positional).append(
            {"name": p, "default": ""} if all_keyword else p)
    for kp in gm["keyword_params"]:
        if rng.random() > knobs["p_param_listed"]:
            continue
        default = kp["default"] if rng.random() < knobs["p_default_exact"] \
            else {"work": "WORK", "0": "0 (none)", "5": "5", "10": "10"}.get(
                kp["default"], kp["default"])
        keyword.append({"name": kp["name"], "default": default})

    macros = [{
        "name": gm["name"],
        "positional_params": positional,
        "keyword_params": keyword,
        "purpose": ("Wraps the whole job: joins the two input datasets, applies the "
                    "threshold filter, derives the rate variable and writes the "
                    "output dataset."),
        # The model is handed the SAS text only -- never the file name -- so
        # it cannot know which program calls this macro.
        "called_by": [],
    }]
    if anchor_prog900 or style["extra_macro_entry"]:
        macros.append({
            "name": "dt", "positional_params": [], "keyword_params": [],
            "purpose": "Macro variable holding the hardcoded reference period.",
            "called_by": [],
        })

    inputs = [_dataset_as_written(d, use_prefix, rng)
              for d in gold["program_summary"]["input_datasets"]]
    outputs = [_dataset_as_written(main_ds, use_prefix, rng)]
    if include_agg:
        outputs.append(_dataset_as_written(agg_ds, use_prefix, rng))

    pred = {
        "program_summary": {
            "description": ("This program reads two raw input datasets, merges them on "
                            "the key variables, filters the records using the threshold "
                            "macro parameter, computes a rate variable and writes the "
                            "result to the output library."),
            "input_datasets": inputs,
            "output_datasets": outputs,
        },
        "macro_reference": macros,
        "variable_dictionary": rows,
    }

    # Schema-invalidity modes (no JSON-mode decoding on either path).
    if style["schema_break"] == "type_word" and pred["variable_dictionary"]:
        for row in pred["variable_dictionary"]:
            row["type"] = "numeric" if row["type"] == "num" else "character"
    elif style["schema_break"] == "missing_key" and pred["variable_dictionary"]:
        del pred["variable_dictionary"][0]["length"]

    return pred


def base_style(base, rng, knobs):
    """The systematic, prompt-driven half of the base model's behaviour on one
    program -- shared by config1 and config2-base (same weights, same prompt,
    same greedy decode)."""
    schema_break = None
    if rng.random() < knobs["p_type_word"]:
        schema_break = "type_word"
    elif rng.random() < knobs["p_missing_key"]:
        schema_break = "missing_key"
    return {
        "use_prefix": rng.random() < knobs["p_work_prefix"],
        "include_agg": rng.random() < knobs["p_documents_agg1"],
        "all_keyword": rng.random() < knobs["p_all_keyword"],
        "extra_macro_entry": rng.random() < knobs["p_extra_macro_entry"],
        "schema_break": schema_break,
    }


def _anchor_prog900(pred, gold, rng):
    """config1's catalog line for prog900 -- "4 macro row(s), 10 dictionary
    row(s)", schema valid, zero guardrail flags -- pins that program's shape:
    exactly 10 variable rows, every name real, nothing schema-invalid."""
    rows = [r for r in pred["variable_dictionary"] if r["name"] != "OBSDATE"]
    have = {(r["name"], r["dataset"]) for r in rows}
    spelled = rows[0]["dataset"] if rows else "WORK.O1"
    for v in gold["variable_dictionary"]:           # pad with real gold names
        if len(rows) >= C1_PROG900_DICT_ROWS:
            break
        key = (v["name"], spelled)
        if key in have:
            continue
        rows.append({"name": v["name"], "dataset": spelled, "type": v["type"],
                     "length": v["length"], "label": _short_label(v["label"]),
                     "derivation": _plain_derivation(v["name"], v)})
        have.add(key)
    rows = rows[:C1_PROG900_DICT_ROWS]
    for row in rows:                                # schema_valid was True
        row["type"] = "num" if row["type"] in ("num", "numeric") else "char"
        if "length" not in row:
            row["length"] = 8
    pred["variable_dictionary"] = rows
    return pred


def make_tuned_pred(base, gold, rng, knobs):
    """QLoRA adapter trained on 580 corpus_gen.py programs: same schema, same
    WORK.O1/WORK.AGG1 conventions, same derivation phrasing. Where it stays
    in distribution it is close to gold; the eval set's hand-written PROC SQL
    joins are what it never saw."""
    p_keep = knobs["p_keep_var_sql"] if is_sql_join(base) else knobs["p_keep_var_merge"]
    pred = copy.deepcopy(gold)
    pred.pop("program_name", None)

    rows = []
    for v in gold["variable_dictionary"]:
        if rng.random() > p_keep:
            continue
        row = dict(v)
        if rng.random() > knobs["p_type_right"]:
            row["type"] = "char" if v["type"] == "num" else "num"
        if rng.random() > knobs["p_length_right"]:
            row["length"] = None
        rows.append(row)
    pred["variable_dictionary"] = rows

    for m in pred["macro_reference"]:
        # Trained on <program>.sas as called_by, but never shown the file
        # name at inference time -- so it emits a plausible wrong one.
        m["called_by"] = ["prog%d_%s.sas" % (rng.randint(100, 699),
                                             base.split("_", 1)[1])]
        if rng.random() < knobs["p_all_keyword"]:
            m["keyword_params"] = ([{"name": p, "default": ""}
                                    for p in m["positional_params"]]
                                   + m["keyword_params"])
            m["positional_params"] = []
    return pred


def write_run(config, preds, elapsed, extra_meta, meta_only_when_run=False):
    """meta_only_when_run: a run that was CUT SHORT never reaches the later
    programs at all, so it leaves no .meta.json for them either. A run that
    reached a program and failed to parse its output still writes one (that
    is what infer.py does), which is why this is not the default."""
    out_dir = os.path.join(PRED_ROOT, config)
    os.makedirs(out_dir, exist_ok=True)
    for base in program_bases():
        pred = preds.get(base)
        if pred is not None:
            with open(os.path.join(out_dir, base + ".pred.json"), "w") as fh:
                json.dump(pred, fh, indent=2)
        elif meta_only_when_run:
            continue
        meta = {"elapsed_sec": round(elapsed[base], 2), "cost_usd": 0.0}
        meta.update(extra_meta(base, pred))
        with open(os.path.join(out_dir, base + ".meta.json"), "w") as fh:
            json.dump(meta, fh, indent=2)
    n = sum(1 for b in program_bases() if preds.get(b) is not None)
    n_meta = n if meta_only_when_run else len(program_bases())
    print("[%s] wrote %d .pred.json + %d .meta.json into %s"
          % (config, n, n_meta, os.path.relpath(out_dir, HERE)))


def score(config, pred_dir_name, out_prefix_name, log_name):
    """Run the repo's real scorer over the simulated predictions."""
    cmd = [sys.executable, os.path.join(REPO, "results", "run_eval.py"),
           "--config", config,
           "--gold-dir", GOLD_DIR, "--source-dir", SAS_DIR,
           "--pred-dir", os.path.join(PRED_ROOT, pred_dir_name),
           "--out-prefix", os.path.join(HERE, out_prefix_name)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    proc.check_returncode()
    with open(os.path.join(HERE, log_name), "w") as fh:
        fh.write(proc.stdout)
    # Make the sidecar say out loud that the predictions were simulated.
    prov_path = os.path.join(HERE, out_prefix_name + ".provenance.json")
    rec = json.load(open(prov_path))
    rec["notes"] = ("PREDICTED RUN -- the .pred.json files fingerprinted here were "
                    "SIMULATED by testrun/predicted/predict_run_outputs.py, not "
                    "generated by a model. The eval-corpus fingerprint is real. Do "
                    "not publish these numbers as measurements.")
    rec["simulated_predictions"] = True
    json.dump(rec, open(prov_path, "w"), indent=2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20260922)
    args = ap.parse_args()

    bases = program_bases()
    golds = {b: load_gold(b) for b in bases}

    # ---- config1 (and, from the same decode, config2-base) ---------------
    c1_preds, c2b_preds = {}, {}
    for b in bases:
        style = base_style(b, random.Random("%s|style|%d" % (b, args.seed)), BASE)

        rng = random.Random("%s|c1|%d" % (b, args.seed))
        pred = make_base_pred(b, golds[b], rng, BASE, style=style,
                              anchor_prog900=(b == "prog900_estab"))
        if b == "prog900_estab":
            pred = _anchor_prog900(pred, golds[b], rng)
        c1_preds[b] = pred

        # config2-base: identical weights, prompt and greedy decode, run in
        # 4-bit NF4 instead of bf16. Same systematic `style`; only the
        # token-level draws differ, and only on some programs.
        qrng = random.Random("%s|c2b|%d" % (b, args.seed))
        if qrng.random() < BASE["p_quant_divergence"]:
            c2b_preds[b] = make_base_pred(b, golds[b], qrng, BASE, style=style)
        else:
            c2b_preds[b] = copy.deepcopy(pred)

    c1_elapsed = {}
    for b in bases:
        rng = random.Random("%s|t1|%d" % (b, args.seed))
        c1_elapsed[b] = C1_ELAPSED_OBSERVED.get(b, rng.uniform(2380.0, 2860.0))
    write_run("config1-gemma-cpu", c1_preds, c1_elapsed,
              lambda b, p: {"model": C1_MODEL, "backend": "hf",
                            "hardware": C1_HARDWARE, "truncated": False})

    # ---- config2-base ------------------------------------------------------
    write_run("config2-base", c2b_preds, C2_BASE_ELAPSED,
              lambda b, p: {"model": C1_MODEL, "adapter": None,
                            "gpu_usd_per_hour": 0.0, "hardware": C2_HARDWARE,
                            "max_new_tokens": 1200, "truncated": False,
                            "parse_error": None})

    # ---- config2-tuned -----------------------------------------------------
    c2t_preds = {}
    for b in bases:
        if b not in C2_TUNED_PARSE_OK:
            c2t_preds[b] = None                     # infer.py writes no .pred.json
            continue
        rng = random.Random("%s|c2t|%d" % (b, args.seed))
        c2t_preds[b] = make_tuned_pred(b, golds[b], rng, TUNED)

    def tuned_meta(b, pred):
        ok = b in C2_TUNED_PARSE_OK
        return {"model": C1_MODEL, "adapter": "../adapters/sasdoc-lora",
                "gpu_usd_per_hour": 0.0, "hardware": C2_HARDWARE,
                "max_new_tokens": 1200, "truncated": not ok,
                "parse_error": None if ok else
                "Expecting ',' delimiter: line 1 column 1 (char 0)"}

    write_run("config2-tuned", c2t_preds, C2_TUNED_ELAPSED, tuned_meta)

    # ---- config1, partial: what a free Colab session actually delivers -----
    # Cell 12 measured 2590.2s/program and printed "873.3 min for all 20",
    # i.e. 14.6 h against Colab free's ~12 h ceiling and ~90 min idle cut-off.
    # A session that survives long enough to be worth scoring still stops
    # part-way; 12 programs is ~8.7 h. score.py counts the rest as "no output
    # produced", which is the whole point of scoring a partial run AS partial.
    partial = {b: (c1_preds[b] if i < C1_PARTIAL_N else None)
               for i, b in enumerate(bases)}
    write_run("config1-gemma-cpu-partial%d" % C1_PARTIAL_N, partial, c1_elapsed,
              lambda b, p: {"model": C1_MODEL, "backend": "hf",
                            "hardware": C1_HARDWARE, "truncated": False},
              meta_only_when_run=True)

    # ---- score all four with the repo's own scorer -------------------------
    print()
    score("config1-gemma-cpu", "config1-gemma-cpu", "config1-gemma-cpu",
          "config1-gemma-cpu.scoring.log")
    score("config2-base", "config2-base", "config2-base", "config2-base.scoring.log")
    score("config2-tuned", "config2-tuned", "config2-tuned", "config2-tuned.scoring.log")
    score("config1-gemma-cpu-partial%d" % C1_PARTIAL_N,
          "config1-gemma-cpu-partial%d" % C1_PARTIAL_N,
          "config1-gemma-cpu-partial%d" % C1_PARTIAL_N,
          "config1-gemma-cpu-partial%d.scoring.log" % C1_PARTIAL_N)


if __name__ == "__main__":
    main()
