"""
Build a small-scale "hybrid" knowledge graph from the LLM and spaCy batch runs
under paper_claims/_llm_runs/ and _spacy_runs/. The 5 sources are:

  S1. LLM entities        (CDM-typed, with confidence + paper context)
  S2. spaCy NER entities  (per-model labels, 4 models in parallel)
  S3. Cross-paper co-occurrence edges
  S4. Type-based canonical edges (ORGANISM-DISEASE, CHEMICAL-DISEASE, ...)
  S5. Cross-source co-mention (LLM term + spaCy term, same paper)
  S6. Biological-KB seed entities (curated; organism/drug/disease with known associations)

Version 2 changes:
  - Imports paper_claims/biological_kb.py for type validation and synonym expansion
  - Re-types entities whose type disagrees with the KB (e.g., "Fusobacterium" → ORGANISM)
  - Adds curated KB entities (all 65 organisms, 44 drugs, 22 diseases) as the S6 source
  - Adds curated edges (drug treats disease, organism associated with disease) from KNOWN_ASSOCIATIONS
  - Preserves all original behavior; just adds the biological layer

Outputs to paper_claims/claim_C_hybrid_fusion/mini_hybrid_v2/:
  - entities.json     (list of entity dicts with `source` provenance)
  - relationships.json (list of relationship dicts)
  - sources.json      (counts per source)
  - biological_soundness.txt (recall check against KNOWN_ASSOCIATIONS)
"""
import sys, io
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
import argparse, csv, json, re
from collections import defaultdict, Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))
from paper_claims.biological_kb import (
    norm, lookup, canonicalize,
    ORGANISMS, DRUGS, DISEASES, KNOWN_ASSOCIATIONS, kb_stats,
    SCFA_TREATS_INFLAMMATION, ANTIBIOTIC_DISRUPTS,
    CATEGORY_TO_DISEASE,
)

DEFAULT_LLM = REPO_ROOT / "paper_claims" / "_llm_runs"
DEFAULT_SPACY = REPO_ROOT / "paper_claims" / "_spacy_runs"
DEFAULT_OUT = REPO_ROOT / "paper_claims" / "claim_C_hybrid_fusion" / "mini_hybrid_v2"

# Type-pair canonical relation hints (from kg_pipeline.py VALID_TYPE_PAIRS).
CANONICAL_PAIRS = {
    ("ORGANISM", "DISEASE"): "associated_with",
    ("DISEASE", "ORGANISM"): "associated_with",
    ("ORGANISM", "CHEMICAL"): "produces",
    ("CHEMICAL", "ORGANISM"): "produced_by",
    ("CHEMICAL", "DISEASE"): "treats",
    ("DISEASE", "CHEMICAL"): "treated_by",
    ("GENE", "PROTEIN"): "encodes",
    ("PROTEIN", "GENE"): "encoded_by",
    ("PATHWAY", "CHEMICAL"): "involves",
    ("CHEMICAL", "PATHWAY"): "involved_in",
    ("PATHWAY", "DISEASE"): "implicated_in",
    ("DISEASE", "PATHWAY"): "implicates",
    ("ORGANISM", "PATHWAY"): "participates_in",
    ("PATHWAY", "ORGANISM"): "participates_in",
}


# ----------------------------------------------------------------------------
# Entity validation filter (rejects garbage entities at source)
# ----------------------------------------------------------------------------

_GARBAGE_AFFILIATIONS = re.compile(
    r"\b(department|division|institute|laboratory|school|college|"
    r"faculty|center|centre|university|hospital|clinic)\b",
    re.IGNORECASE,
)
_GARBAGE_JOURNALS = {
    "nucleic acids res", "nucleic acids research",
    "nature", "science", "cell", "pnas", "plos one",
    "front microbiol", "appl environ microbiol",
}
_GARBAGE_EXACT = {
    "ated", "ples", "demon-", "bi dobacterium", "mmol l",
    "rev", "f d", "l k", "c l", "base-",
}
_GARBAGE_AUTHOR = re.compile(r"^\d+,\s+[A-Z][a-z]")  # e.g. "3, Hiroko"
_GARBAGE_NUMERIC = re.compile(r"^[\d≤≥<>=+\-\.,\s]+$")
_GARBAGE_DNA_SEQ = re.compile(r"^[ACGT]{10,}$", re.IGNORECASE)
_GARBAGE_PRIMER = re.compile(r"[ACGT]{20,}", re.IGNORECASE)


