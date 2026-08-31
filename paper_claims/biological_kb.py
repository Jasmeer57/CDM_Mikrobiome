"""
Curated biological knowledge base for the Microbiome-CDM project.

Used by build_mini_hybrid_v2.py and claim_F_biological_validation/ as a
normalization + type-validation layer. Compiled from well-established
human microbiome literature; no external downloads required.

This is a "starting set" — the long-term plan is to auto-generate it from
NCBI Taxonomy (organisms), ChEBI (chemicals), DrugBank (drugs), DisGeNET
(disease-gene), HMDAD (microbe-disease), gutMGBrain (gut-brain axis).
Curated list here covers the most common human-microbiome entities so
the validation/recall checks can run on a 10-paper batch.

Designed to be GENERAL across the human microbiome — not IBD-specific.
Thematic areas covered (no single one dominates):
  1. Population / cohort biology
  2. Functional guilds (butyrate / mucin / propionate / lactate producers)
  3. Disease associations (IBD, T2D, obesity, CRC, CVD, neuropsych, liver, allergic, CDI)
  4. Pharmacology (broad antibiotics, anti-inflammatory, antidiabetic, lipid-lowering, probiotic)
  5. Microbial metabolites (SCFAs, bile acids, LPS, TMAO, vitamins, neurotransmitters)
  6. Cross-kingdom (fungi, archaea, eukaryotes, viruses)
  7. Methods (16S vs shotgun, alpha/beta diversity, common tools)
  8. Host factors (age, sex, diet, antibiotic exposure)
"""
from __future__ import annotations


# ----------------------------------------------------------------------------
# ORGANISMS — common human-associated microbes, with synonyms and disease
# associations. Organized by category to keep the file readable.
# ----------------------------------------------------------------------------
# Each entry: canonical_name -> {
#   "synonyms": [list of surface forms seen in papers],
#   "ncbi_taxon": NCBI Taxonomy ID (where known),
#   "type": "ORGANISM" (always, but explicit for clarity),
#   "produces": [chemicals the organism is known to produce],
#   "depleted_in": [diseases where this organism is reduced],
#   "enriched_in": [diseases where this organism is increased],
#   "category": functional group label
# }

