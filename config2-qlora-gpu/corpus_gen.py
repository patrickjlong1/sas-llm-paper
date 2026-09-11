r"""
corpus_gen.py
=============
Generates synthetic, undocumented legacy SAS programs paired with PERFECT
gold documentation JSON, matching the schema all three configs (Gemma-CPU,
QLoRA, frontier-with-skills) are scored against.

Core idea, unchanged from the original prototype this was adapted from:
generate a machine-readable SPEC first, then render two things from the same
spec:

    spec ---> ugly, undocumented, macro-heavy SAS program   (model INPUT)
         \--> gold documentation JSON                        (scoring target)

Because both sides come from one spec, the gold JSON is ground truth by
construction -- no frontier model needed to label it, and results/score.py
can score precision/recall/F1 and hallucination exactly.

Realism knobs: variable names in the rendered code are lossy abbreviations
of the true names (employment_level -> EMPL), there are no header comments,
and macro parameters are cryptic single/short tokens (p, lb, thr, dbg) --
that is what legacy SAS actually looks like.

Gold JSON schema (see ../PLAN.md section 1 for the prose spec this
implements):

    {
      "program_name": "prog101_estab.sas",
      "program_summary": {
        "description": "...",
        "input_datasets": ["WORK.D1", "WORK.D2"],
        "output_datasets": ["WORK.O1", "WORK.AGG1"]
      },
      "macro_reference": [
        {"name": "dostep1", "positional_params": ["p"],
         "keyword_params": [{"name": "lb", "default": "work"}],
         "purpose": "...", "called_by": ["prog101_estab.sas"]}
      ],
      "variable_dictionary": [
        {"name": "ESTID", "dataset": "WORK.O1", "type": "char", "length": 12,
         "label": "Establishment identifier", "derivation": "..."}
      ]
    }

Usage
-----
    # 20 held-out eval programs (used by every config, never trained on):
    python3 corpus_gen.py --n 20 --seed 777 --id-offset 900 \
        --sas-out programs/ --gold-out gold/

    # 600 training pairs for config2's QLoRA fine-tune (disjoint id range +
    # disjoint seed from the eval set above -- see config2's SETUP.md):
    python3 corpus_gen.py --n 600 --seed 20260903 --id-offset 100 \
        --sas-out /tmp/train_sas/ --gold-out /tmp/train_gold/ \
        --jsonl /tmp/train.jsonl

Pure stdlib. Deterministic for a given --seed.
"""

import argparse
import json
import os
import random

# --------------------------------------------------------------------------
# Domain vocabulary. Each measure: (true_name, code_alias, sas_type, length,
# label, sas_format).
# --------------------------------------------------------------------------

DOMAINS = {
    "estab": {
        "entity": "sampled establishment",
        "keys": [
            ("establishment_id", "ESTID", "char", 12, "Establishment identifier", None),
            ("state_fips", "ST", "char", 2, "State FIPS code", None),
        ],
        "period": ("reference_period", "PER", "char", 6, "Reference period YYYYMM", None),
        "measures": [
            ("employment_level", "EMPL", "num", 8, "Total employment level", "comma12."),
            ("job_openings", "JO", "num", 8, "Job openings count", "comma12."),
            ("hires_count", "HIR", "num", 8, "Total hires", "comma12."),
            ("separations_count", "SEP", "num", 8, "Total separations", "comma12."),
            ("weight_final", "WGTF", "num", 8, "Final sampling weight", "10.4"),
            ("response_flag", "RSPF", "char", 1, "Response status flag (R/N/P)", None),
        ],
    },
    "hhold": {
        "entity": "surveyed household",
        "keys": [
            ("household_id", "HHID", "char", 10, "Household identifier", None),
            ("region_code", "RGN", "char", 1, "Census region code", None),
        ],
        "period": ("interview_month", "IMTH", "char", 6, "Interview month YYYYMM", None),
        "measures": [
            ("persons_in_household", "NPER", "num", 8, "Count of persons in household", "3."),
            ("labor_force_status", "LFST", "char", 2, "Labor force status code", None),
            ("usual_hours_worked", "UHRS", "num", 8, "Usual weekly hours worked", "4.1"),
            ("income_bracket", "INCB", "char", 2, "Reported income bracket code", None),
            ("weight_person", "PWGT", "num", 8, "Person-level weight", "10.4"),
            ("proxy_flag", "PRXF", "char", 1, "Proxy interview flag (Y/N)", None),
        ],
    },
    "estcost": {
        "entity": "reporting unit",
        "keys": [
            ("reporting_unit_id", "RUID", "char", 14, "Reporting unit identifier", None),
            ("industry_code", "IND", "char", 6, "Industry classification code", None),
        ],
        "period": ("quarter_label", "QTR", "char", 6, "Quarter label YYYYQn", None),
        "measures": [
            ("total_compensation", "TCOMP", "num", 8, "Total compensation cost", "dollar14.2"),
            ("wage_cost", "WCOST", "num", 8, "Wage and salary cost", "dollar14.2"),
            ("benefit_cost", "BCOST", "num", 8, "Benefit cost", "dollar14.2"),
            ("hours_paid", "HRSP", "num", 8, "Total hours paid", "comma12."),
            ("weight_occupation", "OWGT", "num", 8, "Occupation-level weight", "10.4"),
            ("edit_flag", "EDTF", "char", 1, "Edit action flag (A/E/I)", None),
        ],
    },
}

