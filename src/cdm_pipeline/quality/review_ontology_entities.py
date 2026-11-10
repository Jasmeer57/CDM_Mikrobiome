#!/usr/bin/env python3
"""Review all 26,538 entities — flag non-biomedical or misclassified entities.

Categories:
1. generic_word — generic English words that are not biomedical entities
2. adjective — standalone adjectives with no specific biomedical meaning
3. verb_form — verbs/participles used as entities
4. time_unit — time/measurement units
5. ocr_fragment — OCR artifact fragments (truncated words)
6. wrong_type — entity with incorrect entity_type (fix or delete)
"""
from __future__ import annotations

_CDM_ROOT = next(p for p in __import__("pathlib").Path(__file__).resolve().parents
                 if (p / ".cdm_root").is_file())  # repo root, found at run time
import json, os, sys, sqlite3, argparse
from pathlib import Path

# ── Generic English words that are NOT biomedical entities ──────────────
GENERIC_WORDS = {
    # Generic nouns/concepts
    "impact", "research", "associated with", "composition", "function", "analyses",
    "evidence", "model", "models", "source", "status", "position",
    "length", "standard", "version", "variability", "parameters", "protocol",
    "literature", "database", "data set", "accuracy", "prediction", "data processing",
    "correlations", "design", "study design", "cases", "responses", "activity",
    "clusters", "cluster", "criteria", "heatmap", "target",
    "region", "sites", "growth", "development",
    "subject", "percentage", "variance", "standard deviation", "sd",
    "administration", "weight", "progression", "nutrition",
    "intake", "prevention", "quantitative", "statistical",
    "commensal", "biota", "taxon", "taxa", "taxonomic",
    "phenotype", "phenotypes", "diagnosis",
    "mortality", "incidence", "prevalence",
    "inclusion", "effects of", "effects", "course",
    "written informed consent",
    "r package", "laboratory",
    "sample collection", "sample size",
    "data analysis", "sequencing data",
    "experiments", "experiment",
    "lifestyle", "environment", "environmental",
    "mucosal", "fecal",
    "healthy controls", "healthy control", "control", "controls",
    "clinical trial",
    "production", "alterations", "differences", "difference",
    "resistance", "symptoms", "symptom", "pathogenesis",
    "alteration", "response", "finding", "findings",
    "outcome", "outcomes", "result", "results",
    "method", "methods", "approach", "approaches",
    "analysis", "study", "studies",
    "cohort", " cohorts",
    "sample", "samples", "sampling",
    "data", "dataset", "datasets",
    "group", "groups", "grouping",
    "type", "types", "category", "categories",
    "level", "levels",
    "rate", "rates",
    "factor", "factors",
    "change", "changes", "modification", "modifications",
    "association", "associations",
    "correlation",
    "significance", "significant",
    "abundance", "abundant",
    "diversity",
    "composition",
    "baseline",
    "feature", "features",
    "characteristic", "characteristics",
    "property", "properties",
    "condition", "conditions",
    "state", "states",
    "treatment", "treatments",
    "therapy", "therapies",
    "intervention", "interventions",
    "diet", "diets", "dietary",
    "age", "aging",
    "sex", "gender",
    "health", "disease", "diseases",
    # Generic adjectives
    "metabolic", "molecular", "clinical", "ecological",
    "genomic", "phylogenetic", "chronic", "severe", "anaerobic",
    "intestinal", "bacterial",
    "immunity", "immune",
    "healthy", "normal", "abnormal",
    # Additional generic words spotted in output
    "disease", "diseases", "health", "treatment", "treatments",
    "diet", "diets", "dietary",
    "diversity", "cohort", "cohorts",
    "abundance",
}

# ── Verb forms / participles that are not entities ─────────────────────
VERB_FORMS = {
    "comparing", "compared", "increasing", "evaluated", "tested",
    "clustered", "treated", "identified", "measured", "observed",
    "associated", "correlated", "related", "linked",
    "analyzed", "investigated", "examined", "assessed",
    "determined", "detected", "found", "reported",
    "performed", "conducted", "carried", "used",
    "shown", "demonstrated", "revealed", "showed",
    "described", "characterized", "classified",
}

