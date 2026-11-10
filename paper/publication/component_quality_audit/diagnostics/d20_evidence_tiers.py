"""D20 - evidence-tier audit for components G, J, K, L (benchmarks, KG,
cleaned layer, external references).

Read-only. This script does NOT compute accuracy. It audits the EVIDENCE
STRUCTURE of six existing result bundles so the four tiers stay separate:

  TIER 1  public gold standard        ner_fair_bench (BC5CDR/BioRED) - measures
                                      the NER MODEL on public data, never this
                                      corpus.
  TIER 2  external-reference grounding triple_reference_check, bugsigdb_comparison
                                      (reference coverage, not correctness).
  TIER 3  KG support                  kg_2026-11-04 (absence != incorrect).
  TIER 4  model-generated validity    llm_judge_deepseek_v4_flash, cleaned_layer
                                      (model opinion, never human validation).

For each bundle it records: manifest presence and verification, preregistration
commitment, denominator, what was actually scored, what was NOT scored, and any
scope statement that could be misread as corpus accuracy.
"""
from __future__ import annotations

import collections
import csv
import gzip
import hashlib
import json
import re

from common import REPO, emit

B = REPO / "outputs/results/benchmark"
KG = REPO / "outputs/results/kg_2026-11-04"
CLEAN = REPO / "outputs/results/cleaned_layer_deepseek"


def sha256_file(p, chunk=1 << 20):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        while True:
            b = fh.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def verify_manifest(d):
    """Return (entries, matches, mismatches, missing, extra_files)."""
    mf = d / "MANIFEST.sha256"
    if not mf.exists():
        return {"manifest": "ABSENT"}
    listed = {}
    for line in mf.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([0-9a-f]{64})\s+\*?(.+)$", line)
        if m:
            listed[m.group(2).strip()] = m.group(1)
    ok = bad = miss = 0
    mismatches = []
    for rel, want in listed.items():
        p = d / rel
        if not p.exists():
            miss += 1
            continue
        got = sha256_file(p)
        if got == want:
            ok += 1
        else:
            bad += 1
            if len(mismatches) < 8:
                mismatches.append(rel)
    on_disk = {
        str(p.relative_to(d))
        for p in d.rglob("*")
        if p.is_file() and p.name != "MANIFEST.sha256"
    }
    return {
        "manifest": "PRESENT",
        "entries": len(listed),
        "verified": ok,
        "mismatch": bad,
        "missing": miss,
        "mismatch_examples": mismatches,
        "files_on_disk": len(on_disk),
        "unlisted_on_disk": sorted(on_disk - set(listed))[:15],
        "unlisted_count": len(on_disk - set(listed)),
    }


