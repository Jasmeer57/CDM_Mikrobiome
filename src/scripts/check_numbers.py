#!/usr/bin/env python3
"""check_numbers.py — Verify manuscript numbers against numbers.json.

Usage: python src/scripts/check_numbers.py

Exits 0 if all checks pass, 1 if any mismatch.
"""
import json
import re
import sys
from pathlib import Path

REPO = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
NUMBERS = json.loads((REPO / "paper" / "manuscript" / "numbers.json").read_text())
TEX = (REPO / "paper" / "manuscript" / "manuscript.tex").read_text()

CLAIM_C_CANDIDATES = json.loads(
    (REPO / "paper_claims" / "claim_C_hybrid_fusion" / "results" / "candidate_associations_summary.json").read_text()
)

passed = 0
failed = 0


def check(description, expected, pattern, flags=0):
    """Search for a number in the manuscript. Passes if at least one
    numeric value extracted from the matches equals the expected value."""
    global passed, failed
    matches = list(re.finditer(pattern, TEX, flags))
    if not matches:
        failed += 1
        print(f"  FAIL  {description}: pattern not found")
        print(f"        pattern: {pattern}")
        return
    # Extract all numbers from all matches (group 0 = full match)
    found_nums = []
    for m in matches:
        text = m.group(0)
        # Extract all numeric values from the match text
        for n_match in re.finditer(r"(\d[\d,]*\.?\d*)", text):
            val_str = n_match.group(1).replace(",", "")
            try:
                found_nums.append(float(val_str))
            except ValueError:
                pass
    expected_f = float(expected) if not isinstance(expected, (int, float)) else float(expected)
    # For fractions stored as 0.xxx, the manuscript has percentages (multiply by 100)
    if 0 < expected_f < 1:
        candidates = [expected_f, expected_f * 100]
    elif expected_f == 0:
        candidates = [0.0, 0.0]
    else:
        candidates = [expected_f]
    for fn in found_nums:
        for cand in candidates:
            if abs(fn - cand) < 0.05:
                passed += 1
                print(f"  OK    {description}: {expected}")
                return
    failed += 1
    print(f"  FAIL  {description}: expected {expected}, found {found_nums[:5]}")


def check_absent(description, pattern, flags=0):
    """Check that a pattern does NOT appear in the manuscript."""
    global passed, failed
    matches = list(re.finditer(pattern, TEX, flags))
    if matches:
        failed += 1
        print(f"  FAIL  {description}: forbidden pattern found ({len(matches)}x)")
        for m in matches[:3]:
            print(f"        ...{m.group(0)}...")
    else:
        passed += 1
        print(f"  OK    {description}: absent")


print("=" * 70)
print("CHECK_NUMBERS.PY — manuscript vs numbers.json")
print("=" * 70)

# === Production DB headline numbers ===
print("\n--- Production DB ---")
check("total entities", NUMBERS["db"]["total_entities"], r"\b34[,.]300\b")
check("total relationships", NUMBERS["db"]["total_relationships"], r"\b54[,.]788\b")
check("vocab mappings", NUMBERS["db"]["total_controlled_vocab"], r"\b140[,.]745\b")
check("edge evidence rows", NUMBERS["db"]["total_edge_evidence"], r"\b622[,.]893\b")
check("UMLS pct", NUMBERS["db"]["umls_pct"], r"\b59\.9\\?%")
check("n projects", NUMBERS["db"]["n_projects"], r"\b444\s+papers")

# === Typed core / co-occurrence ===
print("\n--- Edge layers ---")
check("typed core edges", NUMBERS["evidence_typed_core_total"], r"\b21[,.]514\b")
check("co-occurrence edges", NUMBERS["evidence_cooccur_total"], r"\b33[,.]274\b")
check("evidence with text pct", NUMBERS["evidence_typed_core_with_text_pct"], r"\b97\.9\\?%.*evidence")
check("Tier 1 verbatim pct", NUMBERS["evidence_tier1_pct"], r"\b10\.1\\?%.*verbatim")
check("Tier 2 paper pct", NUMBERS["evidence_tier2_pct"], r"\b80\.2\\?%.*both.terms")
check("Tier 3 ungrounded pct", NUMBERS["evidence_tier3_pct"], r"\b9\.7\\?%.*ungrounded")
check("co-occur provenance", NUMBERS["evidence_cooccur_with_provenance_pct"], r"\b100\\?%.*paper.level provenance")

# === Relabeling ===
print("\n--- Relabeling (§4.14) ---")
check("relabel total", NUMBERS["relabel_total"], r"\b1[,.]314\b.*relabeled")
check("relabel ASSOCIATED_WITH", NUMBERS["relabel_associated_with"], r"\b1[,.]313\b.*ASSOCIATED")
check("relabel ENRICHED_IN", NUMBERS["relabel_enriched_in"], r"\b1\b.*ENRICHED")
check("invalid pair count", NUMBERS["invalid_pair_count"], r"0 edges.*INVALID")

