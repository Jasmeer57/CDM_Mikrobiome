"""
UMLS mapping module incorporating SciSpacy linking and BioPortal/OLS/NCBO integration.
Based on reference umls.py functionality.
"""

import logging
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import requests
import spacy

# Optional scispacy imports
try:
    from scispacy.linking import EntityLinker
    SCISPACY_AVAILABLE = True
except ImportError:
    EntityLinker = None
    SCISPACY_AVAILABLE = False

from src.config.settings import UMLSConfig, BioPortalConfig

logger = logging.getLogger(__name__)


@dataclass
class UMLSMapping:
    """UMLS mapping result"""
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
class BioPortalMapping:
    """BioPortal mapping result"""
    id: str
    label: str
    ontology: str
    description: Optional[str] = None
    synonyms: List[str] = None

    def __post_init__(self):
        if self.synonyms is None:
            self.synonyms = []


@dataclass
class OLSMapping:
    """OLS (Ontology Lookup Service) mapping result"""
    id: str
    label: str
    ontology: str
    iri: str
    description: Optional[str] = None


@dataclass
class NCBOMapping:
    """NCBO Annotator mapping result"""
    id: str
    label: str
    ontology: str
    score: float
    context: Optional[str] = None


@dataclass
class MappingResult:
    """Complete mapping result for a term"""
    term: str
    umls_exact: List[UMLSMapping]
    umls_others: List[UMLSMapping]
    bioportal_exact: List[BioPortalMapping]
    bioportal_others: List[BioPortalMapping]
    ols_exact: List[OLSMapping]
    ols_others: List[OLSMapping]
    ncbo_exact: List[NCBOMapping]
    ncbo_others: List[NCBOMapping]

    def __post_init__(self):
        for field_name in [
            'umls_exact', 'umls_others', 'bioportal_exact', 'bioportal_others',
            'ols_exact', 'ols_others', 'ncbo_exact', 'ncbo_others'
        ]:
            if getattr(self, field_name) is None:
                setattr(self, field_name, [])

    def to_dict(self):
        """Convert MappingResult to dictionary for JSON serialization"""
        return {
            "term": self.term,
            "umls_exact": [self._serialize_mapping(mapping) for mapping in self.umls_exact],
            "umls_others": [self._serialize_mapping(mapping) for mapping in self.umls_others],
            "bioportal_exact": [self._serialize_mapping(mapping) for mapping in self.bioportal_exact],
            "bioportal_others": [self._serialize_mapping(mapping) for mapping in self.bioportal_others],
            "ols_exact": [self._serialize_mapping(mapping) for mapping in self.ols_exact],
            "ols_others": [self._serialize_mapping(mapping) for mapping in self.ols_others],
            "ncbo_exact": [self._serialize_mapping(mapping) for mapping in self.ncbo_exact],
            "ncbo_others": [self._serialize_mapping(mapping) for mapping in self.ncbo_others]
        }

    def _serialize_mapping(self, mapping):
        """Helper method to serialize mapping objects"""
        if hasattr(mapping, '__dict__'):
            return {k: v for k, v in mapping.__dict__.items() if not k.startswith('_')}
        return str(mapping)


