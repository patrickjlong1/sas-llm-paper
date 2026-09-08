r"""
01_generate_corpus.py
=====================
Synthetic training corpus for the air-gapped SAS documentation experiment.

Core idea: DO NOT write ugly SAS and then try to document it. Instead generate a
machine-readable SPEC first, then render two things from the same spec:

    spec ---> ugly, undocumented, macro-heavy SAS program   (model INPUT)
         \--> clean documentation + data dictionary         (model TARGET)

Because both sides come from one spec, the targets are ground truth by
construction -- no frontier model needed to label the training set, and the
evaluator in 03_evaluate.py can score coverage and hallucination exactly.

Realism knob that matters: variable names in the rendered code are *lossy
abbreviations* of the true names (employment_level -> EMPL), not random tokens.
That is what legacy SAS actually looks like, and it keeps the mapping learnable.

Usage
-----
    python 01_generate_corpus.py --n 600 --seed 20260903 --out ../data/train.jsonl
    python 01_generate_corpus.py --n 20  --seed 777      --out ../data/eval.jsonl --emit-sas ../data/eval_sas

Every record is:
    {"spec": {...}, "sas": "<program text>", "doc": "<markdown>", "dict": {...}}

Pure stdlib. Deterministic for a given --seed.
"""

import argparse
import json
import os
import random
import textwrap

# --------------------------------------------------------------------------
# Domain vocabulary. Non-work, generic establishment-survey flavour.
# Each measure: (true_name, code_alias, sas_type, length, label, sas_format)
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

STEP_KINDS = ["sort_merge", "summarize", "sql_join", "transpose", "derive"]

BAD_HABITS = [
    "options nomprint nosymbolgen;",
    "options nonotes;",
    "options mlogic nomprint;",
    "options validvarname=v7;",
]


# --------------------------------------------------------------------------
# Spec construction
# --------------------------------------------------------------------------

