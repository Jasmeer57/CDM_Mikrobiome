#!/usr/bin/env python
"""
Classify MeSH descriptors into structured categories for study-level metadata.

Categories:
  - age_groups: Adult, Child, Infant, Middle Aged, Aged, etc.
  - sex: Male, Female
  - study_design: Case-Control, Cohort, RCT, Longitudinal, etc.
  - population: Humans, Animals, Mice, Rats, etc.
  - sample_material: Feces, Saliva, Blood, Tissue, etc.
  - geography: Countries, Regions (e.g., Ghana, USA)
  - disease: HIV, IBD, Obesity, Colorectal Cancer, etc.
  - methods: DNA Sequencing, Sequence Analysis, Metagenomics, etc.
  - analysis: Statistics, Regression, Machine Learning, etc.

Usage:
  from cdm_pipeline.entrez.mesh_categorizer import categorize_mesh
  cats = categorize_mesh(mesh_terms)
"""

from typing import Dict, List, Set

# ---------------------------------------------------------------------------
# MeSH descriptor -> category mappings
# ---------------------------------------------------------------------------

AGE_GROUP_MSH = {
    "Adult", "Adolescent", "Child", "Child, Preschool", "Infant",
    "Infant, Newborn", "Middle Aged", "Aged", "Aged, 80 and over",
    "Young Adult", "Minor", "Postmenopause",
}

SEX_MSH = {
    "Male", "Female",
}

STUDY_DESIGN_MSH = {
    "Case-Control Studies", "Cohort Studies", "Cross-Sectional Studies",
    "Longitudinal Studies", "Randomized Controlled Trial",
    "Clinical Trial", "Clinical Trial, Phase II", "Clinical Trial, Phase III",
    "Clinical Trial, Phase IV", "Multicenter Study", "Observational Study",
    "Twin Study", "Comparative Study", "Validation Study", "Pilot Projects",
    "Meta-Analysis", "Systematic Review", "Pragmatic Clinical Trial",
    "Equivalence Trial", "Double-Bl Method", "Triple-Blind Procedure",
    "Placebos", "Feasibility Studies",
}

POPULATION_MSH = {
    "Humans", "Animals", "Mice", "Rats", "Rats, Sprague-Dawley",
    "Swine", "Cattle", "Fish", "Drosophila", "Zebrafish",
    "Caenorhabditis elegans", "Guinea Pigs", "Rabbits", "Dogs", "Cats",
    "Nonhuman Primates", "Chickens", "Sheep", "Horses",
    "Infant, Newborn", "Adult", "Child", "Adolescent",
    "Pregnant Women", "Postmenopausal",
}

SAMPLE_MATERIAL_MSH = {
    "Feces", "Saliva", "Blood", "Plasma", "Serum", "Urine",
    "Tissue, Adipose", "Tissue, Adipose White", "Dental Plaque",
    "Gastrointestinal Tract", "Intestinal Mucosa", "Colon",
    "Vaginal Smear", "Semen", "Breast Milk", "Milk, Human",
    "Meconium", "Amniotic Fluid", "Cerebrospinal Fluid",
    "Sputum", "Bronchoalveolar Lavage Fluid",
    "Biopsy", "Tissue", "Mucous Membrane",
    "Skin", "Buccal Mucosa", "Oral Cavity",
}

METHODS_MSH = {
    "RNA, Ribosomal, 16S", "RNA, Ribosomal, 18S", "RNA, Ribosomal, 23S",
    "DNA, Bacterial", "DNA, Ribosomal",
    "Sequence Analysis, DNA", "Sequence Analysis, RNA",
    "Metagenomics", "Metagenome", "Metabolomics",
    "Genome, Bacterial", "Genome, Human",
    "Genome-Wide Association Study", "High-Throughput Nucleotide Sequencing",
    "Polymerase Chain Reaction", "Reverse Transcriptase Polymerase Chain Reaction",
    "Microarray Analysis", "Flow Cytometry",
    "Mass Spectrometry", "Chromatography, Liquid",
    "Electrophoresis, Gel", "Blotting, Western",
    "Immunohistochemistry", "Immunofluorescence",
    "Bioinformatics", "Computational Biology",
    "DNA Extraction", "RNA Extraction",
}

