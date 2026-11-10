"""D17 - vocabulary mapping quality (component D) and definition quality (E).

Read-only. Component D tests the 331,394 term_concept_map rows: relation mix,
guard behaviour, disposition, candidate rank structure, lexical-versus-exact
character of accepted mappings, provenance attribution and coverage. Component E
tests the 6,773 definitions: does the quoted passage actually contain/define the
term, is the definition specific, are there duplicates and contradictions, and
is the author-declared definition type consistent with the text.

Neither component has a gold standard here, so nothing is called accuracy.
"""
from __future__ import annotations

import collections
import json
import re
import sqlite3

from common import DB, TERM, emit


def norm_ws(s):
    return " ".join((s or "").split())


def load_jsonl(p):
    out = []
    with open(p, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def main():
    out = {}
    c = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)

    # ======================= component D: mappings ==========================
    tcm = [r[1] for r in c.execute("PRAGMA table_info(term_concept_map)")]
    out["mapping_columns"] = tcm
    out["mapping_rows"] = c.execute("SELECT COUNT(*) FROM term_concept_map").fetchone()[0]

    out["mapping_relation"] = dict(
        c.execute("SELECT mapping_relation, COUNT(*) FROM term_concept_map GROUP BY 1 ORDER BY 2 DESC").fetchall()
    )
    out["guard_status"] = dict(
        c.execute("SELECT guard_status, COUNT(*) FROM term_concept_map GROUP BY 1 ORDER BY 2 DESC").fetchall()
    )
    out["mapping_disposition"] = dict(
        c.execute("SELECT mapping_disposition, COUNT(*) FROM term_concept_map GROUP BY 1 ORDER BY 2 DESC").fetchall()
    )
    out["term_status"] = dict(
        c.execute("SELECT term_status, COUNT(*) FROM term_concept_map GROUP BY 1 ORDER BY 2 DESC").fetchall()
    )
    out["matched_via"] = dict(
        c.execute("SELECT COALESCE(matched_via,'(null)'), COUNT(*) FROM term_concept_map GROUP BY 1 ORDER BY 2 DESC LIMIT 20").fetchall()
    )
    out["candidate_rank"] = dict(
        c.execute("SELECT COALESCE(candidate_rank,'(null)'), COUNT(*) FROM term_concept_map GROUP BY 1 ORDER BY 2 DESC LIMIT 12").fetchall()
    )
    out["is_canonical_candidate"] = dict(
        c.execute("SELECT COALESCE(is_canonical_candidate,'(null)'), COUNT(*) FROM term_concept_map GROUP BY 1 ORDER BY 2 DESC").fetchall()
    )
    out["mapping_provenance"] = dict(
        c.execute("SELECT COALESCE(mapping_provenance,'(null)'), COUNT(*) FROM term_concept_map GROUP BY 1 ORDER BY 2 DESC LIMIT 20").fetchall()
    )
    out["mapping_evidence_status"] = dict(
        c.execute("SELECT COALESCE(mapping_evidence_status,'(null)'), COUNT(*) FROM term_concept_map GROUP BY 1 ORDER BY 2 DESC LIMIT 15").fetchall()
    )
    out["guard_rejection_reason"] = dict(
        c.execute("SELECT COALESCE(guard_rejection_reason,'(null)'), COUNT(*) FROM term_concept_map GROUP BY 1 ORDER BY 2 DESC LIMIT 20").fetchall()
    )
    out["source_service_mapping"] = dict(
        c.execute("SELECT COALESCE(source_service_mapping,'(null)'), COUNT(*) FROM term_concept_map GROUP BY 1 ORDER BY 2 DESC LIMIT 15").fetchall()
    )
    out["relation_llm_g9"] = dict(
        c.execute("SELECT COALESCE(relation_llm_g9,'(null)'), COUNT(*) FROM term_concept_map GROUP BY 1 ORDER BY 2 DESC LIMIT 12").fetchall()
    )
    out["relation_deepseek"] = dict(
        c.execute("SELECT COALESCE(relation_deepseek,'(null)'), COUNT(*) FROM term_concept_map GROUP BY 1 ORDER BY 2 DESC LIMIT 15").fetchall()
    )
    # two-model agreement on relation judgement
    out["relation_model_agreement"] = c.execute(
        "SELECT COALESCE(relation_llm_g9,'(null)')||' || '||COALESCE(relation_deepseek,'(null)'), COUNT(*) "
        "FROM term_concept_map GROUP BY 1 ORDER BY 2 DESC LIMIT 20"
    ).fetchall()

    # coverage: how many live terms carry any candidate / any accepted mapping
    out["live_terms"] = c.execute(
        "SELECT COUNT(*) FROM canonical_term"
    ).fetchone()[0]
    out["live_terms_with_mapping"] = c.execute(
        "SELECT COUNT(DISTINCT term_id) FROM term_concept_map"
    ).fetchone()[0]
    for rel in ("EXACT_MATCH", "RELATED_TO", "AMBIGUOUS", "NO_MATCH_FOUND"):
        out["terms_with_%s" % rel] = c.execute(
            "SELECT COUNT(DISTINCT term_id) FROM term_concept_map WHERE mapping_relation=?",
            (rel,),
        ).fetchone()[0]
    out["terms_with_only_ambiguous_or_related"] = c.execute(
        "SELECT COUNT(*) FROM (SELECT term_id FROM term_concept_map GROUP BY term_id "
        "HAVING SUM(CASE WHEN mapping_relation='EXACT_MATCH' THEN 1 ELSE 0 END)=0)"
    ).fetchone()[0]

    # exact matches: identifier shape and whether the mapped concept label
    # actually equals the term surface (the core "genuinely equivalent" test)
    conc_cols = [r[1] for r in c.execute("PRAGMA table_info(concept)")]
    out["concept_columns"] = conc_cols
    # real schema: concept_id, concept_label, source_service, ontology_name.
    # Guard rather than guess: an unknown quoted column is silently a string
    # literal in SQLite, which is how earlier audits fabricated results.
    lab_col = next(
        (x for x in ("concept_label", "concept_name", "label", "name") if x in conc_cols),
        None,
    )
    assert lab_col, "concept label column not found in %s" % conc_cols
    out["concept_label_column"] = lab_col

    exact = c.execute(
        "SELECT ct.term, k.%s, tcm.mapping_relation, tcm.guard_status, tcm.mapping_disposition "
        "FROM term_concept_map tcm "
        "JOIN canonical_term ct ON ct.term_id=tcm.term_id "
        "LEFT JOIN concept k ON k.concept_id=tcm.concept_id "
        "WHERE tcm.mapping_relation IN ('EXACT_MATCH','RELATED_TO','AMBIGUOUS') "
        "AND k.%s IS NOT NULL" % (lab_col, lab_col)
    )
    cmp = collections.Counter()
    samples = collections.defaultdict(list)
    for term, label, rel, gs, disp in exact:
        same = norm_ws(term).lower() == norm_ws(label).lower()
        key = "%s|%s" % (rel, "label_identical" if same else "label_differs")
        cmp[key] += 1
        if not same and len(samples[key]) < 6:
            samples[key].append((term[:45], (label or "")[:45]))
    out["relation_vs_label_identity"] = dict(cmp)
    out["relation_vs_label_identity_examples"] = dict(samples)

    # exact matches where the surface is identical to the label: the strongest
    # available "genuinely equivalent" evidence
    out["exact_match_label_identical_rows"] = cmp.get("EXACT_MATCH|label_identical", 0)
    out["exact_match_label_differs_rows"] = cmp.get("EXACT_MATCH|label_differs", 0)
    tot_exact = out["exact_match_label_identical_rows"] + out["exact_match_label_differs_rows"]
    out["exact_match_label_identical_pct"] = round(
        100.0 * out["exact_match_label_identical_rows"] / max(1, tot_exact), 3
    )

    # guard pass rate per relation
    out["guard_by_relation"] = c.execute(
        "SELECT mapping_relation, guard_status, COUNT(*) FROM term_concept_map "
        "GROUP BY 1,2 ORDER BY 3 DESC LIMIT 30"
    ).fetchall()

    # ambiguity: how many accepted candidates does a term carry
    dist = c.execute(
        "SELECT n, COUNT(*) FROM (SELECT term_id, COUNT(*) n FROM term_concept_map "
        "WHERE mapping_disposition<>'REJECTED' GROUP BY term_id) GROUP BY 1 ORDER BY 1 LIMIT 15"
    ).fetchall()
    out["accepted_candidates_per_term_top"] = dist
    out["terms_with_multi_accepted"] = c.execute(
        "SELECT COUNT(*) FROM (SELECT term_id FROM term_concept_map "
        "WHERE mapping_disposition<>'REJECTED' GROUP BY term_id HAVING COUNT(*)>1)"
    ).fetchone()[0]

    # ======================= component E: definitions =======================
    td = [r[1] for r in c.execute("PRAGMA table_info(term_definition)")]
    out["definition_columns"] = td
    out["definition_rows"] = c.execute("SELECT COUNT(*) FROM term_definition").fetchone()[0]
    out["distinct_defined_terms"] = c.execute(
        "SELECT COUNT(DISTINCT term_id) FROM term_definition"
    ).fetchone()[0]
    out["definition_source"] = dict(
        c.execute("SELECT definition_source, COUNT(*) FROM term_definition GROUP BY 1 ORDER BY 2 DESC").fetchall()
    )
    out["extraction_run"] = dict(
        c.execute("SELECT COALESCE(extraction_run_id,'(null)'), COUNT(*) FROM term_definition GROUP BY 1 ORDER BY 2 DESC").fetchall()
    )
    out["extraction_method"] = dict(
        c.execute("SELECT COALESCE(extraction_method,'(null)'), COUNT(*) FROM term_definition GROUP BY 1 ORDER BY 2 DESC").fetchall()
    )
    out["evidence_anchor_status"] = dict(
        c.execute("SELECT COALESCE(evidence_anchor_status,'(null)'), COUNT(*) FROM term_definition GROUP BY 1 ORDER BY 2 DESC").fetchall()
    )
    out["definition_type_by_anchor"] = c.execute(
        "SELECT definition_source, evidence_anchor_status, COUNT(*) FROM term_definition "
        "GROUP BY 1,2 ORDER BY 3 DESC"
    ).fetchall()

    # 1. does the definition text actually mention the term?
    rows = c.execute(
        "SELECT d.definition_id, d.term, d.definition_text, d.definition_source, "
        "d.evidence_anchor_status, g.section_text_original, g.text_hash_sha256, "
        "d.section_text_sha256, d.paper_id, d.section_id "
        "FROM term_definition d LEFT JOIN section g "
        "ON g.paper_id=d.paper_id AND g.section_id_original=d.section_id"
    ).fetchall()
    out["definition_join_rows"] = len(rows)

    contains = collections.Counter()
    text_ok = 0
    hash_match = 0
    hash_mismatch = 0
    no_section = 0
    empty_def = 0
    specifics = collections.Counter()
    by_source = collections.defaultdict(lambda: collections.Counter())
    not_containing_examples = []
    for did, term, dtext, src, anchor, sect, shash, dhash, pid, sid in rows:
        dt = dtext or ""
        if not dt.strip():
            empty_def += 1
            continue
        if sect is None:
            no_section += 1
        if shash and dhash:
            if shash == dhash:
                hash_match += 1
            else:
                hash_mismatch += 1
        t = norm_ws(term).lower()
        d = norm_ws(dt).lower()
        if t and t in d:
            contains["term_in_definition"] += 1
            by_source[src]["term_in_definition"] += 1
        elif t:
            contains["term_absent_from_definition"] += 1
            by_source[src]["term_absent_from_definition"] += 1
            if len(not_containing_examples) < 15:
                not_containing_examples.append(
                    {"term": term[:45], "definition": dt[:90], "source": src}
                )
        # is the quoted passage actually present in the section?
        if sect and d:
            if d[:80] in norm_ws(sect).lower():
                text_ok += 1
                contains["passage_in_section"] += 1
            else:
                contains["passage_not_literal_in_section"] += 1
        # specificity proxy: a definition that is only the term, or <20 chars
        if len(dt.strip()) < 20:
            specifics["under_20_chars"] += 1
        if norm_ws(dt).lower().rstrip(".") == t:
            specifics["definition_equals_term"] += 1
        if re.fullmatch(r"[\W\d\s]+", dt):
            specifics["no_alphabetic_content"] += 1
        if len(dt) > 1200:
            specifics["over_1200_chars"] += 1
        if "et al" in d or "we " in d or "this study" in d:
            specifics["first_person_or_citation_style"] += 1

    out["definition_content_checks"] = dict(contains)
    out["definition_specificity_flags"] = dict(specifics)
    out["definition_term_coverage_by_source"] = {k: dict(v) for k, v in by_source.items()}
    out["definition_section_hash"] = {
        "match": hash_match, "mismatch": hash_mismatch,
        "mismatch_pct": round(100.0 * hash_mismatch / max(1, hash_match + hash_mismatch), 4),
    }
    out["definition_section_not_found"] = no_section
    out["definition_empty_text"] = empty_def
    out["definition_not_containing_term_examples"] = not_containing_examples

    # 2. duplicate definition text across different terms (broad reuse)
    out["definition_text_duplicate_groups"] = c.execute(
        "SELECT COUNT(*) FROM (SELECT definition_text FROM term_definition "
        "GROUP BY definition_text HAVING COUNT(DISTINCT term_id)>1)"
    ).fetchone()[0]
    out["definition_text_duplicate_examples"] = c.execute(
        "SELECT COUNT(DISTINCT term_id), SUBSTR(definition_text,1,80) FROM term_definition "
        "GROUP BY definition_text HAVING COUNT(DISTINCT term_id)>1 ORDER BY 1 DESC LIMIT 10"
    ).fetchall()

    # 3. contradictory definitions: same term, several definitions from
    #    different papers. Deterministic proxy: do they share vocabulary?
    multi = c.execute(
        "SELECT term_id, COUNT(DISTINCT definition_text) n FROM term_definition "
        "GROUP BY term_id HAVING n>1 ORDER BY n DESC LIMIT 200"
    ).fetchall()
    out["terms_with_multiple_definitions"] = c.execute(
        "SELECT COUNT(*) FROM (SELECT term_id FROM term_definition GROUP BY term_id "
        "HAVING COUNT(DISTINCT definition_text)>1)"
    ).fetchone()[0]
    div = []
    for tid, n in multi[:40]:
        texts = [
            r[0] for r in c.execute(
                "SELECT definition_text FROM term_definition WHERE term_id=? LIMIT 8", (tid,)
            )
        ]
        toks = [{w for w in re.findall(r"[a-z]{4,}", (t or "").lower())} for t in texts]
        if len(toks) > 1:
            inter = set.intersection(*toks) if all(toks) else set()
            union = set.union(*toks) if any(toks) else set()
            jac = len(inter) / max(1, len(union))
            div.append({"term_id": tid, "n_defs": n, "pairwise_jaccard": round(jac, 3)})
    out["multi_definition_overlap"] = div

    # 4. definition type plausibility (component E, source-specific)
    #    ABBREVIATION_EXPANSION should contain parentheses or a short expansion
    abbr = c.execute(
        "SELECT definition_text FROM term_definition WHERE definition_source='ABBREVIATION_EXPANSION'"
    ).fetchall()
    ab_ok = sum(1 for (t,) in abbr if re.search(r"[A-Za-z][\s-]*\(|\)\s*$", t or ""))
    out["abbreviation_expansion_shape"] = {
        "rows": len(abbr),
        "with_parenthetical_or_trailing_paren": ab_ok,
        "pct": round(100.0 * ab_ok / max(1, len(abbr)), 3),
    }
    gloss = c.execute(
        "SELECT definition_text FROM term_definition WHERE definition_source='GLOSSARY_DEFINITION'"
    ).fetchall()
    out["glossary_definition_count"] = len(gloss)
    out["glossary_mean_chars"] = round(
        sum(len(t or "") for (t,) in gloss) / max(1, len(gloss)), 1
    )

    # 5. terminology release subset relationship (already established in D11)
    tf = TERM / "term_definitions.jsonl"
    if tf.exists():
        recs = load_jsonl(tf)
        ids_file = {r.get("definition_id") for r in recs}
        ids_db = {r[0] for r in c.execute("SELECT definition_id FROM term_definition")}
        out["terminology_file_vs_db"] = {
            "file": len(ids_file),
            "db": len(ids_db),
            "in_file_not_db": len(ids_file - ids_db),
            "in_db_not_file": len(ids_db - ids_file),
        }

    c.close()
    emit("d17_mapping_definition_quality", out)


if __name__ == "__main__":
    main()
