"""F1 — build FULL judge inputs (every row, no sampling).

Mirrors the per-row field extraction of
src/scripts/llm_judge_gemma4/build_inputs.py (the 500-item sample builder) but emits
EVERY row instead of a stratified sample, and streams to disk so the 334k-row C3
file does not have to fit in memory.

Read-only against all source artifacts. Writes to $OUTD:
  input_full_C1.jsonl  catalogue records      (56,985)
  input_full_C2.jsonl  inventory->canonical   (27,870)
  input_full_C3.jsonl  ontology mappings     (334,231)
  input_full_C4.jsonl  canonical triples      (32,713)
  _input_full_stats.json

A join failure above 0.5% for any artifact aborts the build with a non-zero exit
code — a silent partial join would corrupt every downstream rate.

Differences from the sample builder (deliberate, documented):
  * No stratified sampling / sha1 ranking — every row is kept.
  * C3's first-sentence fallback IS applied at full scale, but with an
    Aho-Corasick automaton over the 74,618 distinct terms that lack a stored
    definition. The sample builder did the same lookup with a nested
    substring loop, which is O(sections x terms) and intractable here; the
    automaton makes it O(total_section_chars + matches) and yields the same
    answer (first sentence in section order, 20-400 chars, containing the term).
  * item_id construction is unchanged, so the 500 sampled items are exact
    subsets of these files and cache keys remain compatible.

Usage:
  python build_inputs_full.py [--outdir outputs/logs/llm_judge] [--max-join-fail 0.005]
"""

_CDM_ROOT = next(p for p in __import__("pathlib").Path(__file__).resolve().parents
                 if (p / ".cdm_root").is_file())  # repo root, found at run time
import argparse
import csv
import json
import os
import re
import sys

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

CLAIM_FIELDS = {
    "assays": ["assay_type", "target_gene_or_region", "sequencing_platform", "library_preparation"],
    "cohorts": ["population_description", "cohort_label", "health_status"],
    "data_assets": ["asset_name", "description", "asset_type"],
    "datasets": ["dataset_title", "dataset_description", "dataset_type"],
    "findings": ["finding_text", "outcome", "author_interpretation"],
    "samples": ["sample_type", "body_site", "sample_processing"],
}


def norm(t):
    return re.sub(r"\s+", " ", t or "").strip()


def window(text, cs, ce, before=200, after=200):
    if text is None or cs is None:
        return "", ""
    return text[max(0, cs - before):cs], text[ce:ce + after]


def claim_text(et, flds):
    parts = []
    for k in CLAIM_FIELDS.get(et, []):
        v = flds.get(k)
        if isinstance(v, str) and v.strip():
            parts.append("%s: %s" % (k, v.strip()))
        if len(parts) >= 2:
            break
    return " | ".join(parts)


def load_sections():
    bypair, byrec = {}, {}
    with open(SECTIONS) as fh:
        for line in fh:
            d = json.loads(line)
            t = d.get("section_text_original")
            bypair[(d["paper_id"], d["section_id_original"])] = t
            byrec[d["section_record_id"]] = t
    return bypair, byrec


class Writer:
    def __init__(self, path):
        self.path = path
        self.fh = open(path, "w", encoding="utf-8")
        self.n = 0

    def write(self, obj):
        self.fh.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self.n += 1

    def close(self):
        self.fh.close()
        return os.path.getsize(self.path)


# ── C1: catalogue records ────────────────────────────────────────────────────
def build_c1(w, max_fail):
    bypair, _ = load_sections()
    total = null_span = missing_section = 0
    with open(RECORDS) as fh:
        for line in fh:
            d = json.loads(line)
            f = d.get("fields", {})
            total += 1
            sid = "%s|%s|%s|%s|%s|%s" % (
                d["entity_type"], d["paper_id"], d["section_id"],
                d.get("char_start"), d.get("char_end"), f.get("evidence_text", ""))
            text = bypair.get((d["paper_id"], d["section_id"]))
            cs, ce = d.get("char_start"), d.get("char_end")
            if cs is None or ce is None:
                null_span += 1
                cb, ca = "", ""
            else:
                if text is None:
                    missing_section += 1
                cb, ca = window(text, cs, ce)
            w.write({
                "item_id": "C1|%s" % sid,
                "artifact": "C1",
                "entity_type": d["entity_type"],
                "paper_id": d["paper_id"],
                "section_id": d["section_id"],
                "claim_text": claim_text(d["entity_type"], f),
                "evidence_text": f.get("evidence_text", ""),
                "context_before": cb,
                "context_after": ca,
            })
    fail = missing_section / total if total else 0
    return {"rows": total, "null_span": null_span,
            "section_join_missing": missing_section,
            "join_fail_rate": round(fail, 6)}


