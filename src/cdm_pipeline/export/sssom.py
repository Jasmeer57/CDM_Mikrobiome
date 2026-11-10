"""SSSOM (Simple Standard for Sharing Ontological Mappings) export.

Reads controlled_vocabularies from the CDM SQLite DB and writes a
TSV file conforming to the SSSOM 1.0 specification.

Usage:
    python -m cdm_pipeline.export.sssom --db cdm_output/microbiome_cdm.db --out cdm_output/mappings.sssom.tsv
"""
import argparse
import sqlite3
from datetime import date
from pathlib import Path

from ..config import CDM_OUTPUT_DIR

SSSOM_HEADER = [
    "subject_id",
    "subject_label",
    "predicate_id",
    "object_id",
    "object_label",
    "mapping_justification",
    "confidence",
    "mapping_source",
    "subject_type",
    "is_canonical",
]


def export_sssom(db_path: Path, out_path: Path):
    """Export controlled_vocabularies table to SSSOM TSV.

    subject_id  = CDM entity term (local:term)
    object_id   = vocabulary_uri (or vocabulary_name:vocabulary_id)
    predicate   = skos:exactMatch / skos:closeMatch based on confidence
    """
    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()

    rows = c.execute("""
        SELECT e.term, e.entity_type,
               cv.vocabulary_name, cv.vocabulary_id, cv.vocabulary_uri,
               cv.vocabulary_label, cv.mapping_confidence, cv.mapping_source,
               cv.is_canonical
        FROM controlled_vocabularies cv
        JOIN entities e ON cv.entity_id = e.id
        ORDER BY e.entity_type, e.term
    """).fetchall()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        # SSSOM metadata block (commented lines starting with #)
        f.write(f"# sssom_version: 1.0\n")
        f.write(f"# mapping_set_id: microbiome-cdm/mappings/{date.today().isoformat()}\n")
        f.write(f"# license: CC-BY-4.0\n")
        f.write(f"# subject_source: Microbiome-CDM\n")
        f.write(f"# mapping_set_description: "
                f"Ontology mappings for the Microbiome Common Data Model "
                f"({len(rows)} mappings)\n")
        f.write("#\n")
        f.write("\t".join(SSSOM_HEADER) + "\n")
        for term, etype, vocab_name, vocab_id, vocab_uri, vocab_label, conf, source, canonical in rows:
            subject_id = f"MicrobiomeCDM:{term.replace(' ', '_')}"
            if vocab_uri:
                object_id = vocab_uri
            elif vocab_id:
                object_id = f"{vocab_name}:{vocab_id}"
            else:
                object_id = f"{vocab_name}:{vocab_label}"
            predicate = "skos:exactMatch" if (conf or 0) >= 0.85 else "skos:closeMatch"
            justification = "semapv:ManualMappingCuration" if source and "kb" in source.lower() else "semapv:LexicalMatching"
            f.write("\t".join([
                subject_id,
                term,
                predicate,
                object_id,
                vocab_label or "",
                justification,
                f"{conf:.3f}" if conf else "",
                source or "",
                etype or "",
                "true" if canonical else "false",
            ]) + "\n")

    conn.close()
    print(f"SSSOM export: {len(rows)} mappings → {out_path}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Export CDM mappings to SSSOM TSV")
    p.add_argument("--db", type=Path, default=CDM_OUTPUT_DIR / "microbiome_cdm.db")
    p.add_argument("--out", type=Path, default=CDM_OUTPUT_DIR / "mappings.sssom.tsv")
    args = p.parse_args()
    export_sssom(args.db, args.out)
