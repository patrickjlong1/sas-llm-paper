# Config 1 setup: Gemma, CPU-only, zero-shot

This is the floor of the three-config comparison: an off-the-shelf small
open-weight model, no fine-tuning, no tool access, running entirely on
ordinary CPU hardware -- the air-gapped baseline.

`config1_gemma_cpu.ipynb` in this folder is a runnable copy of this file
and its section numbers match. Both cover the same two ways to run
config1, picked with `document_sas.py --backend`:

| | `--backend hf` | `--backend ollama` |
|---|---|---|
| where | Colab's free CPU runtime, or any box without `/internal/e2b-gemma` | this box (local Ollama server) |
| model | `transformers` downloads `google/gemma-3-4b-it` | `gemma3:1b` (default) or `gemma3:4b` |
| weights | HF safetensors, bfloat16 | GGUF int4 |
| parity with config2's base | exact (same repo id) | approximate (GGUF build of the same weights) |
| JSON-mode decoding | none | yes (`format: "json"`) |
| speed | slow; measure before committing (section 4) | ~3-6 min/program measured for `gemma3:1b` |

**Neither needs a GPU.** On Colab, leave Runtime -> Change runtime type on
**CPU** (or "None"). Needing no accelerator is the entire point of config1
versus config2's T4 requirement.

The two are **not interchangeable for reporting**: different weight
formats, different default parameter counts, JSON-mode on one and not the
other. Score them as two rows. The notebook writes them to different
`preds/` directories for exactly this reason
(`config1-gemma-cpu` vs `config1-gemma-cpu-hf`).

## 0. Get the whole repo

Sections 4-5 read `../eval-programs/` and `../results/` as siblings of
this folder. Pull the whole repo, not just this directory:

```bash
git clone --depth 1 https://github.com/patrickjlong1/sas-llm-paper.git
cd sas-llm-paper/config1-gemma-cpu
```

The notebook's first cell does this automatically when it detects Colab.

Note what a fresh clone does **not** include: `jre/` (136 MB, gitignored)
and `/internal/e2b-gemma/` (9.6 GB of model blobs, never in the repo).
That is why `--backend ollama` is not available on Colab and why section 7
installs a JDK there.

## 1. Python dependencies

```bash
pip install -r requirements.txt      # both backends
pip install requests                 # --backend ollama only
```

`requests` is all the `ollama` backend needs -- Ollama does the model
work out of process. `requirements.txt` additionally pulls
`transformers`/`torch`/`accelerate`/`huggingface_hub` for the `hf`
backend, which loads the weights in-process.

The notebook probes for a local Ollama server (stdlib only, so it works
before anything is installed) and installs only what the resulting
backend needs -- on a box that already serves the model, pulling ~2 GB of
torch to not use it is not a no-op.

The optional ODA push in section 7 additionally needs `saspy` + `pandas`
(already installed into `/internal/venvs/main` on this box; section 7
installs them on Colab).

## 2. The model runtime

### `--backend ollama` (this box)

The weights + Ollama server live OUTSIDE this folder, at
`/internal/e2b-gemma/` -- infrastructure, not project code, so it isn't
duplicated here. See `/internal/e2b-gemma/README.md`; short version:

```bash
# start the server (already running on this box -- only needed after a reboot):
nohup /internal/e2b-gemma/serve.sh > /internal/e2b-gemma/server.log 2>&1 &
disown

# confirm it's up:
curl -s http://127.0.0.1:11434/api/version
```

On a different machine, install Ollama yourself (no sudo required -- see
Ollama's docs for the tarball install) and `ollama pull gemma3:1b`.

`gemma3:1b` is this backend's default. `gemma3:4b` was tried first, to
match config2's 4B QLoRA base, but it is a MULTIMODAL checkpoint (the
server log shows it loading an `mmproj` blob and running an image-size
warmup pass, not just text weights) and it timed out loading on this
box's 4.7 GB RAM: 13m47s elapsed, repeatedly cycling `loading model` /
`not responding` under swap pressure, before Ollama's own load-timeout
killed it and `document_sas.py` surfaced a `500 Internal Server Error`.
`gemma3:1b` is text-only, lighter, and is what the ~11 tok/s prompt /
~4.5 tok/s generation / 3-6 min-per-program numbers in this project were
actually measured against.

With more RAM, pass `--model gemma3:4b` yourself to restore exact
base-model-size parity with config2 -- and say so in the paper, since
that parity is the point of the config1-vs-config2 comparison. Raising
`OLLAMA_LOAD_TIMEOUT` (set before `ollama serve`; default 5 min) helps if
a bigger model needs more *time* rather than more memory than you have.

### `--backend hf` (Colab, or anywhere without that server)

