"""P4 - build judge input files for the four artifact types (500 each).

Read-only against frozen artifacts. Deterministic sha1 ranking. Writes to $OUTD:
  input_C1.jsonl  (catalogue records)
  input_C2.jsonl  (inventory -> canonical term types)
  input_C3.jsonl  (ontology mappings)
  input_C4.jsonl  (canonical triples)

Every item carries the generic judge fields (claim_text, evidence_text,
context_before, context_after) plus artifact-specific fields. Only human-visible
fields are included; no confidence / extraction_method / internal metadata.

Framing: this feeds an LLM-as-judge evaluation (judge = Gemma 4 E4B, extractor =
Qwen 3.5:9b). It is NOT a human gold standard.

Usage:
  python build_inputs.py            # writes 4 x 500-item inputs to $OUTD
  python build_inputs.py --per-artifact 50 --outdir /tmp/x
"""

_CDM_ROOT = next(p for p in __import__("pathlib").Path(__file__).resolve().parents
                 if (p / ".cdm_root").is_file())  # repo root, found at run time
import argparse
import collections
import csv
import hashlib
import json
import os
import re

ROOT = str(_CDM_ROOT)
OUTD = os.path.join(ROOT, "outputs/logs", "llm_judge")
REL = os.path.join(ROOT, "pipelines/corpus_v2", "releases", "2.2.0", "data")
SECTIONS = os.path.join(REL, "sections.jsonl")
TRIPLES = os.path.join(REL, "canonical_triples.jsonl")
MENTIONS = os.path.join(REL, "triple_mentions.jsonl")
MAPPINGS = os.path.join(ROOT, "outputs/results", "terminology_v1", "term_ontology_mappings.jsonl")
DEFS = os.path.join(ROOT, "outputs/results", "terminology_v1", "term_definitions.jsonl")
RECORDS = os.path.join(ROOT, "releases/data_catalogue", "records", "catalogue_records.jsonl")
CROSSWALK = os.path.join(ROOT, "docs", "crosswalk", "inventory_to_canonical.csv")
INVENTORY = os.path.join(ROOT, "pipelines/corpus_v2", "releases", "2.2.0", "terminology_inventory.csv")

SAMPLE_PREFIX = "judge-gemma4-v1|"


def norm(t):
    return re.sub(r"\s+", " ", t or "").strip()


def rank(sid):
    return hashlib.sha1((SAMPLE_PREFIX + str(sid)).encode()).hexdigest()


def allocate(groups, k):
    """Proportional largest-remainder allocation over strata (>=1 if room)."""
    total = sum(len(v) for v in groups.values())
    if total == 0:
        return {}
    if k < len(groups):
        # not enough to give each stratum one; take from the largest strata
        order = sorted(groups, key=lambda g: -len(groups[g]))
        return {g: (1 if i < k else 0) for i, g in enumerate(order)}
    raw = {g: k * len(v) / total for g, v in groups.items()}
    alloc = {g: max(1, int(raw[g])) for g in groups}
    # fix overshoot / undershoot by largest remainder among non-floor candidates
    while sum(alloc.values()) > k:
        g = max(alloc, key=lambda x: alloc[x] - raw[x])
        if alloc[g] > 1:
            alloc[g] -= 1
        else:
            g2 = max((x for x in alloc if alloc[x] > 1), key=lambda x: alloc[x], default=None)
            if g2 is None:
                break
            alloc[g2] -= 1
    rem = k - sum(alloc.values())
    if rem > 0:
        order = sorted(groups, key=lambda g: -(raw[g] - int(raw[g])))
        for g in order[:rem]:
            alloc[g] += 1
    return alloc


def strat_sample(rows, key, k):
    groups = collections.defaultdict(list)
    for r in rows:
        groups[r[key]].append(r)
    alloc = allocate(groups, k)
    picked = []
    for g in sorted(groups):
        n = alloc.get(g, 0)
        if n <= 0:
            continue
        picked.extend(sorted(groups[g], key=lambda r: rank(r["_sid"]))[:n])
    picked.sort(key=lambda r: rank(r["_sid"]))
    return picked, {g: alloc.get(g, 0) for g in sorted(groups)}