def build_spec(rng, idx):
    dom_key = rng.choice(list(DOMAINS))
    dom = DOMAINS[dom_key]

    keys = dom["keys"]
    period = dom["period"]
    picked = rng.sample(dom["measures"], rng.randint(3, 5))
    nums = [m for m in picked if m[2] == "num"]
    chars = [m for m in picked if m[2] == "char"]
    if len(nums) < 2:                      # ensure >=2 numerics to filter/derive on
        pool = [m for m in dom["measures"] if m[2] == "num" and m not in nums]
        nums += rng.sample(pool, 2 - len(nums))
    measures = nums + chars                # measures[0], measures[1] are always numeric

    prog_no = 100 + idx
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
                  "%s expressed as a rate per 100 %s" % (base[3], "units"), "8.2")
            derived.append(dv)
            steps.append({"kind": kind, "n": i, "base": base, "derived": dv})
        elif kind == "summarize":
            steps.append({"kind": kind, "n": i, "by": keys[1][1], "stat": rng.choice(["sum", "mean"]),
                          "vars": [m for m in measures if m[2] == "num"][:2]})
        elif kind == "transpose":
            steps.append({"kind": kind, "n": i, "by": keys[0][1],
                          "var": [m for m in measures if m[2] == "num"][0]})
        elif kind == "sql_join":
            steps.append({"kind": kind, "n": i})
        else:
            steps.append({"kind": kind, "n": i, "by": [k[1] for k in keys]})

    out_vars = keys + [period] + measures + derived
    outputs = [{
        "member": "o%d" % rng.randint(1, 3),
        "role": "analysis-ready file consumed by downstream estimation",
        "vars": out_vars,
    }]
    if any(s["kind"] == "summarize" for s in steps):
        sm = next(s for s in steps if s["kind"] == "summarize")
        outputs.append({
            "member": "agg1",
            "role": "aggregated totals by %s used for review tables" % keys[1][0],
            "vars": [keys[1]] + [(v[0] + "_" + sm["stat"], v[1] + sm["stat"][:1].upper(),
                                  "num", 8, "%s (%s across records)" % (v[3], sm["stat"]), v[5])
                                 for v in sm["vars"]],
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
# Renderer 1: the ugly SAS program (model input)
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

    # seed data so the program is self-contained and actually runs on ODA
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
                        # keys must take the SAME value in every input so the merge matches
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

    if any(q["name"] == "thr" for q in p):
        thr_var = spec["measures"][0][1]
    else:
        thr_var = None

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
        elif k == "sql_join":
            a("proc sql noprint;")
            a("  create table _t%d as" % st["n"])
            a("    select a.*, b.%s as %s_b" % (spec["measures"][-1][1], spec["measures"][-1][1]))
            a("    from _t%d a left join _s%s b" % (st["n"] - 1, spec["inputs"][1]["member"]))
            a("      on a.%s = b.%s;" % (keys[0], keys[0]))
            a("quit;")
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
# Renderer 2: documentation + data dictionary (model target)
# --------------------------------------------------------------------------

def render_dict(spec):
    d = {}
    for out in spec["outputs"]:
        d[out["member"]] = {
            "role": out["role"],
            "variables": [
                {"name": v[1], "inferred_meaning": v[0], "type": v[2],
                 "length": v[3], "label": v[4], "format": v[5]}
                for v in out["vars"]
            ],
        }
    return d


def render_doc(spec):
    m = spec["macro"]
    keys = ", ".join(k[1] for k in spec["keys"])
    L = []
    a = L.append
    a("# %s" % spec["program_name"])
    a("")
    a("## Purpose")
    a("Builds an analysis-ready file at the %s level for a single reference period, "
      "by merging raw collected microdata with a control file, applying a retention "
      "filter, and writing the result to a caller-specified library." % spec["entity"])
    a("")
    a("## Inputs")
    for inp in spec["inputs"]:
        a("- `%s` -- %s. Key: %s." % (inp["member"], inp["role"], keys))
    a("- Library `xin` is asserted against a hardcoded path (`%s`); it is declared but "
      "not read by any step in this program." % spec["hardcoded_path"])
    a("")
    a("## Outputs")
    for out in spec["outputs"]:
        a("- `%s` -- %s." % (out["member"], out["role"]))
    a("")
    a("## Macro reference: %%%s" % m["name"])
    a("| Parameter | Default | Meaning |")
    a("|---|---|---|")
    for q in m["params"]:
        a("| `%s` | %s | %s |" % (q["name"], "*required*" if not q["default"] else "`%s`" % q["default"],
                                  q["meaning"]))
    a("")
    a("## Processing sequence")
    for st in spec["steps"]:
        k = st["kind"]
        if k == "sort_merge":
            a("%d. Sort each input by %s and match-merge them, keeping only records "
              "present in the raw file (`if i1`)." % (st["n"], keys))
        elif k == "derive":
            a("%d. Derive `%s` (%s) from `%s`; set to missing when the denominator is "
              "not positive." % (st["n"], st["derived"][1], st["derived"][0], st["base"][1]))
        elif k == "summarize":
            a("%d. Aggregate %s by `%s` using %s, writing `agg1`."
              % (st["n"], ", ".join(v[1] for v in st["vars"]), st["by"], st["stat"].upper()))
        elif k == "transpose":
            a("%d. Transpose `%s` by `%s` into a wide intermediate (`_x%d`), which is "
              "not carried into the output." % (st["n"], st["var"][1], st["by"], st["n"]))
        elif k == "sql_join":
            a("%d. PROC SQL left join back to the control file on `%s` to attach a "
              "suffixed copy of `%s`." % (st["n"], spec["keys"][0][1], spec["measures"][-1][1]))
    a("")
    a("## Lineage")
    chain = " -> ".join(["_t%d" % s["n"] for s in spec["steps"]])
    a("`%s` + `%s` -> %s -> `&lb..%s`"
      % (spec["inputs"][0]["member"], spec["inputs"][1]["member"], chain, spec["outputs"][0]["member"]))
    a("")
    a("## Side effects and cautions")
    a("- `%%let dt=%s` hardcodes a reference period at the top of the program and is "
      "passed as `p` at invocation, so the `p` parameter has no independent effect as "
      "written." % spec["hardcoded_period"])
    if any(q["name"] == "dbg" for q in m["params"]):
        a("- With `dbg=0` the program deletes every `_t:`, `_s:` and `_x:` member in "
          "WORK, which will remove same-named datasets created by other programs in "
          "the same session.")
    a("- [INFERRED] Variable meanings below are inferred from usage and naming; the "
      "program contains no comments or labels. Confirm against the source system "
      "before publishing.")
    a("")
    a("## Data dictionary")
    for out in spec["outputs"]:
        a("")
        a("### %s" % out["member"])
        a("| Variable | Inferred meaning | Type | Len | Format |")
        a("|---|---|---|---|---|")
        for v in out["vars"]:
            a("| `%s` | %s | %s | %d | %s |"
              % (v[1], v[4], v[2], v[3], v[5] or "-"))
    return "\n".join(L)


# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=600)
    ap.add_argument("--seed", type=int, default=20260903)
    ap.add_argument("--out", default="../data/train.jsonl")
    ap.add_argument("--emit-sas", default=None,
                    help="also write each .sas program to this directory (for ODA runs)")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    if args.emit_sas:
        os.makedirs(args.emit_sas, exist_ok=True)

    with open(args.out, "w") as fh:
        for i in range(args.n):
            spec = build_spec(rng, i)
            sas = render_sas(spec, rng)
            rec = {"spec": spec, "sas": sas, "doc": render_doc(spec), "dict": render_dict(spec)}
            fh.write(json.dumps(rec) + "\n")
            if args.emit_sas:
                with open(os.path.join(args.emit_sas, spec["program_name"]), "w") as sf:
                    sf.write(sas + "\n")

    print("wrote %d records to %s" % (args.n, args.out))
    if args.emit_sas:
        print("wrote %d .sas programs to %s" % (args.n, args.emit_sas))


if __name__ == "__main__":
    main()