# === Claim A ===
print("\n--- Claim A (disambiguation) ---")
ca = NUMBERS["claim_a"]
check("LLM mean acc", ca["mean_acc"], r"\b54\.\d\\?%.*LLM.*mean of 5 runs", flags=re.IGNORECASE)
check("spaCy CRAFT acc", ca["spacy_craft"]["acc"], r"\b32\.4\\?%.*best single spaCy model", flags=re.IGNORECASE)
check("spaCy union acc", ca["spacy_union"]["acc"], r"\b51\.4\\?%.*spaCy union", flags=re.IGNORECASE)
check("McNemar LLM vs CRAFT p", ca["mcnemar_llm_vs_craft"]["p"], r"p=0\.077")
check("shared LLM acc", ca["shared_llm"]["acc"], r"\b66\.7\\?%")
check("shared union acc", ca["shared_union"]["acc"], r"\b79\.2\\?%")
check("n runs", ca["n_runs"], r"\b5\b\s+runs", flags=re.IGNORECASE)
check("temperature", ca["temperature"], r"temperature.*\b0\.8\b")

# === Claim B ===
print("\n--- Claim B (complementarity) ---")
cb = NUMBERS["claim_b"]
check("truly novel LLM", cb["n_truly_novel"], r"\b7[,.]098\b.*unique-to-Qwen")
check("spaCy-only novel", cb["n_spacy_only_truly_novel"], r"\b199[,.]618\b.*spaCy")
check("Jaccard B", cb["jaccard"], r"Jaccard.*\b0\.050\b")
check("intersection B", cb["intersection_size"], r"\b11[,.]035\b.*entities out of")
check("union B", cb["union_size"], r"\b219[,.]014\b.*distinct")

# === Claim C (50+50 hybrid) ===
print("\n--- Claim C (hybrid fusion) ---")
cc = NUMBERS["claim_c"]
check("hybrid entities", cc["n_entities"], r"\b5[,.]995\b.*entities")
check("hybrid relationships", cc["n_relationships"], r"\b34[,.]524\b.*relationship")
check("S1 LLM entities", cc["source_counts"]["S1_llm_entities"], r"\b1[,.]564\b")
check("S2 spaCy entities", cc["source_counts"]["S2_spacy_entities"], r"\b4[,.]359\b.*spaCy")
check("cross-source entities", cc["cross_source_entities"], r"\b503\b.*shared")
check("hybrid mult vs LLM", cc["hybrid_multiplier_vs_llm"], r"\b3\.83\b")
check("hybrid mult vs spaCy", cc["hybrid_multiplier_vs_spacy"], r"\b1\.23\b")
check("Jaccard C", cc["jaccard"], r"Jaccard.*\b0\.085\b")

# === Claim D ===
print("\n--- Claim D (speed/efficiency) ---")
cd = NUMBERS["claim_d"]
check("LLM total time", cd["llm_total_s"], r"\b2[,.]?117\.7\b")
check("spaCy total time", cd["spacy_total_s"], r"\b84\.9\b")
check("LLM entities", cd["llm_n_entities"], r"\b1[,.]007\b")
check("spaCy entities", cd["spacy_n_entities"], r"\b1[,.]422\b")
check("LLM throughput", cd["llm_throughput"], r"\b0\.48\b.*ent/s")
check("spaCy throughput", cd["spacy_throughput"], r"\b16\.75\b.*ent/s")
check("LLM cost", cd["llm_cost_usd"], r"\$0\.4412")
check("spaCy cost", cd["spacy_cost_usd"], r"\$0\.0047")
check("LLM s/KB", cd["llm_s_per_kb"], r"\b3\.5\b.*s/KB")
check("speed factor", 24.9, r"\b24\.9\b")
check("cost factor", 93.9, r"\b93\.9\b")

# === Leave-k-out ===
print("\n--- Leave-k-out ---")
lk = cc["leave_k_out"]
check("10% full recall", lk["0.1"]["mean_recall_full"], r"\b26\.7\b")
check("20% full recall", lk["0.2"]["mean_recall_full"], r"\b28\.4\b")
check("30% full recall", lk["0.3"]["mean_recall_full"], r"\b29\.5\b")

# === Candidate associations ===
print("\n--- Candidate associations ---")
check("7,307 candidates (50+50)", CLAIM_C_CANDIDATES["n_novel_candidates"], r"\b7[,.]307\b.*candidate")
check("3,406 production candidates", NUMBERS["candidate_associations_production"]["total"], r"\b3[,.]406\b.*typed candidate")
check("3,185 after stoplist", NUMBERS["candidate_associations_production"]["after_stoplist"], r"\b3[,.]185\b")
check("151 ge3 papers", NUMBERS["candidate_associations_production"]["ge3_papers"], r"\b151\b.*\bge3\b|\b151\b.*\\geq.*3")

