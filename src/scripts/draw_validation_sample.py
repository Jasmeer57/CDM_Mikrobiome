"""Draw the deterministic human-validation sample for the frozen terminology release.

Design constraints
------------------
1. **No RNG.** Rows are ranked by ``sha256(seed|task|stratum|row_id)`` and the
   ``n`` smallest are kept.  Selection therefore depends only on the seed, the
   task, the stratum label, and the row id — reproducible on any machine, any
   Python version, in any iteration order.
2. **Labels are never clobbered.** If an output sheet already exists it is not
   rewritten.  ``--force`` rewrites only when every human column is still empty.
3. **Every stratum is representable.** Allocation is proportional with a floor,
   so a small-but-important stratum (e.g. ``ABBREVIATION_EXPANSION``, 126 rows)
   still appears in the sheet.
4. **Weights are explicit.** Each row carries ``stratum_population`` and
   ``sampling_weight = N_stratum / n_stratum`` so a reviewer can compute
   stratum-weighted estimates without re-deriving the design.

This replaces the quarantined ``calibration_v0_pre_fix`` sample, which was drawn
against the superseded 334,275-row mapping table.

Usage
-----
    python3 src/scripts/draw_validation_sample.py --out outputs/results/validation
    python3 src/scripts/draw_validation_sample.py --out outputs/results/validation --dry-run
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import heapq
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())

MENTIONS = ROOT / "outputs/results" / "terminology_v1" / "term_mentions.jsonl"
DEFINITIONS = ROOT / "outputs/results" / "terminology_v1" / "term_definitions.jsonl"
MAPPINGS = ROOT / "outputs/results" / "terminology_v1" / "term_ontology_mappings.jsonl"
CANONICAL = ROOT / "outputs/results" / "terminology_v1" / "canonical_terms.jsonl"
CATALOGUE = ROOT / "releases/data_catalogue" / "records" / "catalogue_records.jsonl"

DEFAULT_SEED = "20261026"
TARGETS = {"mentions": 400, "definitions": 200, "mappings": 300, "findings": 300}
MIN_PER_STRATUM = 20
MAX_PER_STRATUM = 120

# Human columns are appended empty.  A non-empty value in any of these means a
# reviewer has started working and the sheet must not be regenerated.
HUMAN_COLUMNS = [
    "reviewer_id", "review_round", "review_verdict", "review_confidence",
    "review_notes", "adjudicated_verdict", "adjudicator_notes",
]


def rel(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 22), b""):
            h.update(block)
    return h.hexdigest()


def rank_key(seed: str, task: str, stratum: str, row_id: str) -> str:
    return hashlib.sha256(f"{seed}\x1f{task}\x1f{stratum}\x1f{row_id}".encode()).hexdigest()


def allocate(populations: dict[str, int], total: int) -> dict[str, int]:
    """Capped proportional allocation (D'Hondt-style water-filling).

    Each stratum first receives ``MIN_PER_STRATUM`` (scaled down when there are
    more strata than can afford it), then single units are given to whichever
    stratum currently has the largest population-per-allocated-slot ratio.  This
    guarantees the realised total reaches ``total`` whenever the populations and
    ``MAX_PER_STRATUM`` allow it, and that no stratum is silently omitted.
    """
    if not populations:
        return {}
    n = len(populations)
    floor = min(MIN_PER_STRATUM, max(1, total // n))
    alloc = {s: min(floor, p) for s, p in populations.items()}

    while sum(alloc.values()) < total:
        cands = [s for s, p in populations.items() if alloc[s] < min(p, MAX_PER_STRATUM)]
        if not cands:
            break  # every stratum is either full or capped
        s = max(cands, key=lambda k: (populations[k] / (alloc[k] + 1), populations[k], k))
        alloc[s] += 1
    return alloc


def select(task: str, seed: str, rows, stratum_of, n_by_stratum: dict[str, int]):
    """Streaming selection: keep the n smallest rank keys per stratum.

    The third tuple element is a unique row index so the heap can never fall
    through to comparing the row dicts when two 64-bit rank prefixes collide.
    """
    heaps: dict[str, list] = defaultdict(list)
    for i, row in enumerate(rows):
        s = stratum_of(row)
        n = n_by_stratum.get(s, 0)
        if n <= 0:
            continue
        key = rank_key(seed, task, s, str(row["__row_id__"]))
        r = int(key[:16], 16)
        h = heaps[s]
        if len(h) < n:
            heapq.heappush(h, (-r, key, i, row))
        elif r < -h[0][0]:
            heapq.heapreplace(h, (-r, key, i, row))
    out = []
    for s, h in heaps.items():
        out.extend(t[3] for t in sorted(h, key=lambda t: t[1]))
    return out


def iter_jsonl(path: Path, id_field: str):
    """Yield rows with a unique, deterministic row key.

    ``mention_id`` / ``mapping_id`` are **not unique** in these artifacts (see
    ``docs/VALIDATION_PROTOCOL.md`` §2): they identify a span or a term-concept
    pair, not a physical row.  The row key therefore appends the line position,
    which is stable because the source files are frozen and hashed above.
    """
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            d = json.loads(line)
            base = d.get(id_field) or "NA"
            d["source_row"] = lineno
            d["row_uid"] = f"{base}#{lineno}"
            d["__row_id__"] = d["row_uid"]
            if d.get(id_field):
                yield d


# ---------------------------------------------------------------- task shapes
def task_mentions(seed):
    canon = {}
    with open(CANONICAL, encoding="utf-8") as fh:
        for line in fh:
            d = json.loads(line)
            canon.setdefault(d["term_norm"], d)

    def rows():
        for d in iter_jsonl(MENTIONS, "mention_id"):
            c = canon.get(d.get("normalized_mention") or "")
            d["candidate_canonical_term_id"] = c["term_id"] if c else ""
            d["candidate_canonical_type"] = c["cdm_type"] if c else ""
            yield d

    fields = ["row_uid", "source_row", "mention_id", "paper_id", "section_id", "surface_form",
              "normalized_mention",
              "entity_type", "start_offset", "end_offset", "extraction_run_id",
              "extraction_model", "candidate_canonical_term_id", "candidate_canonical_type",
              "supporting_sentence"]
    return rows, (lambda d: d.get("entity_type") or "UNKNOWN"), fields, "mention_id"


def task_definitions(seed):
    def rows():
        yield from iter_jsonl(DEFINITIONS, "definition_id")

    fields = ["row_uid", "source_row", "definition_id", "term", "term_norm", "defined_surface",
              "cdm_type",
              "definition_text", "definition_source", "definition_formality",
              "provenance_class", "paper_id", "section_id", "definition_char_start",
              "definition_char_end", "extraction_model"]
    return rows, (lambda d: d.get("definition_source") or "UNKNOWN"), fields, "definition_id"


def task_mappings(seed):
    # Rank vocabularies so the stratum label stays low-cardinality.
    top = Counter()
    with open(MAPPINGS, encoding="utf-8") as fh:
        for line in fh:
            d = json.loads(line)
            if d.get("ontology_name"):
                top[d["ontology_name"]] += 1
    keep = {v for v, _ in top.most_common(10)}

    def stratum(d):
        rel = d.get("mapping_relation") or "UNKNOWN"
        if rel != "EXACT_MATCH":
            return rel
        on = d.get("ontology_name")
        return f"EXACT_MATCH:{on if on in keep else 'OTHER_VOCAB'}"

    def rows():
        # UNRESOLVED rows carry no mapping_id at all (11,477 of them).  They are
        # still reviewable — "is there really no matching concept?" — so they are
        # identified by `row_uid`, which appends the stable line position.
        with open(MAPPINGS, encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                d = json.loads(line)
                real = d.get("mapping_id") or ""
                d["source_row"] = lineno
                d["row_uid"] = f"{real or 'NA'}#{lineno}"
                d["__row_id__"] = d["row_uid"]
                d["mapping_id"] = real
                yield d

    fields = ["row_uid", "source_row", "mapping_id", "term", "term_norm", "cdm_type",
              "ontology_name", "concept_id", "concept_label", "standard_concept_id",
              "standard_concept_label", "mapping_relation", "mapping_disposition",
              "auto_accept_eligible", "auto_accept_ineligible_reason", "matched_via",
              "candidate_rank", "is_canonical_candidate", "source_service"]
    return rows, stratum, fields, "mapping_id"


def task_findings(seed):
    # `finding_domain` is free text (hundreds of bespoke values) and cannot
    # stratify.  `direction` is a small controlled vocabulary and is the axis a
    # reviewer actually adjudicates ("does the evidence support this direction?"),
    # so it is grouped to the 8 most common labels plus OTHER, crossed with the
    # machine's own evidence_verified flag.
    dir_counts = Counter()
    with open(CATALOGUE, encoding="utf-8") as fh:
        for line in fh:
            d = json.loads(line)
            if d.get("entity_type") != "findings":
                continue
            f = d.get("fields") or {}
            dir_counts[(f.get("direction") or "EMPTY")] += 1
    keep_dirs = {v for v, _ in dir_counts.most_common(8)}

    def rows():
        with open(CATALOGUE, encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                d = json.loads(line)
                if d.get("entity_type") != "findings":
                    continue
                f = d.get("fields") or {}
                direction = f.get("direction") or "EMPTY"
                rec = {
                    "__row_id__": f"{f.get('finding_id') or 'NA'}#{lineno}",
                    "row_uid": f"{f.get('finding_id') or 'NA'}#{lineno}",
                    "source_row": lineno,
                    "finding_id": f.get("finding_id", ""),
                    "paper_id": d.get("paper_id", ""),
                    "section_id": d.get("section_id", ""),
                    "section_path": d.get("section_path", ""),
                    "character_start": d.get("char_start"),
                    "character_end": d.get("char_end"),
                    "evidence_verified": d.get("evidence_verified"),
                    "finding_domain": f.get("finding_domain", ""),
                    "finding_text": f.get("finding_text", ""),
                    "evidence_text": f.get("evidence_text", ""),
                    "evidence_location": f.get("evidence_location", ""),
                    "direction": direction,
                    "direction_group": direction if direction in keep_dirs else "OTHER",
                    "taxon_or_feature": f.get("taxon_or_feature", ""),
                    "outcome": f.get("outcome", ""),
                    "effect_estimate": f.get("effect_estimate", ""),
                    "p_value": f.get("p_value", ""),
                }
                if rec["__row_id__"]:
                    yield rec

    def stratum(d):
        return f"direction={d['direction_group']}|verified={d['evidence_verified']}"

    fields = ["row_uid", "source_row", "finding_id", "paper_id", "section_id", "section_path",
              "finding_domain",
              "finding_text", "evidence_text", "evidence_location", "character_start",
              "character_end", "evidence_verified", "direction", "direction_group",
              "taxon_or_feature", "outcome", "effect_estimate", "p_value"]
    return rows, stratum, fields, "finding_id"


TASKS = {
    "mentions": task_mentions,
    "definitions": task_definitions,
    "mappings": task_mappings,
    "findings": task_findings,
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(ROOT / "outputs/results" / "validation"))
    ap.add_argument("--seed", default=DEFAULT_SEED)
    ap.add_argument("--target-total", type=int, default=None,
                    help="override the total sample size for every task")
    ap.add_argument("--force", action="store_true",
                    help="rewrite an existing sheet, but only if it has no review values")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    out = Path(args.out)
    out = (ROOT / out).resolve() if not out.is_absolute() else out.resolve()
    sheets = out / "sample_v1"
    if not args.dry_run:
        sheets.mkdir(parents=True, exist_ok=True)

    manifest = {
        "sample_version": "v1",
        "seed": args.seed,
        "selection": ("rows ranked by sha256(seed|task|stratum|row_id); the n smallest "
                      "per stratum are kept. No RNG is used."),
        "allocation": (f"proportional with a floor of {MIN_PER_STRATUM} per stratum, "
                       f"capped at {MAX_PER_STRATUM}; largest-remainder for the rest"),
        "weights": "sampling_weight = stratum_population / stratum_sample (inverse probability)",
        "human_columns": HUMAN_COLUMNS,
        "replaces": "releases/terminology/1.0.0/calibration_v0_pre_fix/ (drawn against 334,275 rows)",
        "inputs": {},
        "tasks": {},
    }
    for p in (MENTIONS, DEFINITIONS, MAPPINGS, CANONICAL, CATALOGUE):
        manifest["inputs"][p.name] = {"path": str(p.relative_to(ROOT)), "sha256": sha256_file(p)}

    rc = 0
    for task, factory in TASKS.items():
        rows, stratum_of, fields, id_field = factory(args.seed)

        # Pass 1 — population per stratum.
        populations = Counter()
        for d in rows():
            populations[stratum_of(d)] += 1

        total = args.target_total or TARGETS[task]
        alloc = allocate(dict(populations), total)

        # Pass 2 — deterministic selection.
        rows, stratum_of, fields, id_field = factory(args.seed)
        picked = select(task, args.seed, rows(), stratum_of, alloc)

        name = f"{task}.csv"
        dest = sheets / name
        header = fields + ["stratum", "stratum_population", "stratum_sample",
                           "sampling_weight"] + HUMAN_COLUMNS

        if dest.exists() and not args.force:
            print(f"  {task:12} SKIPPED_EXISTING  {dest.relative_to(ROOT)}")
            manifest["tasks"][task] = {"status": "SKIPPED_EXISTING", "path": rel(dest)}
            continue
        if dest.exists() and args.force:
            with open(dest, newline="", encoding="utf-8") as fh:
                existing = list(csv.DictReader(fh))
            filled = [r for r in existing
                      if any((r.get(c) or "").strip() for c in HUMAN_COLUMNS)]
            if filled:
                print(f"  {task:12} REFUSED_DIRTY    {len(filled)} row(s) already reviewed")
                manifest["tasks"][task] = {"status": "REFUSED_DIRTY", "reviewed_rows": len(filled)}
                rc = 2
                continue

        realised = Counter(stratum_of(d) for d in picked)
        if not args.dry_run:
            with open(dest, "w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=header, extrasaction="ignore")
                w.writeheader()
                for d in picked:
                    s = stratum_of(d)
                    row = {k: d.get(k, "") for k in fields}
                    row.update({
                        "stratum": s,
                        "stratum_population": populations[s],
                        "stratum_sample": realised[s],
                        "sampling_weight": round(populations[s] / realised[s], 6),
                    })
                    for c in HUMAN_COLUMNS:
                        row[c] = ""
                    w.writerow(row)

        manifest["tasks"][task] = {
            "status": "DRY_RUN" if args.dry_run else "DRAWN",
            "path": rel(dest),
            "population": sum(populations.values()),
            "strata": len(populations),
            "target": total,
            "realised": len(picked),
            "per_stratum_population": dict(sorted(populations.items())),
            "per_stratum_sample": dict(sorted(realised.items())),
        }
        print(f"  {task:12} {'DRY_RUN' if args.dry_run else 'DRAWN':12} "
              f"population={sum(populations.values()):>7} strata={len(populations):>3} "
              f"target={total:>4} realised={len(picked):>4}")

    if not args.dry_run:
        (sheets / "_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(f"\nmanifest: {(sheets / '_manifest.json').relative_to(ROOT)}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
