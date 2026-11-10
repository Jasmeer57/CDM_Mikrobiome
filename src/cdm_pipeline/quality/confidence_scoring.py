"""Scientific confidence scoring for the Microbiome-CDM knowledge graph.

Adapted from EFRE's scientific_quality() function (8-component formula) and
extended with:
  - Microbiome-relevance boost (replaces EFRE's nutrition boost)
  - Bio-audit penalty (relations flagged by bio_audit.py)
  - External corroboration bonus (relations validated by external_validation.py)
  - Direction recovery from evidence text (ported from EFRE's _evidence_direction)
  - Per-edge confidence_basis string explaining the score

The 8 components (total weight = 1.0):
  1. LLM verdict        (0.30) — supported/demoted/flagged
  2. Subject grounding   (0.15) — has ontology ID (UMLS/OLS/NCBITaxon)
  3. Object grounding    (0.15) — has ontology ID
  4. Evidence quality    (0.15) — strong vs hedge words in evidence
  5. Study type          (0.10) — RCT > cohort > case-control > animal
  6. Section context     (0.10) — results > discussion > introduction
  7. Corroboration       (0.15) — multi-paper boost
  8. Predicate strength  (modulation) — associated_with *= 0.85

Post-score adjustments:
  + Microbiome relevance boost (up to +0.08)
  - Bio-audit penalty (up to -0.15)
  + External corroboration bonus (up to +0.05)
  - Single-paper penalty (already in corroboration component)

Usage (standalone):
  python -m cdm_pipeline.quality.confidence_scoring --db path/to/microbiome_cdm.db

Usage (imported from rebuild_relations.py):
  from cdm_pipeline.quality.confidence_scoring import rescore_relations
  rescore_relations(db_path)
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from ..config import CDM_OUTPUT_DIR
from .predicate_synonyms import HEDGE_WORDS, STRONG_EVIDENCE_WORDS, is_correlational_evidence

DB_PATH = CDM_OUTPUT_DIR / "microbiome_cdm.db"

# ── Section context scores (from EFRE) ──
SECTION_SCORES = {
    "results": 1.0, "findings": 1.0, "conclusions": 0.9, "abstract": 0.8,
    "discussion": 0.6, "introduction": 0.3, "background": 0.2,
    "references": 0.1, "materials and methods": 0.4, "methods": 0.4,
    "statistical analysis": 0.5,
}

# ── Study type scores (from EFRE, adapted) ──
STUDY_TYPE_SCORES = {
    "systematic_review_meta_analysis": 1.0, "randomized_controlled_trial": 0.95,
    "prospective_cohort": 0.85, "cohort": 0.8, "retrospective_cohort": 0.7,
    "case_control": 0.6, "cross_sectional": 0.5, "case_series": 0.4,
    "case_report": 0.3, "in_vivo_animal": 0.55, "in_vitro": 0.45,
    "in_silico": 0.4, "review": 0.35, "guideline": 0.3, "consensus_statement": 0.3,
    "letter": 0.2, "editorial": 0.2, "conference_abstract": 0.3, "unknown": 0.25,
}

# ── Study type detection regexes ──
STUDY_TYPE_PATTERNS: dict[str, re.Pattern] = {
    "systematic_review_meta_analysis": re.compile(
        r"\b(meta.?analysis|systematic review|prisma)\b", re.I),
    "randomized_controlled_trial": re.compile(
        r"\b(randomized|randomised|rct|double.?blind|placebo.?controlled|clinical trial)\b", re.I),
    "prospective_cohort": re.compile(
        r"\b(prospective cohort|prospective study|follow.?up)\b", re.I),
    "retrospective_cohort": re.compile(
        r"\b(retrospective|historical cohort)\b", re.I),
    "case_control": re.compile(
        r"\b(case.?control)\b", re.I),
    "cross_sectional": re.compile(
        r"\b(cross.?sectional)\b", re.I),
    "in_vivo_animal": re.compile(
        r"\b(animal model|mouse model|murine|in vivo|gnotobiotic|germ.?free)\b", re.I),
    "in_vitro": re.compile(
        r"\b(in vitro|cell culture|cell line)\b", re.I),
    "review": re.compile(
        r"\b(this review|we review|review article)\b", re.I),
}

# ── Direction recovery regexes (ported from EFRE + microbiome extensions) ──
DIR_UP_RE = re.compile(
    r"\b(increased|higher|elevated|greater|more|upregulat|positiv|promot|rise|rises|"
    r"enriched|overrepresent|over.?represent|abundant|enrich|accumulat|"
    r"enhanced|up.?regulated|stimulat|induc|augment|amplif)\w*",
    re.I,
)
DIR_DOWN_RE = re.compile(
    r"\b(decreased|reduced|lower|fewer|less|diminished|downregulat|negativ|invers|"
    r"declin|protective|protect|depleted|underrepresent|under.?represent|"
    r"deplet|suppress|inhibit|attenuat|diminish|impair|ablating|deficien|"
    r"absence|lacking|eradicated|eliminated)\w*",
    re.I,
)
DIR_ADJ_BEFORE_RISK_RE = re.compile(
    r"(increased|decreased|reduced|higher|lower|elevated|high|low|greater|less|fewer)"
    r"\s+(risk|incidence|prevalence|likelihood|probability)\s+(of|for)",
    re.I,
)
DIR_ASSOCIATED_RE = re.compile(
    r"(inversely|negatively|positively|directly)\s+associated",
    re.I,
)
# Microbiome-specific abundance / association patterns
DIR_ABUNDANCE_UP_RE = re.compile(
    r"\b(increased|higher|elevated|greater|enriched|enrich|overrepresent)\s+"
    r"(relative\s+)?(abundance|level|presence|prevalence)",
    re.I,
)
DIR_ABUNDANCE_DOWN_RE = re.compile(
    r"\b(decreased|reduced|lower|depleted|deplete|underrepresent|diminished|less)\s+"
    r"(relative\s+)?(abundance|level|presence|prevalence)",
    re.I,
)
DIR_ENRICHED_IN_RE = re.compile(
    r"\b(enriched|depleted|increased|decreased|higher|lower|more|less|greater|fewer)\s+"
    r"(in|with)\b",
    re.I,
)
DIR_IMPLIED_BY_RISK_OBJ = {
    "increased": "positive", "higher": "positive", "elevated": "positive",
    "high": "positive", "greater": "positive",
    "decreased": "negative", "reduced": "negative", "lower": "negative",
    "low": "negative", "less": "negative", "fewer": "negative",
}
DIR_ENRICH_DEPLETE_MAP = {
    "enriched": "positive", "increased": "positive", "higher": "positive",
    "more": "positive", "greater": "positive",
    "depleted": "negative", "decreased": "negative", "lower": "negative",
    "less": "negative", "fewer": "negative",
}

# ── Microbiome-relevance boost entities (replaces EFRE's nutrition boost) ──
MICROBIOME_RELEVANCE_RE = re.compile(
    r"\b(microbiom|microbiota|gut bacteria|fecal|faecal|dysbiosis|"
    r"probiotic|prebiotic|synbiotic|postbiotic|"
    r"short.?chain fatty acid|scfa|butyrate|acetate|propionate|"
    r"akkermansia|bacteroides|firmicutes|bifidobacter|lactobacill|"
    r"faecalibacterium|prevotella|roseburia|clostridi|"
    r"fusobacterium|enterococcus|veillonella|"
    r"antibiotic|antimicrobial|bacteriocin|"
    r"inflammatory bowel|crohn|ulcerative colitis|colitis|"
    r"irritable bowel|ibs|ibd|"
    r"leaky gut|intestinal permeability|gut barrier|"
    r"gut.?brain|microbiome.?gut|"
    r"16s|shotgun|metagenomic|amplicon|operational taxonomic)\b",
    re.I,
)


def detect_study_type(evidence: str, source_type: str = "") -> str:
    """Detect study type from evidence text.

    Returns the study type key from STUDY_TYPE_SCORES, or 'unknown'.
    """
    combined = f"{evidence} {source_type}".lower()
    for study_type, pattern in STUDY_TYPE_PATTERNS.items():
        if pattern.search(combined):
            return study_type
    return "unknown"


def detect_section_context(evidence: str, evidence_type: str = "") -> str:
    """Detect the section context from evidence metadata.

    Returns the section key from SECTION_SCORES, or a default.
    """
    combined = f"{evidence} {evidence_type}".lower()
    for section in SECTION_SCORES:
        if section in combined:
            return section
    return "unknown"


def recover_evidence_direction(evidence: str, object_text: str) -> str | None:
    """Recover the sign of an association from its cited evidence.

    Ported from EFRE's _evidence_direction() and extended with
    microbiome-specific abundance / enrichment / depletion patterns.

    Returns 'positive' (exposure raises the outcome) or 'negative'
    (exposure lowers it), or None when the evidence carries no
    directional signal.
    """
    if not evidence or not object_text:
        return None

    # 1. "increased/decreased risk of X"
    m = DIR_ADJ_BEFORE_RISK_RE.search(evidence)
    if m:
        return DIR_IMPLIED_BY_RISK_OBJ.get(m.group(1).lower())

    # 2. "inversely/positively associated"
    m = DIR_ASSOCIATED_RE.search(evidence)
    if m:
        return {
            "inversely": "negative", "negatively": "negative",
            "positively": "positive", "directly": "positive",
        }[m.group(1).lower()]

    # 3. Microbiome-specific: "enriched/depleted in X"
    m = DIR_ENRICHED_IN_RE.search(evidence)
    if m:
        return DIR_ENRICH_DEPLETE_MAP.get(m.group(1).lower())

    # 4. Microbiome-specific: "increased/decreased abundance"
    if DIR_ABUNDANCE_UP_RE.search(evidence) and not DIR_ABUNDANCE_DOWN_RE.search(evidence):
        return "positive"
    if DIR_ABUNDANCE_DOWN_RE.search(evidence) and not DIR_ABUNDANCE_UP_RE.search(evidence):
        return "negative"

    # 5. Object-anchored: look for direction word near the object mention
    obj_tok = [w for w in re.split(r"[^a-z0-9]+", object_text.lower()) if w and len(w) > 2]
    if not obj_tok:
        return None
    for n in (3, 2, 1):
        probe = r"\b" + r"\s+".join(re.escape(w) for w in obj_tok[:n]) + r"\b"
        hit = re.search(probe, evidence, re.I)
        if hit:
            start = max(0, hit.start() - 60)
            window = evidence[start:hit.end()]
            up = DIR_UP_RE.search(window)
            down = DIR_DOWN_RE.search(window)
            if up and not down:
                return "positive"
            if down and not up:
                return "negative"
            break
    return None


def _has_grounding(entity_row: dict) -> bool:
    """Check if an entity has ontology grounding (any ontology ID)."""
    for col in ("UMLS_ID", "OLS", "Bioportal", "NCBITaxon", "OMOP"):
        val = entity_row.get(col, "") or ""
        if val and val.strip():
            return True
    return False


def _evidence_quality_score(evidence: str) -> float:
    """Score evidence quality based on strong vs hedge words.

    Returns 0..1 where 1 = strong causal evidence, 0 = purely correlational.
    """
    if not evidence:
        return 0.0
    ev_lower = evidence.lower()
    has_hedge = any(h in ev_lower for h in HEDGE_WORDS)
    has_strong = any(s in ev_lower for s in STRONG_EVIDENCE_WORDS)

    if has_strong and not has_hedge:
        return 1.0
    if has_strong and has_hedge:
        return 0.7
    if has_hedge and not has_strong:
        return 0.3
    return 0.5  # neutral


def scientific_quality(
    rel: dict,
    subject_entity: dict,
    object_entity: dict,
    n_papers: int = 1,
    llm_verdict: str = "",
    bio_audit_flag: str = "",
    external_corroboration: list[str] | None = None,
) -> tuple[float, str, str | None]:
    """Compute a 0..1 composite scientific quality score for a relationship.

    Args:
        rel: Relationship dict (from DB row)
        subject_entity: Subject entity dict (from DB row)
        object_entity: Object entity dict (from DB row)
        n_papers: Number of corroborating papers
        llm_verdict: LLM verifier verdict ('supported', 'demoted', 'flagged', etc.)
        bio_audit_flag: Bio-audit flag name if flagged, '' otherwise
        external_corroboration: List of external DBs that corroborated this relation

    Returns:
        (score, confidence_basis, direction) where score is 0..1,
        confidence_basis is a human-readable string explaining the score,
        and direction is 'positive', 'negative', or None.
    """
    score = 0.0
    basis_parts: list[str] = []

    # ── 1. LLM verdict (0.30) ──
    verdict = (llm_verdict or rel.get("validation_status", "") or "").lower()
    if "supported" in verdict:
        v_score = 0.30 * 0.8  # assume 0.8 confidence if not specified
        basis_parts.append(f"llm=supported(+0.24)")
    elif "demote" in verdict or "contradict" in verdict:
        v_score = 0.10
        basis_parts.append(f"llm=demoted(+0.10)")
    elif "flag" in verdict:
        v_score = 0.15
        basis_parts.append(f"llm=flagged(+0.15)")
    else:
        v_score = 0.15  # unknown/default
        basis_parts.append(f"llm=unknown(+0.15)")
    score += v_score

    # ── 2. Subject grounding (0.15) ──
    if _has_grounding(subject_entity):
        score += 0.15
        basis_parts.append("subj_grounded(+0.15)")
    else:
        basis_parts.append("subj_ungrounded(+0.00)")

    # ── 3. Object grounding (0.15) ──
    if _has_grounding(object_entity):
        score += 0.15
        basis_parts.append("obj_grounded(+0.15)")
    else:
        basis_parts.append("obj_ungrounded(+0.00)")

    # ── 4. Evidence quality (0.15) ──
    evidence = rel.get("evidence", "") or ""
    eq_score = _evidence_quality_score(evidence)
    eq_weight = 0.15 * eq_score
    score += eq_weight
    basis_parts.append(f"evidence_quality={eq_score:.2f}(+{eq_weight:.3f})")

    # ── 5. Study type (0.10) — prefer DB column from study_type_annotator ──
    source_type = rel.get("source_type", "") or ""
    study_type = rel.get("study_type", "") or ""
    if not study_type or study_type == "unknown":
        study_type = detect_study_type(evidence, source_type)
    st_score = STUDY_TYPE_SCORES.get(study_type, 0.25)
    st_weight = 0.10 * st_score
    score += st_weight
    basis_parts.append(f"study_type={study_type}(+{st_weight:.3f})")

    # ── 6. Section context (0.10) ──
    evidence_type = rel.get("evidence_type", "") or ""
    section = detect_section_context(evidence, evidence_type)
    sec_score = SECTION_SCORES.get(section, 0.5)
    sec_weight = 0.10 * sec_score
    score += sec_weight
    basis_parts.append(f"section={section}(+{sec_weight:.3f})")

    # ── 7. Corroboration (0.15) ──
    if n_papers >= 5:
        corrob_weight = 0.15
    elif n_papers >= 2:
        corrob_weight = 0.10
    else:
        corrob_weight = 0.03
    score += corrob_weight
    basis_parts.append(f"n_papers={n_papers}(+{corrob_weight:.3f})")

    # ── 8. Predicate strength modulation ──
    pred = (rel.get("relationship_type", "") or "").lower()
    if pred == "associated_with":
        score *= 0.85
        basis_parts.append("pred=associated_with(×0.85)")
    elif pred in ("treats", "treated_by", "produces", "produced_by", "disrupts",
                   "encodes", "expresses"):
        basis_parts.append(f"pred={pred}(×1.0)")

    # ── Post-score: Microbiome relevance boost (up to +0.08) ──
    subj_text = (rel.get("subject", "") or subject_entity.get("term", "")).lower()
    obj_text = (rel.get("object", "") or object_entity.get("term", "")).lower()
    mb_boost = 0.0
    if MICROBIOME_RELEVANCE_RE.search(subj_text):
        mb_boost += 0.04
    if MICROBIOME_RELEVANCE_RE.search(obj_text):
        mb_boost += 0.04
    if mb_boost > 0:
        score = min(1.0, score + mb_boost)
        basis_parts.append(f"microbiome_boost(+{mb_boost:.2f})")

    # ── Post-score: Bio-audit penalty (up to -0.15) ──
    if bio_audit_flag:
        if "demote" in (rel.get("demotion_reason", "") or "").lower():
            score -= 0.15
            basis_parts.append(f"bio_audit_demoted(-0.15)")
        else:
            score -= 0.05
            basis_parts.append(f"bio_audit_flagged(-0.05)")

    # ── Post-score: External corroboration bonus (up to +0.05) ──
    if external_corroboration:
        bonus = min(0.05, 0.02 * len(external_corroboration))
        score = min(1.0, score + bonus)
        basis_parts.append(f"ext_corroboration={len(external_corroboration)}(+{bonus:.2f})")

    # ── Direction recovery (all predicates — microbiome direction is common) ──
    direction = recover_evidence_direction(evidence, obj_text)
    if direction:
        basis_parts.append(f"direction={direction}")

    score = round(max(0.0, min(1.0, score)), 4)
    confidence_basis = " | ".join(basis_parts)

    return score, confidence_basis, direction


def rescore_relations(
    db_path: Path | str = DB_PATH,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Recompute scientific confidence scores for all relationships in the DB.

    Updates the confidence column and adds a confidence_basis column.

    Args:
        db_path: Path to microbiome_cdm.db
        dry_run: If True, don't modify the DB

    Returns:
        Summary dict with score distribution and counts.
    """
    db_path = Path(db_path)
    conn = sqlite3.connect(str(db_path))

    # Add confidence_basis column if not exists
    if not dry_run:
        try:
            conn.execute("ALTER TABLE relationships ADD COLUMN confidence_basis TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE relationships ADD COLUMN association_direction TEXT")
        except sqlite3.OperationalError:
            pass

    # Check if external_corroboration column exists
    cursor = conn.execute("PRAGMA table_info(relationships)")
    col_names = {row[1] for row in cursor.fetchall()}
    has_ext_corr = "external_corroboration" in col_names

    # Load all relationships with entity info
    has_study_type = "study_type" in col_names
    base_query = """
        SELECT r.id, r.source_id, r.target_id, r.relationship_type,
               r.confidence as old_confidence, r.evidence, r.source_type,
               r.evidence_type, r.validation_status, r.demotion_reason,
               r.co_occurrence_count, r.pubmed_ids,
               {st_sel}
               {ext_corr_sel}
               s.term as subject, s.entity_type as subject_type,
               s.UMLS_ID as s_umls, s.OLS as s_ols, s.Bioportal as s_bp,
               s.NCBITaxon as s_ncbitaxon, s.OMOP as s_omop,
               t.term as object, t.entity_type as object_type,
               t.UMLS_ID as t_umls, t.OLS as t_ols, t.Bioportal as t_bp,
               t.NCBITaxon as t_ncbitaxon, t.OMOP as t_omop
        FROM relationships r
        JOIN entities s ON r.source_id = s.id
        JOIN entities t ON r.target_id = t.id
    """.format(
        st_sel="r.study_type," if has_study_type else "NULL as study_type,",
        ext_corr_sel="r.external_corroboration," if has_ext_corr else "NULL as external_corroboration,",
    )
    rows = conn.execute(base_query).fetchall()
    cols = [d[0] for d in conn.execute(base_query).description]
    relations = [dict(zip(cols, row)) for row in rows]
    conn.close()

    print(f"Loaded {len(relations):,} relations for confidence rescoring")

    # Group by (source_id, relationship_type, target_id) to get n_papers
    from collections import defaultdict
    paper_counts: dict[tuple, int] = defaultdict(int)
    for rel in relations:
        key = (rel["source_id"], rel["relationship_type"], rel["target_id"])
        n_pmids = len([p for p in (rel.get("pubmed_ids", "") or "").split(",") if p.strip()])
        paper_counts[key] = max(paper_counts[key], n_pmids, rel.get("co_occurrence_count", 1) or 1)

    updates: list[tuple] = []
    score_distribution = Counter()
    direction_counts: Counter = Counter()
    old_new_diffs = []

    for rel in relations:
        subject_entity = {
            "term": rel.get("subject", ""),
            "UMLS_ID": rel.get("s_umls", ""),
            "OLS": rel.get("s_ols", ""),
            "Bioportal": rel.get("s_bp", ""),
            "NCBITaxon": rel.get("s_ncbitaxon", ""),
            "OMOP": rel.get("s_omop", ""),
        }
        object_entity = {
            "term": rel.get("object", ""),
            "UMLS_ID": rel.get("t_umls", ""),
            "OLS": rel.get("t_ols", ""),
            "Bioportal": rel.get("t_bp", ""),
            "NCBITaxon": rel.get("t_ncbitaxon", ""),
            "OMOP": rel.get("t_omop", ""),
        }

        # Parse external corroboration
        ext_corr = rel.get("external_corroboration", "")
        if ext_corr:
            try:
                ext_corr_list = json.loads(ext_corr)
            except (json.JSONDecodeError, TypeError):
                ext_corr_list = []
        else:
            ext_corr_list = None

        # Get n_papers for this relation
        key = (rel["source_id"], rel["relationship_type"], rel["target_id"])
        n_papers = paper_counts.get(key, 1)

        # Get LLM verdict from validation_status
        llm_verdict = rel.get("validation_status", "") or ""

        # Get bio-audit flag from demotion_reason
        bio_flag = ""
        demotion = (rel.get("demotion_reason", "") or "").lower()
        if "bio_audit" in demotion:
            bio_flag = "bio_audit"

        new_score, basis, direction = scientific_quality(
            rel=rel,
            subject_entity=subject_entity,
            object_entity=object_entity,
            n_papers=n_papers,
            llm_verdict=llm_verdict,
            bio_audit_flag=bio_flag,
            external_corroboration=ext_corr_list,
        )

        # Track distribution
        bucket = f"{new_score:.1f}"
        score_distribution[bucket] += 1
        if direction:
            direction_counts[direction] += 1

        old_conf = rel.get("old_confidence", 0) or 0
        old_new_diffs.append(new_score - old_conf)

        updates.append((new_score, basis, direction, rel["id"]))

    # Apply updates
    if not dry_run:
        conn = sqlite3.connect(str(db_path))
        conn.executemany(
            "UPDATE relationships SET confidence = ?, confidence_basis = ?, "
            "association_direction = ? WHERE id = ?",
            updates,
        )
        conn.commit()
        conn.close()
        print(f"Updated {len(updates):,} relationships")

    # Stats
    n_up = sum(1 for d in old_new_diffs if d > 0.01)
    n_down = sum(1 for d in old_new_diffs if d < -0.01)
    n_same = sum(1 for d in old_new_diffs if abs(d) <= 0.01)

    return {
        "n_scored": len(updates),
        "score_distribution": dict(sorted(score_distribution.items())),
        "n_increased": n_up,
        "n_decreased": n_down,
        "n_unchanged": n_same,
        "direction_recovered": dict(direction_counts),
        "mean_old_score": sum(r.get("old_confidence", 0) or 0 for r in relations) / max(len(relations), 1),
        "mean_new_score": sum(u[0] for u in updates) / max(len(updates), 1),
        "dry_run": dry_run,
    }


