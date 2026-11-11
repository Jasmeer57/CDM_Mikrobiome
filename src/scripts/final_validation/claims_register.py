"""Manuscript claims register: every number in the draft, recomputed from frozen files and compared.

Each claim = (id, section, wording, stated value, how it is recomputed, source). Status:
MATCH | MISMATCH (stated != recomputed) | PENDING (result does not exist yet).

    python claims_register.py
"""
from __future__ import annotations

import csv
import re
import json
import sqlite3
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
CDM = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
OUT = ROOT / "paper/publication/final_validation"
c = sqlite3.connect(f"file:{CDM}?mode=ro", uri=True)


JV2 = "outputs/results/benchmark/judge_v2_2026-11-10/test/ANALYSIS.json"
TRV = "outputs/results/triple_retype_v2_2026-11-10/all_v25/SUMMARY.json"
RMS = "outputs/results/retype_merged_2026-11-10/SUMMARY.json"
LSC = "outputs/results/benchmark/judge_v2_2026-11-10/link_structural_check.json"

def q(sql):
    return c.execute(sql).fetchone()[0]


CDM310 = ROOT / "releases/cdm_v3/3.1.0/microbiome_cdm_v3.1.0.db"
c310 = sqlite3.connect(f"file:{CDM310}?mode=ro", uri=True) if CDM310.exists() else None


def q3(sql):
    return c310.execute(sql).fetchone()[0]


def lines(p):
    return sum(1 for _ in open(ROOT / p, encoding="utf-8"))


def js(p, *keys):
    d = json.load(open(ROOT / p))
    for k in keys:
        d = d[k]
    return d


CAT = "WHERE claim_source='catalogue_v3_1'"
VERB = "('EXACT','WHITESPACE','RELOCATED','NORMALISED')"
ALL_CAT = " UNION ALL ".join(f"SELECT evidence_anchor_status s FROM {t}" + (f" {CAT}" if t == "claim" else "")
                             for t in ("claim", "cohort", "sample", "assay", "dataset", "data_asset"))
