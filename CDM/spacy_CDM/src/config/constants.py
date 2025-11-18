"""
Constants and configurations for the microbiome term extraction pipeline.
Preserves ALL features from the original reference scripts.
"""

from typing import List, Dict, Set

# =============================================================================
# SCIAPACY MODELS AND CONFIGURATION (from terms.py)
# =============================================================================

SCISPACY_MODELS = [
    "en_ner_craft_md",      # Best for genes, proteins, organisms
    "en_ner_bc5cdr_md",     # Best for diseases and chemicals
    "en_core_sci_md",       # General scientific model
    "en_ner_jnlpba_md",     # Additional biomedical entities
]

# High-quality embedding model for all semantic tasks
EMBEDDING_MODEL = 'all-MiniLM-L12-v2'

# -----------------------------------------------------------------------------
# P1 FIX: Conceptual Fragmentation - Synonymy and Normalization
# -----------------------------------------------------------------------------
SYNONYM_MAP = {
    "microbiota": "microbiome",
    "gut flora": "microbiome",
    "intestinal bacteria": "microbiome",
    "microbial community": "microbiome",
    "short-chain fatty acids": "scfa",
    "inflammatory bowel disease": "ibd",
    "crohn's disease": "ibd",
    "ulcerative colitis": "ibd",
    "irritable bowel syndrome": "ibs",
    "inflammatory bowel syndrome": "ibs",
    "short chain fatty acid": "scfa",
    "short chain fatty acids": "scfa",
    "gastrointestinal tract": "gi tract",
    "gastrointestinal": "gi",
    "gastro-intestinal": "gi",
    "antibiotic associated diarrhea": "aad",
    "antibiotic-associated diarrhea": "aad",
    "clostridium difficile": "c. difficile",
    "c diff": "c. difficile",
    "clostridioides difficile": "c. difficile",
    "fecal microbiota transplantation": "fmt",
    "fecal transplant": "fmt",
    "stool transplant": "fmt",
    "bacterial vaginosis": "bv",
    "vaginal microbiome": "vaginal flora",
    "vaginal microbiota": "vaginal flora",
    "oral microbiome": "oral flora",
    "oral microbiota": "oral flora",
    "skin microbiome": "skin flora",
    "skin microbiota": "skin flora",
    "lung microbiome": "lung flora",
    "lung microbiota": "lung flora",
    "respiratory microbiome": "respiratory flora",
    "respiratory microbiota": "respiratory flora"
}

