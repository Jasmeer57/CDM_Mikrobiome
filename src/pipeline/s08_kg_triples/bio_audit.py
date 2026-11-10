"""Biological plausibility audit for the Microbiome-CDM knowledge graph.

Adapted and extended from EFRE's kg_bio_audit.py (8 IBD/diet-specific flags)
to 14 microbiome-specific flags covering the 14 CDM entity types.

Flags are written to the relationships.validation_status column and a
separate audit report JSON. Each flag has a suggested fix:
  - demote: predicate → associated_with (keep in KG)
  - flag: mark for human review (keep as-is)
  - drop: delete from KG
  - swap_subject_object: swap direction

Usage (standalone):
  python -m cdm_pipeline.quality.bio_audit --db path/to/microbiome_cdm.db

Usage (imported from rebuild_relations.py):
  from cdm_pipeline.quality.bio_audit import audit_relations
  flags = audit_relations(db_path)
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from pipeline.config import CDM_OUTPUT_DIR

DB_PATH = CDM_OUTPUT_DIR / "microbiome_cdm.db"

# ── CDM entity type sets ──
DISEASE_TYPES = frozenset({"DISEASE"})
CLINICAL_TYPES = frozenset({"CLINICAL", "DISEASE"})
ORGANISM_TYPES = frozenset({"ORGANISM"})
CHEMICAL_TYPES = frozenset({"CHEMICAL"})
GENE_TYPES = frozenset({"PROTEIN", "DNA_RNA"})
METHOD_TYPES = frozenset({
    "LAB_METHOD", "DATA_ANALYSIS", "SAMPLE_METHOD",
    "EXPERIMENTAL_METHOD", "STUDY_DESIGN",
})
PATHWAY_TYPES = frozenset({"PATHWAY"})

# Predicates that imply treatment/causation — require disease/condition as object
TREATS_VALID_OBJECTS = frozenset({"DISEASE", "CLINICAL"})

# Predicates that imply production — valid for chemical/gene→substance
PRODUCES_VALID_OBJECTS = frozenset({"CHEMICAL", "PROTEIN", "DNA_RNA"})

# Predicates that imply abundance change — valid for organism→disease/condition
ABUNDANCE_PREDICATES = frozenset({"enriched_in", "depleted_in"})

# Predicates that imply encoding — valid for DNA_RNA→PROTEIN
ENCODES_VALID_PAIRS = frozenset({("DNA_RNA", "PROTEIN"), ("DNA_RNA", "DNA_RNA")})

# ── Known organism-disease associations (gold standard subset) ──
# These are well-established microbiome-disease links that should NOT be flagged
KNOWN_ORGANISM_DISEASE = {
    # IBD
    ("faecalibacterium prausnitzii", "crohn's disease"),
    ("faecalibacterium prausnitzii", "inflammatory bowel disease"),
    ("escherichia coli", "inflammatory bowel disease"),
    ("bacteroides fragilis", "colorectal cancer"),
    ("fusobacterium nucleatum", "colorectal cancer"),
    # Obesity
    ("akkermansia muciniphila", "obesity"),
    # C. diff
    ("clostridioides difficile", "clostridioides difficile infection"),
    ("clostridium difficile", "clostridium difficile infection"),
}

# ── Known gut-associated organisms (for ANIMAL_MIXED flag) ──
GUT_ORGANISMS_RE = re.compile(
    r"\b(bacteroides|firmicutes|bifidobacterium|lactobacillus|faecalibacterium|"
    r"akkermansia|prevotella|roseburia|eubacterium|ruminococcus|"
    r"clostridium|clostridioides|escherichia|enterococcus|streptococcus|"
    r"veillonella|fusobacterium|parabacteroides|alistipes|"
    r"christensenella|methanobrevibacter|succinivibrio)\w*",
    re.I,
)

# ── Animal study indicators ──
ANIMAL_STUDY_RE = re.compile(
    r"\b(animal|mouse|murine|wean|week-old|wk-old|animal model|mouse model|"
    r"gnotobiotic|germ-free|germfree|dnbs|dss-induced|tnbs|"
    r"c57bl|balb|c57bl/6|rat model|piglet|zebrafish)\w*",
    re.I,
)

SPECIES_TOKENS_RE = re.compile(
    r"\b(mouse|mice|rat|murine|pig|piglet|rabbit|dog|puppy|zebrafish|"
    r"c57bl|balb|c57bl/6|dss-induced|dnbs|tnbs|"
    r"human|patient|subject|participant|cohort|clinical)\w*",
    re.I,
)

# ── Disease hierarchy (parent → child relationships) ──
DISEASE_HIERARCHY = {
    "inflammatory bowel disease": {"crohn's disease", "ulcerative colitis", "ibd"},
    "ibd": {"crohn's disease", "ulcerative colitis"},
    "obesity": {"bmi", "body mass index", "weight gain", "adiposity"},
    "metabolic syndrome": {"diabetes", "type 2 diabetes", "insulin resistance", "hyperglycemia"},
    "cancer": {"colorectal cancer", "breast cancer", "lung cancer", "liver cancer"},
}

# ── Typing errors: entities that are commonly mistyped ──
TYPING_ERRORS: dict[str, set[str]] = {
    "gut bacteria": {"ORGANISM"},  # should be ORGANISM, not CELL_TYPE or CHEMICAL
    "gut microbiota": {"ORGANISM"},
    "gut microbiome": {"ORGANISM"},
    "fecal microbiota": {"ORGANISM"},
    "short-chain fatty acids": {"CHEMICAL"},  # not PROTEIN or METABOLITE
    "scfa": {"CHEMICAL"},
    "butyrate": {"CHEMICAL"},
    "acetate": {"CHEMICAL"},
    "propionate": {"CHEMICAL"},
}


def _is_gut_organism(text: str) -> bool:
    """Check if text mentions a known gut-associated organism."""
    return bool(GUT_ORGANISMS_RE.search(text))


def _is_animal_study(evidence: str, source_type: str) -> bool:
    """Check if evidence indicates an animal study."""
    combined = f"{evidence} {source_type}".lower()
    return bool(ANIMAL_STUDY_RE.search(combined))


def _has_species_token(evidence: str, subject: str, object: str) -> bool:
    """Check if the combined text mentions a species/human token."""
    combined = f"{evidence} {subject} {object}"
    return bool(SPECIES_TOKENS_RE.search(combined))


# ── 14 Bio-Audit Flags ──

def flag_treats_non_disease(rel: dict) -> tuple[bool, str, str]:
    """Flag: treats/treated_by with non-disease object.

    EFRE flag #3, adapted for CDM.
    """
    pred = rel.get("relationship_type", "").lower()
    obj_type = rel.get("object_type", "")
    if pred in ("treats", "treated_by") and obj_type and obj_type not in TREATS_VALID_OBJECTS:
        return True, "demote", f"treats/treated_by requires DISEASE/CLINICAL object, got {obj_type}"
    return False, "", ""


def flag_organism_treats_disease(rel: dict) -> tuple[bool, str, str]:
    """Flag: ORGANISM treats DISEASE — organisms don't 'treat' diseases.

    MCDM-specific: should be enriched_in/depleted_in/associated_with.
    """
    pred = rel.get("relationship_type", "").lower()
    subj_type = rel.get("subject_type", "")
    obj_type = rel.get("object_type", "")
    if pred == "treats" and subj_type == "ORGANISM" and obj_type in DISEASE_TYPES:
        # Check if this is a known probiotic treatment
        subj_lower = rel.get("subject", "").lower()
        obj_lower = rel.get("object", "").lower()
        if (subj_lower, obj_lower) in KNOWN_ORGANISM_DISEASE:
            return False, "", ""
        return True, "demote", "ORGANISM treats DISEASE: should be enriched_in/depleted_in/associated_with"
    return False, "", ""


def flag_chemical_treats_organism(rel: dict) -> tuple[bool, str, str]:
    """Flag: CHEMICAL treats ORGANISM — chemicals don't 'treat' organisms.

    MCDM-specific (no EFRE equivalent).
    """
    pred = rel.get("relationship_type", "").lower()
    subj_type = rel.get("subject_type", "")
    obj_type = rel.get("object_type", "")
    if pred == "treats" and subj_type == "CHEMICAL" and obj_type == "ORGANISM":
        return True, "demote", "CHEMICAL treats ORGANISM: should be disrupts/associated_with"
    return False, "", ""


def flag_gene_produces_disease(rel: dict) -> tuple[bool, str, str]:
    """Flag: GENE/PROTEIN produces DISEASE — genes don't 'produce' diseases.

    MCDM-specific.
    """
    pred = rel.get("relationship_type", "").lower()
    subj_type = rel.get("subject_type", "")
    obj_type = rel.get("object_type", "")
    if pred == "produces" and subj_type in GENE_TYPES and obj_type in DISEASE_TYPES:
        return True, "demote", "GENE/PROTEIN produces DISEASE: should be implicated_in/associated_with"
    return False, "", ""


def flag_method_treats_disease(rel: dict) -> tuple[bool, str, str]:
    """Flag: METHOD treats DISEASE — methods don't treat diseases.

    MCDM-specific.
    """
    pred = rel.get("relationship_type", "").lower()
    subj_type = rel.get("subject_type", "")
    obj_type = rel.get("object_type", "")
    if pred == "treats" and subj_type in METHOD_TYPES and obj_type in DISEASE_TYPES:
        return True, "demote", "METHOD treats DISEASE: should be associated_with/participates_in"
    return False, "", ""


def flag_abundance_wrong_object(rel: dict) -> tuple[bool, str, str]:
    """Flag: enriched_in/depleted_in with non-organism subject or non-disease object.

    MCDM-specific: these predicates are microbiome-specific.
    """
    pred = rel.get("relationship_type", "").lower()
    subj_type = rel.get("subject_type", "")
    obj_type = rel.get("object_type", "")
    if pred in ABUNDANCE_PREDICATES:
        if subj_type and subj_type != "ORGANISM" and subj_type not in GENE_TYPES:
            return True, "demote", f"{pred} requires ORGANISM/GENE subject, got {subj_type}"
        if obj_type and obj_type not in DISEASE_TYPES and obj_type not in CLINICAL_TYPES and obj_type != "ORGANISM":
            return True, "demote", f"{pred} requires DISEASE/CLINICAL/ORGANISM object, got {obj_type}"
    return False, "", ""


def flag_encodes_wrong_pair(rel: dict) -> tuple[bool, str, str]:
    """Flag: encodes with non-DNA→PROTEIN pair.

    MCDM-specific.
    """
    pred = rel.get("relationship_type", "").lower()
    subj_type = rel.get("subject_type", "")
    obj_type = rel.get("object_type", "")
    if pred == "encodes":
        pair = (subj_type, obj_type)
        if pair not in ENCODES_VALID_PAIRS and subj_type != "DNA_RNA":
            return True, "demote", f"encodes requires DNA_RNA subject, got {subj_type}"
    return False, "", ""


def flag_disease_hierarchy(rel: dict) -> tuple[bool, str, str]:
    """Flag: disease-disease hierarchy violations.

    Adapted from EFRE flag #4.
    """
    pred = rel.get("relationship_type", "").lower()
    subj = rel.get("subject", "").lower()
    obj = rel.get("object", "").lower()
    subj_type = rel.get("subject_type", "")
    obj_type = rel.get("object_type", "")

    if pred in ("associated_with", "co_occurs_with", "implicated_in"):
        if subj_type in DISEASE_TYPES and obj_type in DISEASE_TYPES:
            for parent, children in DISEASE_HIERARCHY.items():
                if parent in subj and any(c in obj for c in children):
                    return True, "flag", f"Disease hierarchy: {parent} → {obj} (parent-child disease pair)"
                if parent in obj and any(c in subj for c in children):
                    return True, "flag", f"Disease hierarchy: {parent} → {subj} (parent-child disease pair)"
    return False, "", ""


def flag_animal_mixed(rel: dict) -> tuple[bool, str, str]:
    """Flag: animal study without species mention.

    Adapted from EFRE flag #5. In microbiome research, many studies are
    animal models but don't explicitly mention the species in the relationship.
    """
    evidence = rel.get("evidence", "") or ""
    source_type = rel.get("source_type", "") or ""
    subject = rel.get("subject", "") or ""
    obj = rel.get("object", "") or ""

    if _is_animal_study(evidence, source_type):
        combined = f"{evidence} {subject} {obj}"
        if not _has_species_token(evidence, subject, obj):
            # Also check if subject/object are known gut organisms
            if not _is_gut_organism(subject) and not _is_gut_organism(obj):
                return True, "flag", "Animal study without species/human token in evidence"
    return False, "", ""


def flag_overqualified_object(rel: dict) -> tuple[bool, str, str]:
    """Flag: object text is too long (> 100 chars).

    Adapted from EFRE flag #6.
    """
    obj = rel.get("object", "") or ""
    if len(obj) > 100:
        return True, "flag", f"Overqualified object (len={len(obj)})"
    return False, "", ""


def flag_comparator_leak(rel: dict) -> tuple[bool, str, str]:
    """Flag: 'compared with/to' leaked into object text.

    Adapted from EFRE flag #7.
    """
    obj = rel.get("object", "") or ""
    if "compared with" in obj.lower() or "compared to" in obj.lower():
        return True, "flag", "Comparator phrase leaked into object"
    return False, "", ""


def flag_typing_error(rel: dict) -> tuple[bool, str, str]:
    """Flag: entity commonly mistyped.

    Adapted from EFRE flag #8.
    """
    subj = rel.get("subject", "").lower()
    obj = rel.get("object", "").lower()
    subj_type = rel.get("subject_type", "")
    obj_type = rel.get("object_type", "")

    for entity, wrong_types in TYPING_ERRORS.items():
        if entity in subj and subj_type and subj_type not in wrong_types:
            return True, "flag", f"Typing error: '{entity}' should be {wrong_types}, got {subj_type}"
        if entity in obj and obj_type and obj_type not in wrong_types:
            return True, "flag", f"Typing error: '{entity}' should be {wrong_types}, got {obj_type}"
    return False, "", ""


def flag_trivial_organism_pair(rel: dict) -> tuple[bool, str, str]:
    """Flag: ORGANISM co_occurs_with ORGANISM with no context.

    MCDM-specific: many CO_OCCURS_WITH organism-organism pairs are trivial
    (they just co-occur in the same paper). Flag if confidence is low.
    """
    pred = rel.get("relationship_type", "").lower()
    subj_type = rel.get("subject_type", "")
    obj_type = rel.get("object_type", "")
    conf = rel.get("confidence", 1.0)

    if pred == "co_occurs_with" and subj_type == "ORGANISM" and obj_type == "ORGANISM":
        if conf < 0.5:
            return True, "flag", "Trivial organism-organism co-occurrence (low confidence)"
    return False, "", ""


def flag_pathway_self_reference(rel: dict) -> tuple[bool, str, str]:
    """Flag: PATHWAY part_of_pathway PATHWAY where subject == object.

    MCDM-specific.
    """
    pred = rel.get("relationship_type", "").lower()
    subj = rel.get("subject", "").lower()
    obj = rel.get("object", "").lower()
    subj_type = rel.get("subject_type", "")
    obj_type = rel.get("object_type", "")

    if pred == "part_of_pathway" and subj_type == "PATHWAY" and obj_type == "PATHWAY":
        if subj == obj:
            return True, "drop", "Pathway self-reference (subject == object)"
    return False, "", ""


# ── All flags registry ──
ALL_FLAGS = [
    ("treats_non_disease", flag_treats_non_disease),
    ("organism_treats_disease", flag_organism_treats_disease),
    ("chemical_treats_organism", flag_chemical_treats_organism),
    ("gene_produces_disease", flag_gene_produces_disease),
    ("method_treats_disease", flag_method_treats_disease),
    ("abundance_wrong_object", flag_abundance_wrong_object),
    ("encodes_wrong_pair", flag_encodes_wrong_pair),
    ("disease_hierarchy", flag_disease_hierarchy),
    ("animal_mixed", flag_animal_mixed),
    ("overqualified_object", flag_overqualified_object),
    ("comparator_leak", flag_comparator_leak),
    ("typing_error", flag_typing_error),
    ("trivial_organism_pair", flag_trivial_organism_pair),
    ("pathway_self_reference", flag_pathway_self_reference),
]


def audit_relations(
    db_path: Path | str = DB_PATH,
    where_clause: str = "",
    apply: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run all bio-audit flags on relationships in the DB.

    Args:
        db_path: Path to microbiome_cdm.db
        where_clause: Optional SQL WHERE clause to filter relations
        apply: If True, write flags to DB (demote/flag/drop)
        dry_run: If True with apply, don't actually modify DB

    Returns:
        Dict with flag counts, per-flag samples, and total audited.
    """
    db_path = Path(db_path)
    conn = sqlite3.connect(str(db_path))

    query = """
        SELECT r.id, r.source_id, r.target_id, r.relationship_type,
               r.confidence, r.evidence, r.source_type, r.validation_status,
               r.original_predicate, r.demotion_reason,
               s.term as subject, s.entity_type as subject_type,
               t.term as object, t.entity_type as object_type
        FROM relationships r
        JOIN entities s ON r.source_id = s.id
        JOIN entities t ON r.target_id = t.id
    """
    if where_clause:
        query += f" WHERE {where_clause}"

    rows = conn.execute(query).fetchall()
    relations = [dict(zip([d[0] for d in conn.execute(query).description], row)) for row in rows]
    conn.close()

    print(f"Loaded {len(relations)} relations for bio-audit")

    flag_counts = Counter()
    flag_samples: dict[str, list[dict]] = defaultdict(list)
    action_counts = Counter()
    flagged_rels: list[dict] = []

    for rel in relations:
        for flag_name, flag_fn in ALL_FLAGS:
            triggered, action, message = flag_fn(rel)
            if triggered:
                flag_counts[flag_name] += 1
                action_counts[action] += 1
                if len(flag_samples[flag_name]) < 5:
                    flag_samples[flag_name].append({
                        "rel_id": rel["id"],
                        "subject": rel["subject"][:80],
                        "predicate": rel["relationship_type"],
                        "object": rel["object"][:80],
                        "subject_type": rel["subject_type"],
                        "object_type": rel["object_type"],
                        "action": action,
                        "message": message,
                    })
                flagged_rels.append({
                    "rel_id": rel["id"],
                    "flag": flag_name,
                    "action": action,
                    "message": message,
                    "subject": rel["subject"],
                    "predicate": rel["relationship_type"],
                    "object": rel["object"],
                })

    # Apply to DB
    if apply and not dry_run:
        conn = sqlite3.connect(str(db_path))
        applied_counts = Counter()
        for fr in flagged_rels:
            if fr["action"] == "demote":
                conn.execute(
                    "UPDATE relationships SET relationship_type = 'ASSOCIATED_WITH', "
                    "original_predicate = COALESCE(original_predicate, relationship_type), "
                    "demotion_reason = COALESCE(demotion_reason, ?), "
                    "validation_status = 'bio_audit_demoted' "
                    "WHERE id = ?",
                    (f"bio_audit: {fr['flag']}: {fr['message']}", fr["rel_id"]),
                )
                applied_counts["demote"] += 1
            elif fr["action"] == "drop":
                conn.execute("DELETE FROM relationships WHERE id = ?", (fr["rel_id"],))
                applied_counts["drop"] += 1
            elif fr["action"] == "flag":
                conn.execute(
                    "UPDATE relationships SET validation_status = 'bio_audit_flagged' "
                    "WHERE id = ? AND validation_status IS NULL",
                    (fr["rel_id"],),
                )
                applied_counts["flag"] += 1
        conn.commit()
        conn.close()
        print(f"\nApplied to DB: {dict(applied_counts)}")

    return {
        "n_audited": len(relations),
        "n_flagged": sum(flag_counts.values()),
        "n_unique_flagged": len({fr["rel_id"] for fr in flagged_rels}),
        "flag_counts": dict(flag_counts),
        "action_counts": dict(action_counts),
        "samples": {k: v for k, v in flag_samples.items()},
        "flagged_relations": flagged_rels if len(flagged_rels) < 10000 else flagged_rels[:10000],
    }


