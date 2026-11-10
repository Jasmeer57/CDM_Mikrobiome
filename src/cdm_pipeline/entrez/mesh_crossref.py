#!/usr/bin/env python
"""
Cross-reference CDM entities against MeSH using three strategies:

1. Name match: normalize entity terms and match against the 5,449 MeSH
   descriptors + chemicals from pubmed_metadata.json (instant, no API).

2. UMLS CUI → MeSH crosswalk: for entities with UMLS CUIs but no name match,
   call the UTS REST API (atoms endpoint) with fresh service tickets per
   request to extract MeSH descriptor UIs.  Parallelised with ThreadPoolExecutor.

3. MeSH label lookup: for entities without CUIs or that failed the crosswalk,
   call the MeSH REST API ``/lookup/descriptor?label=...`` endpoint.

Outputs (under ``cdm_output/``):
  - mesh_entity_crossref.json — per-entity MeSH mapping + strategy used
  - mesh_coverage_report.txt  — human-readable summary
  - entities table gains ``MeSH_UI`` and ``MeSH_tree`` columns

Usage:
  python -m cdm_pipeline.entrez.mesh_crossref [--db PATH] [--metadata PATH]
      [--workers 5] [--max-api N] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "paper" / "_multi_ner_runs" / "cdm_output"
DB_PATH = OUTPUT_DIR / "microbiome_cdm.db"
METADATA_PATH = OUTPUT_DIR / "pubmed_metadata.json"
ENV_PATH = PROJECT_ROOT / ".env"

MESH_WORTHY_TYPES = {
    "DISEASE", "CHEMICAL", "PROTEIN", "ORGANISM",
    "DNA_RNA", "PATHWAY", "CELL_TYPE", "CLINICAL",
    "EXPERIMENTAL_METHOD", "LAB_METHOD", "SAMPLE_METHOD",
    "STUDY_DESIGN", "DATA_ANALYSIS", "GENOMICS",
}

UTS_API_KEY = ""
UTS_TGT_URL: Optional[str] = None
API_DELAY = 0.1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize(term: str) -> str:
    term = unicodedata.normalize("NFKD", term)
    term = "".join(c for c in term if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", term.strip().lower())


def _load_env() -> None:
    global UTS_API_KEY
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.strip().split("=", 1)
                if k == "UMLS_API_KEY":
                    UTS_API_KEY = v
    if not UTS_API_KEY:
        UTS_API_KEY = os.environ.get("UMLS_API_KEY", "")


def _get_tgt() -> str:
    """Get a Ticket Granting Ticket from UTS (lasts ~8 hours)."""
    resp = requests.post(
        "https://utslogin.nlm.nih.gov/cas/v1/api-key",
        data={"apikey": UTS_API_KEY},
        timeout=15,
    )
    if resp.status_code != 201:
        raise RuntimeError(f"UTS TGT failed: {resp.status_code}")
    match = re.search(r'action="([^"]+)"', resp.text)
    if not match:
        raise RuntimeError("Could not parse TGT URL from response")
    return match.group(1)


def _get_service_ticket(tgt_url: str) -> str:
    """Get a single-use service ticket from the TGT."""
    resp = requests.post(tgt_url, data={"service": "http://umlsks.nlm.nih.gov"}, timeout=15)
    if resp.status_code != 200:
        raise RuntimeError(f"Service ticket failed: {resp.status_code}")
    return resp.text.strip()


# ---------------------------------------------------------------------------
# Strategy 1: Name match against PubMed MeSH
# ---------------------------------------------------------------------------

def build_mesh_name_index(metadata_path: Path) -> Dict[str, str]:
    """Build {normalized_term: MeSH_UI} from pubmed_metadata.json."""
    with open(metadata_path, encoding="utf-8") as f:
        data = json.load(f)

    index: Dict[str, str] = {}
    for _bp_id, meta in data.items():
        for heading in meta.get("mesh_headings", []):
            desc = heading.get("descriptor", "").strip()
            ui = heading.get("ui", "").strip()
            if desc and ui.startswith("D"):
                key = _normalize(desc)
                if key not in index:
                    index[key] = ui
        for chem in meta.get("chemicals", []):
            name = chem.get("name", "").strip()
            ui = chem.get("ui", "").strip()
            if name and ui.startswith("D"):
                key = _normalize(name)
                if key not in index:
                    index[key] = ui
    return index


def strategy_name_match(
    entities: List[Dict[str, Any]],
    mesh_index: Dict[str, str],
) -> List[Dict[str, Any]]:
    """Match entities to MeSH by normalized name. Returns enrichment list."""
    results: List[Dict[str, Any]] = []
    for ent in entities:
        key = _normalize(ent["term"])
        mesh_ui = mesh_index.get(key)
        if mesh_ui:
            results.append({
                "entity_id": ent["id"],
                "term": ent["term"],
                "entity_type": ent["entity_type"],
                "mesh_ui": mesh_ui,
                "strategy": "name_match",
            })
    return results


# ---------------------------------------------------------------------------
# Strategy 2: UMLS CUI → MeSH via UTS atoms endpoint
# ---------------------------------------------------------------------------

def cui_to_mesh(cui: str, tgt_url: str) -> Optional[str]:
    """Crosswalk a single UMLS CUI to a MeSH descriptor UI."""
    try:
        ticket = _get_service_ticket(tgt_url)
        resp = requests.get(
            f"https://uts-ws.nlm.nih.gov/rest/content/current/CUI/{cui}/atoms",
            params={"ticket": ticket, "pageSize": 100},
            timeout=15,
        )
        if resp.status_code != 200:
            return None
        atoms = resp.json().get("result", [])
        for atom in atoms:
            if atom.get("rootSource") == "MSH":
                match = re.search(r"(D\d{6})", atom.get("code", ""))
                if match:
                    return match.group(1)
        return None
    except Exception:
        return None


def strategy_cui_crosswalk(
    entities: List[Dict[str, Any]],
    already_mapped_ids: Set[int],
    tgt_url: str,
    workers: int = 5,
    max_api: int = 12000,
) -> List[Dict[str, Any]]:
    """Crosswalk CUIs to MeSH UIs in parallel. Returns enrichment list."""
    # Deduplicate by CUI — only need to look up each CUI once
    cui_to_entities: Dict[str, List[Dict]] = defaultdict(list)
    for ent in entities:
        if ent["id"] in already_mapped_ids:
            continue
        cui = ent.get("umls_id", "")
        if cui and cui.startswith("C"):
            cui_to_entities[cui].append(ent)

    unique_cuis = list(cui_to_entities.keys())
    if max_api > 0:
        unique_cuis = unique_cuis[:max_api]

    print(f"  {len(unique_cuis):,} unique CUIs to look up (max_api={max_api})")

    results: List[Dict[str, Any]] = []
    cui_to_mesh_cache: Dict[str, Optional[str]] = {}
    done = 0

    def _lookup(cui: str) -> Tuple[str, Optional[str]]:
        return cui, cui_to_mesh(cui, tgt_url)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_lookup, cui): cui for cui in unique_cuis}
        for future in as_completed(futures):
            cui, mesh_ui = future.result()
            cui_to_mesh_cache[cui] = mesh_ui
            done += 1
            if done % 100 == 0:
                print(f"    ... {done}/{len(unique_cuis)} CUIs processed")
            if mesh_ui:
                for ent in cui_to_entities[cui]:
                    results.append({
                        "entity_id": ent["id"],
                        "term": ent["term"],
                        "entity_type": ent["entity_type"],
                        "mesh_ui": mesh_ui,
                        "strategy": "cui_crosswalk",
                    })

    n_hit = sum(1 for v in cui_to_mesh_cache.values() if v)
    print(f"  CUI crosswalk: {n_hit}/{len(unique_cuis)} CUIs → MeSH ({n_hit/len(unique_cuis)*100:.1f}%)")
    return results


# ---------------------------------------------------------------------------
# Strategy 3: MeSH label lookup for remaining entities
# ---------------------------------------------------------------------------

def mesh_label_lookup(term: str, session: requests.Session) -> Optional[str]:
    """Look up a term via the MeSH REST API label endpoint."""
    if len(term) < 4:
        return None
    # Skip generic terms
    generic = {"the", "and", "study", "results", "conclusion", "introduction",
               "methods", "discussion", "data", "analysis", "associated",
               "using", "based", "composition", "abundance", "diversity",
               "function", "individual", "compared", "evaluated", "expressed",
               "characteristics", "development", "evidence", "decrease",
               "model", "alterations", "food", "metabolic", "functional",
               "children", "early", "female", "male", "adult"}
    if term.lower().strip() in generic:
        return None
    try:
        resp = session.get(
            "https://id.nlm.nih.gov/mesh/lookup/descriptor",
            params={"label": term, "format": "json"},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        results = resp.json()
        if results and isinstance(results, list) and len(results) > 0:
            uri = results[0].get("resource", "")
            if uri:
                ui = uri.rsplit("/", 1)[-1]
                if ui.startswith("D"):
                    return ui
    except Exception:
        pass
    return None


def strategy_label_lookup(
    entities: List[Dict[str, Any]],
    already_mapped_ids: Set[int],
    workers: int = 3,
    max_api: int = 2000,
) -> List[Dict[str, Any]]:
    """Look up remaining entities by MeSH label. Returns enrichment list."""
    remaining = [e for e in entities if e["id"] not in already_mapped_ids]
    if max_api > 0:
        remaining = remaining[:max_api]

    # Sort by paper_count descending to get most important first
    remaining.sort(key=lambda e: e.get("paper_count", 0) or 0, reverse=True)

    print(f"  {len(remaining):,} entities for label lookup (max_api={max_api})")

    results: List[Dict[str, Any]] = []
    session = requests.Session()
    done = 0
    hit = 0

    for ent in remaining:
        mesh_ui = mesh_label_lookup(ent["term"], session)
        done += 1
        if done % 100 == 0:
            print(f"    ... {done}/{len(remaining)} label lookups ({hit} hits)")
        if mesh_ui:
            results.append({
                "entity_id": ent["id"],
                "term": ent["term"],
                "entity_type": ent["entity_type"],
                "mesh_ui": mesh_ui,
                "strategy": "label_lookup",
            })
            hit += 1
        time.sleep(API_DELAY)

    print(f"  Label lookup: {hit}/{len(remaining)} hits ({hit/len(remaining)*100 if remaining else 0:.1f}%)")
    return results


# ---------------------------------------------------------------------------
# DB enrichment
# ---------------------------------------------------------------------------

def enrich_db(
    db_path: Path,
    all_mappings: List[Dict[str, Any]],
    dry_run: bool = False,
) -> int:
    """Add MeSH_UI column to entities and populate it."""
    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()

    cols = [row[1] for row in c.execute("PRAGMA table_info(entities)").fetchall()]
    if "MeSH_UI" not in cols:
        c.execute("ALTER TABLE entities ADD COLUMN MeSH_UI TEXT DEFAULT ''")
        print("  Added MeSH_UI column to entities")

    # Deduplicate by entity_id (first mapping wins, name_match > cui > label)
    ent_to_mesh: Dict[int, str] = {}
    strategy_priority = {"name_match": 0, "cui_crosswalk": 1, "label_lookup": 2}
    all_mappings.sort(key=lambda m: strategy_priority.get(m["strategy"], 3))
    for m in all_mappings:
        eid = m["entity_id"]
        if eid not in ent_to_mesh:
            ent_to_mesh[eid] = m["mesh_ui"]

    if not dry_run:
        n_updated = 0
        for eid, mesh_ui in ent_to_mesh.items():
            c.execute("UPDATE entities SET MeSH_UI = ? WHERE id = ?", (mesh_ui, eid))
            n_updated += 1
        conn.commit()
        print(f"  Enriched {n_updated:,} entities with MeSH_UI")
    else:
        print(f"  [DRY RUN] Would enrich {len(ent_to_mesh):,} entities")

    conn.close()
    return len(ent_to_mesh)


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def write_reports(
    output_dir: Path,
    all_mappings: List[Dict[str, Any]],
    entities: List[Dict[str, Any]],
    mesh_index: Dict[str, str],
) -> None:
    """Write JSON + text reports."""

    # JSON: per-entity mapping
    crossref_path = output_dir / "mesh_entity_crossref.json"
    with open(crossref_path, "w", encoding="utf-8") as f:
        json.dump({
            "n_entities_total": len(entities),
            "n_entities_with_mesh": len(all_mappings),
            "mesh_coverage_pct": len(all_mappings) / len(entities) * 100 if entities else 0,
            "mappings": all_mappings,
        }, f, indent=2, ensure_ascii=False)
    print(f"  Wrote {crossref_path}")

    # Strategy breakdown
    strategy_counts = Counter(m["strategy"] for m in all_mappings)
    type_coverage: Dict[str, Dict[str, int]] = defaultdict(lambda: {"total": 0, "mapped": 0})
    for ent in entities:
        type_coverage[ent["entity_type"]]["total"] += 1
    mapped_ids = {m["entity_id"] for m in all_mappings}
    for ent in entities:
        if ent["id"] in mapped_ids:
            type_coverage[ent["entity_type"]]["mapped"] += 1

    # Text summary
    summary_path = output_dir / "mesh_coverage_report.txt"
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("=" * 60 + "\n")
        f.write("MeSH Cross-Reference Coverage Report\n")
        f.write("=" * 60 + "\n\n")

        f.write(f"Total entities:           {len(entities):,}\n")
        f.write(f"Entities with MeSH UI:    {len(all_mappings):,} ({len(all_mappings)/len(entities)*100:.1f}%)\n")
        f.write(f"PubMed MeSH dictionary:   {len(mesh_index):,} terms\n\n")

        f.write("Strategy breakdown:\n")
        for strat, cnt in strategy_counts.most_common():
            f.write(f"  {strat:20s}: {cnt:5d}\n")

        f.write("\nCoverage by entity type:\n")
        f.write(f"  {'Type':22s} {'Total':>7s} {'Mapped':>7s} {'%':>6s}\n")
        f.write(f"  {'-'*22} {'-'*7} {'-'*7} {'-'*6}\n")
        for et, counts in sorted(type_coverage.items(), key=lambda x: -x[1]["total"]):
            pct = counts["mapped"] / counts["total"] * 100 if counts["total"] else 0
            f.write(f"  {et:22s} {counts['total']:7d} {counts['mapped']:7d} {pct:5.1f}%\n")

        f.write("\n" + "=" * 60 + "\n")
    print(f"  Wrote {summary_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Cross-reference CDM entities against MeSH")
    ap.add_argument("--db", default=str(DB_PATH))
    ap.add_argument("--metadata", default=str(METADATA_PATH))
    ap.add_argument("--output-dir", default=str(OUTPUT_DIR))
    ap.add_argument("--workers", type=int, default=5, help="Parallel workers for CUI crosswalk")
    ap.add_argument("--max-cui-api", type=int, default=12000, help="Max CUI crosswalk API calls")
    ap.add_argument("--max-label-api", type=int, default=2000, help="Max label lookup API calls")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db_path = Path(args.db)
    metadata_path = Path(args.metadata)
    output_dir = Path(args.output_dir)

    _load_env()

    print("=" * 60)
    print("MeSH Cross-Reference")
    print("=" * 60)

    # Load entities
    conn = sqlite3.connect(str(db_path))
    entities: List[Dict[str, Any]] = []
    for row in conn.execute(
        "SELECT id, term, entity_type, UMLS_ID, paper_count FROM entities"
    ).fetchall():
        entities.append({
            "id": row[0], "term": row[1], "entity_type": row[2],
            "umls_id": row[3] or "", "paper_count": row[4] or 0,
        })
    conn.close()
    print(f"\nLoaded {len(entities):,} entities from DB")

    # Strategy 1: Name match
    print(f"\n[1/4] Name match against PubMed MeSH dictionary...")
    mesh_index = build_mesh_name_index(metadata_path)
    print(f"  MeSH dictionary: {len(mesh_index):,} terms")
    s1_results = strategy_name_match(entities, mesh_index)
    print(f"  Name match: {len(s1_results):,} entities matched")
    already_mapped = {r["entity_id"] for r in s1_results}

    # Strategy 2: CUI crosswalk
    print(f"\n[2/4] UMLS CUI → MeSH crosswalk (UTS API)...")
    if UTS_API_KEY:
        tgt_url = _get_tgt()
        print(f"  Got TGT: ...{tgt_url[-25:]}")
        s2_results = strategy_cui_crosswalk(
            entities, already_mapped, tgt_url,
            workers=args.workers, max_api=args.max_cui_api,
        )
        already_mapped.update(r["entity_id"] for r in s2_results)
    else:
        print("  SKIPPED — no UMLS_API_KEY set")
        s2_results = []

    # Strategy 3: Label lookup
    print(f"\n[3/4] MeSH label lookup for remaining entities...")
    s3_results = strategy_label_lookup(
        entities, already_mapped,
        workers=args.workers, max_api=args.max_label_api,
    )
    already_mapped.update(r["entity_id"] for r in s3_results)

    # Combine
    all_mappings = s1_results + s2_results + s3_results
    print(f"\n  Total mappings: {len(all_mappings):,}")

    # Enrich DB
    print(f"\n[4/4] Enriching entities table with MeSH_UI...")
    enrich_db(db_path, all_mappings, dry_run=args.dry_run)

    # Reports
    print(f"\nWriting reports...")
    write_reports(output_dir, all_mappings, entities, mesh_index)

    print("\n" + "=" * 60)
    print("DONE")
    print("=" * 60)


if __name__ == "__main__":
    main()
