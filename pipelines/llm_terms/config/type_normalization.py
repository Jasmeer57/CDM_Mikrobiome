"""
Type Normalization Configuration
================================
Defines canonical type names and mappings for normalizing entity types
in the knowledge graph. Handles pluralization, spelling variants, and
filters out non-biological noise types.
"""

from typing import Set, Dict, Optional


# ============================================================================
# TYPE NORMALIZATION MAPPINGS
# ============================================================================

TYPE_MAPPINGS: Dict[str, str] = {
    # Plural to singular variants
    'GENES': 'GENE',
    'PROTEINS': 'PROTEIN',
    'ORGANISMS': 'ORGANISM',
    'DISEASES': 'DISEASE',
    'CHEMICALS': 'CHEMICAL',
    'CELL_TYPES': 'CELL_TYPE',
    'CELLS': 'CELL_TYPE',

    # Compound/split type variants
    'GENE/PROTEIN': 'PROTEIN',  # Default to protein when ambiguous
    'PATHWAY/PROTEIN': 'PROTEIN',
    'PROTEIN/GENE': 'GENE',  # Prioritize gene when listed first

    # Chemical type variants
    'BIOCHEMICAL_ENTITY': 'CHEMICAL',
    'BIOCHEMICAL': 'CHEMICAL',
    'METABOLITE': 'CHEMICAL',
    'METABOLITES': 'CHEMICAL',
    'COMPOUND': 'CHEMICAL',
    'DRUG': 'CHEMICAL',
    'TOXIN': 'CHEMICAL',

    # Clinical type variants
    'CLINICAL METADATA': 'CLINICAL',
    'CLINICAL PARAMETER': 'CLINICAL_PARAMETER',
    'CLINICAL FINDING': 'CLINICAL',
    'SYMPTOM': 'CLINICAL',
    'PHENOTYPE': 'CLINICAL',

    # Organism type variants
    'BACTERIUM': 'ORGANISM',
    'BACTERIA': 'ORGANISM',
    'MICROBE': 'ORGANISM',
    'MICROORGANISM': 'ORGANISM',
    'PATHOGEN': 'ORGANISM',
    'TAXON': 'ORGANISM',

    # Gene/Genomic variants
    'GENETIC': 'GENE',
    'GENOMIC': 'GENE',
    'DNA/RNA': 'DNA_RNA',

    # Pathway type variants (Phase 2 - PATHWAY type)
    'PATHWAYS': 'PATHWAY',
    'METABOLIC_PATHWAY': 'PATHWAY',
    'SIGNALING_PATHWAY': 'PATHWAY',
    'BIOLOGICAL_PATHWAY': 'PATHWAY',

    # Methodological type variants - split into proper types
    'LAB_METHOD': 'EXPERIMENTAL_METHOD',
    'EXPERIMENTAL_METHOD': 'EXPERIMENTAL_METHOD',  # New canonical type
    'ANALYSIS_METHOD': 'EXPERIMENTAL_METHOD',
    'STATISTICAL_METHOD': 'DATA_ANALYSIS',  # Keep stats as DATA_ANALYSIS
    'STUDY_DESIGN': 'STUDY_DESIGN',  # New canonical type
    'EXPERIMENTAL_DESIGN': 'STUDY_DESIGN',
    'CONTROL_GROUP': 'STUDY_DESIGN',
    'TRANSGENIC_MODEL': 'ORGANISM',  # Re-classify as organism

    # Deprecated/legacy types
    'SCIENTIFIC_TERM': 'DATA_ANALYSIS',
    'SAMPLE_METHOD': 'DATA_ANALYSIS',
}


# ============================================================================
# CANONICAL TYPE SETS
# ============================================================================

# Core biological types that should be preserved in the KG
CORE_BIOLOGICAL_TYPES: Set[str] = {
    'ORGANISM',
    'CHEMICAL',
    'GENE',
    'PROTEIN',
    'DISEASE',
    'CELL_TYPE',
    'DNA_RNA',
    'CLINICAL',
    'CLINICAL_PARAMETER',
    'PATHWAY',  # Phase 2: Add pathway type
    'STUDY_DESIGN',  # Phase 1: Study design entities
}


# Types that represent methods/tools (may be filtered or tagged separately)
METHOD_TYPES: Set[str] = {
    'DATA_ANALYSIS',  # Statistical/bioinformatics analysis methods
    'EXPERIMENTAL_METHOD',  # Wet lab and experimental methods
    'SAMPLE_METHOD',
    'GENOMICS',
}


