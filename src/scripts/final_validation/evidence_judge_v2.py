"""Catalogue evidence judge, rubric v2 (2026-11-10): fixes the three causes of judge disagreement found by
judge_disagreement_by_field.py. Freeze exception: new model run, PENDING project-lead approval (CHANGE_RECORD).

What changed from the 2026-11-09 constrained judge (same records, same passages, same CDM 3.0.3 read-only):
  1. Link fields (cohort_id / assay_id / dataset_id) are NOT judged by a model: a passage cannot show an internal id.
     They are checked structurally by link_structural_check.py.
  2. Classification fields (cites_other_work, is_primary_finding, direction, taxonomic_rank, intervention_category,
     cohort_role, longitudinal, dataset_role, data_availability_status, original_or_reused, access_status) are asked
     BLIND: the judge answers a decomposed question from a closed list (plus CANNOT_TELL) without seeing the stored
     value; the comparison with the stored value is done by this script (MATCH / MISMATCH / CANNOT_TELL). The old
     rubric asked whether the text "states" values such as cites_other_work=NO, which a passage cannot state.
  3. Stated-value fields: SUPPORTED needs an evidence span copied from the text; the script checks that the span is
     in the source text and contains the value (SUPPORTED with a failed check is reported as unverified). UNCERTAIN
     is narrowed to "the text is cut off before the relevant part or is about a different record".
Schema-enforced output (vLLM json_schema), temperature 0. Records are split by a fixed hash: dev (~1%, rubric
development) and test (the rest); the rubric is frozen (PROMPT_SHA256 recorded per output line) before the test run.
Three judges from three model families, all local on one A40: Qwen3.5-9B (AWQ), Llama-3.1-8B (AWQ), Mistral-7B (AWQ).
MODEL JUDGEMENTS, not accuracy.

    python evidence_judge_v2.py judge --model qwen9 --host http://127.0.0.1:8000 --split dev --shard 0 --nshards 1
Written with Claude Code (declare).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(ROOT / "src/scripts/final_validation"))
import evidence_judge_constrained as V1  # noqa: E402  (records(), ENTITY, RULE, LINKS: identical inputs)

OUT = ROOT / "outputs/results/benchmark/judge_v2_2026-11-10"
MODELS = {"qwen9": "cyankiwi/Qwen3.5-9B-AWQ-4bit", "llama": "hugging-quants/Meta-Llama-3.1-8B-Instruct-AWQ-INT4",
          "mistral": "TechxGenus/Mistral-7B-Instruct-v0.3-AWQ"}
NO_SYSTEM_ROLE = {"mistral"}
THINKING_OFF = {"qwen9"}
AVAIL = ["PUBLIC", "CONTROLLED", "EMBARGOED", "UPON_REQUEST", "NOT_DEPOSITED", "LINK_ONLY"]
RANKS = ["strain", "species", "genus", "family", "order", "class", "phylum", "kingdom_or_domain", "OTU_or_ASV",
         "community_or_diversity", "metabolite_or_molecule", "gene_or_pathway", "host_or_clinical_measure",
         "multiple_levels", "other"]
INTERVENTIONS = ["INFECTION_OR_DISEASE_STATE", "NOT_AN_INTERVENTION", "METHOD_OR_TECHNICAL", "OTHER_DRUG", "DIET_OR_FIBRE",
                 "PREBIOTIC_OR_SYNBIOTIC", "AGE_OR_DEVELOPMENT", "ENVIRONMENT_OR_GEOGRAPHY", "EXERCISE_OR_LIFESTYLE",
                 "ANTIBIOTIC", "FECAL_MICROBIOTA_TRANSPLANT", "SURGERY_OR_PROCEDURE", "SEX_OR_GENETICS", "PROBIOTIC", "VACCINE"]
# (table, field) -> (decomposed question, options). CANNOT_TELL is always added.
CLASSIFY = {
    ("claim", "cites_other_work"): ("Is this finding attributed to ANOTHER, previously published study (the sentence cites "
                                    "earlier work for it) rather than reported as a result of THIS paper?", ["YES", "NO"]),
    ("claim", "is_primary_finding"): ("Is this finding a result of THIS study's own analysis (not background, not a methods "
                                      "detail, not a statement about other studies)?", ["YES", "NO"]),
    ("claim", "direction"): ("What change does the text state for the feature in this comparison? INCREASE = higher, "
                             "enriched or positively associated; DECREASE = lower, depleted or negatively associated; "
                             "NO_ASSOCIATION = the text says there is no significant difference or association; MIXED = "
                             "opposite directions within this one finding; NOT_STATED = the text gives no direction.",
                             ["INCREASE", "DECREASE", "NO_ASSOCIATION", "MIXED", "NOT_STATED"]),
    ("claim", "taxonomic_rank"): ("At what level or of what kind is the feature of this finding? Use multiple_levels if it "
                                  "names features at several ranks.", RANKS),
    ("claim", "intervention_category"): ("Which category best describes the exposure, condition or intervention that this "
                                         "finding compares? NOT_AN_INTERVENTION if the comparison is not an exposure, "
                                         "condition or intervention (e.g. body sites, methods).", INTERVENTIONS),
    ("cohort", "cohort_role"): ("Does this cohort consist of cases AND controls (two or more compared groups), or of a "
                                "single group?", ["cases_and_controls", "single_group"]),
    ("cohort", "longitudinal"): ("Is this cohort followed over time with repeated sampling or measurements?", ["YES", "NO"]),
    ("dataset", "dataset_role"): ("Is this dataset generated by THIS study (primary_study_data) or an external dataset that "
                                  "the study links to or reuses (linked_data)?", ["primary_study_data", "linked_data"]),
    ("dataset", "data_availability_status"): ("How does the text say this dataset can be accessed?", AVAIL),
    ("dataset", "original_or_reused"): ("Was this dataset produced by this study (ORIGINAL) or taken from earlier work "
                                        "(REUSED)?", ["ORIGINAL", "REUSED"]),
    ("data_asset", "access_status"): ("How does the text say this data asset can be accessed?", AVAIL),
}
CONTEXT = {"claim": ["finding_text", "taxon_or_feature", "comparison_or_exposure", "outcome"],
           "cohort": ["cohort_label"], "sample": ["body_site", "sample_type"], "assay": ["assay_type"],
           "dataset": ["dataset_title", "repository_accession"], "data_asset": ["asset_name"]}
# v2.1: model-written labels and summaries cannot be "stated" verbatim; they are judged as fair / unfair descriptions
LABELS = {("claim", "finding_domain"), ("claim", "author_interpretation"), ("claim", "effect_measure"),
          ("cohort", "population_description"), ("dataset", "dataset_description"), ("data_asset", "description")}
LABEL_V = ["FAIR", "UNFAIR", "CANNOT_TELL"]
CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
STATED = ["SUPPORTED", "NOT_SUPPORTED", "CONTRADICTED", "WRONG_FIELD", "UNCERTAIN"]
SYSTEM = """You check one record extracted from a scientific paper against the paper's text. Use ONLY the text given;
never outside knowledge. Answer three parts.