CLAIMS = [
    ("C01", "Corpus", "papers", 453, lambda: q("SELECT COUNT(*) FROM paper"), "CDM 3.0.3 paper"),
    ("C02", "Corpus", "distinct publications", 447, lambda: q("SELECT COUNT(*) FROM publication"), "CDM 3.0.3 publication"),
    ("C03", "Corpus", "publications shared by several BioProjects", 5,
     lambda: q("SELECT COUNT(*) FROM publication WHERE n_bioprojects > 1"), "CDM 3.0.3 publication"),
    ("C04", "Corpus", "BioProjects sharing those publications", 11,
     lambda: q("SELECT SUM(n_bioprojects) FROM publication WHERE n_bioprojects > 1"), "CDM 3.0.3 publication"),
    ("C05", "Corpus", "compendium samples in corpus BioProjects (BioProject-level link)", 156330,
     lambda: js("outputs/audit/2026-11-02/audit_facts.json", "facts", "A.compendium_samples_linked", "value"),
     "recomputed from data/168000-samples-paper/sample_metadata.tsv (audit)"),
    ("C06", "Corpus", "compendium samples total", 168464,
     lambda: js("outputs/audit/2026-11-02/audit_facts.json", "facts", "A.compendium_samples_total", "value"), "audit"),
    ("C07", "Corpus", "sections", 4006, lambda: q("SELECT COUNT(*) FROM section"), "CDM 3.0.3 section"),
    ("C08", "Corpus", "section hashes mismatching text", "0/4006",
     lambda: js("outputs/audit/2026-11-02/audit_facts.json", "facts", "A.section_hash_mismatch", "value"), "audit"),
    ("C09", "Corpus", "share of compendium samples in corpus BioProjects (%)", 92.8,
     lambda: round(100 * js("outputs/audit/2026-11-02/audit_facts.json", "facts", "A.compendium_samples_linked", "value")
                   / js("outputs/audit/2026-11-02/audit_facts.json", "facts", "A.compendium_samples_total", "value"), 1), "audit"),
    ("C10", "Corpus", "sections by type Abstract/Introduction/Methods/Results/Discussion/Supplementary/Acknowledgements/References/Other",
     "247/216/385/379/482/239/431/385/1242",
     lambda: "/".join(str(q(f"SELECT COUNT(*) FROM section WHERE section_type='{t}'")) for t in
                      ("Abstract", "Introduction", "Methods", "Results", "Discussion", "Supplementary", "Acknowledgements", "References", "Other")),
     "CDM 3.0.3 section"),
    ("M01", "Mentions", "mention records in CDM", 2505684, lambda: q("SELECT COUNT(*) FROM term_mention"), "CDM 3.0.3"),
    ("M13", "Mentions", "mentions linked to a canonical term (%)", 87.8,
     lambda: round(100 * q("SELECT COUNT(*) FROM term_mention WHERE canonical_term_id IS NOT NULL AND canonical_term_id != ''")
                   / q("SELECT COUNT(*) FROM term_mention"), 1), "CDM"),
    ("M14", "Mentions", "mentions sharing a span id with another (dropped by the old one-row-per-id load)", 557625,
     lambda: q("SELECT COUNT(*) - COUNT(DISTINCT mention_id) FROM term_mention"), "CDM; VERIFICATION_303.json S3D"),
    ("K12", "Catalogue", "records findings/assays/sample groups/cohorts/datasets/data assets", "24272/8545/7530/7085/2976/1992",
     lambda: "/".join(str(q(f"SELECT COUNT(*) FROM {t}" + (f" {CAT}" if t == "claim" else "")))
                      for t in ("claim", "assay", "sample", "cohort", "dataset", "data_asset")), "CDM"),
    ("K13", "Catalogue", "G3 removals methods/cited/invalid/table-figure/wrong type/empty/reagent", "1264/945/127/103/71/49/27",
     lambda: "/".join(str(js("outputs/results/gap_runs/G3/catalogue/_G3_report.json", f"G3.removed.{k}")) for k in
                      ("METHODS_TEXT_NOT_A_RECORD", "CITED_OTHER_STUDY", "INVALID", "TABLE_OR_FIGURE_TEXT", "WRONG_ENTITY_TYPE",
                       "EMPTY_OR_MEANINGLESS", "REAGENT_OR_FILE")), "_G3_report.json"),
    ("K14", "Catalogue", "quote anchoring EXACT/WHITESPACE/RELOCATED/NORMALISED (%)", "15.1/58.0/5.9/9.3",
     lambda: "/".join(f"{100 * q(f'SELECT COUNT(*) FROM ({ALL_CAT}) WHERE s=' + repr(s)) / q(f'SELECT COUNT(*) FROM ({ALL_CAT})'):.1f}"
                      for s in ("EXACT", "WHITESPACE", "RELOCATED", "NORMALISED")), "CDM"),
    ("L01", "LLM-judge suppl.", "BERT chemical: valid and correctly typed, distinct (%)", 59.3, lambda: lj("benchmark", "bert_chemical"), "llm_judge summary.json"),
    ("L02", "LLM-judge suppl.", "GLiNER v2.5 medium: valid and correctly typed (%)", 43.6, lambda: lj("benchmark", "gliner_v25_medium"), "llm_judge summary.json"),
    ("L03", "LLM-judge suppl.", "best LLM (Gemma zero-shot): valid and correctly typed (%)", 35.5, lambda: lj("benchmark", "llm_gemma_zs"), "llm_judge summary.json"),
    ("L04", "LLM-judge suppl.", "lowest (Llama zero-shot): valid and correctly typed (%)", 15.7, lambda: lj("benchmark", "llm_llama_zs"), "llm_judge summary.json"),
    ("L05", "LLM-judge suppl.", "en_core_sci_lg (generic ENTITY source): valid distinct strings (%)", 9.4, lambda: lj("cdm_models", "en_core_sci_lg", "valid"), "llm_judge summary.json"),
    ("L06", "LLM-judge suppl.", "MeSH gazetteer / BioBERT-diseases: valid (%)", "67.3/60.9",
     lambda: f'{lj("cdm_models", "mesh-gazetteer", "valid")}/{lj("cdm_models", "biobert_diseases", "valid")}', "llm_judge summary.json"),
    ("L07", "LLM-judge suppl.", "Qwen3.5-4B vLLM / Ollama valid distinct; vLLM mention-weighted (%)", "34.5/36.6/50.7",
     lambda: f'{lj("cdm_models", "Qwen/Qwen3.5-4B", "valid")}/{lj("cdm_models", "qwen3.5:4b", "valid")}/{lj("cdm_models", "Qwen/Qwen3.5-4B", "valid", "mentions")}', "llm_judge summary.json"),
    ("L08", "LLM-judge suppl.", "CDM types valid: chemical/data analysis/disease/experimental method/study design (%)", "44.3/43.1/42.8/14.1/16.1",
     lambda: "/".join(str(x) for x in lj_types(("CHEMICAL", "DATA_ANALYSIS", "DISEASE", "EXPERIMENTAL_METHOD", "STUDY_DESIGN"))), "llm_judge entity_verdicts"),
    ("L09", "LLM-judge suppl.", "triples judged well-formed claims (%)", 39.3, lambda: ljt("WY"), "llm_judge summary.json"),
    ("L10", "LLM-judge suppl.", "triples with valid subject and object (%)", 38.7, lambda: ljt("EY"), "llm_judge summary.json"),
    ("L11", "LLM-judge suppl.", "triples with specific relation label (%)", 12.5, lambda: ljt("SY"), "llm_judge summary.json"),
    ("L12", "LLM-judge suppl.", "triples with too-generic relation label (%)", 29.5, lambda: ljt("SG"), "llm_judge summary.json"),
    ("L13", "LLM-judge suppl.", "items judged: benchmark pairs / CDM pairs / total", "345693/358714/730195",
     lambda: lj_counts(), "llm_judge items.jsonl"),
    ("L14", "LLM-judge suppl.", "items omitted in first pass and re-requested", 272,
     lambda: int(re.findall(r"'missing': (\d+)", open(ROOT / "outputs/results/benchmark/llm_judge_deepseek_v4_flash/judge_run.log").read())[-1]),
     "llm_judge judge_run.log"),
    ("L15", "LLM-judge suppl.", "cleaned layer: triples to relabel / with CC BY sentence / direction swapped / relabelled to ASSOCIATED_WITH",
     "6733/4012/408/1758", lambda: cleaned_counts(), "cleaned_layer_deepseek"),
    ("N01", "BugSigDB suppl.", "papers / signatures in both CDM 3.0.3 and BugSigDB", "47/270",
     lambda: f'{bs("papers")}/{bs("signatures")}', "bugsigdb_comparison summary.json"),
    ("N02", "BugSigDB suppl.", "BugSigDB taxa covered by catalogue findings, exact or same genus / cross-paper chance (%)", "27.7/9.0",
     lambda: f'{bsp("taxa", "catalogue", "coverage")}/{bsp("taxa", "catalogue", "coverage_chance")}', "bugsigdb_comparison summary.json"),
    ("N03", "BugSigDB suppl.", "BugSigDB taxa covered, exact NCBI ID (%)", 23.5,
     lambda: float(bsp("taxa", "catalogue", "exact_coverage")), "bugsigdb_comparison summary.json"),
    ("N04", "BugSigDB suppl.", "our taxa also in BugSigDB / cross-paper chance (%)", "57.3/18.1",
     lambda: f'{bsp("taxa", "catalogue", "support_rate")}/{bsp("taxa", "catalogue", "support_chance")}', "bugsigdb_comparison summary.json"),
    ("N05", "BugSigDB suppl.", "same direction (%) / determinable pairs / base-rate chance (%)", "77.0/261/52.0",
     lambda: f'{bsp("taxa", "catalogue", "direction_same")}/{bs("taxa", "catalogue", "direction_determinable")}/'
             f'{bsp("taxa", "catalogue", "posthoc_direction_chance")}', "bugsigdb_comparison summary.json"),
    ("N06", "BugSigDB suppl.", "coverage by BugSigDB signature source: text / table / figure / supplement (%)", "100.0/51.4/27.6/22.1",
     lambda: "/".join(bsp("taxa", "catalogue", "posthoc_coverage_by_source", k, "coverage") for k in ("Text", "Table", "Figure", "Supplement")),
     "bugsigdb_comparison summary.json"),
    ("N07", "BugSigDB suppl.", "metadata concordance: 16S region / country / statistical test / group size (%)", "97.7/94.0/85.7/56.2",
     lambda: "/".join(bsp("fields", k, "concordance") for k in ("region_16s", "country", "statistical_test", "group_size")),
     "bugsigdb_comparison summary.json"),
    ("N08", "BugSigDB suppl.", "condition (SapBERT) / group name (SapBERT) / body site (lexical) concordance (%)", "92.7/54.2/84.2",
     lambda: f'{bsp("fields", "condition", "concordance")}/{bsp("fields", "group_name", "concordance")}/{bsp("fields", "body_site", "lexical_match")}',
     "bugsigdb_comparison summary.json"),
    ("N09", "BugSigDB suppl.", "post-hoc strict set equality: sequencing type / platform / statistical test (%)", "50.0/89.4/3.6",
     lambda: "/".join(bsp("fields", k, "posthoc_strict_set_equal") for k in ("sequencing_type", "platform", "statistical_test")),
     "bugsigdb_comparison summary.json"),
    ("N10", "BugSigDB suppl.", "taxon IDs not in current NCBI Taxonomy: BugSigDB overlap / of / BugSigDB all / of / our findings",
     "8/668/71/8479/0",
     lambda: "/".join(str(x) for x in (bs("ontology_currency", "bugsigdb_overlap", "absent_from_snapshot"),
                                       bs("ontology_currency", "bugsigdb_overlap", "distinct_taxa"),
                                       bs("ontology_currency", "bugsigdb_full_dump", "absent_from_snapshot"),
                                       bs("ontology_currency", "bugsigdb_full_dump", "distinct_taxa"),
                                       bs("ontology_currency", "cdm_findings_absent_from_snapshot"))),
     "bugsigdb_comparison summary.json"),
    ("N11", "BugSigDB suppl.", "answer-template records / bootstrap replicates / adjudicated disagreements / our value in text",
     "2989/2000/11/10", lambda: bs_adj(), "bugsigdb_comparison items.jsonl + scoring_schema.json"),
    ("XR01", "Triple ref. suppl.", "taxon triples checked against BugSigDB: (triple, paper) items / papers", "518/45",
     lambda: f'{tr("bugsigdb", "items")}/{tr("bugsigdb", "papers_with_items")}', "triple_reference_check summary.json"),
    ("XR02", "Triple ref. suppl.", "taxon of the triple in BugSigDB signatures of the same paper / chance (%)", "50.4/16.1",
     lambda: f'{trp("bugsigdb", "support", "all", "rate")}/{trp("bugsigdb", "support_chance")}', "triple_reference_check summary.json"),
    ("XR03", "Triple ref. suppl.", "BugSigDB support: kept / dropped by DeepSeek cleaning / difference (points)", "54.3/44.3/10.0",
     lambda: f'{trp("bugsigdb", "support", "kept", "rate")}/{trp("bugsigdb", "support", "dropped", "rate")}/'
             f'{trp("bugsigdb", "support_effect", "kept_minus_dropped")}', "triple_reference_check summary.json"),
    ("XR04", "Triple ref. suppl.", "direction agreement with BugSigDB: same / determinable", "11/12",
     lambda: f'{tr("bugsigdb", "direction_original", "k")}/{tr("bugsigdb", "direction_original", "n")}', "triple_reference_check summary.json"),
    ("XR05", "Triple ref. suppl.", "chemical-disease triples resolved / any CTD support (%) / chance (%)", "49/22.4/24.2",
     lambda: f'{tr("ctd_chemical_disease", "items")}/{trp("ctd_chemical_disease", "any_support", "all", "rate")}/'
             f'{trp("ctd_chemical_disease", "chance_any")}', "triple_reference_check summary.json"),
    ("XR06", "Triple ref. suppl.", "gene-disease triples resolved / curated in CTD", "7/0",
     lambda: f'{tr("ctd_gene_disease", "items")}/{tr("ctd_gene_disease", "curated", "all", "k")}', "triple_reference_check summary.json"),
    ("F01", "Figures", "CDM entities: populated / partially populated / planned", "17/15/1",
     lambda: "/".join(str(fx("cdm", "status", k)) for k in ("POPULATED_EXISTING", "PARTIAL_POPULATED", "PLANNED")),
     "manuscript_bib/figures/extra_figures_facts.json"),
    ("F02", "Figures", "CDM entities without a table of their own (embedded)", 5,
     lambda: len(fx("cdm", "embedded")), "manuscript_bib/figures/extra_figures_facts.json"),
    ("F03", "Figures", "genus x condition cells comparable with independent BugSigDB consensus: same / total (exploratory)", "25/44",
     lambda: f'{fx("F", "same")}/{fx("F", "cells_compared")}', "manuscript_bib/figures/extra_figures_facts.json"),
    ("Q01", "KG suppl.", "KG nodes / edges: full; cleaned", "22579/25788;8897/9682",
     lambda: f'{kgs("full", "nodes")}/{kgs("full", "edges")};{kgs("cleaned", "nodes")}/{kgs("cleaned", "edges")}', "kg_2026-11-04 kg_stats.json"),
    ("Q02", "KG suppl.", "largest connected component share: full / cleaned (%)", "68.5/67.8",
     lambda: f'{100 * kgs("full", "largest_component_share"):.1f}/{100 * kgs("cleaned", "largest_component_share"):.1f}', "kg_2026-11-04 kg_stats.json"),
    ("Q03", "KG suppl.", "triples judged against their CC BY/CC0 sentence / eligible", "16132/16142",
     lambda: f'{evs("judged")}/{evs("items")}', "kg evidence_check summary.json"),
    ("Q04", "KG suppl.", "sentence states a relationship / original label supported / supported or generic (%)", "86.6/22.0/80.2",
     lambda: f'{evp("R_stated")}/{evp("A_supported")}/{evp("A_supported_or_partial")}', "kg evidence_check summary.json"),
    ("Q05", "KG suppl.", "original label supported: kept / dropped by cleaning (%)", "30.6/17.2",
     lambda: f'{evp("kept")}/{evp("dropped")}', "kg evidence_check summary.json"),
    ("Q06", "KG suppl.", "relabelled triples supported: original / cleaned label (%)", "17.2/50.4",
     lambda: f'{100 * evs("relabelled", "A_supported", "rate"):.1f}/{100 * evs("relabelled", "B_supported", "rate"):.1f}', "kg evidence_check summary.json"),
    ("Q07", "KG suppl.", "microbe-disease edges resolved / in Disbiome or BugSigDB (%) / chance (%)", "622/13.2/5.8",
     lambda: f'{gks("microbe_disease", "resolved_edges")}/{100 * gks("microbe_disease", "support", "rate"):.1f}/{100 * gks("microbe_disease", "chance"):.1f}',
     "kg gold_kg_check summary.json"),
    ("Q08", "KG suppl.", "microbe-disease edges in a reference: kept / dropped by cleaning (%)", "15.5/6.4",
     # from k/n, not from the stored 4-decimal rate (0.1545 -> 15.4 was a double rounding of 72/466 = 15.45%)
     lambda: f'{100 * gks("microbe_disease", "kept", "k") / gks("microbe_disease", "kept", "n"):.1f}/'
             f'{100 * gks("microbe_disease", "dropped", "k") / gks("microbe_disease", "dropped", "n"):.1f}', "kg gold_kg_check summary.json"),
    ("Q09", "KG suppl.", "chemical-disease edges resolved / in CTD (%) / chance (%)", "202/11.4/9.8",
     lambda: f'{gks("chemical_disease", "resolved_edges")}/{100 * gks("chemical_disease", "support", "rate"):.1f}/{100 * gks("chemical_disease", "chance"):.1f}',
     "kg gold_kg_check summary.json"),
    ("H07", "Benchmark", "highest corpus grounding of any configuration and type (%)", 41.3,
     lambda: max(g["grounded_pct"] for m in js("outputs/results/ner_corpus_bench/corpus_metrics.json", "models").values()
                 for g in (m.get("grounding") or {}).values()), "corpus_metrics.json"),
    ("M02", "Mentions", "mention rows in terminology 1.0.1", 2505735, lambda: lines("releases/terminology/1.0.1/term_mentions.jsonl"),
     "terminology 1.0.1"),
    ("M03", "Mentions", "cpu_ensemble_v1 mentions", 1705449, lambda: q("SELECT COUNT(*) FROM term_mention WHERE extraction_run_id='cpu_ensemble_v1'"), "CDM"),
    ("M04", "Mentions", "qwen35_vllm_body_v1 mentions", 366123, lambda: q("SELECT COUNT(*) FROM term_mention WHERE extraction_run_id='qwen35_vllm_body_v1'"), "CDM"),
    ("M05", "Mentions", "qwen_ollama_cell7c_v1 mentions", 186024, lambda: q("SELECT COUNT(*) FROM term_mention WHERE extraction_run_id='qwen_ollama_cell7c_v1'"), "CDM"),
    ("M06", "Mentions", "mesh_gazetteer_2026 mentions", 248088, lambda: q("SELECT COUNT(*) FROM term_mention WHERE extraction_run_id='mesh_gazetteer_2026'"), "CDM"),
    ("M07", "Mentions", "mentions with offsets", 2505628, lambda: q("SELECT COUNT(*) FROM term_mention WHERE start_offset IS NOT NULL"), "CDM"),
    ("M08", "Mentions", "offsets corrected (CDM)", 156870, lambda: q("SELECT COUNT(*) FROM term_mention WHERE offset_status='CORRECTED'"), "CDM"),
    ("M09", "Mentions", "unanchored mentions (CDM)", 56, lambda: q("SELECT COUNT(*) FROM term_mention WHERE offset_status='UNANCHORED'"), "CDM"),
    ("M10", "Mentions", "mentions linked to a canonical term", 2198766,
     lambda: q("SELECT COUNT(*) FROM term_mention WHERE term_link_status IN ('LINKED','LINKED_BY_TYPE')"), "CDM"),
    ("M11", "Mentions", "ambiguous mentions", 7072, lambda: q("SELECT COUNT(*) FROM term_mention WHERE term_link_status='AMBIGUOUS'"), "CDM"),
    ("M12", "Mentions", "mentions without canonical term", 299846, lambda: q("SELECT COUNT(*) FROM term_mention WHERE term_link_status='NO_CANONICAL_TERM'"), "CDM"),
    ("T01", "Terms", "canonical terms in terminology 1.0.1", 165991, lambda: lines("releases/terminology/1.0.1/canonical_terms.jsonl"), "terminology 1.0.1"),
    ("T02", "Terms", "canonical terms in CDM 3.0.3 (after review)", 162409, lambda: q("SELECT COUNT(*) FROM canonical_term"), "CDM"),
    ("T03", "Terms", "terms removed by review", 3582, lambda: q("SELECT COUNT(*) FROM removed_canonical_term"), "CDM"),
    ("T04", "Terms", "T02 + T03 = T01", 165991, lambda: q("SELECT (SELECT COUNT(*) FROM canonical_term)+(SELECT COUNT(*) FROM removed_canonical_term)"), "CDM"),
    ("T05", "Terms", "terms typed ENTITY", 89799, lambda: q("SELECT COUNT(*) FROM canonical_term WHERE cdm_type='ENTITY'"), "CDM"),
    ("T06", "Terms", "terms with taxonomy category (AGREED+PARENT_AGREED)", 37740,
     lambda: q("SELECT COUNT(*) FROM taxonomy_annotation WHERE agreement_status IN ('AGREED','PARENT_AGREED')"), "CDM"),
    ("D01", "Definitions", "definitions in CDM", 6773, lambda: q("SELECT COUNT(*) FROM term_definition"), "CDM"),
    ("D02", "Definitions", "terms with a definition", 3397, lambda: q("SELECT COUNT(DISTINCT term_id) FROM term_definition"), "CDM"),
    ("D03", "Definitions", "definitions exact at offsets", 6460, lambda: q("SELECT COUNT(*) FROM term_definition WHERE evidence_anchor_status='EXACT'"), "CDM"),
    ("P01", "Mappings", "candidates retrieved (before guards)", 334231,
     lambda: js("releases/frozen_output/02_data_catalogue/terminology/mapping_guards_v2/guard_summary.json", "rows_total"), "guard_summary.json"),
    ("P02", "Mappings", "candidates kept by guards", 314772, lambda: q("SELECT COUNT(*) FROM term_concept_map WHERE guard_status='kept'"), "CDM"),
    ("P03", "Mappings", "candidates rejected by guards", 16622, lambda: q("SELECT COUNT(*) FROM term_concept_map WHERE guard_status='rejected_guard'"), "CDM"),
    ("P04", "Mappings", "candidates demoted by guards (not loaded into the CDM)", 2837,
     lambda: lines("releases/frozen_output/02_data_catalogue/terminology/mapping_guards_v2/mapping_demoted.jsonl"), "guard files"),
    ("P05", "Mappings", "mapping rows ACCEPTED by two-model agreement", 18272,
     lambda: q("SELECT COUNT(*) FROM term_concept_map WHERE mapping_disposition_reviewed='ACCEPTED'"), "CDM"),
    ("P06", "Mappings", "terms with an ACCEPTED mapping", 16750,
     lambda: q("SELECT COUNT(DISTINCT term_id) FROM term_concept_map WHERE mapping_disposition_reviewed='ACCEPTED'"), "CDM"),
    ("P07", "Mappings", "mapping rows with no recorded service", 11477, lambda: q("SELECT COUNT(*) FROM term_concept_map WHERE source_service_mapping IS NULL"), "CDM"),
    ("K01", "Catalogue", "catalogue records", 52400,
     lambda: sum(q(f"SELECT COUNT(*) FROM {t}" + (f" {CAT}" if t == "claim" else "")) for t in ("claim", "cohort", "sample", "assay", "dataset", "data_asset")), "CDM"),
    ("K02", "Catalogue", "findings", 24272, lambda: q(f"SELECT COUNT(*) FROM claim {CAT}"), "CDM"),
    ("K03", "Catalogue", "G1 values accepted", 21403, lambda: js("outputs/results/gap_runs/G1/catalogue/_G1_report.json", "G1.filled"), "G1 report"),
    ("K04", "Catalogue", "G1 proposals rejected by validators", 76253,
     lambda: sum(v for k, v in js("outputs/results/gap_runs/G1/catalogue/_G1_report.json").items() if k.startswith("G1.rejected")), "G1 report"),
    ("K05", "Catalogue", "NOT_REPORTED values in release", 46182,
     lambda: js("outputs/audit/2026-11-02/audit_facts.json", "facts", "C.missing_codes", "value", "NOT_REPORTED"), "audit (catalogue 3.1.1)"),
    ("K06", "Catalogue", "CONFLICTING values in release", 4586,
     lambda: js("outputs/audit/2026-11-02/audit_facts.json", "facts", "C.missing_codes", "value", "CONFLICTING"), "audit"),
    ("K07", "Catalogue", "records removed by G3", 2586,
     lambda: sum(1 for l in open(ROOT / "releases/data_catalogue_v3/3.1.1/provenance/_removed.jsonl")
                 if '"REMOVED:G3_' in l), "_removed.jsonl"),
    ("K08", "Catalogue", "quotes verbatim (%)", 88.2, lambda: round(100 * q(f"SELECT AVG(s IN {VERB}) FROM ({ALL_CAT})"), 1), "CDM"),
    ("K09", "Catalogue", "quotes approximate FUZZY (%)", 8.0, lambda: round(100 * q(f"SELECT AVG(s='FUZZY') FROM ({ALL_CAT})"), 1), "CDM"),
    ("K10", "Catalogue", "quotes unlocated or absent (%)", 3.8,
     lambda: round(100 * q(f"SELECT AVG(s IN ('UNANCHORED','NO_EVIDENCE')) FROM ({ALL_CAT})"), 1), "CDM"),
    ("K11", "Catalogue", "datasets without section (BioProject-derived)", 142, lambda: q("SELECT COUNT(*) FROM dataset WHERE COALESCE(section_id,'')=''"), "CDM"),
    ("X01", "CDM", "tables", 44, lambda: q("SELECT COUNT(*) FROM sqlite_master WHERE type='table'"), "CDM"),
    ("X02", "CDM", "columns", 866, lambda: sum(len(c.execute(f'PRAGMA table_info("{t}")').fetchall())
                                              for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()), "CDM"),
    ("X03", "CDM", "registered runs", 45, lambda: q("SELECT COUNT(*) FROM extraction_run"), "CDM"),
    ("X04", "CDM", "runs not independently verified (AS_IN_3.0.2_UNVERIFIED)", 4,
     lambda: q("SELECT COUNT(*) FROM extraction_run WHERE verification='AS_IN_3.0.2_UNVERIFIED'"), "CDM"),
    ("X05", "CDM", "change-log entries 3.0.2 -> 3.0.3", 79, lambda: q("SELECT COUNT(*) FROM cdm_change_log"), "CDM"),
    ("X06", "CDM", "rows whose run id does not resolve (all run-bearing tables)", 0,
     lambda: sum(q(f"SELECT COUNT(*) FROM {t} WHERE COALESCE(extraction_run_id,'') NOT IN (SELECT extraction_run_id FROM extraction_run)")
                 for t in ("term_mention", "term_definition", "cohort", "sample", "assay", "dataset", "data_asset", "relation",
                           "taxonomy_annotation", "term_concept_map", "type_harmonization"))
     + q("SELECT COUNT(*) FROM claim WHERE COALESCE(extraction_run_id, extraction_run_id_recovered) NOT IN (SELECT extraction_run_id FROM extraction_run)"), "CDM"),
    ("X07", "CDM", "validation tests pass / fail / conditional", "118/2/1",
     lambda: "/".join(str(js("releases/cdm_v3/3.0.3/remediation/VERIFICATION_303.json", "validation_proposed_registry", k))
                      for k in ("PASS", "FAIL", "CONDITIONAL")), "VERIFICATION_303.json"),
    ("X08", "CDM", "3.0.3 verification overall", True, lambda: js("releases/cdm_v3/3.0.3/remediation/VERIFICATION_303.json", "pass"), "VERIFICATION_303.json"),
    ("R01", "Triples", "relation triples", 25788, lambda: q("SELECT COUNT(*) FROM relation"), "CDM"),
    ("R02", "Triples", "generic (escape) relations", 17717, lambda: q("SELECT COUNT(*) FROM relation WHERE relation_family='escape'"), "CDM"),
    ("R03", "Triples", "triples with conflicting polarity across mentions", 195, lambda: q("SELECT COUNT(*) FROM relation WHERE polarity_agreement='conflicting'"), "CDM"),
    ("B01", "Benchmark", "BC5CDR best (PubTator3) exact F1", 90.1,
     lambda: round(100 * js("outputs/results/ner_fair_bench/fair_ner_metrics.json", "bc5cdr__pubtator3", "full_schema", "exact", "F1"), 1), "fair_ner_metrics.json"),
    ("B02", "Benchmark", "BioRED best (HunFlair2) exact F1", 80.6,
     lambda: round(100 * js("outputs/results/ner_fair_bench/fair_ner_metrics.json", "biored__hunflair2", "full_schema", "exact", "F1"), 1), "fair_ner_metrics.json"),
    ("B03", "Benchmark", "BC5CDR best LLM (Qwen 3-shot) exact F1", 69.5,
     lambda: round(100 * js("outputs/results/ner_fair_bench/fair_ner_metrics.json", "bc5cdr__llm_qwen_fs", "full_schema", "exact", "F1"), 1), "fair_ner_metrics.json"),
    ("B04", "Benchmark", "BioRED best LLM (Qwen 3-shot) exact F1", 66.2,
     lambda: round(100 * js("outputs/results/ner_fair_bench/fair_ner_metrics.json", "biored__llm_qwen_fs", "full_schema", "exact", "F1"), 1), "fair_ner_metrics.json"),
    ("B05", "Benchmark", "public benchmark configurations", 27,
     lambda: len({k.split("__", 1)[1] for k in json.load(open(ROOT / "outputs/results/ner_fair_bench/fair_ner_metrics.json"))}), "fair_ner_metrics.json"),
    ("V01", "Validation", "source-first: accessions in text also in catalogue (%)", 88.7,
     lambda: js("paper/publication/final_validation/source_first/coverage_summary.json", "accessions", "share_of_source_facts_in_catalogue_pct"), "coverage_summary.json"),
    ("V02", "Validation", "source-first: platforms (%)", 89.2,
     lambda: js("paper/publication/final_validation/source_first/coverage_summary.json", "platforms", "share_of_source_facts_in_catalogue_pct"), "coverage_summary.json"),
    ("V03", "Validation", "source-first: 16S regions (%)", 72.1,
     lambda: js("paper/publication/final_validation/source_first/coverage_summary.json", "regions_16S", "share_of_source_facts_in_catalogue_pct"), "coverage_summary.json"),
    ("H01", "Validation", "human-annotated items", "NONE (no human annotation performed)", None, "—"),
    ("E01", "Validation", "deterministic: text values found in evidence (%)", 70.5, lambda: det_pct("text_in_evidence"), "deterministic_summary.json"),
    ("E02", "Validation", "deterministic: counts found in evidence (%)", 75.4, lambda: det_pct("count_in_evidence"), "deterministic_summary.json"),
    ("J01", "Validation", "Llama: text values judged FAIL (% of valid labels)", 2.9, lambda: judge_pct("llama", "FAIL"), "judge_summary.json"),
    ("J02", "Validation", "Mistral: text values judged FAIL (% of valid labels)", 6.6, lambda: judge_pct("mistral", "FAIL"), "judge_summary.json"),
    ("J03", "Validation", "Mistral rubric compliance on text values", 0.554, lambda: js(JS, "rubric_compliance_text_values", "mistral"), "judge_summary.json"),
    ("J04", "Validation", "judge observed agreement, both-valid pairs", 0.85, lambda: js(JS, "judge_agreement_text_values_both_valid", "observed_agreement"), "judge_summary.json"),
    ("J05", "Validation", "Cohen's kappa between the two model judges", 0.282, lambda: js(JS, "judge_agreement_text_values_both_valid", "cohen_kappa_between_models"), "judge_summary.json"),
    ("J06", "Validation", "values failed by both judges", 2023, lambda: js(JS, "judge_agreement_text_values_both_valid", "both_fail"), "judge_summary.json"),
    ("J07", "Validation", "gap-filled values judged FAIL by Mistral (%)", 19.1, lambda: src_pct("mistral", "gap_filled"), "judge_summary.json"),
    ("J08", "Validation", "original values judged FAIL by Mistral (%)", 5.6, lambda: src_pct("mistral", "original_extraction"), "judge_summary.json"),
    ("H03", "Benchmark", "corpus benchmark configurations", 26, lambda: len(js("outputs/results/ner_corpus_bench/corpus_metrics.json", "models")), "corpus_metrics.json"),
    ("H04", "Benchmark", "Spearman BioRED F1 vs corpus grounding, disease", 0.749,
     lambda: js(BA, "public_vs_corpus", "correlation", "DiseaseOrPhenotypicFeature", "spearman_f1_vs_grounding"), "benchmark_analysis.json"),
    ("H05", "Benchmark", "Spearman BioRED F1 vs corpus grounding, organism", 0.023,
     lambda: js(BA, "public_vs_corpus", "correlation", "OrganismTaxon", "spearman_f1_vs_grounding"), "benchmark_analysis.json"),
    # Decision guide (BiB Table 3), 2026-11-06: best BioRED configuration per entity type, exact F1 / 95% bootstrap CI,
    # and the per-type Spearman values not registered before. Facts: outputs/results/benchmark/decision_guide_facts_2026-11-06/
    ("G01", "Decision guide", "BioRED disease best (HunFlair2, not trained on BioRED): exact F1 / CI low / CI high (%)",
     "86.6/83.0/89.8", lambda: ptf("biored", "hunflair2", "DiseaseOrPhenotypicFeature"), "fair_ner_metrics.json"),
    ("G02", "Decision guide", "BioRED chemical best (PubTator3, trained in-domain): exact F1 / CI low / CI high (%)",
     "88.8/83.7/93.0", lambda: ptf("biored", "pubtator3", "ChemicalEntity"), "fair_ner_metrics.json"),
    ("G03", "Decision guide", "BioRED gene/protein best (HunFlair2, not trained on BioRED): exact F1 / CI low / CI high (%)",
     "83.3/79.6/86.5", lambda: ptf("biored", "hunflair2", "GeneOrGeneProduct"), "fair_ner_metrics.json"),
    ("G04", "Decision guide", "BioRED organism best (HunFlair2, not trained on BioRED): exact F1 / CI low / CI high (%)",
     "94.4/90.8/97.3", lambda: ptf("biored", "hunflair2", "OrganismTaxon"), "fair_ner_metrics.json"),
    ("G05", "Decision guide", "BioRED variant best (PubTator3, trained in-domain): exact F1 / CI low / CI high (%)",
     "82.3/72.2/89.2", lambda: ptf("biored", "pubtator3", "SequenceVariant"), "fair_ner_metrics.json"),
    ("G06", "Decision guide", "BioRED cell line best (PubTator3, trained in-domain): exact F1 / CI low / CI high (%)",
     "80.8/50.9/96.5", lambda: ptf("biored", "pubtator3", "CellLine"), "fair_ner_metrics.json"),
    ("G07", "Decision guide", "Spearman BioRED F1 vs corpus grounding, gene/protein", 0.2,
     lambda: js(BA, "public_vs_corpus", "correlation", "GeneOrGeneProduct", "spearman_f1_vs_grounding"), "benchmark_analysis.json"),
    ("G08", "Decision guide", "Spearman BioRED F1 vs corpus grounding, chemical", 0.252,
     lambda: js(BA, "public_vs_corpus", "correlation", "ChemicalEntity", "spearman_f1_vs_grounding"), "benchmark_analysis.json"),
    ("G09", "Decision guide", "Spearman BioRED F1 vs corpus grounding, variant", 0.112,
     lambda: js(BA, "public_vs_corpus", "correlation", "SequenceVariant", "spearman_f1_vs_grounding"), "benchmark_analysis.json"),
    # Triple-vs-sentence LLM screen of 2026-11-07 (DeepSeek-V4.1-Flash, Genie gateway), CC BY / CC0 sentences only,
    # and the rights accounting of that run. Facts: outputs/results/benchmark/triple_evidence_ccby_2026-11-07/
    ("W01", "Triple screen", "sentences sent to the Genie gateway: total / CC BY or CC0 / other licences", "25714/16085/9629",
     lambda: f'{tes("rights_sent_sentences", "total")}/{tes("rights_sent_sentences", "cc_by_or_cc0")}/{tes("rights_sent_sentences", "other")}',
     "triple_evidence_ccby summary.json"),
    ("W02", "Triple screen", "triples judged against a CC BY/CC0 sentence (2026-11-07 rubric)", 16032,
     lambda: tes("ccby_subset", "triples_judged"), "triple_evidence_ccby summary.json"),
    ("W03", "Triple screen", "sentence supports / partially / does not / conflicts (%)", "56.0/22.6/18.2/3.3",
     lambda: "/".join(f'{100 * tes("ccby_subset", "distribution", l, "rate"):.1f}' for l in ("SUPPORTED", "PARTIAL", "NOT_SUPPORTED", "CONFLICTS")),
     "triple_evidence_ccby summary.json"),
    ("W04", "Triple screen", "SUPPORTED: specific predicate / generic OTHER_RELATION (%)", "54.8/56.5",
     lambda: f'{100 * tes("ccby_subset", "by_predicate_kind", "specific_predicate", "SUPPORTED", "rate"):.1f}/'
             f'{100 * tes("ccby_subset", "by_predicate_kind", "generic_predicate", "SUPPORTED", "rate"):.1f}',
     "triple_evidence_ccby summary.json"),
    ("W05", "Triple screen", "triples judged by both runs / Q04-partial (P) triples now SUPPORTED", "16022/5360",
     lambda: f'{tes("reconciliation_with_2026_11_03", "overlap_triples")}/'
             f'{tes("reconciliation_with_2026_11_03", "crosstab_old_A_rows_new_support_columns", "P", "SUPPORTED")}',
     "triple_evidence_ccby summary.json"),
    # Rights layers of the corpus (licence check per paper, Europe PMC / PMC records) and the public Zenodo build.
    # Facts: paper/publication/rights/PAPER_RIGHTS_MATRIX.csv, releases/zenodo_frozen/ (added 2026-11-09).
    ("RT01", "Rights", "papers licence-checked / text included (CC BY, CC0) / NC layer / text withheld", "453/274/15/164",
     lambda: "/".join(str(x) for x in rts()), "PAPER_RIGHTS_MATRIX.csv"),
    ("RT02", "Rights", "papers whose text is not redistributed: total / no licence found / CC BY-NC-ND / CC BY-NC / CC BY-NC-SA",
     "179/135/29/12/3", lambda: "/".join(str(x) for x in rts_split()), "PAPER_RIGHTS_MATRIX.csv"),
    ("RT03", "Rights", "public build: text values emptied / table-columns redacted / unexplained rights-scan hits",
     "2103395/263/0", lambda: zen(), "zenodo_frozen RELEASE_REDACTION_LOG.csv + VERIFICATION_RIGHTS_SCAN.json"),
    ("RT04", "Rights", "FhGenie triple-label judge (2026-11-07): labels sent / withheld-only / of these >= 50 chars", "51576/6477/1460",
     lambda: "/".join(str(x) for x in (js("outputs/results/rights/B24_EXTERNAL_PROCESSING_ADDENDUM_2026-11-10.json", "deepseek_v41_judge_triple_labels", "labels", "strings"),
                                        js("outputs/results/rights/B24_EXTERNAL_PROCESSING_ADDENDUM_2026-11-10.json", "deepseek_v41_judge_triple_labels", "labels", "withheld_only"),
                                        js("outputs/results/rights/B24_EXTERNAL_PROCESSING_ADDENDUM_2026-11-10.json", "deepseek_v41_judge_triple_labels", "labels", "by_band", ">=50|withheld_only"))), "B24 addendum 2026-11-10"),
    ("RT05", "Rights", "FhGenie term-relevance screen (2026-11-09): labels sent / withheld-only / of these >= 50 chars", "157990/13138/877",
     lambda: "/".join(str(x) for x in (js("outputs/results/rights/B24_EXTERNAL_PROCESSING_ADDENDUM_2026-11-10.json", "term_relevance_screen", "labels", "strings"),
                                        js("outputs/results/rights/B24_EXTERNAL_PROCESSING_ADDENDUM_2026-11-10.json", "term_relevance_screen", "labels", "withheld_only"),
                                        js("outputs/results/rights/B24_EXTERNAL_PROCESSING_ADDENDUM_2026-11-10.json", "term_relevance_screen", "labels", "by_band", ">=50|withheld_only"))), "B24 addendum 2026-11-10"),
    ("RT06", "Rights", "definitions layer: terms with a model field holding a withheld span / quoted source definitions from non-open papers",
     "2061/1422",
     lambda: "/".join(str(js("outputs/results/rights/B24_EXTERNAL_PROCESSING_ADDENDUM_2026-11-10.json", "definitions_layer_rights_check", "counts", k)) for k in ("any_model_field", "source_definitions")),
     "B24 addendum 2026-11-10"),
    # CDM 3.1.0 (frozen 2026-11-10; = 3.0.3 + cleaned / enriched / repaired layers as new tables; lead approval pending)
    ("CL01", "CDM 3.1.0", "canonical terms: 3.0.3 / after dedup / kept after relevance filter", "162409/157815/116755",
     lambda: cl("SELECT count(*) FROM canonical_term", "SELECT count(*) FROM term_curation",
                "SELECT count(*) FROM term_curation WHERE kept='True'"), "CDM 3.1.0 term_curation"),
    ("CL02", "CDM 3.1.0", "accepted concepts: IRIs / after ID normalisation / after dedup / kept", "13330/12657/12182/11912",
     lambda: cl("SELECT count(*) FROM concept_curie_map", "SELECT count(DISTINCT curie) FROM concept_curie_map",
                "SELECT count(*) FROM concept_curation", "SELECT count(*) FROM concept_curation WHERE kept='True'"),
     "CDM 3.1.0 concept_curie_map, concept_curation"),
    ("CL03", "CDM 3.1.0", "accepted mappings: 3.0.3 rows / clean rows", "18272/15769",
     lambda: cl("SELECT count(*) FROM term_concept_map WHERE mapping_disposition_reviewed='ACCEPTED'",
                "SELECT count(*) FROM term_concept_map_clean"), "CDM 3.1.0 term_concept_map_clean"),
    ("CL04", "CDM 3.1.0", "accepted mappings by agreed relation: EXACT / BROADER / NARROWER / RELATED", "13540/598/1313/2821",
     lambda: cl(*["SELECT count(*) FROM term_concept_map WHERE mapping_disposition_reviewed='ACCEPTED' AND relation_llm_g9='%s'" % r
                  for r in ("EXACT", "BROADER", "NARROWER", "RELATED")]), "CDM 3.1.0 term_concept_map"),
    ("CL05", "CDM 3.1.0", "triples with a specific relation and verified cue / generic triples now specific / old specific labels confirmed",
     "8307/3966/4117",
     lambda: cl("SELECT count(*) FROM triple_tier WHERE specific_relation='True' AND cue_found='True'",
                "SELECT count(*) FROM triple_tier WHERE old_relation='OTHER_RELATION' AND specific_relation='True' AND cue_found='True'",
                "SELECT count(*) FROM triple_tier WHERE old_relation!='OTHER_RELATION' AND relation=old_relation"),
     "CDM 3.1.0 triple_tier"),
    ("CL06", "CDM 3.1.0", "triple tiers 1 / 2 / 3", "1794/6263/17731",
     lambda: cl(*["SELECT count(*) FROM triple_tier WHERE tier='%d'" % t for t in (1, 2, 3)]), "CDM 3.1.0 triple_tier"),
    ("CL07", "CDM 3.1.0", "triples: no specific relation stated / not supported / null finding", "14867/1207/93",
     lambda: cl(*["SELECT count(*) FROM triple_tier WHERE relation='%s'" % r
                  for r in ("NO_SPECIFIC_RELATION_STATED", "NOT_SUPPORTED", "NULL_FINDING")]), "CDM 3.1.0 triple_tier"),
    ("CL08", "CDM 3.1.0", "model definitions: contextual / general / non-concept description (of 162,409 terms)", "120091/530/41779",
     lambda: cl(*["SELECT count(*) FROM term_enrichment WHERE MODEL_definition_kind='%s'" % k
                  for k in ("CONTEXTUAL", "GENERAL", "NON_CONCEPT")]), "CDM 3.1.0 term_enrichment"),
    ("CL09", "CDM 3.1.0", "accepted mappings with ontology definition / model description / none", "13325/4912/35",
     lambda: cl(*["SELECT count(*) FROM mapping_enrichment WHERE concept_definition_final_origin='%s'" % k
                  for k in ("ONTOLOGY", "MODEL_GENERATED", "NONE")]), "CDM 3.1.0 mapping_enrichment"),
    ("CL10", "CDM 3.1.0", "terms found only by en_core_sci_lg / of these typed ENTITY / accepted-mapping terms among them",
     "74729/74700/0", lambda: sci_only(), "CDM 3.0.3 canonical_term.models"),
    ("CL11", "CDM 3.1.0", "catalogue judges, schema-enforced: Mistral invalid (%) / all-pairs observed / kappa / PASS-FAIL PABAK",
     "0.1/0.802/0.293/0.847", lambda: judges_constrained(), "judge_format_analysis_constrained summary.json"),
    ("CL12", "CDM 3.1.0", "triples with a specific relation after repair / of these with a verified cue", "9621/8307",
     lambda: "/".join(str(js("outputs/results/triple_repair_2026-11-09/TIERS_SUMMARY.json", k)) for k in ("specific_after_repair", "specific_after_repair_with_cue")), "triple_repair TIERS_SUMMARY.json"),
    ("CL13", "Triples (post-3.1.0)", "triple dedup: triples in / distinct / clean (junk endpoints, self-loops dropped) / clean with a specific relation",
     "25788/25470/23339/8967",
     lambda: "/".join(str(x) for x in (js("outputs/results/triple_dedup_2026-11-10/summary.json", "triples_in"), js("outputs/results/triple_dedup_2026-11-10/summary.json", "distinct_triples"), js("outputs/results/triple_dedup_2026-11-10/summary.json", "clean", "triples"),
                                        js("outputs/results/triple_dedup_2026-11-10/summary.json", "specific_relation", "clean"))), "triple_dedup_2026-11-10 summary.json (not in 3.1.0)"),
    ("CL14", "Triples (post-3.1.0)", "clean triples without a specific relation (%)", 61.6,
     lambda: round(100 * (1 - js("outputs/results/triple_dedup_2026-11-10/summary.json", "specific_relation", "clean") / js("outputs/results/triple_dedup_2026-11-10/summary.json", "clean", "triples")), 1),
     "triple_dedup_2026-11-10 summary.json (not in 3.1.0)"),
    ("CL15", "CDM 3.1.0", "catalogue judges, schema-enforced: Gwet AC1 3-label / AC1 PASS-FAIL / specific agreement PASS / FAIL / 3-label PABAK",
     "0.771/0.913/0.959/0.39/0.704",
     lambda: "/".join(str(x) for x in (js("outputs/results/benchmark/judge_format_analysis_constrained_2026-11-09/agreement_extended.json", "three_label", "gwet_ac1"), js("outputs/results/benchmark/judge_format_analysis_constrained_2026-11-09/agreement_extended.json", "pass_vs_fail_both_decided", "gwet_ac1"),
                                        js("outputs/results/benchmark/judge_format_analysis_constrained_2026-11-09/agreement_extended.json", "pass_vs_fail_both_decided", "specific_agreement", "PASS"),
                                        js("outputs/results/benchmark/judge_format_analysis_constrained_2026-11-09/agreement_extended.json", "pass_vs_fail_both_decided", "specific_agreement", "FAIL"),
                                        js("outputs/results/benchmark/judge_format_analysis_constrained_2026-11-09/agreement_extended.json", "three_label", "pabak"))), "agreement_extended.json"),
    ("X09", "CDM", "test S4 (dataset_id pattern): non-matching ids / of these BioProject-link rows HMDATA_BP_", "142/142",
     lambda: "/".join(str(js("paper/publication/final_validation/X07_TEST_EXCEPTIONS_2026-11-10.json", "S4", k)) for k in ("failing_ids", "failing_ids_that_are_BioProject_links")), "X07_TEST_EXCEPTIONS json"),
    ("X10", "CDM", "test S9 (one storage type): text values in the 4 integer columns / of these not empty or a missing-data code",
     "11578/0",
     lambda: "/".join(str(sum(v[k] for v in js("paper/publication/final_validation/X07_TEST_EXCEPTIONS_2026-11-10.json", "S9", "columns").values())) for k in ("text_values", "text_values_not_missing_codes")),
     "X07_TEST_EXCEPTIONS json"),
    # rubric-v2 catalogue judges, test split (2026-11-10; new model run, lead approval pending)
    ("JV01", "Judges v2", "test split, Llama x Mistral: observed agreement / Cohen kappa / FAIL specific agreement; same records under the 2026-11-09 rubric: kappa / FAIL agreement",
     "0.829/0.566/0.598/0.361/0.33",
     lambda: "/".join(str(x) for x in (js(JV2, "verified", "all", "pairwise", "llama|mistral", "observed"), js(JV2, "verified", "all", "pairwise", "llama|mistral", "kappa"),
                                        js(JV2, "verified", "all", "pairwise", "llama|mistral", "specific_agreement", "FAIL"),
                                        js(JV2, "v1_constrained_same_records", "kappa"), js(JV2, "v1_constrained_same_records", "specific_agreement", "FAIL"))), "judge_v2 test ANALYSIS.json"),
    ("JV02", "Judges v2", "test split, three judges: Fleiss kappa all fields / stated / classification / label fields / blind classification answers",
     "0.471/0.535/0.409/0.068/0.616",
     lambda: "/".join(str(x) for x in (js(JV2, "verified", "all", "fleiss_kappa"), js(JV2, "verified", "stated", "fleiss_kappa"), js(JV2, "verified", "classify", "fleiss_kappa"),
                                        js(JV2, "verified", "label", "fleiss_kappa"), js(JV2, "classify_blind_answers", "fleiss_kappa"))), "judge_v2 test ANALYSIS.json"),
    ("JV03", "Re-typing", "ENTITY terms re-typed: total / to one of the 14 CDM types / to proposed extension types / NOT_A_CONCEPT",
     "53780/40113/8856/4811",
     lambda: "/".join(str(js("outputs/results/entity_retype_2026-11-10/all/SUMMARY.json", k)) for k in ("terms", "core_14_types", "proposed_extension_types", "not_a_concept")),
     "entity retype SUMMARY.json"),
    ("JV04", "Re-typing", "unspecific triples re-typed (v2.5): total / verified specific / NOT_SUPPORTED / REVERSED direction",
     "14867/5257/6832/195",
     lambda: "/".join(str(x) for x in (js(TRV, "triples"), js(TRV, "specific_verified"), js(TRV, "relations", "NOT_SUPPORTED"), js(TRV, "direction_reversed"))),
     "triple retype v2.5 SUMMARY.json"),
    ("JV05", "Re-typing", "triples after re-typing over 3.1.0: specific and cue-verified / % / not supported / association without direction / null finding",
     "13564/52.6/8039/1708/915",
     lambda: "/".join(str(js(RMS, "triples", k)) for k in ("specific_cue_verified_after_retype", "specific_cue_verified_after_retype_pct",
                                                             "not_supported", "association_unsigned", "null_finding")), "retype_merged SUMMARY.json"),
    ("JV06", "Re-typing", "kept terms after re-typing: total / generic ENTITY before / after / in the 14 CDM types / %",
     "116755/53780/0/103088/88.3",
     lambda: "/".join(str(js(RMS, "terms", k)) for k in ("kept", "generic_entity_before", "generic_entity_after", "in_14_cdm_types_after",
                                                           "in_14_cdm_types_after_pct")), "retype_merged SUMMARY.json"),
    ("JV07", "Judges v2", "test split: judgeable records / judges / Gwet AC1 Llama x Mistral / record links checked / broken",
     "51837/3/0.788/167197/0",
     lambda: "/".join(str(x) for x in (js(JV2, "records_judged", "llama"), len(js(JV2, "judges")), js(JV2, "verified", "all", "pairwise", "llama|mistral", "gwet_ac1"),
                                        sum(js(LSC, "total").values()), sum(v for k, v in js(LSC, "total").items() if not k.startswith("VALID")))),
     "judge_v2 test ANALYSIS.json; link_structural_check.json"),
    ("JV08", "Judges v2", "test split, stated values: failed by a majority of judges / values judged / %",
     "33253/254022/13.1",
     lambda: "/".join(str(x) for x in (js(JV2, "verified", "stated", "majority", "FAIL"), js(JV2, "verified", "stated", "fields"),
                                        round(100 * js(JV2, "verified", "stated", "majority", "FAIL") / js(JV2, "verified", "stated", "fields"), 1))),
     "judge_v2 test ANALYSIS.json"),
    ("JV09", "Re-typing", "constructed test sets: terms typed correctly / terms / sentences given the expected relation / sentences",
     "19/20/17/17",
     lambda: "/".join(str(js("outputs/results/entity_retype_2026-11-10/GOLD_CHECK.json", "summary", k))
                      for k in ("entities_correct", "entities", "triples_correct", "triples")), "GOLD_CHECK.json"),
    ("H06", "Benchmark", "Disbiome associations recovered by GLiNER v2.5 biomed", 1456,
     lambda: js("outputs/results/ner_corpus_bench/corpus_metrics.json", "models", "gliner_v25_biomed", "kg", "microbe_disease", "distinct_known_associations"), "corpus_metrics.json"),
]