# === Per-model quality ===
print("\n--- Per-model quality ---")
pm = NUMBERS["per_model_quality"]["models"]
check("Qwen unique", pm["Qwen 3.5:9b"]["unique"], r"\b19[,.]140\b.*unique")
check("spaCy unique", pm["sciSpaCy (4 combined)"]["unique"], r"\b231[,.]733\b")
check("spaCy generic pct", pm["sciSpaCy (4 combined)"]["generic_pct"], r"\b79\.1\\?%.*ENTITY")
check("GLiNER unique", pm["GLiNER (medium)"]["unique"], r"\b40[,.]058\b")
check("GLiNER-BioMed unique", pm["GLiNER-BioMed"]["unique"], r"\b74[,.]168\b")
check("PubMedBERT unique", pm["PubMedBERT"]["unique"], r"\b5[,.]753\b")
check("PubTator3 unique", pm["PubTator3"]["unique"], r"\b1[,.]508\b")

# === Absent content (should NOT appear) ===
print("\n--- Forbidden content ---")
check_absent("old 634 entities/s", r"634\s+entities/s")
check_absent("old $1.1533", r"\$1\.1533")
check_absent("old 0% error rate claim", r"error rate of 0\\?%")
check_absent("old 0.9% artifact", r"0\.9\\?%.*artifact")
check_absent("old 21% artifact", r"21\\?%.*artifact")
check_absent("old 14.2% artifact", r"14\.2\\?%.*artifact")
check_absent("old 62.1% UMLS (Qwen-primary)", r"62\.1\\?%.*UMLS.*Qwen.primary")
check_absent("old 4,359 as spaCy total (not spaCy-only)", r"yields 4,359 unique")
check_absent("old 12 of 14", r"12 of 14 schema types")
check_absent("old 24 distinct types", r"24 distinct types total")

# Check 19/81/0 only appears in supplement context, not main text claims
print("\n--- Supplement-only content ---")
# 19/81/0 should only appear in supplement/appendix, not in main text results
# Let's check if it appears outside of a supplement section
tex_no_supplement = re.sub(r"\\appendix.*", "", TEX, flags=re.DOTALL)
if re.search(r"19/81/0", tex_no_supplement):
    failed += 1
    print("  FAIL  19/81/0 appears in main text (should be supplement only)")
else:
    passed += 1
    print("  OK    19/81/0 not in main text")

# === DB-level verification: all 14 schema types are materialized ===
print("\n--- DB verification: 14 relation types ---")
import sqlite3
DB = sqlite3.connect(str(REPO / "releases" / "v2.1.1-clean" / "microbiome_cdm.db"))
cur = DB.cursor()
cur.execute("SELECT DISTINCT relationship_type FROM relationships")
db_types = {r[0] for r in cur.fetchall()}
SCHEMA_TYPES = {
    "ASSOCIATED_WITH", "TREATS", "TREATED_BY", "PRODUCES", "PRODUCED_BY",
    "DISRUPTS", "DEPLETED_IN", "ENRICHED_IN", "CO_OCCURS_WITH", "ENCODES",
    "EXPRESSES", "PART_OF_PATHWAY", "PARTICIPATES_IN", "IMPLICATED_IN",
}
missing = SCHEMA_TYPES - db_types
if missing:
    failed += 1
    print(f"  FAIL  {len(missing)} schema types missing from DB: {missing}")
else:
    passed += 1
    print(f"  OK    all 14 schema types present in production DB")

# Verify the KB loader bug: source_type='kb' edges should all be CO_OCCURS_WITH
cur.execute(
    "SELECT relationship_type, COUNT(*) FROM relationships "
    "WHERE source_type = 'kb' GROUP BY relationship_type"
)
kb_rows = cur.fetchall()
kb_cooccur = sum(c for rt, c in kb_rows if rt == "CO_OCCURS_WITH")
kb_total = sum(c for _, c in kb_rows)
if kb_cooccur == kb_total and kb_total > 0:
    passed += 1
    print(f"  OK    KB loader bug confirmed: {kb_cooccur}/{kb_total} source_type=kb edges are CO_OCCURS_WITH")
else:
    failed += 1
    print(f"  FAIL  KB loader bug: expected all CO_OCCURS_WITH, got {kb_cooccur}/{kb_total}")

# Verify manuscript says "all 14" and also discloses the KB loader bug
has_all14 = bool(re.search(r"materializ.*all 14.*schema types", TEX, re.IGNORECASE))
has_kb_bug = bool(re.search(r"loader bug", TEX, re.IGNORECASE))
if has_all14 and has_kb_bug:
    passed += 1
    print("  OK    manuscript states all 14 materialized AND discloses KB loader bug")
else:
    failed += 1
    print(f"  FAIL  manuscript missing 'all 14 materialized' ({has_all14}) or KB loader bug ({has_kb_bug})")

DB.close()

# === Summary ===
print("\n" + "=" * 70)
print(f"RESULTS: {passed} passed, {failed} failed")
print("=" * 70)
sys.exit(0 if failed == 0 else 1)