STEP_KINDS = ["sort_merge", "summarize", "transpose", "derive"]

BAD_HABITS = [
    "options nomprint nosymbolgen;",
    "options nonotes;",
    "options mlogic nomprint;",
    "options validvarname=v7;",
]


# --------------------------------------------------------------------------
# Spec construction
# --------------------------------------------------------------------------

def build_spec(rng, idx, id_offset):
    dom_key = rng.choice(list(DOMAINS))
    dom = DOMAINS[dom_key]

    keys = dom["keys"]
    period = dom["period"]
    picked = rng.sample(dom["measures"], rng.randint(3, 5))
    nums = [m for m in picked if m[2] == "num"]
    chars = [m for m in picked if m[2] == "char"]
    if len(nums) < 2:
        pool = [m for m in dom["measures"] if m[2] == "num" and m not in nums]
        nums += rng.sample(pool, 2 - len(nums))
    measures = nums + chars

    prog_no = id_offset + idx
    macro_name = rng.choice(["mkrun", "bldout", "prcstep", "runjob", "dostep"]) + str(rng.randint(1, 9))

    params = [
        {"name": "p", "meaning": "reference period passed as YYYYMM", "default": None},
        {"name": "lb", "meaning": "output library reference", "default": "work"},
    ]
    if rng.random() < 0.6:
        params.append({
            "name": "thr",
            "meaning": "minimum %s required for a record to be retained" % measures[0][0],
            "default": str(rng.choice([0, 1, 5, 10])),
        })
    if rng.random() < 0.4:
        params.append({
            "name": "dbg",
            "meaning": "debug switch; when 1 the intermediate dataset is kept",
            "default": "0",
        })

    inputs = [
        {"member": "d1", "role": "raw collected microdata for the reference period",
         "vars": keys + [period] + measures[:2]},
        {"member": "d2", "role": "control/frame file used to attach weights and flags",
         "vars": keys + measures[2:]},
    ]
    if rng.random() < 0.35:
        inputs.append({
            "member": "d3",
            "role": "prior-period file used for period-over-period comparison",
            "vars": keys + [period] + [measures[0]],
        })

    n_steps = rng.randint(3, 5)
    kinds = ["sort_merge"] + rng.sample(STEP_KINDS[1:], min(n_steps - 1, len(STEP_KINDS) - 1))
    steps = []
    derived = []
    for i, kind in enumerate(kinds, start=1):
        if kind == "derive":
            base = rng.choice([m for m in measures if m[2] == "num"][:2])
            dv = ("%s_rate" % base[0], "%sR" % base[1], "num", 8,
                  "%s expressed as a rate per 100 units" % base[4], "8.2")
            derived.append(dv)
            steps.append({"kind": kind, "n": i, "base": base, "derived": dv})
        elif kind == "summarize":
            steps.append({"kind": kind, "n": i, "by": keys[1][1], "stat": rng.choice(["sum", "mean"]),
                          "vars": [m for m in measures if m[2] == "num"][:2]})
        elif kind == "transpose":
            steps.append({"kind": kind, "n": i, "by": keys[0][1],
                          "var": [m for m in measures if m[2] == "num"][0]})
        else:
            steps.append({"kind": kind, "n": i, "by": [k[1] for k in keys]})

    out_vars = keys + [period] + measures + derived
    outputs = [{
        "member": "o1",
        "role": "analysis-ready file consumed by downstream estimation",
        "vars": out_vars,
        "lib": "lb",       # written as &lb..o1 -- default libref "work"
    }]
    if any(s["kind"] == "summarize" for s in steps):
        sm = next(s for s in steps if s["kind"] == "summarize")
        outputs.append({
            "member": "agg1",
            "role": "aggregated totals by %s used for review tables" % keys[1][0],
            # PROC SUMMARY's `output out=agg1(...) sum=;` with a BLANK right-hand
            # side keeps each variable's ORIGINAL name in the output dataset (SAS
            # only renames if you list new names after the `=`) -- so the alias
            # here must stay v[1] unchanged, not a suffixed name.
            "vars": [keys[1]] + [(v[0], v[1], "num", 8,
                                  "%s (%s across records)" % (v[4], sm["stat"]), v[5])
                                 for v in sm["vars"]],
            "lib": "work",
            "stat": sm["stat"],
            "stat_vars": sm["vars"],
            "stat_by": sm["by"],
        })

    return {
        "program_name": "prog%d_%s.sas" % (prog_no, dom_key),
        "domain": dom_key,
        "entity": dom["entity"],
        "macro": {"name": macro_name, "params": params},
        "inputs": inputs,
        "outputs": outputs,
        "steps": steps,
        "period_var": period,
        "keys": keys,
        "measures": measures,
        "derived": derived,
        "bad_habit": rng.choice(BAD_HABITS),
        "hardcoded_period": "%d%02d" % (rng.randint(2016, 2021), rng.randint(1, 12)),
        "hardcoded_path": rng.choice(["/sasdata/arch/%s" % dom_key, "/prod/legacy/%s/in" % dom_key]),
    }


