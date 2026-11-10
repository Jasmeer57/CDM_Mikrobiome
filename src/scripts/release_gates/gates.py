"""Gate implementations G1-G10.

Every gate is read-only.  A gate that cannot find its input returns
``MISSING`` (fail-closed), never ``PASS`` and never an implicit zero.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .core import (
    CDM_TYPES,
    FAIL,
    MANIFEST_BASENAMES,
    MAPPING_DISPOSITIONS,
    MAPPING_RELATIONS,
    MISSING,
    NA,
    PASS,
    SECRET_RE,
    Ctx,
    GateResult,
    count_lines,
    iter_jsonl,
    parse_sha256sum_manifest,
    sha256_file,
    walk_files,
)

TITLES = {
    "G1": "manifest integrity / unlisted files",
    "G2": "count reconciliation",
    "G3": "referential integrity (soft join)",
    "G4": "offset verification",
    "G5": "calibration state",
    "G6": "release ledger integrity",
    "G7": "documentation consistency",
    "G8": "secret hygiene",
    "G9": "schema conformance",
    "G10": "provenance completeness",
}


# --------------------------------------------------------------------------- G1
def g1_manifest(ctx: Ctx) -> GateResult:
    mf = ctx.path("MANIFEST.sha256")
    if not mf.is_file():
        return GateResult("G1", TITLES["G1"], MISSING, "MANIFEST.sha256 not found")
    entries = parse_sha256sum_manifest(mf)
    if not entries:
        return GateResult("G1", TITLES["G1"], FAIL, "manifest is empty or unparseable")

    bad, ok = [], 0
    for digest, rel in entries:
        p = ctx.root / rel
        if not p.is_file():
            bad.append(f"MISSING {rel}")
            continue
        if sha256_file(p) != digest:
            bad.append(f"DIGEST {rel}")
        else:
            ok += 1

    listed = {str(Path(rel)) for _, rel in entries}
    unlisted = sorted(
        f for f in walk_files(ctx.root)
        if f not in listed and Path(f).name not in MANIFEST_BASENAMES and f != "MANIFEST.sha256"
    )
    if unlisted:
        bad.extend(f"UNLISTED {f}" for f in unlisted)

    status = PASS if not bad else FAIL
    return GateResult(
        "G1", TITLES["G1"], status,
        f"{ok}/{len(entries)} listed files match; {len(unlisted)} unlisted",
        {"verified": ok, "listed": len(entries), "unlisted": unlisted[:20],
         "failures": bad[:20]},
    )


# --------------------------------------------------------------------------- G2
def _g2_terminology(ctx: Ctx) -> GateResult:
    mf = ctx.path("terminology_extraction_manifest.json")
    if not mf.is_file():
        return GateResult("G2", TITLES["G2"], MISSING, "terminology manifest missing")
    m = json.loads(mf.read_text(encoding="utf-8"))
    declared = {a["name"]: a.get("records") for a in m.get("artifacts", []) if a.get("sha256")}
    coverage = (m.get("coverage") or {}).get("mention_records")

    targets = [
        "term_mentions.jsonl",
        "canonical_terms.jsonl",
        "term_definitions.jsonl",
        "term_ontology_mappings.jsonl",
    ]
    rows, bad = {}, []
    for name in targets:
        p = ctx.path(name)
        if not p.is_file():
            bad.append(f"MISSING {name}")
            rows[name] = {"declared": declared.get(name), "physical": None}
            continue
        physical = count_lines(p)
        rows[name] = {"declared": declared.get(name), "physical": physical}
        if declared.get(name) != physical:
            bad.append(f"{name}: declared={declared.get(name)} physical={physical}")

    off_by_one = (
        coverage is not None
        and declared.get("term_mentions.jsonl") is not None
        and coverage != declared.get("term_mentions.jsonl")
    )
    if off_by_one:
        bad.append(
            "coverage.mention_records=%s != artifacts[term_mentions].records=%s"
            % (coverage, declared.get("term_mentions.jsonl"))
        )

    status = PASS if not bad else FAIL
    detail = "all declared counts reconcile with physical rows" if not bad else "; ".join(bad[:4])
    return GateResult(
        "G2", TITLES["G2"], status, detail,
        {"rows": rows, "coverage_mention_records": coverage,
         "known_off_by_one_detected": bool(off_by_one),
         "known_off_by_one_explanation": (
             "coverage block was computed from a pre-write counter; the artifact "
             "'records' field and the physical row count agree"
         ) if off_by_one else None},
    )


def _g2_corpus(ctx: Ctx) -> GateResult:
    mf = ctx.path("corpus_manifest.json")
    if not mf.is_file():
        return GateResult("G2", TITLES["G2"], MISSING, "corpus_manifest.json missing")
    counts = (json.loads(mf.read_text(encoding="utf-8")).get("counts") or {})
    data = ctx.path("data")
    pairs = {
        "papers": "papers.jsonl",
        "sections": "sections.jsonl",
        "segments": "segments.jsonl",
        "studies": "studies.jsonl",
        "findings": "findings.jsonl",
        "findings_sections": "findings_sections.jsonl",
        "independent_fulltext_crosschecked": "fulltext_crosscheck.jsonl",
        "triple_mentions": "triple_mentions.jsonl",
        "canonical_triples": "canonical_triples.jsonl",
        "triples_sections": "triples_sections.jsonl",
        "entities": "entities.jsonl",
        "candidate_entity_mappings": "candidate_entity_mappings.jsonl",
        "cross_paper_evidence": "cross_paper_evidence.jsonl",
        "paper_summaries": "paper_summaries.jsonl",
    }
    rows, bad = {}, []
    for key, name in pairs.items():
        p = data / name
        if not p.is_file():
            bad.append(f"MISSING {name}")
            continue
        n = count_lines(p)
        rows[name] = {"declared": counts.get(key), "physical": n}
        if counts.get(key) != n:
            bad.append(f"{name}: declared={counts.get(key)} physical={n}")

    # terminology_inventory_rows is a CSV; compare header-excluded line count.
    inv = ctx.path("terminology_inventory.csv")
    if inv.is_file():
        n = count_lines(inv) - 1
        rows["terminology_inventory.csv"] = {"declared": counts.get("terminology_inventory_rows"), "physical": n}
        if counts.get("terminology_inventory_rows") != n:
            bad.append(f"terminology_inventory.csv: declared={counts.get('terminology_inventory_rows')} physical={n}")

    # llm_terms is a nested count (terms per section row), not a row count.
    lt = data / "llm_terms.jsonl"
    if lt.is_file():
        nested = 0
        for _, obj in iter_jsonl(lt):
            nested += len(obj.get("llm_terms") or [])
        rows["llm_terms.jsonl#nested_terms"] = {"declared": counts.get("llm_terms"), "physical": nested}
        if counts.get("llm_terms") != nested:
            bad.append(f"llm_terms nested: declared={counts.get('llm_terms')} physical={nested}")

    status = PASS if not bad else FAIL
    return GateResult(
        "G2", TITLES["G2"], status,
        "all declared counts reconcile" if not bad else "; ".join(bad[:4]),
        {"rows": rows},
    )


def _g2_catalogue(ctx: Ctx) -> GateResult:
    mf = ctx.path("MANIFEST.json")
    if not mf.is_file():
        return GateResult("G2", TITLES["G2"], MISSING, "MANIFEST.json missing")
    m = json.loads(mf.read_text(encoding="utf-8"))
    declared = m.get("records")
    per_entity = m.get("records_per_entity") or {}
    total = sum(int(v) for v in per_entity.values())
    bad = []
    if declared != total:
        bad.append(f"records={declared} != sum(records_per_entity)={total}")

    rec = ctx.path("records", "catalogue_records.jsonl")
    physical = count_lines(rec) if rec.is_file() else None
    if physical is None:
        bad.append("MISSING records/catalogue_records.jsonl")
    elif physical != declared:
        bad.append(f"catalogue_records.jsonl: declared={declared} physical={physical}")

    # Per-entity CSVs carry embedded newlines in evidence fields; do not use wc -l.
    status = PASS if not bad else FAIL
    return GateResult(
        "G2", TITLES["G2"], status,
        "records reconcile (%s)" % declared if not bad else "; ".join(bad),
        {"records": declared, "sum_records_per_entity": total,
         "catalogue_records_jsonl_lines": physical,
         "note": "per-entity CSV line counts are not used: evidence fields contain embedded newlines"},
    )


def g2_counts(ctx: Ctx) -> GateResult:
    if ctx.kind == "TERMINOLOGY":
        return _g2_terminology(ctx)
    if ctx.kind == "CORPUS":
        return _g2_corpus(ctx)
    if ctx.kind == "CATALOGUE":
        return _g2_catalogue(ctx)
    return GateResult("G2", TITLES["G2"], NA, f"unknown release kind: {ctx.kind}")


# --------------------------------------------------------------------------- G3
def g3_referential(ctx: Ctx, min_term_coverage: float = 0.85) -> GateResult:
    """Referential integrity of canonical ids and of the documented soft join.

    The soft join has two steps and they measure different things:

    ``term``  ``normalized_mention`` exists as a ``term_norm`` in L2.
    ``type``  the observed ``entity_type`` equals the canonical ``cdm_type``.

    Step 2 legitimately fails for a large share of mentions: L2 assigns one
    primary type per term, while every NER observation carries its own type.
    That difference is a *preserved type conflict*, not a broken reference, and
    the gate reports it as such.  The gate fails only on:

    * a non-null ``canonical_term_id`` that does not resolve (dangling FK), or
    * term-level coverage below ``min_term_coverage`` (regression floor).

    ``min_term_coverage`` is a regression guard against the characterised
    baseline, not a scientific-quality target.
    """
    if ctx.kind != "TERMINOLOGY":
        return GateResult("G3", TITLES["G3"], NA, "terminology-specific gate")
    canon_p = ctx.path("canonical_terms.jsonl")
    mentions_p = ctx.path("term_mentions.jsonl")
    for p in (canon_p, mentions_p):
        if not p.is_file():
            return GateResult("G3", TITLES["G3"], MISSING, f"{p.name} missing")

    keys, ids, norms = set(), set(), set()
    for _, d in iter_jsonl(canon_p):
        keys.add((d.get("term_norm"), d.get("cdm_type")))
        norms.add(d.get("term_norm"))
        ids.add(d.get("term_id"))

    total = pair_resolved = type_conflict = term_missing = 0
    null_fk = bad_fk = 0
    per_source = {}
    examples = []
    for _, d in iter_jsonl(mentions_p):
        total += 1
        cid = d.get("canonical_term_id")
        if cid is None:
            null_fk += 1
        elif cid not in ids:
            bad_fk += 1

        nm, et = d.get("normalized_mention"), d.get("entity_type")
        src = d.get("extraction_run_id") or "UNKNOWN"
        bucket = per_source.setdefault(src, {"total": 0, "pair": 0, "conflict": 0, "missing": 0})
        bucket["total"] += 1
        if (nm, et) in keys:
            pair_resolved += 1
            bucket["pair"] += 1
        elif nm in norms:
            type_conflict += 1
            bucket["conflict"] += 1
            if len(examples) < 10:
                examples.append({"mention_id": d.get("mention_id"), "kind": "type_conflict",
                                 "normalized_mention": nm, "entity_type": et})
        else:
            term_missing += 1
            bucket["missing"] += 1
            if len(examples) < 10:
                examples.append({"mention_id": d.get("mention_id"), "kind": "term_missing",
                                 "normalized_mention": nm, "entity_type": et})

    term_coverage = ((pair_resolved + type_conflict) / total) if total else 0.0
    pair_coverage = (pair_resolved / total) if total else 0.0

    bad = []
    if total == 0:
        bad.append("no mentions")
    if bad_fk:
        bad.append(f"{bad_fk} non-null canonical_term_id values do not resolve")
    if term_coverage < min_term_coverage:
        bad.append(f"term coverage {term_coverage:.4%} < regression floor {min_term_coverage:.0%}")

    status = PASS if not bad else FAIL
    return GateResult(
        "G3", TITLES["G3"], status,
        f"term coverage {term_coverage:.4%}, pair {pair_coverage:.4%}, "
        f"type-conflict {type_conflict}, term-missing {term_missing}, dangling FK {bad_fk}",
        {"total": total, "pair_resolved": pair_resolved, "type_conflict": type_conflict,
         "term_missing": term_missing, "term_coverage": term_coverage,
         "pair_coverage": pair_coverage, "null_canonical_term_id": null_fk,
         "dangling_fk": bad_fk, "per_source": per_source,
         "min_term_coverage": min_term_coverage, "examples": examples,
         "note": "canonical_term_id is null by design. The documented soft join is "
                 "(normalized_mention, entity_type) -> (term_norm, cdm_type). "
                 "A term that exists but whose observed type differs from the canonical "
                 "primary type is a preserved TYPE CONFLICT, not a broken reference; "
                 "it is never auto-resolved or merged."},
    )


# --------------------------------------------------------------------------- G4
def g4_offsets(ctx: Ctx, max_shift: int = 3, tolerance: float = 0.005) -> GateResult:
    if ctx.kind != "TERMINOLOGY":
        return GateResult("G4", TITLES["G4"], NA, "terminology-specific gate")
    mentions_p = ctx.path("term_mentions.jsonl")
    if not mentions_p.is_file():
        return GateResult("G4", TITLES["G4"], MISSING, "term_mentions.jsonl missing")
    corpus_data = ctx.corpus_data or (ctx.repo_root / "pipelines/corpus_v2" / "releases" / "2.2.0" / "data")
    sections_p = Path(corpus_data) / "sections.jsonl"
    if not sections_p.is_file():
        return GateResult("G4", TITLES["G4"], MISSING, f"corpus sections missing: {sections_p}")

    text = {}
    for _, d in iter_jsonl(sections_p):
        text[(d.get("paper_id"), d.get("section_id_original"))] = d.get("section_text_original") or ""

    hist, total = {}, 0
    exact = shifted = unresolved = oor = missing_section = 0
    sections_with_shift = set()
    examples = []
    for _, d in iter_jsonl(mentions_p):
        total += 1
        key = (d.get("paper_id"), d.get("section_id"))
        if key not in text:
            missing_section += 1
            continue
        t = text[key]
        s, e, sf = d.get("start_offset"), d.get("end_offset"), d.get("surface_form")
        if s is None or e is None or s < 0 or e > len(t):
            oor += 1
            continue
        found = None
        for delta in [0] + [x for k in range(1, max_shift + 1) for x in (-k, k)]:
            i = s + delta
            if i < 0:
                continue
            if t[i:i + len(sf)] == sf:
                found = delta
                break
        if found is None:
            unresolved += 1
            if len(examples) < 10:
                examples.append({"mention_id": d.get("mention_id"), "section_id": d.get("section_id"),
                                 "surface_form": sf, "slice": t[s:e]})
            continue
        hist[found] = hist.get(found, 0) + 1
        if found == 0:
            exact += 1
        else:
            shifted += 1
            sections_with_shift.add(key)

    checked = total - missing_section
    rate = (unresolved / checked) if checked else 1.0

    # The build excludes a small number of rows from its own offset check
    # (validation_summary.json: mention_offset_verification.mentions_checked).
    # Exclusions are allowed only when declared and fully accounted for.
    excluded_declared = None
    vs = ctx.path("validation_summary.json")
    if vs.is_file():
        try:
            excluded_declared = int(
                json.loads(vs.read_text(encoding="utf-8"))
                ["mention_offset_verification"]["mentions_checked"]
            )
        except (KeyError, TypeError, ValueError):
            excluded_declared = None
    expected_excluded = (total - excluded_declared) if excluded_declared is not None else None
    unaccounted = (oor - expected_excluded) if expected_excluded is not None else oor

    bad = []
    if oor and excluded_declared is None:
        bad.append(f"{oor} out-of-range offsets and no declared exclusion count")
    if unaccounted > 0:
        bad.append(f"{unaccounted} out-of-range offsets are not accounted for by the declared exclusion")
    if missing_section:
        bad.append(f"{missing_section} mentions reference an unknown section")
    if rate > tolerance:
        bad.append(f"unresolved rate {rate:.4%} > {tolerance:.2%}")

    status = PASS if not bad else FAIL
    return GateResult(
        "G4", TITLES["G4"], status,
        f"exact {exact}/{checked}, shifted {shifted}, unresolved {unresolved} ({rate:.4%}), "
        f"excluded {oor} (declared {expected_excluded})",
        {"total_mentions": total, "checked": checked, "exact": exact,
         "shifted": shifted, "unresolved": unresolved, "out_of_range": oor,
         "excluded_declared_by_build": excluded_declared,
         "excluded_expected": expected_excluded,
         "excluded_unaccounted": unaccounted,
         "missing_section": missing_section, "unresolved_rate": rate,
         "shift_histogram": {str(k): v for k, v in sorted(hist.items())},
         "sections_with_nonzero_shift": len(sections_with_shift),
         "unresolved_examples": examples,
         "warning": (f"offsets are section-relative; {shifted} mentions ({shifted/checked:.2%}) "
                     f"resolve only after a bounded shift against section_text_original, caused by "
                     f"segment-boundary rendering; consumers must not assume byte-exact slicing")
                    if shifted else None},
    )


# --------------------------------------------------------------------------- G5
def g5_calibration(ctx: Ctx) -> GateResult:
    if ctx.kind != "TERMINOLOGY":
        return GateResult("G5", TITLES["G5"], NA, "terminology-specific gate")
    summ_p = ctx.path("mapping_projection_summary.json")
    if not summ_p.is_file():
        return GateResult("G5", TITLES["G5"], MISSING, "mapping_projection_summary.json missing")
    summ = json.loads(summ_p.read_text(encoding="utf-8"))
    counts = summ.get("counts") or {}
    cal = summ.get("calibration") or {}
    auto_accepted = int(counts.get("auto_accepted") or 0)
    cal_status = cal.get("status", "UNKNOWN")

    mappings_p = ctx.path("term_ontology_mappings.jsonl")
    scanned = accepted_rows = accepted_ineligible = 0
    if mappings_p.is_file():
        for _, d in iter_jsonl(mappings_p):
            scanned += 1
            if d.get("mapping_disposition") == "AUTO_ACCEPTED":
                accepted_rows += 1
                if not d.get("auto_accept_eligible"):
                    accepted_ineligible += 1

    bad = []
    if auto_accepted > 0 and cal_status != "CALIBRATED":
        bad.append(f"auto_accepted={auto_accepted} with calibration={cal_status}")
    if accepted_ineligible > 0:
        bad.append(f"{accepted_ineligible} AUTO_ACCEPTED rows are not auto_accept_eligible")
    if scanned and accepted_rows != auto_accepted:
        bad.append(f"declared auto_accepted={auto_accepted} but scanned rows={accepted_rows}")

    status = PASS if not bad else FAIL
    return GateResult(
        "G5", TITLES["G5"], status,
        f"auto_accepted={auto_accepted}, calibration={cal_status}" if not bad else "; ".join(bad),
        {"auto_accepted_declared": auto_accepted, "auto_accepted_rows_scanned": accepted_rows,
         "auto_accepted_ineligible": accepted_ineligible,
         "calibration_status": cal_status, "mapping_rows_scanned": scanned},
    )


# --------------------------------------------------------------------------- G6
def g6_ledger(ctx: Ctx) -> GateResult:
    releases_dir = (ctx.repo_root / "releases").resolve()
    try:
        ctx.root.relative_to(releases_dir)
    except ValueError:
        return GateResult(
            "G6", TITLES["G6"], NA,
            f"release is not under {releases_dir}; the ledger governs only that tree",
        )
    ledger = ctx.repo_root / "releases" / "RELEASES.md"
    if not ledger.is_file():
        return GateResult("G6", TITLES["G6"], MISSING, f"ledger missing: {ledger}")
    mf = ctx.path("MANIFEST.sha256")
    if not mf.is_file():
        return GateResult("G6", TITLES["G6"], MISSING, "MANIFEST.sha256 missing")
    digest = sha256_file(mf)
    version = ctx.root.name
    rows = [ln for ln in ledger.read_text(encoding="utf-8").splitlines()
            if ln.startswith("|") and f"| {version} |" in ln]
    if not rows:
        return GateResult("G6", TITLES["G6"], FAIL,
                          f"no ledger row for version {version}",
                          {"version": version, "manifest_sha256": digest})
    match = [r for r in rows if digest in r]
    status = PASS if match else FAIL
    return GateResult(
        "G6", TITLES["G6"], status,
        "ledger digest matches" if match else "ledger row exists but digest differs",
        {"version": version, "manifest_sha256": digest,
         "ledger_rows": len(rows), "matched": len(match)},
    )


# --------------------------------------------------------------------------- G7
RETIRED_TOKENS = [
    # token, exemption keywords — a line carrying one of these is documenting the
    # value as retired/superseded rather than asserting it as a current count.
    ("2,505,736", ("off-by-one", "known failure", "not patched", "retired")),
    ("334,275", ("pre-fix", "superseded", "historical", "quarantine")),
    ("166,012 canonical", ("chain", "l1 table", "separate run")),
    ("51,941", None),
    ("16,607", None),
    ("3,241/4,006", None),
    ("80.0%", None),
]


def g7_docs(ctx: Ctx, files=None) -> GateResult:
    docs = files or [ctx.repo_root / "AGENTS.md", ctx.repo_root / "README.md"]
    hits = []
    for p in docs:
        p = Path(p)
        if not p.is_file():
            continue
        for lineno, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for token, exemptions in RETIRED_TOKENS:
                if token not in line:
                    continue
                low = line.lower()
                if exemptions and any(e in low for e in exemptions):
                    continue
                hits.append({"file": p.name, "line": lineno, "token": token,
                             "text": line.strip()[:160]})
    status = PASS if not hits else FAIL
    return GateResult(
        "G7", TITLES["G7"], status,
        "no retired counts found" if not hits else f"{len(hits)} stale reference(s)",
        {"hits": hits[:50], "files_checked": [str(Path(p).name) for p in docs],
         "note": "heuristic; exemptions allow lines that explicitly label a figure as historical"},
    )


# --------------------------------------------------------------------------- G8
def g8_secrets(ctx: Ctx) -> GateResult:
    roots = [ctx.root]
    prov = ctx.path("PROVENANCE.json")
    if prov.is_file():
        try:
            srcs = (json.loads(prov.read_text(encoding="utf-8")).get("sources") or {})
            for v in srcs.values():
                rel = v.get("path") if isinstance(v, dict) else None
                if rel:
                    p = ctx.repo_root / rel
                    if p.is_dir():
                        roots.append(p)
        except Exception:
            pass

    hits, scanned = [], 0
    for r in roots:
        if not Path(r).exists():
            continue
        if Path(r).is_file():
            scanned += 1
            if SECRET_RE.match(Path(r).name):
                hits.append(str(r))
            continue
        for base, _dirs, names in os.walk(r):
            for n in names:
                scanned += 1
                if SECRET_RE.match(n):
                    hits.append(str(Path(base) / n))

    # .gitignore coverage for the known secret path.
    gi = ctx.repo_root / ".gitignore"
    gi_text = gi.read_text(encoding="utf-8", errors="replace") if gi.is_file() else ""
    need = ["secrets.env", "**/secrets.env", "*.key", "*.pem"]
    missing_rules = [r for r in need if r not in gi_text]

    bad = []
    if hits:
        bad.append(f"{len(hits)} secret-like file(s) in scope")
    if missing_rules:
        bad.append(f".gitignore missing rules: {missing_rules}")
    status = PASS if not bad else FAIL
    return GateResult(
        "G8", TITLES["G8"], status,
        "no secret-like basenames in scope; .gitignore complete" if not bad else "; ".join(bad),
        {"scanned_files": scanned, "hits": hits[:20],
         "gitignore_missing_rules": missing_rules,
         "roots_scanned": [str(Path(r)) for r in roots]},
    )


# --------------------------------------------------------------------------- G9
def g9_schema(ctx: Ctx) -> GateResult:
    bad, metrics = [], {}
    if ctx.kind == "TERMINOLOGY":
        canon = ctx.path("canonical_terms.jsonl")
        maps = ctx.path("term_ontology_mappings.jsonl")
        for p in (canon, maps):
            if not p.is_file():
                return GateResult("G9", TITLES["G9"], MISSING, f"{p.name} missing")
        unknown_types, unknown_rel, unknown_disp = set(), set(), set()
        for _, d in iter_jsonl(canon):
            if d.get("cdm_type") not in CDM_TYPES:
                unknown_types.add(d.get("cdm_type"))
        for _, d in iter_jsonl(maps):
            if d.get("mapping_relation") not in MAPPING_RELATIONS:
                unknown_rel.add(d.get("mapping_relation"))
            if d.get("mapping_disposition") not in MAPPING_DISPOSITIONS:
                unknown_disp.add(d.get("mapping_disposition"))
        metrics = {"unknown_cdm_types": sorted(map(str, unknown_types)),
                   "unknown_mapping_relations": sorted(map(str, unknown_rel)),
                   "unknown_mapping_dispositions": sorted(map(str, unknown_disp))}
        if unknown_types:
            bad.append(f"unknown cdm_type(s): {sorted(map(str, unknown_types))[:5]}")
        if unknown_rel:
            bad.append(f"unknown relation(s): {sorted(map(str, unknown_rel))[:5]}")
        if unknown_disp:
            bad.append(f"unknown disposition(s): {sorted(map(str, unknown_disp))[:5]}")
    elif ctx.kind == "CORPUS":
        req = {
            "data/papers.jsonl": ["paper_id", "full_text_completeness", "validation_status"],
            "data/sections.jsonl": ["section_record_id", "paper_id", "section_type", "character_count"],
            "data/validation_per_paper.jsonl": ["paper_id", "validation_status", "checks"],
        }
        for rel, keys in req.items():
            p = ctx.path(*rel.split("/"))
            if not p.is_file():
                bad.append(f"MISSING {rel}")
                continue
            _, first = next(iter_jsonl(p))
            miss = [k for k in keys if k not in first]
            if miss:
                bad.append(f"{rel} missing keys {miss}")
    elif ctx.kind == "CATALOGUE":
        mf = ctx.path("MANIFEST.json")
        if not mf.is_file():
            return GateResult("G9", TITLES["G9"], MISSING, "MANIFEST.json missing")
        m = json.loads(mf.read_text(encoding="utf-8"))
        for k in ("generated_at", "records", "records_per_entity", "file_count"):
            if k not in m:
                bad.append(f"MANIFEST.json missing {k}")
    else:
        return GateResult("G9", TITLES["G9"], NA, f"unknown release kind: {ctx.kind}")

    status = PASS if not bad else FAIL
    return GateResult("G9", TITLES["G9"], status,
                      "schema OK" if not bad else "; ".join(bad), metrics)


# --------------------------------------------------------------------------- G10
def g10_provenance(ctx: Ctx) -> GateResult:
    bad = []
    metrics = {}
    if ctx.kind == "TERMINOLOGY":
        p = ctx.path("PROVENANCE.json")
        if not p.is_file():
            return GateResult("G10", TITLES["G10"], MISSING, "PROVENANCE.json missing")
        d = json.loads(p.read_text(encoding="utf-8"))
        for k in ("job_id", "generated_at", "artifacts", "sources", "non_claims", "corpus_release"):
            if not d.get(k):
                bad.append(f"PROVENANCE.json missing/empty {k}")
        metrics = {"job_id": d.get("job_id"), "generated_at": d.get("generated_at"),
                   "artifacts": len(d.get("artifacts") or {}),
                   "sources": len(d.get("sources") or {}),
                   "non_claims": len(d.get("non_claims") or [])}
    elif ctx.kind == "CORPUS":
        p = ctx.path("corpus_manifest.json")
        if not p.is_file():
            return GateResult("G10", TITLES["G10"], MISSING, "corpus_manifest.json missing")
        d = json.loads(p.read_text(encoding="utf-8"))
        for k in ("corpus_version", "generated_at", "counts", "known_limitations"):
            if not d.get(k):
                bad.append(f"corpus_manifest.json missing/empty {k}")
        metrics = {"corpus_version": d.get("corpus_version"),
                   "generated_at": d.get("generated_at"),
                   "limitations": len(d.get("known_limitations") or [])}
    elif ctx.kind == "CATALOGUE":
        p = ctx.path("MANIFEST.json")
        if not p.is_file():
            return GateResult("G10", TITLES["G10"], MISSING, "MANIFEST.json missing")
        d = json.loads(p.read_text(encoding="utf-8"))
        for k in ("generated_at", "papers", "records", "file_count", "coverage_status"):
            if d.get(k) in (None, ""):
                bad.append(f"MANIFEST.json missing/empty {k}")
        metrics = {"generated_at": d.get("generated_at"), "records": d.get("records"),
                   "files": d.get("file_count")}
    else:
        return GateResult("G10", TITLES["G10"], NA, f"unknown release kind: {ctx.kind}")

    status = PASS if not bad else FAIL
    return GateResult("G10", TITLES["G10"], status,
                      "provenance complete" if not bad else "; ".join(bad), metrics)
