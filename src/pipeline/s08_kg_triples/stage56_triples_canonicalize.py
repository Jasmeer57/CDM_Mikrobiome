#!/usr/bin/env python3
"""Stage 56: canonicalize triple MENTIONS (from stage 53) into canonical
TRIPLES + an entity registry + cross-paper evidence (template §K).

CPU-only, no LLM, fully deterministic. Grouping is string-normalization v1:
two mentions belong to the same canonical triple iff their alphanumeric-
collapsed (lowercase, all non-alphanumerics stripped) subject strings are
identical, their relation_normalized is identical, AND their object strings
are identical. No abbreviation expansion, no ontology distance, no fuzzy
matching - anything weaker stays a separate canonical triple (record, never
guess). External linking (OMOP / NCBI taxid / BioPortal) is stage 57 and is
NOT done here; every external id field stays unresolved here.

Backfills into data/triple_mentions.jsonl (downgrade-only, in place):
  canonical_triple_id      pending_stage56  -> HMCV2-CT-<n>
  duplicate_group_id       pending_stage56  -> HMCV2-DUP-<n>
  duplicate_validation_status pending_stage56 -> unique_mention /
                           within_paper_duplicate / cross_paper_duplicate
  subject_entity_id / object_entity_id: unresolved -> HMCV2-ENT-<n>
                           (registry id; resolution status stays
                            unresolved_string_match_v1 until stage 57)

Conflict policy: a canonical group whose member mentions disagree on polarity,
assertion_status or effect_direction is KEPT and flagged
(conflicting_* in canonical record unresolved_issues + human_review stays
pending) - never resolved, never dropped.

Outputs
  data/triple_mentions.jsonl          updated in place (atomic rewrite)
  data/canonical_triples.jsonl        one record per canonical triple
  data/entities.jsonl                 entity registry (subject+object sides)
  data/cross_paper_evidence.jsonl     canonical triples backed by >=2 papers
  validation/triples_canonicalization_report.json

Fail-closed
  - data/triple_mentions.jsonl missing/empty -> exit 1 (run stage 53 --merge)
  - any empty normalized subject/object mention -> exit 1 (corrupt input)
  - mentions_total != sum of group memberships -> exit 1
  - any record left with pending_stage56 after backfill -> exit 1
  - idempotent: rerun recomputes everything from the (possibly backfilled)
    mentions; backfill overwrites only the 56-owned fields.

ID convention: HMCV2-CT-<n:05d> / HMCV2-ENT-<n:05d> / HMCV2-DUP-<n:04d> are
assigned in sorted key order within THIS build (graph_version 2.1.0); ids are
build-scoped and may change if the mention set changes - the assignment
convention is recorded in the report.
"""
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pipeline.common as C

STAGE = "stage56_triples_canonicalize"
PV = "2.1.0"
NR = "not_reported"
UNRES = "unresolved"

MENTIONS_PATH = C.CORPUS_DIR / "data" / "triple_mentions.jsonl"


def canon_norm(s: str) -> str:
    """Alphanumeric-collapsed lowercase form (v1 normalization)."""
    if s is None:
        return ""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def group_key(m: dict) -> tuple:
    return (canon_norm(m["subject_mention"]),
            m["relation_normalized"],
            canon_norm(m["object_mention"]))