LJ = "outputs/results/benchmark/llm_judge_deepseek_v4_flash/summary.json"


def lj(group, name, field="valid_type", kind="distinct"):
    d = js(LJ, group, name, kind)
    return round(100 * d[field] / d["d"], 1)


BS = "outputs/results/benchmark/bugsigdb_comparison_2026-11-03/summary.json"


TR = "outputs/results/benchmark/triple_reference_check_2026-11-03/summary.json"


def kgs(*keys):
    return js("outputs/results/kg_2026-11-04/kg_stats.json", *keys)


def evs(*keys):
    return js("outputs/results/kg_2026-11-04/evidence_check/summary.json", *keys)


def evp(key):
    return f"{100 * evs(key, 'rate'):.1f}"


def gks(*keys):
    return js("outputs/results/kg_2026-11-04/gold_kg_check/summary.json", "edge_types", *keys)


def _rights():
    return list(csv.DictReader(open(ROOT / "paper/publication/rights/PAPER_RIGHTS_MATRIX.csv", encoding="utf-8")))


def rts():
    r = _rights()
    d = [x["proposed_release_decision"] for x in r]
    return len(r), d.count("INCLUDE_TEXT"), d.count("RESTRICTED_NC_LAYER"), d.count("WITHHOLD_TEXT")