ORGANISMS: dict[str, dict] = {
    # ============================================================
    # Functional guild: Butyrate producers
    # ============================================================
    "faecalibacterium prausnitzii": {
        "synonyms": ["F. prausnitzii", "F prausnitzii", "Faecalibacterium prausnitzii"],
        "ncbi_taxon": "853",
        "produces": ["butyrate", "butyric acid", "short-chain fatty acid"],
        "depleted_in": ["inflammatory bowel disease", "colorectal cancer", "obesity", "diabetes mellitus type 2"],
        "category": "butyrate_producer",
    },
    "eubacterium rectale": {
        "synonyms": ["E. rectale", "Eubacterium rectale", "Agathobacter rectalis"],
        "ncbi_taxon": "39491",
        "produces": ["butyrate"],
        "category": "butyrate_producer",
    },
    "eubacterium hallii": {
        "synonyms": ["E. hallii", "Eubacterium hallii", "Anaerobutyricum hallii"],
        "ncbi_taxon": "39488",
        "produces": ["butyrate", "propionate"],
        "category": "butyrate_producer",
    },
    "roseburia intestinalis": {
        "synonyms": ["R. intestinalis", "Roseburia intestinalis", "Roseburia"],
        "ncbi_taxon": "166486",
        "produces": ["butyrate"],
        "category": "butyrate_producer",
    },
    "roseburia hominis": {
        "synonyms": ["R. hominis", "Roseburia hominis"],
        "ncbi_taxon": "585393",
        "produces": ["butyrate"],
        "category": "butyrate_producer",
    },
    "butyrivibrio fibrisolvens": {
        "synonyms": ["Butyrivibrio fibrisolvens", "Butyrivibrio"],
        "produces": ["butyrate"],
        "category": "butyrate_producer",
    },
    "butyricicoccus pullicaecorum": {
        "synonyms": ["Butyricicoccus pullicaecorum", "Butyricicoccus"],
        "produces": ["butyrate"],
        "category": "butyrate_producer",
    },
    "anaerostipes hadrus": {
        "synonyms": ["A. hadrus", "Anaerostipes hadrus", "Anaerostipes"],
        "produces": ["butyrate"],
        "category": "butyrate_producer",
    },
    "coprococcus catus": {
        "synonyms": ["C. catus", "Coprococcus catus", "Coprococcus"],
        "produces": ["butyrate"],
        "category": "butyrate_producer",
    },
    "coprococcus eutactus": {
        "synonyms": ["C. eutactus", "Coprococcus eutactus"],
        "produces": ["butyrate"],
        "category": "butyrate_producer",
    },

    # ============================================================
    # Functional guild: Mucin degraders
    # ============================================================
    "akkermansia muciniphila": {
        "synonyms": ["A. muciniphila", "Akkermansia muciniphila", "Akkermansia"],
        "ncbi_taxon": "239935",
        "depleted_in": ["obesity", "type 2 diabetes mellitus", "inflammatory bowel disease"],
        "category": "mucin_degrader",
    },

    # ============================================================
    # Functional guild: Propionate producers
    # ============================================================
    "bacteroides thetaiotaomicron": {
        "synonyms": ["B. thetaiotaomicron", "Bacteroides thetaiotaomicron"],
        "ncbi_taxon": "818",
        "produces": ["propionate"],
        "category": "propionate_producer",
    },
    "prevotella copri": {
        "synonyms": ["P. copri", "Prevotella copri"],
        "ncbi_taxon": "165179",
        "produces": ["propionate"],
        "category": "propionate_producer",
    },
    "veillonella parvula": {
        "synonyms": ["V. parvula", "Veillonella parvula"],
        "produces": ["propionate"],
        "category": "propionate_producer",
    },

    # ============================================================
    # Common commensals (Bifidobacterium, Lactobacillus, Bacteroides)
    # ============================================================
    "bifidobacterium longum": {
        "synonyms": ["B. longum", "Bifidobacterium longum", "Bifidobacterium"],
        "ncbi_taxon": "216816",
        "produces": ["short-chain fatty acid", "acetate"],
        "depleted_in": ["inflammatory bowel disease", "allergic disease"],
        "category": "commensal",
    },
    "bifidobacterium breve": {
        "synonyms": ["B. breve", "Bifidobacterium breve"],
        "ncbi_taxon": "1685",
        "category": "commensal",
    },
    "bifidobacterium adolescentis": {
        "synonyms": ["B. adolescentis", "Bifidobacterium adolescentis"],
        "ncbi_taxon": "1680",
        "category": "commensal",
    },
    "bifidobacterium infantis": {
        "synonyms": ["B. infantis", "Bifidobacterium infantis"],
        "category": "commensal",
    },
    "lactobacillus rhamnosus": {
        "synonyms": ["L. rhamnosus", "Lactobacillus rhamnosus", "LGG", "Lactobacillus rhamnosus GG"],
        "ncbi_taxon": "47715",
        "category": "probiotic",
    },
    "lactobacillus acidophilus": {
        "synonyms": ["L. acidophilus", "Lactobacillus acidophilus"],
        "ncbi_taxon": "1579",
        "category": "probiotic",
    },
    "lactobacillus plantarum": {
        "synonyms": ["L. plantarum", "Lactobacillus plantarum"],
        "ncbi_taxon": "1590",
        "category": "probiotic",
    },
    "lactobacillus casei": {
        "synonyms": ["L. casei", "Lactobacillus casei"],
        "category": "probiotic",
    },
    "lactobacillus reuteri": {
        "synonyms": ["L. reuteri", "Lactobacillus reuteri"],
        "category": "probiotic",
    },
    "bacteroides fragilis": {
        "synonyms": ["B. fragilis", "Bacteroides fragilis", "Bacteroides"],
        "ncbi_taxon": "817",
        "produces": ["polysaccharide a"],
        "category": "commensal",
    },
    "bacteroides ovatus": {
        "synonyms": ["B. ovatus", "Bacteroides ovatus"],
        "category": "commensal",
    },
    "bacteroides uniformis": {
        "synonyms": ["B. uniformis", "Bacteroides uniformis"],
        "category": "commensal",
    },
    "phocaeicola vulgatus": {
        "synonyms": ["P. vulgatus", "Phocaeicola vulgatus", "Bacteroides vulgatus"],
        "category": "commensal",
    },

    # ============================================================
    # Pathobionts (enriched in disease)
    # ============================================================
    "ruminococcus gnavus": {
        "synonyms": ["R. gnavus", "Ruminococcus gnavus", "Ruminococcus"],
        "ncbi_taxon": "33038",
        "enriched_in": ["inflammatory bowel disease", "atherosclerosis"],
        "category": "pathobiont",
    },
    "ruminococcus torques": {
        "synonyms": ["R. torques", "Ruminococcus torques"],
        "enriched_in": ["inflammatory bowel disease"],
        "category": "pathobiont",
    },
    "fusobacterium nucleatum": {
        "synonyms": ["F. nucleatum", "Fusobacterium nucleatum", "Fusobacterium"],
        "ncbi_taxon": "851",
        "enriched_in": ["colorectal cancer"],
        "category": "pathobiont",
    },
    "enterobacteriaceae": {
        "synonyms": ["Enterobacteriaceae", "Enterobacteriaceae family"],
        "enriched_in": ["inflammatory bowel disease", "colorectal cancer"],
        "category": "pathobiont_family",
    },
    "adherent invasive escherichia coli": {
        "synonyms": ["AIEC", "adherent-invasive E. coli", "adherent invasive e coli",
                    "adherent-invasive Escherichia coli"],
        "ncbi_taxon": "562",
        "enriched_in": ["crohn's disease"],
        "category": "pathobiont",
    },
    "veillonella": {
        "synonyms": ["Veillonella", "Veillonella atypica", "Veillonella parvula"],
        "enriched_in": ["inflammatory bowel disease"],
        "category": "pathobiont",
    },
    "klebsiella pneumoniae": {
        "synonyms": ["K. pneumoniae", "Klebsiella pneumoniae", "Klebsiella"],
        "ncbi_taxon": "573",
        "enriched_in": ["inflammatory bowel disease", "liver disease"],
        "category": "pathobiont",
    },
    "proteus mirabilis": {
        "synonyms": ["P. mirabilis", "Proteus mirabilis"],
        "category": "pathobiont",
    },
    "helicobacter pylori": {
        "synonyms": ["H. pylori", "Helicobacter pylori", "Helicobacter"],
        "ncbi_taxon": "210",
        "enriched_in": ["gastric cancer", "peptic ulcer"],
        "category": "pathobiont",
    },
    "clostridioides difficile": {
        "synonyms": ["C. difficile", "Clostridioides difficile", "Clostridium difficile", "C diff"],
        "ncbi_taxon": "1496",
        "enriched_in": ["c. difficile infection"],
        "category": "pathobiont",
    },

    # ============================================================
    # Cross-kingdom: Fungi, Archaea, Eukaryotes
    # ============================================================
    "candida albicans": {
        "synonyms": ["C. albicans", "Candida albicans", "Candida"],
        "ncbi_taxon": "5476",
        "enriched_in": ["inflammatory bowel disease", "antibiotic-associated diarrhea"],
        "category": "fungus",
    },
    "saccharomyces cerevisiae": {
        "synonyms": ["S. cerevisiae", "Saccharomyces cerevisiae", "baker's yeast"],
        "ncbi_taxon": "4932",
        "category": "fungus",
    },
    "saccharomyces boulardii": {
        "synonyms": ["S. boulardii", "Saccharomyces boulardii"],
        "category": "probiotic_fungus",
    },
    "methanobrevibacter smithii": {
        "synonyms": ["M. smithii", "Methanobrevibacter smithii"],
        "ncbi_taxon": "2173",
        "category": "archaeon",
    },
    "blastocystis": {
        "synonyms": ["Blastocystis", "Blastocystis hominis"],
        "ncbi_taxon": "94468",
        "category": "eukaryote_parasite",
    },

    # ============================================================
    # Major phyla/genera (commonly detected)
    # ============================================================
    "firmicutes": {"synonyms": ["Firmicutes", "Firmicutes phylum"], "category": "phylum"},
    "bacteroidetes": {"synonyms": ["Bacteroidetes", "Bacteroidetes phylum"], "category": "phylum"},
    "actinobacteria": {"synonyms": ["Actinobacteria"], "category": "phylum"},
    "verrucomicrobia": {"synonyms": ["Verrucomicrobia"], "category": "phylum"},
    "proteobacteria": {"synonyms": ["Proteobacteria"], "category": "phylum"},
    "prevotella": {"synonyms": ["Prevotella", "Prevotella copri"], "ncbi_taxon": "165179", "category": "genus"},
    "ruminococcus": {"synonyms": ["Ruminococcus"], "category": "genus"},
    "lactobacillus": {"synonyms": ["Lactobacillus"], "category": "genus"},
    "bifidobacterium": {"synonyms": ["Bifidobacterium"], "category": "genus"},
    "bacteroides": {"synonyms": ["Bacteroides"], "category": "genus"},
    "streptococcus": {"synonyms": ["Streptococcus"], "category": "genus"},
    "staphylococcus": {"synonyms": ["Staphylococcus"], "category": "genus"},
    "escherichia coli": {
        "synonyms": ["E. coli", "Escherichia coli", "E.coli"],
        "ncbi_taxon": "562",
        "category": "commensal_and_pathobiont",
    },
    "enterococcus": {"synonyms": ["Enterococcus", "Enterococcus faecalis", "Enterococcus faecium"],
                     "category": "genus"},
    "alistipes": {"synonyms": ["Alistipes", "Alistipes putredinis", "Alistipes onderdonkii"],
                  "category": "genus"},
    "parabacteroides": {"synonyms": ["Parabacteroides", "Parabacteroides distasonis"],
                        "category": "genus"},
    "sutterella": {"synonyms": ["Sutterella", "Sutterella wadsworthensis"], "category": "genus"},
    "megamonas": {"synonyms": ["Megamonas", "Megamonas funiformis"], "category": "genus"},
    "dialister": {"synonyms": ["Dialister", "Dialister invisus"], "category": "genus"},
    "gemma": {"synonyms": ["Gemmiger", "Gemmiger formicilis"], "category": "genus"},
    "roseburia": {"synonyms": ["Roseburia"], "category": "genus"},
    "blautia": {"synonyms": ["Blautia", "Blautia obeum", "Blautia wexlerae"], "category": "genus"},
    "dorea": {"synonyms": ["Dorea", "Dorea longicatena", "Dorea formicigenerans"], "category": "genus"},
    "subdoligranulum": {"synonyms": ["Subdoligranulum", "Subdoligranulum variabile"], "category": "genus"},
    "intestinimonas": {"synonyms": ["Intestinimonas", "Intestinimonas butyriciproducens"],
                       "category": "genus"},
    "faecalibacterium": {"synonyms": ["Faecalibacterium"], "category": "genus"},
    "roseburia intestinalis": {"synonyms": ["R. intestinalis", "Roseburia intestinalis", "Roseburia"],
                              "ncbi_taxon": "166486", "category": "butyrate_producer"},
}


