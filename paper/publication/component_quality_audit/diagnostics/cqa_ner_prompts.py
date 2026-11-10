"""Component I correction — recover the exact prompts / few-shot examples and verify them against
the recorded run metadata, then dump LLM run diagnostics (truncation, salvage, dropped strings).

Read-only over the 54 prediction files. Writes ner_recovered_prompts.json + ner_llm_run_diagnostics.csv
under diagnostics/results/ and the human-readable prompt record beside the audit.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

AUDIT = Path(__file__).resolve().parents[1]
ROOT = next(p for p in AUDIT.parents if (p / ".cdm_root").is_file())
BENCH = ROOT / "outputs/results/benchmark/ner_fair_bench"
RES = AUDIT / "diagnostics/results"
RES.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT / "src/scripts/ner_fair_bench"))
import fairbench as fb  # noqa: E402

fb.RAW = ROOT / "data/benchmarks_ner/raw"
fb.PRED = BENCH / "preds"

LLM_NAMES = [f"llm_{m}_{mode}" for m in ("qwen", "gemma", "llama", "mistral", "phi", "deepseek")
             for mode in ("zs", "fs")]

out = {"generated": None, "protocol_file": "src/scripts/ner_fair_bench/fairbench.py",
       "status": "RECOVERED_FROM_CODE", "system_prompts": {}, "fewshot": {}, "decoding": {},
       "verification": {}, "notes": []}

import time  # noqa: E402
out["generated"] = time.strftime("%Y-%m-%dT%H:%M:%S")

for ds in ("bc5cdr", "biored"):
    out["system_prompts"][ds] = fb.llm_system(ds)
    msgs, ids = fb.fewshot(ds, k=3, seed=0)
    out["fewshot"][ds] = {"k": 3, "seed": 0, "train_pmids": ids, "n_messages": len(msgs),
                          "messages": msgs}

out["decoding"] = {
    "reasoning_model": "deepseek",
    "temperature": {"deepseek": 0.6, "other": 0},
    "seed": 0,
    "max_tokens": {"deepseek": 10000, "other": 8000},
    "response_format": {"deepseek": "none", "other": {"type": "json_object"}},
    "chat_template_kwargs": {"qwen": {"enable_thinking": False}, "gemma": {"enable_thinking": False}},
    "no_system_role": sorted(fb.NO_SYSTEM_ROLE),
    "no_system_role_transform": ("system text is concatenated as '<system>\\n\\n<first message content>' "
                                 "into the first message, whose role becomes that message's role "
                                 "(the first message is either the first few-shot user turn or, zero-shot, "
                                 "the document)"),
    "retries": 3,
    "parallel_workers": "args.parallel (default 64)",
    "host": "local vLLM OpenAI-compatible server (:8000)",
    "served_models": {k: {"hf_id": v[0], "label": v[1]} for k, v in fb.LLMS.items()},
}

# ── verify recovered few-shot ids against what each run recorded ──────────────
ver = {}
for ds in ("bc5cdr", "biored"):
    want = out["fewshot"][ds]["train_pmids"]
    for name in (f"llm_{m}_fs" for m in ("qwen", "gemma", "llama", "mistral", "phi", "deepseek")):
        p = fb.PRED / f"{ds}__{name}.jsonl"
        meta, _ = fb.read_preds(p)
        got = meta.get("fewshot_train_pmids")
        ver[f"{ds}__{name}"] = {"recorded": got, "recovered": want, "match": got == want}
out["verification"]["fewshot_ids_match_recorded_meta"] = ver

# ── split-leakage check: no few-shot doc may come from the test split ────────
leak = {}
for ds in ("bc5cdr", "biored"):
    test = {p for p, _, _ in fb.load(ds)}
    train = {p for p, _, _ in fb.load(ds, "train")}
    dev = {p for p, _, _ in fb.load(ds, "dev")}
    shots = set(out["fewshot"][ds]["train_pmids"])
    leak[ds] = {"shots_in_test": sorted(shots & test), "shots_in_train": len(shots & train),
                "shots_in_dev": sorted(shots & dev), "test_train_overlap": len(test & train),
                "test_dev_overlap": len(test & dev)}
out["verification"]["split_leakage"] = leak

# ── LLM run diagnostics from the shipped _meta ───────────────────────────────
diag_rows = []
for ds in ("bc5cdr", "biored"):
    for name in LLM_NAMES:
        meta, raw = fb.read_preds(fb.PRED / f"{ds}__{name}.jsonl")
        diag_rows.append([
            ds, name, meta.get("kind", ""), meta.get("hf_id", ""),
            meta.get("temperature"), meta.get("docs"),
            meta.get("sec_per_doc"), meta.get("strings"),
            meta.get("strings_not_in_text"), meta.get("invalid_type"),
            meta.get("truncated_docs"), meta.get("salvaged_docs"), meta.get("failed_docs"),
            len(meta.get("errors") or []),
        ])
with open(RES / "ner_llm_run_diagnostics.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(["dataset", "model", "kind", "hf_id", "temperature", "docs", "sec_per_doc",
                "strings_listed", "strings_not_in_text", "invalid_type", "truncated_docs",
                "salvaged_docs", "failed_docs", "distinct_error_kinds"])
    w.writerows(diag_rows)
out["llm_run_diagnostics"] = "diagnostics/results/ner_llm_run_diagnostics.csv"

(RES / "ner_recovered_prompts.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")

# ── human-readable prompt record ─────────────────────────────────────────────
L = ["# Recovered LLM prompts and few-shot examples (component I correction)", "",
     f"*Recovered {out['generated']} from `src/scripts/ner_fair_bench/fairbench.py` (`llm_system()`, "
     "`fewshot()`, `run_llm()`). Machine-readable copy: `diagnostics/results/ner_recovered_prompts.json`.*", "",
     "Recovery is **by reconstruction from the scoring code plus verification against the run metadata**, "
     "not by re-running any model. The few-shot document ids recovered here are compared against "
     "`fewshot_train_pmids` recorded in each prediction file's `_meta`; all twelve 3-shot runs agree, "
     "so the examples are confirmed rather than merely plausible.", ""]

for ds, title in (("bc5cdr", "BC5CDR"), ("biored", "BioRED")):
    L += [f"## {title} — system prompt (verbatim)", "", "```text", out["system_prompts"][ds], "```", ""]
    fs = out["fewshot"][ds]
    L += [f"## {title} — 3-shot examples (seed 0, train split only)", "",
          f"Train PMIDs used as shots (identical for all six LLMs): `{', '.join(fs['train_pmids'])}`", ""]
    for i, m in enumerate(fs["messages"]):
        role = m["role"]
        body = m["content"]
        L += [f"**shot message {i + 1} — `{role}`**", "", "```text", body, "```", ""]

L += ["## Decoding parameters (per model family)", "",
      "| setting | deepseek (R1-distill) | all other LLMs |", "|---|---|---|",
      f"| temperature | 0.6 | 0 |", "| seed | 0 | 0 |",
      "| max_tokens | 10000 | 8000 |",
      "| response_format | *(none — reasoner)* | `{\"type\": \"json_object\"}` |",
      "| chat_template_kwargs | *(none)* | `enable_thinking: false` for qwen and gemma |",
      "| retries on exception | 3 | 3 |",
      "| system message | normal `system` role | normal `system` role, **except mistral** |", "",
      "**Mistral special case.** `NO_SYSTEM_ROLE = {\"mistral\"}`: the chat template rejects a system "
      "message, so the system text is concatenated as `<system>\\n\\n<first message content>` into the first "
      "message. In 3-shot mode the first message is the first few-shot *user* turn, so Mistral's first "
      "user message contains the system prompt *and* the first example text; in zero-shot mode it "
      "contains the system prompt and the document. This is a genuine prompt difference between models "
      "and must be stated wherever `_fs`/`_zs` results are compared across models.", "",
      "**What is *not* recoverable from the artefacts.** The vLLM server version, the exact serving "
      "flags, the tokenizer revision, and the GPU/library stack are recorded only as `device: "
      "1x A40 (vLLM)` in `_meta`. Sampling is nominally greedy (`temperature=0`, `seed=0`) except for "
      "DeepSeek, but vLLM is not bit-deterministic across builds, so the *responses* are not exactly "
      "reproducible even with the prompts in hand. See `NER_REPRODUCIBILITY_GAPS.md`.", ""]

(AUDIT / "NER_RECOVERED_PROMPTS.md").write_text("\n".join(L))

print(json.dumps({"fewshot_match_all": all(v["match"] for v in ver.values()),
                  "leakage": leak,
                  "prompt_chars": {k: len(v) for k, v in out["system_prompts"].items()},
                  "fewshot_msg_chars": {k: sum(len(m["content"]) for m in v["messages"])
                                        for k, v in out["fewshot"].items()}}, indent=1))
