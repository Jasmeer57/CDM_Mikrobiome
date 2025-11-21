"""
Comprehensive Entity Linker System for Biomedical NLP
Supports multiple knowledge bases: UMLS, HPO, GO, CHEBI, DrugBank, and more.
Based on standard SciSpaCy entity linking patterns and biomedical best practices.
"""

import logging
import time
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import requests
import spacy
import json
import re

# Optional scispacy imports
try:
    from scispacy.linking import EntityLinker
    from scispacy.umls_linking import UmlsEntityLinker
    SCISPACY_AVAILABLE = True
except ImportError:
    EntityLinker = None
    UmlsEntityLinker = None
    SCISPACY_AVAILABLE = False

from src.config.settings import UMLSConfig, BioPortalConfig

logger = logging.getLogger(__name__)


@dataclass
class EntityMapping:
    """Universal entity mapping result"""
    entity_id: str
    entity_name: str
    knowledge_base: str
    score: float
    entity_type: Optional[str] = None
    definition: Optional[str] = None
    synonyms: List[str] = None
    context: Optional[str] = None
    source: str = "entity_linker"

    def __post_init__(self):
        if self.synonyms is None:
            self.synonyms = []


@dataclass
class UMLEntity:
    """UMLS entity structure"""
    cui: str
    name: str
    score: float
    tui: Optional[str] = None
    definition: Optional[str] = None
    synonyms: List[str] = None

    def __post_init__(self):
        if self.synonyms is None:
            self.synonyms = []


@dataclass
class HPOEntity:
    """Human Phenotype Ontology entity"""
    hpo_id: str
    term: str
    score: float
    definition: Optional[str] = None
    synonyms: List[str] = None

    def __post_init__(self):
        if self.synonyms is None:
            self.synonyms = []


@dataclass
class GOEntity:
    """Gene Ontology entity"""
    go_id: str
    term: str
    category: str  # BP, MF, CC
    score: float
    definition: Optional[str] = None
    synonyms: List[str] = None

    def __post_init__(self):
        if self.synonyms is None:
            self.synonyms = []


@dataclass
class CHEBIEntity:
    """ChEBI chemical entity"""
    chebi_id: str
    name: str
    score: float
    formula: Optional[str] = None
    definition: Optional[str] = None
    synonyms: List[str] = None

    def __post_init__(self):
        if self.synonyms is None:
            self.synonyms = []


@dataclass
class DrugBankEntity:
    """DrugBank drug entity"""
    drugbank_id: str
    name: str
    score: float
    description: Optional[str] = None
    synonyms: List[str] = None

    def __post_init__(self):
        if self.synonyms is None:
            self.synonyms = []


@dataclass
class ComprehensiveEntityResult:
    """Comprehensive entity linking result"""
    term: str
    umls_entities: List[UMLEntity]
    hpo_entities: List[HPOEntity]
    go_entities: List[GOEntity]
    chebi_entities: List[CHEBIEntity]
    drugbank_entities: List[DrugBankEntity]
    other_ontologies: Dict[str, List[EntityMapping]]

    def __post_init__(self):
        for field_name in ['umls_entities', 'hpo_entities', 'go_entities', 'chebi_entities', 'drugbank_entities']:
            if getattr(self, field_name) is None:
                setattr(self, field_name, [])
        if self.other_ontologies is None:
            self.other_ontologies = {}

    def to_dict(self):
        """Convert to dictionary for JSON serialization"""
        return {
            "term": self.term,
            "umls_entities": [self._serialize_entity(entity) for entity in self.umls_entities],
            "hpo_entities": [self._serialize_entity(entity) for entity in self.hpo_entities],
            "go_entities": [self._serialize_entity(entity) for entity in self.go_entities],
            "chebi_entities": [self._serialize_entity(entity) for entity in self.chebi_entities],
            "drugbank_entities": [self._serialize_entity(entity) for entity in self.drugbank_entities],
            "other_ontologies": {
                k: [self._serialize_entity(entity) for entity in v]
                for k, v in self.other_ontologies.items()
            }
        }

    def _serialize_entity(self, entity):
        """Helper method to serialize entities"""
        if hasattr(entity, '__dict__'):
            return {k: v for k, v in entity.__dict__.items() if not k.startswith('_')}
        return str(entity)