# ----------------------------------------------------------------------------
# DRUGS / CHEMICALS — broad coverage: antibiotics, anti-inflammatory,
# antidiabetic, lipid-lowering, antipsychotic, probiotic, plus the core
# microbiome metabolites (SCFAs, bile acids, LPS, TMAO, vitamins).
# ----------------------------------------------------------------------------

DRUGS: dict[str, dict] = {
    # ===== Antibiotics (broad) =====
    "vancomycin": {"synonyms": ["vancomycin", "Vancocin"],
                   "treats": ["clostridioides difficile infection", "mrsa infection"],
                   "disrupts": ["gut microbiome"],
                   "drug_class": "antibiotic_glycopeptide"},
    "ciprofloxacin": {"synonyms": ["ciprofloxacin", "Cipro", "cipro"],
                      "treats": ["bacterial infections"],
                      "disrupts": ["gut microbiome"],
                      "drug_class": "antibiotic_fluoroquinolone"},
    "metronidazole": {"synonyms": ["metronidazole", "Flagyl", "metro"],
                      "treats": ["anaerobic infections", "c. difficile infection", "trichomoniasis"],
                      "disrupts": ["gut microbiome"],
                      "drug_class": "antibiotic_nitroimidazole"},
    "rifaximin": {"synonyms": ["rifaximin", "Xifaxan"],
                  "treats": ["hepatic encephalopathy", "irritable bowel syndrome"],
                  "disrupts": ["gut microbiome (modestly)"],
                  "drug_class": "antibiotic_rifamycin"},
    "clindamycin": {"synonyms": ["clindamycin", "Cleocin"],
                    "treats": ["anaerobic infections"],
                    "disrupts": ["gut microbiome"],
                    "drug_class": "antibiotic_lincosamide"},
    "tetracycline": {"synonyms": ["tetracycline", "Sumycin"],
                     "treats": ["bacterial infections", "acne"],
                     "disrupts": ["gut microbiome"],
                     "drug_class": "antibiotic_tetracycline"},
    "doxycycline": {"synonyms": ["doxycycline", "Doryx", "Vibramycin"],
                    "treats": ["bacterial infections", "malaria", "lyme disease"],
                    "disrupts": ["gut microbiome"],
                    "drug_class": "antibiotic_tetracycline"},
    "amoxicillin": {"synonyms": ["amoxicillin", "Amoxil"],
                    "treats": ["bacterial infections"],
                    "disrupts": ["gut microbiome"],
                    "drug_class": "antibiotic_penicillin"},
    "ampicillin": {"synonyms": ["ampicillin"],
                   "treats": ["bacterial infections"],
                   "disrupts": ["gut microbiome"],
                   "drug_class": "antibiotic_penicillin"},
    "neomycin": {"synonyms": ["neomycin"],
                 "treats": ["bacterial infections"],
                 "disrupts": ["gut microbiome"],
                 "drug_class": "antibiotic_aminoglycoside"},
    "gentamicin": {"synonyms": ["gentamicin", "Garamycin"],
                   "treats": ["bacterial infections"],
                   "disrupts": ["gut microbiome"],
                   "drug_class": "antibiotic_aminoglycoside"},
    "fidaxomicin": {"synonyms": ["fidaxomicin", "Dificid"],
                    "treats": ["c. difficile infection"],
                    "disrupts": ["gut microbiome (selectively)"],
                    "drug_class": "antibiotic_macrolide"},
    "azithromycin": {"synonyms": ["azithromycin", "Zithromax", "Z-Pak"],
                      "treats": ["bacterial infections"],
                      "disrupts": ["gut microbiome"],
                      "drug_class": "antibiotic_macrolide"},
    "cephalexin": {"synonyms": ["cephalexin", "Keflex"],
                   "treats": ["bacterial infections"],
                   "disrupts": ["gut microbiome"],
                   "drug_class": "antibiotic_cephalosporin"},
    "levofloxacin": {"synonyms": ["levofloxacin", "Levaquin"],
                     "treats": ["bacterial infections"],
                     "disrupts": ["gut microbiome"],
                     "drug_class": "antibiotic_fluoroquinolone"},

    # ===== Anti-inflammatory (general, not just IBD) =====
    "aspirin": {"synonyms": ["aspirin", "acetylsalicylic acid", "ASA"],
                "treats": ["pain", "cardiovascular disease", "fever"],
                "drug_class": "nsaid"},
    "ibuprofen": {"synonyms": ["ibuprofen", "Advil", "Motrin"],
                  "treats": ["pain", "fever", "inflammation"],
                  "disrupts": ["gut microbiome (modestly)"],
                  "drug_class": "nsaid"},
    "naproxen": {"synonyms": ["naproxen", "Aleve"],
                 "treats": ["pain", "inflammation"],
                 "drug_class": "nsaid"},
    "celecoxib": {"synonyms": ["celecoxib", "Celebrex"],
                  "treats": ["pain", "inflammation"],
                  "drug_class": "nsaid_cox2"},
    "prednisone": {"synonyms": ["prednisone", "Deltasone"],
                   "treats": ["inflammation", "autoimmune disease"],
                   "drug_class": "corticosteroid"},
    "prednisolone": {"synonyms": ["prednisolone", "Prelone"],
                     "treats": ["inflammation", "autoimmune disease"],
                     "drug_class": "corticosteroid"},
    "methylprednisolone": {"synonyms": ["methylprednisolone", "Medrol", "Solu-Medrol"],
                            "treats": ["inflammation", "autoimmune disease"],
                            "drug_class": "corticosteroid"},
    "budesonide": {"synonyms": ["budesonide", "Entocort", "Pulmicort"],
                   "treats": ["inflammation", "asthma", "inflammatory bowel disease"],
                   "drug_class": "corticosteroid"},

    # ===== IBD-specific treatments (kept for breadth) =====
    "infliximab": {"synonyms": ["infliximab", "Remicade", "IFX"],
                   "treats": ["crohn's disease", "ulcerative colitis", "rheumatoid arthritis"],
                   "drug_class": "anti-TNF"},
    "adalimumab": {"synonyms": ["adalimumab", "Humira", "ADA"],
                   "treats": ["crohn's disease", "ulcerative colitis", "rheumatoid arthritis", "psoriasis"],
                   "drug_class": "anti-TNF"},
    "ustekinumab": {"synonyms": ["ustekinumab", "Stelara"],
                    "treats": ["crohn's disease", "ulcerative colitis", "psoriasis"],
                    "drug_class": "anti-IL12/23"},
    "vedolizumab": {"synonyms": ["vedolizumab", "Entyvio"],
                    "treats": ["crohn's disease", "ulcerative colitis"],
                    "drug_class": "anti-integrin"},
    "mesalamine": {"synonyms": ["mesalamine", "mesalazine", "5-ASA", "5-aminosalicylic acid",
                                "5 aminosalicylic acid", "Pentasa", "Asacol"],
                   "treats": ["ulcerative colitis", "crohn's disease"],
                   "drug_class": "5-ASA"},
    "sulfasalazine": {"synonyms": ["sulfasalazine", "Azulfidine", "salazosulfapyridine"],
                      "treats": ["ulcerative colitis", "rheumatoid arthritis"],
                      "drug_class": "5-ASA"},
    "azathioprine": {"synonyms": ["azathioprine", "AZA", "Imuran"],
                     "treats": ["crohn's disease", "ulcerative colitis", "autoimmune hepatitis"],
                     "drug_class": "immunomodulator"},
    "6-mercaptopurine": {"synonyms": ["6-mercaptopurine", "6-MP", "6MP", "mercaptopurine", "Purinethol"],
                          "treats": ["crohn's disease", "ulcerative colitis", "leukemia"],
                          "drug_class": "immunomodulator"},
    "methotrexate": {"synonyms": ["methotrexate", "MTX", "Rheumatrex", "Trexall"],
                     "treats": ["crohn's disease", "rheumatoid arthritis", "psoriasis"],
                     "drug_class": "immunomodulator"},

    # ===== Antidiabetic =====
    "metformin": {"synonyms": ["metformin", "Glucophage", "Fortamet"],
                  "treats": ["type 2 diabetes mellitus"],
                  "drug_class": "antidiabetic_biguanide"},
    "glipizide": {"synonyms": ["glipizide", "Glucotrol"],
                  "treats": ["type 2 diabetes mellitus"],
                  "drug_class": "antidiabetic_sulfonylurea"},
    "sitagliptin": {"synonyms": ["sitagliptin", "Januvia"],
                    "treats": ["type 2 diabetes mellitus"],
                    "drug_class": "antidiabetic_dpp4"},
    "empagliflozin": {"synonyms": ["empagliflozin", "Jardiance"],
                      "treats": ["type 2 diabetes mellitus", "cardiovascular disease"],
                      "drug_class": "antidiabetic_sglt2"},
    "liraglutide": {"synonyms": ["liraglutide", "Victoza", "Saxenda"],
                    "treats": ["type 2 diabetes mellitus", "obesity"],
                    "drug_class": "antidiabetic_glp1"},
    "semaglutide": {"synonyms": ["semaglutide", "Ozempic", "Wegovy"],
                    "treats": ["type 2 diabetes mellitus", "obesity"],
                    "drug_class": "antidiabetic_glp1"},

    # ===== Lipid-lowering =====
    "atorvastatin": {"synonyms": ["atorvastatin", "Lipitor"],
                     "treats": ["hypercholesterolemia", "cardiovascular disease"],
                     "drug_class": "statin"},
    "simvastatin": {"synonyms": ["simvastatin", "Zocor"],
                    "treats": ["hypercholesterolemia", "cardiovascular disease"],
                    "drug_class": "statin"},
    "rosuvastatin": {"synonyms": ["rosuvastatin", "Crestor"],
                     "treats": ["hypercholesterolemia", "cardiovascular disease"],
                     "drug_class": "statin"},

    # ===== Antihypertensive =====
    "lisinopril": {"synonyms": ["lisinopril", "Prinivil", "Zestril"],
                   "treats": ["hypertension", "cardiovascular disease"],
                   "drug_class": "ace_inhibitor"},
    "losartan": {"synonyms": ["losartan", "Cozaar"],
                 "treats": ["hypertension"],
                 "drug_class": "arb"},
    "amlodipine": {"synonyms": ["amlodipine", "Norvasc"],
                   "treats": ["hypertension"],
                   "drug_class": "calcium_channel_blocker"},
    "metoprolol": {"synonyms": ["metoprolol", "Lopressor", "Toprol"],
                   "treats": ["hypertension", "cardiovascular disease"],
                   "drug_class": "beta_blocker"},

    # ===== Antipsychotic / Neuropsychiatric =====
    "risperidone": {"synonyms": ["risperidone", "Risperdal"],
                    "treats": ["schizophrenia", "bipolar disorder"],
                    "drug_class": "antipsychotic_atypical"},
    "olanzapine": {"synonyms": ["olanzapine", "Zyprexa"],
                   "treats": ["schizophrenia", "bipolar disorder"],
                   "drug_class": "antipsychotic_atypical"},
    "fluoxetine": {"synonyms": ["fluoxetine", "Prozac"],
                   "treats": ["depression", "anxiety"],
                   "drug_class": "ssri"},
    "sertraline": {"synonyms": ["sertraline", "Zoloft"],
                   "treats": ["depression", "anxiety"],
                   "drug_class": "ssri"},

    # ===== Microbiome metabolites =====
    "butyrate": {"synonyms": ["butyrate", "butyric acid", "butanoate", "butanoic acid"],
                 "category": "scfa", "treats": ["inflammation"]},
    "propionate": {"synonyms": ["propionate", "propionic acid", "propanoate"],
                   "category": "scfa", "treats": ["inflammation", "colorectal cancer"]},
    "acetate": {"synonyms": ["acetate", "acetic acid", "ethanoate"],
                "category": "scfa", "treats": ["inflammation"]},
    "short-chain fatty acid": {
        "synonyms": ["short-chain fatty acid", "short chain fatty acid", "SCFA", "SCFAs",
                    "short-chain fatty acids"],
        "category": "scfa_class",
        "treats": ["inflammation"],
    },
    "lipopolysaccharide": {
        "synonyms": ["lipopolysaccharide", "LPS", "endotoxin"],
        "category": "microbial_product",
        "associated_with": ["inflammation"],
    },
    "polysaccharide a": {
        "synonyms": ["polysaccharide a", "PSA"],
        "category": "microbial_product",
    },
    "trimethylamine n-oxide": {
        "synonyms": ["trimethylamine n-oxide", "trimethylamine N-oxide", "TMAO"],
        "category": "microbial_metabolite",
        "associated_with": ["atherosclerosis", "cardiovascular disease"],
    },
    "bile acid": {"synonyms": ["bile acid", "bile acids", "bile salt", "bile salts"],
                  "category": "host_metabolite"},
    "indole": {"synonyms": ["indole"], "category": "microbial_metabolite"},
    "tryptophan": {"synonyms": ["tryptophan", "L-tryptophan"], "category": "amino_acid"},
    "lactate": {"synonyms": ["lactate", "lactic acid"], "category": "carbohydrate"},
    "gamma-aminobutyric acid": {
        "synonyms": ["gamma-aminobutyric acid", "GABA"],
        "category": "neurotransmitter",
        "produced_by": ["Lactobacillus", "Bifidobacterium", "Enterococcus"],
    },
    "serotonin": {
        "synonyms": ["serotonin", "5-HT", "5-hydroxytryptamine"],
        "category": "neurotransmitter",
        "produced_by": ["Enterococcus", "Streptococcus"],
    },
    "vitamin B12": {
        "synonyms": ["vitamin B12", "cobalamin", "B12"],
        "category": "vitamin",
        "produced_by": ["Bacteroides", "Faecalibacterium"],
    },
    "vitamin K": {
        "synonyms": ["vitamin K", "phylloquinone", "K2", "menaquinone"],
        "category": "vitamin",
        "produced_by": ["Bacteroides"],
    },
}