# --------------------------------------------------------------------------
# Renderer 1: the ugly SAS program (model input) -- bad names, no comments,
# hardcoded macro-unfriendly period, cryptic macro params.
# --------------------------------------------------------------------------

def render_sas(spec, rng):
    L = []
    a = L.append
    keys = [k[1] for k in spec["keys"]]
    per = spec["period_var"][1]

    a(spec["bad_habit"])
    a("libname xin '%s';" % spec["hardcoded_path"])
    a("%%let dt=%s;" % spec["hardcoded_period"])
    a("")

    for inp in spec["inputs"]:
        cols = inp["vars"]
        a("data %s;" % inp["member"])
        a("  length %s;" % " ".join(
            "%s %s%d" % (c[1], "$" if c[2] == "char" else "", c[3]) for c in cols))
        a("  infile datalines dsd truncover;")
        a("  input %s;" % " ".join(
            "%s%s" % (c[1], " $" if c[2] == "char" else "") for c in cols))
        a("  datalines;")
        key_aliases = [k[1] for k in spec["keys"]]
        for r in range(4):
            row = []
            for c in cols:
                if c[2] == "char":
                    if c[1] == per:
                        row.append(spec["hardcoded_period"])
                    elif c[1] in key_aliases:
                        row.append(("%s%04d" % (c[1][:3], r + 1))[: c[3]] if c[3] > 2
                                   else ["01", "06", "02", "11"][r][: c[3]])
                    else:
                        row.append(rng.choice(["R", "N", "P", "Y", "A", "E", "I"])[: c[3]])
                else:
                    row.append("%.2f" % (rng.randint(1, 900) + rng.random()))
            a("  " + ",".join(row))
        a("  ;")
        a("run;")
        a("")

    p = spec["macro"]["params"]
    sig = ", ".join("%s=%s" % (q["name"], q["default"] or "") for q in p)
    a("%%macro %s(%s);" % (spec["macro"]["name"], sig))

    thr_var = spec["measures"][0][1] if any(q["name"] == "thr" for q in p) else None

    for st in spec["steps"]:
        k = st["kind"]
        if k == "sort_merge":
            for inp in spec["inputs"][:2]:
                a("proc sort data=%s out=_s%s; by %s; run;" % (inp["member"], inp["member"], " ".join(keys)))
            a("data _t%d;" % st["n"])
            a("  merge %s;" % " ".join("_s%s(in=i%d)" % (inp["member"], j)
                                        for j, inp in enumerate(spec["inputs"][:2], start=1)))
            a("  by %s;" % " ".join(keys))
            a("  if i1;")
            if thr_var:
                a("  if %s ge &thr;" % thr_var)
            a("  if %s = '' then %s = \"&dt\";" % (per, per))
            a("run;")
        elif k == "derive":
            b = st["base"][1]
            d = st["derived"][1]
            a("data _t%d;" % st["n"])
            a("  set _t%d;" % (st["n"] - 1))
            a("  if %s > 0 then %s = round(100*%s/%s, 0.01);" % (b, d, b, spec["measures"][0][1]))
            a("  else %s = .;" % d)
            a("run;")
        elif k == "summarize":
            a("proc summary data=_t%d nway;" % (st["n"] - 1))
            a("  class %s;" % st["by"])
            a("  var %s;" % " ".join(v[1] for v in st["vars"]))
            a("  output out=agg1(drop=_type_ _freq_) %s=;" % st["stat"])
            a("run;")
            a("data _t%d; set _t%d; run;" % (st["n"], st["n"] - 1))
        elif k == "transpose":
            a("proc transpose data=_t%d out=_x%d prefix=v;" % (st["n"] - 1, st["n"]))
            a("  by %s;" % st["by"])
            a("  var %s;" % st["var"][1])
            a("run;")
            a("data _t%d; set _t%d; run;" % (st["n"], st["n"] - 1))
        a("")

    last = spec["steps"][-1]["n"]
    out = spec["outputs"][0]
    a("data &lb..%s;" % out["member"])
    a("  set _t%d;" % last)
    a("run;")
    if any(q["name"] == "dbg" for q in p):
        a("%%if &dbg=0 %%then %%do;")
        a("  proc datasets lib=work nolist; delete _t: _s: _x:; quit;")
        a("%%end;")
    a("%%mend %s;" % spec["macro"]["name"])
    a("")
    a("%%%s(p=&dt);" % spec["macro"]["name"])
    return "\n".join(L)