ANALYSIS_MSH = {
    "Statistics", "Statistics as Topic", "Regression Analysis",
    "Principal Component Analysis", "Cluster Analysis",
    "Discriminant Analysis", "Bayesian Analysis",
    "Survival Analysis", "Kaplan-Meier Estimate",
    "Multivariate Analysis", "Sensitivity and Specificity",
    "ROC Curve", "Predictive Value of Tests",
    "Data Mining", "Machine Learning", "Artificial Intelligence",
    "Natural Language Processing",
}

# Disease MeSH — inferred from prefix patterns + known set
DISEASE_PREFIX_PATTERNS = {
    "D0": True,  # Many diseases start with D0
}

# Known disease MeSH descriptors commonly in microbiome papers
DISEASE_MSH_KNOWN = {
    "HIV Infections", "HIV-1", "HIV Seropositivity",
    "Inflammatory Bowel Disease", "Crohn Disease", "Ulcerative Colitis",
    "Colitis, Ulcerative", "Colorectal Neoplasms", "Colorectal Cancer",
    "Stomach Neoplasms", "Gastric Cancer", "Stomach Diseases",
    "Obesity", "Overweight", "Metabolic Syndrome",
    "Type 2 Diabetes Mellitus", "Diabetes Mellitus", "Diabetes Mellitus, Type 2",
    "Parkinson Disease", "Alzheimer Disease", "Multiple Sclerosis",
    "Autism Spectrum Disorder", "Autistic Disorder",
    "Rheumatoid Arthritis", "Lupus Erythematosus, Systemic",
    "Asthma", "Allergic", "Allergy and Immunology",
    "Depression", "Depressive Disorder", "Anxiety Disorders",
    "Schizophrenia",
    "Cardiovascular Diseases", "Atherosclerosis", "Hypertension",
    "Liver Cirrhosis", "Fatty Liver", "Non-alcoholic Fatty Liver Disease",
    "Celiac Disease", "Irritable Bowel Syndrome",
    "Diarrhea", "Diarrhea, Infantile",
    "Enterocolitis, Necrotizing", "Necrotizing Enterocolitis",
    "Gastroenteritis", "Colitis",
    "Dysbiosis", "Dysbiosis, Biological",
    "Malnutrition", "Stunting", "Wasting Syndrome",
    "Anorexia Nervosa", "Binge-Eating Disorder",
    "Sepsis", "Bacteremia", "Infection",
    "Cancers", "Neoplasms",
    "Lymphoma", "Leukemia",
    "Melanoma",
    "Osteoporosis", "Bone Diseases",
    "Chronic Fatigue Syndrome", "Myalgic Encephalomyelitis",
    "Gout", "Hyperuricemia",
    "Gallstones", "Cholelithiasis",
    "Chronic Kidney Disease", "Kidney Diseases",
}


# Geography MeSH — countries and regions
GEOGRAPHY_MSH_KNOWN = {
    "Africa", "Asia", "Europe", "North America", "South America", "Oceania",
    "Ghana", "Nigeria", "Kenya", "Uganda", "South Africa", "Tanzania",
    "Ethiopia", "Malawi", "Gambia", "Senegal", "Cameroon", "Zimbabwe",
    "China", "Japan", "India", "Korea", "South Korea", "Taiwan",
    "Thailand", "Vietnam", "Indonesia", "Malaysia", "Singapore",
    "Bangladesh", "Pakistan", "Philippines",
    "United States", "USA", "Canada", "Mexico", "Brazil", "Argentina",
    "Chile", "Peru", "Colombia", "Ecuador",
    "United Kingdom", "Ireland", "France", "Germany", "Netherlands",
    "Belgium", "Spain", "Italy", "Portugal", "Switzerland", "Austria",
    "Denmark", "Sweden", "Norway", "Finland", "Iceland",
    "Poland", "Czech Republic", "Hungary", "Romania", "Greece",
    "Russia", "Ukraine",
    "Australia", "New Zealand",
    "Israel", "Saudi Arabia", "Iran", "Turkey", "Egypt", "Morocco",
    "Middle East",
    "Geography", "Geographic Locations", "Developing Countries",
    " developed Countries",
    "United States", "United Kingdom", "European Union Countries",
    "Africa South of the Sahara", "Sub-Saharan Africa",
    "Scandinavia", "Baltic States",
    "Mongolia", "Nepal",
}