# ----------------------------------------------------------------------------
# DISEASE SYNONYMS — broad coverage: IBD, metabolic, neuropsych, CVD, liver, allergic, etc.
# ----------------------------------------------------------------------------

DISEASES: dict[str, dict] = {
    # ===== IBD (kept for completeness) =====
    "inflammatory bowel disease": {
        "synonyms": ["IBD", "inflammatory bowel disease", "ibd"],
        "abbrev": "IBD",
        "includes": ["crohn's disease", "ulcerative colitis"],
        "type": "DISEASE",
    },
    "crohn's disease": {
        "synonyms": ["Crohn's disease", "Crohns disease", "Crohn disease", "CD", "Crohn's",
                    "morbus crohn", "crohn"],
        "abbrev": "CD",
        "type": "DISEASE",
        "is_subtype_of": "inflammatory bowel disease",
    },
    "ulcerative colitis": {
        "synonyms": ["ulcerative colitis", "UC", "colitis ulcerosa", "uc"],
        "abbrev": "UC",
        "type": "DISEASE",
        "is_subtype_of": "inflammatory bowel disease",
    },

    # ===== IBS =====
    "irritable bowel syndrome": {
        "synonyms": ["IBS", "irritable bowel syndrome", "irritable colon"],
        "abbrev": "IBS",
        "type": "DISEASE",
    },

    # ===== Metabolic =====
    "type 2 diabetes mellitus": {
        "synonyms": ["type 2 diabetes", "T2DM", "T2D", "diabetes mellitus type 2",
                    "non-insulin-dependent diabetes", "adult-onset diabetes"],
        "abbrev": "T2DM",
        "type": "DISEASE",
    },
    "type 1 diabetes mellitus": {
        "synonyms": ["type 1 diabetes", "T1DM", "T1D", "diabetes mellitus type 1"],
        "abbrev": "T1DM",
        "type": "DISEASE",
    },
    "obesity": {
        "synonyms": ["obesity", "obesitas"],
        "type": "DISEASE",
    },

    # ===== Cancer =====
    "colorectal cancer": {
        "synonyms": ["colorectal cancer", "CRC", "colon cancer", "rectal cancer",
                    "colorectal carcinoma"],
        "abbrev": "CRC",
        "type": "DISEASE",
    },
    "gastric cancer": {
        "synonyms": ["gastric cancer", "stomach cancer", "gastric carcinoma"],
        "type": "DISEASE",
    },

    # ===== Cardiovascular =====
    "atherosclerosis": {
        "synonyms": ["atherosclerosis", "coronary artery disease", "CAD",
                    "cardiovascular disease", "CVD"],
        "abbrev": "CVD",
        "type": "DISEASE",
    },
    "hypertension": {
        "synonyms": ["hypertension", "high blood pressure", "HTN"],
        "abbrev": "HTN",
        "type": "DISEASE",
    },

    # ===== Neuropsychiatric =====
    "parkinson's disease": {
        "synonyms": ["Parkinson's disease", "Parkinsons disease", "PD", "Parkinson's",
                    "parkinson's"],
        "abbrev": "PD",
        "type": "DISEASE",
    },
    "alzheimer's disease": {
        "synonyms": ["Alzheimer's disease", "Alzheimers disease", "AD"],
        "abbrev": "AD",
        "type": "DISEASE",
    },
    "autism spectrum disorder": {
        "synonyms": ["autism spectrum disorder", "ASD", "autism"],
        "abbrev": "ASD",
        "type": "DISEASE",
    },
    "depression": {
        "synonyms": ["depression", "major depressive disorder", "MDD"],
        "type": "DISEASE",
    },

    # ===== Liver =====
    "liver disease": {
        "synonyms": ["liver disease", "hepatic disease", "NAFLD", "NASH",
                    "non-alcoholic fatty liver disease", "MASLD", "MASH"],
        "type": "DISEASE",
    },
    "hepatic encephalopathy": {
        "synonyms": ["hepatic encephalopathy", "HE", "portal-systemic encephalopathy"],
        "abbrev": "HE",
        "type": "DISEASE",
    },

    # ===== Allergic =====
    "allergic disease": {
        "synonyms": ["allergic disease", "allergy", "atopic disease", "allergic disorders"],
        "type": "DISEASE",
    },
    "antibiotic-associated diarrhea": {
        "synonyms": ["antibiotic-associated diarrhea", "AAD", "antibiotic associated diarrhea",
                    "C. difficile-associated diarrhea"],
        "abbrev": "AAD",
        "type": "DISEASE",
    },
    "infant colic": {
        "synonyms": ["infant colic", "infantile colic", "baby colic"],
        "type": "DISEASE",
    },
    "asthma": {
        "synonyms": ["asthma"],
        "type": "DISEASE",
    },

    # ===== Infection =====
    "c. difficile infection": {
        "synonyms": ["C. difficile infection", "CDI", "clostridium difficile infection",
                    "clostridioides difficile infection", "c diff infection"],
        "abbrev": "CDI",
        "type": "DISEASE",
    },
    "pseudomembranous colitis": {
        "synonyms": ["pseudomembranous colitis"],
        "type": "DISEASE",
    },
    "bacterial infections": {
        "synonyms": ["bacterial infections", "bacterial infection", "bacteriosis"],
        "type": "DISEASE",
    },

    # ===== Other =====
    "celiac disease": {
        "synonyms": ["celiac disease", "coeliac disease", "gluten-sensitive enteropathy"],
        "type": "DISEASE",
    },
    "rheumatoid arthritis": {
        "synonyms": ["rheumatoid arthritis", "RA"],
        "abbrev": "RA",
        "type": "DISEASE",
    },
    "psoriasis": {
        "synonyms": ["psoriasis"],
        "type": "DISEASE",
    },
    "anxiety": {
        "synonyms": ["anxiety", "generalized anxiety disorder", "GAD"],
        "type": "DISEASE",
    },
    "kidney disease": {
        "synonyms": ["kidney disease", "chronic kidney disease", "CKD", "renal disease"],
        "abbrev": "CKD",
        "type": "DISEASE",
    },
    "chronic fatigue syndrome": {
        "synonyms": ["chronic fatigue syndrome", "CFS", "myalgic encephalomyelitis", "ME"],
        "type": "DISEASE",
    },
    "anorexia nervosa": {
        "synonyms": ["anorexia nervosa", "AN"],
        "type": "DISEASE",
    },
}


