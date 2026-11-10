"""Build the terminology crosswalk between L1 / L2 / L3 (P1 corrected semantics).

L1  releases/data_catalogue/terminology/terminology_dedup.csv           (NER-derived, 166,012)
L2  outputs/results/terminology_v1/canonical_terms.jsonl                (canonical, 165,991)
L3  pipelines/corpus_v2/releases/2.2.0/terminology_inventory.csv           (Qwen corpus-side, 39,694)

Read-only with respect to all three inputs.  Writes only under docs/crosswalk/.

The three inventories are *not* the same population.  L1/L2 come from the
NER-derived catalogue inventory; L3 is a Qwen extraction over corpus 2.2.0
sections.  Counts are therefore reported per inventory and never summed.

Identity rules
--------------
L2  ``(term_norm, cdm_type)``          the canonical identity
L1  ``(term_norm, cdm_type)``          matched against L2
L3  ``term_normalized``                a surface key; L3 carries taxonomy labels,
                                       not CDM types

This script never writes ``canonical_term_id`` for L1/L3 and never invents a
preferred type.  Divergent types are recorded, not resolved.

L1 match methods
----------------
``IDENTITY``   L1 ``(term_norm, cdm_type)`` is an exact L2 key.
``SANITIZED``  equal only after ``sanitize`` (C0/C1 + DEL stripped, whitespace
               collapsed) is applied to the L1 ``term_norm``; i.e. the L1 surface
               carries an invisible control byte.
``UNMATCHED``  neither rule matches.

L3 match methods
----------------
``EXACT_TERM_NORM``  L3 ``term_normalized`` equals an L2 ``term_norm``.
``NORMALIZED``       equal after ``normalize_title`` is applied to both sides.
``UNMATCHED``        neither rule matches.

Type relation (L3 taxonomy label vs L2 CDM type)
------------------------------------------------
``SAME``         L3 label set equals the L2 CDM type (never observed: L3 carries
                 taxonomy labels, not CDM types).
``SUBSET``       L3 label set is a proper subset of the L2 type family.
``GENERIC_ONLY`` the only L2 match is the generic ``ENTITY`` type.
``DISJOINT``     matched but the two vocabularies share no type.
``NONE``         unmatched.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(ROOT / "pipelines/corpus_v2" / "scripts"))
from common import normalize_title  # noqa: E402

L1 = ROOT / "releases/data_catalogue" / "terminology" / "terminology_dedup.csv"
L2 = ROOT / "outputs/results" / "terminology_v1" / "canonical_terms.jsonl"
L3 = ROOT / "pipelines/corpus_v2" / "releases" / "2.2.0" / "terminology_inventory.csv"
OUT = ROOT / "docs" / "crosswalk"

TERMINOLOGY_BUILD = "28619916"
CORPUS_RELEASE = "2.2.0"

CONTROL_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_WS_RE = re.compile(r"\s+")

# L3 taxonomy type -> compatible CDM types.  Documented, conservative, and
# deliberately incomplete: a category with no CDM counterpart is left empty so
# that the resulting rows are reported as DISJOINT rather than forced.
L3_TO_CDM = {
    "organism_taxa": {"ORGANISM"},
    "gene_protein": {"PROTEIN", "DNA_RNA", "GENOMICS"},
    "metabolite": {"CHEMICAL"},
    "disease_phenotype": {"DISEASE", "CLINICAL"},
    "method_technique": {"EXPERIMENTAL_METHOD", "LAB_METHOD", "SAMPLE_METHOD"},
    "statistical_measure": {"DATA_ANALYSIS", "STUDY_DESIGN"},
    "intervention": {"CLINICAL", "STUDY_DESIGN"},
    "anatomical_site": set(),  # no CDM type corresponds to a body site
}


def sanitize(s: str) -> str:
    if not s:
        return ""
    return _WS_RE.sub(" ", CONTROL_RE.sub(" ", s)).strip()


def norm_term(t: str) -> str:
    """Mirror of src/scripts/termpipeline/assemble_mentions.norm_term."""
    if not t:
        return ""
    t = unicodedata.normalize("NFKD", t)
    t = t.encode("ascii", "ignore").decode("ascii")
    t = t.lower().replace("\u2013", "-").replace("\u2014", "-")
    t = re.sub(r"[-_/]", "-", t)
    t = re.sub(r"\s+", " ", t).strip().strip("-")
    return sanitize(t)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 22), b""):
            h.update(block)
    return h.hexdigest()


def load_l2():
    by_pair = defaultdict(list)
    by_norm = defaultdict(list)
    by_normtitle = defaultdict(list)
    by_san_pair = defaultdict(list)
    with open(L2, encoding="utf-8") as fh:
        for line in fh:
            d = json.loads(line)
            by_pair[(d["term_norm"], d["cdm_type"])].append(d)
            by_norm[d["term_norm"]].append(d)
            by_normtitle[normalize_title(d["term_norm"])].append(d)
            by_san_pair[(sanitize(d["term_norm"]), d["cdm_type"])].append(d)
    return by_pair, by_norm, by_normtitle, by_san_pair


def type_relation(l2_row, l3_types):
    """Classify one emitted (L3, L2) row.

    L3 carries taxonomy labels, not CDM types, so SAME/SUBSET are defined but
    never observed: the only generic type is ``ENTITY`` and every other pairing
    is DISJOINT.  ``l3_types`` is retained for documentation; the compatibility
    map ``L3_TO_CDM`` is informational and deliberately not used to force a
    match.
    """
    if l2_row is None:
        return "NONE"
    if l2_row.get("cdm_type") == "ENTITY" or l2_row.get("is_generic_type"):
        return "GENERIC_ONLY"
    return "DISJOINT"


def main():
    OUT.mkdir(parents=True, exist_ok=True)

    hashes = {"L1_dedup": sha256(L1), "L2_canonical": sha256(L2), "L3_inventory": sha256(L3)}
    sources = {
        "L1_dedup": {"path": str(L1.relative_to(ROOT)), "sha256": hashes["L1_dedup"]},
        "L2_canonical": {"path": str(L2.relative_to(ROOT)), "sha256": hashes["L2_canonical"]},
        "L3_inventory": {"path": str(L3.relative_to(ROOT)), "sha256": hashes["L3_inventory"]},
        "terminology_build_id": TERMINOLOGY_BUILD,
        "corpus_release": CORPUS_RELEASE,
    }
    (OUT / "_sources.json").write_text(json.dumps(sources, indent=2) + "\n", encoding="utf-8")

    by_pair, by_norm, by_normtitle, by_san_pair = load_l2()

    # ---------------- L3 -> L2 ----------------
    l3_rows = list(csv.DictReader(open(L3, newline="", encoding="utf-8")))
    l3_stats = Counter()
    type_stats = Counter()
    matched_norms = set()

    inv_fields = [
        "inventory_term", "inventory_term_normalized", "inventory_types",
        "canonical_term_id", "canonical_term_norm", "canonical_cdm_type",
        "canonical_alternative_types", "match_method", "match_score",
        "type_relation", "inventory_sha256", "canonical_sha256",
        "terminology_build", "corpus_release",
    ]
    with open(OUT / "inventory_to_canonical.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=inv_fields)
        w.writeheader()
        for r in l3_rows:
            norm = r["term_normalized"]
            l3_types = [t for t in (r["term_type"] or "").split("|") if t]

            if norm in by_norm:
                method, rows = "EXACT_TERM_NORM", by_norm[norm]
            else:
                rows = by_normtitle.get(normalize_title(norm))
                method = "NORMALIZED" if rows else "UNMATCHED"

            l3_stats[method] += 1
            if rows:
                matched_norms.add(norm)

            if not rows:
                type_stats["NONE"] += 1
                w.writerow({
                    "inventory_term": r["term_original_variants"], "inventory_term_normalized": norm,
                    "inventory_types": r["term_type"], "canonical_term_id": "",
                    "canonical_term_norm": "", "canonical_cdm_type": "",
                    "canonical_alternative_types": "", "match_method": "UNMATCHED",
                    "match_score": "", "type_relation": "NONE",
                    "inventory_sha256": hashes["L3_inventory"][:16],
                    "canonical_sha256": hashes["L2_canonical"][:16],
                    "terminology_build": TERMINOLOGY_BUILD, "corpus_release": CORPUS_RELEASE,
                })
                continue

            seen = set()
            for row in rows:
                key = row["term_id"]
                if key in seen:
                    continue
                seen.add(key)
                rel = type_relation(row, l3_types)
                type_stats[rel] += 1
                w.writerow({
                    "inventory_term": r["term_original_variants"], "inventory_term_normalized": norm,
                    "inventory_types": r["term_type"], "canonical_term_id": row["term_id"],
                    "canonical_term_norm": row["term_norm"], "canonical_cdm_type": row["cdm_type"],
                    "canonical_alternative_types": "|".join(row.get("alternative_types") or []),
                    "match_method": method, "match_score": "1.0",
                    "type_relation": rel,
                    "inventory_sha256": hashes["L3_inventory"][:16],
                    "canonical_sha256": hashes["L2_canonical"][:16],
                    "terminology_build": TERMINOLOGY_BUILD, "corpus_release": CORPUS_RELEASE,
                })

    # ---------------- L1 -> L2 ----------------
    l1_rows = list(csv.DictReader(open(L1, newline="", encoding="utf-8")))
    l1_stats = Counter()

    # Sanitization collisions: rows that collapse to the same
    # (sanitize(term_norm), cdm_type) while differing in the raw term_norm.
    groups = defaultdict(list)
    for i, r in enumerate(l1_rows):
        groups[(sanitize(r["term_norm"]), r["cdm_type"])].append(i)
    collisions = []
    for (sn, cdm), idxs in groups.items():
        norms = {l1_rows[i]["term_norm"] for i in idxs}
        if len(norms) > 1:
            collisions.append({
                "sanitized_term_norm": sn,
                "cdm_type": cdm,
                "row_ids": idxs,
                "raw_term_norms": sorted(norms),
                "survivor_term_norm": norm_term(l1_rows[idxs[0]]["term"]),
            })
    collisions.sort(key=lambda c: (c["sanitized_term_norm"], c["cdm_type"]))
    collision_rows = {i: n for n, c in enumerate(collisions) for i in c["row_ids"]}

    dedup_fields = [
        "l1_term", "l1_term_norm", "l1_cdm_type",
        "l2_term_id", "l2_term_norm", "l2_cdm_type", "match_method",
        "collision_group", "l1_sha256", "l2_sha256",
        "terminology_build",
    ]
    with open(OUT / "dedup_to_canonical.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=dedup_fields)
        w.writeheader()
        for i, r in enumerate(l1_rows):
            tn, ct = r["term_norm"], r["cdm_type"]
            if (tn, ct) in by_pair:
                method, target = "IDENTITY", by_pair[(tn, ct)][0]
            elif (sanitize(tn), ct) in by_san_pair:
                method, target = "SANITIZED", by_san_pair[(sanitize(tn), ct)][0]
            else:
                method, target = "UNMATCHED", None
            l1_stats[method] += 1
            w.writerow({
                "l1_term": r["term"], "l1_term_norm": tn, "l1_cdm_type": ct,
                "l2_term_id": target["term_id"] if target else "",
                "l2_term_norm": target["term_norm"] if target else "",
                "l2_cdm_type": target["cdm_type"] if target else "",
                "match_method": method,
                "collision_group": collision_rows.get(i, ""),
                "l1_sha256": hashes["L1_dedup"][:16],
                "l2_sha256": hashes["L2_canonical"][:16],
                "terminology_build": TERMINOLOGY_BUILD,
            })

    collision_doc = {
        "definition": (
            "Rows in L1 whose (sanitize(term_norm), cdm_type) collide while their raw "
            "term_norm strings differ. sanitize() removes only C0/C1 control bytes and "
            "collapses whitespace, so a collision means the surfaces differ solely by an "
            "invisible byte."
        ),
        "group_count": len(collisions),
        "rows_involved": sum(len(c["row_ids"]) for c in collisions),
        "rows_removed_if_collapsed": sum(len(c["row_ids"]) - 1 for c in collisions),
        "groups": collisions,
        "note": "Superseded ids are preserved here; no L1 row was merged or deleted.",
    }
    (OUT / "_collisions.json").write_text(json.dumps(collision_doc, indent=2) + "\n", encoding="utf-8")

    summary = {
        "l1": {"rows": len(l1_rows), "match_methods": dict(l1_stats)},
        "l3": {
            "rows": len(l3_rows),
            "match_methods": dict(l3_stats),
            "matched_total": l3_stats["EXACT_TERM_NORM"] + l3_stats["NORMALIZED"],
            "distinct_matched_norms": len(matched_norms),
            "type_relation": dict(type_stats),
        },
        "l2": {"rows": sum(len(v) for v in by_pair.values())},
        "sources": sources,
        "l3_to_cdm_mapping": {k: sorted(v) for k, v in L3_TO_CDM.items()},
    }
    (OUT / "_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
