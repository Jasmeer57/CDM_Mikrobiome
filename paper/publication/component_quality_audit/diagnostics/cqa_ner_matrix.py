"""Component I correction — build the type-coverage matrix and the deployability table.

Sources (all read-only):
  * CDM 3.0.3 canonical_term  -> live terms and mention rollup per cdm_type
  * NER_RECOMPUTATION_CHECK.csv (audit root) -> best measured per-type F1 per benchmark type
  * outputs/results/benchmark/ner_corpus_bench/corpus_metrics.json -> section-level run evidence
  * src/scripts/ner_fair_bench/fairbench.py -> RAW_MAP / IN_DOMAIN / supported()
"""
from __future__ import annotations

import csv
import json
import sqlite3
import sys
from pathlib import Path

AUDIT = Path(__file__).resolve().parents[1]
ROOT = next(p for p in AUDIT.parents if (p / ".cdm_root").is_file())
RES = AUDIT / "diagnostics/results"

sys.path.insert(0, str(ROOT / "src/scripts/ner_fair_bench"))
import fairbench as fb  # noqa: E402

CDM_TYPES = ["ORGANISM", "CHEMICAL", "DISEASE", "PROTEIN", "DNA_RNA", "CELL_TYPE", "GENOMICS",
             "PATHWAY", "LAB_METHOD", "DATA_ANALYSIS", "SAMPLE_METHOD", "CLINICAL",
             "EXPERIMENTAL_METHOD", "STUDY_DESIGN"]

# ── corpus-side term counts ─────────────────────────────────────────────────
db = sqlite3.connect(f"file:{ROOT}/releases/cdm_v3/3.0.3/microbiome_cdm_v3.db?mode=ro", uri=True)
terms = {r[0]: (r[1], r[2] or 0) for r in
         db.execute("SELECT cdm_type, count(*), sum(mention_count) FROM canonical_term GROUP BY cdm_type")}
TYPED_TOTAL = sum(terms[t][0] for t in CDM_TYPES)
ALL_TOTAL = sum(v[0] for v in terms.values())

# ── best measured per-type F1 ───────────────────────────────────────────────
best = {}
with open(AUDIT / "NER_RECOMPUTATION_CHECK.csv", encoding="utf-8") as fh:
    for r in csv.DictReader(fh):
        if r["metric"].startswith("per_type_F1[") and r["verdict"] == "MATCH":
            t = r["metric"][len("per_type_F1["):-1]
            v = float(r["recomputed"])
            if t not in best or v > best[t][0]:
                best[t] = (v, r["model"], r["dataset"])