No Ollama server, no `/internal/e2b-gemma`. `transformers` downloads
`google/gemma-3-4b-it` -- the exact weights config2 fine-tunes -- and runs
them on CPU. Nothing to start.

## 3. Pick the backend and authenticate

The notebook picks `ollama` if a local server answers and `hf` otherwise.
From the CLI, pass `--backend` yourself.

`google/gemma-3-4b-it` is **gated**: accept the license on the model's
Hugging Face page while logged in, then either

```python
from huggingface_hub import login
login()
```

or set the `HF_TOKEN` secret in Colab's Secrets panel (padlock icon, left
sidebar), which `login()` picks up automatically. Same gate config2 goes
through for the same weights.

### Dtype, and why it is a real choice (`--dtype`)

- **`bfloat16` (`--dtype auto`, the default)** halves
  `google/gemma-3-4b-it`'s ~17 GB float32 footprint to ~8.6 GB, which is
  what lets the 4B model load at all inside free Colab's ~12.7 GB of CPU
  RAM. The catch: PyTorch only has *fast* bf16 CPU kernels where the CPU
  has AVX512-BF16/AMX, and free Colab's shared Xeons generally do not, so
  bf16 matmuls get upcast per operation. Memory-feasible, but slow.
- **`--dtype float32`** is meaningfully faster per token on those same
  CPUs but only fits a small base: `google/gemma-3-1b-it` is ~4 GB in
  fp32 and comfortable. Pair them
  (`--model google/gemma-3-1b-it --dtype float32`) for the fast Colab
  path -- and report it as such, because it breaks exact base-model parity
  with config2.

No `bitsandbytes` 4-bit quantization here: those kernels need a CUDA GPU
and are config2's path, not config1's.

## 4. Run it

```bash
python3 document_sas.py path/to/program.sas --backend hf
# or, against the whole eval set:
python3 document_sas.py --dir ../eval-programs/programs --backend hf \
    --out ../results/preds/config1-gemma-cpu-hf \
    --catalog ../results/catalog/config1-gemma-cpu-hf
```

Writes `<name>.pred.json` (the structured dictionary), `<name>.meta.json`
(timing/cost, in the shape `results/run_eval.py` expects),
`<name>.raw.txt` (the raw response -- kept even when it fails to parse as
JSON), and `<name>.guardrail.json` (hallucination check against the static
source scan) per program. A per-file failure in batch mode is logged and
skipped rather than aborting the run.

**Measure one program before committing to twenty.** `--backend hf` at 4B
on a free Colab CPU has not been benchmarked end to end here, and Colab
free sessions idle-disconnect after ~90 minutes and cap around 12 hours.
The notebook reads `prog900_estab.meta.json` and extrapolates for you; from
the CLI, time one program and multiply by 20 (model load is paid once).

`--limit N` runs the first N programs only. That is a **smoke test, not a
result**: `results/score.py` scores against all 20 gold files and counts
every missing prediction as a program that produced no output, so a
5-program run scores like a 20-program run that failed 15 times.

## 5. Score this run

```bash
python3 ../results/run_eval.py --config config1-gemma-cpu-hf \
    --pred-dir ../results/preds/config1-gemma-cpu-hf \
    --out-prefix ../results/outputs/config1-gemma-cpu-hf
python3 ../results/run_eval.py --table --rows ../results/rows.example.json
```

Scoring also writes a `.provenance.json` sidecar recording exactly which
eval corpus was scored; `--table` marks a row **STALE** rather than
printing numbers that no longer describe the corpus on disk. See
`../results/outputs/stale-2026-09-17/README.md` for the run that made that
necessary.

`--run-judge` is left off on Colab on purpose: the default judge is a
local Ollama model, which Colab doesn't have. The table prints `not run`
for Description score rather than inventing one; run the judge later on a
box with a server.

## 6. Get the outputs off Colab

Colab's local disk does not survive a runtime recycle, and neither do the
downloaded weights. Unlike config2 there is no trained artifact to lose --
but the predictions, catalog and scores *are* the run, and re-creating
them costs the whole generation time again. The notebook zips and
downloads `preds/`, `catalog/` and `outputs/`; do the same by hand or
point them at mounted Drive.

## 7. (Optional) Push the catalog into SAS via ODA

Only needed to materialize the generated dictionary as real SAS datasets
(`push_to_oda.py`). Config1 has no ground-truth SAS access **by design** --
that asymmetry is config3's job and part of the finding -- so nothing here
feeds back into config1's own output. Skip this section entirely if you
only want the local JSON/CSV output.

