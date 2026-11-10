"""Combine the pipeline flowchart, the results reference and every registered number into one Markdown file.

    python src/scripts/final_validation/build_pipeline_and_numbers.py [--out FILE]

Sources (copied, not rewritten): docs/reports/pipeline_flowchart.md (rev 3),
paper/publication/submission_readiness/RESULTS_REFERENCE_2026-11-06.md, and the register tables produced by
register_to_markdown.py (regenerated first). Adds the 2026-11-08/09 work and a verification table for every number
that is not a register row. Reference notes for the authors, not manuscript text.
"""
from __future__ import annotations

import argparse
import csv
import datetime
import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
FLOW = ROOT / "docs/reports/pipeline_flowchart.md"
RESREF = ROOT / "paper/publication/submission_readiness/RESULTS_REFERENCE_2026-11-06.md"
FV = ROOT / "paper/publication/final_validation"
REG = FV / "MANUSCRIPT_CLAIMS_REGISTER.csv"
AUDIT = FV / "review_2026-11-09/data_audit/PASS_D1_frozen_numbers.md"
TODAY = datetime.date.today().isoformat()

# number -> (where it is written, status, evidence). Status: AUDIT = re-derived from the frozen artefacts by the
# 2026-11-09 data audit (PASS_D1); REPORT = stated in a frozen validation report covered by
# FINAL_VALIDATION_MANIFEST.sha256; RUN = in a dated result file; DERIVED = arithmetic on register rows;
# DO_NOT_CITE; NOT_A_RESULT (ids, dates, limits, stage numbers).
UNREGISTERED = [
    ("2,348,758 / 156,870 / 56 offset status", "AUDIT", "PASS_D1 §1 (EXACT/CORRECTED/UNANCHORED, sum 2,505,684)"),
    ("1,705,501 CPU-ensemble rows (terminology / zenodo_v1); 7-model split", "AUDIT",
     "PASS_D1 §5: en_core_sci_lg 960,719 · gliner_biomed 297,115 · gliner_medium 168,029 · en_ner_craft_md 119,092 · "
     "en_ner_bc5cdr_md 80,584 · en_ner_jnlpba_md 52,992 · biobert_diseases 26,970"),
    ("1,705,500 ensemble rows in term_mentions.jsonl; Δ51 to CDM", "AUDIT", "PASS_D1 §1 Δ51 (load-time PK dedup, load_audit)"),
    ("166,012 → 165,991 canonical terms (L1 → L2)", "AUDIT", "PASS_D1 §2; canonical_terms_summary.json"),
    ("26,874,831 characters (26.9 M); 7,909,432 tokens; 3,934,819 words", "AUDIT", "PASS_D1 §1, §3"),
    ("2,817 body sections (run universe); 2,364 sections with ≥1 mention", "AUDIT", "PASS_D1 §5 (two frames, both correct)"),
    ("296 papers full-text checkable (stage 46)", "AUDIT", "corpus_manifest.json / fulltext_crosscheck_report.json"),
    ("40,141 type harmonisations (G7)", "AUDIT", "PASS_D1 §1"),
    ("8,490,496 rows, 44 tables", "AUDIT", "PASS_D1 §1; Parquet copy 44/44 tables verified 2026-11-09"),
    ("16 upper + 66 subcategories; 0 classified (T4)", "AUDIT", "PASS_D1 §2"),
    ("37,907 corpus-stage entities; 32,713 canonical triples; 34,416 triple mentions (corpus 2.2.0)", "AUDIT", "PASS_D1 §3"),
    ("frozen_output: 110,981 entities / 24,910 relationships / 337,829 edge_evidence / 56,985 records", "AUDIT",
     "PASS_D1 §4 (v2-era build; never mix with 3.0.3)"),
    ("8,750 WITHHOLD_TEXT + 879 RESTRICTED_NC = 9,629 [W01]", "RUN", "triple_evidence_ccby_2026-11-07/summary.json"),
    ("93 NO_EVIDENCE; 74 unjudged (69 + 5)", "RUN", "evidence_judge_all_2026-11-07/summary.json (internal)"),
    ("14,363 / 5,780 / 4,618 / 860 all-licence buckets", "DO_NOT_CITE", "corrections B-01–B-04; cite W02/W03"),
    ("331,394 term_concept_map rows", "DO_NOT_CITE (cite P01/P02/P05)",
     "= 334,231 − 2,837 demoted (PASS_D1 Δ3); corrections M-01"),
    ("34,416 relation_evidence rows", "DO_NOT_CITE", "corrections E-01; say 'most carry a sentence' (6.5% unanchored)"),
    ("392,587 text values; 12,114 counts; 42,679 coded values; 52,397 assessable records", "REPORT",
     "CATALOGUE_EVIDENCE_ASSESSMENT.md; evidence_judge/judge_summary.json (records 52,397)"),
    ("rights split 453 / 274 / 15 / 164; 179 = 135 no licence + 29 NC-ND + 12 NC + 3 NC-SA; 2,103,395 values redacted",
     "REGISTERED 2026-11-09 [RT01-RT03]", "rights/PAPER_RIGHTS_MATRIX.csv; zenodo_frozen redaction log"),
    ("job ids 28671812, 28672584, 28672586, 28672594", "NOT_A_RESULT", "SLURM job ids in the flowchart"),
    ("9,940 unreachable terms; 215 off-vocabulary values", "REPORT", "EXHAUSTIVE_INTEGRITY_REPORT.md"),
    ("6.5% (2,224 of 34,416) triple-evidence mentions unanchored", "REPORT", "EXHAUSTIVE_INTEGRITY_REPORT.md"),
    ("4.9% of triples in pair types a curated KG covers; 50 of 137 (36.5%) in Disbiome", "REPORT",
     "TRIPLE_VALIDATION_REPORT.md"),
    ("68.7% generic relation", "DERIVED", "R02 / R01 = 17,717 / 25,788"),
    ("98.3% of ENTITY-only terms ground nowhere", "REPORT", "TERMINOLOGY_VALIDATION_REPORT.md"),
    ("grounding: organisms 12.2/48.5, chemicals 18.5/50.0, diseases 16.1/54.5, proteins 11.1/27.6", "REPORT",
     "TERMINOLOGY_VALIDATION_REPORT.md"),
    ("97.1% public-dataset papers; 90.1% findings traceable; 26–39% disease/intervention questions", "REPORT",
     "CDM_USABILITY_REPORT.md (Q4; Q5; Q1 26.8, Q2 39.3, Q6 26.1)"),
    ("LLMs invented strings up to 44%, off-schema up to 53%, Llama zero-shot cap 79%; 21 systems", "REPORT",
     "BENCHMARK_FINAL_ANALYSIS.md"),
    ("118 / 121 tests (2 fail, 1 conditional)", "AUDIT", "PASS_D1 §6 VERIFICATION_303.json [X07]"),
    ("all-labels κ 0.084 between the two catalogue judges", "RUN", "s6_judge_matrix_2026-11-06/S6_JUDGE_MATRIX.md"),
    ("S1000: PubTator3 0.705, Qwen3.5-4B 3-shot 0.632, HunFlair2 0.631", "RUN (not registered)",
     "benchmark/ner_species_s1000/species_metrics.json"),
    ("482 BioProjects in the compendium", "REPORT (not registered)", "Abdill 2025"),
    ("job ids (28619916, 2867…), stage numbers (10–70), dates, Excel limits (32,767), denominators 452 / 444",
     "NOT_A_RESULT", "identifiers and rules, not findings"),
]