# ── Time/measurement units ──────────────────────────────────────────────
TIME_UNITS = {
    "months", "weeks", "day", "days", "period", "duration",
    "year", "years", "time", "times",
    "hour", "hours", "minute", "minutes",
}

# ── OCR fragment artifacts (truncated words) ────────────────────────────
OCR_FRAGMENTS = {
    "bolic",       # fragment of "metabolic" or "antibiotic"
    "cific",       # fragment of "specific"
    "peutic",      # fragment of "therapeutic"
    "pecific",     # fragment of "specific"
    "atological",  # fragment of "pathological" or "hematological"
    "logical",     # fragment of various -ological words
    "nal",         # fragment
    "genic",       # could be real but too short to be meaningful
}

# ── Wrong entity type: (term, wrong_type) → action ─────────────────────
# action: "fix:NEW_TYPE" or "delete"
WRONG_TYPE = {
    ("Ruminococcus", "DISEASE"): "fix:ORGANISM",
    ("propionate", "DISEASE"): "fix:CHEMICAL",
    ("phyla", "DISEASE"): "delete",
    ("Sensitivity", "DISEASE"): "delete",
    ("gastrointestinal", "PATHWAY"): "delete",
    ("intake", "DISEASE"): "delete",
}

# ── Adjective whitelist — real biomedical terms ending in -ic/-ical ────
# These are NOT deleted even though they end in adjective suffixes
ADJECTIVE_WHITELIST = {
    # Antibiotics / antimicrobials
    "antibiotic", "antibiotics", "antimicrobial", "antimicrobials",
    "antiseptic", "antiviral", "antibacterial", "antifungal",
    "antiparasitic", "anthelmintic", "antihelmintic", "antianaerobic",
    "lantibiotic",
    # Probiotics / prebiotics / postbiotics
    "probiotic", "probiotics", "prebiotic", "prebiotics",
    "postbiotic", "postbiotics", "synbiotic", "synbiotics",
    "eubiotic",
    # Microbiology terms
    "aerobic", "anaerobic", "microaerobic",
    "facultative", "autochthonous", "allochthonous",
    "planktonic", "sessile", "biofilm",
    "symbiotic", "commensalistic", "pathogenic",
    "heterofermentative", "homofermentative", "saccharolytic",
    "proteolytic", "amylolytic", "cellulolytic", "xylanolytic",
    "lipolytic", "butyrogenic", "bifidogenic",
    "filamentous", "spore-forming",
    # Chemical / acid names (these refer to specific chemicals)
    "butyric", "formic", "acetic", "propionic", "lactic",
    "valeric", "caproic", "caprylic", "capric", "decanoic",
    "palmitic", "stearic", "oleic", "linoleic", "linolenic",
    "arachidonic", "palmitoleic", "myristic",
    "cholic", "chenodeoxycholic", "deoxycholic", "lithocholic",
    "taurocholic", "glycocholic", "hyodeoxycholic",
    "sialic", "uronic", "glucuronic", "galacturonic",
    "pectic", "suberic", "sebacic", "azelaic", "orotic",
    "aromatic", "aliphatic", "phenolic",
    "citric", "malic", "fumaric", "succinic", "oxalic",
    "glutaric", "adipic", "pimelic",
    "hippuric", "indoleacetic", "indolepropionic",
    # Omics / methods
    "metabolomic", "metabolomics", "proteomic", "proteomics",
    "transcriptomic", "transcriptomics", "metagenomic", "metagenomics",
    "metatranscriptomic", "metatranscriptomics",
    "physicochemical", "metabonomic", "metabonomics",
    "phylogenomic", "phylogenomics",
    # Disease/condition adjectives that are used as clinical entities
    "diabetic", "diabetics",
    "cirrhotic", "cirrhotics",
    "atopic",
    "autistic",
    "hypertensive",
    "hypotensive",
    "atherosclerotic",
    "osteoporotic",
    "anemic",
    "bacteremic",
    "viremic",
    "endotoxemic",
    "neutropenic", "neutropaenic",
    "leukemic",
    "ischemic",
    "hemolytic", "haemolytic",
    "necrotic",
    "fibrinolytic",
    "fibrotic",
    "ulcerative",
    "inflammatory",
    "adenomatous",
    "carcinogenic", "tumorigenic", "oncogenic", "mutagenic",
    "genotoxic", "cytotoxic", "hepatotoxic", "nephrotoxic",
    "neurotoxic", "cardiotoxic",
    "invasive",
    "metastatic",
    "hypercholesterolemic", "hyperglycemic", "hypoglycemic",
    "normoglycemic", "hypolipidemic",
    "cholestatic",
    "steatotic",
    "psoriatic",
    "eczematous",
    "depressive",
    "anxious",
    "hypoxic", "anoxic",
    "acidotic", "alkalotic",
    "septic",
    "peptic",
    "colic",
    "immunosuppressive",
    "immunomodulatory",
    "anti-inflammatory",
    "antineoplastic",
    "anticoagulant",
    "enteroaggregative",
    "diarrheagenic", "enterotoxigenic", "enterohemorrhagic",
    "enterotoxic",
    "enteroinvasive",
    "precancerous", "premalignant",
    # Genetics
    "epigenetic", "epigenetics",
    "transgenic",
    "monozygotic", "dizygotic",
    "heterozygous", "homozygous",
    # Clinical states
    "asymptomatic", "symptomatic",
    "progressive",
    "spontaneous",
    "consecutive",
    "prospective", "retrospective",
    "preclinical",
    "nonmyeloablative", "myeloablative",
    # Neuro / psych
    "dopaminergic", "gabaergic", "glutamatergic", "serotonergic",
    "cholinergic", "adrenergic", "noradrenergic",
    "neurogenic", "neurotrophic", "neuroprotective",
    "neurological", "neuropsychiatric",
    # Pharmacological
    "pharmacologic", "pharmacological",
    "therapeutic",
    "bioavailable", "biosynthetic",
    # Cell/tissue types
    "dendritic",
    "synaptic", "cytosolic",
    "intracellular", "extracellular", "transcellular",
    "mucosal", "submucosal", "serosal",
    "cutaneous", "subcutaneous",
    "intracolonic", "intrarectal",
    "glutamatergic",
    "phagocytic",
    # Ecology
    "saprotrophic", "heterotrophic",
    # Demographics
    "demographic",
    "anthropometric",
    "hispanic",
    # Experimental
    "nonparametric",
    "multivariable",
    # Database / resource names (not adjectives but caught by -ic)
    "massive",
    "patric",
    # Other real terms
    "dysbiotic",
    "bifidogenic",
    "symbiotic",
    "eubiotic",
    "normoglycemic",
    "biomedical",
    "physiological", "physiologic",
    "gastric", "enteric", "digestive",
    "opportunistic",
    "enzymatic",
    "histological",
    "infectious",
    "medical",
    "characteristic",
    "immunological",
    "colonic",
    "bioactive", "bioaccessible",
    "antagonistic",
    "pervasive",
    "organic", "inorganic",
    "ionic", "zwitterionic",
    "aqueous",
    "aromatic",
    "obstetric",
    "amnestic",
    "hyperactive",
    "multiparous",
    "sonographic",
    "heterogenous", "heterogeneous",
    "phylogenic", "phylogenetic",
    "permissive",
    "recessive", "dominant",
    "sympathetic", "parasympathetic",
    "systemic",
    "toxic",
    "virulence",
    "pathologic", "pathological",
    "diagnostic",
    "endoscopic",
    "epidemiologic", "epidemiological",
    "eukaryotic", "prokaryotic",
    "hepatic",
    "immunologic",
    "intramammary",
    "neoplastic",
    "psychiatric",
    "clinically",
    "epidemic", "pandemic", "endemic",
    "postmenopausal", "premenopausal",
    "metabolomic",
    "microbial", "microbiologic",
    "bactericidal",
    "chemotherapeutic",
    "cancerous",
    "allergic",
    "cognitive",
    "antibacterial",
    "immunomodulative",
    "virological",
    "arachidonic",
    "traumatic",
    "monocentric",
    "manic", "melancholic",
    "schizoaffective",
    "dyspeptic",
    "dyskinetic",
    "oncologic",
    "nephrological",
    "endocrinological",
    "jejunocolic",
    "proteolytic",
    "transgenic",
    "naive",
    "filamentous",
    "chermic",
    "calcic",
    "chaotropic",
    "phenylcarboxylic",
    "metapeptidomic",
    "bacteriocidal",
    "verotoxigenic",
    "methanogenic",
    "acidogenic",
    "aciduric",
    "acidophilic",
    "basophilic",
    "neutrophilic",
    "eosinophilic",
    "halophilic",
    "thermophilic",
    "psychrophilic",
    "alkaliphilic",
    "barophilic",
    "xerotolerant",
    "osmotic",
    "chemagic",  # Chemagic = brand name, not adjective
    "hilic",     # HILIC = Hydrophilic Interaction Liquid Chromatography
    "hyocholic",
    "muricholic",
    "sulfonic",
    "nitric",
    "nucleic",
}


