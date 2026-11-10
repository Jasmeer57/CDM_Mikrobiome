"""D06 - structured-value grounding against the evidence sentence.

D05 tested whether the *evidence string* exists in the source section. D06 asks a
stricter question: does the *structured value* the catalogue asserts (a participant
count, a sample count, a platform name, a body site) actually appear in that
evidence text?

A value that cannot be found lexically may still be correct (derived by arithmetic
or normalisation), so failure here is a grounding gap, not proof of an error. The
converse is stronger: a value present in the text is at least lexically supported.

Read-only. Stdlib only.
"""

from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import connect, emit  # noqa: E402

OUT: dict = {"diagnostic": "d06_value_grounding", "db": "releases/cdm_v3/3.0.3"}

NUM_RE = re.compile(r"\d[\d,_]*(?:\.\d+)?")


def norm_num(s):
    try:
        return str(int(float(str(s).replace(",", "").replace("_", ""))))
    except Exception:
        return None


def numbers_in(text):
    """Normalised numeric tokens in a sentence (thousands separators stripped)."""
    out = set()
    for m in NUM_RE.finditer(text or ""):
        n = norm_num(m.group(0))
        if n:
            out.add(n)
    return out


def norm_text(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def contains_phrase(haystack_norm, needle):
    """Token-boundary phrase containment on normalised text."""
    n = norm_text(needle)
    if not n:
        return None
    return (" " + n + " ") in (" " + haystack_norm + " ")


def check_numeric(con, table, id_col, value_col, evidence_col, label,
                  also_evidence_location=False):
    """Does the asserted count appear as a number in the evidence text?"""
    have = {r[1] for r in con.execute(f'PRAGMA table_info("{table}")')}
    for c in (id_col, value_col, evidence_col):
        if c not in have:
            return {"table": table, "column": value_col, "error": f"missing {c}"}
    res = Counter()
    examples = []
    n = 0
    for rid, val, ev in con.execute(
        f'select "{id_col}", "{value_col}", "{evidence_col}" from "{table}"'
    ):
        n += 1
        if val is None or str(val).strip() == "":
            res["NO_VALUE"] += 1
            continue
        target = norm_num(val)
        if target is None:
            res["NON_NUMERIC_VALUE"] += 1
            continue
        if not (ev or "").strip():
            res["NO_EVIDENCE"] += 1
            continue
        nums = numbers_in(ev)
        if target in nums:
            res["VALUE_IN_EVIDENCE"] += 1
        else:
            res["VALUE_ABSENT_FROM_EVIDENCE"] += 1
            if len(examples) < 8:
                examples.append({"id": str(rid), "value": str(val)[:30],
                                 "evidence": ev[:150]})
    tot = n or 1
    return {
        "table": table, "column": value_col, "label": label, "rows": n,
        "outcomes": dict(res),
        "pct": {k: round(100.0 * c / tot, 3) for k, c in res.items()},
        "examples_value_absent": examples,
    }


def check_lexical(con, table, id_col, value_col, evidence_col, label):
    """Does a categorical/label value appear in the evidence text at all?"""
    have = {r[1] for r in con.execute(f'PRAGMA table_info("{table}")')}
    for c in (id_col, value_col, evidence_col):
        if c not in have:
            return {"table": table, "column": value_col, "error": f"missing {c}"}
    res = Counter()
    by_value = defaultdict(Counter)
    examples = []
    n = 0
    for rid, val, ev in con.execute(
        f'select "{id_col}", "{value_col}", "{evidence_col}" from "{table}"'
    ):
        n += 1
        if val is None or str(val).strip() == "":
            res["NO_VALUE"] += 1
            continue
        if not (ev or "").strip():
            res["NO_EVIDENCE"] += 1
            continue
        hit = contains_phrase(norm_text(ev), str(val))
        if hit is None:
            res["NON_LEXICAL_VALUE"] += 1
            continue
        if hit:
            res["VALUE_IN_EVIDENCE"] += 1
            by_value[str(val)[:40]]["in"] += 1
        else:
            res["VALUE_ABSENT_FROM_EVIDENCE"] += 1
            by_value[str(val)[:40]]["absent"] += 1
            if len(examples) < 8:
                examples.append({"id": str(rid), "value": str(val)[:50],
                                 "evidence": ev[:150]})
    tot = n or 1
    worst = []
    for v, c in by_value.items():
        t = c["in"] + c["absent"]
        if t >= 20:
            worst.append([v, t, round(100.0 * c["absent"] / t, 1)])
    worst.sort(key=lambda r: -r[2])
    return {
        "table": table, "column": value_col, "label": label, "rows": n,
        "outcomes": dict(res),
        "pct": {k: round(100.0 * c / tot, 3) for k, c in res.items()},
        "least_grounded_values": worst[:12],
        "examples_value_absent": examples,
    }


def evidence_length_profile(con):
    """Are evidence strings sentences, or are they whole sections / empty stubs?"""
    out = []
    for table, col in (("dataset", "evidence_text"), ("sample", "evidence_text"),
                       ("assay", "evidence_text"), ("cohort", "evidence_text"),
                       ("data_asset", "evidence_text"), ("claim", "evidence_text"),
                       ("term_definition", "evidence_text")):
        have = {r[1] for r in con.execute(f'PRAGMA table_info("{table}")')}
        if col not in have:
            continue
        lens = [len(r[0] or "") for r in con.execute(f'select "{col}" from "{table}"')]
        if not lens:
            continue
        lens_sorted = sorted(lens)
        n = len(lens_sorted)
        out.append({
            "table": table,
            "rows": n,
            "empty": sum(1 for x in lens if x == 0),
            "lt_20_chars": sum(1 for x in lens if 0 < x < 20),
            "median_chars": lens_sorted[n // 2],
            "p90_chars": lens_sorted[int(n * 0.9)],
            "max_chars": lens_sorted[-1],
            "over_2000_chars": sum(1 for x in lens if x > 2000),
        })
    return out


def claim_direction_support(con):
    """Does a directional claim have a directional cue in its evidence text?"""
    have = {r[1] for r in con.execute('PRAGMA table_info("claim")')}
    if "direction" not in have or "evidence_text" not in have:
        return {"error": "columns absent"}
    up = re.compile(r"\b(increas|higher|elevat|enrich|more abundant|greater|upregulat)", re.I)
    down = re.compile(r"\b(decreas|lower|reduc|deplet|less abundant|fewer|downregulat)", re.I)
    res = Counter()
    by_dir = defaultdict(Counter)
    for d, ev in con.execute('select direction, evidence_text from claim'):
        key = str(d)
        if not (ev or "").strip():
            res["NO_EVIDENCE"] += 1
            by_dir[key]["NO_EVIDENCE"] += 1
            continue
        u = bool(up.search(ev))
        dn = bool(down.search(ev))
        if u and dn:
            o = "BOTH_CUES"
        elif u:
            o = "UP_CUE"
        elif dn:
            o = "DOWN_CUE"
        else:
            o = "NO_CUE"
        res[o] += 1
        by_dir[key][o] += 1
    return {"outcomes": dict(res),
            "by_direction": {k: dict(v) for k, v in by_dir.items() if sum(v.values()) >= 50},
            "note": ("Direction is a model-inferred field; a missing cue means the "
                     "direction is not lexically recoverable from the stored sentence.")}


def main():
    con = connect()

    numeric = [
        check_numeric(con, "cohort", "cohort_id", "participant_count",
                      "evidence_text", "cohort.participant_count"),
        check_numeric(con, "cohort", "cohort_id", "sample_count",
                      "evidence_text", "cohort.sample_count"),
        check_numeric(con, "sample", "sample_group_id", "sample_count",
                      "evidence_text", "sample.sample_count"),
    ]
    lexical = [
        check_lexical(con, "assay", "assay_id", "sequencing_platform",
                      "evidence_text", "assay.sequencing_platform"),
        check_lexical(con, "assay", "assay_id", "target_gene_or_region",
                      "evidence_text", "assay.target_gene_or_region"),
        check_lexical(con, "cohort", "cohort_id", "country_or_region",
                      "evidence_text", "cohort.country_or_region"),
        check_lexical(con, "sample", "sample_group_id", "body_site_original",
                      "evidence_text", "sample.body_site_original"),
        check_lexical(con, "dataset", "dataset_id", "repository_name",
                      "evidence_text", "dataset.repository_name"),
        check_lexical(con, "dataset", "dataset_id", "repository_accession",
                      "evidence_text", "dataset.repository_accession"),
        check_lexical(con, "data_asset", "asset_id", "accession",
                      "evidence_text", "data_asset.accession"),
    ]
    OUT["numeric_grounding"] = numeric
    OUT["lexical_grounding"] = lexical
    OUT["evidence_length_profile"] = evidence_length_profile(con)
    OUT["claim_direction_support"] = claim_direction_support(con)

    # Normalised-value presence for body sites (the value is a controlled term,
    # but the normalised form should still be traceable).
    OUT["body_site_normalisation"] = {
        "sample_with_original": con.execute(
            "select count(*) from sample where body_site_original is not null "
            "and body_site_original <> ''").fetchone()[0],
        "sample_with_normalized": con.execute(
            "select count(*) from sample where body_site_normalized is not null "
            "and body_site_normalized <> ''").fetchone()[0],
        "sample_body_site_status": [[str(r[0]), r[1]] for r in con.execute(
            "select body_site_status, count(*) c from sample group by 1 order by c desc limit 8")],
        "distinct_original": con.execute(
            "select count(distinct body_site_original) from sample where body_site_original "
            "is not null and body_site_original <> ''").fetchone()[0],
        "distinct_normalized": con.execute(
            "select count(distinct body_site_normalized) from sample where "
            "body_site_normalized is not null and body_site_normalized <> ''").fetchone()[0],
        "distinct_with_ontology_id": con.execute(
            "select count(distinct body_site_ontology_id) from sample where "
            "body_site_ontology_id is not null and body_site_ontology_id <> ''").fetchone()[0],
    }

    print("=== numeric value grounding ===")
    for r in numeric:
        if "error" in r:
            print(f"  {r['table']}.{r['column']}: ERROR {r['error']}")
            continue
        print(f"  {r['label']:34s} rows={r['rows']:>6,} {r['pct']}")
    print("\n  examples where the asserted number is absent from the sentence:")
    for r in numeric:
        for e in r.get("examples_value_absent", [])[:2]:
            print(f"    [{r['label']}] value={e['value']} :: {e['evidence'][:90]}")

    print("\n=== lexical value grounding ===")
    for r in lexical:
        if "error" in r:
            print(f"  {r['table']}.{r['column']}: ERROR {r['error']}")
            continue
        print(f"  {r['label']:36s} rows={r['rows']:>6,} {r['pct']}")
    print("\n  least-grounded categorical values (n>=20):")
    for r in lexical:
        for w in r.get("least_grounded_values", [])[:4]:
            print(f"    [{r['label']}] {w[0]!r} n={w[1]} absent={w[2]}%")

    print("\n=== evidence length profile ===")
    for e in OUT["evidence_length_profile"]:
        print(f"  {e['table']:16s} rows={e['rows']:>7,} empty={e['empty']:>6,} "
              f"<20ch={e['lt_20_chars']:>6,} median={e['median_chars']:>5,} "
              f"p90={e['p90_chars']:>6,} >2000ch={e['over_2000_chars']:>5,} "
              f"max={e['max_chars']:,}")

    print("\n=== claim direction support ===")
    d = OUT["claim_direction_support"]
    print(f"  {d.get('outcomes')}")
    for k, v in (d.get("by_direction") or {}).items():
        print(f"   direction={k:16s} {v}")

    print("\n=== body site normalisation ===")
    for k, v in OUT["body_site_normalisation"].items():
        print(f"  {k}: {v}")

    emit("d06_value_grounding", OUT)


if __name__ == "__main__":
    main()