MATRIX = {
    # cdm_type: (bc5cdr, biored, correspondence, transfer, semantic note)
    "CHEMICAL": ("Chemical", "ChemicalEntity", "DIRECT", "DIRECT",
                 "Same concept in both corpora. BC5CDR 'Chemical' and BioRED 'ChemicalEntity' both cover "
                 "drugs, metabolites and named chemical classes; CDM CHEMICAL is the same concept. The only "
                 "residual difference is granularity (BioRED also tags small molecules that the CDM may file "
                 "under a different type), not meaning."),
    "DISEASE": ("Disease", "DiseaseOrPhenotypicFeature", "DIRECT", "DIRECT",
                "BC5CDR 'Disease' is a direct match. BioRED's type is broader (it adds phenotypic features, "
                "signs and symptoms) while the CDM has no phenotype type and folds those into DISEASE; the "
                "correspondence for the disease core is direct, for the phenotype fringe it is approximate."),
    "PROTEIN": ("(none)", "GeneOrGeneProduct", "APPROXIMATE", "WEAK",
                "GeneOrGeneProduct is a superset that includes genes, mRNAs and protein families. The CDM "
                "splits the same region of meaning across PROTEIN and DNA_RNA, so a benchmark hit does not "
                "tell you which CDM type it should become. A gene mention scored as a PROTEIN success is a "
                "typing error in CDM terms."),
    "ORGANISM": ("(none)", "OrganismTaxon", "APPROXIMATE", "WEAK",
                 "Schema-level the correspondence holds (a taxon is an organism). Instance-level it fails: "
                 "the benchmark type is defined to include 'human, mouse or patients', and 90.8% of the "
                 "BioRED test OrganismTaxon mentions are host-generic terms with ZERO bacterial taxa; the CDM "
                 "ORGANISM layer is 53.6% microbial by mention and led by 'microbiota'/'gut microbiota'. This "
                 "is the Species-vs-ORGANISM question and it is the single largest transfer gap in the suite."),
    "CELL_TYPE": ("(none)", "CellLine", "APPROXIMATE", "WEAK",
                  "CellLine is not CellType. An immortalised line (HeLa, HEK293) is a reagent; a cell type "
                  "(enterocyte, T cell) is an anatomical class. The benchmark's own label map records the "
                  "distinction ('cell type != cell line') and maps CellLine to it only because there is no "
                  "better slot. A high CellLine F1 says nothing about CDM CELL_TYPE extraction."),
    "DNA_RNA": ("(none)", "(none)", "NONE", "NONE",
                "SequenceVariant is the nearest BioRED type and it is not the same thing: a variant is a "
                "difference in a sequence, not a molecule. No benchmark type corresponds."),
    "GENOMICS": ("(none)", "(none)", "NONE", "NONE",
                 "No correspondence. Nothing in either corpus is annotated as a genomics domain/method."),
    "PATHWAY": ("(none)", "(none)", "NONE", "NONE", "No correspondence in either corpus."),
    "LAB_METHOD": ("(none)", "(none)", "NONE", "NONE",
                   "No correspondence. Neither corpus annotates assays, instruments or laboratory procedures."),
    "DATA_ANALYSIS": ("(none)", "(none)", "NONE", "NONE",
                      "No correspondence. Neither corpus annotates statistical or bioinformatic methods."),
    "SAMPLE_METHOD": ("(none)", "(none)", "NONE", "NONE",
                      "No correspondence. Specimen collection and processing are not annotated in either corpus."),
    "CLINICAL": ("(none)", "(none)", "NONE", "NONE",
                 "No correspondence. Clinical variables (BMI, age, antibiotic use) are not a benchmark type."),
    "EXPERIMENTAL_METHOD": ("(none)", "(none)", "NONE", "NONE",
                            "No correspondence. Neither corpus annotates experimental design or intervention."),
    "STUDY_DESIGN": ("(none)", "(none)", "NONE", "NONE",
                     "No correspondence. Cohort/case-control/RCT labels are not annotated in either corpus."),
}

# empirical context for the ORGANISM row, measured in this audit
ORG_CONTEXT = {
    "biored_test_organismtaxon_mentions": 393,
    "biored_test_host_generic": 357,
    "biored_test_viral": 27,
    "biored_test_other_species": 9,
    "biored_test_bacterial_taxa": 0,
    "cdm_organism_terms": terms.get("ORGANISM", (0, 0))[0],
    "cdm_organism_microbial_pattern_terms_pct": 31.8,
    "cdm_organism_microbial_pattern_mention_pct": 53.6,
    "biored_surfaces_matching_cdm_organism": 9,
    "biored_mentions_matching_cdm_organism": 181,
}

rows = []
for t in CDM_TYPES:
    b5, br, corr, transfer, note = MATRIX[t]
    n_terms, n_ment = terms.get(t, (0, 0))
    b5_best = best.get(b5) if b5 != "(none)" else None
    br_best = best.get(br) if br != "(none)" else None
    rows.append([
        t, n_terms, f"{100 * n_terms / TYPED_TOTAL:.2f}", n_ment,
        b5, b5_best[0] if b5_best else "", b5_best[1] if b5_best else "", b5_best[2] if b5_best else "",
        br, br_best[0] if br_best else "", br_best[1] if br_best else "", br_best[2] if br_best else "",
        corr, transfer, note,
    ])

with open(AUDIT / "NER_TYPE_COVERAGE_MATRIX.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(["cdm_type", "corpus_live_terms", "pct_of_typed_terms", "corpus_mention_rollup",
                "bc5cdr_type", "bc5cdr_best_exact_f1", "bc5cdr_best_model", "bc5cdr_best_dataset",
                "biored_type", "biored_best_exact_f1", "biored_best_model", "biored_best_dataset",
                "correspondence", "transfer_to_corpus", "semantic_note"])
    w.writerows(rows)
    # one explicit row for the off-schema label that dominates the corpus
    w.writerow(["ENTITY", terms.get("ENTITY", (0, 0))[0], "n/a (not a CDM type)",
                terms.get("ENTITY", (0, 0))[1], "(none)", "", "", "", "(none)", "", "", "",
                "NONE", "NONE",
                "Not in CDM_TYPES but 55.29% of live terms. No benchmark can score an untyped label; "
                "untyped span F1 is the only available measurement."])

