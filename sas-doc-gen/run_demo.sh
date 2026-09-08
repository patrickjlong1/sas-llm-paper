#!/usr/bin/env bash
# run_demo.sh -- single entry point for a new user to try sas-doc-gen end to end.
#
# By default documents the three bundled example programs in demo_programs/
# (two synthetic, one a real ad-hoc SAS program) using the local zero-shot
# gemma3:1b model over Ollama -- no ODA account, no credentials, no GPU
# needed for this part. Pass --dir to point at your OWN .sas programs instead.
#
# Optionally (--push) also writes the results into YOUR OWN SAS OnDemand for
# Academics account as real datasets, via saspy. This script never asks for,
# reads, or transmits your ODA password -- that lives only in your own
# ~/.authinfo, which you create yourself (see "ODA setup" below).
#
# Usage:
#   ./run_demo.sh                          # bundled demo programs, no push
#   ./run_demo.sh --dir /path/to/your/sas  # your own .sas programs
#   ./run_demo.sh --push                   # also push results to your ODA
#   ./run_demo.sh --dir path/ --push --libname mylib --libpath /path/on/oda
#
# Env overrides: OLLAMA_URL (default http://127.0.0.1:11434), MODEL (default
# gemma3:1b), VENV_PY (default /internal/venvs/main/bin/python3, only needed
# for --push).

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

DIR="demo_programs"
OUT="demo_out"
CATALOG="demo_catalog"
MODEL="${MODEL:-gemma3:1b}"
OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:11434}"
VENV_PY="${VENV_PY:-/internal/venvs/main/bin/python3}"
PUSH=0
LIBNAME=""
LIBPATH=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir) DIR="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    --catalog) CATALOG="$2"; shift 2 ;;
    --model) MODEL="$2"; shift 2 ;;
    --push) PUSH=1; shift ;;
    --libname) LIBNAME="$2"; shift 2 ;;
    --libpath) LIBPATH="$2"; shift 2 ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \?//'; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done

echo "== sas-doc-gen demo =="
echo "programs dir : $DIR"
echo "model        : $MODEL"
echo "push to ODA  : $([[ $PUSH -eq 1 ]] && echo yes || echo no)"
echo

# ---- preflight -------------------------------------------------------------

if [[ ! -d "$DIR" ]]; then
  echo "ERROR: --dir '$DIR' does not exist." >&2
  exit 1
fi
if ! ls "$DIR"/*.sas >/dev/null 2>&1; then
  echo "ERROR: no *.sas files found in '$DIR'." >&2
  exit 1
fi
n_files=$(ls "$DIR"/*.sas | wc -l)
echo "found $n_files .sas file(s) in $DIR"

if ! python3 -c "import requests" 2>/dev/null; then
  echo "ERROR: system python3 is missing 'requests' (needed by document_sas.py)." >&2
  echo "       pip install requests" >&2
  exit 1
fi

if ! curl -s --max-time 3 "$OLLAMA_URL/api/tags" >/dev/null; then
  echo "ERROR: can't reach Ollama at $OLLAMA_URL." >&2
  echo "       Start it, or point OLLAMA_URL at wherever it's running." >&2
  exit 1
fi
if ! curl -s --max-time 3 "$OLLAMA_URL/api/tags" | grep -q "\"$MODEL\""; then
  echo "WARNING: model '$MODEL' not found in 'ollama list' at $OLLAMA_URL."
  echo "         Run: ollama pull $MODEL"
fi

if [[ $PUSH -eq 1 ]]; then
  if [[ ! -x "$VENV_PY" ]]; then
    echo "ERROR: --push needs a python with saspy+pandas at $VENV_PY (set VENV_PY=... to override)." >&2
    exit 1
  fi
  if ! "$VENV_PY" -c "import saspy, pandas" 2>/dev/null; then
    echo "ERROR: $VENV_PY is missing saspy/pandas." >&2
    exit 1
  fi
  if [[ ! -f "$HOME/.authinfo" ]]; then
    cat >&2 <<'EOF'
ERROR: --push needs ~/.authinfo with your OWN ODA credentials. This script
never asks for or touches your password -- create it yourself:

    echo "oda user YOUR_ODA_EMAIL password YOUR_ODA_PASSWORD" >> ~/.authinfo
    chmod 600 ~/.authinfo

Do this in your own terminal, not by pasting your password into a chat
session with an assistant. Then re-run with --push.
EOF
    exit 1
  fi
  if grep -q "CHANGE ME" config/sascfg_personal.py; then
    echo "ERROR: config/sascfg_personal.py still has a 'CHANGE ME' iomhost placeholder." >&2
    echo "       Edit it to your ODA region's host list (see comments in that file), then re-run." >&2
    exit 1
  fi
fi

echo

# ---- run the pipeline -------------------------------------------------------

python3 document_sas.py --dir "$DIR" --out "$OUT" --catalog "$CATALOG" --model "$MODEL"

echo
echo "== documentation written to $OUT/, local catalog updated in $CATALOG/ =="

if [[ $PUSH -eq 1 ]]; then
  echo
  echo "== pushing catalog to your ODA account via saspy =="
  push_args=(--catalog "$CATALOG")
  [[ -n "$LIBNAME" ]] && push_args+=(--libname "$LIBNAME")
  [[ -n "$LIBPATH" ]] && push_args+=(--libpath "$LIBPATH")
  "$VENV_PY" push_to_oda.py "${push_args[@]}"
fi

echo
echo "Done. Per-program docs: $OUT/*.doc.md, guardrail reports: $OUT/*.guardrail.json"