def main():
    C.require_slurm(STAGE)

    cfg = C.load_config()

    # ---- load mentions (fail-closed on missing/empty) --------------------
    mentions = C.read_jsonl(MENTIONS_PATH)
    if not mentions:
        sys.exit(f"ERROR: {MENTIONS_PATH} missing or empty; "
                 "run stage 53 (shards + --merge) first")

    # ---- normalize + validate --------------------------------------------
    for i, m in enumerate(mentions):
        key = group_key(m)
        if not key[0] or not key[2]:
            sys.exit(f"ERROR: mention {m.get('triple_mention_id')} (#{i}) has "
                     "empty normalized subject or object; corrupt input")
        if m.get("record_status") != "active":
            sys.exit(f"ERROR: mention {m.get('triple_mention_id')} has "
                     f"record_status={m.get('record_status')!r}; cannot "
                     "canonicalize a non-active record")

    mentions.sort(key=m_sort)
    ids_expected = [m["triple_mention_id"] for m in mentions]
    if len(set(ids_expected)) != len(ids_expected):
        sys.exit("ERROR: duplicate triple_mention_id in input")

    # ---- group mentions into canonical triples ---------------------------
    groups = defaultdict(list)
    for m in mentions:
        groups[group_key(m)].append(m["triple_mention_id"])

    by_id = {m["triple_mention_id"]: m for m in mentions}
    if sum(len(v) for v in groups.values()) != len(mentions):
        sys.exit("ERROR: group membership sum != mentions_total")

    sorted_keys = sorted(groups)     # deterministic id assignment order
    ct_id = {k: f"HMCV2-CT-{n:05d}" for n, k in enumerate(sorted_keys, 1)}
    dup_id = {k: f"HMCV2-DUP-{n:04d}" for n, k in enumerate(sorted_keys, 1)}

    # ---- entity registry (subject + object sides) ------------------------
    ent_members = defaultdict(list)   # normalized label -> list of (id, side)
    for m in mentions:
        for side, lab_key in (("subject", "subject_normalized_label"),
                               ("object", "object_normalized_label")):
            lab = canon_norm(m[f"{side}_mention"])
            ent_members[lab].append((m["triple_mention_id"], side))
    sorted_ent = sorted(ent_members)
    ent_id = {lab: f"HMCV2-ENT-{n:05d}" for n, lab in enumerate(sorted_ent, 1)}

    # ---- build canonical records ------------------------------------------
    canonical_recs = []
    cross_paper_recs = []
    stats = Counter()
    polarity_conflicts = assertion_conflicts = direction_conflicts = 0

    for k in sorted_keys:
        member_ids = groups[k]
        members = [by_id[i] for i in member_ids]
        pols = {m["polarity"] for m in members}
        asrt = {m["assertion_status"] for m in members}
        dirs = {m["effect_direction"] for m in members}
        papers = sorted({m["paper_id"] for m in members})
        issues = []

        if len(pols) > 1:
            polarity_conflicts += 1
            issues.append("conflicting_polarity_across_mentions")
        if len(asrt) > 1:
            assertion_conflicts += 1
            issues.append("conflicting_assertion_status_across_mentions")
        if len(dirs) > 1:
            direction_conflicts += 1
            issues.append("conflicting_effect_direction_across_mentions")

        if len(member_ids) == 1:
            stats["groups_size_1"] += 1
            dup_status = "unique_mention"
        elif len(papers) == 1:
            stats["groups_within_paper"] += 1
            dup_status = "within_paper_duplicate"
        else:
            stats["groups_cross_paper"] += 1
            dup_status = "cross_paper_duplicate"

        rec = {
            "canonical_triple_id": ct_id[k],
            "duplicate_group_id": dup_id[k],
            "graph_id": cfg["corpus"]["corpus_id"],
            "graph_version": PV,
            "canonicalization_stage": f"{STAGE}@{PV}",
            "canonicalization_method": "string_normalization_v1_exact",
            "subject_normalized_label": k[0],
            "subject_display_label": pick_display(members, "subject"),
            "subject_entity_id": ent_id[k[0]],
            "subject_entity_type": pick_common(members, "subject_entity_type"),
            "subject_domain": pick_common(members, "subject_domain"),
            "relation_normalized": k[1],
            "relation_id": members[0]["relation_id"],
            "relation_family": members[0]["relation_family"],
            "relation_is_causal": members[0]["relation_is_causal"],
            "relation_is_symmetric": members[0]["relation_is_symmetric"],
            "object_normalized_label": k[2],
            "object_display_label": pick_display(members, "object"),
            "object_entity_id": ent_id[k[2]],
            "object_entity_type": pick_common(members, "object_entity_type"),
            "object_domain": pick_common(members, "object_domain"),
            "mention_count": len(member_ids),
            "triple_mention_ids": member_ids,
            "paper_count": len(papers),
            "paper_ids": papers,
            "polarity_variants": sorted(pols),
            "polarity_agreement": ("unanimous" if len(pols) == 1
                                   else "conflicting"),
            "assertion_status_variants": sorted(asrt),
            "assertion_agreement": ("unanimous" if len(asrt) == 1
                                    else "conflicting"),
            "effect_direction_variants": sorted(dirs),
            "effect_direction_agreement": ("unanimous" if len(dirs) == 1
                                           else "conflicting"),
            "evidence_locator_statuses": sorted(
                {m["evidence_locator_status"] for m in members}),
            "evidence_verified_count": sum(
                1 for m in members
                if m["evidence_locator_status"].startswith("verified")),
            "evidence_unresolved_count": sum(
                1 for m in members
                if m["evidence_locator_status"] != "verified_exact"
                and m["evidence_locator_status"] != "verified_normalized"),
            "subject_entity_resolution_status": "unresolved_string_match_v1",
            "object_entity_resolution_status": "unresolved_string_match_v1",
            "subject_ontology_id": UNRES,
            "object_ontology_id": UNRES,
            "external_linking_status": "pending_stage57",
            "duplicate_validation_status": dup_status,
            "conflict_flag": ("conflicting_across_mentions" if issues
                              else "no_conflict_recorded"),
            "triple_quality_status": "flagged_needs_review" if (
                issues or any(m.get("triple_quality_status")
                              == "flagged_needs_review" for m in members)
            ) else "automated_checks_passed",
            "human_review_status": "pending",
            "verification_status": "pending",
            "unresolved_issues": issues or None,
            "record_status": "active",
        }
        canonical_recs.append(rec)

        if len(papers) >= 2:
            cross_paper_recs.append({
                "canonical_triple_id": ct_id[k],
                "duplicate_group_id": dup_id[k],
                "graph_id": cfg["corpus"]["corpus_id"],
                "graph_version": PV,
                "subject_normalized_label": k[0],
                "relation_normalized": k[1],
                "object_normalized_label": k[2],
                "corroboration_paper_count": len(papers),
                "paper_ids": papers,
                "mention_count": len(member_ids),
                "triple_mention_ids": member_ids,
                "polarity_agreement": rec["polarity_agreement"],
                "effect_direction_agreement": rec["effect_direction_agreement"],
                "conflict_flag": rec["conflict_flag"],
                "evidence_verified_count": rec["evidence_verified_count"],
                "cross_paper_evidence_status": (
                    "corroborated_no_conflict" if not issues
                    else "corroborated_with_conflicts"),
                "record_status": "active",
            })

    # ---- entity registry records -----------------------------------------
    entity_recs = []
    for lab in sorted_ent:
        members = ent_members[lab]
        side_counts = Counter(side for _, side in members)
        mention_objs = [by_id[i] for i, _ in members]
        dom_counts = Counter()
        type_counts = Counter()
        surface_counts = Counter()
        papers = set()
        for i, side in members:
            m = by_id[i]
            dom_counts[m[f"{side}_domain"]] += 1
            type_counts[m[f"{side}_entity_type"]] += 1
            surface_counts[m[f"{side}_mention"]] += 1
            papers.add(m["paper_id"])
        domain_conflict = len(dom_counts) > 1
        type_conflict = len(type_counts) > 1
        ent_rec = {
            "entity_id": ent_id[lab],
            "graph_id": cfg["corpus"]["corpus_id"],
            "graph_version": PV,
            "normalized_label": lab,
            "display_label": surface_counts.most_common(1)[0][0],
            "entity_types_observed": sorted(type_counts),
            "entity_type_conflict": ("type_conflict_flagged" if type_conflict
                                     else "no_conflict_recorded"),
            "domains_observed": sorted(dom_counts),
            "domain_conflict": ("domain_conflict_flagged" if domain_conflict
                                else "no_conflict_recorded"),
            "observed_as_subject_mentions": side_counts.get("subject", 0),
            "observed_as_object_mentions": side_counts.get("object", 0),
            "mention_count_total": len(members),
            "paper_count": len(papers),
            "triple_mention_ids": sorted(i for i, _ in members),
            "canonical_triple_ids_as_subject": sorted({
                ct_id[group_key(by_id[i])] for i, side in members
                if side == "subject"}),
            "canonical_triple_ids_as_object": sorted({
                ct_id[group_key(by_id[i])] for i, side in members
                if side == "object"}),
            "surface_forms": [{"form": f, "count": c} for f, c in
                              sorted(surface_counts.items())],
            "entity_resolution_status": "unresolved_string_match_v1",
            "resolution_method": "string_normalization_v1",
            "ncbi_tax_id": "pending_stage57",
            "omop_concept_id": "pending_stage57",
            "umls_cui": "unresolved",
            "bioportal_id": "unresolved",
            "external_linking_status": "pending_stage57",
            "record_status": "active",
        }
        entity_recs.append(ent_rec)

    # ---- backfill mentions (downgrade-only) --------------------------------
    for m in mentions:
        k = group_key(m)
        m["canonical_triple_id"] = ct_id[k]
        m["duplicate_group_id"] = dup_id[k]
        if len(groups[k]) == 1:
            m["duplicate_validation_status"] = "unique_mention"
        else:
            papers_in_group = {by_id[i]["paper_id"] for i in groups[k]}
            m["duplicate_validation_status"] = (
                "within_paper_duplicate"
                if len(papers_in_group) == 1 else "cross_paper_duplicate")
        m["subject_entity_id"] = ent_id[k[0]]
        m["object_entity_id"] = ent_id[k[2]]
        # entity ids are string-normalization-level ids, NOT linked ids;
        # keep the resolution status explicit
        m["subject_entity_resolution_status"] = "unresolved_string_match_v1"
        m["object_entity_resolution_status"] = "unresolved_string_match_v1"

    C.write_jsonl(MENTIONS_PATH, mentions)

    # ---- fail-closed recheck: nothing may still be pending ---------------
    for m in C.read_jsonl(MENTIONS_PATH):
        for f in ("canonical_triple_id", "duplicate_group_id",
                  "duplicate_validation_status"):
            if m.get(f) in (None, "", "pending_stage56"):
                sys.exit(f"ERROR: {m.get('triple_mention_id')} field {f} "
                         "still pending after backfill")
        if m.get("subject_entity_id") in (None, "", UNRES) and \
                canon_norm(m["subject_mention"]):
            sys.exit(f"ERROR: {m.get('triple_mention_id')} subject_entity_id "
                     "still unresolved after registry assignment")

    C.write_jsonl(C.CORPUS_DIR / "data" / "canonical_triples.jsonl",
                  canonical_recs)
    C.write_jsonl(C.CORPUS_DIR / "data" / "entities.jsonl", entity_recs)
    C.write_jsonl(C.CORPUS_DIR / "data" / "cross_paper_evidence.jsonl",
                  cross_paper_recs)

    # ---- phase 2: entity linking -------------------------------------------
    # Deterministic canonicalization above is complete; linking (OMOP T0/T1,
    # embedding T2, Entrez/UMLS/BioPortal T3) is budget-capped enrichment,
    # downgrade-only. Skip entirely (tests / no-network) with
    # HMCV2_SKIP_LINKING=1; force offline-only with HMCV2_LINK_OFFLINE=1.
    link_report = None
    if os.environ.get("HMCV2_SKIP_LINKING") != "1":
        import pipeline.s03_corpus_v2.entity_linker
        el_cfg = cfg.get("entity_linking") or {}
        budget = float(el_cfg.get("budget_seconds",
                                  os.environ.get("HMCV2_LINK_BUDGET_SECONDS",
                                                 16200)))
        offline = bool(el_cfg.get("offline", False)) or \
            os.environ.get("HMCV2_LINK_OFFLINE") == "1"
        entity_recs, link_report, cand_recs = entity_linker.run_linking(
            entity_recs, budget_seconds=budget, offline=offline)
        C.write_jsonl(C.CORPUS_DIR / "data" / "entities.jsonl", entity_recs)
        C.write_jsonl(C.CORPUS_DIR / "data" / "candidate_entity_mappings.jsonl",
                      cand_recs)
        C.atomic_write_json(
            C.CORPUS_DIR / "validation" / "entity_linking_report.json",
            link_report)
        oc = link_report["outcomes"]
        print(f"[stage56] linking: "
              f"{oc.get('linked_T0_omop_exact', 0)} T0 / "
              f"{oc.get('linked_T2_embed_rerank', 0)} T2 / "
              f"{oc.get('review_required_embed_band', 0)} review / "
              f"{oc.get('linked_T3_entrez', 0)}+"
              f"{oc.get('linked_T3_ols', 0)}+"
              f"{oc.get('linked_T3_umls', 0)}+"
              f"{oc.get('linked_T3_bioportal', 0)} T3 "
              f"({link_report['candidate_mapping_records']} candidates, "
              f"wall {link_report['wall_seconds']}s)")

    # ---- report ------------------------------------------------------------
    by_paperct = Counter(r["paper_count"] for r in canonical_recs)
    report = {
        "stage": STAGE,
        "graph_version": PV,
        "pipeline_stage": f"{STAGE}@{PV}",
        "mentions_total": len(mentions),
        "canonical_triples_total": len(canonical_recs),
        "entities_total": len(entity_recs),
        "cross_paper_evidence_records": len(cross_paper_recs),
        "groups": dict(stats),
        "canonical_group_size_histogram": {
            "1_paper_mentions": by_paperct.get(1, 0),
            "2_papers": by_paperct.get(2, 0),
            "3_to_5_papers": sum(v for k, v in by_paperct.items()
                                 if 3 <= k <= 5),
            "6_plus_papers": sum(v for k, v in by_paperct.items() if k >= 6),
        },
        "conflicts": {
            "polarity_conflicts": polarity_conflicts,
            "assertion_status_conflicts": assertion_conflicts,
            "effect_direction_conflicts": direction_conflicts,
            "canonical_triples_with_any_conflict": sum(
                1 for r in canonical_recs
                if r["conflict_flag"] == "conflicting_across_mentions"),
        },
        "evidence_in_canonical_triples": {
            "all_mentions_verified": sum(
                1 for r in canonical_recs
                if r["evidence_unresolved_count"] == 0),
            "at_least_one_unresolved": sum(
                1 for r in canonical_recs
                if r["evidence_unresolved_count"] > 0),
        },
        "id_assignment_convention": {
            "canonical_triple_id": "HMCV2-CT-<n:05d>, n ascending in sorted "
                                  "(subject_norm, relation, object_norm) "
                                  "key order; build-scoped",
            "entity_id": "HMCV2-ENT-<n:05d>, n ascending in sorted "
                         "normalized-label order; build-scoped",
            "duplicate_group_id": "HMCV2-DUP-<n:04d>, same order as canonical",
        },
        "idempotency": "rerun-safe; re-derives all outputs and overwrites "
                       "the five 56-owned mention fields",
        "external_linking": "deferred to stage 57 (omop/taxid/bioportal); "
                            "all external ids pending_stage57 or unresolved",
        "backfilled_mention_fields": ["canonical_triple_id",
                                      "duplicate_group_id",
                                      "duplicate_validation_status",
                                      "subject_entity_id",
                                      "object_entity_id",
                                      "subject_entity_resolution_status",
                                      "object_entity_resolution_status"],
        "top_predicates": Counter(m["relation_normalized"]
                                  for m in mentions).most_common(15),
        "top_entities_by_mention_count": sorted(
            ((e["normalized_label"], e["mention_count_total"])
             for e in entity_recs),
            key=lambda t: -t[1])[:15],
        "entity_linking": link_report or "skipped (HMCV2_SKIP_LINKING=1)",
    }

    C.atomic_write_json(
        C.CORPUS_DIR / "validation" / "triples_canonicalization_report.json",
        report)

    ev = C.Events(cfg["corpus"]["corpus_id"], STAGE, PV)
    ev.record(pipeline_stage=STAGE,
              run_status="success",
              note=f"mentions={len(mentions)} "
                   f"canonical={len(canonical_recs)} "
                   f"entities={len(entity_recs)} "
                   f"crosspaper={len(cross_paper_recs)}")
    ev.close()
    cur = C.CurationLog()
    cur.add(cfg["corpus"]["corpus_id"], STAGE,
            "stage56_triples_canonicalize.py", PV,
            "canonicalize_triple_mentions",
            f"{len(canonical_recs)} canonical triples from {len(mentions)} "
            f"mentions; {polarity_conflicts} polarity conflicts kept",
            problem=("conflicting mentions flagged, not resolved"
                     if polarity_conflicts or assertion_conflicts
                     or direction_conflicts else ""),
            resolution="recorded in unresolved_issues; human_review=pending")
    print(json.dumps({k: report[k] for k in
                      ("mentions_total", "canonical_triples_total",
                       "entities_total", "cross_paper_evidence_records",
                       "conflicts")}, indent=2))
    print("STAGE 56 COMPLETE")


def m_sort(m: dict):
    return (m["paper_id"], m["triple_mention_id"])


def pick_display(members: list, side: str) -> str:
    """Most common original surface form for display."""
    counts = Counter(m[f"{side}_mention"] for m in members)
    return counts.most_common(1)[0][0]


def pick_common(members: list, field: str):
    """Most common value; ties broken alphabetically. Records the variant
    set in the entity/canonical conflict fields separately."""
    counts = Counter(m[field] for m in members)
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


if __name__ == "__main__":
    main()