def main():
    ap = argparse.ArgumentParser(description="Biological plausibility audit for MCDM KG")
    ap.add_argument("--db", required=True, help="Path to microbiome_cdm.db")
    ap.add_argument("--where", default="", help="SQL WHERE clause to filter relations")
    ap.add_argument("--output", help="Output JSON path for audit report")
    ap.add_argument("--apply", action="store_true", help="Apply flags to DB (demote/flag/drop)")
    ap.add_argument("--dry-run", action="store_true", help="Don't modify DB")
    args = ap.parse_args()

    result = audit_relations(
        db_path=args.db,
        where_clause=args.where,
        apply=args.apply,
        dry_run=args.dry_run,
    )

    print(f"\n{'='*60}")
    print(f"BIO-AUDIT RESULTS ({result['n_audited']} relations audited)")
    print(f"{'='*60}")
    print(f"Flagged: {result['n_flagged']} flags on {result['n_unique_flagged']} unique relations")
    print(f"\nFlag counts:")
    for flag, count in sorted(result["flag_counts"].items(), key=lambda x: -x[1]):
        pct = count / result["n_audited"] * 100
        print(f"  {flag:30s}: {count:6d} ({pct:.1f}%)")
    print(f"\nAction counts:")
    for action, count in sorted(result["action_counts"].items(), key=lambda x: -x[1]):
        print(f"  {action:30s}: {count:6d}")

    print(f"\nSamples:")
    for flag, samples in sorted(result["samples"].items()):
        print(f"\n  ── {flag} ──")
        for s in samples[:3]:
            print(f"    [{s['action']}] {s['subject']} --{s['predicate']}--> {s['object']}")
            print(f"       ({s['subject_type']} → {s['object_type']}) {s['message']}")

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"\nReport written to {out_path}")


if __name__ == "__main__":
    main()
