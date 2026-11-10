"""D16 - canonical terminology quality (component C).

Read-only. Audits the 162,409 retained canonical terms: normalisation and
grouping behaviour, over-merging / under-merging signatures, type assignment,
generic ENTITY overuse, ambiguous abbreviations, taxonomic specificity, mention
link stability, and removed-term reasons.

Terms are always reported distinct-weighted and mention-weighted separately:
a defect affecting 1% of term rows may affect 30% of mentions.
"""
from __future__ import annotations

import collections
import json
import re
import sqlite3

from common import DB, emit

CDM_TYPES = [
    "ORGANISM", "TAXON", "CHEMICAL", "GENE", "PROTEIN", "DISEASE",
    "PHENOTYPE", "ANATOMY", "HABITAT", "DIET", "HOST", "EXPERIMENTAL_METHOD",
    "SEQUENCING_PLATFORM", "STATISTICAL_METHOD", "CLINICAL", "OTHER",
]

# Surfaces that are almost never a single biological concept on their own.
GENERIC_SURFACES = {
    "bacteria", "microbiota", "microbiome", "flora", "organism", "organisms",
    "species", "strain", "strains", "isolate", "isolates", "sample", "samples",
    "patient", "patients", "subject", "subjects", "participant", "participants",
    "group", "groups", "data", "dataset", "study", "studies", "analysis",
    "dna", "rna", "gene", "genes", "protein", "proteins", "cell", "cells",
    "figure", "table", "supplement", "supplementary", "sequence", "sequences",
    "genus", "family", "phylum", "order", "class", "taxa", "taxon",
}


def norm_ws(s):
    return " ".join((s or "").split())