# ----------------------------------------------------------------------------
# KNOWN BIOLOGICAL ASSOCIATIONS — rebalanced across categories.
# IBD is one of 11 categories (~9% of associations). The set reflects
# general human microbiome biology, not just disease.
# ----------------------------------------------------------------------------

KNOWN_ASSOCIATIONS: dict[str, dict] = {
    # ===== 1. IBD (kept, consolidated) =====
    "ibd_overall": {
        "depleted_organisms": [
            "faecalibacterium prausnitzii", "akkermansia muciniphila",
            "bifidobacterium longum", "roseburia intestinalis",
            "eubacterium rectale", "lactobacillus rhamnosus",
        ],
        "enriched_organisms": [
            "ruminococcus gnavus", "fusobacterium nucleatum",
            "enterobacteriaceae", "veillonella", "klebsiella pneumoniae",
            "adherent invasive escherichia coli", "candida albicans",
        ],
        "treatments": [
            "infliximab", "adalimumab", "ustekinumab", "vedolizumab",
            "mesalamine", "sulfasalazine", "prednisone", "budesonide",
            "azathioprine", "6-mercaptopurine", "methotrexate",
        ],
        "evidence_quality": "high (multiple meta-analyses)",
    },

    # ===== 2. Butyrate production =====
    "butyrate_production": {
        "producer_to_product": [
            ("faecalibacterium prausnitzii", "butyrate"),
            ("faecalibacterium prausnitzii", "short-chain fatty acid"),
            ("eubacterium rectale", "butyrate"),
            ("eubacterium hallii", "butyrate"),
            ("eubacterium hallii", "propionate"),
            ("roseburia intestinalis", "butyrate"),
            ("roseburia hominis", "butyrate"),
            ("anaerostipes hadrus", "butyrate"),
            ("coprococcus catus", "butyrate"),
            ("butyrivibrio fibrisolvens", "butyrate"),
            ("butyricicoccus pullicaecorum", "butyrate"),
            ("bifidobacterium longum", "short-chain fatty acid"),
        ],
        "evidence_quality": "high",
    },

    # ===== 3. SCFA function (anti-inflammatory) =====
    "scfa_function": {
        "metabolite_to_disease": [
            ("butyrate", "inflammatory bowel disease"),
            ("butyrate", "colorectal cancer"),
            ("short-chain fatty acid", "inflammatory bowel disease"),
            ("propionate", "inflammatory bowel disease"),
            ("acetate", "inflammatory bowel disease"),
        ],
        "evidence_quality": "high",
    },

    # ===== 4. Type 2 diabetes =====
    "t2d_association": {
        "depleted_organisms": [
            "akkermansia muciniphila", "bifidobacterium longum",
            "bifidobacterium",  # genus-level depletion (Wu 2017)
            "faecalibacterium prausnitzii", "roseburia intestinalis",
        ],
        "treatments": [
            "metformin", "glipizide", "sitagliptin", "empagliflozin",
            "liraglutide", "semaglutide",
        ],
        "evidence_quality": "moderate",
    },

    # ===== 5. Obesity =====
    "obesity_association": {
        "depleted_organisms": [
            "akkermansia muciniphila", "bifidobacterium longum",
            "faecalibacterium prausnitzii",
        ],
        "enriched_organisms": [
            "firmicutes",
        ],
        "treatments": ["liraglutide", "semaglutide"],
        "evidence_quality": "moderate (F/B ratio is debated)",
    },

    # ===== 6. Colorectal cancer =====
    "crc_association": {
        "enriched_organisms": [
            "fusobacterium nucleatum", "enterobacteriaceae",
            "bacteroides fragilis",
        ],
        "depleted_organisms": ["faecalibacterium prausnitzii"],
        "evidence_quality": "high for F. nucleatum",
    },

    # ===== 7. Cardiovascular (TMAO, atherosclerosis) =====
    "cvd_association": {
        "metabolite_to_disease": [
            ("trimethylamine n-oxide", "atherosclerosis"),
        ],
        "enriched_organisms": [
            "ruminococcus gnavus",  # some evidence for atherosclerosis
        ],
        "treatments": [
            "atorvastatin", "simvastatin", "rosuvastatin",
            "lisinopril", "losartan", "amlodipine", "metoprolol",
            "aspirin",
        ],
        "evidence_quality": "moderate",
    },

    # ===== 8. Neuropsychiatric (gut-brain axis) =====
    "neuropsych_association": {
        "organism_to_disease": [
            # Bifidobacterium and Lactobacillus depleted in depression
            # Akkermansia enrichment associated with improved cognition
        ],
        "metabolite_to_disease": [
            ("gamma-aminobutyric acid", "anxiety"),
            ("serotonin", "depression"),
        ],
        "treatments": [
            "fluoxetine", "sertraline", "risperidone", "olanzapine",
        ],
        "evidence_quality": "emerging (gut-brain axis research)",
    },

    # ===== 9. Antibiotic disruption (general) =====
    "antibiotic_disruption": {
        "antibiotic_to_organism": [
            ("vancomycin", "faecalibacterium prausnitzii"),
            ("vancomycin", "bifidobacterium"),
            ("ciprofloxacin", "bifidobacterium"),
            ("ciprofloxacin", "roseburia"),
            ("metronidazole", "bifidobacterium"),
            ("metronidazole", "roseburia intestinalis"),
            ("clindamycin", "bifidobacterium"),
            ("clindamycin", "lactobacillus"),
            ("clindamycin", "clostridioides difficile"),  # clindamycin -> C. diff risk
        ],
        "evidence_quality": "high (Dethlefsen 2011, multiple)",
    },

    # ===== 10. Probiotic benefit (general) =====
    "probiotic_benefit": {
        "probiotic_to_condition": [
            ("saccharomyces boulardii", "antibiotic-associated diarrhea"),
            ("saccharomyces boulardii", "c. difficile infection"),
            ("lactobacillus rhamnosus", "antibiotic-associated diarrhea"),
            ("lactobacillus rhamnosus", "c. difficile infection"),
            ("lactobacillus reuteri", "infant colic"),
            ("lactobacillus reuteri", "allergic disease"),
        ],
        "evidence_quality": "moderate (specific strains, conditions)",
    },

    # ===== 11. C. difficile infection =====
    "cdi_treatment": {
        "treatments": [
            "vancomycin", "metronidazole", "fidaxomicin",
            "ciprofloxacin", "rifaximin",
        ],
        "evidence_quality": "high",
    },

    # ===== 12. Liver =====
    "liver_disease": {
        "metabolite_to_disease": [
            ("trimethylamine n-oxide", "liver disease"),
        ],
        "enriched_organisms": [
            "klebsiella pneumoniae",  # some evidence in liver disease
        ],
        "treatments": [
            "rifaximin",  # for hepatic encephalopathy
        ],
        "evidence_quality": "moderate",
    },
}