def is_valid_entity(term: str) -> bool:
    """Return False if the term is a garbage entity (truncation, affiliation,
    journal name, numeric, DNA sequence, author fragment, or too short).

    This is a conservative filter: it only rejects clear garbage.  Ambiguous
    short tokens that happen to be valid (e.g. 'IBD', 'IL-6', 'SCFA') are kept
    because they survive the length check (>= 3) and are not pure-symbol.
    """
    t = (term or "").strip()
    if len(t) < 3:
        return False
    if t.startswith("-") or t.endswith("-"):
        return False
    if _GARBAGE_AUTHOR.match(t):
        return False
    if _GARBAGE_NUMERIC.match(t):
        return False
    if _GARBAGE_DNA_SEQ.match(t):
        return False
    if _GARBAGE_PRIMER.search(t):
        return False
    if _GARBAGE_AFFILIATIONS.search(t):
        return False
    if t.lower() in _GARBAGE_JOURNALS or t.lower() in _GARBAGE_EXACT:
        return False
    return True


# ----------------------------------------------------------------------------
# Loaders
# ----------------------------------------------------------------------------

def load_llm(llm_dir: Path):
    """Return triples and per-paper term sets, with KB-validated types."""
    triples, by_paper = [], defaultdict(set)
    n_rejected = 0
    for j in sorted(llm_dir.glob("*.cdm_entities.json")):
        try:
            d = json.loads(j.read_text(encoding="utf-8"))
        except Exception:
            continue
        paper = j.stem.replace(".cdm_entities", "")
        inner = d.get("results", {}).get("cdm_entities", {}) or {}
        for etype, lst in inner.items():
            for e in (lst or []):
                term = e.get("entity") or e.get("term")
                if not term:
                    continue
                if not is_valid_entity(term):
                    n_rejected += 1
                    continue
                conf = float(e.get("confidence") or 0.0)
                # KB-validate: if term is in KB, override type with KB type
                kbinfo = lookup(term)
                if kbinfo:
                    etype = kbinfo["type"]  # KB wins
                triples.append((term.strip(), etype, conf, paper))
                by_paper[paper].add(norm(term))
    print(f"  [llm] rejected garbage entities: {n_rejected}")
    return triples, by_paper


def load_spacy(spacy_dir: Path):
    """Return triples and per-paper term sets, with KB-validated types."""
    triples, by_paper = [], defaultdict(set)
    n_rejected = 0
    for j in sorted(spacy_dir.glob("*.spacy_ner.csv")):
        paper = j.stem.replace(".spacy_ner", "")
        try:
            with open(j, "r", encoding="utf-8", newline="") as f:
                r = csv.DictReader(f)
                for row in r:
                    term = row.get("term", "").strip()
                    label = row.get("labels", "").strip()
                    if not term or len(term) < 2:
                        continue
                    if label == "ENTITY":
                        continue
                    if not is_valid_entity(term):
                        n_rejected += 1
                        continue
                    # KB-validate: prefer KB type over scispaCy label
                    kbinfo = lookup(term)
                    if kbinfo:
                        coarse = kbinfo["type"]
                    else:
                        coarse = {
                            "CHEBI": "CHEMICAL", "CHEMICAL": "CHEMICAL", "DRUG": "CHEMICAL",
                            "TAXON": "ORGANISM", "GGP": "PROTEIN", "SO": "DNA_RNA",
                            "DNA": "DNA_RNA", "RNA": "DNA_RNA",
                            "PROTEIN": "PROTEIN", "GENE": "GENE",
                            "DISEASE": "DISEASE",
                            "CELL_LINE": "CELL_TYPE", "CELL_TYPE": "CELL_TYPE",
                        }.get(label.upper(), "UNKNOWN")
                    triples.append((term, coarse, paper))
                    by_paper[paper].add(norm(term))
        except Exception:
            continue
    print(f"  [spacy] rejected garbage entities: {n_rejected}")
    return triples, by_paper


# ----------------------------------------------------------------------------
# KB-seed entities (S6)
# ----------------------------------------------------------------------------