def main():
    out = {}
    c = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)

    ct_cols = [r[1] for r in c.execute("PRAGMA table_info(canonical_term)")]
    out["canonical_term_columns"] = ct_cols
    for need in ("term_id", "term", "term_norm", "cdm_type", "mention_count",
                 "definition_count", "review_status", "is_generic_type"):
        assert need in ct_cols, "canonical_term missing %s" % need

    out["canonical_terms"] = c.execute("SELECT COUNT(*) FROM canonical_term").fetchone()[0]
    out["distinct_term_norm"] = c.execute(
        "SELECT COUNT(DISTINCT term_norm) FROM canonical_term"
    ).fetchone()[0]

    # ---- type distribution, distinct and mention weighted -------------------
    rows = c.execute(
        "SELECT cdm_type, COUNT(*), SUM(COALESCE(mention_count,0)) "
        "FROM canonical_term GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall()
    tot_n = sum(r[1] for r in rows)
    tot_m = sum(r[2] or 0 for r in rows)
    out["by_cdm_type"] = {
        t: {
            "terms": n,
            "terms_pct": round(100.0 * n / max(1, tot_n), 3),
            "mentions": m,
            "mentions_pct": round(100.0 * (m or 0) / max(1, tot_m), 3),
        }
        for t, n, m in rows
    }
    out["cdm_type_not_in_declared_vocabulary"] = sorted(
        {r[0] for r in rows if r[0] not in CDM_TYPES and r[0] != "ENTITY"}
    )
    out["generic_type_rows"] = c.execute(
        "SELECT COUNT(*) FROM canonical_term WHERE cdm_type='ENTITY'"
    ).fetchone()[0]
    out["generic_type_mentions"] = c.execute(
        "SELECT COALESCE(SUM(mention_count),0) FROM canonical_term WHERE cdm_type='ENTITY'"
    ).fetchone()[0]
    out["is_generic_type_flag"] = c.execute(
        "SELECT COUNT(*) FROM canonical_term WHERE is_generic_type IN ('1',1,'true','TRUE')"
    ).fetchone()[0]
    # disagreement between the flag and the type
    out["flag_vs_type_disagreement"] = c.execute(
        "SELECT COUNT(*) FROM canonical_term WHERE "
        "(is_generic_type IN ('1',1,'true','TRUE') AND cdm_type<>'ENTITY') OR "
        "(COALESCE(is_generic_type,'') NOT IN ('1','true','TRUE') AND cdm_type='ENTITY')"
    ).fetchone()[0]
    out["type_source"] = dict(
        c.execute("SELECT type_source, COUNT(*) FROM canonical_term GROUP BY 1 ORDER BY 2 DESC").fetchall()
    )
    out["cdm_type_original"] = dict(
        c.execute(
            "SELECT cdm_type_original, COUNT(*) FROM canonical_term GROUP BY 1 ORDER BY 2 DESC LIMIT 25"
        ).fetchall()
    )

    # ---- surface-form and normalisation behaviour ---------------------------
    # term_norm that groups several distinct surface forms = merge decision
    multi = c.execute(
        "SELECT COUNT(*) FROM (SELECT term_norm FROM canonical_term "
        "GROUP BY term_norm HAVING COUNT(DISTINCT term)>1)"
    ).fetchone()[0]
    out["term_norm_groups_with_multiple_surfaces"] = multi
    out["term_norm_merge_examples"] = c.execute(
        "SELECT term_norm, COUNT(DISTINCT term), GROUP_CONCAT(DISTINCT term) FROM canonical_term "
        "GROUP BY term_norm HAVING COUNT(DISTINCT term)>1 ORDER BY 2 DESC LIMIT 15"
    ).fetchall()

    # over-merge risk: normalisation collapsing distinct qualifiers
    # e.g. removal of punctuation/hyphens merges "Bacteroides vulgatus" variants
    over = c.execute(
        "SELECT term_norm, GROUP_CONCAT(DISTINCT term) FROM canonical_term "
        "GROUP BY term_norm HAVING COUNT(DISTINCT term)>1"
    ).fetchall()
    qualifier_risk = []
    for tf, terms in over:
        parts = [t for t in (terms or "").split(",") if t.strip()]
        # flag pairs whose difference is a digit/strain token or a negation
        if len(parts) > 1:
            lows = {p.strip().lower() for p in parts}
            if any(re.search(r"\d", p) for p in lows):
                qualifier_risk.append({"term_norm": tf, "surfaces": parts[:6]})
        if len(qualifier_risk) >= 10:
            break
    out["overmerge_numeric_qualifier_examples"] = qualifier_risk

    # under-merge risk: near-identical normals that stayed separate
    # cheap deterministic proxy: terms differing only by plural / trailing 's'
    under = c.execute(
        "SELECT term_norm, term_id FROM canonical_term"
    ).fetchall()
    norm_set = {r[0] for r in under}
    sing = []
    for n, tid in under:
        if n and n.endswith("s") and len(n) > 4 and n[:-1] in norm_set and (n[:-1] + "s") != n:
            other = c.execute(
                "SELECT term_id, term FROM canonical_term WHERE term_norm=?", (n[:-1],)
            ).fetchone()
            if other:
                sing.append({"plural": n, "singular": n[:-1]})
        if len(sing) >= 15:
            break
    out["undermerge_plural_examples"] = sing
    out["undermerge_plural_count_at_least"] = len(sing)

    # ---- generic / vacuous surfaces ----------------------------------------
    gen_rows = c.execute(
        "SELECT term, COUNT(*) FROM canonical_term "
        "WHERE LOWER(TRIM(term)) IN (%s) GROUP BY 1"
        % ",".join("?" * len(GENERIC_SURFACES)),
        tuple(sorted(GENERIC_SURFACES)),
    ).fetchall()
    out["generic_surface_terms"] = {t: n for t, n in gen_rows}
    out["generic_surface_rows"] = sum(n for _, n in gen_rows)
    out["generic_surface_mentions"] = c.execute(
        "SELECT COALESCE(SUM(mention_count),0) FROM canonical_term WHERE LOWER(TRIM(term)) IN (%s)"
        % ",".join("?" * len(GENERIC_SURFACES)),
        tuple(sorted(GENERIC_SURFACES)),
    ).fetchone()[0]

    # very short surfaces (1-2 chars) that survived canonicalisation
    out["short_surfaces"] = {}
    for L in (1, 2, 3):
        out["short_surfaces"]["len_%d" % L] = c.execute(
            "SELECT COUNT(*) FROM canonical_term WHERE LENGTH(TRIM(term))=?", (L,)
        ).fetchone()[0]
    out["short_surface_examples"] = c.execute(
        "SELECT term, cdm_type, mention_count FROM canonical_term "
        "WHERE LENGTH(TRIM(term))<=2 ORDER BY COALESCE(mention_count,0) DESC LIMIT 20"
    ).fetchall()

    # ---- ambiguous abbreviations -------------------------------------------
    # short all-caps or mixed-case surfaces that are not taxon abbreviations
    abbrev = c.execute(
        "SELECT term, cdm_type, COUNT(*) OVER () FROM canonical_term "
        "WHERE LENGTH(term) BETWEEN 2 AND 6 AND term=UPPER(term) "
        "AND term GLOB '[A-Z]*' AND term NOT GLOB '*[0-9]*' "
        "ORDER BY COALESCE(mention_count,0) DESC LIMIT 25"
    ).fetchall()
    out["abbreviation_examples"] = [(t, ty) for t, ty, _ in abbrev]
    out["abbreviation_rows"] = c.execute(
        "SELECT COUNT(*) FROM canonical_term WHERE LENGTH(term) BETWEEN 2 AND 6 "
        "AND term=UPPER(term) AND term GLOB '[A-Z]*' AND term NOT GLOB '*[0-9]*'"
    ).fetchone()[0]
    # same abbreviation under several types = ambiguity
    out["abbrev_multi_type"] = c.execute(
        "SELECT COUNT(*) FROM (SELECT term FROM canonical_term WHERE LENGTH(term) BETWEEN 2 AND 6 "
        "AND term=UPPER(term) AND term GLOB '[A-Z]*' GROUP BY term HAVING COUNT(DISTINCT cdm_type)>1)"
    ).fetchone()[0]
    out["abbrev_multi_type_examples"] = c.execute(
        "SELECT term, GROUP_CONCAT(DISTINCT cdm_type) FROM canonical_term "
        "WHERE LENGTH(term) BETWEEN 2 AND 6 AND term=UPPER(term) AND term GLOB '[A-Z]*' "
        "GROUP BY term HAVING COUNT(DISTINCT cdm_type)>1 ORDER BY 2 LIMIT 12"
    ).fetchall()

    # ---- taxonomic specificity --------------------------------------------
    # binomial (Genus species) vs bare genus vs strain designation
    out["binomial_like"] = c.execute(
        "SELECT COUNT(*) FROM canonical_term WHERE term GLOB '[A-Z][a-z]* [a-z]*'"
    ).fetchone()[0]
    for ty in ("ORGANISM", "TAXON"):
        out["type_%s_rows" % ty] = c.execute(
            "SELECT COUNT(*) FROM canonical_term WHERE cdm_type=?", (ty,)
        ).fetchone()[0]
    out["organism_rows_without_binomial_shape"] = c.execute(
        "SELECT COUNT(*) FROM canonical_term WHERE cdm_type IN ('ORGANISM','TAXON') "
        "AND term NOT GLOB '[A-Z][a-z]* [a-z]*'"
    ).fetchone()[0]
    out["organism_examples_non_binomial"] = c.execute(
        "SELECT term, cdm_type, mention_count FROM canonical_term "
        "WHERE cdm_type IN ('ORGANISM','TAXON') AND term NOT GLOB '[A-Z][a-z]* [a-z]*' "
        "ORDER BY COALESCE(mention_count,0) DESC LIMIT 15"
    ).fetchall()
    out["strain_designation_rows"] = c.execute(
        "SELECT COUNT(*) FROM canonical_term WHERE term GLOB '*[A-Z][a-z]* [a-z]* *[0-9A-Z]*' "
        "AND cdm_type IN ('ORGANISM','TAXON')"
    ).fetchone()[0]

    # ---- mention link stability -------------------------------------------
    # a canonical term whose linked mentions span many papers is more stable
    out["term_paper_reach"] = {}
    for lo, hi, lbl in ((1, 1, "1_paper"), (2, 2, "2_papers"), (3, 9, "3_9"),
                        (10, 49, "10_49"), (50, 10 ** 9, "50_plus")):
        out["term_paper_reach"][lbl] = c.execute(
            "SELECT COUNT(*) FROM (SELECT canonical_term_id FROM term_mention "
            "WHERE canonical_term_id IS NOT NULL GROUP BY 1 "
            "HAVING COUNT(DISTINCT paper_id) BETWEEN ? AND ?)", (lo, hi)
        ).fetchone()[0]

    # ---- removed terms and their reasons ----------------------------------
    rc = [r[1] for r in c.execute("PRAGMA table_info(removed_canonical_term)")]
    out["removed_canonical_term_columns"] = rc
    out["removed_terms"] = c.execute("SELECT COUNT(*) FROM removed_canonical_term").fetchone()[0]
    for col in rc:
        if "reason" in col.lower():
            out["removed_reason_%s" % col] = dict(
                c.execute(
                    "SELECT COALESCE(%s,'(null)'), COUNT(*) FROM removed_canonical_term GROUP BY 1 ORDER BY 2 DESC LIMIT 20" % col
                ).fetchall()
            )
    # do removed terms still carry mentions?
    out["removed_terms_with_live_mentions"] = c.execute(
        "SELECT COUNT(DISTINCT r.term_id) FROM removed_canonical_term r "
        "JOIN term_mention m ON m.canonical_term_id=r.term_id"
    ).fetchone()[0]
    out["non_concept_surface_rows"] = c.execute(
        "SELECT COUNT(*) FROM canonical_term WHERE is_non_concept_surface IN ('1',1,'true','TRUE')"
    ).fetchone()[0]
    out["non_concept_reason"] = dict(
        c.execute(
            "SELECT COALESCE(non_concept_reason,'(null)'), COUNT(*) FROM canonical_term GROUP BY 1 ORDER BY 2 DESC LIMIT 15"
        ).fetchall()
    )
    out["review_status"] = dict(
        c.execute("SELECT review_status, COUNT(*) FROM canonical_term GROUP BY 1 ORDER BY 2 DESC").fetchall()
    )

    # ---- type conflicts at the surface level across papers ----------------
    # same surface appearing under several CDM types is a stability risk
    out["surface_multi_type_groups"] = c.execute(
        "SELECT COUNT(*) FROM (SELECT term_norm FROM canonical_term GROUP BY term_norm "
        "HAVING COUNT(DISTINCT cdm_type)>1)"
    ).fetchone()[0]
    out["most_common_alternative_types"] = c.execute(
        "SELECT alternative_types, COUNT(*) FROM canonical_term "
        "WHERE alternative_types IS NOT NULL AND alternative_types<>'' "
        "GROUP BY 1 ORDER BY 2 DESC LIMIT 15"
    ).fetchall()
    out["rows_with_alternative_types"] = c.execute(
        "SELECT COUNT(*) FROM canonical_term WHERE alternative_types IS NOT NULL AND alternative_types<>''"
    ).fetchone()[0]
    out["type_disagreement_flag"] = c.execute(
        "SELECT COUNT(*) FROM canonical_term WHERE cdm_type_ds_suggestion IS NOT NULL "
        "AND cdm_type_ds_suggestion<>'' AND cdm_type_ds_suggestion<>cdm_type"
    ).fetchone()[0]

    c.close()
    emit("d16_terminology_quality", out)


if __name__ == "__main__":
    main()