class UMLSMapper:
    """Comprehensive UMLS and ontology mapping"""

    # API endpoints
    BIOPORTAL_SEARCH_URL = "https://data.bioontology.org/search"
    OLS_SEARCH_URL = "https://www.ebi.ac.uk/ols/api/search"
    NCBO_ANNOTATOR_URL = "https://data.bioontology.org/annotator"

    def __init__(self, umls_config: UMLSConfig, bioportal_config: BioPortalConfig):
        self.umls_config = umls_config
        self.bioportal_config = bioportal_config
        self.nlp = None
        self.linker = None

    def _initialize_scispacy(self):
        """Initialize SciSpacy model with UMLS linker"""
        if not self.umls_config.enabled:
            logger.info("UMLS mapping disabled")
            return

        if not SCISPACY_AVAILABLE:
            logger.warning("SciSpacy not available - UMLS mapping disabled")
            return

        try:
            logger.info("Loading SciSpacy model with UMLS linker...")
            self.nlp = spacy.load("en_core_sci_lg")

            if "scispacy_linker" not in self.nlp.pipe_names:
                self.nlp.add_pipe(
                    "scispacy_linker",
                    config={"resolve_abbreviations": True, "linker_name": "umls"}
                )

            self.linker = self.nlp.get_pipe("scispacy_linker")
            logger.info("SciSpacy UMLS linker initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize SciSpacy UMLS linker: {e}")
            self.umls_config.enabled = False

    def map_to_umls_scispacy(self, terms: List[str]) -> Dict[str, Dict[str, List[UMLSMapping]]]:
        """Map terms to UMLS using SciSpacy"""
        if not self.umls_config.enabled or not self.nlp or not SCISPACY_AVAILABLE:
            logger.warning("UMLS mapping disabled or SciSpacy not available")
            return {term: {"exact": [], "others": []} for term in terms}

        if not self.linker:
            self._initialize_scispacy()

        if not self.linker:  # Still not available after initialization
            return {term: {"exact": [], "others": []} for term in terms}

        results = {}
        kb = self.linker.kb

        logger.info(f"Mapping {len(terms)} terms to UMLS via SciSpacy...")

        for doc, term in tqdm(
            zip(self.nlp.pipe(terms, batch_size=self.umls_config.batch_size), terms),
            total=len(terms),
            desc="UMLS SciSpacy Mapping"
        ):
            exact_matches = []
            fuzzy_matches = []

            # Get all entity links
            for ent in doc.ents:
                if hasattr(ent, '_') and hasattr(ent._, 'kb_ents'):
                    for cui, score in ent._.kb_ents:
                        concept_entity = kb.cui_to_entity.get(cui)
                        if concept_entity:
                            mapping = UMLSMapping(
                                cui=cui,
                                name=concept_entity.canonical_name,
                                score=round(float(score), 4),
                                tui=concept_entity.tui,
                                definition=concept_entity.definition[:200] if concept_entity.definition else None,
                                synonyms=list(concept_entity.aliases)[:10] if concept_entity.aliases else []
                            )

                            if concept_entity.canonical_name.lower() == term.lower():
                                exact_matches.append(mapping)
                            else:
                                fuzzy_matches.append(mapping)

            # Sort by score
            exact_matches.sort(key=lambda x: x.score, reverse=True)
            fuzzy_matches.sort(key=lambda x: x.score, reverse=True)

            results[term] = {
                "exact": exact_matches[:5],  # Keep top 5 exact matches
                "others": fuzzy_matches[:10]  # Keep top 10 fuzzy matches
            }

        return results

    def map_to_bioportal(self, term: str) -> Dict[str, List[BioPortalMapping]]:
        """Map term to BioPortal ontologies"""
        if not self.bioportal_config.enabled or not self.bioportal_config.api_key:
            return {"exact": [], "others": []}

        params = {
            "q": term,
            "apikey": self.bioportal_config.api_key,
            "ontologies": ",".join(self.bioportal_config.ontologies),
            "require_exact_match": "true",
            "pagesize": self.bioportal_config.max_results
        }

        try:
            response = requests.get(
                self.BIOPORTAL_SEARCH_URL,
                params=params,
                timeout=self.bioportal_config.timeout
            )
            response.raise_for_status()
            data = response.json()

            exact_matches = []
            other_matches = []

            for item in data.get("collection", []):
                label = item.get("prefLabel", "")
                mapping = BioPortalMapping(
                    id=item.get("@id", "").split("/")[-1],
                    ontology=item.get("links", {}).get("ontology", "").split("/")[-1],
                    label=label,
                    description=item.get("definition", [])[:1][0] if item.get("definition") else None,
                    synonyms=item.get("synonym", [])[:5] if item.get("synonym") else []
                )

                if label.lower() == term.lower():
                    exact_matches.append(mapping)
                else:
                    other_matches.append(mapping)

            return {"exact": exact_matches, "others": other_matches[:5]}

        except requests.RequestException as e:
            logger.warning(f"BioPortal API error for '{term}': {e}")
            return {"exact": [], "others": []}

    def map_to_ols(self, term: str) -> Dict[str, List[OLSMapping]]:
        """Map term to OLS (Ontology Lookup Service)"""
        params = {
            "q": term,
            "rows": self.bioportal_config.max_results,
            "fieldList": "obo_id,label,ontology_name,iri,description"
        }

        try:
            response = requests.get(
                self.OLS_SEARCH_URL,
                params=params,
                timeout=self.bioportal_config.timeout
            )
            response.raise_for_status()
            data = response.json()

            exact_matches = []
            other_matches = []

            for item in data.get("response", {}).get("docs", []):
                label = item.get("label", "")
                identifier = (item.get("obo_id") or item.get("iri", "")).split("/")[-1].replace("_", ":")

                mapping = OLSMapping(
                    id=identifier,
                    label=label,
                    ontology=item.get("ontology_name"),
                    iri=item.get("iri", ""),
                    description=item.get("description", "")[:200] if item.get("description") else None
                )

                if label.lower() == term.lower():
                    exact_matches.append(mapping)
                else:
                    other_matches.append(mapping)

            return {"exact": exact_matches, "others": other_matches[:5]}

        except requests.RequestException as e:
            logger.warning(f"OLS API error for '{term}': {e}")
            return {"exact": [], "others": []}

    def map_to_ncbo(self, term: str) -> Dict[str, List[NCBOMapping]]:
        """Map term using NCBO Annotator"""
        if not self.bioportal_config.enabled or not self.bioportal_config.api_key:
            return {"exact": [], "others": []}

        params = {
            "text": term,
            "longest_only": "true",
            "apikey": self.bioportal_config.api_key,
            "ontologies": ",".join(self.bioportal_config.ontologies),
            "max_hits": self.bioportal_config.max_results
        }

        try:
            response = requests.get(
                self.NCBO_ANNOTATOR_URL,
                params=params,
                timeout=self.bioportal_config.timeout
            )
            response.raise_for_status()
            data = response.json()

            exact_matches = []
            other_matches = []

            for annotation in data[:self.bioportal_config.max_results]:
                annotated_class = annotation.get("annotatedClass", {})
                label = annotated_class.get("prefLabel", "")
                ontology = annotated_class.get("links", {}).get("ontology", "").split("/")[-1] if "links" in annotated_class else None

                mapping = NCBOMapping(
                    id=annotated_class.get("@id", "").split("/")[-1],
                    ontology=ontology,
                    label=label,
                    score=annotation.get("score", 0.0),
                    context=annotation.get("text", "")[:100]
                )

                if label.lower() == term.lower():
                    exact_matches.append(mapping)
                else:
                    other_matches.append(mapping)

            return {"exact": exact_matches, "others": other_matches[:5]}

        except requests.RequestException as e:
            logger.warning(f"NCBO Annotator error for '{term}': {e}")
            return {"exact": [], "others": []}

    def _parallel_api_mapping(self, terms: List[str], map_function, max_workers: int = 5, sleep_time: float = 0.1) -> Dict[str, Any]:
        """Execute API mapping in parallel"""
        results = {}

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_term = {
                executor.submit(map_function, term): term for term in terms
            }

            for future in tqdm(as_completed(future_to_term), total=len(terms), desc=f"API Mapping ({map_function.__name__})"):
                term = future_to_term[future]
                try:
                    results[term] = future.result()
                except Exception as e:
                    logger.warning(f"Error mapping '{term}' via {map_function.__name__}: {e}")
                    results[term] = {"exact": [], "others": []}

                time.sleep(sleep_time)

        return results

    def map_terms_comprehensive(self, terms: List[str]) -> Dict[str, MappingResult]:
        """Perform comprehensive mapping using all available sources"""
        logger.info(f"Starting comprehensive UMLS/ontology mapping for {len(terms)} terms...")

        results = {}

        # SciSpacy UMLS mapping
        umls_results = self.map_to_umls_scispacy(terms)

        # API mappings (parallelized)
        bioportal_results = self._parallel_api_mapping(
            terms, self.map_to_bioportal,
            max_workers=5, sleep_time=0.5
        )

        ols_results = self._parallel_api_mapping(
            terms, self.map_to_ols,
            max_workers=10, sleep_time=0.05
        )

        ncbo_results = self._parallel_api_mapping(
            terms, self.map_to_ncbo,
            max_workers=3, sleep_time=1.0
        )

        # Combine results
        for term in terms:
            results[term] = MappingResult(
                term=term,
                umls_exact=[UMLSMapping(**m.__dict__) for m in umls_results.get(term, {}).get("exact", [])],
                umls_others=[UMLSMapping(**m.__dict__) for m in umls_results.get(term, {}).get("others", [])],
                bioportal_exact=[BioPortalMapping(**m.__dict__) for m in bioportal_results.get(term, {}).get("exact", [])],
                bioportal_others=[BioPortalMapping(**m.__dict__) for m in bioportal_results.get(term, {}).get("others", [])],
                ols_exact=[OLSMapping(**m.__dict__) for m in ols_results.get(term, {}).get("exact", [])],
                ols_others=[OLSMapping(**m.__dict__) for m in ols_results.get(term, {}).get("others", [])],
                ncbo_exact=[NCBOMapping(**m.__dict__) for m in ncbo_results.get(term, {}).get("exact", [])],
                ncbo_others=[NCBOMapping(**m.__dict__) for m in ncbo_results.get(term, {}).get("others", [])]
            )

        logger.info("Comprehensive mapping completed")
        return results

    def get_best_umls_match(self, term: str) -> Optional[UMLSMapping]:
        """Get the best UMLS match for a term"""
        umls_results = self.map_to_umls_scispacy([term])
        term_mappings = umls_results.get(term, {})

        exact_matches = term_mappings.get("exact", [])
        if exact_matches:
            return exact_matches[0]

        other_matches = term_mappings.get("others", [])
        if other_matches and other_matches[0].score > 0.7:  # Threshold for fuzzy match
            return other_matches[0]

        return None


def create_umls_mapper(umls_config: UMLSConfig, bioportal_config: BioPortalConfig) -> UMLSMapper:
    """Factory function to create UMLS mapper"""
    return UMLSMapper(umls_config, bioportal_config)