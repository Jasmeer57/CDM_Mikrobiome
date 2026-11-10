"""D04 - duplication and near-duplication across the frozen CDM 3.0.3.

Measures, per entity family:
  * exact duplicate groups on the table's natural key,
  * surface-form near-duplicates that survive as separate canonical rows,
  * ensemble mention duplication (same span counted once per model),
  * whether the DB carries any de-duplication bookkeeping for the family.

Read-only. No writes to the release. Stdlib only.
"""

from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import connect, emit, rows  # noqa: E402

OUT: dict = {"diagnostic": "d04_duplication", "db": "releases/cdm_v3/3.0.3"}


def natural_key_dups(con, table, cols, label, sample_limit=5, sentinels=None):
    """Count exact duplicate groups on a natural key (NULLs excluded).

    sentinels: value spellings that mean "no value" and must not be treated as a
    shared key. Without this, e.g. 34 datasets in one paper all 'NOT_REPORTED'
    look like 33 duplicates.
    """
    for c in cols:
        have = {r[1] for r in con.execute(f'PRAGMA table_info("{table}")')}
        if c not in have:
            return {"family": label, "table": table, "error": f"missing column {c}"}
    sel = ", ".join(f'"{c}"' for c in cols)
    notnull = " and ".join(f'"{c}" is not null and "{c}" <> \'\'' for c in cols)
    total_rows = con.execute(f'select count(*) from "{table}"').fetchone()[0]
    groups = 0
    extra = 0
    samples = []
    sentinel_rows = 0
    if sentinels:
        marks = ", ".join("?" for _ in sentinels)
        # Count rows whose key contains a sentinel spelling.
        clause = " or ".join(f'upper(trim("{c}")) in ({marks})' for c in cols)
        params = tuple(s.upper() for s in sentinels) * len(cols)
        sentinel_rows = con.execute(
            f'select count(*) from "{table}" where {notnull} and ({clause})', params
        ).fetchone()[0]
        # Exclude sentinel rows from the duplicate scan via Python-side filter.
        sql = (f'select {sel}, count(*) c from "{table}" where {notnull} '
               f'group by {sel} having c > 1')
        for r in con.execute(sql):
            key_vals = [str(v).strip().upper() for v in r[:-1]]
            if any(k in {s.upper() for s in sentinels} for k in key_vals):
                continue
            groups += 1
            extra += r[-1] - 1
            if len(samples) < sample_limit:
                samples.append({c: str(v)[:70] for c, v in zip(cols, r[:-1])} | {"n": r[-1]})
    else:
        sql = (f'select {sel}, count(*) c from "{table}" where {notnull} '
               f'group by {sel} having c > 1')
        for r in con.execute(sql):
            groups += 1
            extra += r[-1] - 1
            if len(samples) < sample_limit:
                samples.append({c: str(v)[:70] for c, v in zip(cols, r[:-1])} | {"n": r[-1]})
    return {
        "family": label,
        "table": table,
        "key": list(cols),
        "rows": total_rows,
        "sentinel_keyed_rows_excluded": sentinel_rows,
        "duplicate_groups": groups,
        "redundant_rows": extra,
        "pct_rows_redundant": round(100.0 * extra / total_rows, 4) if total_rows else 0.0,
        "examples": samples,
    }


def surface_near_dups(con, limit=25):
    """Canonical terms that differ only by case / internal punctuation / spacing."""
    def squash(s):
        s = (s or "").lower()
        s = re.sub(r"[^a-z0-9]+", " ", s)
        return re.sub(r"\s+", " ", s).strip()

    buckets = defaultdict(list)
    for term_id, term, tnorm, cdm_type in con.execute(
        'select term_id, term, term_norm, cdm_type from canonical_term'
    ):
        buckets[squash(term)].append((term_id, term, cdm_type))

    groups = {k: v for k, v in buckets.items() if len(v) > 1 and k}
    redundant = sum(len(v) - 1 for v in groups.values())
    same_type = 0
    cross_type = 0
    examples = []
    for k, v in groups.items():
        types = {t for _, _, t in v}
        if len(types) == 1:
            same_type += 1
        else:
            cross_type += 1
        if len(examples) < limit:
            examples.append(
                {"squashed": k[:60], "variants": [t[:60] for _, t, _ in v][:4],
                 "types": sorted(types)[:4]}
            )
    total = con.execute("select count(*) from canonical_term").fetchone()[0]
    return {
        "family": "canonical_term surface near-duplicates",
        "rows": total,
        "groups": len(groups),
        "redundant_rows": redundant,
        "pct_rows_redundant": round(100.0 * redundant / total, 4),
        "groups_within_one_cdm_type": same_type,
        "groups_spanning_cdm_types": cross_type,
        "examples": examples,
    }