def write_jsonl(path, rows):
    with open(path, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return os.path.getsize(path)


# ── shared lookups ───────────────────────────────────────────────────────────
def load_sections():
    bypair, byrec = {}, {}
    with open(SECTIONS) as fh:
        for line in fh:
            d = json.loads(line)
            t = d.get("section_text_original")
            bypair[(d["paper_id"], d["section_id_original"])] = t
            byrec[d["section_record_id"]] = t
    return bypair, byrec


def window(text, cs, ce, before=200, after=200):
    if text is None or cs is None:
        return "", ""
    return text[max(0, cs - before):cs], text[ce:ce + after]


CLAIM_FIELDS = {
    "assays": ["assay_type", "target_gene_or_region", "sequencing_platform", "library_preparation"],
    "cohorts": ["population_description", "cohort_label", "health_status"],
    "data_assets": ["asset_name", "description", "asset_type"],
    "datasets": ["dataset_title", "dataset_description", "dataset_type"],
    "findings": ["finding_text", "outcome", "author_interpretation"],
    "samples": ["sample_type", "body_site", "sample_processing"],
}


def claim_text(et, flds):
    parts = []
    for k in CLAIM_FIELDS.get(et, []):
        v = flds.get(k)
        if isinstance(v, str) and v.strip():
            parts.append("%s: %s" % (k, v.strip()))
        if len(parts) >= 2:
            break
    return " | ".join(parts)


# ── C1: catalogue records ────────────────────────────────────────────────────
def build_c1(k):
    secs, _ = load_sections()
    rows = []
    with open(RECORDS) as fh:
        for line in fh:
            d = json.loads(line)
            f = d.get("fields", {})
            rows.append({
                "_sid": "%s|%s|%s|%s|%s|%s" % (
                    d["entity_type"], d["paper_id"], d["section_id"],
                    d.get("char_start"), d.get("char_end"), f.get("evidence_text", "")),
                "entity_type": d["entity_type"],
                "paper_id": d["paper_id"],
                "section_id": d["section_id"],
                "claim_text": claim_text(d["entity_type"], f),
                "evidence_text": f.get("evidence_text", ""),
                "_cs": d.get("char_start"),
                "_ce": d.get("char_end"),
            })
    picked, alloc = strat_sample(rows, "entity_type", k)
    out = []
    for r in picked:
        text = secs.get((r["paper_id"], r["section_id"]))
        cb, ca = window(text, r["_cs"], r["_ce"])
        out.append({
            "item_id": "C1|%s" % r["_sid"],
            "artifact": "C1",
            "entity_type": r["entity_type"],
            "paper_id": r["paper_id"],
            "section_id": r["section_id"],
            "claim_text": r["claim_text"],
            "evidence_text": r["evidence_text"],
            "context_before": cb,
            "context_after": ca,
        })
    return out, alloc, len(rows)


# ── C2: inventory -> canonical types ─────────────────────────────────────────
def build_c2(k):
    ctx = {}
    with open(INVENTORY, newline="") as fh:
        for row in csv.DictReader(fh):
            ctx[row.get("term_normalized", "")] = row.get("example_context", "")
    rows = []
    with open(CROSSWALK, newline="") as fh:
        for row in csv.DictReader(fh):
            if not (row.get("canonical_term_norm") or "").strip():
                continue
            rows.append({
                "_sid": "%s|%s" % (row["inventory_term_normalized"], row["canonical_term_id"]),
                "type_relation": (row.get("type_relation") or "UNKNOWN").strip() or "UNKNOWN",
                "inventory_term": row["inventory_term"],
                "inventory_types": row["inventory_types"],
                "canonical_term_norm": row["canonical_term_norm"],
                "canonical_cdm_type": row["canonical_cdm_type"],
                "canonical_alternative_types": row.get("canonical_alternative_types", ""),
                "context_sentence": ctx.get(row["inventory_term_normalized"], ""),
            })
    picked, alloc = strat_sample(rows, "type_relation", k)
    out = []
    for r in picked:
        ct = "term '%s' typed as %s (inventory types: %s)" % (
            r["inventory_term"], r["canonical_cdm_type"], r["inventory_types"])
        out.append({
            "item_id": "C2|%s" % r["_sid"],
            "artifact": "C2",
            "type_relation": r["type_relation"],
            "inventory_term": r["inventory_term"],
            "inventory_types": r["inventory_types"],
            "canonical_term_norm": r["canonical_term_norm"],
            "canonical_cdm_type": r["canonical_cdm_type"],
            "canonical_alternative_types": r["canonical_alternative_types"],
            "context_sentence": r["context_sentence"],
            "claim_text": ct,
            "evidence_text": r["context_sentence"],
            "context_before": "",
            "context_after": "",
        })
    return out, alloc, len(rows)


# ── C3: ontology mappings ────────────────────────────────────────────────────
def build_c3(k):
    defs = {}
    with open(DEFS) as fh:
        for line in fh:
            d = json.loads(line)
            key = d.get("term_norm") or d.get("term")
            if key and key not in defs:
                defs[key] = d.get("definition_text", "")

    rows = []
    with open(MAPPINGS) as fh:
        for line in fh:
            d = json.loads(line)
            rows.append({
                "_sid": d.get("mapping_id") or "|".join(
                    str(d.get(x)) for x in ("term_id", "ontology_name", "concept_id",
                                            "mapping_relation", "candidate_rank")),
                "mapping_relation": (d.get("mapping_relation") or "UNKNOWN").strip() or "UNKNOWN",
                "term": d.get("term", ""),
                "term_norm": d.get("term_norm", ""),
                "cdm_type": d.get("cdm_type", ""),
                "ontology_name": d.get("ontology_name") or "",
                "concept_id": d.get("concept_id") or "",
                "concept_label": d.get("concept_label") or "",
                "definition_context": defs.get(d.get("term_norm") or d.get("term"), ""),
            })
    picked, alloc = strat_sample(rows, "mapping_relation", k)

    # first-sentence fallback for sampled terms lacking a definition
    need = {r["term_norm"] or r["term"] for r in picked if not r["definition_context"]}
    need = {t for t in need if t}
    found = {}
    if need:
        _, byrec = load_sections()
        for text in byrec.values():
            if not text or len(found) >= len(need):
                continue
            for s in re.split(r"(?<=[.!?])\s+", text):
                s = norm(s)
                if not (20 <= len(s) <= 400):
                    continue
                sl = s.lower()
                for t in list(need):
                    if t in sl:
                        found[t] = s
                        need.discard(t)
                if not need:
                    break

    out = []
    for r in picked:
        dc = r["definition_context"] or found.get(r["term_norm"] or r["term"], "")
        ct = "term '%s' (%s) mapped to %s %s '%s'" % (
            r["term"], r["cdm_type"], r["ontology_name"] or "?",
            r["concept_id"] or "?", r["concept_label"] or "")
        out.append({
            "item_id": "C3|%s" % r["_sid"],
            "artifact": "C3",
            "mapping_relation": r["mapping_relation"],
            "term": r["term"],
            "cdm_type": r["cdm_type"],
            "ontology_name": r["ontology_name"],
            "concept_id": r["concept_id"],
            "concept_label": r["concept_label"],
            "definition_context": dc,
            "claim_text": ct,
            "evidence_text": dc,
            "context_before": "",
            "context_after": "",
        })
    return out, alloc, len(rows)


# ── C4: canonical triples ────────────────────────────────────────────────────
def build_c4(k):
    ment = {}
    with open(MENTIONS) as fh:
        for line in fh:
            d = json.loads(line)
            ment[d["triple_mention_id"]] = d
    _, byrec = load_sections()
    rows = []
    with open(TRIPLES) as fh:
        for line in fh:
            d = json.loads(line)
            m = next((ment[mid] for mid in d.get("triple_mention_ids", []) if mid in ment), None)
            ev = (m or {}).get("source_sentence", "")
            sec = byrec.get((m or {}).get("section_id"), "")
            ctxt = ""
            if ev and sec:
                i = norm(sec).find(norm(ev))
                if i >= 0:
                    n = norm(sec)
                    ctxt = n[max(0, i - 150):i + len(norm(ev)) + 150]
            rows.append({
                "_sid": d["canonical_triple_id"],
                "relation": (d.get("relation_normalized") or "UNKNOWN").strip() or "UNKNOWN",
                "subject_surface": d.get("subject_display_label") or d.get("subject_normalized_label", ""),
                "subject_type": d.get("subject_entity_type", ""),
                "object_surface": d.get("object_display_label") or d.get("object_normalized_label", ""),
                "object_type": d.get("object_entity_type", ""),
                "evidence_text": ev,
                "context_sentence": ctxt,
            })
    picked, alloc = strat_sample(rows, "relation", k)
    out = []
    for r in picked:
        ct = "%s --%s--> %s" % (r["subject_surface"], r["relation"], r["object_surface"])
        out.append({
            "item_id": "C4|%s" % r["_sid"],
            "artifact": "C4",
            "relation": r["relation"],
            "subject_surface": r["subject_surface"],
            "subject_type": r["subject_type"],
            "object_surface": r["object_surface"],
            "object_type": r["object_type"],
            "evidence_text": r["evidence_text"],
            "context_sentence": r["context_sentence"],
            "claim_text": ct,
            "context_before": r["context_sentence"][:150],
            "context_after": r["context_sentence"][-150:] if r["context_sentence"] else "",
        })
    return out, alloc, len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-artifact", type=int, default=500)
    ap.add_argument("--outdir", default=OUTD)
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)
    k = args.per_artifact

    builders = [("C1", build_c1), ("C2", build_c2), ("C3", build_c3), ("C4", build_c4)]
    stats = {}
    for name, fn in builders:
        rows, alloc, total = fn(k)
        path = os.path.join(args.outdir, "input_%s.jsonl" % name)
        size = write_jsonl(path, rows)
        stats[name] = {"total_rows": total, "sample": len(rows),
                       "bytes": size, "strata": alloc}
        print("%s: total %7d -> sample %4d  %7.2f MB  strata=%s"
              % (name, total, len(rows), size / 1e6, alloc))

    with open(os.path.join(args.outdir, "_input_stats.json"), "w") as fh:
        json.dump(stats, fh, indent=1)
    print("wrote _input_stats.json")


if __name__ == "__main__":
    main()