def is_problematic(item: dict) -> tuple[str, str] | None:
    """Return (reason, detail) if entity is problematic, else None."""
    term = item["term"]
    term_lower = term.lower().strip()
    etype = item["type"]

    # Wrong entity type
    if (term, etype) in WRONG_TYPE:
        action = WRONG_TYPE[(term, etype)]
        if action == "delete":
            return ("wrong_type_delete", f"'{term}' classified as {etype} — too generic, delete")
        elif action.startswith("fix:"):
            return ("wrong_type_fix", f"'{term}' classified as {etype} — should be {action[4:]}")

    # Generic English words
    if term_lower in GENERIC_WORDS:
        return ("generic_word", f"'{term}' is a generic English word, not a biomedical entity")

    # Time units
    if term_lower in TIME_UNITS:
        return ("time_unit", f"'{term}' is a time/measurement unit")

    # Verb forms
    if term_lower in VERB_FORMS:
        return ("verb_form", f"'{term}' is a verb/participle, not an entity")

    # OCR fragments
    if term_lower in OCR_FRAGMENTS:
        return ("ocr_fragment", f"'{term}' is an OCR fragment/truncated word")

    # Adjective patterns — standalone adjectives are not entities
    # BUT only flag if it's a single word (multi-word terms are more specific)
    if " " not in term and "-" not in term and "/" not in term and len(term_lower) > 4:
        ADJECTIVE_ENDINGS = ("ic", "ical", "ive", "ous", "able", "ible")
        if any(term_lower.endswith(suffix) for suffix in ADJECTIVE_ENDINGS):
            if term_lower not in ADJECTIVE_WHITELIST:
                # Check if it has grounding — if it has NCBITaxon or UMLS, it might be real
                grounding = item.get("grounding", "")
                if "NCBITaxon" in grounding or "MeSH" in grounding:
                    # Has strong biomedical grounding — keep but flag for review
                    return ("adjective_review", f"'{term}' is an adjective but has grounding: {grounding}")
                return ("adjective", f"'{term}' is an adjective, not a standalone entity")

    return None