# Types that are considered noise and should be removed
NOISE_TYPES: Set[str] = {
    'INSTRUMENT',
    'STATISTICAL_TEST',
    'SOFTWARE_VERSION',
    'SOFTWARE',
    'HARDWARE',
    'PLATFORM_VERSION',
    'KIT_VERSION',
}


# Types that are considered metadata (preserved in properties, not as nodes)
METADATA_TYPES: Set[str] = {
    'ANNOTATION',
    'ONTOLOGY_TERM',
    'DATABASE_ID',
    'REFERENCE',
}


# ============================================================================
# RELATIONSHIP TYPE NORMALIZATION
# ============================================================================

RELATIONSHIP_TYPE_MAPPINGS: Dict[str, str] = {
    # Plural variants
    'produces': 'produces',
    'produce': 'produces',
    'producing': 'produces',
    'consumes': 'consumes',
    'consume': 'consumes',
    'encodes': 'encodes',
    'encode': 'encodes',
    'encoding': 'encodes',

    # Semantic variants - causal
    'causes': 'causes',
    'cause': 'causes',
    'causing': 'causes',
    'leads_to': 'causes',
    'results_in': 'causes',
    'triggers': 'causes',
    'induces': 'causes',

    # Semantic variants - treatment
    'treats': 'treats',
    'treat': 'treats',
    'treating': 'treats',
    'ameliorates': 'treats',
    'alleviates': 'treats',
    'prevents': 'treats',

    # Semantic variants - interaction
    'interacts_with': 'interacts_with',
    'interact_with': 'interacts_with',
    'interacting': 'interacts_with',
    'binds_to': 'interacts_with',
    'binds': 'interacts_with',
    'binding': 'interacts_with',

    # Semantic variants - inhibition
    'inhibits': 'inhibits',
    'inhibit': 'inhibits',
    'inhibiting': 'inhibits',
    'blocks': 'inhibits',
    'suppresses': 'inhibits',

    # Semantic variants - activation
    'activates': 'activates',
    'activate': 'activates',
    'activating': 'activates',
    'stimulates': 'activates',
    'promotes': 'activates',

    # Semantic variants - correlation
    'correlates_with': 'correlates_with',
    'correlate': 'correlates_with',
    'correlated': 'correlates_with',
    'associated_with': 'correlates_with',
    'associated': 'correlates_with',
    'associates_with': 'correlates_with',
}


# ============================================================================
# VALID RELATIONSHIP TYPE CONSTRAINTS
# ============================================================================

# Limited set of ~10 well-defined relationship types
VALID_RELATIONSHIP_TYPES: Set[str] = {
    'causes',           # Entity A causes Entity B
    'treats',           # Entity A treats Entity B
    'produces',         # Organism produces chemical
    'consumes',         # Organism consumes chemical
    'encodes',          # Gene encodes protein
    'interacts_with',   # Physical interaction
    'inhibits',         # Entity A inhibits Entity B
    'activates',        # Entity A activates Entity B
    'correlates_with',  # Statistical/correlational association
    'measured_by',      # Entity measured by method
    'analyzed_by',      # Entity analyzed by method
    'derived_from',     # Entity derived from analysis
}