def rts_split():
    r = [x for x in _rights() if x["proposed_release_decision"] != "INCLUDE_TEXT"]
    lic = [x["licence"].lower() for x in r]
    return len(r), lic.count("none_found"), lic.count("cc by-nc-nd"), lic.count("cc by-nc"), lic.count("cc by-nc-sa")


def zen():
    log = list(csv.DictReader(open(ROOT / "releases/zenodo_frozen/RELEASE_REDACTION_LOG.csv", encoding="utf-8")))
    scan = json.load(open(ROOT / "releases/zenodo_frozen/VERIFICATION_RIGHTS_SCAN.json", encoding="utf-8"))
    return f'{sum(int(x["values_emptied"] or 0) for x in log)}/{len(log)}/{scan["unexplained_hits"]}'



def cl(*sqls):
    return "/".join(str(q3(x)) for x in sqls)


def sci_only():
    sel = 'models=\'["en_core_sci_lg"]\''
    return "/".join(str(q(x)) for x in (
        "SELECT count(*) FROM canonical_term WHERE " + sel,
        "SELECT count(*) FROM canonical_term WHERE " + sel + " AND cdm_type='ENTITY'",
        "SELECT count(DISTINCT m.term_id) FROM term_concept_map m JOIN canonical_term t USING(term_id) "
        "WHERE m.mapping_disposition_reviewed='ACCEPTED' AND t." + sel))