# ----------------------------------------------------------------------------
# Cross-cutting semantic relations (used by build_mini_hybrid_v2.py)
# ----------------------------------------------------------------------------

SCFA_TREATS_INFLAMMATION = {
    "butyrate": ["inflammatory bowel disease", "ulcerative colitis", "crohn's disease",
                "colorectal cancer"],
    "propionate": ["inflammatory bowel disease"],
    "acetate": ["inflammatory bowel disease"],
    "short-chain fatty acid": ["inflammatory bowel disease", "ulcerative colitis",
                              "colorectal cancer"],
}

ANTIBIOTIC_DISRUPTS = {
    "vancomycin": ["faecalibacterium prausnitzii", "bifidobacterium", "roseburia"],
    "ciprofloxacin": ["bifidobacterium", "faecalibacterium prausnitzii", "roseburia"],
    "metronidazole": ["bifidobacterium", "roseburia intestinalis", "faecalibacterium prausnitzii"],
    "clindamycin": ["bifidobacterium", "lactobacillus", "faecalibacterium prausnitzii"],
    "rifaximin": ["bifidobacterium"],
    "tetracycline": ["bifidobacterium", "lactobacillus"],
    "azithromycin": ["bifidobacterium", "faecalibacterium prausnitzii"],
    "amoxicillin": ["bifidobacterium", "lactobacillus"],
}