def mention_duplication(con):
    """Same span reported by several NER models - expected for an ensemble, but it
    inflates raw mention counts unless the consumer knows to collapse on the span."""
    have = {r[1] for r in con.execute('PRAGMA table_info("term_mention")')}
    # term_mention uses start_offset/end_offset, not char_start/char_end.
    key_cols = [c for c in ("paper_id", "section_id", "start_offset", "end_offset")
                if c in have]
    if len(key_cols) < 4:
        return {"error": f"term_mention lacks span columns; has {sorted(have)}"}
    sel = ", ".join(f'"{c}"' for c in key_cols)
    total = con.execute("select count(*) from term_mention").fetchone()[0]
    spans = con.execute(
        f'select count(*) from (select {sel} from term_mention group by {sel})'
    ).fetchone()[0]
    multi = con.execute(
        f"select count(*) from (select {sel}, count(*) c from term_mention "
        f"group by {sel} having c > 1)"
    ).fetchone()[0]
    # extraction_model, not model
    src = []
    for col in ("extraction_model", "extraction_method"):
        if col in have:
            src = [[str(r[0]), r[1]] for r in con.execute(
                f'select "{col}", count(*) c from term_mention group by 1 order by c desc')]
            break
    return {
        "family": "term_mention span-level duplication",
        "rows": total,
        "distinct_spans": spans,
        "spans_with_multiple_rows": multi,
        "redundant_rows_by_span_collapse": total - spans,
        "pct_rows_redundant": round(100.0 * (total - spans) / total, 4) if total else 0.0,
        "rows_by_model": src,
        "note": (
            "Rows are (model x span). Collapsing to distinct spans removes "
            "cross-model agreement rows; the CDM also stores term_occurrence "
            "with n_models to express that agreement explicitly."
        ),
    }


def dedup_bookkeeping(con):
    """Which families carry an explicit duplicate-group id, and is it populated?"""
    out = []
    for table in ("relation", "removed_relation", "canonical_term",
                  "removed_canonical_term", "claim", "dataset", "sample",
                  "assay", "cohort", "data_asset"):
        have = {r[1] for r in con.execute(f'PRAGMA table_info("{table}")')}
        if not have:
            continue
        row = {"table": table,
               "rows": con.execute(f'select count(*) from "{table}"').fetchone()[0]}
        if "duplicate_group_id" in have:
            n = con.execute(
                f'select count(*) from "{table}" where duplicate_group_id is not null '
                f'and duplicate_group_id <> ""'
            ).fetchone()[0]
            g = con.execute(
                f'select count(distinct duplicate_group_id) from "{table}" '
                f'where duplicate_group_id is not null and duplicate_group_id <> ""'
            ).fetchone()[0]
            row.update({"has_duplicate_group_id": True,
                        "populated": n,
                        "distinct_groups": g,
                        "groups_spanning_multiple_rows": g  # 1 row per group == no collapse
                        if n == g else None})
        else:
            row["has_duplicate_group_id"] = False
        if "merged_from" in have:
            n = con.execute(
                f'select count(*) from "{table}" where merged_from is not null '
                f'and merged_from <> ""'
            ).fetchone()[0]
            row["merged_from_populated"] = n
        out.append(row)
    return out


def relation_dup_groups(con):
    """129k-ish duplicate_group_id values on relation - do any group >1 row?"""
    have = {r[1] for r in con.execute('PRAGMA table_info("relation")')}
    if "duplicate_group_id" not in have:
        return {"error": "no duplicate_group_id"}
    g = con.execute(
        "select count(*) from (select duplicate_group_id from relation "
        "group by 1 having count(*) > 1)"
    ).fetchone()[0]
    tot = con.execute("select count(*) from relation").fetchone()[0]
    dist = con.execute("select count(distinct duplicate_group_id) from relation").fetchone()[0]
    return {
        "relation_rows": tot,
        "distinct_duplicate_group_id": dist,
        "groups_containing_more_than_one_row": g,
        "interpretation": (
            "duplicate_group_id is unique per row, so it records the group a triple "
            "was canonicalised from, not a surviving duplicate cluster."
            if g == 0 else "real clusters present"
        ),
    }


