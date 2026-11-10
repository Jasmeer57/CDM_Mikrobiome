"""D08 - triple assertion semantics: relation typing, direction, polarity, verdicts.

The CDM's 25,788 canonical triples are the most publication-facing product.
This diagnostic asks whether they carry a *typed, directional, asserted* relation,
and how much of the table is the escape bucket. It does not judge whether a triple
is scientifically true - no gold standard exists - it measures the internal
semantics that a consumer or reader would rely on.

Read-only. Stdlib only.
"""

from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import connect, emit  # noqa: E402

OUT: dict = {"diagnostic": "d08_triple_semantics", "db": "releases/cdm_v3/3.0.3"}

TEMPLATE_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")
NUMERIC_START_RE = re.compile(r"^\s*[-+]?[\d.,]+\s*$|^\s*\d")
MODEL_TOKEN_RE = re.compile(r"\b(model|regression|p-?value|ci\b|sem\b|sensitivity)", re.I)


def relation_typing(con):
    rows = con.execute(
        "select relation_family, relation_normalized, relation_id, "
        "relation_is_causal, relation_is_symmetric, count(*) c "
        "from relation group by 1,2,3,4,5 order by c desc"
    ).fetchall()
    total = con.execute("select count(*) from relation").fetchone()[0]
    fam = Counter()
    for r in rows:
        fam[str(r[0])] += r[5]
    escape = fam.get("escape", 0)
    templates = con.execute("select count(distinct relation_normalized) from relation").fetchone()[0]
    # one normalized template per row id?
    id_to_norm = con.execute(
        "select relation_id, count(distinct relation_normalized) from relation "
        "group by 1 having count(distinct relation_normalized) > 1"
    ).fetchall()
    return {
        "rows": total,
        "distinct_relation_id": con.execute(
            "select count(distinct relation_id) from relation").fetchone()[0],
        "distinct_relation_normalized": templates,
        "relation_id_to_normalized_is_1to1": len(id_to_norm) == 0,
        "by_family": dict(fam.most_common()),
        "escape_bucket": {
            "family": "escape",
            "template": "OTHER_RELATION",
            "rows": escape,
            "pct_of_triples": round(100.0 * escape / total, 3),
            "interpretation": (
                "A single untyped catch-all relation carries the majority of the "
                "table. The relation is therefore not informative for these rows: "
                "a consumer cannot distinguish 'causes' from 'measured by' from "
                "'numerically larger than'."
            ),
        },
        "top_relations": [[str(r[1]), str(r[0]), r[5]] for r in rows[:20]],
    }


def escape_profile(con):
    """What do the escape-bucket triples actually look like?"""
    total = con.execute("select count(*) from relation").fetchone()[0]
    esc = con.execute(
        "select count(*) from relation where relation_family='escape'").fetchone()[0]
    out = {"rows": esc, "pct_of_triples": round(100.0 * esc / total, 3)}

    out["quality_status"] = [[str(r[0]), r[1]] for r in con.execute(
        "select triple_quality_status, count(*) c from relation "
        "where relation_family='escape' group by 1 order by c desc")]
    out["verdict_deepseek"] = [[str(r[0]), r[1]] for r in con.execute(
        "select verdict_deepseek, count(*) c from relation "
        "where relation_family='escape' group by 1 order by c desc limit 10")]
    out["verdict_gemma_c4"] = [[str(r[0]), r[1]] for r in con.execute(
        "select verdict_gemma_c4, count(*) c from relation "
        "where relation_family='escape' group by 1 order by c desc limit 10")]
    out["assertion_agreement"] = [[str(r[0]), r[1]] for r in con.execute(
        "select assertion_agreement, count(*) c from relation "
        "where relation_family='escape' group by 1 order by c desc limit 6")]

    # Supported-by-LLM but flagged-needs-review: the contradiction that matters.
    both = con.execute(
        "select count(*) from relation where relation_family='escape' "
        "and verdict_deepseek='SUPPORTED' and triple_quality_status='flagged_needs_review'"
    ).fetchone()[0]
    out["escape_supported_but_flagged"] = both
    out["escape_supported_total"] = con.execute(
        "select count(*) from relation where relation_family='escape' "
        "and verdict_deepseek='SUPPORTED'").fetchone()[0]

    # Label plausibility heuristics - NOT truth judgments, just shape tests.
    labels = con.execute(
        "select subject_display_label, object_display_label from relation "
        "where relation_family='escape'").fetchall()
    numeric_subject = numeric_object = stub_subject = stub_object = 0
    method_like = 0
    examples = []
    for s, o in labels:
        s = (s or "").strip()
        o = (o or "").strip()
        if NUMERIC_START_RE.search(s):
            numeric_subject += 1
        if NUMERIC_START_RE.search(o):
            numeric_object += 1
        if len(s) < 3:
            stub_subject += 1
        if len(o) < 3:
            stub_object += 1
        if MODEL_TOKEN_RE.search(s) or MODEL_TOKEN_RE.search(o):
            method_like += 1
            if len(examples) < 8:
                examples.append([s[:70], o[:70]])
    out["subject_starts_numerically"] = numeric_subject
    out["object_starts_numerically"] = numeric_object
    out["subject_shorter_than_3_chars"] = stub_subject
    out["object_shorter_than_3_chars"] = stub_object
    out["mentions_statistical_or_model_terms"] = method_like
    out["examples_method_like"] = examples
    out["heuristic_caveat"] = (
        "These are surface-shape measurements. A numeric-looking subject is not "
        "automatically an error (e.g. '16S rRNA', '5-ASA'). They bound how many "
        "escape triples cannot be repaired by relabelling alone."
    )

    # Linkability: how many escape triples resolved to a canonical term?
    out["subject_term_link"] = [[str(r[0]), r[1]] for r in con.execute(
        "select subject_link_status, count(*) c from relation "
        "where relation_family='escape' group by 1 order by c desc")]
    out["object_term_link"] = [[str(r[0]), r[1]] for r in con.execute(
        "select object_link_status, count(*) c from relation "
        "where relation_family='escape' group by 1 order by c desc")]
    return out