def categorize_mesh(mesh_terms: List[str]) -> Dict[str, List[str]]:
    """
    Classify a list of MeSH descriptor names into structured categories.

    Returns dict with keys: age_groups, sex, study_design, population,
    sample_material, methods, analysis, diseases, geography, other.
    """
    cats: Dict[str, List[str]] = {
        "age_groups": [],
        "sex": [],
        "study_design": [],
        "population": [],
        "sample_material": [],
        "methods": [],
        "analysis": [],
        "diseases": [],
        "geography": [],
        "other": [],
    }

    # Build lookup sets for O(1) matching
    age_set = AGE_GROUP_MSH
    sex_set = SEX_MSH
    design_set = STUDY_DESIGN_MSH
    pop_set = POPULATION_MSH - AGE_GROUP_MSH  # avoid dup with age
    material_set = SAMPLE_MATERIAL_MSH
    methods_set = METHODS_MSH
    analysis_set = ANALYSIS_MSH
    disease_set = DISEASE_MSH_KNOWN
    geo_set = GEOGRAPHY_MSH_KNOWN

    classified = set()

    for term in mesh_terms:
        if not term:
            continue
        t = term.strip()
        if t in classified:
            continue

        if t in age_set:
            cats["age_groups"].append(t)
            classified.add(t)
        elif t in sex_set:
            cats["sex"].append(t)
            classified.add(t)
        elif t in design_set:
            cats["study_design"].append(t)
            classified.add(t)
        elif t in pop_set:
            cats["population"].append(t)
            classified.add(t)
        elif t in material_set:
            cats["sample_material"].append(t)
            classified.add(t)
        elif t in methods_set:
            cats["methods"].append(t)
            classified.add(t)
        elif t in analysis_set:
            cats["analysis"].append(t)
            classified.add(t)
        elif t in disease_set:
            cats["diseases"].append(t)
            classified.add(t)
        elif t in geo_set:
            cats["geography"].append(t)
            classified.add(t)

    # Catch-all: any MeSH not classified yet
    for term in mesh_terms:
        if term and term not in classified:
            cats["other"].append(term)

    return cats


def categorize_mesh_headings(mesh_headings: List[dict]) -> Dict[str, List[dict]]:
    """
    Like categorize_mesh but preserves full MeSH heading detail
    (descriptor, UI, major_topic, qualifiers).
    """
    cats: Dict[str, List[dict]] = {
        "age_groups": [],
        "sex": [],
        "study_design": [],
        "population": [],
        "sample_material": [],
        "methods": [],
        "analysis": [],
        "diseases": [],
        "geography": [],
        "other": [],
    }

    for mh in mesh_headings:
        desc = mh.get("descriptor", "")
        if not desc:
            continue

        if desc in AGE_GROUP_MSH:
            cats["age_groups"].append(mh)
        elif desc in SEX_MSH:
            cats["sex"].append(mh)
        elif desc in STUDY_DESIGN_MSH:
            cats["study_design"].append(mh)
        elif desc in POPULATION_MSH:
            cats["population"].append(mh)
        elif desc in SAMPLE_MATERIAL_MSH:
            cats["sample_material"].append(mh)
        elif desc in METHODS_MSH:
            cats["methods"].append(mh)
        elif desc in ANALYSIS_MSH:
            cats["analysis"].append(mh)
        elif desc in DISEASE_MSH_KNOWN:
            cats["diseases"].append(mh)
        elif desc in GEOGRAPHY_MSH_KNOWN:
            cats["geography"].append(mh)
        else:
            cats["other"].append(mh)

    return cats
