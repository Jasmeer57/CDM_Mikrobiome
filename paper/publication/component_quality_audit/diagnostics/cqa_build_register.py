#!/usr/bin/env python3
"""Build the cross-component issue register (15_ISSUE_REGISTER.csv).

Parses every `### CQA-*` block out of reports 01-14, plus the twelve
amendment-raised gaps recorded in NER_REPRODUCIBILITY_GAPS.md section 12,
plus the two dated amendments themselves, into one machine-readable table.

Field values are copied verbatim out of the reports (minus markdown emphasis);
only `type_class` and `severity` are normalised, and both keep the original
string in `*_raw` so nothing is lost.

Stdlib only. Deterministic. Writes 15_ISSUE_REGISTER.csv next to the reports.
"""
from __future__ import annotations

import csv
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
AUDIT = os.path.dirname(HERE)
REPO = os.path.abspath(os.path.join(AUDIT, "..", "..", ".."))

COMPONENTS = [
    ("A", "01_CORPUS_QUALITY.md", "Corpus"),
    ("B", "02_ENTITY_EXTRACTION_QUALITY.md", "Entity extraction"),
    ("C", "03_TERMINOLOGY_QUALITY.md", "Terminology"),
    ("D", "04_MAPPING_QUALITY.md", "Ontology mapping"),
    ("E", "05_DEFINITION_QUALITY.md", "Definitions"),
    ("F", "06_CATALOGUE_QUALITY.md", "Catalogue"),
    ("G", "07_TRIPLE_AND_KG_QUALITY.md", "Triples and KG"),
    ("H", "08_CDM_QUALITY.md", "CDM schema"),
    ("I", "09_NER_BENCHMARK_QUALITY.md", "NER benchmark"),
    ("J", "10_CLEANED_LAYER_QUALITY.md", "Cleaned layer"),
    ("K", "11_BUGSIGDB_COMPARISON_QUALITY.md", "BugSigDB comparison"),
    ("L", "12_TRIPLE_REFERENCE_QUALITY.md", "Triple reference"),
    ("M", "13_INTEROPERABILITY_QUALITY.md", "Interoperability"),
    ("N", "14_RIGHTS_READINESS_QUALITY.md", "Rights readiness"),
    ("P", "17_PUBLICATION_CLAIM_IMPACT.md", "Manuscript claims"),
]

SEV_CANON = {
    "CRITICAL": "CRITICAL",
    "HIGH": "HIGH",
    "MODERATE": "MODERATE",
    "MEDIUM": "MODERATE",
    "LOW": "LOW",
}
SEV_ORDER = {"CRITICAL": 0, "HIGH": 1, "MODERATE": 2, "LOW": 3}

# Type classification. Order matters: first regex that matches wins.
TYPE_RULES = [
    (r"^amendment\b", "AUDIT_CORRECTION"),
    (r"no human check|adjudicat", "VALIDATION_ABSENT"),
    (r"governance", "GOVERNANCE_GAP"),
    (r"risk \(tested", "MEASURED_PROPERTY"),
    (r"small-denominator|confirmed risk|potential risk|untested assumption|"
     r"risk \(partly|partly confirmed|untested", "POTENTIAL_RISK"),
    (r"usability", "USABILITY_LIMITATION"),
    (r"dependency", "CLAIM_DEPENDENCY"),
    (r"documentation|provenance gap|provenance/documentation", "DOCUMENTATION"),
    (r"reproducib|regenerat|re-run", "REPRODUCIBILITY"),
    (r"schem|foreign key|declared type|multi-value", "SCHEMA"),
    (r"residual|artifact|artefact|over-redaction|leftover|surviv", "RESIDUAL_CONTENT"),
    (r"truthful|self-reported|mislabell|overstat|mislead|falsif|specification vs|"
     r"description-vs-behaviour", "DESCRIPTION_VS_BEHAVIOUR"),
    (r"coverage|scope limitation|comparability|incompleteness|limitation", "COVERAGE_OR_SCOPE"),
    (r"property|characterisation|interpretive|interpretation|measurement|null with|"
     r"concordance|negative result|currency", "MEASURED_PROPERTY"),
    (r"defect|inconsisten|stale|sentinel|duplicat|corrupt|loss|lost|unpopulated|"
     r"placeholder|classification|linkage|vocabulary|weak field|hygiene", "CONFIRMED_DEFECT"),
]
TYPE_CLASSES = [c for _, c in TYPE_RULES] + ["UNCLASSIFIED"]

FIELDS = {
    "severity": "**Severity:**",
    "type": "**Type:**",
    "evidence": "**Evidence:**",
    "affected": "**Affected:**",
    "affected_alt": "**Reconciliation:**",
    "sci": "**Scientific impact:**",
    "pub": "**Publication impact:**",
    "action": "**Recommended action:**",
    "blocking": "**Blocking:**",
}

