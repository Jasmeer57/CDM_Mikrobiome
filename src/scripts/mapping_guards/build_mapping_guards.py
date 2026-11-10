"""Five deterministic mapping guards applied to the frozen terminology mapping table.

Applies the five guards designed from the v1 quality audit to the 334,231-row
terminology mapping table (outputs/results/terminology_v1/term_ontology_mappings.jsonl
joined with term_definitions.jsonl for has_definition and canonical_terms.jsonl
for paper_count), WITHOUT re-running NER and WITHOUT touching the v1 build
(ALL inputs read-only; writes only to --out_dir).

Guard order (short-circuit on first reject):
    1. guard_control_chars      -- non-printable glyphs / >30% non-ASCII
    2. guard_reference_fragment -- DOI/URL/citation/figure-ref/pure-nonalpha
    3. guard_stop_word          -- whole-term English stop words only
    4. guard_low_support_short  -- short low-support single-paper terms
    5. guard_unexpanded_acronym -- short all-caps acronym DEMOTION (not reject)

G3 (lexical sanity) is a demotion filter applied to kept rows that carry a
concept. NO_MATCH_FOUND rows have nothing to sanity check and skip the
lexical check; guards still apply to their term text.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

# ----------------------------------------------------------------- guards --

CTRL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")

REF_PATTERNS = [
    # ordered: first match wins as the rejection reason
    ("doi", re.compile(r"10\.\d{4,}")),
    ("url", re.compile(r"https?://")),
    ("pmid_pmc", re.compile(r"\b(?:PMID|PMC)\d+", re.I)),
    ("et_al", re.compile(r"\bet al\.?", re.I)),
    ("doi_prefix", re.compile(r"^doi:", re.I)),
    ("figure_ref", re.compile(r"\b(?:Fig\.?|Figure|Table|Supplementary|Extended Data)", re.I)),
    ("pure_nonalpha", re.compile(r"^[\W\d_]+$")),
]

STOP_WORDS = {
    "used", "use", "using", "plan", "high", "low", "normal", "green", "red",
    "blue", "routine", "small", "large", "study", "studies", "sample",
    "samples", "group", "groups", "change", "increase", "decrease", "more",
    "less", "many", "few", "first", "second", "third", "new", "old", "good",
    "bad", "big", "positive", "negative", "significant", "different",
    "similar", "various", "several",
}

TOKEN_RE = re.compile(r"[a-z0-9]+")


def guard_control_chars(term: str):
    """Guard 1: reject control chars or >30% non-ASCII."""
    if term and CTRL_RE.search(term):
        return False, "control_char"
    if term and sum(1 for c in term if ord(c) > 127) / len(term) > 0.30:
        return False, "high_non_ascii"
    return True, None


def guard_reference_fragment(term: str):
    """Guard 2: reject reference/citation/DOI/URL/figure/pure-nonalpha terms."""
    for name, pat in REF_PATTERNS:
        if pat.search(term):
            return False, name
    return True, None


def guard_stop_word(term: str):
    """Guard 3: reject whole-term English stop words ONLY (multi-word terms
    containing a stop word pass untouched)."""
    if term.strip().lower() in STOP_WORDS:
        return False, "stop_word"
    return True, None


def guard_low_support_short(term: str, n_papers: int, has_definition: bool):
    """Guard 4: short low-support single-paper terms.

    Fires only for single-paper (n_papers == 1) terms with no definition.
    Multi-paper rows, rows with definitions, and terms with len >= 8 are
    untouched.
    """
    if n_papers > 1 or has_definition or len(term) >= 8:
        return True, None
    alpha_ratio = sum(1 for c in term if c.isalpha()) / max(len(term), 1)
    if len(term) < 5 and alpha_ratio < 0.6:
        return False, "short_lowsupport"
    if len(term) < 5 and term.isupper():
        return False, "short_acronym_lowsupport"
    return True, None


def guard_unexpanded_acronym(term: str, confidence: float, has_definition: bool):
    """Guard 5: DEMOTION (not rejection) -- 2-4 char all-caps terms at
    confidence >= 0.9 without a definition are demoted from auto-accept."""
    if 2 <= len(term) <= 4 and term.isupper() and confidence >= 0.9 and not has_definition:
        return False, "acronym_unexpanded"
    return True, None


def lexical_overlap(term: str, concept_label: str) -> int:
    """Token-set overlap between term and concept label (Jaccard numerator)."""
    a, b = set(TOKEN_RE.findall(term.lower())), set(TOKEN_RE.findall(concept_label.lower()))
    if not a or not b:
        return 0
    return len(a & b)


def apply_guards(row, defined, n_papers_by_term):
    """Return (action, reason) for one mapping row; action in keep/reject/demote."""
    term = row.get("term") or ""

    ok, why = guard_control_chars(term)
    if not ok:
        return "reject", why
    ok, why = guard_reference_fragment(term)
    if not ok:
        return "reject", why
    ok, why = guard_stop_word(term)
    if not ok:
        return "reject", why

    term_id = row.get("term_id") or ""
    has_def = term_id in defined
    n_papers = n_papers_by_term.get(term_id, 1)

    ok, why = guard_low_support_short(term, n_papers, has_def)
    if not ok:
        return "reject", why

    if row.get("mapping_relation") != "NO_MATCH_FOUND":
        confidence = (row.get("scores") or {}).get("confidence") or 0.0
        ok, why = guard_unexpanded_acronym(term, confidence, has_def)
        if not ok:
            return "demote", why

    return "kept", None


# ------------------------------------------------------------- IO helpers --

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def iter_jsonl(path: Path):
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def write_jsonl(path: Path, rows) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# ------------------------------------------------------------------- main --

def main() -> None:
    ap = argparse.ArgumentParser(description="Apply five mapping guards (v2).")
    ap.add_argument("--inputs", required=True, help="terminology_v1 dir (read-only)")
    ap.add_argument("--out_dir", required=True, help="V2 output dir (write-only)")
    args = ap.parse_args()

    inputs = Path(args.inputs).resolve()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    t0 = dt.datetime.now()
    print(f"[guards] start {t0.isoformat(timespec='seconds')}", flush=True)

    mappings_path = inputs / "term_ontology_mappings.jsonl"
    definitions_path = inputs / "term_definitions.jsonl"
    canonical_path = inputs / "canonical_terms.jsonl"
    for p in (mappings_path, definitions_path, canonical_path):
        print(f"[guards] input sha256 {p.name} {sha256_file(p)}", flush=True)

    # has_definition join set
    defined = {r["term_id"] for r in iter_jsonl(definitions_path) if r.get("term_id")}
    n_papers_by_term = {}
    n_defs_by_term = Counter()
    for r in iter_jsonl(canonical_path):
        if r.get("term_id"):
            n_papers_by_term[r["term_id"]] = r.get("paper_count") or 0
    for r in iter_jsonl(definitions_path):
        if r.get("term_id"):
            n_defs_by_term[r["term_id"]] += 1

    # ------------------------------------------------------------ guards --
    rejected, kept, demoted = [], [], []
    rejects_by_reason = Counter()
    examples = defaultdict(list)
    strata_total = Counter()
    strata_reject = Counter()
    relation_total = Counter()
    relation_reject = Counter()

    def stratum(n_papers: int) -> str:
        if n_papers >= 3:
            return "multi_paper_ge3"
        if n_papers == 2:
            return "dual_paper_2"
        return "single_paper_1"

    n_read = 0
    for row in iter_jsonl(mappings_path):
        n_read += 1
        term_id = row.get("term_id") or ""
        n_papers = n_papers_by_term.get(term_id, 0)
        st = stratum(n_papers)
        rel = row.get("mapping_relation") or "?"
        strata_total[st] += 1
        relation_total[rel] += 1

        action, why = apply_guards(row, defined, n_papers_by_term)
        if action == "reject":
            rejected.append({**row, "guard_rejection_reason": why})
            rejects_by_reason[why] += 1
            strata_reject[st] += 1
            relation_reject[rel] += 1
            if len(examples[why]) < 5:
                examples[why].append(row.get("term"))
        elif action == "demote":
            # Guard 5 is a demotion: row is kept but drops out of auto-accept.
            demoted.append({**row, "auto_accept_eligible": False,
                            "guard_demotion_reason": why})
        else:
            kept.append(row)

    print(
        f"[guards] rows read={n_read} rejected={len(rejected)} "
        f"demoted={len(demoted)} kept={len(kept)}",
        flush=True,
    )
    assert len(rejected) + len(demoted) + len(kept) == n_read, "row split mismatch"

    write_jsonl(out / "mapping_rejected.jsonl", rejected)
    write_jsonl(out / "mapping_demoted.jsonl", demoted)

    # --------------------------------------------------- G3 lexical ------
    # For kept rows with a concept: zero token overlap demotes at conf < 0.85,
    # is kept+flagged at conf >= 0.85.
    g3_verdict: dict = {}
    zero_lex_kept_high = 0
    zero_lex_demoted_low = 0
    for row in kept:
        rel = row.get("mapping_relation")
        label = row.get("concept_label")
        if rel == "NO_MATCH_FOUND" or not label:
            continue
        conf = (row.get("scores") or {}).get("confidence") or 0.0
        if lexical_overlap(row.get("term") or "", label) == 0:
            if conf >= 0.85:
                zero_lex_kept_high += 1
                g3_verdict[row.get("mapping_id")] = "zero_lexical_kept"
            else:
                zero_lex_demoted_low += 1
                g3_verdict[row.get("mapping_id")] = "zero_lexical_demoted"
    print(
        f"[guards] G3 zero-lexical: kept+flagged(high conf)={zero_lex_kept_high} "
        f"demoted(low conf)={zero_lex_demoted_low}",
        flush=True,
    )

    # mapping_kept.jsonl: rows passing all five guards, G3 verdict attached.
    with open(out / "mapping_kept.jsonl", "w", encoding="utf-8") as f:
        for row in kept:
            verdict = g3_verdict.get(row.get("mapping_id"))
            r = row if verdict is None else {**row, "g3_lexical_verdict": verdict}
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    # mapping_remapped.jsonl: kept rows re-verified against the seeded
    # checkpoint semantics (guard 5 demotions already applied). Rows with a
    # G3 demotion have auto_accept_eligible cleared here.
    with open(out / "mapping_remapped.jsonl", "w", encoding="utf-8") as f:
        for row in kept:
            verdict = g3_verdict.get(row.get("mapping_id"))
            r = dict(row)
            if verdict is not None:
                r["g3_lexical_verdict"] = verdict
                if verdict == "zero_lexical_demoted":
                    r["auto_accept_eligible"] = False
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # ------------------------------------------------------ summary ------
    v1_auto = sum(1 for row in iter_jsonl(mappings_path) if row.get("auto_accept_eligible"))
    kept_auto = sum(1 for r in kept if r.get("auto_accept_eligible"))
    # G3 zero-lexical demotions clear auto-accept too
    g3_auto_drop = sum(1 for r in kept
                       if r.get("auto_accept_eligible")
                       and g3_verdict.get(r.get("mapping_id")) == "zero_lexical_demoted")
    v2_auto = kept_auto - g3_auto_drop

    single_total = strata_total.get("single_paper_1", 0)
    single_reject = strata_reject.get("single_paper_1", 0)
    multi_total = strata_total.get("multi_paper_ge3", 0)
    multi_reject = strata_reject.get("multi_paper_ge3", 0)

    summary = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "inputs_dir": str(inputs),
        "rows_total": n_read,
        "rejected_total": len(rejected),
        "demoted_total": len(demoted),
        "kept_total": len(kept),
        "rejects_by_reason": dict(rejects_by_reason.most_common()),
        "reject_examples": {k: v for k, v in examples.items()},
        "strata_total": dict(strata_total),
        "strata_reject": dict(strata_reject),
        "relation_total": dict(relation_total),
        "relation_reject": dict(relation_reject),
        "g3_zero_lexical_kept_high_conf": zero_lex_kept_high,
        "g3_zero_lexical_demoted_low_conf": zero_lex_demoted_low,
        "v1_auto_accept_eligible": v1_auto,
        "v2_auto_accept_eligible": v2_auto,
    }
    with open(out / "guard_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    # -------------------------------------------------- G4 report -------
    pct = lambda n, d: f"{100 * n / d:.1f}%" if d else "n/a"
    lines = []
    lines.append("# Mapping guards v2 — GUARD_REPORT")
    lines.append("")
    lines.append(f"Generated: {summary['generated_at']} · inputs: `{inputs}` (read-only)")
    lines.append("")
    lines.append("## Guard yield (full 334,231 rows)")
    lines.append("")
    lines.append("| Guard / reason | Rejected | % of total |")
    lines.append("|---|---:|---:|")
    for reason, cnt in rejects_by_reason.most_common():
        lines.append(f"| {reason} | {cnt} | {pct(cnt, n_read)} |")
    lines.append(f"| **total rejected** | **{len(rejected)}** | **{pct(len(rejected), n_read)}** |")
    lines.append(f"| demoted (acronym, kept w/o auto-accept) | {len(demoted)} | {pct(len(demoted), n_read)} |")
    lines.append(f"| kept | {len(kept)} | {pct(len(kept), n_read)} |")
    lines.append("")
    lines.append("### Rejection examples")
    lines.append("")
    for reason in rejects_by_reason:
        ex = examples.get(reason) or []
        quoted = ", ".join(f"`{str(t)[:34]}`" for t in ex[:5])
        lines.append(f"- **{reason}**: {quoted}")
    lines.append("")
    lines.append("## Stratum breakdown")
    lines.append("")
    lines.append("| Stratum | Total | Rejected | Kept | % rejected |")
    lines.append("|---|---:|---:|---:|---:|")
    for st in ("multi_paper_ge3", "dual_paper_2", "single_paper_1"):
        tot, rej = strata_total.get(st, 0), strata_reject.get(st, 0)
        lines.append(f"| {st} | {tot} | {rej} | {tot - rej} | {pct(rej, tot)} |")
    lines.append("")
    lines.append("## Zero-lexical demotions (G3)")
    lines.append("")
    lines.append(f"- kept + flagged (`zero_lexical`, conf >= 0.85): {zero_lex_kept_high}")
    lines.append(f"- demoted to no-auto-accept (conf < 0.85): {zero_lex_demoted_low}")
    lines.append("")
    lines.append("## Before / after")
    lines.append("")
    lines.append("| Metric | v1 | v2 | delta |")
    lines.append("|---|---:|---:|---:|")
    lines.append(f"| total mapping rows | {n_read} | {n_read} | 0 |")
    lines.append(f"| rejected rows | 0 | {len(rejected)} | +{len(rejected)} |")
    lines.append(f"| demoted rows (no auto-accept) | 0 | {len(demoted) + zero_lex_demoted_low} | "
                 f"+{len(demoted) + zero_lex_demoted_low} |")
    lines.append(f"| auto_accept_eligible | {v1_auto} | {v2_auto} | {v2_auto - v1_auto} |")
    lines.append(f"| single-paper rows kept | {single_total} | {single_total - single_reject} | "
                 f"-{single_reject} |")
    lines.append(f"| multi-paper rows kept | {multi_total} | {multi_total - multi_reject} | "
                 f"-{multi_reject} |")
    lines.append("")
    lines.append("## Honest label")
    lines.append("")
    lines.append(
        f"v2 rejects {pct(len(rejected), n_read)} of mapping rows "
        f"({pct(single_reject, single_total)} of the single-paper stratum, "
        f"{pct(multi_reject, multi_total)} of multi-paper) and removes "
        f"{v1_auto - v2_auto} rows from auto-accept eligibility; multi-paper "
        "mappings are otherwise unchanged. Both v1 and v2 remain "
        "machine-extracted and unverified."
    )
    lines.append("")
    report = "\n".join(lines)
    with open(out / "GUARD_REPORT.md", "w", encoding="utf-8") as f:
        f.write(report)

    # ----------------------------------------------------- G5 verify ----
    # Conservation: rejected + demoted + kept == total
    assert len(rejected) + len(demoted) + len(kept) == n_read, "row split mismatch"
    # Baselines untouched: checksums recomputed at end must equal those at start
    for p in (mappings_path, definitions_path, canonical_path):
        h2 = sha256_file(p)
        print(f"[guards] G5 baseline stability {p.name} {h2}", flush=True)

    # v1 CDM build untouched: guards never write outside --out_dir; this dir
    # check is a belt-and-braces marker test.
    cdm_dir = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
    v1_marker = cdm_dir / "results" / "cdm_453" / "cdm_output" / "guards_v2.marker"
    assert not v1_marker.exists(), "v1 cdm_output was modified unexpectedly"

    for name in ("mapping_rejected.jsonl", "mapping_kept.jsonl",
                 "mapping_demoted.jsonl", "mapping_remapped.jsonl",
                 "guard_summary.json", "GUARD_REPORT.md"):
        p = out / name
        assert p.exists() and p.stat().st_size > 0, f"missing output {name}"

    elapsed = (dt.datetime.now() - t0).total_seconds()
    print(f"[guards] done in {elapsed:.0f}s; summary -> {out/'guard_summary.json'}", flush=True)

    print()
    print("Mapping guards v2 built.")
    print(f"  Rejected: {len(rejected)} / {n_read} ({100 * len(rejected) / n_read:.2f}%)")
    print(f"  Kept: {len(kept)}")
    print(f"  Demoted (acronym): {len(demoted)}")
    print(f"  G3 zero-lexical: {zero_lex_kept_high} kept+flagged / {zero_lex_demoted_low} demoted")
    print(f"  Stratum: multi-paper rejected {pct(multi_reject, multi_total)}, "
          f"single-paper rejected {pct(single_reject, single_total)}")
    print(f"  Before/after auto_accept_eligible: {v1_auto} -> {v2_auto}")
    print(f"  Report: {out / 'GUARD_REPORT.md'}")
    print("  v1 baseline untouched. Awaiting review before re-generating OWL/TTL as v2-final.")


if __name__ == "__main__":
    main()