def semantics_columns(con):
    """Assertion status, polarity, causality and symmetry across the whole table."""
    total = con.execute("select count(*) from relation").fetchone()[0]
    out = {"rows": total}
    for col in ("assertion_status_variants", "assertion_agreement",
                "polarity_variants", "polarity_agreement",
                "effect_direction_variants", "effect_direction_agreement",
                "relation_is_causal", "relation_is_symmetric",
                "evidence_locator_statuses", "evidence_verified_count",
                "evidence_unresolved_count"):
        have = {r[1] for r in con.execute('PRAGMA table_info("relation")')}
        if col not in have:
            out[col] = {"error": "absent"}
            continue
        d = [[str(r[0]), r[1]] for r in con.execute(
            f'select "{col}", count(*) c from relation group by 1 order by c desc limit 10')]
        out[col] = d
        if col.endswith("_variants"):
            # mixed-variant rows are the ones where the literature disagreed
            mixed = con.execute(
                f'select count(*) from relation where "{col}" like "%,%" '
                f'or ("{col}" like "[%," )').fetchone()[0]
            out[col + "_multi_valued_rows"] = mixed
    # Rows whose variants say both NEGATED and ASSERTED
    out["assertion_mixed_rows"] = con.execute(
        "select count(*) from relation where assertion_status_variants "
        "like '%ASSERTED%' and assertion_status_variants like '%NEGATED%'"
    ).fetchone()[0]
    out["polarity_mixed_rows"] = con.execute(
        "select count(*) from relation where polarity_variants "
        "like '%POSITIVE%' and polarity_variants like '%NEGATIVE%'"
    ).fetchone()[0]
    return out


def verdict_label_hygiene(con):
    """Model-judge label vocabularies on every table that stores one."""
    out = {}
    for table, col in (
        ("relation", "verdict_deepseek"),
        ("relation", "verdict_gemma_c4"),
        ("term_definition", "verdict_deepseek"),
        ("removed_relation", "verdict_deepseek"),
        ("removed_relation", "verdict_gemma_c4"),
    ):
        have = {r[1] for r in con.execute(f'PRAGMA table_info("{table}")')}
        if col not in have:
            continue
        d = [[str(r[0]), r[1]] for r in con.execute(
            f'select "{col}", count(*) c from "{table}" group by 1 order by c desc')]
        canonical = {"SUPPORTED", "PARTIAL", "NOT_SUPPORTED", "DEFINITION",
                     "MENTIONS", "WRONG_TERM", "PLAUSIBLE_BUT_WEAK", "SENSIBLE",
                     "NONSENSE", "UNCERTAIN", "UNKNOWN", "SUPPRESSED", "POSITIVE",
                     "NEGATIVE", "NOT_PROVIDED", "PARTIALLY_SUPPORTED"}
        suspects = [(v, n) for v, n in d if v not in canonical]
        out[f"{table}.{col}"] = {
            "distinct": len(d),
            "values": d,
            "off_vocabulary_values": suspects,
            "off_vocabulary_rows": sum(n for _, n in suspects),
            "pct_off_vocabulary": round(
                100.0 * sum(n for _, n in suspects) / max(1, sum(n for _, n in d)), 3),
        }
    return out