def compendium_duplication(con):
    """Compendium tables are the largest in the DB; check their natural keys."""
    out = []
    for table, cols in (
        ("compendium_sample", ("sample_accession",)),
        ("compendium_sample_tag", ("sample_accession", "tag")),
        ("compendium_project", ("bioproject",)),
    ):
        have = {r[1] for r in con.execute(f'PRAGMA table_info("{table}")')}
        if not have:
            out.append({"table": table, "absent": True})
            continue
        usable = [c for c in cols if c in have]
        if not usable:
            out.append({"table": table, "columns": sorted(have), "note": "key cols absent"})
            continue
        out.append(natural_key_dups(con, table, usable, f"{table} natural key"))
    return out


SENTINEL_SPELLINGS = (
    "NOT_REPORTED", "NOT_REPORTED_IN_PAPER", "NONE", "NA", "N/A", "UNKNOWN",
    "UNSPECIFIED", "NOT_APPLICABLE", "NOT_STATED", "UNRESOLVED", "TBD",
    "PENDING", "NO_ACCESSION", "UNNAMED", "-", "NOT_AVAILABLE",
)


def sentinel_census(con):
    """Free-text fields where a placeholder token occupies a real-value slot.

    A consumer that groups by or joins on these columns silently treats every
    placeholder as one shared value.
    """
    candidates = [
        ("dataset", "repository_accession"),
        ("dataset", "repository_name"),
        ("dataset", "dataset_title"),
        ("dataset", "license_or_terms"),
        ("data_asset", "accession"),
        ("data_asset", "asset_name"),
        ("sample", "body_site"),
        ("sample", "sample_type"),
        ("cohort", "country_or_region"),
        ("assay", "sequencing_platform"),
        ("assay", "target_gene_or_region"),
        ("claim", "effect_estimate"),
        ("relation", "subject_ontology_id"),
        ("relation", "object_ontology_id"),
    ]
    marks = ", ".join("?" for _ in SENTINEL_SPELLINGS)
    params = tuple(SENTINEL_SPELLINGS)
    out = []
    for table, col in candidates:
        have = {r[1] for r in con.execute(f'PRAGMA table_info("{table}")')}
        if col not in have:
            continue
        total = con.execute(f'select count(*) from "{table}"').fetchone()[0]
        nulls = con.execute(
            f'select count(*) from "{table}" where "{col}" is null or trim("{col}")=\'\''
        ).fetchone()[0]
        sent = con.execute(
            f'select count(*) from "{table}" where upper(trim("{col}")) in ({marks})', params
        ).fetchone()[0]
        top = [[str(r[0])[:40], r[1]] for r in con.execute(
            f'select "{col}", count(*) c from "{table}" '
            f'where "{col}" is not null and trim("{col}")<>\'\' '
            f'group by 1 order by c desc limit 5')]
        out.append({
            "table": table, "column": col, "rows": total,
            "null_or_empty": nulls, "sentinel_valued": sent,
            "real_values": total - nulls - sent,
            "pct_sentinel_of_rows": round(100.0 * sent / total, 3) if total else 0.0,
            "top_values": top,
        })
    return out