def main():
    parser = argparse.ArgumentParser(description="Review entities with ontology mappings")
    parser.add_argument("--review_dir", default=str(_CDM_ROOT / "paper/_multi_ner_runs/cdm_output/ontology_review"))
    parser.add_argument("--db", default=str(_CDM_ROOT / "paper/_multi_ner_runs/cdm_output/microbiome_cdm.db"))
    parser.add_argument("--batch", type=int, default=None, help="Review only this batch number")
    parser.add_argument("--apply", action="store_true", help="Delete flagged entities from DB")
    parser.add_argument("--dry_run", action="store_true", default=True, help="Don't delete, just report")
    parser.add_argument("--no_dry_run", dest="dry_run", action="store_false", help="Actually apply changes")
    parser.add_argument("--show_all", action="store_true", help="Show all flagged items, not just first 20")
    args = parser.parse_args()

    review_dir = Path(args.review_dir)

    # Load batches
    if args.batch:
        batch_files = sorted(review_dir.glob(f"batch_{args.batch:03d}.json"))
    else:
        batch_files = sorted(review_dir.glob("batch_*.json"))

    all_flagged = []
    total_reviewed = 0

    for bf in batch_files:
        with open(bf, encoding="utf-8") as f:
            items = json.load(f)
        total_reviewed += len(items)
        for item in items:
            result = is_problematic(item)
            if result:
                reason, detail = result
                all_flagged.append({
                    "id": item["id"],
                    "term": item["term"],
                    "type": item["type"],
                    "papers": item["papers"],
                    "reason": reason,
                    "detail": detail,
                    "grounding": item["grounding"],
                })

    # Sort by papers (descending) — most impactful first
    all_flagged.sort(key=lambda x: x["papers"], reverse=True)

    # Separate into actions
    to_delete = [i for i in all_flagged if i["reason"] not in ("wrong_type_fix", "adjective_review")]
    to_fix = [i for i in all_flagged if i["reason"] == "wrong_type_fix"]
    to_review = [i for i in all_flagged if i["reason"] == "adjective_review"]

    # Group by reason
    by_reason: dict[str, list] = {}
    for item in all_flagged:
        by_reason.setdefault(item["reason"], []).append(item)

    print(f"\n{'='*60}")
    print(f"ONTOLOGY ENTITY REVIEW")
    print(f"{'='*60}")
    print(f"  Total entities reviewed: {total_reviewed}")
    print(f"  Total flagged: {len(all_flagged)}")
    print(f"    → to delete:  {len(to_delete)}")
    print(f"    → to fix type: {len(to_fix)}")
    print(f"    → to review:   {len(to_review)}")
    print(f"  Batches: {len(batch_files)}")
    print()
    for reason, items in sorted(by_reason.items()):
        show_n = len(items) if args.show_all else min(len(items), 20)
        print(f"  {reason} ({len(items)}):")
        for item in items[:show_n]:
            print(f"    id={item['id']:6d} '{item['term']:30s}' type={item['type']:20s} papers={item['papers']:4d}  {item['grounding']}")
        if len(items) > show_n:
            print(f"    ... and {len(items) - show_n} more")
        print()

    # Save flagged list
    out_file = review_dir / "flagged_for_removal.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(all_flagged, f, ensure_ascii=False, indent=2)
    print(f"  Flagged list saved: {out_file}")

    # Apply deletions if requested
    if args.apply and not args.dry_run:
        ids_to_delete = [item["id"] for item in to_delete]
        print(f"\n  Deleting {len(ids_to_delete)} flagged entities from DB...")
        conn = sqlite3.connect(args.db)
        c = conn.cursor()
        placeholders = ",".join("?" * len(ids_to_delete))

        # Count cascading deletions
        ids2 = ids_to_delete + ids_to_delete
        rel_count = c.execute(f"SELECT COUNT(*) FROM relationships WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders})", ids2).fetchone()[0]
        evi_count = c.execute(f"SELECT COUNT(*) FROM edge_evidence WHERE relationship_id IN (SELECT id FROM relationships WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders}))", ids2).fetchone()[0]
        ment_count = c.execute(f"SELECT COUNT(*) FROM entity_project_mentions WHERE entity_id IN ({placeholders})", ids_to_delete).fetchone()[0]
        print(f"  Will cascade: {rel_count} relationships, {evi_count} evidence, {ment_count} mentions")

        # Delete cascade
        c.execute(f"DELETE FROM edge_evidence WHERE relationship_id IN (SELECT id FROM relationships WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders}))", ids2)
        c.execute(f"DELETE FROM relationships WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders})", ids2)
        c.execute(f"DELETE FROM entity_project_mentions WHERE entity_id IN ({placeholders})", ids_to_delete)
        c.execute(f"DELETE FROM entities WHERE id IN ({placeholders})", ids_to_delete)

        # Fix wrong types
        for item in to_fix:
            term = item["term"]
            old_type = item["type"]
            new_type = item["detail"].split("should be ")[1]
            print(f"  Fixing: '{term}' {old_type} → {new_type}")
            c.execute("UPDATE entities SET entity_type = ? WHERE term = ? AND entity_type = ?", (new_type, term, old_type))

        conn.commit()

        remaining = c.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        rel_remaining = c.execute("SELECT COUNT(*) FROM relationships").fetchone()[0]
        evi_remaining = c.execute("SELECT COUNT(*) FROM edge_evidence").fetchone()[0]
        print(f"\n  Remaining: {remaining} entities, {rel_remaining} relationships, {evi_remaining} evidence")
        conn.close()


if __name__ == "__main__":
    main()