def judge_human_separation(con):
    """The CDM must not present model verdicts as human review."""
    out = {}
    out["human_review_rows"] = con.execute("select count(*) from human_review").fetchone()[0]
    out["relation_human_review_status"] = [[str(r[0]), r[1]] for r in con.execute(
        "select human_review_status, count(*) c from relation group by 1 order by c desc")]
    out["relation_verification_status"] = [[str(r[0]), r[1]] for r in con.execute(
        "select verification_status, count(*) c from relation group by 1 order by c desc")]
    out["relation_review_status"] = [[str(r[0]), r[1]] for r in con.execute(
        "select review_status, count(*) c from relation group by 1 order by c desc")]
    have = {r[1] for r in con.execute('PRAGMA table_info("canonical_term")')}
    if "review_status" in have:
        out["canonical_term_review_status"] = [[str(r[0]), r[1]] for r in con.execute(
            "select review_status, count(*) c from canonical_term group by 1 order by c desc")]
    have = {r[1] for r in con.execute('PRAGMA table_info("term_definition")')}
    if "review_status" in have:
        out["term_definition_review_status"] = [[str(r[0]), r[1]] for r in con.execute(
            "select review_status, count(*) c from term_definition group by 1 order by c desc")]
    return out


def evidence_rollups_on_triples(con):
    """Do the per-triple evidence counters reconcile with relation_evidence?"""
    declared_v = con.execute("select sum(evidence_verified_count) from relation").fetchone()[0] or 0
    declared_u = con.execute("select sum(evidence_unresolved_count) from relation").fetchone()[0] or 0
    actual = con.execute(
        "select count(*) from relation_evidence where relation_table='relation'").fetchone()[0]
    return {
        "relation.evidence_verified_count_sum": declared_v,
        "relation.evidence_unresolved_count_sum": declared_u,
        "declared_total": declared_v + declared_u,
        "relation_evidence_rows_for_relation": actual,
        "matches": (declared_v + declared_u) == actual,
        "note": (
            "relation_evidence also holds rows for removed_relation, so the "
            "relation-only slice must be compared, not the whole table."
        ),
    }


def main():
    con = connect()
    OUT["relation_typing"] = relation_typing(con)
    OUT["escape_bucket"] = escape_profile(con)
    OUT["semantics"] = semantics_columns(con)
    OUT["verdict_label_hygiene"] = verdict_label_hygiene(con)
    OUT["judge_vs_human"] = judge_human_separation(con)
    OUT["triple_evidence_rollup"] = evidence_rollups_on_triples(con)

    rt = OUT["relation_typing"]
    print("=== relation typing ===")
    print(f"  rows {rt['rows']:,}  templates {rt['distinct_relation_normalized']}  "
          f"id==normalized 1:1 {rt['relation_id_to_normalized_is_1to1']}")
    for k, v in rt["by_family"].items():
        print(f"   {k:24s} {v:>7,}  ({100.0*v/rt['rows']:.2f}%)")
    e = rt["escape_bucket"]
    print(f"  ESCAPE: {e['rows']:,} rows = {e['pct_of_triples']:.2f}% of all triples")

    eb = OUT["escape_bucket"]
    print(f"\n=== escape bucket profile ===")
    print(f"  quality_status {eb['quality_status']}")
    print(f"  deepseek      {eb['verdict_deepseek'][:6]}")
    print(f"  gemma         {eb['verdict_gemma_c4'][:5]}")
    print(f"  SUPPORTED yet flagged_needs_review: {eb['escape_supported_but_flagged']:,}"
          f" / SUPPORTED {eb['escape_supported_total']:,}")
    print(f"  subject starts numeric {eb['subject_starts_numerically']:,}  "
          f"object {eb['object_starts_numerically']:,}  "
          f"model/stat terms {eb['mentions_statistical_or_model_terms']:,}")
    print(f"  subject link {eb['subject_term_link']}  object {eb['object_term_link']}")

    s = OUT["semantics"]
    print(f"\n=== assertion / polarity ===")
    for k in ("assertion_status_variants", "assertion_agreement", "polarity_variants",
              "polarity_agreement", "effect_direction_variants", "relation_is_causal",
              "relation_is_symmetric"):
        print(f"  {k}: {s.get(k)}")
    print(f"  assertion mixed rows {s['assertion_mixed_rows']:,}  "
          f"polarity mixed rows {s['polarity_mixed_rows']:,}")

    print(f"\n=== verdict label hygiene ===")
    for k, v in OUT["verdict_label_hygiene"].items():
        print(f"  {k}: distinct={v['distinct']} off-vocab={v['off_vocabulary_rows']:,} "
              f"({v['pct_off_vocabulary']:.2f}%)")
        for val, n in v["off_vocabulary_values"][:12]:
            print(f"      {val!r} -> {n}")

    h = OUT["judge_vs_human"]
    print(f"\n=== judge vs human ===")
    print(f"  human_review rows: {h['human_review_rows']}")
    for k, v in h.items():
        if k != "human_review_rows":
            print(f"  {k}: {v[:4]}")

    print(f"\n=== triple evidence rollup ===")
    print(f"  {OUT['triple_evidence_rollup']}")

    emit("d08_triple_semantics", OUT)


if __name__ == "__main__":
    main()
