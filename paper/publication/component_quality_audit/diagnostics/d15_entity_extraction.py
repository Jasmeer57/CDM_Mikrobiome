"""D15 - entity mention extraction quality (component B).

Read-only. Audits the 2,505,684 term_mention rows across the four extraction
families (CPU NER ensemble, Qwen vLLM, Qwen Ollama, MeSH gazetteer) on
deterministic properties only: span exactness against the source text, surface
form plausibility, within-source duplication, cross-source type conflict,
source overlap/complementarity, and per-source error signatures.

No accuracy claim is made: there is no gold annotation for this corpus.
"""
from __future__ import annotations

import collections
import json
import re
import sqlite3

from common import DB, emit

# Extraction families. `extraction_model` is the live column.
FAMILY = {
    "en_core_sci_lg": "cpu_ensemble",
    "gliner_biomed": "cpu_ensemble",
    "gliner_medium": "cpu_ensemble",
    "en_ner_craft_md": "cpu_ensemble",
    "en_ner_bc5cdr_md": "cpu_ensemble",
    "en_ner_jnlpba_md": "cpu_ensemble",
    "biobert_diseases": "cpu_ensemble",
    "Qwen/Qwen3.5-4B": "qwen_vllm",
    "qwen3.5:4b": "qwen_ollama",
    "mesh-gazetteer": "mesh_gazetteer",
}

GENERIC = {
    "microbiota", "microbiome", "gut microbiota", "gut microbiome", "bacteria",
    "patients", "samples", "study", "data", "results", "analysis", "group",
    "species", "strain", "dna", "rna", "gene", "protein", "figure", "table",
}


def norm_ws(s):
    return " ".join((s or "").split())