# -----------------------------------------------------------------------------
# P3 FIX: Noise Blocklist - Expanded noise filtering
# -----------------------------------------------------------------------------
NOISE_BLOCKLIST = {
    # Generic academic and research terms
    "sequential", "clustering", "abundance", "composition", "analysis", "study",
    "studies", "research", "method", "methods", "approach", "result", "results",
    "finding", "findings", "conclusion", "discussion", "introduction", "background",
    "abstract", "methods", "figure", "table", "paper", "article", "review",
    "meta-analysis", "systematic review", "clinical trial", "randomized",
    "prospective", "retrospective", "cohort", "case-control", "cross-sectional",

    # Generic descriptive terms
    "changes", "change", "increase", "decrease", "effect", "effects", "impact",
    "impacts", "role", "function", "functions", "process", "processes", "mechanism",
    "mechanisms", "pathway", "pathways", "association", "associations", "correlation",
    "correlations", "relationship", "relationships", "interaction", "interactions",

    # People and demographics
    "subjects", "patients", "individuals", "people", "humans", "human", "adult",
    "adults", "elderly", "elder", "child", "children", "infant", "infants",
    "neonate", "neonates", "adolescent", "adolescents", "men", "women", "male",
    "female", "sex", "age", "ages", "years", "year", "old", "young", "newborn",
    "pediatric", "geriatric", "population", "populations", "group", "groups",
    "cohort", "cohorts", "sample", "samples",

    # Generic biological terms
    "bacteria", "bacterial", "organism", "organisms", "species", "genus", "genera",
    "family", "families", "order", "orders", "class", "classes", "phylum", "phyla",
    "kingdom", "domain", "taxa", "taxon", "cell", "cells", "tissue", "tissues",
    "organ", "organs", "system", "systems", "molecule", "molecules", "compound",
    "compounds", "chemical", "chemicals", "enzyme", "enzymes", "protein", "proteins",
    "gene", "genes", "dna", "rna", "genome", "genomes", "genetic", "molecular",
    "biological", "biochemical", "physiological", "pathological",

    # Sample and data terms
    "samples", "sample", "data", "dataset", "datasets", "sequence", "sequences",
    "sequencing", "gene", "genes", "genome", "genomes", "dna", "rna", "protein",
    "proteins", "enzyme", "enzymes", "database", "databases", "repository",
    "repositories", "record", "records", "file", "files", "document", "documents",

    # Statistical and mathematical terms
    "significant", "significance", "correlation", "correlations", "association",
    "associations", "frequency", "frequencies", "distribution", "distributions",
    "variation", "variations", "diversity", "diverse", "similar", "different",
    "difference", "statistical", "statistics", "p-value", "p-value", "confidence",
    "interval", "mean", "median", "mode", "standard deviation", "variance",
    "regression", "analysis of variance", "anova", "t-test", "chi-square", "test",
    "tests", "hypothesis", "hypotheses", "model", "models", "predictor",
    "predictors", "variable", "variables", "factor", "factors",

    # Location and institutional terms
    "japan", "japanese", "usa", "us", "america", "american", "china", "chinese",
    "korea", "korean", "europe", "european", "asia", "asian", "africa", "african",
    "university", "hospital", "clinic", "institute", "center", "laboratory", "lab",
    "department", "foundation", "country", "nation", "national", "international",
    "city", "cities", "state", "states", "region", "regions", "continent",
    "continents", "world", "global", "local", "regional",

    # Time terms
    "time", "times", "period", "periods", "duration", "phase", "phases", "stage",
    "stages", "point", "points", "moment", "moments", "second", "seconds", "minute",
    "minutes", "hour", "hours", "day", "days", "week", "weeks", "month", "months",
    "year", "years", "decade", "decades", "century", "centuries", "past", "present",
    "future", "history", "historical", "contemporary", "recent", "current", "previous",
    "early", "late", "initial", "final", "temporary", "permanent", "acute", "chronic",

    # Generic medical terms
    "disease", "disorders", "condition", "conditions", "syndrome", "syndromes",
    "infection", "infections", "inflammation", "treatment", "treatments", "therapy",
    "therapies", "drug", "drugs", "medication", "medications", "medicine", "medicines",
    "pharmaceutical", "pharmaceuticals", "prescription", "prescriptions", "dose",
    "dosage", "administration", "route", "side effect", "side effects", "adverse",
    "adverse event", "adverse events", "complication", "complications", "outcome",
    "outcomes", "prognosis", "diagnosis", "diagnoses", "diagnostic", "screening",
    "prevention", "preventive", "management", "care", "health", "healthcare",
    "medical", "clinical", "surgical", "non-surgical", "intervention", "interventions",
    "procedure", "procedures", "operation", "operations", "surgery",

    # Publication terms
    "article", "articles", "paper", "papers", "journal", "journals", "publication",
    "publications", "author", "authors", "reference", "references", "citation",
    "citations", "doi", "pmid", "pmcid", "pubmed", "medline", "embase", "scopus",
    "web of science", "google scholar", "literature", "review", "meta-analysis",
    "systematic review", "guideline", "guidelines", "consensus", "recommendation",
    "recommendations", "expert opinion", "editorial", "letter", "commentary",

    # Technical and methodological terms
    "technique", "techniques", "technology", "technologies", "methodology", "method",
    "protocol", "protocols", "procedure", "procedures", "assay", "assays", "test",
    "tests", "measurement", "measurements", "detection", "identification", "quantification",
    "characterization", "analysis", "analyses", "evaluation", "assessment", "validation",
    "verification", "calibration", "standardization", "normalization", "optimization",
    "quality control", "quality assurance", "reproducibility", "replication", "accuracy",
    "precision", "sensitivity", "specificity", "reliability", "validity",

    # Generic microbiome terms that need context
    "profile", "profiles", "signature", "signatures", "pattern", "patterns", "marker",
    "markers", "biomarker", "biomarkers", "indicator", "indicators", "factor", "factors",
    "element", "elements", "component", "components", "part", "parts", "aspect",
    "aspects", "feature", "features", "characteristic", "characteristics",
    "property", "properties", "attribute", "attributes", "parameter", "parameters",
    "variable", "variables", "metric", "metrics", "index", "indices", "score", "scores",
    "scale", "scales", "level", "levels", "degree", "degrees", "amount", "amounts",
    "quantity", "quantities", "number", "numbers", "count", "counts", "frequency",
    "frequencies", "prevalence", "incidence", "rate", "rates", "ratio", "ratios",
    "proportion", "proportions", "percentage", "percentages", "fraction", "fractions",

    # Generic terms about changes and effects
    "response", "responses", "reaction", "reactions", "activity", "activities",
    "behavior", "behaviors", "function", "functions", "dysfunction", "dysfunctions",
    "regulation", "regulations", "modulation", "modulations", "alteration",
    "alterations", "modification", "modifications", "adaptation", "adaptations",
    "adjustment", "adjustments", "compensation", "compensations", "homeostasis",
    "imbalance", "imbalances", "balance", "balanced", "unbalanced", "stability",
    "instability", "dynamic", "dynamics", "fluctuation", "fluctuations", "variation",
    "variations", "change", "changes", "shift", "shifts", "trend", "trends",
    "pattern", "patterns", "cycle", "cycles", "rhythm", "rhythms", "oscillation",
    "oscillations", "periodicity", "periodic", "seasonal", "temporal", "spatial",

    # Generic descriptive and qualitative terms
    "high", "low", "medium", "moderate", "severe", "mild", "intense", "weak", "strong",
    "significant", "insignificant", "substantial", "minimal", "major", "minor", "primary",
    "secondary", "principal", "main", "chief", "key", "critical", "crucial", "essential",
    "important", "relevant", "irrelevant", "notable", "remarkable", "unremarkable",
    "typical", "atypical", "normal", "abnormal", "regular", "irregular", "standard",
    "non-standard", "conventional", "unconventional", "traditional", "modern",
    "ancient", "recent", "old", "new", "novel", "innovative", "advanced", "basic",
    "fundamental", "complex", "simple", "complicated", "straightforward", "difficult",
    "easy", "hard", "possible", "impossible", "feasible", "infeasible", "practical",
    "theoretical", "experimental", "empirical", "hypothetical", "observed", "expected",
    "predicted", "estimated", "calculated", "measured", "assessed", "evaluated",
    "determined", "identified", "detected", "discovered", "found", "reported",
    "published", "unpublished", "known", "unknown", "recognized", "acknowledged",
    "established", "confirmed", "verified", "validated", "proven", "disproven",
    "accepted", "rejected", "controversial", "uncontroversial", "disputed", "undisputed",
    "certain", "uncertain", "definite", "indefinite", "clear", "unclear", "obvious",
    "hidden", "apparent", "real", "apparent", "actual", "potential", "possible"
}