class ComprehensiveEntityLinker:
    """
    Comprehensive entity linking system supporting multiple biomedical knowledge bases
    """

    # API endpoints
    UMLS_API = "https://uts-ws.nlm.nih.gov/rest"
    HPO_API = "https://ontology.jax.org/api"
    GO_API = "http://purl.obolibrary.org/obo"
    CHEBI_API = "https://www.ebi.ac.uk/chebi/rest"
    DRUGBANK_API = "https://api.drugbank.com/v1"
    BIOportal_API = "https://data.bioontology.org"
    OLS_API = "https://www.ebi.ac.uk/ols/api"

    def __init__(self, umls_config: UMLSConfig, bioportal_config: BioPortalConfig):
        self.umls_config = umls_config
        self.bioportal_config = bioportal_config
        self.nlp_models = {}
        self.entity_linkers = {}

        # Initialize supported ontologies
        self.supported_ontologies = {
            "UMLS": self._get_umls_entities,
            "HPO": self._get_hpo_entities,
            "GO": self._get_go_entities,
            "CHEBI": self._get_chebi_entities,
            "DRUGBANK": self._get_drugbank_entities,
            "SNOMEDCT": self._get_snomed_entities,
            "MONDO": self._get_mondo_entities,
            "DOID": self._get_doid_entities,
            "HP": self._get_hp_entities,
            "EFO": self._get_efo_entities,
            "NCIT": self._get_ncit_entities
        }

        self._initialize_scispacy_linkers()

    def _initialize_scispacy_linkers(self):
        """Initialize SciSpaCy entity linkers if available"""
        if not SCISPACY_AVAILABLE:
            logger.warning("SciSpaCy not available - entity linking disabled")
            return

        try:
            # Try to load models with entity linkers
            model_configs = [
                ("en_core_sci_md", "UMLS"),
                ("en_core_sci_lg", "UMLS"),
            ]

            for model_name, linker_type in model_configs:
                try:
                    logger.info(f"Loading {model_name} with {linker_type} linker...")
                    nlp = spacy.load(model_name)

                    # Add entity linker if not already present
                    if "scispacy_linker" not in nlp.pipe_names:
                        nlp.add_pipe(
                            "scispacy_linker",
                            config={
                                "resolve_abbreviations": True,
                                "linker_name": linker_type.lower()
                            }
                        )

                    self.nlp_models[model_name] = nlp
                    self.entity_linkers[linker_type] = nlp.get_pipe("scispacy_linker")
                    logger.info(f"✓ Initialized {model_name} with {linker_type} linker")

                except Exception as e:
                    logger.warning(f"Failed to initialize {model_name}: {e}")

        except Exception as e:
            logger.error(f"Failed to initialize SciSpaCy linkers: {e}")

    def _get_umls_entities(self, term: str) -> List[UMLEntity]:
        """Get UMLS entities using SciSpaCy UMLS linker"""
        entities = []

        if not self.umls_config.enabled or "UMLS" not in self.entity_linkers:
            return entities

        try:
            linker = self.entity_linkers["UMLS"]
            doc = list(self.nlp_models["en_core_sci_md"].pipe([term]))[0]

            for ent in doc.ents:
                if hasattr(ent, '_') and hasattr(ent._, 'kb_ents'):
                    for cui, score in ent._.kb_ents:
                        if score > 0.7:  # Confidence threshold
                            concept_entity = linker.kb.cui_to_entity.get(cui)
                            if concept_entity:
                                entity = UMLEntity(
                                    cui=cui,
                                    name=concept_entity.canonical_name,
                                    score=round(float(score), 4),
                                    tui=concept_entity.tui,
                                    definition=concept_entity.definition[:200] if concept_entity.definition else None,
                                    synonyms=list(concept_entity.aliases)[:10] if concept_entity.aliases else []
                                )
                                entities.append(entity)

            # Sort by score and return top results
            entities.sort(key=lambda x: x.score, reverse=True)
            return entities[:5]

        except Exception as e:
            logger.warning(f"UMLS linking failed for '{term}': {e}")
            return entities

    def _get_hpo_entities(self, term: str) -> List[HPOEntity]:
        """Get Human Phenotype Ontology entities via BioPortal API"""
        entities = []

        if not self.bioportal_config.enabled or not self.bioportal_config.api_key:
            return entities

        try:
            url = f"{self.BIOportal_API}/search"
            params = {
                "q": term,
                "apikey": self.bioportal_config.api_key,
                "ontologies": "HP",
                "require_exact_match": "true",
                "pagesize": 5
            }

            response = requests.get(url, params=params, timeout=self.bioportal_config.timeout)
            response.raise_for_status()
            data = response.json()

            for item in data.get("collection", []):
                if item.get("@type") == "http://www.w3.org/2002/07/owl#Class":
                    hpo_id = item.get("@id", "").split("/")[-1]
                    entity = HPOEntity(
                        hpo_id=hpo_id,
                        term=item.get("prefLabel", ""),
                        score=1.0,  # Exact match
                        definition=item.get("definition", [""])[0] if item.get("definition") else None,
                        synonyms=item.get("synonym", [])[:5] if item.get("synonym") else []
                    )
                    entities.append(entity)

        except Exception as e:
            logger.warning(f"HPO linking failed for '{term}': {e}")

        return entities

    def _get_go_entities(self, term: str) -> List[GOEntity]:
        """Get Gene Ontology entities via OLS API"""
        entities = []

        try:
            url = f"{self.OLS_API}/search"
            params = {
                "q": term,
                "ontology": "go",
                "rows": 5,
                "fieldList": "obo_id,label,ontology_name,description,short_form"
            }

            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            for item in data.get("response", {}).get("docs", []):
                go_id = item.get("short_form", "")
                label = item.get("label", "")
                description = item.get("description", [""])[0] if item.get("description") else ""

                # Determine GO category (BP, MF, CC) from ID or description
                category = "BP"  # Default
                if "molecular_function" in description.lower():
                    category = "MF"
                elif "cellular_component" in description.lower():
                    category = "CC"

                entity = GOEntity(
                    go_id=go_id,
                    term=label,
                    category=category,
                    score=1.0,  # Exact match
                    definition=description[:200],
                    synonyms=[]
                )
                entities.append(entity)

        except Exception as e:
            logger.warning(f"GO linking failed for '{term}': {e}")

        return entities

    def _get_chebi_entities(self, term: str) -> List[CHEBIEntity]:
        """Get ChEBI chemical entities via EBI API"""
        entities = []

        try:
            url = f"{self.CHEBI_API}/search"
            params = {
                "query": term,
                "limit": 5,
                "searchCategories": "ALL"
            }

            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()

            # Parse CHEBI response (note: CHEBI API returns XML by default)
            if response.headers.get('content-type', '').startswith('application/json'):
                data = response.json()
                for item in data.get("searchResults", {}).get("results", []):
                    chebi_id = item.get("chebiId", "")
                    entity = CHEBIEntity(
                        chebi_id=chebi_id,
                        name=item.get("chebiAsciiName", ""),
                        score=1.0,
                        formula=item.get("formulae", [""])[0] if item.get("formulae") else None,
                        definition=item.get("definition", "")[:200] if item.get("definition") else None,
                        synonyms=item.get("synonyms", [])[:5] if item.get("synonyms") else []
                    )
                    entities.append(entity)

        except Exception as e:
            logger.warning(f"ChEBI linking failed for '{term}': {e}")

        return entities

    def _get_drugbank_entities(self, term: str) -> List[DrugBankEntity]:
        """Get DrugBank drug entities (requires API key)"""
        entities = []

        # Note: DrugBank API requires authentication
        # This is a placeholder implementation
        try:
            # Would implement DrugBank API call here
            # For now, return empty list
            pass
        except Exception as e:
            logger.warning(f"DrugBank linking failed for '{term}': {e}")

        return entities

    def _get_snomed_entities(self, term: str) -> List[EntityMapping]:
        """Get SNOMED CT entities via BioPortal"""
        return self._get_bioportal_entities(term, "SNOMEDCT")

    def _get_mondo_entities(self, term: str) -> List[EntityMapping]:
        """Get Mondo disease ontology entities"""
        return self._get_bioportal_entities(term, "MONDO")

    def _get_doid_entities(self, term: str) -> List[EntityMapping]:
        """Get Human Disease Ontology entities"""
        return self._get_bioportal_entities(term, "DOID")

    def _get_hp_entities(self, term: str) -> List[EntityMapping]:
        """Get HPO entities (alternative method)"""
        return self._get_bioportal_entities(term, "HP")

    def _get_efo_entities(self, term: str) -> List[EntityMapping]:
        """Get Experimental Factor Ontology entities"""
        return self._get_bioportal_entities(term, "EFO")

    def _get_ncit_entities(self, term: str) -> List[EntityMapping]:
        """Get NCI Thesaurus entities"""
        return self._get_bioportal_entities(term, "NCIT")

    def _get_bioportal_entities(self, term: str, ontology: str) -> List[EntityMapping]:
        """Generic method to get entities from BioPortal ontologies"""
        entities = []

        if not self.bioportal_config.enabled or not self.bioportal_config.api_key:
            return entities

        try:
            url = f"{self.BIOportal_API}/search"
            params = {
                "q": term,
                "apikey": self.bioportal_config.api_key,
                "ontologies": ontology,
                "require_exact_match": "true",
                "pagesize": 3
            }

            response = requests.get(url, params=params, timeout=self.bioportal_config.timeout)
            response.raise_for_status()
            data = response.json()

            for item in data.get("collection", []):
                entity = EntityMapping(
                    entity_id=item.get("@id", "").split("/")[-1],
                    entity_name=item.get("prefLabel", ""),
                    knowledge_base=ontology,
                    score=1.0,
                    entity_type=item.get("@type", ""),
                    definition=item.get("definition", [""])[0] if item.get("definition") else None,
                    synonyms=item.get("synonym", [])[:5] if item.get("synonym") else [],
                    source="BioPortal"
                )
                entities.append(entity)

        except Exception as e:
            logger.warning(f"BioPortal {ontology} linking failed for '{term}': {e}")

        return entities

    def _parallel_ontology_mapping(self, term: str, ontology_map: Dict[str, callable]) -> Dict[str, List]:
        """Execute ontology mapping in parallel"""
        results = {}

        with ThreadPoolExecutor(max_workers=3) as executor:
            future_to_ontology = {
                executor.submit(mapping_func, term): ontology
                for ontology, mapping_func in ontology_map.items()
            }

            for future in as_completed(future_to_ontology):
                ontology = future_to_ontology[future]
                try:
                    results[ontology] = future.result()
                except Exception as e:
                    logger.warning(f"Error in {ontology} mapping: {e}")
                    results[ontology] = []

        return results

    def link_entities_comprehensive(self, terms: List[str]) -> Dict[str, ComprehensiveEntityResult]:
        """
        Perform comprehensive entity linking across all supported knowledge bases
        """
        logger.info(f"Starting comprehensive entity linking for {len(terms)} terms...")

        results = {}

        # Primary biomedical ontologies
        primary_ontologies = {
            "UMLS": self._get_umls_entities,
            "HPO": self._get_hpo_entities,
            "GO": self._get_go_entities,
            "CHEBI": self._get_chebi_entities,
        }

        # Secondary ontologies via BioPortal
        secondary_ontologies = {
            "SNOMEDCT": self._get_snomed_entities,
            "MONDO": self._get_mondo_entities,
            "DOID": self._get_doid_entities,
            "HP": self._get_hp_entities,
            "EFO": self._get_efo_entities,
            "NCIT": self._get_ncit_entities,
        }

        for term in tqdm(terms, desc="Entity Linking"):
            # Get primary ontology mappings
            primary_results = self._parallel_ontology_mapping(term, primary_ontologies)

            # Get secondary ontology mappings
            secondary_results = self._parallel_ontology_mapping(term, secondary_ontologies)

            # Create comprehensive result
            result = ComprehensiveEntityResult(
                term=term,
                umls_entities=primary_results.get("UMLS", []),
                hpo_entities=primary_results.get("HPO", []),
                go_entities=primary_results.get("GO", []),
                chebi_entities=primary_results.get("CHEBI", []),
                drugbank_entities=[],  # Placeholder
                other_ontologies=secondary_results
            )

            results[term] = result

        logger.info("Comprehensive entity linking completed")
        return results

    def get_best_entity_matches(self, term: str, top_k: int = 3) -> List[EntityMapping]:
        """
        Get the best entity matches across all knowledge bases for a term
        """
        all_entities = []

        # Get mappings from all knowledge bases
        for ontology, mapping_func in self.supported_ontologies.items():
            try:
                entities = mapping_func(term)

                # Convert to EntityMapping format
                for entity in entities:
                    if isinstance(entity, EntityMapping):
                        all_entities.append(entity)
                    else:
                        # Convert other entity types to EntityMapping
                        mapping = EntityMapping(
                            entity_id=getattr(entity, 'cui', getattr(entity, 'hpo_id', getattr(entity, 'go_id', getattr(entity, 'chebi_id', '')))),
                            entity_name=getattr(entity, 'name', getattr(entity, 'term', getattr(entity, 'chebi_id', ''))),
                            knowledge_base=ontology,
                            score=getattr(entity, 'score', 0.0),
                            entity_type=getattr(entity, 'tui', getattr(entity, 'category', None)),
                            definition=getattr(entity, 'definition', None),
                            synonyms=getattr(entity, 'synonyms', []),
                            source="entity_linker"
                        )
                        all_entities.append(mapping)

            except Exception as e:
                logger.warning(f"Error getting {ontology} entities for '{term}': {e}")

        # Sort by score and return top matches
        all_entities.sort(key=lambda x: x.score, reverse=True)
        return all_entities[:top_k]

    def add_custom_linker(self, name: str, linker_func: callable):
        """Add a custom entity linker function"""
        self.supported_ontologies[name] = linker_func
        logger.info(f"Added custom linker: {name}")

    def get_supported_ontologies(self) -> List[str]:
        """Get list of supported ontologies"""
        return list(self.supported_ontologies.keys())


def create_comprehensive_entity_linker(umls_config: UMLSConfig, bioportal_config: BioPortalConfig) -> ComprehensiveEntityLinker:
    """Factory function to create comprehensive entity linker"""
    return ComprehensiveEntityLinker(umls_config, bioportal_config)