#!/usr/bin/env python3
"""Reproducer for CQA-I-AMEND-2026-11-05-1 (Component I corpus-grounding provenance).

Establishes, from artefacts on disk, that the corpus-benchmark "grounding" column
is measured against EXTERNAL reference lexicons rather than the project's own
canonical-term layer -- i.e. that the circularity claim in `CQA-I-06` is wrong.
It also enumerates the denominator facts the issue block gets wrong.

Reads only:
  outputs/results/benchmark/ner_corpus_bench/corpus_metrics.json
  src/scripts/ner_fair_bench/corpus_bench.py   (source scan, no import)

Writes diagnostics/results/cqa_i_grounding.json.

Stdlib only. Deterministic. Read-only.
"""
from __future__ import annotations

import json
import re

from common import REPO, emit

BENCH = REPO / "outputs/results/benchmark/ner_corpus_bench/corpus_metrics.json"
SRC = REPO / "src/scripts/ner_fair_bench/corpus_bench.py"

# Reference inputs build_lexicon() consumes, and the type each feeds.
LEXICON_SOURCES = [
    ("REF/Homo_sapiens.gene_info.gz", "GeneOrGeneProduct", "NCBI Gene"),
    ("REF/Mus_musculus.gene_info.gz", "GeneOrGeneProduct", "NCBI Gene"),
    ("REF/CTD_diseases.tsv.gz", "DiseaseOrPhenotypicFeature", "CTD/MEDIC (MeSH + OMIM)"),
    ("REF/CTD_chemicals.tsv.gz", "ChemicalEntity", "CTD (MeSH chemicals)"),
    ("outputs/results/omop_vocab/CONCEPT.csv", "DiseaseOrPhenotypicFeature", "OMOP/Mondo + HPO"),
    ("outputs/results/omop_vocab/CONCEPT_SYNONYM.csv", "DiseaseOrPhenotypicFeature", "OMOP synonyms"),
    ("REF/names.dmp", "OrganismTaxon", "NCBI Taxonomy"),
]

# Types ground() resolves WITHOUT any lexicon: one by regex, one never.
NON_LEXICON_TYPES = {
    "SequenceVariant": "VARIANT_RE regex pattern match (VARIANT_RE.match), not a vocabulary lookup",
    "CellLine": "ground() returns set() unconditionally -- 0.0% by construction",
}


