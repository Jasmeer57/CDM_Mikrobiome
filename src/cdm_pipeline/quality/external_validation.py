"""External database cross-validation for the Microbiome-CDM knowledge graph.

Adapted from EFRE's cross_validate_external.py and extended with
microbiome-specific databases (NCBITaxon, gutMGBrain-derived associations).

Validates MCDM relationships against:
  1. DisGeNET (gene-disease associations)
     - MCDM PROTEIN/DNA_RNA entities matched by gene symbol → NCBI gene ID
     - MCDM DISEASE entities matched by UMLS CUI → DOID via MONDO/DOID xrefs
  2. MONDO/DOID ontology cross-references
     - DISEASE entities validated via UMLS CUI xref existence
  3. ChEBI ontology relations
     - CHEMICAL entities matched by name → ChEBI ID
     - (CHEBI:xxx, relation, CHEBI:yyy) existence in chebi.obo
     - Therapeutic role check for "treats" predicates
  4. NCBITaxon (organism validation)
     - ORGANISM entities with NCBITaxon IDs validated against NCBI Taxonomy

Writes corroboration info to relationships table (external_corroboration column)
and generates a JSON report.

Usage (standalone):
  python -m cdm_pipeline.quality.external_validation \
    --db path/to/microbiome_cdm.db \
    --disgenet /path/to/disgenet_gene_disease.tsv \
    --hgnc-map /path/to/hgnc_to_ncbi_gene.tsv \
    --mondo /path/to/mondo.obo \
    --doid /path/to/doid.obo \
    --chebi /path/to/chebi.obo \
    --report path/to/report.json
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from ..config import CDM_OUTPUT_DIR

DB_PATH = CDM_OUTPUT_DIR / "microbiome_cdm.db"

# Regex for parsing .obo files
_XREF_RE = re.compile(r"xref:\s*(\S+):\s*(\S+)")
_NAME_RE = re.compile(r"name:\s*(.+)")


# ── OBO loaders ──

def load_obo_xrefs(path: str) -> dict[str, set[str]]:
    """Return {id: {SRC:VAL, ...}} from an .obo file."""
    xrefs: dict[str, set[str]] = defaultdict(set)
    current_id = None
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("id:"):
                current_id = line.split(maxsplit=1)[1].strip()
            elif line.startswith("xref:") and current_id:
                m = _XREF_RE.match(line)
                if m:
                    xrefs[current_id].add(f"{m.group(1)}:{m.group(2)}")
            elif line.startswith("[Term]"):
                current_id = None
    return xrefs


def load_obo_names(path: str) -> dict[str, str]:
    """Return {id: name} from an .obo file."""
    names: dict[str, str] = {}
    current_id = None
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("id:"):
                current_id = line.split(maxsplit=1)[1].strip()
            elif line.startswith("name:") and current_id:
                name = line[len("name:"):].strip()
                names[current_id] = name
            elif line.startswith("[Term]"):
                current_id = None
    return names


def load_chebi_relations(path: str) -> dict[str, set[tuple[str, str]]]:
    """Return {CHEBI:xxx: set of (relation_type, target_CHEBI_id)}."""
    rels: dict[str, set[tuple[str, str]]] = defaultdict(set)
    current_id = None
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if line.startswith("id:"):
                current_id = line.split(maxsplit=1)[1].strip()
            elif line.startswith("relationship:") and current_id:
                rest = line[len("relationship:"):].strip()
                parts = rest.split(None, 1)
                if len(parts) >= 2:
                    target = parts[1].split("!")[0].strip()
                    rels[current_id].add((parts[0], target))
            elif line.startswith("is_a:") and current_id:
                target = line[len("is_a:"):].strip().split("!")[0].strip()
                rels[current_id].add(("is_a", target))
            elif line.startswith("[Term]"):
                current_id = None
    return rels


def load_disgenet(path: str) -> set[tuple[str, str]]:
    """Return set of (ncbi_gene_id, DOID:xxxxx) pairs from DisGeNET TSV."""
    pairs = set()
    n = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            n += 1
            if n == 1:
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 5:
                continue
            doid = parts[0].strip()
            gene = parts[2].strip()
            if doid.startswith("DOID:") and gene.isdigit():
                pairs.add((gene, doid))
    return pairs


def load_hgnc_map(path: str) -> tuple[dict[str, str], dict[str, str]]:
    """Return ({HGNC:xxx: ncbi_gene_id}, {symbol: ncbi_gene_id})."""
    id_map = {}
    sym_map = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("#"):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 3 and parts[0].startswith("HGNC:"):
                id_map[parts[0]] = parts[1]
                sym_map[parts[2].upper()] = parts[1]
    return id_map, sym_map


def build_umls_to_doid(
    mondo_xrefs: dict[str, set[str]],
    doid_xrefs: dict[str, set[str]],
) -> dict[str, set[str]]:
    """Build {UMLS:CUI: {DOID:xxx, ...}} mapping via MONDO and DOID xrefs."""
    umls_to_doid: dict[str, set[str]] = defaultdict(set)

    # MONDO terms often have UMLS xrefs
    for mondo_id, xs in mondo_xrefs.items():
        for x in xs:
            if x.startswith("UMLS:"):
                cui = x[len("UMLS:"):]
                umls_to_doid[cui].add(mondo_id)

    # DOID terms often have UMLS/MESH xrefs
    for doid_id, xs in doid_xrefs.items():
        for x in xs:
            if x.startswith("UMLS:"):
                cui = x[len("UMLS:"):]
                umls_to_doid[cui].add(doid_id)
            if x.startswith("MESH:"):
                # Try to resolve MESH → DOID directly
                pass

    # Also map MONDO → DOID via shared xrefs (UMLS, MESH)
    mesh_to_mondo: dict[str, set[str]] = defaultdict(set)
    mesh_to_doid: dict[str, set[str]] = defaultdict(set)
    for m, xs in mondo_xrefs.items():
        for x in xs:
            if x.startswith("MESH:"):
                mesh_to_mondo[x].add(m)
    for d, xs in doid_xrefs.items():
        for x in xs:
            if x.startswith("MESH:"):
                mesh_to_doid[x].add(d)

    for mesh, mondos in mesh_to_mondo.items():
        for d in mesh_to_doid.get(mesh, set()):
            for m in mondos:
                # Transfer any UMLS CUIs associated with this MONDO to the DOID
                for x in mondo_xrefs.get(m, set()):
                    if x.startswith("UMLS:"):
                        umls_to_doid[x[len("UMLS:"):]].add(d)

    return umls_to_doid


def build_chebi_name_map(
    chebi_names: dict[str, str],
) -> dict[str, str]:
    """Build {lowercase_name: CHEBI:xxx} from ChEBI .obo names."""
    return {name.lower(): chebi_id for chebi_id, name in chebi_names.items()}


# ── Therapeutic roles for ChEBI role check ──
THERAPEUTIC_ROLES = {
    "CHEBI:23888",   # drug
    "CHEBI:37821",   # therapeutic agent
    "CHEBI:65414",   # anti-inflammatory agent
    "CHEBI:35480",   # anti-inflammatory drug
    "CHEBI:67079",   # immunosuppressive agent
    "CHEBI:50747",   # analgesic
    "CHEBI:35618",   # anti-inflammatory agent
    "CHEBI:50858",   # antibiotic
    "CHEBI:50996",   # antineoplastic agent
    "CHEBI:49200",   # anti-infective agent
    "CHEBI:36047",   # androgen antagonist
}


def cross_validate(
    db_path: Path | str = DB_PATH,
    disgenet_path: str | None = None,
    hgnc_path: str | None = None,
    mondo_path: str | None = None,
    doid_path: str | None = None,
    chebi_path: str | None = None,
    pubmed_meta_path: str | None = None,
    apply: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Cross-validate MCDM relationships against external databases.

    Args:
        db_path: Path to microbiome_cdm.db
        disgenet_path: Path to disgenet_gene_disease.tsv
        hgnc_path: Path to hgnc_to_ncbi_gene.tsv
        mondo_path: Path to mondo.obo
        doid_path: Path to doid.obo
        chebi_path: Path to chebi.obo
        pubmed_meta_path: Path to pubmed_metadata.json (for MeSH co-occurrence)
        apply: If True, write corroboration info to DB
        dry_run: If True with apply, don't actually modify DB

    Returns:
        Dict with per-DB corroboration rates, per-predicate breakdowns.
    """
    db_path = Path(db_path)

    # ── Load external sources ──
    disgenet_pairs: set[tuple[str, str]] = set()
    if disgenet_path:
        print(f"Loading DisGeNET from {disgenet_path}...")
        disgenet_pairs = load_disgenet(disgenet_path)
        print(f"  {len(disgenet_pairs):,} (gene, DOID) pairs")

    hgnc_map: dict[str, str] = {}
    symbol_map: dict[str, str] = {}
    if hgnc_path:
        print(f"Loading HGNC→NCBI gene map from {hgnc_path}...")
        hgnc_map, symbol_map = load_hgnc_map(hgnc_path)
        print(f"  {len(hgnc_map):,} HGNC IDs, {len(symbol_map):,} gene symbols")

    mondo_xrefs: dict[str, set[str]] = {}
    if mondo_path:
        print(f"Loading MONDO xrefs from {mondo_path}...")
        mondo_xrefs = load_obo_xrefs(mondo_path)
        print(f"  {len(mondo_xrefs):,} MONDO terms with xrefs")

    doid_xrefs: dict[str, set[str]] = {}
    if doid_path:
        print(f"Loading DOID xrefs from {doid_path}...")
        doid_xrefs = load_obo_xrefs(doid_path)
        print(f"  {len(doid_xrefs):,} DOID terms with xrefs")

    umls_to_doid: dict[str, set[str]] = {}
    if mondo_path and doid_path:
        print("Building UMLS→DOID mapping...")
        umls_to_doid = build_umls_to_doid(mondo_xrefs, doid_xrefs)
        print(f"  {len(umls_to_doid):,} UMLS CUIs mapped to DOIDs")

    # Build MeSH→DOID mapping from DOID xrefs
    mesh_to_doid: dict[str, set[str]] = defaultdict(set)
    if doid_path:
        for doid_id, xs in doid_xrefs.items():
            for x in xs:
                if x.startswith("MESH:") or x.startswith("MSH:"):
                    mesh_ui = x.split(":", 1)[1]
                    mesh_to_doid[mesh_ui].add(doid_id)
        print(f"  {len(mesh_to_doid):,} MeSH UIs mapped to DOIDs")

    chebi_rels: dict[str, set[tuple[str, str]]] = {}
    chebi_names: dict[str, str] = {}
    chebi_name_map: dict[str, str] = {}
    if chebi_path:
        print(f"Loading ChEBI relations from {chebi_path}...")
        chebi_rels = load_chebi_relations(chebi_path)
        print(f"  {len(chebi_rels):,} ChEBI terms with relations")
        chebi_names = load_obo_names(chebi_path)
        chebi_name_map = build_chebi_name_map(chebi_names)
        print(f"  {len(chebi_name_map):,} ChEBI name→ID mappings")

    # ── Load MeSH co-occurrence data from PubMed metadata ──
    mesh_cooccurrence: set[tuple[str, str]] = set()
    if pubmed_meta_path:
        print(f"Loading MeSH co-occurrences from {pubmed_meta_path}...")
        with open(pubmed_meta_path, encoding="utf-8") as f:
            pubmed_meta = json.load(f)
        for _bp_id, meta in pubmed_meta.items():
            uis = []
            for heading in meta.get("mesh_headings", []):
                ui = heading.get("ui", "")
                if ui.startswith("D"):
                    uis.append(ui)
            for chem in meta.get("chemicals", []):
                ui = chem.get("ui", "")
                if ui.startswith("D"):
                    uis.append(ui)
            # All pairwise co-occurrences
            for i in range(len(uis)):
                for j in range(i + 1, len(uis)):
                    pair = tuple(sorted([uis[i], uis[j]]))
                    mesh_cooccurrence.add(pair)
        print(f"  {len(mesh_cooccurrence):,} unique MeSH UI co-occurrence pairs")

    # ── Load MCDM relations ──
    conn = sqlite3.connect(str(db_path))
    # Check if MeSH_UI column exists
    ent_cols = {row[1] for row in conn.execute("PRAGMA table_info(entities)").fetchall()}
    has_mesh_ui = "MeSH_UI" in ent_cols
    mesh_ui_sel = "s.MeSH_UI as subject_mesh, t.MeSH_UI as object_mesh," if has_mesh_ui else "NULL as subject_mesh, NULL as object_mesh,"

    query = """
        SELECT r.id, r.source_id, r.target_id, r.relationship_type,
               r.confidence, r.evidence, r.source_type, r.validation_status,
               s.term as subject, s.entity_type as subject_type,
               s.UMLS_ID as subject_umls, s.NCBITaxon as subject_ncbitaxon,
               t.term as object, t.entity_type as object_type,
               t.UMLS_ID as object_umls, t.NCBITaxon as object_ncbitaxon,
               {mesh_ui_sel}
               r.pubmed_ids
        FROM relationships r
        JOIN entities s ON r.source_id = s.id
        JOIN entities t ON r.target_id = t.id
    """.format(mesh_ui_sel=mesh_ui_sel)
    rows = conn.execute(query).fetchall()
    relations = [dict(zip([d[0] for d in conn.execute(query).description], row)) for row in rows]
    conn.close()

    print(f"\nLoaded {len(relations):,} relations for cross-validation")

    # ── Validate ──
    n_total = 0
    n_corroborated = 0
    per_db: Counter = Counter()
    eligible_per_db: Counter = Counter()
    per_pred: dict[str, Counter] = defaultdict(Counter)
    novel_triples = 0
    corroboration_records: list[dict] = []

    for rel in relations:
        n_total += 1
        pred = rel.get("relationship_type", "").lower()
        subj = rel.get("subject", "")
        obj = rel.get("object", "")
        subj_type = rel.get("subject_type", "")
        obj_type = rel.get("object_type", "")
        subj_umls = rel.get("subject_umls", "") or ""
        obj_umls = rel.get("object_umls", "") or ""
        subj_ncbitaxon = rel.get("subject_ncbitaxon", "") or ""
        obj_ncbitaxon = rel.get("object_ncbitaxon", "") or ""
        subj_mesh = rel.get("subject_mesh", "") or ""
        obj_mesh = rel.get("object_mesh", "") or ""

        corroborated_by: list[str] = []

        # ── 1. DisGeNET: (gene, DOID) pair ──
        if disgenet_pairs and symbol_map:
            # Try both orientations
            for gene_term, gene_type, disease_term, disease_type, disease_umls in [
                (subj, subj_type, obj, obj_type, obj_umls),
                (obj, obj_type, subj, subj_type, subj_umls),
            ]:
                if gene_type not in ("PROTEIN", "DNA_RNA"):
                    continue
                # Resolve gene → NCBI gene ID by symbol
                ncbi_gene = symbol_map.get(gene_term.upper())
                if not ncbi_gene:
                    continue
                # Resolve disease → DOID via UMLS CUI
                doid = None
                if disease_umls:
                    cui = subj_umls if disease_term == subj else obj_umls
                    cui = disease_umls  # already selected above
                    doids = umls_to_doid.get(cui, set())
                    if doids:
                        doid = next(iter(doids))
                if not doid:
                    continue
                eligible_per_db["DisGeNET"] += 1
                if (ncbi_gene, doid) in disgenet_pairs:
                    corroborated_by.append("DisGeNET")
                    break

        # ── 2. MONDO/DOID: disease entity existence ──
        if mondo_xrefs or doid_xrefs:
            for disease_term, disease_type, disease_umls in [
                (subj, subj_type, subj_umls),
                (obj, obj_type, obj_umls),
            ]:
                if disease_type != "DISEASE":
                    continue
                if not disease_umls:
                    continue
                doids = umls_to_doid.get(disease_umls, set())
                if doids:
                    eligible_per_db["MONDO_DOID"] += 1
                    corroborated_by.append("MONDO_DOID")
                    break

        # ── 3. NCBITaxon: organism validation ──
        for taxon_id in [subj_ncbitaxon, obj_ncbitaxon]:
            if taxon_id and "NCBITaxon:" in taxon_id:
                eligible_per_db["NCBITaxon"] += 1
                corroborated_by.append("NCBITaxon")
                break

        # ── 3.5. MeSH→DOID: disease validation via MeSH_UI ──
        if mesh_to_doid:
            for mesh_ui, ent_type in [
                (subj_mesh, subj_type),
                (obj_mesh, obj_type),
            ]:
                if not mesh_ui or ent_type != "DISEASE":
                    continue
                doids = mesh_to_doid.get(mesh_ui, set())
                if doids:
                    eligible_per_db["MeSH_DOID"] += 1
                    corroborated_by.append("MeSH_DOID")
                    break

        # ── 3.6. MeSH co-occurrence: both entities have MeSH_UIs that co-occur ──
        if mesh_cooccurrence and subj_mesh and obj_mesh:
            pair = tuple(sorted([subj_mesh, obj_mesh]))
            if pair in mesh_cooccurrence:
                eligible_per_db["MeSH_cooccurrence"] += 1
                corroborated_by.append("MeSH_cooccurrence")

        # ── 4. ChEBI: chemical relations + therapeutic roles ──
        if chebi_rels and chebi_name_map:
            # Match chemicals by name
            subj_chebi = chebi_name_map.get(subj.lower())
            obj_chebi = chebi_name_map.get(obj.lower())

            # 4a. Therapeutic role check for "treats" predicates
            if pred == "treats" and subj_chebi and subj_type == "CHEMICAL":
                eligible_per_db["ChEBI_role"] += 1
                rels = chebi_rels.get(subj_chebi, set())
                role_targets = {target for rel_type, target in rels if rel_type == "RO:0000087"}
                if role_targets & THERAPEUTIC_ROLES:
                    corroborated_by.append("ChEBI_role")

            # 4b. Chemical-chemical relation existence
            if subj_chebi and obj_chebi and subj_type == "CHEMICAL" and obj_type == "CHEMICAL":
                eligible_per_db["ChEBI_relation"] += 1
                rels = chebi_rels.get(subj_chebi, set())
                if any(obj_chebi == target for _, target in rels):
                    corroborated_by.append("ChEBI_relation")

        # ── Tally ──
        if corroborated_by:
            n_corroborated += 1
            for db in set(corroborated_by):
                per_db[db] += 1
            per_pred[pred]["corroborated"] += 1
            corroboration_records.append({
                "rel_id": rel["id"],
                "corroborated_by": corroborated_by,
            })
        else:
            novel_triples += 1
            per_pred[pred]["novel"] += 1

    # ── Apply to DB ──
    if apply and not dry_run:
        conn = sqlite3.connect(str(db_path))
        # Add column if not exists
        try:
            conn.execute("ALTER TABLE relationships ADD COLUMN external_corroboration TEXT")
        except sqlite3.OperationalError:
            pass
        for rec in corroboration_records:
            conn.execute(
                "UPDATE relationships SET external_corroboration = ? WHERE id = ?",
                (json.dumps(rec["corroborated_by"]), rec["rel_id"]),
            )
        conn.commit()
        conn.close()
        print(f"\nApplied corroboration info to {len(corroboration_records):,} relations")

    return {
        "n_total": n_total,
        "n_corroborated": n_corroborated,
        "n_novel": novel_triples,
        "corroboration_rate": n_corroborated / max(n_total, 1),
        "per_db": dict(per_db.most_common()),
        "eligible_per_db": dict(eligible_per_db.most_common()),
        "per_predicate": {p: dict(c) for p, c in per_pred.items()},
        "disgenet_pairs_loaded": len(disgenet_pairs),
        "hgnc_mapped": len(hgnc_map),
        "mondo_xrefs_loaded": len(mondo_xrefs),
        "doid_xrefs_loaded": len(doid_xrefs),
        "chebi_rels_loaded": len(chebi_rels),
        "umls_to_doid_mappings": len(umls_to_doid),
        "mesh_to_doid_mappings": len(mesh_to_doid),
        "mesh_cooccurrence_pairs": len(mesh_cooccurrence),
    }