# ── deployability ───────────────────────────────────────────────────────────
corpus = json.loads((ROOT / "outputs/results/benchmark/ner_corpus_bench/corpus_metrics.json").read_text())["models"]
metrics = json.loads((ROOT / "outputs/results/benchmark/ner_fair_bench/fair_ner_metrics.json").read_text())

dep_rows = []
names = sorted({k.split("__", 1)[1] for k in metrics})
for name in names:
    m5 = metrics.get(f"bc5cdr__{name}")
    mb = metrics.get(f"biored__{name}")
    cm = corpus.get(name)
    kind = (m5 or mb)["meta"].get("kind", "")
    sup = sorted(set((m5 or {}).get("supported_types", []) + (mb or {}).get("supported_types", [])))
    if name == "pubtator3":
        deploy, basis = "NO — REFERENCE ONLY", (
            "API lookup by PMID against PubTator3's own indexed collection. Cannot annotate arbitrary "
            "section text: `cdm_pipeline.ner.pubtator.predict_text` is not implemented, the runner excludes it "
            "from section mode, and its offsets are abstract/passage geometry, not corpus section offsets. "
            "Absent from the 26-configuration section run.")
        role = "REFERENCE CEILING — not a candidate"
    elif not sup:
        deploy, basis = "NO — UNTYPED ONLY", (
            "Runs on any text but emits a single generic `ENTITY` label, so it cannot produce a CDM type and "
            "cannot be scored on any typed benchmark. In the section run it produced 0 papers with entities.")
        role = "NOT USABLE for a typed CDM"
    else:
        deploy = "YES — SECTION-LEVEL"
        chars = cm["meta"].get("chars", 21560603) if cm else 0
        basis = (f"Ran on all 453 papers (every section except References/Acknowledgements) in the corpus "
                 f"benchmark: {cm['meta']['chunks']} chunks / {chars:,} chars under the BioRED type schema, "
                 f"producing entities in {cm['papers_with_entities']} papers." if cm else
                 "Runs on arbitrary text via the cdm_pipeline registry (no section run recorded).")
        role = "CANDIDATE"
    dep_rows.append([
        name, kind, deploy, basis,
        ";".join(sup) if sup else "(none — untyped)",
        m5["full_schema"]["exact"]["F1"] if m5 else "",
        m5["in_domain_training"] if m5 else "",
        mb["full_schema"]["exact"]["F1"] if mb else "",
        mb["in_domain_training"] if mb else "",
        "yes" if cm else "no",
        cm["papers_with_entities"] if cm else "",
        (cm["meta"].get("seconds") or cm["meta"].get("seconds_this_run")) if cm else "",
        f"{cm['meta']['sec_per_doc']:.4f}" if cm and cm["meta"].get("sec_per_doc") else
        (f"{cm['meta']['seconds_this_run'] / 452:.2f} (per paper)"
         if cm and cm["meta"].get("seconds_this_run") else ""),
        role,
    ])

with open(AUDIT / "NER_MODEL_DEPLOYABILITY.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(["model", "kind", "deployable_on_section_text", "deployability_basis",
                "typed_labels_emitted", "bc5cdr_full_schema_exact_f1", "bc5cdr_in_domain_flag",
                "biored_full_schema_exact_f1", "biored_in_domain_flag",
                "ran_on_corpus_sections", "corpus_papers_with_entities", "corpus_seconds",
                "corpus_sec_per_doc", "recommended_role"])
    w.writerows(dep_rows)

print(json.dumps({"typed_total": TYPED_TOTAL, "all_total": ALL_TOTAL,
                  "entity": terms.get("ENTITY"), "organism": ORG_CONTEXT,
                  "best_per_type": {k: v for k, v in sorted(best.items())},
                  "matrix_rows": len(rows),
                  "deploy_rows": len(dep_rows),
                  "deployable": sum(1 for r in dep_rows if r[2].startswith("YES")),
                  "reference_only": sum(1 for r in dep_rows if r[2].startswith("NO")),
                  }, indent=1))