**Get a free ODA account** (if you don't have one): sign up at SAS's
OnDemand for Academics site with an email address -- no cost, academic/
non-commercial use. This gives you a personal cloud SAS session with a
`SASUSER` library that persists across sessions.

1. **Credentials.** On your own machine, create `~/.authinfo` in a
   terminal -- don't paste credentials into a chat session or a saved
   notebook cell:
   ```bash
   echo "oda user YOUR_ODA_EMAIL password YOUR_ODA_PASSWORD" >> ~/.authinfo
   chmod 600 ~/.authinfo
   ```
   On Colab, use the Secrets panel (padlock icon) with `ODA_USER` /
   `ODA_PASS` secrets; the notebook reads them from there and writes
   `~/.authinfo` into the ephemeral session, prompting only if they aren't
   set. Either way the password never becomes part of the saved notebook.

2. **Java.** `config/sascfg_personal.py` prefers the portable JRE bundled
   at the repo root (`../jre/`) and falls back to whatever `java` is on
   `PATH`. `jre/` is 136 MB and gitignored, so a fresh clone -- i.e.
   Colab -- does **not** have it. There, install one:
   ```bash
   !apt-get -qq install default-jdk > /dev/null
   ```
   (Colab runs as root, so no sudo.) Do NOT hand-build a `classpath` in
   `sascfg_personal.py`: SAS's IOM protocol needs `org.omg.CORBA.*`, which
   the JDK dropped in JEP 320, and saspy's own default classpath already
   carries the back-port. Overriding it produces
   `NoClassDefFoundError: org/omg/CORBA/COMM_FAILURE` at connect time.

3. **Check your ODA region** matches `config/sascfg_personal.py`'s
   `iomhost` list. It's already filled in for US-region/usw2 (confirmed
   working for the account this was set up under). For a different region,
   find your host names on your ODA dashboard (Support -> "SAS OnDemand
   for Academics" connection info, or the region picker at signup) and
   replace the `iomhost` list -- the three regions SAS publishes are:
   - US: `odaws0{1,2,3,4}-usw2.oda.sas.com`
   - Europe: `odaws0{1,2}-euw1.oda.sas.com`
   - Asia Pacific: `odaws0{1,2}-apse1.oda.sas.com`

4. **Run the push** with whichever interpreter has `saspy` -- the venv on
   this box, the notebook kernel on Colab:
   ```bash
   /internal/venvs/main/bin/python3 push_to_oda.py \
       --catalog ../results/catalog/config1-gemma-cpu
   ```
   Writes `PROGRAM_SUMMARY`, `MACRO_PARAMS`, `DATA_DICTIONARY` into your
   `SASUSER` library (SAS's auto-assigned, persistent-across-sessions
   library -- no `LIBNAME` statement or path to know). Pass `--libname`/
   `--libpath` only if you want a different, custom-path library instead.

**Licence note:** ODA is for academic/non-commercial use -- check current
terms before pushing anything work-adjacent there.

## Why zero-shot, not few-shot or fine-tuned

Tested in-context learning (showing the model 1-2 example SAS->JSON pairs)
here and it made output WORSE, not better: with even one exemplar in
context, `gemma3:1b` lost coherence and fabricated an entirely fictional SAS
program instead of documenting the real one. That's a genuine capability
ceiling of a 1B-parameter model on this task, not a prompt bug -- if you
want few-shot or fine-tuned quality, that's config2
(`../config2-qlora-gpu/`).

## Known limitations (report these honestly in the results)

- Small-model JSON-mode output frequently fails `schema.py`'s structural
  validation outright (missing keys, wrong types, a list entry that's a
  bare string instead of an object). `document_sas.py` does NOT crash on
  this -- it records `schema_valid: false` in the catalog/meta output and
  moves on, exactly so `results/score.py` can report schema validity as its
  own honest metric rather than one bad program aborting a batch run.
  `--backend hf` has no JSON-mode decoding constraint at all (there is no
  `transformers` equivalent of Ollama's `format: "json"`), so expect this
  to be worse there than on `ollama`, on the same prompt.
- Even when schema-valid, meanings/types are genuinely best-guess and were
  observed wrong on toy synthetic input (e.g. calling a sampling weight
  "Work Time"). The guardrail only catches INVENTED names, never wrong
  MEANINGS -- read every entry, don't just trust an absence of flags.
- `extract.py`'s regex scan is a heuristic on arbitrary real SAS syntax --
  it can miss real identifiers written in forms it doesn't anticipate,
  which under-flags (reports clean when it isn't).
- The `hf` backend's per-program throughput on a free Colab CPU has not
  been benchmarked end to end. Record real wall-clock numbers once you've
  run the full eval set and report them; don't carry the `gemma3:1b`/
  Ollama figures above across to it.
- A `--limit`ed run is a smoke test, not a result (see section 4).