def main():
    ap = argparse.ArgumentParser(description="External DB cross-validation for MCDM KG")
    ap.add_argument("--db", required=True, help="Path to microbiome_cdm.db")
    ap.add_argument("--disgenet", help="DisGeNET gene-disease TSV")
    ap.add_argument("--hgnc-map", help="HGNC→NCBI gene ID TSV")
    ap.add_argument("--mondo", help="mondo.obo file")
    ap.add_argument("--doid", help="doid.obo file")
    ap.add_argument("--chebi", help="chebi.obo file")
    ap.add_argument("--pubmed-meta", help="pubmed_metadata.json for MeSH co-occurrence")
    ap.add_argument("--report", help="JSON report output path")
    ap.add_argument("--apply", action="store_true", help="Write corroboration to DB")
    ap.add_argument("--dry-run", action="store_true", help="Don't modify DB")
    args = ap.parse_args()

    result = cross_validate(
        db_path=args.db,
        disgenet_path=args.disgenet,
        hgnc_path=args.hgnc_map,
        mondo_path=args.mondo,
        doid_path=args.doid,
        chebi_path=args.chebi,
        pubmed_meta_path=args.pubmed_meta,
        apply=args.apply,
        dry_run=args.dry_run,
    )

    print(f"\n{'='*60}")
    print(f"CROSS-VALIDATION RESULTS ({result['n_total']:,} relations)")
    print(f"{'='*60}")
    print(f"Corroborated: {result['n_corroborated']:,} ({result['corroboration_rate']*100:.1f}%)")
    print(f"Novel:        {result['n_novel']:,} ({(1-result['corroboration_rate'])*100:.1f}%)")
    print(f"\nPer external DB (corroborated / eligible):")
    for db, c in result["per_db"].items():
        elig = result["eligible_per_db"].get(db, 0)
        pct = c / max(elig, 1) * 100
        print(f"  {db:30s}: {c:6d} / {elig:6d} eligible ({pct:.1f}%)")

    print(f"\nPer predicate:")
    for p, c in sorted(result["per_predicate"].items()):
        cor = c.get("corroborated", 0)
        nov = c.get("novel", 0)
        tot = cor + nov
        print(f"  {p:30s}: cor={cor:6d}  nov={nov:6d}  ({cor/max(tot,1)*100:.1f}%)")

    if args.report:
        rp = Path(args.report)
        rp.parent.mkdir(parents=True, exist_ok=True)
        with open(rp, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"\nReport: {rp}")


if __name__ == "__main__":
    main()