def read_jsonl(p, limit=None):
    out = []
    if not p.exists():
        return out
    op = gzip.open if p.suffix == ".gz" else open
    with op(p, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                out.append({"_unparsed": line[:120]})
            if limit and len(out) >= limit:
                break
    return out


def md_headings(p, n=40):
    if not p.exists():
        return []
    out = []
    with open(p, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("#"):
                out.append(line.rstrip())
            if len(out) >= n:
                break
    return out


def scan_scope_language(p):
    """Find sentences that could be read as claiming corpus accuracy."""
    if not p.exists():
        return {}
    txt = p.read_text(encoding="utf-8", errors="replace")
    pats = {
        "accuracy": r"[^.]*\baccuracy\b[^.]*\.",
        "recall": r"[^.]*\brecall\b[^.]*\.",
        "f1": r"[^.]*\bF1\b[^.]*\.",
        "precision": r"[^.]*\bprecision\b[^.]*\.",
        "gold_standard": r"[^.]*gold[ -]standard[^.]*\.",
        "agreement": r"[^.]*\bagreement\b[^.]*\.",
        "not_accuracy_disclaimer": r"[^.]*(?:not|never|no)\s+(?:a\s+)?(?:measure\s+of\s+)?accuracy[^.]*\.",
    }
    out = {}
    for k, pat in pats.items():
        hits = re.findall(pat, txt, flags=re.I)
        out[k] = {"n": len(hits), "examples": [h.strip()[:220] for h in hits[:4]]}
    return out


def main():
    out = {}

    # ============ TIER 1: public gold standard (component I) ================
    t1 = {}
    fb = B / "ner_fair_bench"
    t1["bundle"] = str(fb)
    t1["exists"] = fb.exists()
    t1["manifest"] = verify_manifest(fb)
    fj = fb / "fair_ner_metrics.json"
    if fj.exists():
        d = json.loads(fj.read_text(encoding="utf-8"))
        t1["metrics_keys"] = sorted(d.keys()) if isinstance(d, dict) else "list"
        t1["metrics"] = d
    t1["headings"] = md_headings(fb / "FAIR_NER_BENCHMARK.md")
    t1["scope_language"] = scan_scope_language(fb / "FAIR_NER_BENCHMARK.md")
    # what datasets were used (denominator)
    preds = fb / "preds"
    if preds.exists():
        t1["pred_files"] = sorted(p.name for p in preds.rglob("*") if p.is_file())[:25]
    t1["tier_statement"] = (
        "public benchmark F1 measures the NER model on BC5CDR/BioRED; it is not "
        "evidence of accuracy on this corpus"
    )
    out["tier1_public_gold_standard"] = t1

    # ============ TIER 2: external-reference grounding (J, K) ===============
    t2 = {}
    for name, d in (
        ("triple_reference_check", B / "triple_reference_check_2026-11-03"),
        ("bugsigdb_comparison", B / "bugsigdb_comparison_2026-11-03"),
    ):
        e = {"path": str(d), "exists": d.exists()}
        e["manifest"] = verify_manifest(d)
        for f in ("summary.json",):
            p = d / f
            if p.exists():
                e["summary"] = json.loads(p.read_text(encoding="utf-8"))
        e["headings"] = md_headings(d / "REPORT.md")
        e["scope_language"] = scan_scope_language(d / "REPORT.md")
        items = read_jsonl(d / "items.jsonl")
        e["items_rows"] = len(items)
        if items:
            e["item_keys"] = sorted(items[0].keys())
            # verdict / status vocabulary
            for k in ("verdict", "status", "outcome", "result", "label", "match"):
                if k in items[0]:
                    e["by_%s" % k] = dict(
                        collections.Counter(str(i.get(k)) for i in items).most_common(15)
                    )
            e["items_sample"] = items[:2]
        e["preregistration"] = (d / "PREREGISTRATION.sha256").read_text(
            encoding="utf-8", errors="replace"
        ).strip()[:200] if (d / "PREREGISTRATION.sha256").exists() else "ABSENT"
        # does the bundle carry licence/attribution for the reference source?
        lic = [p.name for p in d.rglob("*") if "licen" in p.name.lower() or "attribut" in p.name.lower()]
        e["licence_files"] = lic
        t2[name] = e
    t2["tier_statement"] = (
        "reference coverage / grounding; absence from a reference resource is not "
        "evidence that a triple is incorrect"
    )
    out["tier2_external_reference"] = t2

    # ============ TIER 3: KG support (component J) =========================
    t3 = {"path": str(KG), "exists": KG.exists()}
    t3["manifest"] = verify_manifest(KG)
    ks = KG / "kg_stats.json"
    if ks.exists():
        t3["stats"] = json.loads(ks.read_text(encoding="utf-8"))
    t3["headings"] = md_headings(KG / "REPORT.md")
    t3["scope_language"] = scan_scope_language(KG / "REPORT.md")
    for sub in ("gold_kg_check", "evidence_check"):
        sd = KG / sub
        e = {"exists": sd.exists()}
        if sd.exists():
            e["files"] = sorted(p.name for p in sd.rglob("*") if p.is_file())[:20]
            for f in sd.glob("*.json"):
                try:
                    e[f.stem] = json.loads(f.read_text(encoding="utf-8"))
                except ValueError:
                    pass
            e["headings"] = md_headings(sd / "REPORT.md")
        t3[sub] = e
    # count nodes / edges without loading the graphml
    for f, key in (("nodes.csv.gz", "nodes"), ("edges.csv.gz", "edges")):
        p = KG / f
        if p.exists():
            n = 0
            with gzip.open(p, "rt", encoding="utf-8", errors="replace") as fh:
                for _ in fh:
                    n += 1
            t3["%s_lines_incl_header" % key] = n
    t3["tier_statement"] = (
        "KG support is a coverage statement; a triple absent from the KG is "
        "untested, not incorrect"
    )
    out["tier3_kg_support"] = t3

    # ============ TIER 4: model-generated validity (L, G) ==================
    t4 = {}
    lj = B / "llm_judge_deepseek_v4_flash"
    e = {"path": str(lj), "exists": lj.exists()}
    e["manifest"] = verify_manifest(lj)
    e["files"] = sorted(p.name for p in lj.rglob("*") if p.is_file())[:25] if lj.exists() else []
    for f in lj.glob("*.json") if lj.exists() else []:
        try:
            e[f.stem] = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            pass
    e["headings"] = md_headings(lj / "README.md") + md_headings(lj / "REPORT.md")
    e["scope_language"] = scan_scope_language(lj / "README.md") if (lj / "README.md").exists() else scan_scope_language(lj / "REPORT.md")
    t4["llm_judge"] = e

    cl = {"path": str(CLEAN), "exists": CLEAN.exists()}
    cl["manifest"] = verify_manifest(CLEAN)
    cl["headings"] = md_headings(CLEAN / "CLEANING_REPORT.md")
    cl["scope_language"] = scan_scope_language(CLEAN / "CLEANING_REPORT.md")
    rep = CLEAN / "CLEANING_REPORT.md"
    if rep.exists():
        cl["report_chars"] = len(rep.read_text(encoding="utf-8", errors="replace"))
    for f, kind in (("cleaned_terms.csv.gz", "terms"), ("cleaned_triples.csv.gz", "triples")):
        p = CLEAN / f
        if p.exists():
            with gzip.open(p, "rt", encoding="utf-8", errors="replace") as fh:
                rdr = csv.reader(fh)
                hdr = next(rdr, [])
                n = sum(1 for _ in rdr)
            cl["%s_rows" % kind] = n
            cl["%s_columns" % kind] = hdr
    rel = read_jsonl(CLEAN / "relabel.jsonl")
    cl["relabel_rows"] = len(rel)
    if rel:
        cl["relabel_keys"] = sorted(rel[0].keys())
        for k in ("new_label", "label", "verdict", "reason", "action"):
            if k in rel[0]:
                cl["relabel_by_%s" % k] = dict(
                    collections.Counter(str(r.get(k)) for r in rel).most_common(15)
                )
        cl["relabel_sample"] = rel[:2]
    t4["cleaned_layer"] = cl
    t4["tier_statement"] = (
        "model verdicts and model relabels are model output; no human annotation "
        "exists (human_review table is empty)"
    )
    out["tier4_model_generated"] = t4

    # ============ cross-cutting: does any bundle claim human review? ========
    human_claim = {}
    for label, d in [
        ("ner_fair_bench", fb),
        ("triple_reference", B / "triple_reference_check_2026-11-03"),
        ("bugsigdb", B / "bugsigdb_comparison_2026-11-03"),
        ("kg", KG),
        ("cleaned", CLEAN),
        ("llm_judge", lj),
    ]:
        txt = ""
        for p in d.rglob("*.md") if d.exists() else []:
            txt += p.read_text(encoding="utf-8", errors="replace")
        hits = re.findall(r"[^.]*\bhuman(?:ly)?\s+(?:annotat|review|curat|validat)[^.]*\.", txt, flags=re.I)
        human_claim[label] = {"n": len(hits), "examples": [h.strip()[:200] for h in hits[:3]]}
    out["human_validation_claims_scan"] = human_claim

    # ============ tier leakage detection ===================================
    # a tier-1/tier-2 number presented as corpus accuracy would be a leak
    leaks = []
    for label, d in [
        ("ner_fair_bench", fb),
        ("triple_reference", B / "triple_reference_check_2026-11-03"),
        ("bugsigdb", B / "bugsigdb_comparison_2026-11-03"),
        ("kg", KG),
        ("cleaned", CLEAN),
        ("llm_judge", lj),
    ]:
        if not d.exists():
            continue
        for p in d.rglob("*.md"):
            txt = p.read_text(encoding="utf-8", errors="replace")
            for m in re.finditer(
                r"[^.]*\b(?:corpus|CDM|extraction)\b[^.]{0,80}\b(?:accuracy|F1)\b[^.]*\.",
                txt, flags=re.I,
            ):
                s = m.group(0).strip()
                if re.search(r"\b(?:not|never|no|cannot|unable)\b", s, flags=re.I):
                    continue
                leaks.append({"bundle": label, "file": p.name, "sentence": s[:260]})
    out["potential_tier_leaks"] = leaks[:25]
    out["potential_tier_leak_count"] = len(leaks)

    emit("d20_evidence_tiers", out)


if __name__ == "__main__":
    main()