PART A - CLASSIFY. For each question, choose the option that the text supports. You are NOT shown the extracted
answer; answer from the text. Choose CANNOT_TELL only if the text gives no basis for any option.

PART B - CHECK STATED VALUES. For each field give a verdict and evidence:
- SUPPORTED: the text states this value for this field of this record. Paraphrase, abbreviation, synonym, unit or
  formatting differences are fine. "e" MUST be the shortest exact copy (max 25 words) of the TEXT that states it -
  copied from the TEXT, never from the value. If the value paraphrases the text, copy the text words it paraphrases.
- NOT_SUPPORTED: no part of the text states this value (even if it is plausible).
- CONTRADICTED: the text states a different value for this field.
- WRONG_FIELD: the value appears in the text but describes a different field or a different record.
- UNCERTAIN: ONLY if the text is cut off before the relevant part, or the text is about a different record.
  Do not use UNCERTAIN because a judgement is difficult.
For every verdict except SUPPORTED, "e" may be "".

PART C - LABELS AND SUMMARIES. These short labels or summaries were written by the extraction model, so the text
will not contain them word for word. Decide: FAIR = a correct description of what the text says about this record;
UNFAIR = wrong, or adds things the text does not say; CANNOT_TELL = the text gives no basis.

Example (invented). Text: "Faecal samples were stored at -80 C. Sequencing used the Illumina MiSeq platform."
  sequencing_platform = "Illumina MiSeq" -> {"v": "SUPPORTED", "e": "Illumina MiSeq platform"}
  storage_condition = "-20 C" -> {"v": "CONTRADICTED", "e": "stored at -80 C"}
  dna_extraction_method = "QIAamp kit" -> {"v": "NOT_SUPPORTED", "e": ""}