# -----------------------------------------------------------------------------
# Microbiome Seeds for Semantic Relevance (moved from gold labels)
# -----------------------------------------------------------------------------
MICROBIOME_SEEDS = [
    # Core microbiome concepts
    "microbiome", "microbiota", "gut microbiota", "intestinal microbiota",
    "gut microbiome", "intestinal microbiome", "commensal bacteria",
    "gut flora", "intestinal flora", "microbial community", "bacterial community",
    "microbial ecosystem", "bacterial ecosystem", "commensal microorganisms",
    "symbiotic bacteria", "beneficial bacteria", "probiotic bacteria",

    # Major bacterial phyla and classes
    "bacteroidetes", "firmicutes", "actinobacteria", "proteobacteria",
    "verrucomicrobia", "cyanobacteria", "fusobacteria", "tenericutes",
    "spirochaetes", "thermotogae", "aquificae", "chlorobi", "chloroflexi",
    "deinococcus-thermus", "nitrospira", "planctomycetes", "venrucomicrobia",
    "acidobacteria", "gemmatimonadetes", "firmicut bacteri", "bacteroidia",
    "clostridia", "bacilli", "negativicutes", "erysipelotrichia", "gammaproteobacteria",
    "betaproteobacteria", "alphaproteobacteria", "deltaproteobacteria",
    "epsilonproteobacteria", "actinobacteria class", "coriobacteriia",
    "acidimicrobiia", "nitriliruptoria",

    # Important bacterial genera
    "bacteroides", "bifidobacterium", "lactobacillus", "clostridium",
    "escherichia", "eubacterium", "faecalibacterium", "roseburia",
    "akkermansia", "prevotella", "ruminococcus", "blautia", "streptococcus",
    "enterococcus", "staphylococcus", "enterobacter", "klebsiella", "pseudomonas",
    "salmonella", "shigella", "campylobacter", "helicobacter", "vibrio",
    "listeria", "bacillus", "mycobacterium", "corynebacterium", "propionibacterium",
    "actinomyces", "mobiluncus", "atopobium", "gardnerella", "veillonella",
    "methanobrevibacter", "sutterella", "dialister", "megamonas", "phascolarctobacter",
    "odoricbacter", "desulfovibrio", "bilophila", "alistipes", "oscillibacter",
    "coprococcus", "dorea", "lachnospira", "lachnoclostridium", "fusicatenibacter",
    "anaerostipes", "subdoligranulum", "christensenella", "collinsella",
    "eggerthella", "parabacteroides", "porphyromonas", "tannerella", "treponema",

    # Important bacterial species (complete list)
    "bacteroides fragilis", "bacteroides thetaiotaomicron", "bacteroides vulgatus",
    "bacteroides ovatus", "bacteroides uniformis", "bacteroides caccae",
    "bacteroides stercoris", "bacteroides eggerthii", "bifidobacterium longum",
    "bifidobacterium breve", "bifidobacterium adolescentis", "bifidobacterium bifidum",
    "bifidobacterium infantis", "bifidobacterium animalis", "lactobacillus acidophilus",
    "lactobacillus casei", "lactobacillus rhamnosus", "lactobacillus plantarum",
    "lactobacillus reuteri", "lactobacillus fermentum", "lactobacillus johnsonii",
    "lactobacillus gasseri", "lactobacillus salivarius", "lactobacillus bulgaricus",
    "clostridium difficile", "clostridium perfringens", "clostridium botulinum",
    "clostridium tetani", "clostridium septicum", "clostridium sordellii",
    "escherichia coli", "eubacterium rectale", "eubacterium hallii",
    "faecalibacterium prausnitzii", "roseburia hominis", "roseburia intestinalis",
    "akkermansia muciniphila", "prevotella copri", "prevotella melaninogenica",
    "ruminococcus bromii", "ruminococcus gnavus", "blautia obeum", "blautia producta",
    "streptococcus thermophilus", "streptococcus salivarius", "enterococcus faecalis",
    "enterococcus faecium", "staphylococcus aureus", "staphylococcus epidermidis",
    "enterobacter cloacae", "klebsiella pneumoniae", "pseudomonas aeruginosa",
    "salmonella enterica", "shigella sonnei", "campylobacter jejuni",
    "helicobacter pylori", "listeria monocytogenes", "bacillus subtilis",
    "mycobacterium tuberculosis", "mycobacterium avium", "corynebacterium diphtheriae",
    "propionibacterium acnes", "actinomyces israelii", "mobiluncus mulieris",
    "atopobium vaginae", "gardnerella vaginalis", "veillonella parvula",
    "methanobrevibacter smithii", "sutterella wadsworthensis", "dialister invisus",
    "megamonas hypermegale", "phascolarctobacter faecium", "odoricbacter splanchnicus",
    "desulfovibrio piger", "bilophila wadsworthia", "alistipes putredinis",
    "oscillibacter valericigenes", "coprococcus comes", "dorea formicigenerans",
    "lachnospira pectinoschiza", "lachnoclostridium phytofermentans",
    "fusicatenibacter saccharivorans", "anaerostipes hadrus", "subdoligranulum variabile",
    "christensenella minuta", "collinsella aerofaciens", "eggerthella lenta",
    "parabacteroides distasonis", "porphyromonas gingivalis", "tannerella forsythia",
    "treponema denticola",

    # Key metabolites and compounds
    "short-chain fatty acids", "scfa", "butyrate", "propionate", "acetate",
    "lactate", "succinate", "formate", "valerate", "isobutyrate", "isovalerate",
    "caproate", "caprylate", "bile acids", "tryptophan", "indole", "indolepropionic acid",
    "short chain fatty acids", "indole-3-acetic acid", "indole-3-aldehyde",
    "indole-3-propionic acid", "indole-3-acrylic acid", "tryptamine", "phenol",
    "p-cresol", "hydrogen sulfide", "methane", "ammonia", "polyamines",
    "putrescine", "cadaverine", "spermine", "spermidine", "vitamin k",
    "b vitamins", "vitamin b12", "folate", "riboflavin", "thiamine", "niacin",
    "vitamin b6", "biotin", "pantothenic acid", "lipopolysaccharide", "lps",
    "peptidoglycan", "lipoteichoic acid", "flagellin", "cps", "capsular polysaccharide",
    "exopolysaccharide", "eps", "siderophores", "bacteriocins", "organic acids",

    # Diseases and conditions
    "inflammatory bowel disease", "ibd", "crohn disease", "crohn's disease",
    "ulcerative colitis", "irritable bowel syndrome", "ibs", "antibiotic-associated diarrhea",
    "colitis", "enterocolitis", "necrotizing enterocolitis", "diverticulitis",
    "pouchitis", "microscopic colitis", "collagenous colitis", "lymphocytic colitis",
    "clostridium difficile infection", "cdi", "pseudomembranous colitis",
    "toxic megacolon", "small intestinal bacterial overgrowth", "sibo",
    "leaky gut", "intestinal permeability", "bacterial overgrowth", "dysbiosis",
    "symbiosis", "commensalism", "mutualism", "parasitism", "pathobiont",
    "opportunistic pathogen", "probiotic", "prebiotic", "synbiotic", "postbiotic",

    # Methods and techniques
    "16s rrna", "16s rrna sequencing", "metagenomics", "metagenomic sequencing",
    "metabolomics", "metatranscriptomics", "amplicon sequencing", "whole-genome sequencing",
    "shotgun metagenomics", "phylogenetic analysis", "microbiome analysis",
    "next-generation sequencing", "ngs", "high-throughput sequencing", "illumina sequencing",
    "ion torrent sequencing", "pacific biosciences sequencing", "oxford nanopore sequencing",
    "fluorescence in situ hybridization", "fish", "quantitative pcr", "qpcr",
    "digital pcr", "microarray", "mass spectrometry", "lc-ms", "gc-ms",
    "nuclear magnetic resonance", "nmr", "bioinformatics", "multivariate statistics",
    "principal component analysis", "pca", "principal coordinates analysis", "pcoa",
    "non-metric multidimensional scaling", "nmds", "cluster analysis", "hierarchical clustering",
    "k-means clustering", "diversity analysis", "alpha diversity", "beta diversity",
    "gamma diversity", "phylogenetic diversity", "taxonomic diversity", "functional diversity",
    "metabolic pathway analysis", "kegg pathway", "metacyc pathway", "biochemical pathway",

    # Diversity and ecological concepts
    "alpha diversity", "beta diversity", "shannon diversity", "simpson diversity",
    "species richness", "phylogenetic diversity", "microbial diversity", "operational taxonomic units",
    "otu", "otu clustering", "amplicon sequence variants", "asv", "exact sequence variants",
    "phylogenetic tree", "phylogeny", "taxonomic classification", "taxonomic assignment",
    "species identification", "strain typing", "genotyping", "phenotyping",
    "functional profiling", "taxonomic profiling", "metagenomic assembly", "binning",
    "contig binning", "metagenome-assembled genomes", "mag", "single-cell genomics",
    "culture-independent", "culture-dependent", "anaerobic culture", "facultative anaerobe",
    "obligate anaerobe", "aerobe", "microaerophile", "capnophile",

    # Other key terms
    "dysbiosis", "eubiosis", "symbiosis", "probiotic", "prebiotic", "synbiotic",
    "postbiotic", "pathobiont", "commensal", "mutualist", "parasite", "gut barrier",
    "intestinal barrier", "mucus layer", "biofilm", "gut-brain axis", "microbial metabolism",
    "bacterial metabolism", "fermentation", "symbiotic bacteria", "beneficial bacteria",
    "harmful bacteria", "opportunistic pathogens", "gut health", "intestinal health",
    "colon health", "rectal health", "digestive health", "gastrointestinal health",
    "immune system", "immune response", "inflammation", "anti-inflammatory", "pro-inflammatory",
    "immune modulation", "immune regulation", "tolerance", "immune tolerance",
    "mucosal immunity", "gut-associated lymphoid tissue", "galt", "immune homeostasis",
    "immune development", "immune maturation", "innate immunity", "adaptive immunity",
    "t cells", "b cells", "nk cells", "macrophages", "dendritic cells", "neutrophils",
    "cytokines", "chemokines", "antibodies", "immunoglobulins", "iga", "igg", "igm",
    "inflammatory cytokines", "anti-inflammatory cytokines", "th1 cells", "th2 cells",
    "th17 cells", "treg cells", "regulatory t cells", "immune homeostasis",

    # Clinical and therapeutic terms
    "probiotic therapy", "prebiotic therapy", "synbiotic therapy", "fecal microbiota transplantation",
    "fmt", "microbiome transplantation", "bacteriotherapy", "live biotherapeutic products",
    "lbp", "next-generation probiotics", "novel probiotics", "psychobiotics", "antibiotic stewardship",
    "antibiotic resistance", "antimicrobial resistance", "amr", "multi-drug resistance",
    "mdr", "extensively drug-resistant", "xdr", "pan-drug resistant", "pdr", "resistome",
    "antibiotic genes", "mobile genetic elements", "horizontal gene transfer", "conjugation",
    "transformation", "transduction", "plasmids", "integrons", "transposons", "phages",
    "bacteriophages", "viral metagenomics", "virome", "mycobiome", "fungi", "yeast",
    "mold", "archaea", "protists", "parasites", "helminths", "protozoa",

    # Environmental and lifestyle factors
    "diet", "nutrition", "fiber", "dietary fiber", "prebiotic fiber", "inulin",
    "fructooligosaccharides", "fos", "galactooligosaccharides", "gos", "xylooligosaccharides",
    "xos", "resistant starch", "fermentable carbohydrates", "fermentation substrates",
    "western diet", "mediterranean diet", "vegetarian diet", "vegan diet", "ketogenic diet",
    "high-fat diet", "high-protein diet", "low-carb diet", "low-fodmap diet", "elimination diet",
    "breastfeeding", "formula feeding", "birth mode", "vaginal delivery", "cesarean section",
    "c-section", "early life exposure", "childhood exposure", "antibiotic exposure",
    "probiotic supplementation", "prebiotic supplementation", "synbiotic supplementation",
    "functional foods", "nutraceuticals", "dietary supplements", "herbal supplements",
    "traditional medicine", "alternative medicine", "complementary medicine",

    # Technological and industrial applications
    "microbial ecology", "microbial biotechnology", "industrial microbiology",
    "food microbiology", "dairy microbiology", "probiotic industry", "functional foods",
    "fermented foods", "yogurt", "kefir", "kimchi", "sauerkraut", "kombucha", "tempeh",
    "miso", "natto", "cheese", "fermented milk", "fermented vegetables", "probiotic foods",
    "postbiotic foods", "synbiotic foods", "microbial therapeutics", "biotherapeutics",
    "microbial enzymes", "industrial enzymes", "biocatalysts", "bioremediation",
    "waste treatment", "sewage treatment", "wastewater treatment", "biogas production",
    "methane production", "biofuel production", "sustainable agriculture", "soil microbiome",
    "plant microbiome", "rhizosphere microbiome", "phyllosphere microbiome",
    "endophytic microbiome", "marine microbiome", "aquatic microbiome", "built environment microbiome",
    "indoor microbiome", "hospital microbiome", "built microbiome", "urban microbiome",

    # Advanced research concepts
    "microbiome engineering", "synthetic ecology", "designer microbiomes", "microbial consortia",
    "defined microbial communities", "synthetic microbial communities", "microbial community design",
    "precision microbiome", "personalized microbiome", "microbiome-based diagnostics",
    "microbiome biomarkers", "microbiome signatures", "microbiome-based therapeutics",
    "targeted antimicrobials", "precision antibiotics", "phage therapy", "bacteriophage therapy",
    "antimicrobial peptides", "bacteriocins", "quorum sensing inhibitors", "biofilm disruptors",
    "virulence factor inhibitors", "toxin neutralizers", "immune modulators",
    "microbiome vaccines", "microbiome-based vaccines", "live bacterial therapeutics",
    "engineered bacteria", "designer probiotics", "smart probiotics", "programmable probiotics",
    "synthetic biology", "metabolic engineering", "genome engineering", "crispr-based microbiome editing",
    "microbiome editing", "microbiome modulation", "microbiome manipulation",
    "microbiome restoration", "microbiome reconstitution", "microbiome transplantation",
    "microbiome engraftment", "microbiome colonization", "microbiome succession",
    "microbiome resilience", "microbiome stability", "microbiome robustness",
    "microbiome plasticity", "microbiome flexibility", "microbiome adaptability"
]