# ----------------------------------------------------------------------------
# Category -> primary disease mapping
# ----------------------------------------------------------------------------
# Each KNOWN_ASSOCIATIONS category can have an "old-style" depleted_organisms /
# enriched_organisms / treatments list, where the target is the category itself
# (e.g. "ibd_overall"). For the build to emit concrete disease names that
# match the gold standard, we map each category to its canonical disease term.
# Some categories expand to multiple diseases (e.g. cvd_association covers
# atherosclerosis + hypertension); the build iterates the list.

CATEGORY_TO_DISEASE: dict[str, list[str]] = {
    "ibd_overall":          ["inflammatory bowel disease", "crohn's disease", "ulcerative colitis"],
    "crc_association":      ["colorectal cancer"],
    "obesity_association":  ["obesity"],
    "t2d_association":      ["type 2 diabetes mellitus"],
    "cvd_association":      ["atherosclerosis", "hypertension", "cardiovascular disease"],
    "neuropsych_association": ["depression", "anxiety"],
    "liver_disease":        ["liver disease", "non-alcoholic fatty liver disease"],
    "cdi_treatment":        ["c. difficile infection"],
    "probiotic_benefit":    ["antibiotic-associated diarrhea", "infant colic",
                              "allergic disease", "irritable bowel syndrome"],
    # Categories that don't map cleanly to a single disease:
    "butyrate_production":  [],  # target is a chemical, not a disease
    "scfa_function":        ["inflammatory bowel disease", "ulcerative colitis",
                              "crohn's disease", "colorectal cancer"],
    "antibiotic_disruption": [],  # target is an organism, not a disease
}


