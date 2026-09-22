r"""
hf_backend.py
=============
CPU-only Hugging Face `transformers` backend for document_sas.py, using the
SAME base model config2 fine-tunes (`google/gemma-3-4b-it`) instead of
config1's original Ollama/GGUF serving. This is what makes config1 runnable
on a bare Colab CPU runtime: there's no `/internal/e2b-gemma` Ollama server
there, and Colab's free tier is the whole point of *not* needing a GPU for
this config (config2 is the one that needs Colab's GPU).

No 4-bit/bitsandbytes quantization (that's config2's QLoRA GPU path --
bitsandbytes' 4-bit kernels need a CUDA GPU and don't run on CPU).

Dtype, and why it is a real choice rather than a detail (--dtype):

  * `bfloat16` (the default) halves `google/gemma-3-4b-it`'s ~17 GB
    float32 footprint to ~8.6 GB, which is what lets the 4B model load at
    all inside free Colab's ~12.7 GB of CPU RAM. The catch: PyTorch only
    has *fast* bf16 CPU kernels where the CPU has AVX512-BF16/AMX, and
    free Colab's shared Xeons generally do not -- bf16 matmuls get upcast
    per operation, so it is memory-feasible but slow.
  * `float32` is meaningfully faster per token on those same CPUs, but
    only fits for a small base: `google/gemma-3-1b-it` is ~4 GB in fp32
    and comfortable. That is the fast Colab path, at the cost of breaking
    exact base-model parity with config2 (say so if you report it).

So: 4B => bfloat16 (slow but faithful), 1B => float32 (fast but a
different base than config2). `--dtype auto` picks bfloat16, i.e. the
faithful default; nothing changes unless you ask for it.

Gated model: same license-acceptance + `huggingface-cli login` (or Colab's
HF_TOKEN secret) requirement as config2 -- see this folder's SETUP.md.

Model + tokenizer are cached at module level so a batch run
(`document_sas.py --dir ...`) loads the weights once and reuses them across
every program, instead of once per file.
"""

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

_CACHE = {}

_DTYPES = {
    "auto": torch.bfloat16,
    "bfloat16": torch.bfloat16,
    "float32": torch.float32,
}


def _load_with_dtype(cls, model_id, revision, dtype):
    """transformers renamed `torch_dtype` to `dtype` in 4.56; accept either so
    this runs on whatever the Colab session resolved."""
    try:
        return cls.from_pretrained(model_id, revision=revision, dtype=dtype,
                                   device_map="cpu")
    except TypeError:
        return cls.from_pretrained(model_id, revision=revision, torch_dtype=dtype,
                                   device_map="cpu")


def _from_pretrained(model_id, revision, dtype):
    """`google/gemma-3-4b-it` is a Gemma3ForConditionalGeneration checkpoint
    (it carries a vision tower alongside the text decoder), so which Auto
    class accepts it depends on the installed transformers version. Try the
    causal-LM mapping first -- recent versions register gemma3 there, and it
    is the mapping every other config in this repo uses -- and fall back to
    the image-text-to-text mapping rather than dying with an unhelpful
    "Unrecognized configuration class". Generation stays text-only either
    way: nothing here ever passes an image."""
    try:
        return _load_with_dtype(AutoModelForCausalLM, model_id, revision, dtype)
    except ValueError:
        from transformers import AutoModelForImageTextToText
        print("note: %s is not registered for AutoModelForCausalLM in this "
              "transformers version -- loading via AutoModelForImageTextToText "
              "instead (still text-only generation)." % model_id)
        return _load_with_dtype(AutoModelForImageTextToText, model_id, revision, dtype)


def _load(model_id, revision, dtype_name):
    key = (model_id, revision, dtype_name)
    if key not in _CACHE:
        dtype = _DTYPES[dtype_name]
        print("loading %s (revision=%s) as %s on CPU -- one-time cost per run, "
              "reused for every program after this..."
              % (model_id, revision, str(dtype).replace("torch.", "")))
        tok = AutoTokenizer.from_pretrained(model_id, revision=revision)
        model = _from_pretrained(model_id, revision, dtype)
        model.eval()
        _CACHE[key] = (tok, model)
    return _CACHE[key]


def generate(messages, model_id, num_predict, revision="main", dtype="auto"):
    """Same (raw_text, done_reason) shape as document_sas.py's Ollama
    generate() -- done_reason == "length" means generation was cut off at
    num_predict tokens (Ollama's own vocabulary for the same event, reused
    here so document_sas.py's --truncated handling needs no branching)."""
    tok, model = _load(model_id, revision, dtype)
    ids = tok.apply_chat_template(messages, add_generation_prompt=True, return_tensors="pt")
    attention_mask = torch.ones_like(ids)
    with torch.no_grad():
        out = model.generate(
            ids, attention_mask=attention_mask,
            max_new_tokens=num_predict, do_sample=False,
            temperature=None, top_p=None, top_k=None,
            pad_token_id=tok.eos_token_id)
    new_tokens = out[0][ids.shape[-1]:]
    text = tok.decode(new_tokens, skip_special_tokens=True)
    done_reason = "length" if new_tokens.shape[-1] >= num_predict else "stop"
    return text, done_reason