# Directional type pair constraints
VALID_TYPE_PAIRS: Dict[tuple, Set[str]] = {
    ('ORGANISM', 'DISEASE'): {'causes', 'treats', 'correlates_with'},
    ('ORGANISM', 'CHEMICAL'): {'produces', 'consumes'},
    ('GENE', 'PROTEIN'): {'encodes', 'regulates'},
    ('GENE', 'GENE'): {'regulates', 'interacts_with'},
    ('PROTEIN', 'PROTEIN'): {'interacts_with', 'inhibits', 'activates'},
    ('CHEMICAL', 'PROTEIN'): {'interacts_with', 'inhibits', 'activates'},
    ('CHEMICAL', 'DISEASE'): {'causes', 'treats'},
    ('DISEASE', 'CLINICAL'): {'characterized_by', 'has_symptom'},

    # EXPERIMENTAL_METHOD relationships (Phase 1 - was DATA_ANALYSIS)
    ('EXPERIMENTAL_METHOD', 'ORGANISM'): {'measures', 'quantifies', 'detects', 'identifies'},
    ('EXPERIMENTAL_METHOD', 'GENE'): {'measures', 'quantifies', 'detects'},
    ('EXPERIMENTAL_METHOD', 'PROTEIN'): {'measures', 'quantifies', 'detects'},
    ('EXPERIMENTAL_METHOD', 'CHEMICAL'): {'measures', 'detects', 'quantifies'},
    ('EXPERIMENTAL_METHOD', 'DISEASE'): {'diagnoses', 'detects', 'screens_for'},

    # STUDY_DESIGN relationships (Phase 1)
    ('STUDY_DESIGN', 'ORGANISM'): {'studies', 'investigates', 'compares', 'examines'},
    ('STUDY_DESIGN', 'DISEASE'): {'investigates', 'treats', 'prevents', 'examines'},
    ('STUDY_DESIGN', 'CLINICAL'): {'measures', 'assesses', 'evaluates'},
    ('STUDY_DESIGN', 'CHEMICAL'): {'analyzes', 'quantifies', 'examines'},

    # PATHWAY relationships (Phase 2)
    ('GENE', 'PATHWAY'): {'regulates', 'participates_in', 'activates', 'inhibits'},
    ('PROTEIN', 'PATHWAY'): {'participates_in', 'activates', 'inhibits', 'regulates'},
    ('PATHWAY', 'CHEMICAL'): {'produces', 'metabolizes', 'synthesizes'},
    ('PATHWAY', 'ORGANISM'): {'exists_in', 'utilized_by', 'activated_in'},
    ('PATHWAY', 'DISEASE'): {'contributes_to', 'mediates', 'causes', 'associated_with'},
    ('ORGANISM', 'PATHWAY'): {'utilizes', 'activates', 'modulates'},

    # DATA_ANALYSIS relationships (kept for compatibility)
    ('ORGANISM', 'DATA_ANALYSIS'): {'measured_by', 'analyzed_by', 'derived_from'},
    ('CHEMICAL', 'DATA_ANALYSIS'): {'measured_by', 'analyzed_by', 'derived_from'},
    ('GENE', 'DATA_ANALYSIS'): {'measured_by', 'analyzed_by'},
    ('PROTEIN', 'DATA_ANALYSIS'): {'measured_by', 'analyzed_by'},
    ('DISEASE', 'DATA_ANALYSIS'): {'measured_by', 'analyzed_by', 'derived_from'},
}


# ============================================================================
# EVIDENCE TYPE CLASSIFICATIONS
# ============================================================================

class EvidenceType:
    """Evidence type classifications for relationships."""

    LITERATURE = "literature"      # From literature/papers
    EXPERIMENTAL = "experimental"    # From direct experiment/measurement
    COMPUTATIONAL = "computational"  # From computational analysis/modeling

    @classmethod
    def all(cls) -> Set[str]:
        return {cls.LITERATURE, cls.EXPERIMENTAL, cls.COMPUTATIONAL}


# ============================================================================
# SUBGRAPH LABELS
# ============================================================================

class SubgraphLabel:
    """Subgraph labels for organizing KG content."""

    MECHANISM = "mechanism"                      # Biological mechanism relationships
    MICROBIOME_METABOLITE = "microbiome_metabolite"  # Microbiome-metabolite interactions
    METHODS_PROVENANCE = "methods_provenance"    # Methods and data provenance

    @classmethod
    def all(cls) -> Set[str]:
        return {cls.MECHANISM, cls.MICROBIOME_METABOLITE, cls.METHODS_PROVENANCE}


# ============================================================================
# KG SCOPE STATEMENT
# ============================================================================

KG_SCOPE = (
    "This knowledge graph models mechanistic and microbiome-mediated pathways "
    "of Enterotoxigenic E. coli–associated diarrheal disease, integrating "
    "biological entities (organisms, genes, proteins, chemicals, diseases) with "
    "experimental and analytical context. The graph focuses on ETEC pathogenesis "
    "mechanisms, host-microbiome interactions, and metabolite-mediated "
    "modulation of disease outcomes."
)


# ============================================================================
# FUNCTIONS
# ============================================================================

def normalize_type_name(type_name: str) -> str:
    """
    Normalize an entity type name to its canonical form.

    Args:
        type_name: The raw type name to normalize

    Returns:
        The canonical type name
    """
    if not type_name:
        return 'UNKNOWN'

    # Convert to uppercase and strip whitespace
    normalized = type_name.upper().strip()

    # Apply mappings
    if normalized in TYPE_MAPPINGS:
        return TYPE_MAPPINGS[normalized]

    # If no mapping found, return the original (already uppercased)
    return normalized