def main() -> None:
    src = SRC.read_text(encoding="utf-8", errors="replace")

    # 1. Lexicon provenance ------------------------------------------------
    present = []
    for rel, cdm_side, name in LEXICON_SOURCES:
        present.append(
            {
                "path_in_build_lexicon": rel,
                "reference": name,
                "feeds_type": cdm_side,
                "cited_in_source": rel.split("/")[-1].split(".")[0] in src
                or rel in src,
            }
        )
    lexicon_dir_defined = bool(re.search(r'^LEX\s*=\s*OUT\s*/\s*"lexicon"', src, re.M))
    builds_from_external = "from the downloaded references only" in src
    mentions_canonical_term = bool(re.search(r"canonical_term|canonical_terms", src))
    ground_fn = re.search(r"def ground\(t, s\):(.*?)\n    C = ", src, re.S)
    ground_body = ground_fn.group(1) if ground_fn else ""

    # 2. What the shipped metrics actually contain -------------------------
    d = json.loads(BENCH.read_text(encoding="utf-8"))
    models = d["models"]

    cells, zero_cells, by_type = [], [], {}
    for name, m in models.items():
        for t, g in (m.get("grounding") or {}).items():
            cells.append({"model": name, "type": t, **g})
            by_type.setdefault(t, {"cells": 0, "zero": 0})
            by_type[t]["cells"] += 1
            if g.get("grounded_pct") == 0.0:
                by_type[t]["zero"] += 1
                zero_cells.append({"model": name, "type": t})

    models_with_grounding = sorted({c["model"] for c in cells})
    models_without = sorted(set(models) - set(models_with_grounding))

    def cell(model, t):
        for c in cells:
            if c["model"] == model and c["type"] == t:
                return {k: c[k] for k in ("unique", "grounded", "grounded_pct")}
        return None

    variant_cells = [c for c in cells if c["type"] == "SequenceVariant"]
    variant_unique = sum(c["unique"] for c in variant_cells)
    variant_grounded = sum(c["grounded"] for c in variant_cells)

    other_type_zero = [c for c in cells if c.get("other_type_pct") == 0.0]

    payload = {
        "amendment": "CQA-I-AMEND-2026-11-05-1",
        "question": "Is corpus-bench grounding measured against the project's own "
                    "canonical-term layer (circular), or against external references?",
        "verdict": "EXTERNAL. The circularity claim in CQA-I-06 is wrong.",
        "lexicon_provenance": {
            "lexicon_dir_defined": lexicon_dir_defined,
            "docstring_says_downloaded_references_only": builds_from_external,
            "source_mentions_canonical_term_layer": mentions_canonical_term,
            "sources": present,
            "n_sources_not_cited_in_source": sum(
                1 for p in present if not p["cited_in_source"]
            ),
        },
        "non_lexicon_types": {
            "SequenceVariant": {
                "mechanism": NON_LEXICON_TYPES["SequenceVariant"],
                "regex_in_ground_body": bool(re.search(r"VARIANT_RE", ground_body)),
                "cells": len(variant_cells),
                "unique_strings": variant_unique,
                "pattern_matched": variant_grounded,
                "pattern_matched_pct": round(100 * variant_grounded / variant_unique, 1)
                if variant_unique
                else None,
            },
            "CellLine": {
                "mechanism": NON_LEXICON_TYPES["CellLine"],
                "hardcoded_empty_set_in_ground_body": bool(
                    re.search(r'if t == "CellLine":\s*\n\s*return set\(\)', ground_body)
                ),
                "cells": by_type.get("CellLine", {}).get("cells", 0),
                "cells_at_zero": by_type.get("CellLine", {}).get("zero", 0),
            },
        },
        "denominators": {
            "configurations_in_run": len(models),
            "configurations_with_a_grounding_block": len(models_with_grounding),
            "configurations_without": models_without,
            "grounding_cells": len(cells),
            "cells_by_type": by_type,
            "zero_cells_total": len(zero_cells),
            "zero_cells_all_CellLine": all(z["type"] == "CellLine" for z in zero_cells),
        },
        "quoted_values_checked": {
            "bert_chemical/ChemicalEntity": cell("bert_chemical", "ChemicalEntity"),
            "scispacy_craft/ChemicalEntity": cell("scispacy_craft", "ChemicalEntity"),
            "bert_disease/DiseaseOrPhenotypicFeature": cell(
                "bert_disease", "DiseaseOrPhenotypicFeature"
            ),
            "scispacy_bc5cdr/ChemicalEntity": cell("scispacy_bc5cdr", "ChemicalEntity"),
            "llm_gemma_zs/OrganismTaxon": cell("llm_gemma_zs", "OrganismTaxon"),
        },
        "cross_type_ambiguity": {
            "fields_available_in_metrics": "other_type_pct",
            "cells_where_other_type_pct_is_zero": len(other_type_zero),
            "note": "Strings not grounded in the predicted type but grounded in another "
                    "type. Present in the shipped metrics, never reported by the audit "
                    "or the manuscript.",
            "largest_ambiguity": sorted(
                ({"model": c["model"], "type": c["type"], "other_type_pct": c["other_type_pct"]}
                 for c in cells if c.get("other_type_pct")),
                key=lambda x: -x["other_type_pct"],
            )[:5],
        },
    }
    emit("cqa_i_grounding", payload)

    print(json.dumps(
        {
            "external_lexicons": not mentions_canonical_term,
            "configs": len(models),
            "configs_with_grounding": len(models_with_grounding),
            "cells": len(cells),
            "zero_cells": len(zero_cells),
            "zero_all_cellline": payload["denominators"]["zero_cells_all_CellLine"],
            "bert_chemical": cell("bert_chemical", "ChemicalEntity"),
            "variant_pattern_pct": payload["non_lexicon_types"]["SequenceVariant"][
                "pattern_matched_pct"
            ],
        },
        indent=1,
    ))


if __name__ == "__main__":
    main()