# --------------------------------------------------------------------------
# Renderer 2: gold documentation JSON (scoring target -- exact schema all
# three configs are asked to produce).
# --------------------------------------------------------------------------

def _libref_member(lib_alias, member, spec):
    lib = "WORK" if lib_alias == "work" else "WORK"  # &lb defaults to work; gold reflects that default
    return "%s.%s" % (lib, member.upper())


def _derivation_for(spec, out, var):
    """One-line, human-readable derivation description for a single output
    variable, matching plan section 1's "how the variable is derived"."""
    alias = var[1]
    key_aliases = {k[1] for k in spec["keys"]}
    per_alias = spec["period_var"][1]
    derived_aliases = {d[1] for d in spec["derived"]}

    if out["member"] == "agg1":
        stat = out.get("stat", "sum")
        by = out.get("stat_by")
        if alias == by:
            return "grouping variable carried through from the class statement (%s)." % by
        return ("computed via PROC SUMMARY as the %s of this variable across records "
                "sharing the same %s (name unchanged from the input -- the `%s=;` output "
                "statement was not given explicit new names)." % (stat, by, stat))

    if alias in key_aliases:
        return "carried through unchanged from the merged input datasets (join key)."
    if alias == per_alias:
        return ("carried through from the input file when populated; if blank, backfilled from "
                "the &dt macro variable set at the top of the program.")
    if alias in derived_aliases:
        d = next(d for d in spec["derived"] if d[1] == alias)
        base = next(s["base"] for s in spec["steps"] if s["kind"] == "derive" and s["derived"][1] == alias)
        return ("computed as round(100*%s/%s, 0.01) when %s > 0, else set to missing."
                % (base[1], spec["measures"][0][1], base[1]))
    return "carried through unchanged from the merged input datasets."