def main():
    con = connect()

    families = []
    SENT = ("NOT_REPORTED", "NOT_REPORTED_IN_PAPER", "NONE", "NA", "N/A", "UNKNOWN",
            "UNSPECIFIED", "NOT_APPLICABLE", "NOT_STATED")
    for table, cols, label in (
        ("canonical_term", ("term_norm",), "canonical_term.term_norm"),
        ("canonical_term", ("term_norm", "cdm_type"), "canonical_term.term_norm+cdm_type"),
        ("removed_canonical_term", ("term_norm", "cdm_type"), "removed_canonical_term key"),
        ("term_definition", ("term_id", "definition_text"), "term_definition term+text"),
        ("term_concept_map", ("term_id", "concept_id"), "term_concept_map term+concept"),
        ("taxonomy_annotation", ("term_id",), "taxonomy_annotation.term_id"),
        ("type_harmonization", ("term", "context"), "type_harmonization term+context"),
        ("claim", ("paper_id", "finding_text"), "claim paper+finding_text"),
        ("dataset", ("paper_id", "repository_accession"), "dataset paper+accession"),
        ("sample", ("paper_id", "sample_group_id"), "sample group id"),
        ("assay", ("paper_id", "assay_id"), "assay id"),
        ("cohort", ("paper_id", "cohort_id"), "cohort id"),
        ("data_asset", ("paper_id", "accession"), "data_asset paper+accession"),
        ("relation", ("subject_normalized_label", "relation_normalized",
                      "object_normalized_label"), "relation S-P-O"),
        ("term_occurrence", ("paper_id", "section_id", "start_offset", "end_offset"),
         "term_occurrence span key"),
    ):
        sent = SENT if any("accession" in c for c in cols) else None
        families.append(natural_key_dups(con, table, cols, label, sentinels=sent))

    OUT["exact_duplicates"] = families
    OUT["surface_near_duplicates"] = surface_near_dups(con)
    OUT["mention_duplication"] = mention_duplication(con)
    OUT["dedup_bookkeeping"] = dedup_bookkeeping(con)
    OUT["relation_duplicate_groups"] = relation_dup_groups(con)
    OUT["compendium"] = compendium_duplication(con)
    OUT["sentinel_census"] = sentinel_census(con)

    # How much of the catalogue is folded vs retained - cross-check the clean report.
    OUT["catalogue_fold_visible_in_cdm"] = {
        "sample_merged_from": con.execute(
            'select count(*) from sample where merged_from is not null and merged_from <> ""'
        ).fetchone()[0],
        "cohort_merged_from": con.execute(
            'select count(*) from cohort where merged_from is not null and merged_from <> ""'
        ).fetchone()[0],
        "assay_merged_from": con.execute(
            'select count(*) from assay where merged_from is not null and merged_from <> ""'
        ).fetchone()[0],
        "dataset_merged_from": con.execute(
            'select count(*) from dataset where merged_from is not null and merged_from <> ""'
        ).fetchone()[0],
    }

    print("=== exact duplicates on natural keys ===")
    for f in families:
        if "error" in f:
            print(f"  {f['family']:44s} ERROR {f['error']}")
            continue
        print(f"  {f['family']:44s} rows={f['rows']:>8,} groups={f['duplicate_groups']:>6,} "
              f"redundant={f['redundant_rows']:>7,} ({f['pct_rows_redundant']:.3f}%)")

    nd = OUT["surface_near_duplicates"]
    print(f"\n=== canonical_term surface near-duplicates ===")
    print(f"  rows {nd['rows']:,}  groups {nd['groups']:,}  redundant {nd['redundant_rows']:,} "
          f"({nd['pct_rows_redundant']:.3f}%)")
    print(f"  same cdm_type {nd['groups_within_one_cdm_type']:,}  "
          f"cross-type {nd['groups_spanning_cdm_types']:,}")

    md = OUT["mention_duplication"]
    print(f"\n=== term_mention span duplication ===")
    print(f"  rows {md['rows']:,}  distinct spans {md['distinct_spans']:,}  "
          f"redundant {md['redundant_rows_by_span_collapse']:,} ({md['pct_rows_redundant']:.2f}%)")

    print(f"\n=== dedup bookkeeping ===")
    for b in OUT["dedup_bookkeeping"]:
        print(f"  {b['table']:24s} rows={b['rows']:>8,} dup_group_id={b.get('has_duplicate_group_id')} "
              f"populated={b.get('populated', '-')} distinct={b.get('distinct_groups', '-')} "
              f"merged_from={b.get('merged_from_populated', '-')}")

    print(f"\n=== relation duplicate groups ===")
    print(f"  {OUT['relation_duplicate_groups']}")

    print(f"\n=== compendium ===")
    for c in OUT["compendium"]:
        print(f"  {c}")

    print(f"\n=== sentinel-valued fields ===")
    for s in OUT["sentinel_census"]:
        print(f"  {s['table']}.{s['column']:26s} rows={s['rows']:>7,} null={s['null_or_empty']:>7,} "
              f"sentinel={s['sentinel_valued']:>6,} ({s['pct_sentinel_of_rows']:.2f}%) "
              f"real={s['real_values']:>7,}")

    print(f"\n=== merged_from visible in CDM ===")
    for k, v in OUT["catalogue_fold_visible_in_cdm"].items():
        print(f"  {k:24s} {v:,}")

    emit("d04_duplication", OUT)


if __name__ == "__main__":
    main()
