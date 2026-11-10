"""P2 - build normalized judge input files for the three artifact types.

Read-only against frozen artifacts. Writes to $OUTD/labeled/:
  triples_input.jsonl, mappings_input.jsonl, records_input.jsonl

Framing: this feeds an LLM-as-judge evaluation (extractor = Qwen 3.5:9b). It is
NOT a human gold standard.
"""

_CDM_ROOT = next(p for p in __import__("pathlib").Path(__file__).resolve().parents
                 if (p / ".cdm_root").is_file())  # repo root, found at run time
import argparse
import csv
import json
import os
import re

ROOT = str(_CDM_ROOT)
OUTD = os.path.join(ROOT, "outputs/logs", "gold_standard")
LAB = os.path.join(OUTD, "labeled")

REL = os.path.join(ROOT, "pipelines/corpus_v2", "releases", "2.2.0", "data")
TRIPLES = os.path.join(REL, "canonical_triples.jsonl")
MENTIONS = os.path.join(REL, "triple_mentions.jsonl")
SECTIONS = os.path.join(REL, "sections.jsonl")
MAPPINGS = os.path.join(ROOT, "outputs/results", "terminology_v1", "term_ontology_mappings.jsonl")
DEFS = os.path.join(ROOT, "outputs/results", "terminology_v1", "term_definitions.jsonl")
RECORDS = os.path.join(ROOT, "releases/data_catalogue", "records", "catalogue_records.jsonl")


def norm(t):
    return re.sub(r"\s+", " ", t or "").strip()


def write_jsonl(path, rows):
    with open(path, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return os.path.getsize(path)


def build_triples():
    ment = {}
    with open(MENTIONS) as fh:
        for line in fh:
            d = json.loads(line)
            ment[d["triple_mention_id"]] = d
    out = []
    joined = 0
    with open(TRIPLES) as fh:
        for line in fh:
            d = json.loads(line)
            m = None
            for mid in d.get("triple_mention_ids", []):
                if mid in ment:
                    m = ment[mid]
                    break
            if m is not None:
                joined += 1
            out.append({
                "item_id": d["canonical_triple_id"],
                "subject_surface": d.get("subject_display_label") or d.get("subject_normalized_label", ""),
                "subject_type": d.get("subject_entity_type", ""),
                "relation": d.get("relation_normalized", ""),
                "object_surface": d.get("object_display_label") or d.get("object_normalized_label", ""),
                "object_type": d.get("object_entity_type", ""),
                "evidence_text": (m or {}).get("source_sentence", ""),
                "paper_id": (m or {}).get("paper_id", "") or (d.get("paper_ids") or [""])[0],
                "section_id": (m or {}).get("section_id", ""),
            })
    return out, joined


def build_mappings():
    defs = {}
    with open(DEFS) as fh:
        for line in fh:
            d = json.loads(line)
            key = d.get("term_norm") or d.get("term")
            if key and key not in defs:
                defs[key] = d.get("definition_text", "")
    out = []
    joined = 0
    with open(MAPPINGS) as fh:
        for line in fh:
            d = json.loads(line)
            tdef = defs.get(d.get("term_norm") or d.get("term"), "")
            if tdef:
                joined += 1
            out.append({
                "item_id": d.get("mapping_id"),
                "term": d.get("term", ""),
                "cdm_type": d.get("cdm_type", ""),
                "ontology_name": d.get("ontology_name") or "",
                "concept_id": d.get("concept_id") or "",
                "concept_label": d.get("concept_label") or "",
                "term_definition": tdef,
            })
    return out, joined


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


def window(text, cs, ce, before=200, after=200):
    if text is None or cs is None:
        return "", ""
    return text[max(0, cs - before):cs], text[ce:ce + after]


def build_records():
    secs = {}
    with open(SECTIONS) as fh:
        for line in fh:
            d = json.loads(line)
            secs[(d["paper_id"], d["section_id_original"])] = d.get("section_text_original")
    out = []
    joined = 0
    null_span = 0
    with open(RECORDS) as fh:
        for line in fh:
            d = json.loads(line)
            f = d.get("fields", {})
            text = secs.get((d["paper_id"], d["section_id"]))
            if text is not None:
                joined += 1
            cs, ce = d.get("char_start"), d.get("char_end")
            if cs is None:
                null_span += 1
                cb, ca = "", ""
            else:
                cb, ca = window(text, cs, ce)
            out.append({
                "item_id": "%s|%s|%s|%s|%s" % (
                    d["entity_type"], d["paper_id"], d["section_id"],
                    d.get("char_start"), d.get("char_end")),
                "entity_type": d["entity_type"],
                "paper_id": d["paper_id"],
                "section_id": d["section_id"],
                "claim_text": claim_text(d["entity_type"], f),
                "evidence_text": f.get("evidence_text", ""),
                "context_before": cb,
                "context_after": ca,
            })
    return out, joined, null_span


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default=LAB)
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)

    tr, tr_join = build_triples()
    mp, mp_join = build_mappings()
    rc, rc_join, rc_null = build_records()

    p1 = os.path.join(args.outdir, "triples_input.jsonl")
    p2 = os.path.join(args.outdir, "mappings_input.jsonl")
    p3 = os.path.join(args.outdir, "records_input.jsonl")
    s1 = write_jsonl(p1, tr)
    s2 = write_jsonl(p2, mp)
    s3 = write_jsonl(p3, rc)

    print("triples  : %6d rows  %8.1f MB  join(mention) %6d/%d = %.1f%%"
          % (len(tr), s1 / 1e6, tr_join, len(tr), 100.0 * tr_join / max(1, len(tr))))
    print("mappings : %6d rows  %8.1f MB  join(definition) %6d/%d = %.1f%%"
          % (len(mp), s2 / 1e6, mp_join, len(mp), 100.0 * mp_join / max(1, len(mp))))
    print("records  : %6d rows  %8.1f MB  join(section) %6d/%d = %.1f%%  (null-span %d)"
          % (len(rc), s3 / 1e6, rc_join, len(rc), 100.0 * rc_join / max(1, len(rc)), rc_null))
    with open(os.path.join(args.outdir, "_input_stats.json"), "w") as fh:
        json.dump({
            "triples": {"rows": len(tr), "bytes": s1, "mention_join": tr_join},
            "mappings": {"rows": len(mp), "bytes": s2, "definition_join": mp_join},
            "records": {"rows": len(rc), "bytes": s3, "section_join": rc_join, "null_span": rc_null},
        }, fh, indent=1)


if __name__ == "__main__":
    main()