COMPONENT_KEYWORDS = {
    "scientific": [
        r"accuracy", r"recall", r"precis", r"completeness", r"validity",
        r"evidence", r"triple", r"mapping", r"definition", r"term", r"entity",
        r"corpus", r"catalogue", r"ontology", r"grounding", r"taxonom",
        r"coverage", r"sample", r"dataset", r"claim", r"graph", r"benchmark",
    ],
    "publication": [
        r"claim", r"manuscript", r"submit", r"publish", r"quote", r"report",
        r"describe", r"present", r"state", r"disclos", r"figure", r"table",
        r"wording", r"abstract", r"methods",
    ],
    "release": [
        r"deposit", r"release", r"upload", r"bundle", r"licen", r"rights",
        r"redact", r"download", r"zenodo", r"ship", r"archive", r"portab",
        r"interoperab", r"reuse", r"reusab",
    ],
}


def strip_md(text: str) -> str:
    """Remove markdown emphasis and collapse whitespace."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    return re.sub(r"\s+", " ", text).strip().rstrip("|").strip()


def classify_type(raw: str) -> str:
    low = raw.lower()
    for pattern, cls in TYPE_RULES:
        if re.search(pattern, low):
            return cls
    return "UNCLASSIFIED"


def canonical_severity(raw: str) -> str:
    token = strip_md(raw).split()[0].rstrip(".,;:").upper() if strip_md(raw) else ""
    return SEV_CANON.get(token, "")


def impact_flags(block: str) -> tuple[str, str, str]:
    """Derive sci/pub/release impact present-flags from the prose."""
    low = block.lower()
    out = []
    for key in ("scientific", "publication", "release"):
        hit = any(re.search(k, low) for k in COMPONENT_KEYWORDS[key])
        out.append("yes" if hit else "no")
    return tuple(out)


def split_blocks(text: str):
    """Yield (id, title, body) for each `### CQA-...` heading."""
    parts = re.split(r"^### (CQA-[^\n]+)\n", text, flags=re.M)
    # parts = [preamble, heading_tail, body, heading_tail, body, ...]
    for i in range(1, len(parts) - 1, 2):
        tail, body = parts[i].strip(), parts[i + 1]
        # heading forms: "CQA-A-01 — Title" or the grouped "CQA-I-09 … CQA-I-20 — Title"
        hud = re.split(r"\s+[—–-]\s+", tail, maxsplit=1)
        iid = hud[0].strip()
        title = strip_md(hud[1]) if len(hud) > 1 else ""
        if not re.fullmatch(r"CQA-[A-Z]-\d+", iid):
            continue  # grouped pointer heading, handled by the gap register
        yield iid, title, body


def extract_field(body: str, marker: str) -> str:
    """Extract a `- **Field:**` bullet; continuation lines joined."""
    pat = re.compile(
        r"^- " + re.escape(marker) + r"[ \t]*(.*(?:\n(?![ \t]*-[ \t]|\n###|\n## |\Z).*)*)",
        re.M,
    )
    m = pat.search(body)
    if not m:
        return ""
    return strip_md(m.group(1))


def parse_report(path: str):
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    issues = []
    for iid, title, body in split_blocks(text):
        rec = {
            "issue_id": iid,
            "title": title,
            "severity_raw": extract_field(body, FIELDS["severity"]),
            "type_raw": extract_field(body, FIELDS["type"]),
            "evidence": extract_field(body, FIELDS["evidence"]),
            "affected": extract_field(body, FIELDS["affected"])
            or extract_field(body, FIELDS["affected_alt"]),
            "sci_impact": extract_field(body, FIELDS["sci"]),
            "pub_impact": extract_field(body, FIELDS["pub"]),
            "action": extract_field(body, FIELDS["action"]),
            "blocking": extract_field(body, FIELDS["blocking"]),
            "_has_sci": bool(re.search(r"\*\*Scientific impact:\*\*", body)),
            "_has_pub": bool(re.search(r"\*\*Publication impact:\*\*", body)),
        }
        issues.append(rec)
    return issues


# ---------------------------------------------------------------- gaps file
GAP_ROW = re.compile(r"^\| \*\*(CQA-I-\d+)\*\* \| (.*)$", re.M)

# Impacts for the twelve amendment-raised gaps. The gap table in
# NER_REPRODUCIBILITY_GAPS.md scopes severity to provenance, so it does not
# carry scientific/publication impact columns; these are written out here from
# that report's own sections rather than inferred from keywords.
GAP_IMPACTS = {
    "CQA-I-09": (
        "The type-agnostic comparison has no independent measurement for LLMs: up to 69.0% "
        "of emitted strings were dropped before write, so a low type-agnostic score cannot be "
        "separated from a high discard rate.",
        "Report invalid_type rates with every LLM score, or restrict LLM claims to the in-schema "
        "subset.",
    ),
    "CQA-I-10": (
        "The Tier-1 suite cannot be described as pre-specified; any claim that the analysis plan "
        "was fixed before the results is unsupported for this tier.",
        "Do not claim preregistration for the NER suite. Claim it only for Tier 2/3, which have "
        "PREREGISTRATION.sha256.",
    ),
    "CQA-I-11": (
        "Byte-level reproducibility of the predictions is unverifiable; only the reported metrics "
        "are reproducible.",
        "State that runtime library versions are unrecorded rather than implying a pinned stack.",
    ),
    "CQA-I-12": (
        "Without the revision table, a recipient holding only preds/ cannot identify which "
        "checkpoint produced a score.",
        "Ship preds/ with the revision table (section 3), not alone.",
    ),
    "CQA-I-13": (
        "The pre-fix corpus_metrics.json was overwritten; only the SLURM logs preserve what the "
        "earlier runs printed.",
        "Version the per-scoring-run output directory in any future run; do not present the corpus "
        "numbers as a single first-pass result.",
    ),
    "CQA-I-14": (
        "Corpus-side grounding and KG support depend on ~2.5 GB of external vocabulary that was "
        "not pinned at run time, so those numbers are not reproducible from the bundle alone.",
        "Do not report corpus grounding or KG support as reproducible without the reference-input "
        "hashes.",
    ),
    "CQA-I-15": (
        "Truncation, salvage and failed-document events survive only as integers; the affected "
        "documents cannot be identified or re-scored.",
        "Keep truncation and salvage in the limitations; per-document status is a next-run fix.",
    ),
    "CQA-I-16": (
        "PubTator3 offsets failed to map for ~4.9% (BC5CDR) and ~13.2% (BioRED) of its output and "
        "the service version is unknown, so its scores cannot be re-derived against the same "
        "service.",
        "Keep PubTator3 reference-only and never present it as a deployable component.",
    ),
    "CQA-I-17": (
        "None for the metrics: the gold data is content-pinned by SHA256SUMS.",
        "Add a provenance note beside SHA256SUMS so a reader can see the retrieval route.",
    ),
    "CQA-I-18": (
        "A reader summing _meta counters can under-count, because an absent key means zero.",
        "Document the zero-means-absent convention in the prediction-file schema.",
    ),
    "CQA-I-19": (
        "No run-time environment snapshot exists for that job; the 0-byte log proves the capture "
        "ran and failed.",
        "Do not cite the environment-capture job as evidence of a recorded stack.",
    ),
    "CQA-I-20": (
        "None for the numbers; it is a reader-verification hazard, since the two markdown reports "
        "are not independent of the JSON.",
        "State in each report's header that it is generated from the JSON, so cross-checking them "
        "is not read as corroboration.",
    ),
}


def parse_gap_register(path: str):
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    out = []
    for m in GAP_ROW.finditer(text):
        cells = [c.strip() for c in m.group(2).split(" | ")]
        # cells: gap description, severity, closable, what closing takes, [trailing]
        if len(cells) < 4:
            continue
        sci, pub = GAP_IMPACTS.get(m.group(1), ("", ""))
        closable = strip_md(cells[2])
        out.append(
            {
                "issue_id": m.group(1),
                "title": strip_md(cells[0]),
                "severity_raw": strip_md(cells[1]),
                "type_raw": "Confirmed reproducibility gap",
                "evidence": strip_md(cells[0]),
                "affected": "benchmark provenance record",
                "sci_impact": sci,
                "pub_impact": pub,
                "action": strip_md(cells[3]),
                "blocking": (
                    "blocks a pre-specification or losslessness claim; not the metrics"
                    if re.search(r"\bno\b", closable, re.I) and "partly" not in closable.lower()
                    else "neither, if the limitation is disclosed"
                ),
                "_has_sci": True,
                "_has_pub": True,
            }
        )
    return out


AMENDMENT_SOURCE = {
    "CQA-I-AMEND-2026-11-04-1": "NER_ORGANISM_RECALL_AMENDMENT_2026-11-04.md",
    "CQA-I-AMEND-2026-11-05-1": "09_NER_BENCHMARK_QUALITY.md",
    "CQA-F-AMEND-2026-11-05-1": "06_CATALOGUE_QUALITY.md",
    "CQA-F-AMEND-2026-11-05-2": "06_CATALOGUE_QUALITY.md",
    "CQA-N-AMEND-2026-11-05-1": "14_RIGHTS_READINESS_QUALITY.md",
    "CQA-A-AMEND-2026-11-05-1": "01_CORPUS_QUALITY.md",
    "CQA-B-AMEND-2026-11-05-1": "02_ENTITY_EXTRACTION_QUALITY.md",
    "CQA-P-AMEND-2026-11-05-1": "17_PUBLICATION_CLAIM_IMPACT.md",
}

AMENDMENTS = [
    {
        "issue_id": "CQA-I-AMEND-2026-11-04-1",
        "title": "Dated amendment correcting three Component I reporting defects "
                 "(column mislabel, wrong F1 cell, 35-vs-36 typo)",
        "severity_raw": "MODERATE",
        "type_raw": "Amendment (audit correction)",
        "evidence": "D1 section 1.3 column mislabelled: full-schema 6-type micro recalls are "
                    "0.7443/0.7601, not 0.9237/0.8142 (the latter are OrganismTaxon-only). "
                    "D2 gliner_v25_biomed F1 cell 0.3971 is biored/bert_disease/"
                    "span_only_relaxed_F1; true value 0.4238. D3 '35-vs-36' typo: both "
                    "subsets are 36 mentions.",
        "affected": "3 cells/sentences in 09_NER_BENCHMARK_QUALITY.md; no metric value changed",
        "sci_impact": "None. All 1,186 recomputable values reproduce exactly; the corrections "
                      "are to labels and denominators, not results.",
        "pub_impact": "Prevents misquoting OrganismTaxon-only recall as full-schema recall, "
                      "and prevents quoting a span-only baseline as an F1.",
        "action": "Applied 2026-11-04. Superseded text retained with markers; NER_RETROSPECTIVE_SEAL "
                  "re-verified 126/126 after the amendment.",
        "blocking": "neither; correction applied and sealed.",
        "_has_sci": True,
        "_has_pub": True,
    },
    {
        "issue_id": "CQA-F-AMEND-2026-11-05-1",
        "title": "Dated amendment correcting an unreproducible catalogue record count "
                 "(15,582 -> 18,502)",
        "severity_raw": "MODERATE",
        "type_raw": "Amendment (audit correction)",
        "evidence": "06_CATALOGUE_QUALITY.md:86 stated '164 papers / 15,582 catalogue "
                    "records'. 15,582 is reproducible from no table and no table pair "
                    "(18,502 - 15,582 = 2,920 matches neither). Correct value 18,502 "
                    "flagged rows over 164 papers.",
        "affected": "1 sentence in CQA-F-01; scope limited to that sentence",
        "sci_impact": "None; the population was always 18,502 and every other figure in "
                      "CQA-F-01 already used it.",
        "pub_impact": "Prevents an unreproducible count from reaching the manuscript.",
        "action": "Applied 2026-11-05: sentence corrected, superseded wording retained under a "
                  "'corrected by' marker, section 7 amendment record added to report 06.",
        "blocking": "neither; correction applied.",
        "_has_sci": True,
        "_has_pub": True,
    },
    {
        "issue_id": "CQA-N-AMEND-2026-11-05-1",
        "title": "Dated amendment correcting four Component N figures and making one scope "
                 "explicit (gap_changes 930/224/84 -> 946/225/85; 94/35,011 scope; "
                 "withheld characters 9,188,416 -> 9,974,210)",
        "severity_raw": "MODERATE",
        "type_raw": "Amendment (audit correction)",
        "evidence": "A: CQA-N-08 enumerated only five change-log tables and omitted "
                    "findings.csv, which carries 16 cells >=30 chars, 1 of them >=50 and "
                    "verbatim; totals 930/224/84 become 946/225/85 (930+16, 224+1, 84+1), "
                    "buckets 501/205/116/108 become 513/208/117/108. B: '94 (file,column) "
                    "pairs / 35,011 cells' is the population after excluding papers.csv "
                    "(9 pairs / 917 exempt bibliographic cells); unfiltered is 103 / 35,928. "
                    "C: CQA-N-01 quoted only WITHHOLD_TEXT (9,188,416) and omitted the "
                    "785,794 characters on the 15 NC/NC-SA papers; reconciled total is "
                    "9,974,210.",
        "affected": "4 figures in 14_RIGHTS_READINESS_QUALITY.md (CQA-N-01 affected line; "
                    "CQA-N-08 title, evidence, affected, publication-impact, blocking lines; "
                    "section 4); no data defect and no rating changed",
        "sci_impact": "None. CQA-N-08 remains MODERATE; the component's split verdict "
                      "(process STRONG / adjudication CRITICAL WEAKNESS / description WEAK) "
                      "is unchanged.",
        "pub_impact": "Prevents understating residual content in withheld papers (946 not "
                      "930 cells, 85 not 84 verbatim) and understating the withheld layer by "
                      "785,794 characters (37.2%, not the single-class figure).",
        "action": "Applied 2026-11-05: figures corrected in place with 'corrected by' markers, "
                  "section 6 amendment record added to report 14, and a permanent reproducer "
                  "added as diagnostics/cqa_n_rights.py:gap_changes_values() emitting "
                  "gap_changes_values in cqa_n_rights.json (the original probe had no "
                  "reproducer on disk, which is how the omission survived review).",
        "blocking": "neither; correction applied. Register rows CQA-N-01 and CQA-N-08 "
                    "regenerated from the corrected report.",
        "_has_sci": True,
        "_has_pub": True,
    },
    {
        "issue_id": "CQA-F-AMEND-2026-11-05-2",
        "title": "Dated amendment clarifying the evidence-judge scope: four figures "
                 "re-scoped (81.15%/kappa 0.2321/242,158 and 284,325), two crosstab cells "
                 "retained, one unit corrected (2,023 pairs, not records)",
        "severity_raw": "MODERATE",
        "type_raw": "Amendment (audit correction)",
        "evidence": "06_CATALOGUE_QUALITY.md section 4.3 named the text_value both-valid "
                    "scope then quoted figures from three different scopes in one "
                    "sentence. Recomputed from the raw shards by "
                    "diagnostics/cqa_f_judge.py: judge_summary.json carries "
                    "judge_agreement_text_values (351,792 pairs, po 0.477, kappa 0.084) and "
                    "judge_agreement_text_values_both_valid (194,479, 0.85, 0.282), both "
                    "reproducing exactly. PASS|PASS 159,680 and PASS|INVALID 132,890 are "
                    "exact cells of the former and are retained. 242,158 / 0.8115 / 0.2321 "
                    "are reproducible from no scope (nearest all-fields both-valid 241,148 / "
                    "0.8135 / 0.2267; exhaustive sweep over 128 field-drop subsets x 2 link "
                    "modes finds no exact match) - recorded as missing provenance, not "
                    "fabrication. 284,325 IS exact but on the all-fields scope "
                    "(mistral inventory, union record set, link-verdict applied; 544,992 "
                    "cells); on text_value mistral INVALID is 157,011 and llama 2,877. "
                    "The 2,023 both-failed entries are (record, field) pairs over 1,730 "
                    "records, not 2,023 records.",
        "affected": "5 sentences in 06_CATALOGUE_QUALITY.md (section 4.3 x2, 4.4, 4.5, 5); "
                    "no data defect and no rating changed",
        "sci_impact": "None. The 'judges are not an oracle' conclusion holds under every "
                      "scope tested (kappa <= 0.282 on both-valid text values, 0.084 across "
                      "all classes). No accuracy, recall or completeness statement depends "
                      "on the superseded figures.",
        "pub_impact": "Prevents quoting an unreproducible agreement figure (81.15%/0.2321/"
                      "242,158) or an all-fields INVALID count as if it were a text-value "
                      "one, and prevents the manuscript layer's own text_value both-valid "
                      "definition (claims_register.py J04/J05: 0.85/0.282) from appearing "
                      "to contradict this report.",
        "action": "Applied 2026-11-05: superseded values retained under 'superseded by' "
                  "markers, correlation section 7 amendment record added to report 06, and a "
                  "permanent reproducer added as diagnostics/cqa_f_judge.py emitting "
                  "cqa_f_judge.json with shipped_file_reproduces, the two-scope table, a "
                  "24-variant sweep and disputed_figure_provenance.",
        "blocking": "neither; correction applied. No register row value changed.",
        "_has_sci": True,
        "_has_pub": True,
    },
    {
        "issue_id": "CQA-I-AMEND-2026-11-05-1",
        "title": "Dated amendment withdrawing the corpus-grounding circularity claim "
                 "(premise false) and restating the real defect: three unlike measures in "
                 "one column, two unreported denominators",
        "severity_raw": "MODERATE",
        "type_raw": "Amendment (audit correction)",
        "evidence": "CQA-I-06 was titled 'Corpus grounding is measured against the project's "
                    "own terms, so it is partly circular' and claimed grounding = share of "
                    "extracted surfaces matching a canonical_term. False: "
                    "src/scripts/ner_fair_bench/corpus_bench.py:build_lexicon() assembles "
                    "lexicons only from downloaded external references (NCBI Gene "
                    "gene_info.gz, CTD_diseases/CTD_chemicals tsv.gz, OMOP CONCEPT + "
                    "CONCEPT_SYNONYM filtered to Mondo/HPO, NCBI names.dmp); LEX = OUT / "
                    "'lexicon'; the source contains no occurrence of canonical_term. "
                    "Verified by diagnostics/cqa_i_grounding.py "
                    "(source_mentions_canonical_term_layer = false). The replacement finding: "
                    "of 117 grounding cells, 95 across 4 types are genuine external-vocabulary "
                    "lookups; SequenceVariant (16 cells) is VARIANT_RE regex matching "
                    "(1,257/50,249 unique strings = 2.5%) not a lookup; CellLine (19 cells) is "
                    "definitional 0.0% because ground() returns set(); denominator is distinct "
                    "strings, not mentions; and the shipped other_type_pct (up to 19.1%, >10% "
                    "in 9 cells) has never been reported. Affected line also corrected "
                    "'26 configurations' -> 25 (scispacy_lg carries no grounding block).",
        "affected": "2 sentences in the section 1 dimension table and 1 issue block "
                    "(CQA-I-06) in 09_NER_BENCHMARK_QUALITY.md; 117 grounding cells "
                    "re-described; no metric value changed",
        "sci_impact": "None to any result, but one audit claim is withdrawn: grounding is a "
                      "Tier-2 external-reference measure, not a consistency check against the "
                      "project's own vocabulary, so the circularity objection does not apply. "
                      "The surviving limitation is that one third of the cells measure surface "
                      "format or a missing vocabulary rather than correctness.",
        "pub_impact": "Prevents the manuscript defending a claim it does not make: "
                      "01_methods_and_resource.md:148 already says 'precision proxies, not "
                      "accuracy' and names the external vocabularies. The live exposure is "
                      "FIGURE_PLAN.md:11 (CellLine 0.0% plotted as a model outcome) and "
                      "02_results.md:108 (a grounding rate read as an invention rate).",
        "action": "Applied 2026-11-05: CQA-I-06 retitled in place with superseded title, "
                  "evidence and impacts retained under '*[superseded 2026-11-05]*' markers; "
                  "a 'Corrected finding' block added; dimension-table row corrected; section "
                  "6a amendment record added to report 09; permanent reproducer added as "
                  "diagnostics/cqa_i_grounding.py -> cqa_i_grounding.json. No rating changed: "
                  "Grounding stays ADEQUATE and CQA-I-06 stays MODERATE.",
        "blocking": "neither; correction applied. Grounding rating ADEQUATE and CQA-I-06 "
                    "MODERATE are unchanged, so no register row value moved.",
        "_has_sci": True,
        "_has_pub": True,
    },
    {
        "issue_id": "CQA-A-AMEND-2026-11-05-1",
        "title": "Dated amendment disclosing that SQLite LENGTH() and Python len() give two "
                 "different corpus character totals and two different zero-section counts "
                 "(26,874,831 / 453 vs 26,781,631 / 454)",
        "severity_raw": "LOW",
        "type_raw": "Amendment (reporting caveat)",
        "evidence": "01_CORPUS_QUALITY.md header stated 26,874,831 section characters and "
                    "the section 1 'Semantic quality' row stated 'exactly 453 zero-char "
                    "front/(preamble) placeholders'. Both reproduce under a Python read "
                    "(con.text_factory = bytes, then .decode('utf-8','replace')). SQLite "
                    "SUM(LENGTH(section_text_original)) on the same frozen DB gives "
                    "26,781,631 characters and 454 zero-length rows. Delta 93,200 chars / "
                    "1 row, caused by 14 sections in 4 papers carrying U+0000 "
                    "(the documented upstream PDF ligature artifact). The extra SQL-zero "
                    "row is HMPAPER_000120/sec_gap_000, which is 4,310 chars long and "
                    "begins with U+0000 so LENGTH() returns 0; the other 13 are truncated "
                    "by LENGTH(), not zeroed. Per-row table is in the amendment record.",
        "affected": "1 clause in the section 1 dimension table plus a section 5 amendment "
                    "record in 01_CORPUS_QUALITY.md; no count in any other report is "
                    "superseded and no artefact modified",
        "sci_impact": "None. The audit's own 453 is the semantically correct figure (453 "
                      "structurally-expected front/(preamble) placeholders). The exposure is "
                      "that a SQL consumer sees 454 empty sections and cannot reproduce "
                      "term_mention offsets with a naive SQL substr() into the 14 affected "
                      "sections.",
        "pub_impact": "Prevents a reviewer or reuser from 'discovering' an apparent "
                      "discrepancy between the manuscript's corpus size and a SQL query, and "
                      "records which denominator underlies the withheld-share percentages "
                      "(37.24% on the SQL total, 37.11% on the Python total).",
        "action": "Applied 2026-11-05: parenthetical marker added in place, superseded "
                  "wording retained, section 5 amendment record added to report 01 with the "
                  "full 14-row table and both reproducing commands. Report 01's ratings are "
                  "unchanged.",
        "blocking": "neither; caveat disclosed. No register row value moved.",
        "_has_sci": True,
        "_has_pub": True,
    },
    {
        "issue_id": "CQA-B-AMEND-2026-11-05-1",
        "title": "Dated amendment correcting report 02's linkage percentage, which counted only "
                 "the LINKED status token and omitted LINKED_BY_TYPE (86.55% -> 87.75%)",
        "severity_raw": "LOW",
        "type_raw": "Amendment (audit correction)",
        "evidence": "02_ENTITY_EXTRACTION_QUALITY.md section 1 'Reusability' row and CQA-B-06 "
                    "reported 'term_link_status resolves 2,168,717 (86.55%) to a canonical "
                    "term' and '299,846/2,505,684 = 11.97% unlinked'. Verified read-only in "
                    "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db: canonical_term_id IS NOT "
                    "NULL on 2,198,766 rows = LINKED 2,168,717 + LINKED_BY_TYPE 30,049 "
                    "= 87.75%; NO_CANONICAL_TERM 299,846 (11.97%) + AMBIGUOUS 7,072 "
                    "(0.28%). The four classes sum to 2,505,684 exactly. LINKED_BY_TYPE is a "
                    "real resolution (fix_terminology_offsets.py:13,83; "
                    "cdm_remediation/build_dictionary.py:57) that also carries a "
                    "canonical_term_id, so the original figure understated linkage by 1.20 "
                    "points.",
        "affected": "2 figure sentences plus the remainder label in 02_ENTITY_EXTRACTION_"
                    "QUALITY.md; no rating changed and no count in any other report is "
                    "superseded",
        "sci_impact": "None to any underlying value; all four status counts were and remain "
                      "correct. The correction aligns report 02 with the manuscript's own "
                      "M13/M10 87.8% claim, which was correct all along.",
        "pub_impact": "Prevents a reviewer comparing report 02's 86.55% against the "
                      "manuscript's 87.8% from concluding either that the manuscript "
                      "overstates linkage or that the audit disagrees with it.",
        "action": "Applied 2026-11-05: superseded wording retained with an inline marker, "
                  "section 6 amendment record added to report 02 with the four-class "
                  "count table and both reproducer queries. Reusability stays ADEQUATE and "
                  "CQA-B-06 stays MODERATE.",
        "blocking": "neither; correction applied. No register row value moved.",
        "_has_sci": True,
        "_has_pub": True,
    },
    {
        "issue_id": "CQA-P-AMEND-2026-11-05-1",
        "title": "Report 09 does not yet carry the H04/H05 bench-to-corpus correlation set; "
                 "recorded in report 17 section 6.2 instead of applied to the sealed report",
        "severity_raw": "LOW",
        "type_raw": "Amendment (coverage gap, not applied)",
        "evidence": "MANUSCRIPT_CLAIMS_REGISTER.csv carries H04 (Spearman BioRED F1 vs corpus "
                    "grounding, disease 0.749) and H05 (organism 0.023), both recomputing "
                    "from final_validation/benchmark/benchmark_analysis.json "
                    "-> public_vs_corpus.correlation (disease n_models 20, organism 19; "
                    "also chemical 0.252/21, gene 0.200/22, variant 0.112/16). "
                    "09_NER_BENCHMARK_QUALITY.md section 4 already establishes that a "
                    "Tier-1 result supports 'nothing about the corpus', so the conclusion "
                    "is not in conflict; the evidence is simply absent from report 09.",
        "affected": "1 missing subsection in 09_NER_BENCHMARK_QUALITY.md; nothing superseded.",
        "sci_impact": "None. Report 17 section 6.2 states the five-row correlation table and "
                      "the n_models denominators authoritatively in the meantime, and warns "
                      "that the 0.749 must never be quoted without n=20.",
        "pub_impact": "Report 00 must cite report 17 section 6.2 for H04/H05 rather than "
                      "report 09 until the section is added.",
        "action": "Recorded 2026-11-05 and NOT applied: report 09 carries a dated "
                  "retrospective SHA-256 seal and four amendment records, so adding a "
                  "section would require a further reseal. Apply as report 09 section 2.4 "
                  "at the next reseal.",
        "blocking": "neither; statement of a gap in this audit's own reporting.",
        "_has_sci": True,
        "_has_pub": True,
    },
]


def main() -> int:
    rows = []
    for comp, fname, label in COMPONENTS:
        path = os.path.join(AUDIT, fname)
        if not os.path.exists(path):
            print(f"MISSING REPORT: {fname}", file=sys.stderr)
            return 1
        for rec in parse_report(path):
            rec["component"] = comp
            rec["component_name"] = label
            rec["source_report"] = fname
            rows.append(rec)

    n_report = len(rows)

    gaps = parse_gap_register(os.path.join(AUDIT, "NER_REPRODUCIBILITY_GAPS.md"))
    for rec in gaps:
        rec["component"] = "I"
        rec["component_name"] = "NER benchmark"
        rec["source_report"] = "NER_REPRODUCIBILITY_GAPS.md"
        rows.append(rec)

    for rec in AMENDMENTS:
        rec["component"] = rec["issue_id"].split("-")[1]
        rec["component_name"] = dict((c, l) for c, _, l in COMPONENTS)[rec["component"]]
        # Amendments live in the report they amend. Resolve by explicit map so a new
        # amendment cannot silently inherit the wrong provenance.
        rec["source_report"] = AMENDMENT_SOURCE.get(
            rec["issue_id"],
            "NER_ORGANISM_RECALL_AMENDMENT_2026-11-04.md"
            if "2026-11-04" in rec["issue_id"]
            else "06_CATALOGUE_QUALITY.md",
        )
        rows.append(rec)

    out_rows = []
    for rec in rows:
        sev = canonical_severity(rec["severity_raw"])
        sci_flag, pub_flag, rel_flag = impact_flags(
            " ".join(
                [
                    rec.get("sci_impact", ""),
                    rec.get("pub_impact", ""),
                    rec.get("blocking", ""),
                    rec.get("title", ""),
                ]
            )
        )
        out_rows.append(
            {
                "issue_id": rec["issue_id"],
                "component": rec["component"],
                "component_name": rec["component_name"],
                "title": rec["title"],
                "severity": sev,
                "severity_raw": rec["severity_raw"],
                "type_raw": rec["type_raw"],
                "type_class": classify_type(rec["type_raw"]),
                "evidence_summary": rec["evidence"],
                "affected_proportion": rec["affected"],
                "scientific_impact": rec["sci_impact"],
                "publication_impact": rec["pub_impact"],
                "touches_scientific": sci_flag,
                "touches_publication": pub_flag,
                "touches_release": rel_flag,
                "recommended_action": rec["action"],
                "blocking_status": rec["blocking"],
                "source_report": rec["source_report"],
            }
        )

    order = {c: i for i, (c, _, _) in enumerate(COMPONENTS)}
    out_rows.sort(
        key=lambda r: (
            order.get(r["component"], 99),
            SEV_ORDER.get(r["severity"], 9),
            r["issue_id"],
        )
    )

    out_path = os.path.join(AUDIT, "15_ISSUE_REGISTER.csv")
    cols = [
        "issue_id", "component", "component_name", "title", "severity",
        "severity_raw", "type_raw", "type_class", "evidence_summary",
        "affected_proportion", "scientific_impact", "publication_impact",
        "touches_scientific", "touches_publication", "touches_release",
        "recommended_action", "blocking_status", "source_report",
    ]
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, quoting=csv.QUOTE_ALL)
        w.writeheader()
        w.writerows(out_rows)

    # ---- console summary
    import collections

    print(f"reports parsed            : {n_report} issues from 01-14")
    print(f"gap register added        : {len(gaps)} (CQA-I-09..20)")
    print(f"amendments added          : {len(AMENDMENTS)}")
    print(f"TOTAL ROWS                : {len(out_rows)}")
    print()
    print("by component:")
    for comp, _, label in COMPONENTS:
        sub = [r for r in out_rows if r["component"] == comp]
        sev = collections.Counter(r["severity"] for r in sub)
        print(
            f"  {comp} {label:<22} n={len(sub):<3} "
            f"CRITICAL {sev.get('CRITICAL',0):<2} HIGH {sev.get('HIGH',0):<2} "
            f"MODERATE {sev.get('MODERATE',0):<2} LOW {sev.get('LOW',0):<2}"
        )
    print()
    print("by severity:", dict(collections.Counter(r["severity"] for r in out_rows)))
    print("by type_class:")
    for k, v in collections.Counter(r["type_class"] for r in out_rows).most_common():
        print(f"  {k:<28} {v}")
    print()
    empty = [r["issue_id"] for r in out_rows if not r["evidence_summary"]]
    if empty:
        print("!! rows with no evidence text:", empty)
    no_sev = [r["issue_id"] for r in out_rows if not r["severity"]]
    if no_sev:
        print("!! rows with unparsed severity:", no_sev)
    dup = [k for k, v in collections.Counter(r["issue_id"] for r in out_rows).items() if v > 1]
    if dup:
        print("!! duplicate ids:", dup)
    print(f"\nwrote {out_path} ({len(out_rows)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