def render_gold(spec):
    prog = spec["program_name"]

    input_datasets = ["WORK.%s" % inp["member"].upper() for inp in spec["inputs"]]
    output_datasets = [_libref_member(out.get("lib", "work"), out["member"], spec)
                       for out in spec["outputs"]]

    description = (
        "Builds an analysis-ready file at the %s level for a single reference period, by "
        "merging raw collected microdata with a control file, applying a retention filter, "
        "and writing the result to a caller-specified library%s."
        % (spec["entity"],
           "; also aggregates totals by %s for review" % spec["keys"][1][0]
           if any(o["member"] == "agg1" for o in spec["outputs"]) else "")
    )

    m = spec["macro"]
    positional = [q["name"] for q in m["params"] if q["default"] is None]
    keyword = [{"name": q["name"], "default": q["default"]} for q in m["params"] if q["default"] is not None]
    macro_purpose = (
        "Merges %s to produce %s for reference period `p`, applying a %s-step pipeline "
        "(sort/merge%s)."
        % (" and ".join(inp["member"].upper() for inp in spec["inputs"][:2]),
           spec["outputs"][0]["member"].upper(),
           len(spec["steps"]),
           "".join(", " + s["kind"] for s in spec["steps"][1:]))
    )

    macro_reference = [{
        "name": m["name"],
        "positional_params": positional,
        "keyword_params": keyword,
        "purpose": macro_purpose,
        "called_by": [prog],
    }]

    variable_dictionary = []
    for out in spec["outputs"]:
        ds = _libref_member(out.get("lib", "work"), out["member"], spec)
        for v in out["vars"]:
            variable_dictionary.append({
                "name": v[1],
                "dataset": ds,
                "type": v[2],
                "length": v[3],
                "label": v[4],
                "derivation": _derivation_for(spec, out, v),
            })

    return {
        "program_name": prog,
        "program_summary": {
            "description": description,
            "input_datasets": input_datasets,
            "output_datasets": output_datasets,
        },
        "macro_reference": macro_reference,
        "variable_dictionary": variable_dictionary,
    }


# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=777)
    ap.add_argument("--id-offset", type=int, default=900,
                    help="numbers programs prog<offset+i>_<domain>.sas -- keep eval and "
                         "training id ranges disjoint (e.g. eval=900+, train=100+) so a "
                         "held-out program can never collide by name with a training one")
    ap.add_argument("--sas-out", default="programs")
    ap.add_argument("--gold-out", default="gold")
    ap.add_argument("--jsonl", default=None,
                    help="also write one combined {program_name, sas, gold} record per "
                         "line here -- convenient for config2's training data loader")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    os.makedirs(args.sas_out, exist_ok=True)
    os.makedirs(args.gold_out, exist_ok=True)

    jsonl_fh = open(args.jsonl, "w") if args.jsonl else None
    try:
        for i in range(args.n):
            spec = build_spec(rng, i, args.id_offset)
            sas = render_sas(spec, rng)
            gold = render_gold(spec)
            base = os.path.splitext(spec["program_name"])[0]

            with open(os.path.join(args.sas_out, spec["program_name"]), "w") as sf:
                sf.write(sas + "\n")
            with open(os.path.join(args.gold_out, base + ".gold.json"), "w") as gf:
                json.dump(gold, gf, indent=2)
                gf.write("\n")
            if jsonl_fh:
                jsonl_fh.write(json.dumps({"program_name": spec["program_name"], "sas": sas, "gold": gold}) + "\n")
    finally:
        if jsonl_fh:
            jsonl_fh.close()

    print("wrote %d .sas programs to %s" % (args.n, args.sas_out))
    print("wrote %d gold JSON files to %s" % (args.n, args.gold_out))
    if args.jsonl:
        print("wrote combined jsonl to %s" % args.jsonl)


if __name__ == "__main__":
    main()