def main():
    ap = argparse.ArgumentParser(description="Scientific confidence scoring for MCDM KG")
    ap.add_argument("--db", required=True, help="Path to microbiome_cdm.db")
    ap.add_argument("--dry-run", action="store_true", help="Don't modify DB")
    args = ap.parse_args()

    result = rescore_relations(db_path=args.db, dry_run=args.dry_run)

    print(f"\n{'='*60}")
    print(f"CONFIDENCE RESCORE ({'DRY RUN' if result['dry_run'] else 'APPLIED'})")
    print(f"{'='*60}")
    print(f"Relations scored:     {result['n_scored']:,}")
    print(f"Mean old score:       {result['mean_old_score']:.4f}")
    print(f"Mean new score:       {result['mean_new_score']:.4f}")
    print(f"Increased:            {result['n_increased']:,}")
    print(f"Decreased:            {result['n_decreased']:,}")
    print(f"Unchanged:            {result['n_unchanged']:,}")
    dirs = result.get("direction_recovered", {})
    if dirs:
        print(f"Direction recovered:  {dirs}")
    print(f"\nScore distribution:")
    for bucket, count in result["score_distribution"].items():
        bar = "#" * (count // max(1, result["n_scored"] // 50))
        print(f"  {bucket}: {count:6d} {bar}")


if __name__ == "__main__":
    main()