# ── C2: inventory -> canonical types ─────────────────────────────────────────
def build_c2(w, max_fail):
    ctx = {}
    with open(INVENTORY, newline="") as fh:
        for row in csv.DictReader(fh):
            ctx[row.get("term_normalized", "")] = row.get("example_context", "")
    total = kept = no_ctx = 0
    with open(CROSSWALK, newline="") as fh:
        for row in csv.DictReader(fh):
            total += 1
            if not (row.get("canonical_term_norm") or "").strip():
                continue
            kept += 1
            c = ctx.get(row["inventory_term_normalized"], "")
            if not c:
                no_ctx += 1
            ct = "term '%s' typed as %s (inventory types: %s)" % (
                row["inventory_term"], row["canonical_cdm_type"], row["inventory_types"])
            w.write({
                "item_id": "C2|%s|%s" % (row["inventory_term_normalized"], row["canonical_term_id"]),
                "artifact": "C2",
                "type_relation": (row.get("type_relation") or "UNKNOWN").strip() or "UNKNOWN",
                "inventory_term": row["inventory_term"],
                "inventory_types": row["inventory_types"],
                "canonical_term_norm": row["canonical_term_norm"],
                "canonical_cdm_type": row["canonical_cdm_type"],
                "canonical_alternative_types": row.get("canonical_alternative_types", ""),
                "context_sentence": c,
                "claim_text": ct,
                "evidence_text": c,
                "context_before": "",
                "context_after": "",
            })
    fail = no_ctx / kept if kept else 0
    return {"rows": kept, "crosswalk_rows": total,
            "context_missing": no_ctx, "join_fail_rate": round(fail, 6)}


# ── C3: ontology mappings ────────────────────────────────────────────────────
def _load_defs():
    defs = {}
    with open(DEFS) as fh:
        for line in fh:
            d = json.loads(line)
            key = d.get("term_norm") or d.get("term")
            if key and key not in defs:
                defs[key] = d.get("definition_text", "")
    return defs


def _first_sentence_context(need):
    """First corpus sentence (section order, 20-400 chars) containing each term.

    Mirrors the sample builder's fallback, but via Aho-Corasick instead of a
    nested substring loop. Returns {term: sentence}.
    """
    if not need:
        return {}
    try:
        import ahocorasick
    except ImportError:  # optional dependency — degrade to no fallback
        print("WARNING: pyahocorasick unavailable; C3 definition_context stays sparse",
              file=sys.stderr)
        return {}

    automaton = ahocorasick.Automaton()
    lowered = {}
    for t in need:
        lt = t.lower()
        lowered.setdefault(lt, t)
        automaton.add_word(lt, lt)
    automaton.make_automaton()

    found, remaining = {}, set(lowered)
    for text in load_sections()[1].values():
        if not text or not remaining:
            continue
        for s in re.split(r"(?<=[.!?])\s+", text):
            s = norm(s)
            if not (20 <= len(s) <= 400):
                continue
            for _, lt in automaton.iter(s.lower()):
                if lt in remaining:
                    found[lowered[lt]] = s
                    remaining.discard(lt)
            if not remaining:
                break
    print("  C3 fallback: resolved %d/%d terms from corpus sentences"
          % (len(found), len(lowered)), flush=True)
    return found


def build_c3(w, max_fail):
    defs = _load_defs()

    # Pass 1: which terms have no stored definition and therefore need a
    # corpus sentence fallback?
    need = set()
    total = 0
    with open(MAPPINGS) as fh:
        for line in fh:
            d = json.loads(line)
            total += 1
            key = d.get("term_norm") or d.get("term")
            if key and key not in defs:
                need.add(key)
    found = _first_sentence_context(need)

    # Pass 2: emit every mapping.
    with_def = with_fallback = 0
    with open(MAPPINGS) as fh:
        for line in fh:
            d = json.loads(line)
            key = d.get("term_norm") or d.get("term")
            dc = defs.get(key, "")
            if dc:
                with_def += 1
            elif key in found:
                dc = found[key]
                with_fallback += 1
            sid = d.get("mapping_id") or "|".join(
                str(d.get(x)) for x in ("term_id", "ontology_name", "concept_id",
                                        "mapping_relation", "candidate_rank"))
            ct = "term '%s' (%s) mapped to %s %s '%s'" % (
                d.get("term", ""), d.get("cdm_type", ""), d.get("ontology_name") or "?",
                d.get("concept_id") or "?", d.get("concept_label") or "")
            w.write({
                "item_id": "C3|%s" % sid,
                "artifact": "C3",
                "mapping_relation": (d.get("mapping_relation") or "UNKNOWN").strip() or "UNKNOWN",
                "term": d.get("term", ""),
                "cdm_type": d.get("cdm_type", ""),
                "ontology_name": d.get("ontology_name") or "",
                "concept_id": d.get("concept_id") or "",
                "concept_label": d.get("concept_label") or "",
                "definition_context": dc,
                "claim_text": ct,
                "evidence_text": dc,
                "context_before": "",
                "context_after": "",
            })
    # A missing definition is NOT a join failure: it is a legitimate
    # NO_MATCH/undefined term that the prompt must resolve as UNCERTAIN.
    return {"rows": total, "with_definition": with_def,
            "with_fallback_sentence": with_fallback,
            "without_context": total - with_def - with_fallback,
            "join_fail_rate": 0.0}