# ----------------------------------------------------------------------------
# Helper functions (unchanged from previous version)
# ----------------------------------------------------------------------------

def norm(s: str) -> str:
    """Standard normalization: lowercase, strip non-alphanum (keep spaces), collapse spaces."""
    import re
    if not s:
        return ""
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9\s\-]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _build_index():
    """Build a normalized lookup index."""
    idx: dict[str, tuple[str, str, str]] = {}

    for canonical, info in ORGANISMS.items():
        forms = [canonical] + info.get("synonyms", [])
        for f in forms:
            n = norm(f)
            if n:
                idx[n] = (canonical, "organism", "ORGANISM")
    for canonical, info in DRUGS.items():
        forms = [canonical] + info.get("synonyms", [])
        for f in forms:
            n = norm(f)
            if n:
                idx[n] = (canonical, "drug", "CHEMICAL")
    for canonical, info in DISEASES.items():
        forms = [canonical] + info.get("synonyms", [])
        for f in forms:
            n = norm(f)
            if n:
                idx[n] = (canonical, "disease", "DISEASE")

    return idx


_LOOKUP = _build_index()


def lookup(term: str) -> dict | None:
    n = norm(term)
    if n in _LOOKUP:
        canonical, source, cdm_type = _LOOKUP[n]
        if source == "organism":
            info = ORGANISMS[canonical]
        elif source == "drug":
            info = DRUGS[canonical]
        else:
            info = DISEASES[canonical]
        return {
            "canonical": canonical,
            "source": source,
            "type": cdm_type,
            "info": info,
            "matched_norm": n,
        }
    return None


def is_known_organism(term: str) -> bool:
    return lookup(term) is not None and lookup(term)["source"] == "organism"


def is_known_drug(term: str) -> bool:
    return lookup(term) is not None and lookup(term)["source"] == "drug"


def is_known_disease(term: str) -> bool:
    return lookup(term) is not None and lookup(term)["source"] == "disease"


def canonicalize(term: str) -> tuple[str, str | None]:
    info = lookup(term)
    if info:
        return info["canonical"], info["type"]
    return term, None


def known_organisms() -> list[str]:
    return list(ORGANISMS.keys())


def known_drugs() -> list[str]:
    return list(DRUGS.keys())


def known_diseases() -> list[str]:
    return list(DISEASES.keys())


def kb_stats() -> dict:
    return {
        "n_organisms": len(ORGANISMS),
        "n_drugs": len(DRUGS),
        "n_diseases": len(DISEASES),
        "n_known_associations": len(KNOWN_ASSOCIATIONS),
        "n_total_indexed_forms": len(_LOOKUP),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(kb_stats(), indent=2))
    # Test lookups on a diverse set
    for term in ["F. prausnitzii", "infliximab", "ibd", "TMAO", "metformin",
                 "A. muciniphila", "Akkermansia", "butyrate", "Fusobacterium",
                 "vancomycin", "C. albicans", "Parkinson's", "M. smithii",
                 "bifidobacterium", "Lactobacillus", "lipopolysaccharide",
                 "short-chain fatty acid", "T2DM", "CKD", "fluoxetine"]:
        info = lookup(term)
        if info:
            print(f"  {term!r:35s} -> {info['canonical']!r:40s} {info['type']}")
        else:
            print(f"  {term!r:35s} -> NOT IN KB")