def judges_constrained():
    d = json.load(open(ROOT / "outputs/results/benchmark/judge_format_analysis_constrained_2026-11-09/summary.json"))
    return f'{d["mistral"]["invalid_pct"]}/{d["all_pairs"]["observed"]}/{d["all_pairs"]["kappa"]}/{d["pass_vs_fail_both_decided"]["pabak"]}'


def tes(*keys):
    return js("outputs/results/benchmark/triple_evidence_ccby_2026-11-07/summary.json", *keys)


def fx(*keys):
    return js("paper/publication/manuscript_bib/figures/extra_figures_facts.json", *keys)


def tr(*keys):
    return js(TR, *keys)


def trp(*keys):
    return f"{100 * tr(*keys):.1f}"


def bs(*keys):
    return js(BS, *keys)


def bs_adj():
    items = [json.loads(l) for l in open(ROOT / BS.replace("summary.json", "items.jsonl"), encoding="utf-8")]
    adj = [i["adjudication"] for i in items if i["adjudication"]]
    reps = js("src/scripts/bugsigdb_comparison/scoring_schema.json", "uncertainty", "bootstrap", "replicates")
    return f'{len(items)}/{reps}/{len(adj)}/{sum(a in ("BOTH_IN_TEXT", "OURS_ONLY_IN_TEXT") for a in adj)}'