Example (invented). Text: "We compared 40 patients with Crohn's disease and 38 healthy controls."
  comparison_or_exposure = "CD vs controls" -> {"v": "SUPPORTED", "e": "40 patients with Crohn's disease and 38 healthy controls"}
  finding_domain = "case_control_comparison" -> FAIR
Example (invented). Text: "Consistent with Smith et al. [12], Prevotella was enriched in rural children."
  cites_other_work -> YES; direction -> INCREASE; taxonomic_rank -> genus

Also give "record": PASS if the record as a whole is a genuine record of the stated type reported as THIS paper's
own work, FAIL if not (cited prior work, methods boilerplate, table fragment, wrong type), UNCERTAIN otherwise.
Return ONLY the JSON object required by the schema."""
PROMPT_SHA256 = hashlib.sha256((SYSTEM + json.dumps({"|".join(k): v for k, v in CLASSIFY.items()}, sort_keys=True)).encode()).hexdigest()


def split_of(rid):
    return "dev" if int(hashlib.sha1(rid.encode()).hexdigest(), 16) % 100 == 0 else "test"


def build(rec):
    t = rec["table"]
    cls = {f: CLASSIFY[(t, f)] for f in rec["values"] if (t, f) in CLASSIFY}
    labels = {f: v for f, v in rec["values"].items() if (t, f) in LABELS}
    stated = {f: v for f, v in rec["values"].items() if (t, f) not in CLASSIFY and (t, f) not in LABELS and f not in V1.LINKS}
    for f in rec.get("missing_codes", {}):                 # classify fields are asked even when the stored value is a code
        if (t, f) in CLASSIFY:
            cls[f] = CLASSIFY[(t, f)]
    lines = [f"RECORD TYPE: {V1.ENTITY[t]}", "", "TEXT:", CTRL.sub(" ", rec["passage"]), ""]
    for f, q in rec["field_quotes"].items():
        if f in stated or f in cls or f in labels:
            lines += [f"ADDITIONAL TEXT for field {f}:", CTRL.sub(" ", q), ""]
    ctx = [f"- {f}: {rec['values'][f]}" for f in CONTEXT[t] if f in rec["values"]]
    if ctx:
        lines += ["THE RECORD (for identification):", *ctx, ""]
    if cls:
        lines.append("PART A - CLASSIFY:")
        for f, (q, opts) in cls.items():
            lines.append(f"- {f}: {q} Options: {', '.join(opts)}, CANNOT_TELL")
        lines.append("")
    if stated:
        lines.append("PART B - CHECK STATED VALUES:")
        for f, v in stated.items():
            rule = f" (rule: {V1.RULE[f]})" if f in V1.RULE else ""
            lines.append(f"- {f}{rule}: {CTRL.sub(' ', v)}")
        lines.append("")
    if labels:
        lines.append("PART C - LABELS AND SUMMARIES:")
        for f, v in labels.items():
            lines.append(f"- {f}: {CTRL.sub(' ', v)}")
    schema = {"type": "object", "additionalProperties": False, "required": ["record", "classify", "stated", "label"],
              "properties": {
                  "record": {"type": "string", "enum": ["PASS", "FAIL", "UNCERTAIN"]},
                  "classify": {"type": "object", "additionalProperties": False, "required": list(cls),
                               "properties": {f: {"type": "string", "enum": o + ["CANNOT_TELL"]} for f, (_, o) in cls.items()}},
                  "stated": {"type": "object", "additionalProperties": False, "required": list(stated),
                             "properties": {f: {"type": "object", "additionalProperties": False, "required": ["v", "e"],
                                                "properties": {"v": {"type": "string", "enum": STATED},
                                                               "e": {"type": "string", "maxLength": 300}}}
                                            for f in stated}},
                  "label": {"type": "object", "additionalProperties": False, "required": list(labels),
                            "properties": {f: {"type": "string", "enum": LABEL_V} for f in labels}}}}
    return "\n".join(lines), schema, cls, {**stated, **labels}


def judge(a):
    out = a.out / a.split
    out.mkdir(parents=True, exist_ok=True)
    recs = [r for r in V1.records() if r["values"] and (a.split == "all" or split_of(r["record_id"]) == a.split)]
    recs = [r for i, r in enumerate(recs) if i % a.nshards == a.shard]
    path = out / f"{a.model}.shard{a.shard}.jsonl"
    done = set()
    if path.exists():
        done = {(j["table"], j["record_id"]) for j in map(json.loads, open(path)) if "error" not in j}
    todo = [r for r in recs if (r["table"], r["record_id"]) not in done]
    print(f"{a.model} {a.split} shard {a.shard}: {len(recs)} records, {len(todo)} to do; prompt {PROMPT_SHA256[:12]}", flush=True)

    def ask(rec):
        user, schema, cls, stated = build(rec)
        if not cls and not stated:
            return None
        msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
        if a.model in NO_SYSTEM_ROLE:
            msgs = [{"role": "user", "content": SYSTEM + "\n\n" + user}]
        body = {"model": MODELS[a.model], "messages": msgs, "temperature": 0, "seed": a.seed, "max_tokens": 3000,
                "response_format": {"type": "json_schema", "json_schema": {"name": "v2", "schema": schema, "strict": True}}}
        if a.model in THINKING_OFF:
            body["chat_template_kwargs"] = {"enable_thinking": False}
        err = None
        for _ in range(3):
            try:
                req = urllib.request.Request(a.host.rstrip("/") + "/v1/chat/completions", data=json.dumps(body).encode(),
                                             headers={"Content-Type": "application/json"})
                r = json.loads(urllib.request.urlopen(req, timeout=900).read())
                txt = r["choices"][0]["message"].get("content") or "{}"
                lenient = False
                try:
                    j = json.loads(txt)
                except ValueError as e1:
                    try:                       # raw control characters (tab/newline copied from the paper into "e") are
                        j = json.loads(txt, strict=False)   # rejected by the strict parser; same content otherwise
                        lenient = True
                    except ValueError:
                        raise ValueError(f"bad JSON ({e1}) finish={r['choices'][0].get('finish_reason')} len={len(txt)} "
                                         f"tail={txt[-80:]!r}")
                return {"table": rec["table"], "record_id": rec["record_id"], "paper_id": rec["paper_id"],
                        "record": j.get("record"), "classify": j.get("classify", {}), "stated": j.get("stated", {}), "label": j.get("label", {}),
                        "finish": r["choices"][0].get("finish_reason"), "model": MODELS[a.model], "prompt_sha256": PROMPT_SHA256, "seed": a.seed, "json_lenient": lenient}
            except Exception as ex:  # noqa: BLE001
                err = repr(ex)[:200]
        return {"table": rec["table"], "record_id": rec["record_id"], "error": err}

    t0 = time.time()
    with open(path, "a", encoding="utf-8") as fh, ThreadPoolExecutor(a.parallel) as pool:
        for i, res in enumerate(pool.map(ask, todo)):
            if res:
                fh.write(json.dumps(res, ensure_ascii=False) + "\n")
            if i % 500 == 0:
                fh.flush()
                print(f"  {i}/{len(todo)} {time.time() - t0:.0f}s", flush=True)
    print("done", round(time.time() - t0), flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["judge", "prompt"])
    ap.add_argument("--model", choices=sorted(MODELS), default="qwen9")
    ap.add_argument("--host", default="http://127.0.0.1:8000")
    ap.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--nshards", type=int, default=1)
    ap.add_argument("--parallel", type=int, default=48)
    ap.add_argument("--seed", type=int, default=0, help="sampling seed (no effect at temperature 0; kept for the record)")
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args(argv)
    if a.cmd == "prompt":                                    # print one example prompt (dev) for inspection
        r = next(r for r in V1.records() if r["values"] and r["table"] == "claim" and split_of(r["record_id"]) == "dev")
        print(build(r)[0])
        print("PROMPT_SHA256", PROMPT_SHA256)
        return 0
    return judge(a)


if __name__ == "__main__":
    raise SystemExit(main())