def main():
    out = {}
    c = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    cols = [r[1] for r in c.execute("PRAGMA table_info(term_mention)")]
    for need in ("surface_form", "start_offset", "end_offset", "extraction_model",
                 "entity_type", "paper_id", "section_id", "canonical_term_id",
                 "offset_status", "term_link_status"):
        assert need in cols, "missing column %s" % need
    out["columns"] = cols

    total = c.execute("SELECT COUNT(*) FROM term_mention").fetchone()[0]
    out["total_mentions"] = total

    out["by_model"] = dict(
        c.execute(
            "SELECT extraction_model, COUNT(*) FROM term_mention GROUP BY 1 ORDER BY 2 DESC"
        ).fetchall()
    )
    out["by_model_type"] = {
        "%s|%s" % (m, t): n
        for m, t, n in c.execute(
            "SELECT extraction_model, entity_type, COUNT(*) FROM term_mention "
            "GROUP BY 1,2 ORDER BY 3 DESC"
        ).fetchall()[:60]
    }
    out["offset_status"] = dict(
        c.execute("SELECT offset_status, COUNT(*) FROM term_mention GROUP BY 1 ORDER BY 2 DESC").fetchall()
    )
    out["term_link_status"] = dict(
        c.execute("SELECT term_link_status, COUNT(*) FROM term_mention GROUP BY 1 ORDER BY 2 DESC").fetchall()
    )

    # ---- 1. span exactness against the frozen section text -------------------
    # term_mention.section_id stores `section_id_original` (e.g. `sec_001`), which is
    # only unique within a paper -- key on (paper_id, section_id_original), exactly
    # as D01 does. (Joining on `section_record_id` yields zero matches: that form is
    # `HMPAPER_000001:sec:001`.)
    secno = {}
    for pid, sid, txt in c.execute(
        "SELECT paper_id, section_id_original, section_text_original FROM section"
    ):
        secno["%s|%s" % (pid, sid)] = txt or ""

    exact = mismatch = oor = nosection = len_diff = 0
    bad_examples = []
    per_model_ok = collections.Counter()
    per_model_n = collections.Counter()
    for m, pid, sid, st, en, surf in c.execute(
        "SELECT extraction_model, paper_id, section_id, start_offset, end_offset, "
        "surface_form FROM term_mention"
    ):
        per_model_n[m] += 1
        key = "%s|%s" % (pid, sid)
        txt = secno.get(key)
        if txt is None:
            nosection += 1
            continue
        if st is None or en is None:
            oor += 1
            continue
        if st < 0 or en > len(txt) or en <= st:
            oor += 1
            continue
        got = txt[st:en]
        if got == surf:
            exact += 1
            per_model_ok[m] += 1
        elif norm_ws(got) == norm_ws(surf):
            len_diff += 1
            per_model_ok[m] += 1
        else:
            mismatch += 1
            if len(bad_examples) < 15:
                bad_examples.append(
                    {"model": m, "section": key, "offsets": [st, en],
                     "surface": surf[:60], "text": got[:60]}
                )
    out["span_check"] = {
        "exact": exact,
        "whitespace_only_diff": len_diff,
        "mismatch": mismatch,
        "out_of_range_or_null": oor,
        "section_not_found": nosection,
        "checked": exact + len_diff + mismatch,
        "exact_pct": round(100.0 * (exact + len_diff) / max(1, exact + len_diff + mismatch + oor), 4),
        "mismatch_examples": bad_examples,
    }
    out["span_exact_pct_by_model"] = {
        m: round(100.0 * per_model_ok[m] / max(1, per_model_n[m]), 3)
        for m in sorted(per_model_n)
    }

    # ---- 2. surface-form plausibility ---------------------------------------
    surf_stats = collections.Counter()
    for m, s in c.execute("SELECT extraction_model, surface_form FROM term_mention"):
        t = s or ""
        if not t.strip():
            surf_stats["empty"] += 1
        if len(t) == 1:
            surf_stats["single_char"] += 1
        if len(t) > 200:
            surf_stats["over_200_chars"] += 1
        if t and t[0] in ",.;:)]}":
            surf_stats["leading_punct"] += 1
        if t and t[-1] in ",;:([{":
            surf_stats["trailing_punct"] += 1
        if t.strip().lower() in GENERIC:
            surf_stats["generic_surface"] += 1
        if re.fullmatch(r"[\d\s.,%+-]+", t.strip()):
            surf_stats["numeric_only"] += 1
        if re.fullmatch(r"[A-Z]{2,6}", t.strip()):
            surf_stats["all_caps_short"] += 1
        if "\x00" in t:
            surf_stats["contains_nul"] += 1
    out["surface_form_issues"] = dict(surf_stats)
    out["surface_form_issues_pct"] = {
        k: round(100.0 * v / max(1, total), 4) for k, v in surf_stats.items()
    }

    # ---- 3. within-source duplication ---------------------------------------
    out["duplicate_spans_within_model"] = {}
    for m, n, d in c.execute(
        "SELECT extraction_model, COUNT(*), COUNT(DISTINCT paper_id||'|'||section_id||'|'||"
        "start_offset||'|'||end_offset) FROM term_mention GROUP BY 1"
    ).fetchall():
        out["duplicate_spans_within_model"][m] = {
            "rows": n, "distinct_spans": d, "redundant": n - d,
            "redundant_pct": round(100.0 * (n - d) / max(1, n), 4),
        }
    # same surface repeated at same offsets but different type (type conflict within a model)
    out["same_span_multi_type_within_model"] = c.execute(
        "SELECT COUNT(*) FROM (SELECT extraction_model, paper_id, section_id, start_offset, "
        "end_offset FROM term_mention GROUP BY 1,2,3,4,5 HAVING COUNT(DISTINCT entity_type)>1)"
    ).fetchone()[0]

    # ---- 4. cross-source type conflict --------------------------------------
    out["cross_source_type_conflicts"] = c.execute(
        "SELECT COUNT(*) FROM (SELECT paper_id, section_id, start_offset, end_offset "
        "FROM term_mention GROUP BY 1,2,3,4 HAVING COUNT(DISTINCT entity_type)>1)"
    ).fetchone()[0]
    out["cross_source_span_agreement"] = c.execute(
        "SELECT COUNT(*) FROM (SELECT paper_id, section_id, start_offset, end_offset "
        "FROM term_mention GROUP BY 1,2,3,4)"
    ).fetchone()[0]

    # Per-pair span overlap on common sections.
    # Computed by hashing (paper, section, start, end) -> set of models in ONE pass
    # instead of a quadratic self-join (the join plan is a per-paper index scan of
    # 2.5M rows, i.e. ~1e10 comparisons, and does not terminate).
    span_models = collections.defaultdict(set)
    model_span_capable = collections.Counter()
    for m, pid, sid, st, en in c.execute(
        "SELECT extraction_model, paper_id, section_id, start_offset, end_offset "
        "FROM term_mention WHERE start_offset IS NOT NULL AND end_offset IS NOT NULL"
    ):
        span_models[("%s|%s|%s|%s" % (pid, sid, st, en))].add(m)
        model_span_capable[m] += 1
    pair_shared = collections.Counter()
    for models in span_models.values():
        if len(models) < 2:
            continue
        ordered = sorted(models)
        for i in range(len(ordered)):
            for j in range(i + 1, len(ordered)):
                pair_shared[(ordered[i], ordered[j])] += 1
    out["distinct_spans_global"] = len(span_models)
    out["spans_shared_by_2plus_models"] = sum(1 for v in span_models.values() if len(v) > 1)
    out["spans_shared_by_2plus_models_pct"] = round(
        100.0 * out["spans_shared_by_2plus_models"] / max(1, len(span_models)), 4
    )
    out["spans_exclusive_to_one_model"] = sum(1 for v in span_models.values() if len(v) == 1)
    out["span_overlap_by_model_pair"] = [
        {
            "model_a": a, "model_b": b, "shared_spans": n,
            "jaccard_vs_a": round(n / max(1, model_span_capable[a]), 4),
            "jaccard_vs_b": round(n / max(1, model_span_capable[b]), 4),
        }
        for (a, b), n in pair_shared.most_common(30)
    ]
    out["spans_per_model"] = dict(model_span_capable)
    del span_models, pair_shared

    # ---- 5. canonicalisation coverage per family ----------------------------
    out["canonical_link_by_model"] = {}
    for m, n, linked in c.execute(
        "SELECT extraction_model, COUNT(*), SUM(CASE WHEN canonical_term_id IS NOT NULL "
        "THEN 1 ELSE 0 END) FROM term_mention GROUP BY 1"
    ).fetchall():
        out["canonical_link_by_model"][m] = {
            "rows": n, "linked": linked,
            "linked_pct": round(100.0 * linked / max(1, n), 3),
        }
    out["canonical_link_by_family"] = {}
    for m, n, linked in c.execute(
        "SELECT extraction_model, COUNT(*), SUM(CASE WHEN canonical_term_id IS NOT NULL "
        "THEN 1 ELSE 0 END) FROM term_mention GROUP BY 1"
    ).fetchall():
        f = FAMILY.get(m, "other")
        a = out["canonical_link_by_family"].setdefault(f, {"rows": 0, "linked": 0})
        a["rows"] += n
        a["linked"] += linked or 0
    for f, a in out["canonical_link_by_family"].items():
        a["linked_pct"] = round(100.0 * a["linked"] / max(1, a["rows"]), 3)

    # ---- 6. per-source error signatures -------------------------------------
    sig = {}
    for m in sorted(out["by_model"]):
        r = c.execute(
            "SELECT COUNT(*), SUM(LENGTH(surface_form)), AVG(LENGTH(surface_form)), "
            "SUM(CASE WHEN LENGTH(surface_form)<=2 THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN LENGTH(surface_form)>=40 THEN 1 ELSE 0 END) "
            "FROM term_mention WHERE extraction_model=?", (m,)
        ).fetchone()
        n, tot, avg, short, long_ = r
        sig[m] = {
            "rows": n,
            "mean_surface_chars": round(avg or 0, 2),
            "short_le2_pct": round(100.0 * (short or 0) / max(1, n), 3),
            "long_ge40_pct": round(100.0 * (long_ or 0) / max(1, n), 3),
            "distinct_surfaces": c.execute(
                "SELECT COUNT(DISTINCT surface_form) FROM term_mention WHERE extraction_model=?",
                (m,),
            ).fetchone()[0],
        }
        sig[m]["type_entropy_types"] = c.execute(
            "SELECT COUNT(DISTINCT entity_type) FROM term_mention WHERE extraction_model=?",
            (m,),
        ).fetchone()[0]
    out["error_signature"] = sig

    # ---- 7. section coverage per family -------------------------------------
    out["sections_covered_by_family"] = {}
    fam_rows = collections.defaultdict(set)
    for m, pid, sid in c.execute(
        "SELECT extraction_model, paper_id, section_id FROM term_mention"
    ):
        fam_rows[FAMILY.get(m, "other")].add("%s|%s" % (pid, sid))
    body = c.execute(
        "SELECT COUNT(*) FROM section WHERE section_type!='Other' OR LENGTH(section_text_original)>0"
    ).fetchone()[0]
    for f, s in fam_rows.items():
        out["sections_covered_by_family"][f] = {
            "sections_with_mentions": len(s),
            "papers": len({x.split("|")[0] for x in s}),
        }
    out["sections_total"] = c.execute("SELECT COUNT(*) FROM section").fetchone()[0]

    emit("d15_entity_extraction", out)


if __name__ == "__main__":
    main()