NEW_WORK = f"""## Part 4. Work after the flowchart (2026-11-08 / 09)

All of the following read the frozen files read-only; nothing in a release was changed.

### 4.1 Independent data audit (2026-11-09, `final_validation/review_2026-11-09/data_audit/`)

Re-derived the frozen-set numbers from the artefacts (CDM db opened read-only, no paper text read):
**38 / 38 checks PASS** (`DATA_AUDIT.csv`). Four cross-artefact differences are explained, not defects:
Δ51 mentions (terminology 2,505,735 → CDM 2,505,684, primary-key dedup on load); catalogue 52,400 (3.1.1) vs 56,985
(frozen_output v2-era); Δ2,837 mappings (334,231 → 331,394 = demoted rows, P04); term_definition 6,773 (CDM stage)
vs 1,150 (terminology T3). It also records: `relation_evidence` joins `relation` on `canonical_triple_id` (there is
no `relation_id` column); 0 relations without evidence rows.

### 4.2 Ontology mapping and deduplication in CDM 3.0.3 (computed 2026-11-09 from the db; not registered)

- 331,394 candidate mapping rows to 204,817 distinct concept ids, from 5 services (OLS, BioPortal, UMLS, NCBI
  Taxonomy, OMOP). Accepted: **18,272 rows, 16,750 terms, 13,330 concepts [P05, P06]**, across 275 ontologies
  (ontology read from the concept id; `concept.ontology_name` is empty for all accepted rows).
- The accepted flag is `term_concept_map.mapping_disposition_reviewed = 'ACCEPTED'` (`mapping_disposition` never
  says ACCEPTED: REVIEW_REQUIRED 290,021 · REJECTED 30,693 · UNRESOLVED 10,680).
- Accepted rows by ontology: NCIt 3,058 · NCBI Taxonomy 2,569 · MeSH 2,524 + 1,346 (two IRI forms) · ChEBI 2,125 ·
  SNOMED CT 2,026 + 371 (two IRI forms) · UMLS 524 · GO 426 · MONDO 360 · OBI 269 · DOID 265 · PR 236 · LOINC 230 ·
  OMIM 205 · CL 182 · HGNC 134 · STATO 125.
- Deduplicated: mentions → occurrences (2,505,684 → 1,362,931 spans, `term_occurrence.n_models`); occurrences →
  canonical terms (166,012 → 165,991 → 162,409 after review); concepts once per exact id string.
- Not deduplicated: 9,047 codes stored under two id forms (CURIE and IRI, e.g. `NCBITaxon:100175` and
  `…/obo/NCBITaxon_100175`); no accepted term has the same code twice. No cross-ontology merge (MeSH / MONDO / DOID
  stay separate; `identifier_crosswalk` has 4 rows, about table id columns). 1,540 concepts are accepted for ≥2
  terms; 969 terms have ≥2 accepted mappings.

### 4.3 Non-English text (`outputs/results/non_english_scan_2026-11-08/`)

| Source | Finding | Treatment |
|---|---|---|
| HMPAPER_000289, Korean-language paper (WITHHOLD_TEXT) | ~99% of hits; 335 Korean canonical terms | not sent externally; English names open (local model, needs lead approval) |
| corpus 2.2.0 `candidate_entity_mappings.jsonl` (116 rows), `entities.jsonl` (24 rows) | 116 LOINC concepts with Chinese synonyms (e.g. "PR 间期…") | official English `concept_name` from local OMOP CONCEPT.csv: 116 / 116 (`omop_chinese_to_english.tsv`) |
| CDM 3.0.3 `concept` NANDO:1200027 | Japanese label 視神経脊髄炎 | neuromyelitis optica |
| HMPAPER_000240 | `classify‐skle慲渠湡榨癥⁂慹` is mojibake of "classify-sklearn naive Bayes" (8 terms) | known PDF-extraction defect |
| a few papers | Cyrillic look-alikes (`2000с`, `Naпve`), one Thai control character | known PDF-extraction defect |

DeepSeek-V4.1-Flash (Fraunhofer Genie) checked the 117 vocabulary labels only (no paper text): MATCH 109,
PARTIAL 7 (LOINC short names), MISMATCH 1 (a model error). Model judgement.

### 4.4 Exports and copies

- `outputs/exports/cdm_v3_3.0.3_parquet_tables/`: 44 Parquet files, 244 MB (db 2.9 GB); 44 / 44 tables and
  8,490,496 rows verified against the db (`verify_cdm_parquet.py`). Full text: team only.
- `paper/publication/all_frozen_outputs/`: authors' copy of the whole frozen set and all evaluation outputs (1,030
  files, 12.6 GB, `MANIFEST.sha256` all OK). **Not the Zenodo deposit** (withheld text).
- Zenodo: `releases/zenodo_frozen/` (rights scan PASS, text for 274 CC BY / CC0 papers only; not uploaded; licence
  and legal sign-off pending).

### 4.5 Corrections to earlier statements
- A markdown version of the corpus exists (`frozen_output/01_corpus/segmented_sections_markdown`, part of the
  current frozen set); only the old CDM inside `frozen_output` (build 2.1.0) is superseded.
- The Chinese OMOP labels are in corpus 2.2.0 (current set), not only in an old build; they are not in CDM 3.0.3.
- The register is versioned with a change log, not under a manifest; its sha256 is given in Part 1.
- Triple-reference rows are XR01–XR06 (renumbered 2026-11-10 from X01–X06; X01–X10 are the CDM rows).
"""