# ── C4: canonical triples ────────────────────────────────────────────────────
def build_c4(w, max_fail):
    ment = {}
    with open(MENTIONS) as fh:
        for line in fh:
            d = json.loads(line)
            ment[d["triple_mention_id"]] = d
    _, byrec = load_sections()
    total = with_mention = 0
    with open(TRIPLES) as fh:
        for line in fh:
            d = json.loads(line)
            total += 1
            m = next((ment[mid] for mid in d.get("triple_mention_ids", []) if mid in ment), None)
            if m is not None:
                with_mention += 1
            ev = (m or {}).get("source_sentence", "")
            sec = byrec.get((m or {}).get("section_id"), "")
            ctxt = ""
            if ev and sec:
                n = norm(sec)
                i = n.find(norm(ev))
                if i >= 0:
                    ctxt = n[max(0, i - 150):i + len(norm(ev)) + 150]
            ct = "%s --%s--> %s" % (
                d.get("subject_display_label") or d.get("subject_normalized_label", ""),
                (d.get("relation_normalized") or "UNKNOWN").strip() or "UNKNOWN",
                d.get("object_display_label") or d.get("object_normalized_label", ""))
            w.write({
                "item_id": "C4|%s" % d["canonical_triple_id"],
                "artifact": "C4",
                "relation": (d.get("relation_normalized") or "UNKNOWN").strip() or "UNKNOWN",
                "subject_surface": d.get("subject_display_label") or d.get("subject_normalized_label", ""),
                "subject_type": d.get("subject_entity_type", ""),
                "object_surface": d.get("object_display_label") or d.get("object_normalized_label", ""),
                "object_type": d.get("object_entity_type", ""),
                "evidence_text": ev,
                "context_sentence": ctxt,
                "claim_text": ct,
                "context_before": ctxt[:150],
                "context_after": ctxt[-150:] if ctxt else "",
            })
    fail = (total - with_mention) / total if total else 0
    return {"rows": total, "with_mention": with_mention,
            "mention_missing": total - with_mention, "join_fail_rate": round(fail, 6)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default=OUTD)
    ap.add_argument("--max-join-fail", type=float, default=0.005)
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)

    builders = [("C1", build_c1), ("C2", build_c2), ("C3", build_c3), ("C4", build_c4)]
    stats, grand = {}, 0
    for name, fn in builders:
        path = os.path.join(args.outdir, "input_full_%s.jsonl" % name)
        w = Writer(path)
        info = fn(w, args.max_join_fail)
        size = w.close()
        info["bytes"] = size
        info["mb"] = round(size / 1e6, 2)
        stats[name] = info
        grand += info["rows"]
        print("%s: %7d rows  %8.2f MB  join_fail=%.4f%%  %s"
              % (name, info["rows"], info["mb"], 100 * info["join_fail_rate"],
                 {k: v for k, v in info.items() if k not in ("rows", "bytes", "mb")}),
              flush=True)
        if info["join_fail_rate"] > args.max_join_fail:
            print("FATAL: %s join failure %.4f%% exceeds %.2f%% threshold — join logic is broken"
                  % (name, 100 * info["join_fail_rate"], 100 * args.max_join_fail),
                  file=sys.stderr)
            return 2

    stats["TOTAL"] = grand
    with open(os.path.join(args.outdir, "_input_full_stats.json"), "w") as fh:
        json.dump(stats, fh, indent=1)
    print("TOTAL %d items -> _input_full_stats.json" % grand)
    return 0


if __name__ == "__main__":
    sys.exit(main())