def add_kb_seed_entities(seen: dict) -> int:
    """Add all canonical names from ORGANISMS, DRUGS, DISEASES as seed entities.
    These are added even if not detected by LLM/spaCy, so the KG has the basic
    biological vocabulary for queryability.

    Returns the number of new entities added.
    """
    added = 0
    for canonical, info in ORGANISMS.items():
        if norm(canonical) in seen:
            continue
        seen[norm(canonical)] = {
            "term": canonical,
            "term_norm": norm(canonical),
            "type": "ORGANISM",
            "source": "kb_seed",
            "sources": ["kb_seed"],
            "paper_count": 0,
            "papers": [],
            "ncbi_taxon": info.get("ncbi_taxon"),
            "produces": info.get("produces", []),
            "depleted_in": info.get("depleted_in", []),
            "enriched_in": info.get("enriched_in", []),
            "category": info.get("category", ""),
        }
        added += 1
    for canonical, info in DRUGS.items():
        if norm(canonical) in seen:
            continue
        seen[norm(canonical)] = {
            "term": canonical,
            "term_norm": norm(canonical),
            "type": "CHEMICAL",
            "source": "kb_seed",
            "sources": ["kb_seed"],
            "paper_count": 0,
            "papers": [],
            "drug_class": info.get("drug_class", ""),
            "treats": info.get("treats", []),
            "disrupts": info.get("disrupts", []),
        }
        added += 1
    for canonical, info in DISEASES.items():
        if norm(canonical) in seen:
            continue
        seen[norm(canonical)] = {
            "term": canonical,
            "term_norm": norm(canonical),
            "type": "DISEASE",
            "source": "kb_seed",
            "sources": ["kb_seed"],
            "paper_count": 0,
            "papers": [],
            "abbrev": info.get("abbrev", ""),
            "is_subtype_of": info.get("is_subtype_of", ""),
        }
        added += 1
    return added


# ----------------------------------------------------------------------------
# KB-seed relationships (curated biology)
# ----------------------------------------------------------------------------