def bsp(*keys):
    return f"{100 * bs(*keys):.1f}"


def lj_counts():
    from collections import Counter
    c = Counter()
    for l in open(ROOT / "outputs/results/benchmark/llm_judge_deepseek_v4_flash/items.jsonl", encoding="utf-8"):
        d = json.loads(l)
        c[d.get("scheme", "triple")] += 1
    return f'{c["biored"]}/{c["cdm"]}/{sum(c.values())}'


def cleaned_counts():
    import gzip
    d = ROOT / "outputs/results/cleaned_layer_deepseek"
    rl = [json.loads(l) for l in open(d / "relabel.jsonl", encoding="utf-8")]
    with gzip.open(d / "cleaned_triples.csv.gz", "rt", encoding="utf-8") as fh:
        assoc = sum(1 for r in csv.DictReader(fh) if r["kept"] == "1" and r["relation_cleaned"] == "ASSOCIATED_WITH"
                    and r["relation_original"] != "ASSOCIATED_WITH")
    return f'{len(rl)}/{sum(r["had_sentence"] for r in rl)}/{sum(r["swap"] for r in rl)}/{assoc}'


def ljt(code):
    t = js(LJ, "triples")
    return round(100 * t[code] / t["n"], 1)


def lj_types(types):
    import gzip
    c = {t: [0, 0] for t in types}
    with gzip.open(ROOT / "outputs/results/benchmark/llm_judge_deepseek_v4_flash/entity_verdicts.csv.gz", "rt", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["scheme"] == "cdm" and r["proposed_type"] in c and r["valid"] in ("Y", "N"):
                c[r["proposed_type"]][0] += r["valid"] == "Y"
                c[r["proposed_type"]][1] += 1
    return [round(100 * a / b, 1) for a, b in (c[t] for t in types)]


JS = "paper/publication/final_validation/evidence_judge/judge_summary.json"
BA = "paper/publication/final_validation/benchmark/benchmark_analysis.json"


def ptf(dataset, prog, typ):
    """Per-type exact F1 and its 95% bootstrap CI, in %, as 'F1/low/high'."""
    t = js("outputs/results/ner_fair_bench/fair_ner_metrics.json", f"{dataset}__{prog}", "per_type", typ)
    return "/".join(f"{100 * x:.1f}" for x in (t["exact"]["F1"], t["ci"][0], t["ci"][1]))


def det_pct(kind):
    d = js("paper/publication/final_validation/evidence_judge/deterministic_summary.json")
    f = sum(v.get("FOUND", 0) for k, v in d.items() if k.endswith(kind))
    n = sum(v.get("NOT_FOUND", 0) for k, v in d.items() if k.endswith(kind))
    return round(100 * f / (f + n), 1)


def _pct(c, label):
    valid = sum(n for k, n in c.items() if k != "INVALID")
    return round(100 * c.get(label, 0) / valid, 1)


def judge_pct(model, label):
    from collections import Counter
    c = Counter()
    for k, v in js(JS, model, "fields").items():
        if k.endswith("|text_value"):
            c.update(v)
    return _pct(c, label)


def src_pct(model, src):
    return _pct(js(JS, model, "text_value_by_source", src), "FAIL")


def main():
    from collections import Counter as _C
    dup = [k for k, n in _C(c[0] for c in CLAIMS).items() if n > 1]
    if dup:
        raise SystemExit(f"duplicate claim ids: {dup}")
    rows = []
    for cid, sec, what, stated, fn, src in CLAIMS:
        if fn is None:
            rows.append({"claim_id": cid, "section": sec, "claim": what, "stated": stated, "recomputed": "", "status": "PENDING" if stated == "PENDING" else "STATEMENT", "source": src})
            continue
        try:
            v = fn()
        except Exception as ex:  # noqa: BLE001
            v = f"ERROR {ex!r}"[:120]
        ok = (abs(float(v) - float(stated)) < 0.051) if isinstance(stated, (int, float)) and not isinstance(stated, bool) and isinstance(v, (int, float)) else str(v) == str(stated)
        rows.append({"claim_id": cid, "section": sec, "claim": what, "stated": stated, "recomputed": v,
                     "status": "MATCH" if ok else "MISMATCH", "source": src})
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "MANUSCRIPT_CLAIMS_REGISTER.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    from collections import Counter
    print(Counter(r["status"] for r in rows))
    for r in rows:
        if r["status"] == "MISMATCH":
            print(r)


if __name__ == "__main__":
    main()