def sha(p: Path, n=16) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / f"PIPELINE_AND_NUMBERS_{TODAY}.md")
    a = ap.parse_args()
    nums = FV / f"PAPER_NUMBERS_{TODAY}.md"
    subprocess.run([sys.executable, str(ROOT / "src/scripts/final_validation/register_to_markdown.py"), "--out",
                    str(nums)], check=True, capture_output=True)
    reg_rows = list(csv.DictReader(open(REG, encoding="utf-8")))

    flow = FLOW.read_text(encoding="utf-8")
    flow = flow.replace("## Mermaid diagram (rev 2)", "## Mermaid diagram (rev 3)")
    flow = re.sub(r"^# ", "### ", flow, count=1, flags=re.M)
    flow = re.sub(r"^## ", "#### ", flow, flags=re.M)
    resref = RESREF.read_text(encoding="utf-8")
    resref = resref.replace("142 rows", f"142 rows at the time; {len(reg_rows)} now")
    resref = re.sub(r"^# ", "### ", resref, count=1, flags=re.M)
    resref = re.sub(r"^## ", "#### ", resref, flags=re.M)
    numbers = nums.read_text(encoding="utf-8").split("\n", 1)[1]
    numbers = re.sub(r"^## ", "#### ", numbers, flags=re.M)
    numbers = re.sub(r"^- \[([^\]]+)\]\(#[^)]+\)$", r"- \1", numbers, flags=re.M)

    L = [f"# Microbiome-CDM: pipeline, results and every number ({TODAY})", "",
         "*One file combining `docs/reports/pipeline_flowchart.md` (rev 3), "
         "`paper/publication/submission_readiness/RESULTS_REFERENCE_2026-11-06.md` and the full claims register, plus "
         "the 2026-11-08/09 work. Generated by `src/scripts/final_validation/build_pipeline_and_numbers.py`; "
         "the parts are copied, not rewritten. **Reference notes for the authors, not manuscript text.** No human "
         "annotation was done [H01]; nothing here is accuracy unless it is F1 on a public gold standard.*", "",
         "## Contents", "",
         "1. Frozen set and verification status",
         "2. Pipeline flowchart (rev 3, with diagram and stage index)",
         "3. Results reference: what we did and what we got",
         "4. Work after the flowchart (2026-11-08 / 09)",
         "5. Every registered number (claims register)",
         "6. Numbers that are not register rows, and how each was checked",
         "7. Open before submission", "",
         "## Part 1. Frozen set and verification status", "",
         "| Component | Version | Location | Integrity (checked 2026-11-08/09) |", "|---|---|---|---|",
         "| Corpus | 2.2.0 (453 papers, 447 publications, 4,006 sections) | `pipelines/corpus_v2/releases/2.2.0` (+ segmented, "
         "markdown, per-model NER in `releases/frozen_output/01_corpus`, `04_ner`) | own MANIFEST OK |",
         "| Terminology | 1.0.1 | `releases/terminology/1.0.1` | MANIFEST OK |",
         "| Data catalogue | 3.1.1 | `releases/data_catalogue_v3/3.1.1` | MANIFEST OK |",
         "| CDM | 3.0.3 (44 tables, 8,490,496 rows) | `releases/cdm_v3/3.0.3/microbiome_cdm_v3.db` | sha256 5d23ba87…; "
         "MANIFEST OK |",
         "| Index of the set | — | `releases/CURRENT_FROZEN_SET_2026-11-02/` | 17 release manifests OK |",
         "| Validation outputs | frozen 2026-11-02 | `paper/publication/final_validation/` | "
         "FINAL_VALIDATION_MANIFEST.sha256: 119 / 119 OK |",
         f"| Claims register | {len(reg_rows)} rows (146 MATCH, 1 STATEMENT) | `final_validation/"
         f"MANUSCRIPT_CLAIMS_REGISTER.csv` | sha256 {sha(REG)}…; versioned via CHANGE_RECORD.md |",
         "| Data audit | 2026-11-09 | `final_validation/review_2026-11-09/data_audit/` | 38 / 38 PASS |", "",
         "Status labels used below: **[ID]** = register row, recomputed from the frozen data (MATCH); **AUDIT** = "
         "re-derived from frozen artefacts by the 2026-11-09 audit; **REPORT** = stated in a frozen validation report "
         "under FINAL_VALIDATION_MANIFEST; **RUN** = dated result file; **DERIVED** = arithmetic on register rows; "
         "**DO_NOT_CITE**.", "",
         "Do not mix builds: CDM 3.0.3 (25,788 triples, 52,400 catalogue records) vs the v2-era CDM in "
         "`frozen_output/03_common_data_model` (110,981 entities, 24,910 co-occurrence relationships) and the v2-era "
         "catalogue (56,985 records). Corpus 2.2.0 holds 32,713 corpus-stage canonical triples, before the stage-56 "
         "gate that leaves the 25,788 in the CDM.", "",
         "## Part 2. Pipeline flowchart (rev 3)", "", f"*Copied from `{FLOW.relative_to(ROOT)}`.*", "", flow, "",
         "## Part 3. Results reference", "", f"*Copied from `{RESREF.relative_to(ROOT)}`. Every number in it is "
         "either a register row or listed in Part 6.*", "", resref, "", NEW_WORK, "",
         "## Part 5. Every registered number", "", numbers, "",
         "## Part 6. Numbers that are not register rows, and how each was checked", "",
         "| Number | Status | Evidence |", "|---|---|---|"]
    L += [f"| {n} | {s} | {e} |" for n, s, e in UNREGISTERED]
    L += ["", f"Audit file: `{AUDIT.relative_to(ROOT)}`. A number marked AUDIT, REPORT or RUN is checked but still "
          "needs a register row before it is cited in the manuscript.", "",
          "## Part 7. Open before submission", "",
          "- Register the numbers in Part 6 that the manuscript cites (S1000, rights split, 482 BioProjects, the "
          "ontology counts in 4.2, …); triple-reference ids are XR01–XR06 (renumbered 2026-11-10).",
          "- Lead approval to use W01–W05 (from the run that sent non-CC-BY text externally); tell the lead about the "
          "rights incident.",
          "- English names for the 335 Korean terms (local model; freeze exception).",
          "- Zenodo: licence (proposed CC BY 4.0) and legal sign-off; optional v1.1 deposit with the evaluation "
          "results that carry no paper text.",
          "- Declare all AI assistance (pipeline LLMs, judges, Claude Code / OpenCode) in the AI-use statement.", ""]
    a.out.write_text("\n".join(L), encoding="utf-8")
    print(a.out.relative_to(ROOT), sum(1 for _ in a.out.open()), "lines")


if __name__ == "__main__":
    main()