def add_kb_seed_relationships(seen: dict, relationships: list) -> int:
    """Add curated biology edges from KNOWN_ASSOCIATIONS to the relationships list.

    The rebalanced KNOWN_ASSOCIATIONS uses several relation shapes:
      - depleted_organisms / enriched_organisms / treatments (old style, kept)
      - producer_to_product: list of (organism, chemical) tuples
      - metabolite_to_disease: list of (chemical, disease) tuples
      - organism_to_disease: list of (organism, disease) tuples
      - antibiotic_to_organism: list of (drug, organism) tuples (disrupts)
      - probiotic_to_condition: list of (organism, condition) tuples (treats)
    """
    added = 0

    def _add_edge(src: str, rel: str, tgt: str, conf: float, evidence: str):
        s_n, t_n = norm(src), norm(tgt)
        if s_n in seen and t_n in seen:
            relationships.append({
                "source_entity": seen[s_n]["term"],
                "target_entity": seen[t_n]["term"],
                "relationship_type": rel,
                "source_db": "kb_curated",
                "paper_count": 0,
                "papers": [],
                "is_cross_paper": False,
                "confidence": conf,
                "evidence": evidence,
            })
            return 1
        return 0

    for category, info in KNOWN_ASSOCIATIONS.items():
        q = info.get("evidence_quality", "medium")
        # Disease targets for this category (1+ diseases; iterate each)
        disease_targets = CATEGORY_TO_DISEASE.get(category, [category])

        # Old style: depleted/enriched organisms and treatments
        for org in info.get("depleted_organisms", []):
            for disease in (disease_targets or [category]):
                added += _add_edge(org, "depleted_in", disease, 0.85,
                                   f"curated: {org} is depleted in {disease} ({q})")
        for org in info.get("enriched_organisms", []):
            for disease in (disease_targets or [category]):
                added += _add_edge(org, "enriched_in", disease, 0.85,
                                   f"curated: {org} is enriched in {disease} ({q})")
        for drug in info.get("treatments", []):
            for disease in (disease_targets or [category]):
                added += _add_edge(drug, "treats", disease, 0.95,
                                   f"curated: {drug} is approved for {disease} ({q})")

        # New style: tuple-based relations
        for org, chem in info.get("producer_to_product", []):
            added += _add_edge(org, "produces", chem, 0.90,
                               f"curated: {org} produces {chem} ({q})")

        for chem, disease in info.get("metabolite_to_disease", []):
            # For SCFA function, use 'treats'; for TMAO/atherosclerosis, 'associated_with'
            rel = "treats" if chem.lower() in ("butyrate", "propionate", "acetate", "short-chain fatty acid") else "associated_with"
            added += _add_edge(chem, rel, disease, 0.85,
                               f"curated: {chem} is {rel.replace('_',' ')} {disease} ({q})")

        for org, disease in info.get("organism_to_disease", []):
            added += _add_edge(org, "associated_with", disease, 0.80,
                               f"curated: {org} associated with {disease} ({q})")

        for drug, org in info.get("antibiotic_to_organism", []):
            # The "clindamycin -> C. difficile" entries use 'enriched_in'
            # because the antibiotic creates risk for C. diff overgrowth.
            rel = "enriched_in" if org == "clostridioides difficile" else "disrupts"
            added += _add_edge(drug, rel, org, 0.80,
                               f"curated: {drug} {rel.replace('_',' ')} {org} ({q})")

        for org, condition in info.get("probiotic_to_condition", []):
            added += _add_edge(org, "treats", condition, 0.80,
                               f"curated: {org} treats {condition} ({q})")
    # Organism -> Chemical (produces) from KB
    for org_canonical, info in ORGANISMS.items():
        for chem in info.get("produces", []):
            org_n = norm(org_canonical)
            chem_n = norm(chem)
            if org_n in seen and chem_n in seen:
                relationships.append({
                    "source_entity": seen[org_n]["term"],
                    "target_entity": seen[chem_n]["term"],
                    "relationship_type": "produces",
                    "source_db": "kb_curated",
                    "paper_count": 0,
                    "papers": [],
                    "is_cross_paper": False,
                    "confidence": 0.90,
                    "evidence": f"curated: {org_canonical} produces {chem}",
                })
                added += 1

    # Chemical -> Organism (produced_by) from KB - reverse direction
    # Many KB chemicals (GABA, serotonin, B12, vitamin K) carry `produced_by`
    # listing the organisms that produce them. Convert to `produces` from organism.
    for chem_canonical, info in DRUGS.items():
        for org in info.get("produced_by", []):
            org_n = norm(org)
            chem_n = norm(chem_canonical)
            if org_n in seen and chem_n in seen:
                relationships.append({
                    "source_entity": seen[org_n]["term"],
                    "target_entity": seen[chem_n]["term"],
                    "relationship_type": "produces",
                    "source_db": "kb_curated",
                    "paper_count": 0,
                    "papers": [],
                    "is_cross_paper": False,
                    "confidence": 0.85,
                    "evidence": f"curated: {org} produces {chem_canonical} (from DRUGS.produced_by)",
                })
                added += 1

    # ORGANISM -> DISEASE (enriched_in, depleted_in) from KB
    # Some KB organisms (e.g., H. pylori) carry `enriched_in` / `depleted_in` fields
    # listing specific diseases. Emit these as direct edges.
    for org_canonical, info in ORGANISMS.items():
        org_n = norm(org_canonical)
        for disease in info.get("enriched_in", []):
            dis_n = norm(disease)
            if org_n in seen and dis_n in seen:
                relationships.append({
                    "source_entity": seen[org_n]["term"],
                    "target_entity": seen[dis_n]["term"],
                    "relationship_type": "enriched_in",
                    "source_db": "kb_curated",
                    "paper_count": 0,
                    "papers": [],
                    "is_cross_paper": False,
                    "confidence": 0.90,
                    "evidence": f"curated: {org_canonical} enriched in {disease} (ORGANISMS.enriched_in)",
                })
                added += 1
        for disease in info.get("depleted_in", []):
            dis_n = norm(disease)
            if org_n in seen and dis_n in seen:
                relationships.append({
                    "source_entity": seen[org_n]["term"],
                    "target_entity": seen[dis_n]["term"],
                    "relationship_type": "depleted_in",
                    "source_db": "kb_curated",
                    "paper_count": 0,
                    "papers": [],
                    "is_cross_paper": False,
                    "confidence": 0.90,
                    "evidence": f"curated: {org_canonical} depleted in {disease} (ORGANISMS.depleted_in)",
                })
                added += 1

    # DRUG -> DISEASE (treats) from KB
    # Some KB drugs (e.g., rifaximin) carry `treats` fields listing specific diseases.
    # Emit these as direct edges.
    for drug_canonical, info in DRUGS.items():
        drug_n = norm(drug_canonical)
        for disease in info.get("treats", []):
            dis_n = norm(disease)
            if drug_n in seen and dis_n in seen:
                relationships.append({
                    "source_entity": seen[drug_n]["term"],
                    "target_entity": seen[dis_n]["term"],
                    "relationship_type": "treats",
                    "source_db": "kb_curated",
                    "paper_count": 0,
                    "papers": [],
                    "is_cross_paper": False,
                    "confidence": 0.95,
                    "evidence": f"curated: {drug_canonical} treats {disease} (DRUGS.treats)",
                })
                added += 1
        for disease in info.get("associated_with", []):
            dis_n = norm(disease)
            if drug_n in seen and dis_n in seen:
                relationships.append({
                    "source_entity": seen[drug_n]["term"],
                    "target_entity": seen[dis_n]["term"],
                    "relationship_type": "associated_with",
                    "source_db": "kb_curated",
                    "paper_count": 0,
                    "papers": [],
                    "is_cross_paper": False,
                    "confidence": 0.85,
                    "evidence": f"curated: {drug_canonical} associated with {disease} (DRUGS.associated_with)",
                })
                added += 1

    # SCFA -> DISEASE (treats inflammation)
    for chem, diseases in SCFA_TREATS_INFLAMMATION.items():
        chem_n = norm(chem)
        for disease in diseases:
            dis_n = norm(disease)
            if chem_n in seen and dis_n in seen:
                relationships.append({
                    "source_entity": seen[chem_n]["term"],
                    "target_entity": seen[dis_n]["term"],
                    "relationship_type": "treats",
                    "source_db": "kb_curated",
                    "paper_count": 0,
                    "papers": [],
                    "is_cross_paper": False,
                    "confidence": 0.85,
                    "evidence": f"curated: {chem} treats inflammation in {disease} (SCFA)",
                })
                added += 1

    # Antibiotic -> Organism (disrupts)
    for drug, organisms in ANTIBIOTIC_DISRUPTS.items():
        drug_n = norm(drug)
        for org in organisms:
            org_n = norm(org)
            if drug_n in seen and org_n in seen:
                relationships.append({
                    "source_entity": seen[drug_n]["term"],
                    "target_entity": seen[org_n]["term"],
                    "relationship_type": "disrupts",
                    "source_db": "kb_curated",
                    "paper_count": 0,
                    "papers": [],
                    "is_cross_paper": False,
                    "confidence": 0.80,
                    "evidence": f"curated: {drug} disrupts {org} (Dethlefsen 2011 and related)",
                })
                added += 1

    # Clindamycin -> C. difficile (enriched_in): clindamycin is a known C. diff risk factor
    if norm("clindamycin") in seen and norm("clostridioides difficile") in seen:
        relationships.append({
            "source_entity": seen[norm("clindamycin")]["term"],
            "target_entity": seen[norm("clostridioides difficile")]["term"],
            "relationship_type": "enriched_in",
            "source_db": "kb_curated",
            "paper_count": 0,
            "papers": [],
            "is_cross_paper": False,
            "confidence": 0.85,
            "evidence": "curated: clindamycin is a known C. difficile risk factor (Brown 2013)",
        })
        added += 1

    # C. difficile enriched_in CDI (semantic: the organism is "in" the infection)
    if norm("clostridioides difficile") in seen and norm("c. difficile infection") in seen:
        relationships.append({
            "source_entity": seen[norm("clostridioides difficile")]["term"],
            "target_entity": seen[norm("c. difficile infection")]["term"],
            "relationship_type": "enriched_in",
            "source_db": "kb_curated",
            "paper_count": 0,
            "papers": [],
            "is_cross_paper": False,
            "confidence": 0.95,
            "evidence": "curated: C. difficile is the causative agent of CDI",
        })
        added += 1

    # ciprofloxacin treats bacterial infections
    if norm("ciprofloxacin") in seen and norm("bacterial infections") in seen:
        relationships.append({
            "source_entity": seen[norm("ciprofloxacin")]["term"],
            "target_entity": seen[norm("bacterial infections")]["term"],
            "relationship_type": "treats",
            "source_db": "kb_curated",
            "paper_count": 0,
            "papers": [],
            "is_cross_paper": False,
            "confidence": 0.95,
            "evidence": "curated: ciprofloxacin is FDA-approved for bacterial infections",
        })
        added += 1

    # rifaximin treats hepatic encephalopathy
    if norm("rifaximin") in seen and norm("hepatic encephalopathy") in seen:
        relationships.append({
            "source_entity": seen[norm("rifaximin")]["term"],
            "target_entity": seen[norm("hepatic encephalopathy")]["term"],
            "relationship_type": "treats",
            "source_db": "kb_curated",
            "paper_count": 0,
            "papers": [],
            "is_cross_paper": False,
            "confidence": 0.95,
            "evidence": "curated: rifaximin is FDA-approved for hepatic encephalopathy (Bass 2010)",
        })
        added += 1

    # bifidobacterium depleted_in allergic disease
    if norm("bifidobacterium longum") in seen and norm("allergic disease") in seen:
        relationships.append({
            "source_entity": seen[norm("bifidobacterium longum")]["term"],
            "target_entity": seen[norm("allergic disease")]["term"],
            "relationship_type": "depleted_in",
            "source_db": "kb_curated",
            "paper_count": 0,
            "papers": [],
            "is_cross_paper": False,
            "confidence": 0.80,
            "evidence": "curated: B. longum is depleted in allergic disease (Björkstén 2001)",
        })
        added += 1
    return added


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm-dir", default=str(DEFAULT_LLM))
    ap.add_argument("--spacy-dir", default=str(DEFAULT_SPACY))
    ap.add_argument("--output", default=str(DEFAULT_OUT))
    ap.add_argument("--synonym-threshold", type=float, default=0.85)
    args = ap.parse_args()

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    print(f"LLM dir:   {args.llm_dir}")
    print(f"spaCy dir: {args.spacy_dir}")
    print(f"Output:    {out}\n")
    print(f"KB stats: {kb_stats()}\n")

    llm_triples, llm_by_paper = load_llm(Path(args.llm_dir))
    spacy_triples, spacy_by_paper = load_spacy(Path(args.spacy_dir))

    print(f"LLM triples:   {len(llm_triples)}")
    print(f"spaCy triples: {len(spacy_triples)}")

    # Build entity records (S1 = LLM, S2 = spaCy)
    entities = []
    seen: dict[str, dict] = {}

    def add_entity(term, etype, source, paper=None, **extra):
        k = norm(term)
        if k in seen:
            seen[k]["paper_count"] = seen[k].get("paper_count", 1) + 1
            seen[k]["sources"].add(source)
            if paper and paper not in seen[k].get("papers", []):
                seen[k].setdefault("papers", []).append(paper)
            return seen[k]
        rec = {
            "term": term,
            "term_norm": k,
            "type": (etype or "UNKNOWN").upper(),
            "source": source,
            "sources": {source},
            "paper_count": 1,
            "papers": [paper] if paper else [],
            **extra,
        }
        seen[k] = rec
        return rec

    for term, etype, conf, paper in llm_triples:
        add_entity(term, etype, "llm", paper, confidence=conf)
    for term, etype, paper in spacy_triples:
        add_entity(term, etype, "spacy", paper)

    print(f"Entities from LLM + spaCy: {len(seen)}")

    # S6: KB seed entities
    n_seed = add_kb_seed_entities(seen)
    print(f"Entities from KB seed:   +{n_seed}  (total: {len(seen)})")

    # Convert sets to lists for JSON
    for rec in seen.values():
        rec["sources"] = sorted(rec["sources"])

    entities = list(seen.values())
    print(f"Total entities: {len(entities)}\n")

    # S3: cross-paper co-occurrence
    by_paper = defaultdict(set)
    for paper, terms in llm_by_paper.items(): by_paper[paper].update(terms)
    for paper, terms in spacy_by_paper.items(): by_paper[paper].update(terms)
    seen_norms = set(seen.keys())

    relationships = []
    for paper, terms in by_paper.items():
        terms_in_seen = sorted(t for t in terms if t in seen_norms and seen[t]["type"] != "UNKNOWN")
        for i, a in enumerate(terms_in_seen):
            for b in terms_in_seen[i + 1: i + 6]:
                ea, eb = seen[a], seen[b]
                if ea["type"] == eb["type"]:
                    continue
                rel_type = CANONICAL_PAIRS.get((ea["type"], eb["type"]), "co_occurs_with")
                relationships.append({
                    "source_entity": ea["term"],
                    "target_entity": eb["term"],
                    "relationship_type": rel_type,
                    "source_db": "co_occurrence",
                    "paper_count": 1,
                    "papers": [paper],
                    "is_cross_paper": False,
                    "confidence": 0.5,
                    "evidence": f"both mentioned in {paper}",
                })

    # S4: type-canonical (with cap)
    by_type = defaultdict(list)
    for e in entities:
        if e["type"] != "UNKNOWN":
            by_type[e["type"]].append(e)
    for (ta, tb), rel in CANONICAL_PAIRS.items():
        if ta in by_type and tb in by_type:
            for ea in by_type[ta]:
                for eb in by_type[tb]:
                    if ea["term_norm"] == eb["term_norm"]:
                        continue
                    if len([r for r in relationships if r["source_db"] == "canonical_type_pair" and r["relationship_type"] == rel]) > 200:
                        break
                    relationships.append({
                        "source_entity": ea["term"],
                        "target_entity": eb["term"],
                        "relationship_type": rel,
                        "source_db": "canonical_type_pair",
                        "paper_count": 0,
                        "papers": list(set(ea.get("papers", []) + eb.get("papers", []))),
                        "is_cross_paper": len(set(ea.get("papers", []) + eb.get("papers", []))) >= 2,
                        "confidence": 0.3,
                        "evidence": f"type-pair canonical: {ta} ↔ {tb}",
                    })
                else:
                    continue
                break

    # S5: cross-source co-mention flag on entities
    for paper, llm_terms in llm_by_paper.items():
        sp_terms = spacy_by_paper.get(paper, set())
        common = llm_terms & sp_terms
        for t in common:
            e = seen.get(t)
            if e and len(e.get("sources", set())) >= 2:
                e["cross_source"] = True
    # Re-coerce sets after the in-place mutation
    for rec in seen.values():
        rec["sources"] = sorted(rec["sources"])
    entities = list(seen.values())

    # S6: KB-curated relationships
    n_kb_rels = add_kb_seed_relationships(seen, relationships)
    print(f"KB-curated relationships added: +{n_kb_rels}")

    # Dedupe
    dedup = {}
    for r in relationships:
        key = (norm(r["source_entity"]), norm(r["target_entity"]), r["relationship_type"])
        if key not in dedup:
            dedup[key] = dict(r)
        else:
            d = dedup[key]
            d["paper_count"] = d.get("paper_count", 0) + r.get("paper_count", 0)
            d["is_cross_paper"] = d["is_cross_paper"] or r.get("is_cross_paper", False)
            for p in r.get("papers", []):
                if p and p not in d.get("papers", []):
                    d.setdefault("papers", []).append(p)
    relationships = list(dedup.values())
    print(f"Total relationships: {len(relationships)}")

    # Source counts
    sources = {
        "S1_llm_entities":         sum(1 for e in entities if e.get("source") == "llm"),
        "S2_spacy_entities":       sum(1 for e in entities if e.get("source") == "spacy"),
        "S3_co_occurrence_edges":  sum(1 for r in relationships if r.get("source_db") == "co_occurrence"),
        "S4_type_canonical_edges": sum(1 for r in relationships if r.get("source_db") == "canonical_type_pair"),
        "S5_cross_source_entities": sum(1 for e in entities if e.get("cross_source")),
        "S6_kb_seed_entities":     sum(1 for e in entities if e.get("source") == "kb_seed"),
        "S7_kb_curated_edges":     sum(1 for r in relationships if r.get("source_db") == "kb_curated"),
    }
    print("Source counts:", json.dumps(sources, indent=2))

    # Persist
    (out / "entities.json").write_text(json.dumps(entities, indent=2), encoding="utf-8")
    (out / "relationships.json").write_text(json.dumps(relationships, indent=2), encoding="utf-8")
    (out / "sources.json").write_text(json.dumps(sources, indent=2), encoding="utf-8")
    print(f"\nWrote: {out}/entities.json  ({len(entities)} records)")
    print(f"Wrote: {out}/relationships.json  ({len(relationships)} records)")
    print(f"Wrote: {out}/sources.json")

    # Biological soundness check
    bio_report = biological_soundness_report(entities, relationships)
    (out / "biological_soundness.txt").write_text(bio_report, encoding="utf-8")
    print(f"\nWrote: {out}/biological_soundness.txt")

    # Headline
    print()
    print("=" * 70)
    print("MINI-HYBRID v2 (with biological KB layer)")
    print("=" * 70)
    print(f"  Entities: {len(entities)}")
    print(f"  Relationships: {len(relationships)}")
    print(f"  Sources: 7 (added S6 KB-seed + S7 KB-curated)")
    type_counts = Counter(e["type"] for e in entities)
    print(f"  Top entity types: {', '.join(f'{t}={c}' for t, c in type_counts.most_common(8))}")
    rel_counts = Counter(r["relationship_type"] for r in relationships)
    print(f"  Top rel types:    {', '.join(f'{t}={c}' for t, c in rel_counts.most_common(8))}")


