r"""
save_prediction.py
===================
Config3 has no batch inference script -- the model IS Claude, reading each
program and authoring the dictionary by hand per the sas-data-dictionary
skill (repo root .claude/skills/). This tiny helper drops that authored JSON
into the SAME <program>.pred.json / <program>.meta.json shape config1 and
config2 write, so results/score.py and run_eval.py can score all three
configs identically.

Usage (after authoring dictionary.json for one program, per the skill):
    python3 save_prediction.py --program-name prog900_estab \
        --dictionary /tmp/dictionary.json --elapsed-sec 42 \
        --out ../results/preds/config3-frontier-skills
"""

import argparse
import json
import os


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--program-name", required=True, help="without .sas, e.g. prog900_estab")
    ap.add_argument("--dictionary", required=True, help="the JSON you authored, schema.py's shape")
    ap.add_argument("--elapsed-sec", type=float, required=True,
                    help="wall-clock time you spent producing this one program's dictionary "
                         "(read + sas_metadata.py + authoring) -- the plan wants this recorded "
                         "per program for the 'time per program' results column")
    ap.add_argument("--cost-usd", type=float, default=None,
                    help="omit to leave null -- there is no metered API cost when the model "
                         "doing the writing is this Claude Code session itself; fill this in "
                         "if you're driving config3 through the API instead")
    ap.add_argument("--model", default="claude")
    ap.add_argument("--used-proc-contents", action="store_true",
                    help="set if sas_metadata.py's ground truth was actually available/used "
                         "for this program -- feeds the plan's tool-access-vs-model-size note")
    ap.add_argument("--out", default="preds/config3-frontier-skills")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    dictionary = json.load(open(args.dictionary))

    with open(os.path.join(args.out, args.program_name + ".pred.json"), "w") as fh:
        json.dump(dictionary, fh, indent=2)
    with open(os.path.join(args.out, args.program_name + ".meta.json"), "w") as fh:
        json.dump({"model": args.model, "elapsed_sec": round(args.elapsed_sec, 2),
                  "cost_usd": args.cost_usd, "used_ground_truth": args.used_proc_contents,
                  "hardware": "n/a (frontier model, no local compute)"}, fh, indent=2)

    print("wrote %s.pred.json and .meta.json to %s" % (args.program_name, args.out))


if __name__ == "__main__":
    main()