def normalize_relationship_type(rel_type: str) -> str:
    """
    Normalize a relationship type to its canonical form.

    Args:
        rel_type: The raw relationship type to normalize

    Returns:
        The canonical relationship type
    """
    if not rel_type:
        return 'associated_with'

    # Convert to lowercase and strip whitespace
    normalized = rel_type.lower().strip()

    # Apply mappings
    if normalized in RELATIONSHIP_TYPE_MAPPINGS:
        return RELATIONSHIP_TYPE_MAPPINGS[normalized]

    # If no mapping found, return the original (already lowercased)
    return normalized


def is_biological_type(type_name: str) -> bool:
    """
    Check if a type is a core biological type (not noise or method).

    Args:
        type_name: The type name to check

    Returns:
        True if biological, False otherwise
    """
    normalized = normalize_type_name(type_name)
    return normalized in CORE_BIOLOGICAL_TYPES


def is_noise_type(type_name: str) -> bool:
    """
    Check if a type should be filtered as noise.

    Args:
        type_name: The type name to check

    Returns:
        True if noise, False otherwise
    """
    normalized = normalize_type_name(type_name)
    return normalized in NOISE_TYPES


def is_valid_type_pair(source_type: str, target_type: str, rel_type: str) -> bool:
    """
    Check if a relationship is valid for the given type pair.

    Args:
        source_type: Source entity type
        target_type: Target entity type
        rel_type: Relationship type

    Returns:
        True if valid, False otherwise
    """
    normalized_rel = normalize_relationship_type(rel_type)
    normalized_source = normalize_type_name(source_type)
    normalized_target = normalize_type_name(target_type)

    key = (normalized_source, normalized_target)

    if key in VALID_TYPE_PAIRS:
        return normalized_rel in VALID_TYPE_PAIRS[key]

    # Allow unknown type pairs for flexibility
    return True


def create_canonical_id(term: str, entity_type: str) -> str:
    """
    Create a stable canonical ID for an entity.

    Format: {TYPE_PREFIX}_{normalized_term}

    Args:
        term: Entity term/name
        entity_type: Entity type

    Returns:
        Canonical ID string
    """
    import re

    if not term:
        return f"{entity_type}_unknown"

    # Normalize type to get prefix
    normalized_type = normalize_type_name(entity_type)

    # Normalize term: lowercase, replace special chars with underscores
    normalized_term = term.lower().strip()
    normalized_term = re.sub(r'[^\w]+', '_', normalized_term)
    normalized_term = normalized_term.strip('_')

    # Create prefix based on type
    prefixes = {
        'ORGANISM': 'ORG',
        'CHEMICAL': 'CHEM',
        'GENE': 'GENE',
        'PROTEIN': 'PROT',
        'DISEASE': 'DIS',
        'CELL_TYPE': 'CELL',
        'DNA_RNA': 'NA',
        'CLINICAL': 'CLIN',
        'CLINICAL_PARAMETER': 'CPARAM',
        'DATA_ANALYSIS': 'METHOD',
        'EXPERIMENTAL_METHOD': 'EXP',
        'STUDY_DESIGN': 'DESIGN',
        'PATHWAY': 'PATH',
    }

    prefix = prefixes.get(normalized_type, normalized_type[:4].upper())

    # Truncate term if too long
    if len(normalized_term) > 50:
        normalized_term = normalized_term[:50]

    return f"{prefix}_{normalized_term}"


def infer_subgraph_label(
    source_type: str,
    target_type: str,
    relationship_type: str
) -> str:
    """
    Infer the appropriate subgraph label for a relationship.

    Args:
        source_type: Source entity type
        target_type: Target entity type
        relationship_type: Relationship type

    Returns:
        Subgraph label (mechanism, microbiome_metabolite, or methods_provenance)
    """
    # Methods/provenance: involves DATA_ANALYSIS
    if normalize_type_name(source_type) == 'DATA_ANALYSIS' or \
       normalize_type_name(target_type) == 'DATA_ANALYSIS':
        return SubgraphLabel.METHODS_PROVENANCE

    # Microbiome-metabolite: organism <-> chemical
    source_norm = normalize_type_name(source_type)
    target_norm = normalize_type_name(target_type)
    if {source_norm, target_norm} == {'ORGANISM', 'CHEMICAL'}:
        return SubgraphLabel.MICROBIOME_METABOLITE

    # Default: mechanism
    return SubgraphLabel.MECHANISM