def biological_soundness_report(entities, relationships) -> str:
    """Re-run the biological-recall check from the user's question, against the new KG."""
    by_norm = {e["term_norm"]: e for e in entities}
    lines = []
    lines.append("=" * 70)
    lines.append("BIOLOGICAL SOUNDNESS CHECK (v2 hybrid KG with KB layer)")
    lines.append("=" * 70)
    lines.append(f"Entities: {len(entities)}, Relationships: {len(relationships)}")
    lines.append("")

    WELL_KNOWN = {
        "Butyrate producers": [
            "faecalibacterium prausnitzii", "eubacterium rectale", "roseburia intestinalis",
            "roseburia hominis", "butyrivibrio fibrisolvens", "butyricicoccus pullicaecorum",
            "anaerostipes hadrus", "coprococcus catus", "eubacterium hallii",
        ],
        "IBD-depleted organisms": [
            "faecalibacterium prausnitzii", "akkermansia muciniphila",
            "bifidobacterium longum", "roseburia intestinalis", "eubacterium rectale",
        ],
        "IBD-enriched organisms": [
            "ruminococcus gnavus", "ruminococcus torques", "fusobacterium nucleatum",
            "enterobacteriaceae", "veillonella", "adherent invasive escherichia coli",
            "klebsiella pneumoniae",
        ],
        "Butyrate / SCFA chemicals": [
            "butyrate", "propionate", "acetate", "short-chain fatty acid",
            "lipopolysaccharide", "bile acid",
        ],
        "Crohn's disease drugs": [
            "infliximab", "adalimumab", "certolizumab pegol", "ustekinumab",
            "vedolizumab", "mesalamine", "sulfasalazine", "budesonide",
            "azathioprine", "6-mercaptopurine", "methotrexate",
        ],
        "UC drugs": [
            "infliximab", "adalimumab", "golimumab", "vedolizumab",
            "mesalamine", "sulfasalazine", "olsalazine", "balsalazide",
            "prednisone", "budesonide", "cyclosporine", "tacrolimus",
        ],
        "Gut-disrupting antibiotics": [
            "vancomycin", "ciprofloxacin", "metronidazole", "rifaximin",
            "clindamycin", "tetracycline", "doxycycline", "amoxicillin",
            "fidaxomicin",
        ],
        "Common gut diseases": [
            "inflammatory bowel disease", "crohn's disease", "ulcerative colitis",
            "irritable bowel syndrome", "type 2 diabetes mellitus",
            "obesity", "colorectal cancer", "c. difficile infection",
        ],
    }
    for category, terms in WELL_KNOWN.items():
        found = [t for t in terms if norm(t) in by_norm]
        cov = len(found) / len(terms) * 100
        type_note = ""
        if category in ("IBD-depleted organisms", "Butyrate producers", "IBD-enriched organisms",
                        "Common gut diseases"):
            type_note = "  (typed as "
            type_note += ", ".join(f"{by_norm[norm(t)]['term']}={by_norm[norm(t)]['type']}" for t in found)
            type_note += ")"
        lines.append(f"[{cov:5.1f}%] {category} ({len(found)}/{len(terms)}):")
        for f in found:
            e = by_norm[norm(f)]
            lines.append(f"   FOUND: {f}  type={e['type']}  source={e['source']}")
        for m in terms:
            if m not in found:
                lines.append(f"   MISS:  {m}")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
