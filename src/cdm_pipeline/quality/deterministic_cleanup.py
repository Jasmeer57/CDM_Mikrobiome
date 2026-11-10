"""Deterministic cleanup of remaining noise entities in the KG.

Uses high-precision rules (no LLM) to catch noise that the LLM pass missed:
  - Author names ("Braegger C", "Oda K", "Wang Y")
  - Geographic names ("Tokyo", "Japan", "China")
  - Journal/publisher names ("Nature", "BMC", "PLOS")
  - Company/supplier names ("Qiagen", "Illumina", "Zymo")
  - 2-letter fragments that are NOT established biomedical abbreviations
  - Non-Latin script text (Korean, Chinese, Japanese)
  - Thorn (þ) OCR artifacts
  - Truncated word fragments ("tion", "ated", "tive", "ing")
  - Stopwords / generic English words

Usage:
    python -m cdm_pipeline.quality.deterministic_cleanup --db microbiome_cdm.db --apply --delete
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

logger = logging.getLogger(__name__)

# ── Whitelists ──────────────────────────────────────────────

# Biomedical terms that match the "LastName Initial" pattern but are REAL
BIOMED_WHITELIST: Set[str] = {
    # Vitamins
    "Vitamin A", "Vitamin B", "Vitamin C", "Vitamin D", "Vitamin E", "Vitamin K",
    "Vitamin B12", "Vitamin B6", "Vitamin B2", "Vitamin B1", "Vitamin B3", "Vitamin B9",
    # Hepatitis
    "Hepatitis A", "Hepatitis B", "Hepatitis C", "Hepatitis D", "Hepatitis E",
    # Influenza
    "Influenza A", "Influenza B", "Influenza C",
    # Immunoglobulins
    "Immunoglobulin A", "Immunoglobulin G", "Immunoglobulin M", "Immunoglobulin E", "Immunoglobulin D",
    # Antibiotics/chemicals with letter suffix
    "Penicillin G", "Penicillin V", "Actinomycin D", "Polymyxin B", "Streptogramin B",
    "Streptogramin A", "Vancomycin A", "Bacitracin A", "Gramicidin A", "Gramicidin S",
    "Nisin A", "Nisin Z", "Urolithin A", "Urolithin B", "Aquamin F", "Crosatoside B",
    "Epicatechin B", "Catechin A", "Pepsinogen I", "Pepsinogen II",
    # Diseases with Roman numerals
    "Bipolar I", "Bipolar II", "Fragile X", "Obese I", "Obese II",
    # Proteins
    "Ubiquitin D", "Ubiquitin A", "Ubiquitin B", "Ubiquitin C",
    # Taxa with Roman numerals
    "Clostridium XI", "Clostridium I", "Clostridium IV", "Clostridium XIVa",
    # Kits/methods
    "Nextera XT",
    # Study phases/types
    "Phase I", "Phase II", "Phase III", "Phase IV",
    "Type I", "Type II", "Type III", "Type IV",
    "Group A", "Group B", "Group C", "Group D",
    "Class I", "Class II", "Class III",
    "Stage I", "Stage II", "Stage III", "Stage IV",
    "Part B", "Part A",
}

# Real 2-letter biomedical abbreviations (uppercase) — KEEP these
SAFE_2LETTER_UPPER: Set[str] = {
    # Chemical elements
    "Na", "Fe", "Ni", "Cu", "Zn", "Se", "K", "Mg", "Ca", "Mn", "Co", "Mo",
    "Cr", "V", "As", "Li", "Be", "He", "Cl", "Br", "F", "Si", "Sn", "Pb",
    "Sb", "Bi", "Pd", "Ag", "Pt", "Au", "Hg", "Al", "Ge", "Ga", "Rb", "Sr",
    "Y", "Zr", "Nb", "Tc", "Ru", "Rh", "Cd", "In", "Te", "Xe", "Ba", "La",
    "W", "Re", "Os", "Ir", "Pt", "Tl", "Po", "At", "Rn", "Ra", "U", "Np",
    "Pu", "B", "I", "N", "P", "S", "C",
    # Chemistry
    "pH", "Pi", "PPi", "CO", "NO", "SO", "CA", "LA", "FA", "PC", "PG",
    "Pi", "TP", "FP", "PP",
    # Immunology
    "IL", "TN", "IF", "Ig", "GM", "DC", "NK", "TC", "EB",
    # Diseases
    "PD", "AD", "DM", "RA", "MS", "UC", "CD", "TB", "CF", "IBD",
    "GI", "CK", "AK", "HF", "HD", "LD", "COPD", "BD", "AR", "DR",
    "JI", "FD", "EH", "FZ", "UP", "DX", "VL", "VT", "PE", "BC",
    "HF", "HI", "MH", "GD", "GI", "CF", "SB", "BC",
    # Methods
    "CT", "MRI", "PCR", "GC", "LC", "MS", "SD", "QC", "KO", "WT",
    "IV", "IR", "IP", "PR", "EC", "EM", "FL", "WG", "PT", "FT",
    "US", "ST", "CP", "MR", "AI", "PL", "PS", "HM", "ML", "TE",
    "GL", "FC", "BS", "AZ", "IA", "KG", "NB", "RF", "HK", "MW",
    "DG", "PK", "RH", "BF", "SN", "OC", "AV", "SW", "LP", "CV",
    "GO", "IC", "EP", "OS", "WD", "AJ", "BZ", "MX", "PN", "RB",
    "LF", "KB", "HQ", "OL", "OT", "UB", "IU", "FN", "OW", "NQ",
    "QD", "AW", "LT", "DB", "CX", "FO", "PU", "BQ", "EG",
    # Stats
    "SD", "SE", "CI", "RR", "OR", "HR",
    # Molecular biology
    "Tn", "TG", "NT", "SH", "FP", "TP", "DB", "GO", "WT", "KO",
}

# Real 2-letter mixed-case abbreviations (e.g., genus abbreviations) — KEEP
SAFE_2LETTER_MIXED: Set[str] = {
    # Genus abbreviations
    "Hp",   # Helicobacter pylori
    "Kp",   # Klebsiella pneumoniae
    "Ec",   # E. coli
    "Sa",   # S. aureus
    "Pa",   # P. aeruginosa
    "Sp",   # Streptococcus pyogenes / species
    "Cp",   # Clostridium perfringens
    "Se",   # Staphylococcus epidermidis
    "Mt",   # Mycobacterium tuberculosis
    "Bv",   # Bacteroides vulgatus
    "Vk",   # Vitamin K (but already in whitelist)
    "Eo",   # eosinophil
    "Fe",   # iron (element)
    "Ni",   # nickel (element)
    "Ce",   # cerium (element) / C. elegans
    "Tu",   # ?
    "Le",   # ?
    "Re",   # ?
    "Mo",   # molybdenum (element)
    "Px",   # ?
}

# 2-letter mixed-case that are likely author initials — DELETE
NOISE_2LETTER_MIXED: Set[str] = {
    "Jo", "Ku", "Vo", "Fu", "Hu", "Br",
}

# Geographic names to delete
GEO_NAMES: Set[str] = {
    "Tokyo", "Japan", "China", "Europe", "Africa", "America", "USA", "France",
    "Germany", "Italy", "Spain", "Korea", "India", "Brazil", "Mexico",
    "Australia", "Sweden", "Norway", "Denmark", "Finland", "Netherlands",
    "Belgium", "Switzerland", "Austria", "Poland", "Russia", "Canada",
    "Argentina", "Chile", "Peru", "Colombia", "Egypt", "Iran", "Turkey",
    "Israel", "Taiwan", "Thailand", "Vietnam", "Malaysia", "Singapore",
    "Indonesia", "Philippines", "Pakistan", "Bangladesh", "Sri Lanka",
    "Portugal", "Greece", "Ireland", "Hungary", "Czech", "Romania",
    "Bulgaria", "Croatia", "Serbia", "Slovakia", "Slovenia", "Lithuania",
    "Latvia", "Estonia", "Iceland", "Scotland", "Wales", "England",
    "Britain", "UK", "Beijing", "Shanghai", "Boston", "London", "Paris",
    "Berlin", "Madrid", "Rome", "Seoul", "Delhi", "Vienna", "Prague",
    "Warsaw", "Moscow", "Toronto", "Sydney", "Melbourne", "Graz", "Basel",
    "Bern", "Utrecht", "Wageningen", "Copenhagen", "Stockholm", "Oslo",
    "Helsinki", "Dublin", "Lisbon", "Athens", "Reykjavik", "Zurich",
    "Geneva", "Lausanne", "Greece",
}

# Journal/publisher names to delete
JOURNAL_NAMES: Set[str] = {
    "Nature", "Science", "Lancet", "BMJ", "PLOS", "BMC", "Springer",
    "Wiley", "Elsevier", "Oxford", "Cambridge", "Cell Press",
    "Nature Methods", "Nature Biotechnology", "Nature Microbiology",
    "Nature Communications", "Scientific Reports", "PNAS", "JAMA",
    "NEJM", "Gut", "Gastroenterology", "ISME", "mBio", "Microbiome",
    "PLOS ONE", "World J",
}

# Company/supplier names to delete
COMPANY_NAMES: Set[str] = {
    "Qiagen", "Illumina", "Sigma-Aldrich", "Roche", "Beckman", "Agilent",
    "Thermo Fisher", "Thermo", "Fisher", "Promega", "Bio-Rad", "Biorad",
    "Takara", "Clontech", "Zymo", "MoBio", "PowerSoil", "DNeasy", "QIAamp",
    "MinElute", "Nextera", "TruSeq",
}

# Stopwords / generic English words to delete
STOPWORDS: Set[str] = {
    "the", "and", "for", "with", "from", "this", "that", "were", "been",
    "have", "which", "their", "these", "those", "such", "also", "than",
    "then", "them", "when", "where", "while", "both", "some", "each",
    "other", "more", "most", "only", "very", "just", "even", "over",
    "into", "upon", "well", "about", "after", "before", "between",
    "through", "during", "against", "without", "within", "along",
    "across", "behind", "below", "above", "under", "again", "further",
    "once", "here", "there", "now",
    "all", "any", "can", "did", "does", "done", "had", "has", "his",
    "her", "its", "our", "out", "per", "put", "said", "set", "sit",
    "too", "try", "two", "use", "used", "was", "way", "who", "why",
    "will", "yet", "you", "your",
    "able", "back", "being", "came", "come", "down", "find", "found",
    "give", "gave", "given", "goes", "gone", "good", "hard", "head",
    "hear", "held", "help", "high", "hold", "home", "hour", "kind",
    "knew", "know", "last", "left", "less", "life", "like", "line",
    "list", "long", "look", "made", "make", "many", "mean", "might",
    "mind", "move", "much", "must", "name", "near", "need", "next",
    "nice", "none", "note", "open", "order", "page", "part", "past",
    "plan", "play", "point", "read", "real", "rest", "right", "room",
    "round", "same", "seem", "seen", "self", "show", "side", "sort",
    "stay", "stop", "sure", "take", "talk", "tell", "term", "test",
    "they", "thing", "think", "time", "took", "true", "turn", "type",
    "unit", "want", "week", "went", "what", "whom", "wide", "will",
    "word", "work", "year", "zero",
    # Generic non-biomedical
    "blue", "red", "green", "white", "black", "yellow", "brown",
    "gray", "grey", "final", "stable", "measure", "functional",
    "structural", "soluble", "global", "physical", "chemical",
    "biological", "mechanical", "natural", "artificial", "normal",
    "general", "specific", "particular", "individual", "total",
    "partial", "complete", "incomplete", "simple", "complex",
    "single", "double", "triple", "multiple", "common", "rare",
    "frequent", "occasional", "medium", "large", "small", "major",
    "minor", "main", "primary", "secondary", "tertiary", "initial",
    "previous", "current", "new", "old", "early", "late", "recent",
    "modern", "ancient", "traditional", "novel", "original", "unique",
    "typical", "atypical", "regular", "irregular", "public", "private",
    "open", "closed", "active", "inactive", "positive", "negative",
    "neutral", "relative", "absolute", "similar", "different",
    "same", "equal", "dependent", "independent", "direct", "indirect",
    "external", "internal", "inner", "outer", "upper", "lower",
    "front", "back", "top", "bottom", "center", "middle", "start",
    "end", "begin", "increase", "decrease", "reduction", "reduced",
    "increased", "decreased", "elevated", "lowered", "enhanced",
    "impaired", "improved", "worsened", "changed", "unchanged",
    "modified", "altered", "affected", "measured", "calculated",
    "determined", "estimated", "predicted", "observed", "recorded",
    "reported", "described", "characterized", "identified",
    "detected", "found", "shown", "demonstrated", "revealed",
    "suggested", "indicated", "proposed", "Multiple", "Positive",
    "Negative", "Observed",
}

# Truncated word fragments — actual suffixes/fragments with no root word
TRUNCATED_WORDS: Set[str] = {
    "tion", "ated", "tive", "sion", "ence", "ment", "ness", "able", "ible",
    "ing", "ated", "ated", "ysis", "ics", "ions", "ines", "ates", "ants",
    "ents", "ized", "ized", "ized", "ites", "ated", "tion", "sion",
    "ated", "ized", "ized",
}

# OCR ligature artifacts — fi→ﬁ, fl→ﬂ, soft hyphen, thorn
OCR_LIGATURES: Set[str] = {
    "ﬁnal", "ciﬁc", "ﬁsh", "ﬂare", "ﬁrst", "ﬁnd", "ﬁle", "ﬁve",
    "ﬁgure", "ﬁnal", "ﬁlter", "ﬁt", "ﬁll", "ﬁeld",
}

# Real short biomedical terms (3-4 letters lowercase) — DO NOT DELETE
REAL_SHORT_BIOMED: Set[str] = {
    # Nucleotides / metabolites
    "amp", "gtp", "atp", "nad", "fad", "ump", "cmp", "tmp", "gmp",
    "itp", "ctp", "utp", "coa", "fmn", "plp", "sam", "sah", "ppi",
    "udp", "gdp", "adp", "dna", "rna", "dna", "rna",
    # Biology terms
    "gene", "cell", "taxa", "diet", "food", "acid", "drug", "dose",
    "bile", "agar", "heme", "dopa", "gout", "coma", "sera", "loci",
    "iron", "zinc", "urea", "lead", "whey", "bran", "glia", "whey",
    "salt", "fats", "fat", "oil", "oils", "gas", "ion", "ions",
    "eggs", "pain", "lean", "mass", "stem", "gain", "pili", "wild",
    "mold", "rods", "burn", "foot", "rash", "pore", "hair", "clot",
    "cord", "noma", "sens", "ras", "trap", "iota", "fall", "seed",
    "feed", "soil", "gold", "fuel", "seeds", "w/v", "g/d", "nut",
    "lip", "spo", "tab", "arc", "stx", "stx1", "sul2", "tet1",
    "orf3", "p13", "p16", "p18", "p38", "p31", "p42", "p948",
    "air", "cold", "mood", "fear", "leak", "helm", "hook", "odor",
    "v128", "e177", "a4b7", "hg19", "lme4", "ade4", "nlme", "brms",
    "lmer", "30s", "16s", "10s",
    # Chemicals/elements short forms
    "n-3", "n-6", "b12", "b6", "b2", "b1", "b3", "b9",
}


# ── Noise detection rules ───────────────────────────────────

def is_author_name(name: str) -> bool:
    """Detect author names: 'LastName Initial' pattern (e.g., 'Braegger C', 'Oda K').

    Excludes whitelisted biomedical terms that match the same pattern
    (Vitamin A, Hepatitis C, Influenza A, etc.).
    """
    if name in BIOMED_WHITELIST:
        return False
    # "LastName Initial" or "LastName Initials" (up to 2 letters)
    if re.match(r"^[A-Z][a-z]+\s+[A-Z]\.?[A-Z]?$", name) and len(name) < 25:
        return True
    # "LastName AB" (two initials without space)
    if re.match(r"^[A-Z][a-z]+\s+[A-Z]{2}\.?$", name) and len(name) < 25:
        return True
    return False


def is_2letter_noise(name: str) -> bool:
    """Detect 2-letter fragments that are NOT real biomedical abbreviations."""
    if len(name) != 2:
        return False
    # Strip trailing whitespace (DB has padded 2-char terms)
    name_stripped = name.strip()
    if len(name_stripped) != 2:
        return False
    # Uppercase — check whitelist
    if name_stripped in SAFE_2LETTER_UPPER:
        return False
    # Mixed case (e.g., "Hp", "Kp") — check whitelists
    if name_stripped[0].isupper() and name_stripped[1].islower():
        if name_stripped in SAFE_2LETTER_MIXED:
            return False
        if name_stripped in NOISE_2LETTER_MIXED:
            return True
        # Unknown mixed case — likely noise (author initials, fragments)
        return True
    # Lowercase — always noise (truncated words)
    if name_stripped == name_stripped.lower():
        return True
    # Uppercase not in whitelist — noise (author initials, random codes)
    return True


def is_geo_name(name: str) -> bool:
    """Check if entity is a geographic name."""
    return name in GEO_NAMES


def is_journal_name(name: str) -> bool:
    """Check if entity is a journal/publisher name."""
    return name in JOURNAL_NAMES


def is_company_name(name: str) -> bool:
    """Check if entity is a company/supplier name."""
    return name in COMPANY_NAMES


def is_stopword(name: str) -> bool:
    """Check if entity is a stopword or generic English word."""
    # 'ITS' = Internal Transcribed Spacer (microbiome sequencing region) — real biomedical term
    if name == "ITS":
        return False
    return name.lower() in STOPWORDS


def is_non_latin(name: str) -> bool:
    """Check if entity contains non-Latin script (Korean, Chinese, Japanese)."""
    return bool(re.search(r"[가-힣一-龯ぁ-んァ-ン]", name))


def is_thorn_artifact(name: str) -> bool:
    """Check if entity contains thorn (þ) — OCR corruption of '+'."""
    return "þ" in name


def is_truncated(name: str) -> bool:
    """Check if entity is a truncated word fragment.

    ONLY catches actual suffix fragments ("tion", "ated", "tive", "sion", etc.)
    and short generic lowercase words NOT in the biomedical whitelist.
    Does NOT delete entities with ﬁ/ﬂ ligatures — those are real terms with
    OCR artifacts that should be FIXED, not deleted.
    """
    name_stripped = name.strip()
    # Actual truncated suffixes with no root word
    if name_stripped in TRUNCATED_WORDS:
        return True
    # 3-4 letter lowercase that's NOT in the biomedical whitelist → likely truncated
    if len(name_stripped) <= 4 and name_stripped == name_stripped.lower():
        if name_stripped not in REAL_SHORT_BIOMED:
            return True
    return False


def has_ligature(name: str) -> bool:
    """Check if entity contains ﬁ (fi), ﬂ (fl), or ­ (soft hyphen) OCR artifacts."""
    return "ﬁ" in name or "ﬂ" in name or "­" in name


def fix_ligature(name: str) -> str:
    """Fix OCR ligature artifacts: ﬁ→fi, ﬂ→fl, ­→'' (remove soft hyphen)."""
    fixed = name.replace("ﬁ", "fi").replace("ﬂ", "fl").replace("­", "")
    return fixed


def classify_entity(name: str) -> Tuple[str, str]:
    """Classify an entity as noise or keep.

    Returns (category, reason) where category is "keep" or a noise category.
    """
    if not name or len(name) == 0:
        return "empty", "empty string"

    if is_non_latin(name):
        return "non_latin", "non-Latin script"

    if is_thorn_artifact(name):
        return "thorn_artifact", "OCR thorn (þ) artifact"

    if is_author_name(name):
        return "author_name", "author name pattern"

    if is_geo_name(name):
        return "geo_name", "geographic name"

    if is_journal_name(name):
        return "journal_name", "journal/publisher name"

    if is_company_name(name):
        return "company_name", "company/supplier name"

    if is_2letter_noise(name):
        return "two_letter_fragment", "2-letter fragment not in whitelist"

    if is_stopword(name):
        return "stopword", "generic English word"

    if is_truncated(name):
        return "truncated", "truncated word fragment"

    return "keep", ""


# ── DB deletion ─────────────────────────────────────────────

def delete_entities(conn: sqlite3.Connection, noise_ids: List[int]) -> dict:
    """Delete noise entities with full cascade."""
    if not noise_ids:
        return {"entities": 0, "relationships": 0, "edge_evidence": 0, "entity_project_mentions": 0}

    placeholders = ",".join("?" * len(noise_ids))

    # 1. Find relationship IDs referencing noise entities
    rel_ids = [
        r[0] for r in conn.execute(
            f"SELECT id FROM relationships "
            f"WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders})",
            noise_ids + noise_ids,
        ).fetchall()
    ]

    # 2. Delete edge_evidence
    ev_count = 0
    if rel_ids:
        ev_ph = ",".join("?" * len(rel_ids))
        ev_count = conn.execute(
            f"DELETE FROM edge_evidence WHERE relationship_id IN ({ev_ph})",
            rel_ids,
        ).rowcount

    # 3. Delete relationships
    rel_count = conn.execute(
        f"DELETE FROM relationships "
        f"WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders})",
        noise_ids + noise_ids,
    ).rowcount

    # 4. Delete entity_project_mentions
    epm_count = conn.execute(
        f"DELETE FROM entity_project_mentions WHERE entity_id IN ({placeholders})",
        noise_ids,
    ).rowcount

    # 5. Delete entities
    ent_count = conn.execute(
        f"DELETE FROM entities WHERE id IN ({placeholders})",
        noise_ids,
    ).rowcount

    conn.commit()
    return {
        "entities": ent_count,
        "relationships": rel_count,
        "edge_evidence": ev_count,
        "entity_project_mentions": epm_count,
    }


# ── Main ────────────────────────────────────────────────────

def run_deterministic_cleanup(
    db_path: Path,
    apply: bool = False,
    delete: bool = False,
    checkpoint_path: Path | None = None,
) -> dict:
    """Run deterministic noise cleanup on all entities.

    Returns summary with counts per category and list of noise entities.
    """
    logger.info("=" * 60)
    logger.info("DETERMINISTIC NOISE CLEANUP")
    logger.info("=" * 60)
    logger.info(f"  DB: {db_path}")
    logger.info(f"  Apply: {apply}")
    logger.info(f"  Delete: {delete}")

    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()

    rows = c.execute(
        "SELECT id, term, entity_type, confidence_score FROM entities ORDER BY id"
    ).fetchall()

    logger.info(f"  Total entities: {len(rows)}")

    # Classify each entity
    noise_by_category: Dict[str, List[tuple]] = {}
    keep_count = 0

    for row in rows:
        eid, name, etype, conf = row
        name_str = str(name) if name else ""
        category, reason = classify_entity(name_str)

        if category == "keep":
            keep_count += 1
        else:
            if category not in noise_by_category:
                noise_by_category[category] = []
            noise_by_category[category].append((eid, name_str, etype, conf, reason))

    # Print summary
    total_noise = sum(len(v) for v in noise_by_category.values())
    logger.info(f"  Keep: {keep_count}")
    logger.info(f"  Noise (to delete): {total_noise}")

    for cat in sorted(noise_by_category.keys()):
        items = noise_by_category[cat]
        logger.info(f"\n  {cat} ({len(items)}):")
        for eid, name, etype, conf, reason in items[:20]:
            logger.info(f"    id={eid} '{name}' type={etype} conf={conf:.2f}")
        if len(items) > 20:
            logger.info(f"    ... and {len(items) - 20} more")

    # Save checkpoint
    if checkpoint_path:
        checkpoint = {
            "total_entities": len(rows),
            "keep": keep_count,
            "noise_total": total_noise,
            "noise_by_category": {
                cat: [
                    {"id": eid, "name": name, "type": etype, "conf": conf, "reason": reason}
                    for eid, name, etype, conf, reason in items
                ]
                for cat, items in noise_by_category.items()
            },
        }
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        with open(checkpoint_path, "w", encoding="utf-8") as f:
            json.dump(checkpoint, f, ensure_ascii=False, indent=2)
        logger.info(f"  Checkpoint saved: {checkpoint_path}")

    # Delete noise entities
    deleted = {"entities": 0, "relationships": 0, "edge_evidence": 0, "entity_project_mentions": 0}
    if apply and delete:
        all_noise_ids = []
        for items in noise_by_category.values():
            for eid, name, etype, conf, reason in items:
                all_noise_ids.append(eid)

        if all_noise_ids:
            logger.info(f"\n  Deleting {len(all_noise_ids)} noise entities...")
            deleted = delete_entities(conn, all_noise_ids)
            logger.info(
                f"  DELETED: {deleted['entities']} entities, "
                f"{deleted['relationships']} relationships, "
                f"{deleted['edge_evidence']} edge_evidence, "
                f"{deleted['entity_project_mentions']} entity_project_mentions"
            )

    # Post-deletion counts
    if apply and delete:
        c2 = conn.cursor()
        final_ents = c2.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        final_rels = c2.execute("SELECT COUNT(*) FROM relationships").fetchone()[0]
        final_ev = c2.execute("SELECT COUNT(*) FROM edge_evidence").fetchone()[0]
        logger.info(f"\n  Final counts: {final_ents} entities, {final_rels} relationships, {final_ev} evidence")

    conn.close()

    return {
        "total_entities": len(rows),
        "keep": keep_count,
        "noise": {cat: len(items) for cat, items in noise_by_category.items()},
        "noise_total": total_noise,
        "deleted": deleted if (apply and delete) else None,
    }


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    parser = argparse.ArgumentParser(
        description="Deterministic cleanup of remaining noise entities"
    )
    parser.add_argument("--db", type=Path, required=True, help="Path to SQLite DB")
    parser.add_argument("--apply", action="store_true", help="Write changes to DB")
    parser.add_argument("--delete", action="store_true", help="Physically delete noise entities")
    parser.add_argument(
        "--checkpoint-dir", type=Path, default=None, help="Directory for checkpoints"
    )
    args = parser.parse_args()

    checkpoint_dir = args.checkpoint_dir or args.db.parent / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = checkpoint_dir / "deterministic_cleanup.json"

    result = run_deterministic_cleanup(
        db_path=args.db,
        apply=args.apply,
        delete=args.delete,
        checkpoint_path=checkpoint_path,
    )

    print("\n" + "=" * 60)
    print("Deterministic Cleanup Summary")
    print("=" * 60)
    print(f"  Total entities: {result['total_entities']}")
    print(f"  Keep: {result['keep']}")
    print(f"  Noise total: {result['noise_total']}")
    for cat, count in sorted(result["noise"].items()):
        print(f"    {cat}: {count}")
    if result.get("deleted"):
        d = result["deleted"]
        print(f"  Deleted: {d['entities']} entities, {d['relationships']} relationships, "
              f"{d['edge_evidence']} evidence")


if __name__ == "__main__":
    main()
