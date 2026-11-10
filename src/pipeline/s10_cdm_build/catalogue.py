"""Step 4: Build browsable data catalogue (JSON + CSV) and DB statistics."""
import csv
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone

from pipeline.config import CDM_TYPES, CDM_OUTPUT_DIR

OUT = CDM_OUTPUT_DIR


def build_catalogue(corpus, db_path):
    print("\n" + "=" * 60)
    print("STEP 4: Building data catalogue")
    print("=" * 60)

    # JSON catalogue
    by_type = defaultdict(list)
    for e in corpus["entities"]:
        by_type[e["entity_type"]].append(e)

    catalogue = {
        "name": "Microbiome CDM Data Catalogue",
        "version": "2.0.0",
        "created": datetime.now(timezone.utc).isoformat(),
        "source_papers": corpus["metadata"]["source_papers"],
        "total_entities": len(corpus["entities"]),
        "mapped_entities": corpus["metadata"]["entities_with_external_mapping"],
        "mapping_rate": round(100 * corpus["metadata"]["entities_with_external_mapping"] / len(corpus["entities"]), 1),
        "cdm_types": {},
        "vocabularies": Counter(),
        "top_entities_by_frequency": [],
        "top_entities_by_mapping": [],
    }

    for t in CDM_TYPES:
        ents = by_type.get(t, [])
        mapped = [e for e in ents if e["has_any_external_mapping"]]
        catalogue["cdm_types"][t] = {
            "total": len(ents),
            "mapped": len(mapped),
            "mapping_rate": round(100 * len(mapped) / len(ents), 1) if ents else 0,
            "top_terms": [e["entity"] for e in sorted(ents, key=lambda x: -x["paper_count"])[:20]],
        }

    for e in corpus["entities"]:
        canon = e.get("canonical_mapping")
        if canon:
            catalogue["vocabularies"][canon.get("ontology_name", "UNKNOWN")] += 1

    catalogue["top_entities_by_frequency"] = [
        {"term": e["entity"], "type": e["entity_type"],
         "paper_count": e["paper_count"], "occurrences": e["total_occurrences"],
         "mapped": e["has_any_external_mapping"],
         "canonical": e.get("canonical_mapping", {}).get("concept_id", "") if e.get("canonical_mapping") else ""}
        for e in sorted(corpus["entities"], key=lambda x: -x["paper_count"])[:100]
    ]

    mapped_entities = [e for e in corpus["entities"] if e["has_any_external_mapping"]]
    catalogue["top_entities_by_mapping"] = [
        {"term": e["entity"], "type": e["entity_type"],
         "canonical_vocab": e.get("canonical_mapping", {}).get("ontology_name", ""),
         "canonical_id": e.get("canonical_mapping", {}).get("concept_id", ""),
         "canonical_label": e.get("canonical_mapping", {}).get("label", ""),
         "confidence": e.get("canonical_mapping", {}).get("confidence", 0),
         "paper_count": e["paper_count"]}
        for e in sorted(mapped_entities, key=lambda x: -x.get("canonical_mapping", {}).get("confidence", 0))[:100]
    ]

    cat_path = OUT / "data_catalogue.json"
    with open(cat_path, "w", encoding="utf-8") as f:
        json.dump(catalogue, f, indent=2, ensure_ascii=False)
    print(f"  JSON catalogue saved to {cat_path}")

    # CSV catalogue
    csv_path = OUT / "data_catalogue.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "term", "entity_type", "paper_count", "total_occurrences",
            "has_mapping", "canonical_vocab", "canonical_id", "canonical_label",
            "mapping_confidence", "all_vocab_mappings",
        ])
        for e in corpus["entities"]:
            canon = e.get("canonical_mapping") or {}
            all_vocabs = "; ".join(
                f"{m.get('ontology_name', '')}:{m.get('concept_id', '')}"
                for m in (e.get("umls_mappings", []) + e.get("bioportal_mappings", []) +
                          e.get("ols_mappings", []) + e.get("omop_mappings", []) +
                          e.get("ncbi_taxon_mappings", []))
            )
            writer.writerow([
                e["entity"], e["entity_type"], e["paper_count"], e["total_occurrences"],
                e["has_any_external_mapping"],
                canon.get("ontology_name", ""), canon.get("concept_id", ""),
                canon.get("label", ""), canon.get("confidence", ""),
                all_vocabs,
            ])
    print(f"  CSV catalogue saved to {csv_path}")

    # ── DB stats from SQLite ──
    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()
    db_stats = {}
    c.execute("SELECT entity_type, COUNT(*) FROM entities GROUP BY entity_type ORDER BY COUNT(*) DESC")
    db_stats["entities_by_type"] = {r[0]: r[1] for r in c.fetchall()}

    c.execute("SELECT vocabulary_name, COUNT(*) FROM controlled_vocabularies GROUP BY vocabulary_name ORDER BY COUNT(*) DESC")
    db_stats["vocab_by_name"] = {r[0]: r[1] for r in c.fetchall()}

    c.execute("SELECT relationship_type, COUNT(*) FROM relationships GROUP BY relationship_type ORDER BY COUNT(*) DESC")
    db_stats["relationships_by_type"] = {r[0]: r[1] for r in c.fetchall()}

    c.execute("SELECT COUNT(DISTINCT project_id) FROM entity_project_mentions")
    db_stats["projects_with_mentions"] = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM projects WHERE title IS NOT NULL")
    db_stats["projects_with_metadata"] = c.fetchone()[0]

    conn.close()

    stats_path = OUT / "db_statistics.json"
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(db_stats, f, indent=2)
    print(f"  DB statistics saved to {stats_path}")

    # Print summary
    print(f"\n  CDM Type breakdown:")
    for t in CDM_TYPES:
        d = catalogue["cdm_types"].get(t, {})
        print(f"    {t:20s} {d.get('total', 0):5d} entities, {d.get('mapped', 0):5d} mapped ({d.get('mapping_rate', 0):.1f}%)")
    print(f"\n  Top vocabularies:")
    for v, cnt in catalogue["vocabularies"].most_common(15):
        print(f"    {v:20s} {cnt}")
    print(f"\n  Relationships:")
    for rt, cnt in db_stats["relationships_by_type"].items():
        print(f"    {rt:20s} {cnt}")

    return cat_path