# =============================================================================
# UMLS CONFIGURATION (from umls.py)
# =============================================================================

BIOPORTAL_SEARCH_URL = "https://data.bioontology.org/search"
OLS_SEARCH_URL = "https://www.ebi.ac.uk/ols/api/search"
NCBO_ANNOTATOR_URL = "https://data.bioontology.org/annotator"

BIOPORTAL_ONTOLOGIES = [
    "GO", "CHEBI", "DOID", "NCBITAXON", "HP", "MP", "SNOMEDCT",
    "UBERON", "PO", "EFO", "ENVO", "MESH"
]

# =============================================================================
# OMOP CONFIGURATION (from convert.py and mapping.py)
# =============================================================================

DEFAULT_OMOP_DOMAINS = [
    'Condition', 'Drug', 'Procedure', 'Measurement',
    'Observation', 'Device', 'Spec Anatomic Site'
]

OMOP_REQUIRED_FILES = [
    'CONCEPT.csv',
    'CONCEPT_SYNONYM.csv',
    'CONCEPT_RELATIONSHIP.csv',
    'VOCABULARY.csv',
    'DOMAIN.csv'
]

# =============================================================================
# AI MODEL CONFIGURATION (from do.py)
# =============================================================================

MISTRAL_MODEL = 'mistralai/Mistral-7B-Instruct-v0.3'

# =============================================================================
# PROCESSING CONFIGURATION
# =============================================================================

DEFAULT_BATCH_SIZE = 32
DEFAULT_N_PROCESS = 4
DEFAULT_MIN_FREQUENCY = 2
DEFAULT_TOP_K = 2000
DEFAULT_FUZZY_THRESHOLD = 80
DEFAULT_SEMANTIC_THRESHOLD = 0.7