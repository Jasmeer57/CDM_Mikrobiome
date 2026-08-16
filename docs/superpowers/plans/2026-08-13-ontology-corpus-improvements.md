# Ontology + Corpus Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prioritize domain-specific ontologies (ENVO/OHMI/ChEBI/NCBITaxon/etc.) in the existing OLS/BioPortal mapping layer, fail loud instead of silently degrading when the OMOP vocab is missing, add a ChEBI hierarchy builder and an NCBI Taxonomy name-lookup fallback, and fix + rebuild the dormant FAISS corpus semantic index.

**Architecture:** All five pieces are additive/corrective changes to existing modules (`llm_terms/config`, `llm_terms/mappers`, `llm_terms/scripts`, `papers_txt/others`) — no new subsystems, no changes to `standalone_pipeline.py` / `standalone_scispacy_pipeline.py`, no `git push`.

**Tech Stack:** Python 3 stdlib + `requests`, `biopython` (Entrez), `pandas`/`rapidfuzz` (already used by OMOP mapper), `sentence-transformers` + `faiss-cpu` (Task 10 only). Test framework: `unittest` (matches existing `llm_terms/tests/*.py` convention), run via `python -m unittest`.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-13-ontology-corpus-improvements-design.md` — every task below implements one numbered component from that spec; re-read it if a task's rationale is unclear.
- Do not modify `llm_terms/scripts/standalone_pipeline.py` or `spacy_terms/standalone_scispacy_pipeline.py` — user's active dev/test scripts, explicitly out of scope.
- Do not run `git push` at any point — all commits stay local until the user says otherwise.
- All new/changed code must keep working if optional dependencies (`requests`, `biopython`, `sentence-transformers`, `faiss`) are absent — match the existing repo convention of `try/except ImportError` + a `*_AVAILABLE` flag (see `extract_taxonomic_hierarchy.py:25-29` for the pattern).
- All commits are local `git commit` only, made from the repo root (`C:\Users\jkalra\Documents\Microbiome-CDM`), one commit per task.

---

### Task 1: Environment setup — install missing test dependencies

**Files:**
- None created/modified — sandbox environment only.

**Interfaces:**
- Produces: a working `python -m unittest` run for the existing `llm_terms/tests/test_core.py`, which every later task's tests depend on being importable (`core.llm_client` imports `requests` at module load time).

- [ ] **Step 1: Confirm the current baseline failure**

Run (from repo root):
```bash
cd llm_terms && python -m unittest tests.test_core -v
```
Expected: `ModuleNotFoundError: No module named 'requests'` (confirms the gap before fixing it).

- [ ] **Step 2: Install `requests` and `biopython`**

Run:
```bash
python -m pip install requests biopython
```
Expected: both install successfully (pure-Python-ish, no heavy compiled deps).

- [ ] **Step 3: Re-run the baseline test to confirm it now passes**

Run:
```bash
cd llm_terms && python -m unittest tests.test_core -v
```
Expected: `OK` (all existing tests in `test_core.py` pass — this is a pre-existing suite, not one we're writing, so a failure here means an environment problem, not a code problem: stop and diagnose before continuing to Task 2).

- [ ] **Step 4: Commit**

Nothing to commit — this task only installs sandbox packages, no repo files changed. Skip straight to Task 2.

---

### Task 2: Ontology-source preference config

**Files:**
- Modify: `llm_terms/config/cdm_config.py:126` (insert after the `ENTITY_TYPES` dict closes, before the `# Chunking strategies` comment)
- Test: `llm_terms/tests/test_cdm_config.py` (create)

**Interfaces:**
- Produces: `CDMEntityConfig.ENTITY_TYPE_ONTOLOGY_MAP: Dict[str, List[str]]` — entity type name → list of lowercase preferred ontology acronyms. Consumed by Task 5 (`ComprehensiveMapper`).

- [ ] **Step 1: Write the failing test**

Create `llm_terms/tests/test_cdm_config.py`:
```python
import unittest
from config.cdm_config import CDMEntityConfig


class TestEntityTypeOntologyMap(unittest.TestCase):
    def test_map_exists_and_is_dict(self):
        self.assertTrue(hasattr(CDMEntityConfig, 'ENTITY_TYPE_ONTOLOGY_MAP'))
        self.assertIsInstance(CDMEntityConfig.ENTITY_TYPE_ONTOLOGY_MAP, dict)

    def test_all_keys_are_known_entity_types(self):
        known_types = set(CDMEntityConfig.ENTITY_TYPES.keys())
        for entity_type in CDMEntityConfig.ENTITY_TYPE_ONTOLOGY_MAP:
            self.assertIn(entity_type, known_types)

    def test_organism_prefers_ncbitaxon_and_ohmi(self):
        self.assertEqual(
            CDMEntityConfig.ENTITY_TYPE_ONTOLOGY_MAP['ORGANISM'],
            ['ncbitaxon', 'ohmi']
        )

    def test_chemical_prefers_chebi(self):
        self.assertEqual(
            CDMEntityConfig.ENTITY_TYPE_ONTOLOGY_MAP['CHEMICAL'],
            ['chebi']
        )

    def test_values_are_lowercase_acronym_lists(self):
        for entity_type, acronyms in CDMEntityConfig.ENTITY_TYPE_ONTOLOGY_MAP.items():
            self.assertIsInstance(acronyms, list)
            for acronym in acronyms:
                self.assertEqual(acronym, acronym.lower())


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd llm_terms && python -m unittest tests.test_cdm_config -v
```
Expected: FAIL with `AttributeError` / `AssertionError` — `ENTITY_TYPE_ONTOLOGY_MAP` doesn't exist yet.

- [ ] **Step 3: Add the config**

In `llm_terms/config/cdm_config.py`, insert immediately after line 126 (the `}` that closes `ENTITY_TYPES`, before the `# Chunking strategies` comment):
```python

    # Preferred ontology sources per entity type, used by OLSMapper and
    # BioPortalMapper to restrict/boost search results toward domain-precise
    # ontologies instead of generic ones (MeSH, SNOMED) at equal text match.
    # Acronyms are OLS-style lowercase; BioPortalMapper upper-cases them itself.
    ENTITY_TYPE_ONTOLOGY_MAP = {
        'ORGANISM': ['ncbitaxon', 'ohmi'],
        'CHEMICAL': ['chebi'],
        'DISEASE': ['doid', 'mondo'],
        'PATHWAY': ['go'],
        'CELL_TYPE': ['cl'],
        'DNA_RNA': ['so'],
        'SAMPLE_METHOD': ['obi', 'envo'],
        'LAB_METHOD': ['obi', 'envo'],
        'GENOMICS': ['edam'],
        'EXPERIMENTAL_METHOD': ['edam'],
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
cd llm_terms && python -m unittest tests.test_cdm_config -v
```
Expected: `OK` (5 tests pass).

- [ ] **Step 5: Commit**

```bash
cd "C:\Users\jkalra\Documents\Microbiome-CDM"
git add llm_terms/config/cdm_config.py llm_terms/tests/test_cdm_config.py
git commit -m "feat: add per-entity-type ontology preference map

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: OLSMapper — ontology filter + confidence boost

**Files:**
- Modify: `llm_terms/mappers/ols_mapper.py`
- Test: `llm_terms/tests/test_mappers.py` (create)

**Interfaces:**
- Consumes: nothing new from earlier tasks (works standalone; Task 5 wires `ENTITY_TYPE_ONTOLOGY_MAP` into the call site).
- Produces: `OLSMapper.map_entity(entity_name: str, entity_type: str, preferred_ontologies: Optional[List[str]] = None) -> List[OLSMapping]` — new optional third parameter, backward compatible (`None` = today's unrestricted-search behavior).

- [ ] **Step 1: Write the failing tests**

Create `llm_terms/tests/test_mappers.py`:
```python
import unittest
from unittest.mock import MagicMock, patch

from mappers.ols_mapper import OLSMapper


class TestOLSMapperOntologyFilter(unittest.TestCase):
    def setUp(self):
        self.mapper = OLSMapper()

    @patch('mappers.ols_mapper.requests.get')
    def test_no_preferred_ontologies_omits_filter_param(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'response': {'docs': []}}
        mock_get.return_value = mock_response

        self.mapper.map_entity('Bacteroides fragilis', 'ORGANISM')

        called_params = mock_get.call_args.kwargs['params']
        self.assertNotIn('ontology', called_params)

    @patch('mappers.ols_mapper.requests.get')
    def test_preferred_ontologies_added_as_filter_param(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'response': {'docs': []}}
        mock_get.return_value = mock_response

        self.mapper.map_entity(
            'Bacteroides fragilis', 'ORGANISM',
            preferred_ontologies=['ncbitaxon', 'ohmi']
        )

        called_params = mock_get.call_args.kwargs['params']
        self.assertEqual(called_params['ontology'], 'ncbitaxon,ohmi')

    @patch('mappers.ols_mapper.requests.get')
    def test_confidence_boost_for_preferred_ontology_hit(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'response': {'docs': [
                {'iri': 'http://purl.obolibrary.org/obo/NCBITaxon_817',
                 'ontology_name': 'ncbitaxon', 'label': 'Bacteroides fragilis'},
                {'iri': 'http://purl.bioontology.org/ontology/MESH/D001421',
                 'ontology_name': 'mesh', 'label': 'Bacteroides fragilis'},
            ]}
        }
        mock_get.return_value = mock_response

        results = self.mapper.map_entity(
            'Bacteroides fragilis', 'ORGANISM',
            preferred_ontologies=['ncbitaxon', 'ohmi']
        )

        self.assertEqual(len(results), 2)
        # Both have identical label match (confidence 0.9 pre-boost); the
        # ncbitaxon result must rank first due to the preferred-ontology boost.
        self.assertEqual(results[0].ontology_name, 'ncbitaxon')
        self.assertGreater(results[0].mapping_confidence, results[1].mapping_confidence)


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd llm_terms && python -m unittest tests.test_mappers -v
```
Expected: FAIL — `map_entity()` doesn't accept a `preferred_ontologies` keyword yet (`TypeError`), and `_calculate_confidence` has no boost logic.

- [ ] **Step 3: Implement the filter + boost**

Replace the full contents of `llm_terms/mappers/ols_mapper.py` with:
```python
"""
OLS Mapper Module
Maps entities using EBI OLS API
"""

import logging
import requests
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

@dataclass
class OLSMapping:
    """OLS mapping result."""
    entity_name: str
    entity_type: str
    iri: str
    ontology_name: str
    label: str
    mapping_confidence: float
    mapping_method: str

    def to_dict(self) -> Dict:
        return asdict(self)

class OLSMapper:
    """Maps entities using EBI OLS API (Free)."""

    # Boost applied when a result's ontology_name is in the caller's
    # preferred set — enough to break ties against generic-ontology hits
    # with identical text-match confidence, without ever exceeding 1.0.
    PREFERRED_ONTOLOGY_BOOST = 0.15

    def __init__(self, cache_size: int = 1000):
        self.cache = {}
        self.cache_size = cache_size
        self.base_url = "https://www.ebi.ac.uk/ols/api/search"

    def map_entity(self, entity_name: str, entity_type: str,
                    preferred_ontologies: Optional[List[str]] = None) -> List[OLSMapping]:
        """Map entity using OLS API.

        Args:
            entity_name: The term to look up.
            entity_type: CDM entity type (used for cache keying only here).
            preferred_ontologies: Optional list of OLS ontology acronyms
                (lowercase, e.g. ['ncbitaxon', 'ohmi']). When given, OLS's
                native `ontology=` filter restricts the search to these
                ontologies, and any surviving unrestricted result matching
                one of them gets a confidence boost.
        """
        cache_key = f"{entity_name.lower()}_{entity_type}_{','.join(preferred_ontologies or [])}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        mappings = []
        try:
            params = {
                "q": entity_name,
                "rows": 5,
                "exact": "false"
            }
            if preferred_ontologies:
                params["ontology"] = ",".join(preferred_ontologies)

            response = requests.get(self.base_url, params=params, timeout=10)
            if response.status_code == 200:
                results = response.json().get('response', {}).get('docs', [])
                for result in results:
                    confidence = self._calculate_confidence(entity_name, result, preferred_ontologies)
                    if confidence > 0.4:
                        mappings.append(OLSMapping(
                            entity_name=entity_name,
                            entity_type=entity_type,
                            iri=result.get('iri', ''),
                            ontology_name=result.get('ontology_name', ''),
                            label=result.get('label', ''),
                            mapping_confidence=confidence,
                            mapping_method="OLS_API"
                        ))
            
            mappings.sort(key=lambda x: x.mapping_confidence, reverse=True)
            
        except Exception as e:
            logger.debug(f"OLS mapping failed for {entity_name}: {e}")

        if len(self.cache) < self.cache_size:
            self.cache[cache_key] = mappings
            
        return mappings

    def _calculate_confidence(self, entity_name: str, result: Dict,
                               preferred_ontologies: Optional[List[str]] = None) -> float:
        confidence = 0.5
        label = result.get('label', '').lower()
        if label == entity_name.lower():
            confidence += 0.4
        elif entity_name.lower() in label:
            confidence += 0.2
        if preferred_ontologies:
            ontology_name = (result.get('ontology_name') or '').lower()
            if ontology_name in [o.lower() for o in preferred_ontologies]:
                confidence += self.PREFERRED_ONTOLOGY_BOOST
        return min(confidence, 1.0)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd llm_terms && python -m unittest tests.test_mappers -v
```
Expected: `OK` (3 tests pass).

- [ ] **Step 5: Commit**

```bash
cd "C:\Users\jkalra\Documents\Microbiome-CDM"
git add llm_terms/mappers/ols_mapper.py llm_terms/tests/test_mappers.py
git commit -m "feat: add ontology-source filter + boost to OLSMapper

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: BioPortalMapper — ontology filter + confidence boost

**Files:**
- Modify: `llm_terms/mappers/bioportal_mapper.py`
- Test: `llm_terms/tests/test_mappers.py` (append)

**Interfaces:**
- Produces: `BioPortalMapper.map_entity(entity_name: str, entity_type: str, preferred_ontologies: Optional[List[str]] = None) -> List[BioPortalMapping]` — mirrors Task 3's OLS signature/behavior, using BioPortal's `ontologies=` param (comma-joined, uppercase acronyms) instead of OLS's `ontology=`.

- [ ] **Step 1: Write the failing tests**

Append to `llm_terms/tests/test_mappers.py` (add this import near the top, alongside the existing `OLSMapper` import):
```python
from mappers.bioportal_mapper import BioPortalMapper
```
Then add this class at the end of the file, before `if __name__ == '__main__':`:
```python
class TestBioPortalMapperOntologyFilter(unittest.TestCase):
    def setUp(self):
        self.mapper = BioPortalMapper(api_key='test-key')

    @patch('mappers.bioportal_mapper.requests.get')
    def test_no_preferred_ontologies_omits_filter_param(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'collection': []}
        mock_get.return_value = mock_response

        self.mapper.map_entity('Butyrate', 'CHEMICAL')

        called_params = mock_get.call_args.kwargs['params']
        self.assertNotIn('ontologies', called_params)

    @patch('mappers.bioportal_mapper.requests.get')
    def test_preferred_ontologies_added_as_filter_param_uppercase(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'collection': []}
        mock_get.return_value = mock_response

        self.mapper.map_entity('Butyrate', 'CHEMICAL', preferred_ontologies=['chebi'])

        called_params = mock_get.call_args.kwargs['params']
        self.assertEqual(called_params['ontologies'], 'CHEBI')

    @patch('mappers.bioportal_mapper.requests.get')
    def test_confidence_boost_for_preferred_ontology_hit(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'collection': [
                {'@id': 'http://purl.obolibrary.org/obo/CHEBI_17968',
                 'prefLabel': 'Butyrate',
                 'links': {'ontology': 'http://data.bioontology.org/ontologies/CHEBI'}},
                {'@id': 'http://purl.bioontology.org/ontology/MESH/D002104',
                 'prefLabel': 'Butyrate',
                 'links': {'ontology': 'http://data.bioontology.org/ontologies/MESH'}},
            ]
        }
        mock_get.return_value = mock_response

        results = self.mapper.map_entity('Butyrate', 'CHEMICAL', preferred_ontologies=['chebi'])

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].ontology_name, 'CHEBI')
        self.assertGreater(results[0].mapping_confidence, results[1].mapping_confidence)


if __name__ == '__main__':
    unittest.main()
```
(Remove the now-duplicate earlier `if __name__ == '__main__': unittest.main()` block left over from Task 3 so the file has exactly one at the end.)

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd llm_terms && python -m unittest tests.test_mappers -v
```
Expected: FAIL on the 3 new `TestBioPortalMapperOntologyFilter` tests (`TypeError` on the unexpected keyword).

- [ ] **Step 3: Implement the filter + boost**

Replace the full contents of `llm_terms/mappers/bioportal_mapper.py` with:
```python
import logging
import requests
from typing import List, Dict, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class BioPortalMapping:
    """Mapping result from BioPortal."""
    entity_name: str
    entity_type: str
    concept_id: str
    ontology_name: str
    mapping_confidence: float
    mapping_method: str = "BioPortal_API"
    
    def to_dict(self) -> Dict:
        return {
            "entity_name": self.entity_name,
            "entity_type": self.entity_type,
            "concept_id": self.concept_id,
            "ontology_name": self.ontology_name,
            "mapping_confidence": self.mapping_confidence,
            "mapping_method": self.mapping_method
        }

class BioPortalMapper:
    """Maps entities to BioPortal ontologies."""

    # Boost applied when a result's ontology matches the caller's preferred
    # set — mirrors OLSMapper.PREFERRED_ONTOLOGY_BOOST.
    PREFERRED_ONTOLOGY_BOOST = 0.15

    def __init__(self, api_key: str = None, cache_size: int = 1000):
        self.api_key = api_key
        self.cache = {}
        self.cache_size = cache_size
        self.base_url = "http://data.bioontology.org/search"

    def map_entity(self, entity_name: str, entity_type: str,
                    preferred_ontologies: Optional[List[str]] = None) -> List[BioPortalMapping]:
        """Map entity using BioPortal API.

        Args:
            entity_name: The term to look up.
            entity_type: CDM entity type (used for cache keying only here).
            preferred_ontologies: Optional list of ontology acronyms in any
                case (e.g. ['chebi']). When given, BioPortal's native
                `ontologies=` filter restricts the search (upper-cased, as
                BioPortal acronyms are conventionally upper-case), and any
                surviving result matching one of them gets a confidence boost.
        """
        if not self.api_key:
            return []
            
        cache_key = f"{entity_name.lower()}_{entity_type}_{','.join(preferred_ontologies or [])}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        mappings = []
        try:
            params = {
                "q": entity_name,
                "apikey": self.api_key,
                "pagesize": 5,
                "include": "prefLabel,cui,semanticType"
            }
            if preferred_ontologies:
                params["ontologies"] = ",".join(o.upper() for o in preferred_ontologies)
            
            response = requests.get(self.base_url, params=params, timeout=10)
            if response.status_code == 200:
                results = response.json().get('collection', [])
                for result in results:
                    confidence = self._calculate_confidence(entity_name, result, preferred_ontologies)
                    if confidence > 0.4:
                        mappings.append(BioPortalMapping(
                            entity_name=entity_name,
                            entity_type=entity_type,
                            concept_id=result.get('@id', ''),
                            ontology_name=result.get('links', {}).get('ontology', '').split('/')[-1],
                            mapping_confidence=confidence,
                            mapping_method="BioPortal_API"
                        ))
            else:
                 logger.warning(f"BioPortal API error: {response.status_code} - {response.text[:100]}")
            
            mappings.sort(key=lambda x: x.mapping_confidence, reverse=True)
            
        except Exception as e:
            logger.debug(f"BioPortal mapping failed for {entity_name}: {e}")

        if len(self.cache) < self.cache_size:
            self.cache[cache_key] = mappings
            
        return mappings

    def _calculate_confidence(self, entity_name: str, result: Dict,
                               preferred_ontologies: Optional[List[str]] = None) -> float:
        confidence = 0.5
        pref_label = result.get('prefLabel', '').lower()
        if pref_label == entity_name.lower():
            confidence += 0.4
        elif entity_name.lower() in pref_label:
            confidence += 0.2
        if preferred_ontologies:
            ontology_name = result.get('links', {}).get('ontology', '').split('/')[-1].upper()
            if ontology_name in [o.upper() for o in preferred_ontologies]:
                confidence += self.PREFERRED_ONTOLOGY_BOOST
        return min(confidence, 1.0)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd llm_terms && python -m unittest tests.test_mappers -v
```
Expected: `OK` (6 tests total: 3 from Task 3 + 3 from this task).

- [ ] **Step 5: Commit**

```bash
cd "C:\Users\jkalra\Documents\Microbiome-CDM"
git add llm_terms/mappers/bioportal_mapper.py llm_terms/tests/test_mappers.py
git commit -m "feat: add ontology-source filter + boost to BioPortalMapper

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 5: Wire ontology preferences into ComprehensiveMapper

**Files:**
- Modify: `llm_terms/mappers/mapping.py`
- Test: `llm_terms/tests/test_mappers.py` (append)

**Interfaces:**
- Consumes: `CDMEntityConfig.ENTITY_TYPE_ONTOLOGY_MAP` (Task 2), `OLSMapper.map_entity(..., preferred_ontologies=...)` (Task 3), `BioPortalMapper.map_entity(..., preferred_ontologies=...)` (Task 4).
- Produces: `ComprehensiveMapper.map_entity_comprehensive` now passes the entity type's preferred ontologies through to both mappers automatically — no signature change to `map_entity_comprehensive` itself.

- [ ] **Step 1: Write the failing test**

Add this import near the top of `llm_terms/tests/test_mappers.py`:
```python
from mappers.mapping import ComprehensiveMapper
```
Add this class before the final `if __name__ == '__main__':` block:
```python
class TestComprehensiveMapperOntologyWiring(unittest.TestCase):
    @patch('mappers.mapping.OMOPLocalMapper')
    @patch('mappers.mapping.OMOPMapper')
    def setUp(self, MockOMOPMapper, MockOMOPLocalMapper):
        self.mapper = ComprehensiveMapper(use_local_omop=False)
        self.mapper.omop_mapper = MockOMOPMapper.return_value
        self.mapper.umls_mapper = None
        self.mapper.bioportal_mapper = MagicMock()
        self.mapper.ols_mapper = MagicMock()
        self.mapper.ols_mapper.map_entity.return_value = []
        self.mapper.bioportal_mapper.map_entity.return_value = []
        self.mapper.omop_mapper.map_entity_to_omop.return_value = []

    def test_organism_passes_ncbitaxon_and_ohmi_to_ols_and_bioportal(self):
        self.mapper.map_entity_comprehensive("Bacteroides fragilis", "ORGANISM")

        self.mapper.ols_mapper.map_entity.assert_called_once_with(
            "Bacteroides fragilis", "ORGANISM", preferred_ontologies=['ncbitaxon', 'ohmi']
        )
        self.mapper.bioportal_mapper.map_entity.assert_called_once_with(
            "Bacteroides fragilis", "ORGANISM", preferred_ontologies=['ncbitaxon', 'ohmi']
        )

    def test_unmapped_entity_type_passes_none(self):
        self.mapper.map_entity_comprehensive("some term", "UNKNOWN_TYPE")

        self.mapper.ols_mapper.map_entity.assert_called_once_with(
            "some term", "UNKNOWN_TYPE", preferred_ontologies=None
        )


if __name__ == '__main__':
    unittest.main()
```
(Again, remove the now-duplicate `if __name__ == '__main__':` block left over from Task 4.)

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd llm_terms && python -m unittest tests.test_mappers -v
```
Expected: FAIL — `map_entity.assert_called_once_with(...)` mismatch, since `map_entity_comprehensive` doesn't pass `preferred_ontologies` yet.

- [ ] **Step 3: Wire the config through**

In `llm_terms/mappers/mapping.py`, add the import at the top (after the existing imports, before `logger = logging.getLogger(__name__)`):
```python
from config.cdm_config import CDMEntityConfig
```

Then replace the `map_entity_comprehensive` method's BioPortal and OLS blocks:
```python
    def map_entity_comprehensive(self, term: str, entity_type: str) -> Dict:
        """Map a single entity using all available mappers."""
        results = {
            'term': term,
            'entity_type': entity_type,
            'bioportal_mappings': [],
            'ols_mappings': [],
            'umls_mappings': [],
            'omop_mappings': [],
            'has_any_mapping': False
        }

        preferred_ontologies = CDMEntityConfig.ENTITY_TYPE_ONTOLOGY_MAP.get(entity_type)

        # 1. BioPortal Mapping
        if self.bioportal_mapper:
            try:
                bp_results = self.bioportal_mapper.map_entity(
                    term, entity_type, preferred_ontologies=preferred_ontologies
                )
                if bp_results:
                    results['bioportal_mappings'] = [r.to_dict() for r in bp_results[:self.max_matches]]
                    results['has_any_mapping'] = True
            except Exception as e:
                logger.warning(f"BioPortal mapping failed for {term}: {e}")
                
        # 2. OLS Mapping
        if self.ols_mapper:
            try:
                ols_results = self.ols_mapper.map_entity(
                    term, entity_type, preferred_ontologies=preferred_ontologies
                )
                if ols_results:
                    results['ols_mappings'] = [r.to_dict() for r in ols_results[:self.max_matches]]
                    results['has_any_mapping'] = True
            except Exception as e:
                logger.warning(f"OLS mapping failed for {term}: {e}")
```
Leave the UMLS and OMOP blocks below it unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
cd llm_terms && python -m unittest tests.test_mappers -v
```
Expected: `OK` (8 tests total). Also re-run the full pre-existing suite to confirm no regression:
```bash
cd llm_terms && python -m unittest tests.test_core -v
```
Expected: `OK` (the mocked `TestComprehensiveMapper.test_map_entity_comprehensive` in `test_core.py` uses `MagicMock()` for `ols_mapper`/`bioportal_mapper`, so the new `preferred_ontologies` kwarg is accepted without complaint — mocks don't enforce signatures).

- [ ] **Step 5: Commit**

```bash
cd "C:\Users\jkalra\Documents\Microbiome-CDM"
git add llm_terms/mappers/mapping.py llm_terms/tests/test_mappers.py
git commit -m "feat: wire entity-type ontology preferences into ComprehensiveMapper

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 6: OMOP local vocab — fail loud + API fallback + docs

**Files:**
- Modify: `llm_terms/mappers/omop_local_mapper.py`
- Modify: `llm_terms/mappers/mapping.py`
- Modify: `llm_terms/README.md` (after line 11, end of the "📥 Download Large Files" section)
- Test: `llm_terms/tests/test_mappers.py` (append)

**Interfaces:**
- Produces: `OMOPLocalMapper.__init__` raises `FileNotFoundError` when `vocab_dir` is explicitly given but doesn't exist on disk (previously logged a `WARNING` and silently continued with empty lookup tables). `ComprehensiveMapper.__init__` catches that and falls back to the API-based `OMOPMapper()`.

- [ ] **Step 1: Write the failing tests**

Add this import near the top of `llm_terms/tests/test_mappers.py`:
```python
import tempfile
import os
from mappers.omop_local_mapper import OMOPLocalMapper
```
Add this class before the final `if __name__ == '__main__':` block:
```python
class TestOMOPLocalMapperFailsLoud(unittest.TestCase):
    def test_raises_on_missing_vocab_dir(self):
        missing_dir = os.path.join(tempfile.gettempdir(), 'definitely_does_not_exist_omop_vocab')
        self.assertFalse(os.path.exists(missing_dir))

        with self.assertRaises(FileNotFoundError):
            OMOPLocalMapper(vocab_dir=missing_dir)

    def test_error_message_names_the_path_and_athena(self):
        missing_dir = os.path.join(tempfile.gettempdir(), 'definitely_does_not_exist_omop_vocab')
        try:
            OMOPLocalMapper(vocab_dir=missing_dir)
            self.fail("Expected FileNotFoundError")
        except FileNotFoundError as e:
            self.assertIn(missing_dir, str(e))
            self.assertIn("athena.ohdsi.org", str(e))


class TestComprehensiveMapperOMOPFallback(unittest.TestCase):
    @patch('mappers.mapping.OMOPMapper')
    @patch('mappers.mapping.OMOPLocalMapper')
    def test_falls_back_to_api_mapper_when_vocab_dir_missing(self, MockOMOPLocalMapper, MockOMOPMapper):
        MockOMOPLocalMapper.side_effect = FileNotFoundError("vocab dir missing")
        mapper = ComprehensiveMapper(use_local_omop=True, omop_vocab_dir='/nonexistent/path')

        MockOMOPLocalMapper.assert_called_once()
        MockOMOPMapper.assert_called_once()
        self.assertIs(mapper.omop_mapper, MockOMOPMapper.return_value)


if __name__ == '__main__':
    unittest.main()
```
(Remove the leftover duplicate `if __name__ == '__main__':` from Task 5, as before.)

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd llm_terms && python -m unittest tests.test_mappers -v
```
Expected: FAIL — `test_raises_on_missing_vocab_dir` and `test_error_message_names_the_path_and_athena` fail because no exception is currently raised; `test_falls_back_to_api_mapper_when_vocab_dir_missing` fails because `ComprehensiveMapper.__init__` doesn't catch anything yet (it'll propagate the `FileNotFoundError` from the mock and error the test itself).

- [ ] **Step 3: Fix `OMOPLocalMapper.__init__`**

In `llm_terms/mappers/omop_local_mapper.py`, add `from pathlib import Path` to the imports at the top (this fixes a pre-existing latent bug — `Path` is used on line 54 but was never imported, so the `else` branch would have raised `NameError` the first time it executed):
```python
import os
import re
import logging
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union
from dataclasses import dataclass
from rapidfuzz import process, fuzz
import tempfile
import subprocess
```

Then replace the `__init__` method's path-resolution block:
```python
    def __init__(self, vocab_dir: str = None, fuzzy_threshold: int = 95, max_matches: int = 3):
        """
        Initialize the OMOP local mapper.

        Args:
            vocab_dir: Path to OMOP vocabulary directory
            fuzzy_threshold: Minimum fuzzy matching score (default: 95)
            max_matches: Maximum matches per entity (default: 3)

        Raises:
            FileNotFoundError: if vocab_dir is explicitly given but does not
                exist on disk. Callers that want the old silent-empty
                behavior should catch this and decide what to do (see
                ComprehensiveMapper, which falls back to the API-based
                OMOPMapper).
        """
        # Use project-relative path as default instead of user-specific path
        if vocab_dir:
            self.vocab_dir = vocab_dir
            if not os.path.exists(self.vocab_dir):
                raise FileNotFoundError(
                    f"OMOP vocabulary directory not found: {self.vocab_dir}\n\n"
                    "Download the OMOP Standardized Vocabularies from Athena "
                    "(https://athena.ohdsi.org/) and place CONCEPT.csv and "
                    "CONCEPT_SYNONYM.csv in this directory. See the "
                    "'OMOP Vocabulary Setup' section of llm_terms/README.md "
                    "for details."
                )
        else:
            # Default to data/omop_vocab relative to project root
            default_dir = Path(__file__).parent.parent.parent / 'data' / 'omop_vocab'
            self.vocab_dir = os.environ.get('OMOP_VOCAB_DIR', str(default_dir))

        self.fuzzy_threshold = fuzzy_threshold
        self.max_matches = max_matches
```
Leave everything after that (the `# Initialize lookup tables` line onward) unchanged.

- [ ] **Step 4: Fix `ComprehensiveMapper.__init__` to catch and fall back**

In `llm_terms/mappers/mapping.py`, replace:
```python
        self.umls_mapper = UMLSMapper(api_key=umls_api_key) if umls_api_key else None
        if use_local_omop and omop_vocab_dir:
            self.omop_mapper = OMOPLocalMapper(vocab_dir=omop_vocab_dir)
        else:
            self.omop_mapper = OMOPMapper()
```
with:
```python
        self.umls_mapper = UMLSMapper(api_key=umls_api_key) if umls_api_key else None
        if use_local_omop and omop_vocab_dir:
            try:
                self.omop_mapper = OMOPLocalMapper(vocab_dir=omop_vocab_dir)
            except FileNotFoundError as e:
                logger.error(
                    f"Local OMOP vocab unavailable, falling back to API-based "
                    f"OMOP mapper: {e}"
                )
                self.omop_mapper = OMOPMapper()
        else:
            self.omop_mapper = OMOPMapper()
```

- [ ] **Step 5: Document the Athena vocab download step**

In `llm_terms/README.md`, insert a new section immediately after line 11 (`- **Database & Ontology**: [Google Drive](...)`), before the `## 📁 Output Directories` heading:
```markdown

## 🗂️ OMOP Vocabulary Setup

`ComprehensiveMapper`'s local OMOP mapping (`OMOPLocalMapper`) needs the
OMOP Standardized Vocabularies on disk — they are **not** included in this
repo (multi-GB, licensed for redistribution only via Athena directly):

1. Register and download the vocabulary bundle from
   [Athena](https://athena.ohdsi.org/) (select at least `CONCEPT` and
   `CONCEPT_SYNONYM`).
2. Extract `CONCEPT.csv` and `CONCEPT_SYNONYM.csv` into a local directory,
   e.g. `llm_terms/data/omop_vocab/`.
3. Point the pipeline at it either by passing `omop_vocab_dir=...` when
   constructing `ComprehensiveMapper`, or by setting the `OMOP_VOCAB_DIR`
   environment variable.

If this directory is missing, `OMOPLocalMapper` now raises `FileNotFoundError`
at construction (it used to silently continue with empty lookup tables,
making a 0% OMOP mapping rate indistinguishable from "working but nothing
matched"). `ComprehensiveMapper` catches this and falls back automatically
to the slower API-based `OMOPMapper`.
```

- [ ] **Step 6: Run tests to verify they pass**

Run:
```bash
cd llm_terms && python -m unittest tests.test_mappers -v
cd llm_terms && python -m unittest tests.test_core -v
```
Expected: `OK` on both (11 tests in `test_mappers.py`; `test_core.py`'s `TestComprehensiveMapper` still passes since it constructs with `use_local_omop=False`, never touching this code path).

- [ ] **Step 7: Commit**

```bash
cd "C:\Users\jkalra\Documents\Microbiome-CDM"
git add llm_terms/mappers/omop_local_mapper.py llm_terms/mappers/mapping.py llm_terms/README.md llm_terms/tests/test_mappers.py
git commit -m "fix: fail loud on missing OMOP vocab dir instead of silent no-op

- OMOPLocalMapper now raises FileNotFoundError when an explicit
  vocab_dir doesn't exist, with a message pointing at the Athena
  download. Previously logged a WARNING and continued with empty
  lookup tables, making 'no vocab' indistinguishable from '0 matches'.
- Also fixes a latent NameError: Path was used but never imported.
- ComprehensiveMapper catches the new exception and falls back to the
  API-based OMOPMapper.
- Documents the Athena vocab setup step in llm_terms/README.md.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 7: ChEBI hierarchy builder

**Files:**
- Create: `llm_terms/scripts/extract_chemical_hierarchy.py`
- Test: `llm_terms/tests/test_extract_chemical_hierarchy.py` (create)

**Interfaces:**
- Produces: `ChemicalHierarchyExtractor` class with `extract_chebi_iri`, `get_hierarchical_ancestors`, `build_chemical_relationships`, `process_entities` methods. Output relationship dicts use the exact same keys as `extract_taxonomic_hierarchy.py`'s output (`source`, `target`, `relationship_type`, `source_db`, `confidence`, `evidence`, `evidence_type`) so they drop into `kg_refiner.py`'s `validate_and_enhance_relationships` unchanged (verified: it only reads `rel.get('relationship_type')` and generic dict fields).

- [ ] **Step 1: Write the failing tests**

Create `llm_terms/tests/test_extract_chemical_hierarchy.py`:
```python
import unittest
import tempfile
from unittest.mock import MagicMock, patch

from scripts.extract_chemical_hierarchy import ChemicalHierarchyExtractor


class TestChemicalHierarchyExtractor(unittest.TestCase):
    def setUp(self):
        self.extractor = ChemicalHierarchyExtractor(output_dir=tempfile.mkdtemp())

    def test_extract_chebi_iri_found(self):
        iri = self.extractor.extract_chebi_iri(
            "http://purl.obolibrary.org/obo/CHEBI_17968"
        )
        self.assertEqual(iri, "http://purl.obolibrary.org/obo/CHEBI_17968")

    def test_extract_chebi_iri_wrong_ontology_returns_none(self):
        self.assertIsNone(
            self.extractor.extract_chebi_iri("http://purl.obolibrary.org/obo/NCBITaxon_817")
        )

    def test_extract_chebi_iri_none_input_returns_none(self):
        self.assertIsNone(self.extractor.extract_chebi_iri(None))

    @patch('scripts.extract_chemical_hierarchy.requests.get')
    def test_get_hierarchical_ancestors_parses_terms(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            '_embedded': {'terms': [
                {'iri': 'http://purl.obolibrary.org/obo/CHEBI_26666',
                 'label': 'short-chain fatty acid', 'obo_id': 'CHEBI:26666'},
                {'iri': 'http://purl.obolibrary.org/obo/CHEBI_35366',
                 'label': 'monocarboxylic acid', 'obo_id': 'CHEBI:35366'},
            ]}
        }
        mock_get.return_value = mock_response

        ancestors = self.extractor.get_hierarchical_ancestors(
            'http://purl.obolibrary.org/obo/CHEBI_17968'
        )

        self.assertEqual(len(ancestors), 2)
        self.assertEqual(ancestors[0]['label'], 'short-chain fatty acid')
        self.assertEqual(ancestors[1]['label'], 'monocarboxylic acid')

    @patch('scripts.extract_chemical_hierarchy.requests.get')
    def test_build_chemical_relationships_shape(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            '_embedded': {'terms': [
                {'iri': 'http://purl.obolibrary.org/obo/CHEBI_26666',
                 'label': 'short-chain fatty acid', 'obo_id': 'CHEBI:26666'},
            ]}
        }
        mock_get.return_value = mock_response

        rels = self.extractor.build_chemical_relationships(
            'Butyrate', 'http://purl.obolibrary.org/obo/CHEBI_17968'
        )

        self.assertEqual(len(rels), 1)
        rel = rels[0]
        self.assertEqual(rel['source'], 'short-chain fatty acid')
        self.assertEqual(rel['target'], 'Butyrate')
        self.assertEqual(rel['relationship_type'], 'PARENT_OF')
        self.assertEqual(rel['source_db'], 'ChEBI (via OLS)')
        self.assertIn('confidence', rel)
        self.assertIn('evidence', rel)

    @patch('scripts.extract_chemical_hierarchy.requests.get')
    def test_get_hierarchical_ancestors_handles_error_gracefully(self, mock_get):
        mock_get.side_effect = Exception("network error")

        ancestors = self.extractor.get_hierarchical_ancestors(
            'http://purl.obolibrary.org/obo/CHEBI_17968'
        )

        self.assertEqual(ancestors, [])


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd llm_terms && python -m unittest tests.test_extract_chemical_hierarchy -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.extract_chemical_hierarchy'`.

- [ ] **Step 3: Write the implementation**

Create `llm_terms/scripts/extract_chemical_hierarchy.py`:
```python
#!/usr/bin/env python3
"""
Extract ChEBI hierarchy for chemical entities.

Builds parent-child chemical classification relationships using OLS's
ontology-agnostic hierarchicalAncestors endpoint, e.g.:
  Butyrate -is_a-> Short-chain fatty acid -is_a-> Monocarboxylic acid

Uses the EBI OLS REST API (no API key required). Mirrors the structure of
extract_taxonomic_hierarchy.py so both scripts' output drops into the same
downstream relationship-processing code (kg_refiner.py).
"""

import json
import csv
import time
import logging
import re
from typing import List, Dict, Optional
from pathlib import Path
from urllib.parse import quote

import requests

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ChemicalHierarchyExtractor:
    """Extract ChEBI classification hierarchies from EBI OLS."""

    BASE_URL = "https://www.ebi.ac.uk/ols/api/ontologies/chebi/terms"

    def __init__(self, output_dir: str = "knowledge_graph/relationships"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.ancestor_cache = {}

    def extract_chebi_iri(self, ontology_id: Optional[str]) -> Optional[str]:
        """Extract a ChEBI term IRI from an OLS/BioPortal id string."""
        if not ontology_id:
            return None
        match = re.search(r'(http://purl\.obolibrary\.org/obo/CHEBI_\d+)', ontology_id)
        if match:
            return match.group(1)
        return None

    def get_hierarchical_ancestors(self, chebi_iri: str) -> List[dict]:
        """Get all hierarchical ancestors for a ChEBI term via OLS, ordered
        closest-parent-first (matches OLS's own ordering)."""
        if chebi_iri in self.ancestor_cache:
            return self.ancestor_cache[chebi_iri]

        double_encoded_iri = quote(quote(chebi_iri, safe=''), safe='')
        url = f"{self.BASE_URL}/{double_encoded_iri}/hierarchicalAncestors"

        ancestors = []
        try:
            response = requests.get(url, params={"size": 50}, timeout=10)
            if response.status_code == 200:
                terms = response.json().get('_embedded', {}).get('terms', [])
                for term in terms:
                    ancestors.append({
                        'iri': term.get('iri'),
                        'label': term.get('label'),
                        'obo_id': term.get('obo_id')
                    })
            time.sleep(0.1)  # be polite to EBI's public API
        except Exception as e:
            logger.warning(f"Failed to fetch ancestors for {chebi_iri}: {e}")

        self.ancestor_cache[chebi_iri] = ancestors
        return ancestors

    def build_chemical_relationships(self, entity_term: str, chebi_iri: str) -> List[dict]:
        """Build is_a parent-child relationships for a chemical entity."""
        ancestors = self.get_hierarchical_ancestors(chebi_iri)
        if not ancestors:
            return []

        # chain[0] is the entity itself, chain[1] its closest parent, etc.
        chain = [{'iri': chebi_iri, 'label': entity_term, 'obo_id': None}] + ancestors

        relationships = []
        for i in range(len(chain) - 1, 0, -1):
            child = chain[i - 1]
            parent = chain[i]
            relationships.append({
                'source': parent['label'],
                'source_chebi_iri': parent['iri'],
                'target': child['label'],
                'target_chebi_iri': child['iri'],
                'relationship_type': 'PARENT_OF',
                'source_db': 'ChEBI (via OLS)',
                'confidence': 1.0,
                'evidence': f"ChEBI is_a hierarchy: {parent['label']} -> {child['label']}",
                'evidence_type': 'Curated'
            })
        return relationships

    def process_entities(
        self,
        entities: List[dict],
        output_file: str = "chemical_hierarchy.csv"
    ) -> List[dict]:
        """Process all chemical entities and extract ChEBI hierarchy relationships."""
        all_relationships = []
        processed_iris = set()

        chemical_entities = []
        for entity in entities:
            if entity.get('entity_type') != 'CHEMICAL':
                continue
            chebi_iri = self.extract_chebi_iri(entity.get('OLS'))
            if not chebi_iri:
                chebi_iri = self.extract_chebi_iri(entity.get('BioPortal'))
            if chebi_iri:
                chemical_entities.append({'term': entity['term'], 'chebi_iri': chebi_iri})

        logger.info(f"Processing {len(chemical_entities)} chemicals with ChEBI IRIs")

        for i, chem in enumerate(chemical_entities):
            if (i + 1) % 50 == 0:
                logger.info(f"Progress: {i + 1}/{len(chemical_entities)}")

            if chem['chebi_iri'] in processed_iris:
                continue
            processed_iris.add(chem['chebi_iri'])

            rels = self.build_chemical_relationships(chem['term'], chem['chebi_iri'])
            all_relationships.extend(rels)

        self._save_to_csv(all_relationships, output_file)

        json_file = self.output_dir / output_file.replace('.csv', '.json')
        with open(json_file, 'w') as f:
            json.dump(all_relationships, f, indent=2)

        logger.info(f"Extracted {len(all_relationships)} chemical hierarchy relationships")
        logger.info(f"Saved to {output_file}")

        return all_relationships

    def _save_to_csv(self, relationships: List[dict], filename: str):
        """Save relationships to CSV file."""
        if not relationships:
            logger.warning("No relationships to save")
            return

        output_path = self.output_dir / filename

        fieldnames = set()
        for rel in relationships:
            fieldnames.update(rel.keys())

        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=sorted(fieldnames))
            writer.writeheader()
            writer.writerows(relationships)

        logger.info(f"Saved {len(relationships)} relationships to {output_path}")


def main():
    """Main entry point."""
    entities_file = Path("knowledge_graph/cdm_entities_final_v3_embeddings.json")

    with open(entities_file, 'r') as f:
        data = json.load(f)
        entities = data['results']

    logger.info(f"Loaded {len(entities)} entities")

    extractor = ChemicalHierarchyExtractor()
    relationships = extractor.process_entities(entities, output_file="chemical_hierarchy.csv")

    logger.info(f"\nSummary:")
    logger.info(f"  Total chemical hierarchy relationships: {len(relationships)}")
    logger.info(f"  Unique parent chemicals: {len(set(r['source'] for r in relationships))}")
    logger.info(f"  Unique child chemicals: {len(set(r['target'] for r in relationships))}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd llm_terms && python -m unittest tests.test_extract_chemical_hierarchy -v
```
Expected: `OK` (6 tests pass). If you get `ModuleNotFoundError: No module named 'scripts'`, create an empty `llm_terms/scripts/__init__.py` and re-run — implicit namespace packages should make this unnecessary on Python 3.3+, but add it if the import fails.

- [ ] **Step 5: Commit**

```bash
cd "C:\Users\jkalra\Documents\Microbiome-CDM"
git add llm_terms/scripts/extract_chemical_hierarchy.py llm_terms/tests/test_extract_chemical_hierarchy.py
git commit -m "feat: add ChEBI hierarchy builder for CHEMICAL entities

Mirrors extract_taxonomic_hierarchy.py's structure and output shape,
using OLS's ontology-agnostic hierarchicalAncestors endpoint instead
of NCBI Entrez (ChEBI has no Entrez equivalent).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 8: NCBI Taxonomy direct-name fallback

**Files:**
- Modify: `llm_terms/scripts/extract_taxonomic_hierarchy.py`
- Test: `llm_terms/tests/test_extract_taxonomic_hierarchy.py` (create)

**Interfaces:**
- Produces: `TaxonomyHierarchyExtractor.search_taxon_by_name(organism_name: str) -> Optional[str]` — new method, called from `process_entities` as a fallback when `extract_ncbi_taxon_id` finds no OLS-sourced `NCBITaxon_` id for an ORGANISM entity.

- [ ] **Step 1: Write the failing tests**

Create `llm_terms/tests/test_extract_taxonomic_hierarchy.py`:
```python
import unittest
from unittest.mock import MagicMock, patch

from scripts.extract_taxonomic_hierarchy import TaxonomyHierarchyExtractor


class TestTaxonomyNameFallback(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.extractor = TaxonomyHierarchyExtractor(output_dir=tempfile.mkdtemp())

    @patch('scripts.extract_taxonomic_hierarchy.BIOPYTHON_AVAILABLE', True)
    @patch('scripts.extract_taxonomic_hierarchy.Entrez')
    def test_search_taxon_by_name_returns_first_id(self, mock_entrez):
        mock_entrez.esearch.return_value = MagicMock()
        mock_entrez.read.return_value = {'IdList': ['817', '818']}

        taxon_id = self.extractor.search_taxon_by_name('Bacteroides fragilis')

        self.assertEqual(taxon_id, '817')
        mock_entrez.esearch.assert_called_once_with(
            db="taxonomy", term='Bacteroides fragilis', retmode="xml"
        )

    @patch('scripts.extract_taxonomic_hierarchy.BIOPYTHON_AVAILABLE', True)
    @patch('scripts.extract_taxonomic_hierarchy.Entrez')
    def test_search_taxon_by_name_no_results_returns_none(self, mock_entrez):
        mock_entrez.esearch.return_value = MagicMock()
        mock_entrez.read.return_value = {'IdList': []}

        taxon_id = self.extractor.search_taxon_by_name('Nonexistent organism')

        self.assertIsNone(taxon_id)

    @patch('scripts.extract_taxonomic_hierarchy.BIOPYTHON_AVAILABLE', False)
    def test_search_taxon_by_name_without_biopython_returns_none(self):
        taxon_id = self.extractor.search_taxon_by_name('Bacteroides fragilis')
        self.assertIsNone(taxon_id)

    def test_process_entities_falls_back_to_name_search_when_ols_id_missing(self):
        self.extractor.search_taxon_by_name = MagicMock(return_value='817')
        self.extractor.build_taxonomy_relationships = MagicMock(return_value=[
            {'source': 'Bacteroidaceae', 'target': 'Bacteroides fragilis',
             'relationship_type': 'PARENT_OF'}
        ])

        entities = [
            {'entity_type': 'ORGANISM', 'term': 'Bacteroides fragilis', 'OLS': None}
        ]
        relationships = self.extractor.process_entities(entities, output_file='test_out.csv')

        self.extractor.search_taxon_by_name.assert_called_once_with('Bacteroides fragilis')
        self.extractor.build_taxonomy_relationships.assert_called_once_with(
            'Bacteroides fragilis', '817'
        )
        self.assertEqual(len(relationships), 1)


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd llm_terms && python -m unittest tests.test_extract_taxonomic_hierarchy -v
```
Expected: FAIL — `AttributeError: 'TaxonomyHierarchyExtractor' object has no attribute 'search_taxon_by_name'` on the first 3 tests; the 4th fails because `process_entities` never calls a name-search fallback yet (mock never called).

- [ ] **Step 3: Add the fallback method**

In `llm_terms/scripts/extract_taxonomic_hierarchy.py`, add this method to `TaxonomyHierarchyExtractor`, immediately after `get_taxon_info` (i.e. after the method ending at line 111, before `get_lineage`):
```python
    def search_taxon_by_name(self, organism_name: str) -> Optional[str]:
        """Look up an NCBI Taxonomy ID directly by organism name.

        Fallback for when extract_ncbi_taxon_id() has no OLS-sourced
        NCBITaxon_ id to work from (OLS returned nothing, or returned a
        different ontology's id for this ORGANISM entity).
        """
        if not BIOPYTHON_AVAILABLE:
            logger.warning("BioPython not available, skipping taxonomy name search")
            return None

        try:
            handle = Entrez.esearch(db="taxonomy", term=organism_name, retmode="xml")
            record = Entrez.read(handle)
            time.sleep(0.34)  # NCBI rate limit (3 requests/second)

            id_list = record.get('IdList', [])
            if id_list:
                return id_list[0]

        except Exception as e:
            logger.warning(f"Failed to search taxon by name '{organism_name}': {e}")

        return None
```

- [ ] **Step 4: Wire the fallback into `process_entities`**

Replace this block in `process_entities`:
```python
        # Filter organism entities with OLS NCBITaxon IDs
        organism_entities = []
        for entity in entities:
            if entity.get('entity_type') == 'ORGANISM' and entity.get('OLS'):
                taxon_id = self.extract_ncbi_taxon_id(entity['OLS'])
                if taxon_id:
                    organism_entities.append({
                        'term': entity['term'],
                        'taxon_id': taxon_id,
                        'entity': entity
                    })
```
with:
```python
        # Filter organism entities, resolving a taxon ID either from an
        # OLS NCBITaxon_ id or, failing that, a direct name search.
        organism_entities = []
        for entity in entities:
            if entity.get('entity_type') != 'ORGANISM':
                continue

            taxon_id = self.extract_ncbi_taxon_id(entity.get('OLS'))
            if not taxon_id:
                taxon_id = self.search_taxon_by_name(entity['term'])

            if taxon_id:
                organism_entities.append({
                    'term': entity['term'],
                    'taxon_id': taxon_id,
                    'entity': entity
                })
```

- [ ] **Step 5: Run tests to verify they pass**

Run:
```bash
cd llm_terms && python -m unittest tests.test_extract_taxonomic_hierarchy -v
```
Expected: `OK` (4 tests pass).

- [ ] **Step 6: Commit**

```bash
cd "C:\Users\jkalra\Documents\Microbiome-CDM"
git add llm_terms/scripts/extract_taxonomic_hierarchy.py llm_terms/tests/test_extract_taxonomic_hierarchy.py
git commit -m "feat: add direct NCBI name-search fallback to taxonomy extractor

process_entities previously only resolved a taxon ID from an OLS
NCBITaxon_ IRI. When OLS returns nothing (or a different ontology's
id) for an ORGANISM entity, it now falls back to a direct Entrez
esearch by name before giving up on that entity.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 9: Fix `extraction.py` — portable path, cache invalidation, embedding model

**Files:**
- Modify: `papers_txt/others/extraction.py`

**Interfaces:**
- Produces: `compute_corpus_hash(directory: str) -> str` (new module function) and a `--index-only` CLI flag, both used directly by Task 10's manual run. No automated unit test for this task (per spec: this is a data-pipeline script rebuild, not library code — verified manually in Task 10 by checking the printed vector count).

- [ ] **Step 1: Fix the hardcoded path and imports**

In `papers_txt/others/extraction.py`, replace the import block and configuration block:
```python
import os
import re
import json
import time
import hashlib
import requests
import argparse
import numpy as np
import faiss
from pathlib import Path
from openai import OpenAI
from collections import defaultdict
from tqdm import tqdm
from thefuzz import process as fuzzy_process
from sentence_transformers import SentenceTransformer, util

# --- Configuration ---
# Corpus directory: papers_txt/ (this script lives in papers_txt/others/)
INPUT_DIRECTORY = str(Path(__file__).resolve().parent.parent)
# The name of the final JSON output file
OUTPUT_FILE = "master_terminology_dictionary.json"
# The name for the cached embeddings, FAISS index, and corpus-hash files
EMBEDDINGS_FILE = "corpus_embeddings.npy"
FAISS_INDEX_FILE = "corpus_index.faiss"
CORPUS_HASH_FILE = "corpus_index.hash"

# --- Model & Processing Parameters ---
# Model to use for LLM tasks (ensure this is running in Ollama)
LLM_MODEL_NAME = "qwen3.5:9b"
# Model for creating text embeddings (nomic v1.5, matching
# llm_terms/core/semantic_deduplicator.py's choice elsewhere in this project)
EMBEDDING_MODEL_NAME = 'nomic-ai/nomic-embed-text-v1.5'
```
Leave the rest of the configuration block (`FUZZY_DEDUP_THRESHOLD` through `SCORE_WEIGHT_SEMANTIC`) unchanged.

- [ ] **Step 2: Add the corpus-hash function**

Add this function right after the `load_stopwords` function definition (before `preprocess_text`):
```python
def compute_corpus_hash(directory: str) -> str:
    """Hash the corpus's file list, sizes, and mtimes so the cached FAISS
    index can be invalidated automatically when papers_txt/ changes,
    instead of trusting a stale cache forever."""
    files = sorted(f for f in os.listdir(directory) if f.endswith('.txt'))
    hasher = hashlib.sha256()
    for filename in files:
        filepath = os.path.join(directory, filename)
        stat = os.stat(filepath)
        hasher.update(f"{filename}:{stat.st_size}:{int(stat.st_mtime)}".encode('utf-8'))
    return hasher.hexdigest()
```

- [ ] **Step 3: Load the embedding model with nomic's `trust_remote_code`**

Replace:
```python
    print("--- Phase 1: Building/loading embeddings and FAISS index ---")
    embed_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    all_chunks, chunk_to_filename_map = get_text_chunks(INPUT_DIRECTORY)
    if os.path.exists(FAISS_INDEX_FILE):
        print("  - Loading existing FAISS index from cache.")
        index = faiss.read_index(FAISS_INDEX_FILE)
    else:
        print("  - No cache found. Building new FAISS index.")
        embeddings = embed_model.encode(all_chunks, show_progress_bar=True, convert_to_numpy=True)
        index = faiss.IndexFlatL2(embeddings.shape[1])
        index.add(embeddings.astype('float32'))
        faiss.write_index(index, FAISS_INDEX_FILE)
        print("  - Saved new index to cache.")
```
with:
```python
    print("--- Phase 1: Building/loading embeddings and FAISS index ---")
    embed_model = SentenceTransformer(EMBEDDING_MODEL_NAME, trust_remote_code=True)
    all_chunks, chunk_to_filename_map = get_text_chunks(INPUT_DIRECTORY)

    current_hash = compute_corpus_hash(INPUT_DIRECTORY)
    cache_valid = (
        os.path.exists(FAISS_INDEX_FILE)
        and os.path.exists(CORPUS_HASH_FILE)
        and open(CORPUS_HASH_FILE).read().strip() == current_hash
    )

    if cache_valid:
        print("  - Loading existing FAISS index from cache (corpus unchanged).")
        index = faiss.read_index(FAISS_INDEX_FILE)
    else:
        print("  - Corpus changed or no cache found. Building new FAISS index.")
        # nomic v1.5 requires a task prefix on every encoded string.
        prefixed_chunks = [f"search_document: {chunk}" for chunk in all_chunks]
        embeddings = embed_model.encode(prefixed_chunks, show_progress_bar=True, convert_to_numpy=True)
        np.save(EMBEDDINGS_FILE, embeddings)
        index = faiss.IndexFlatL2(embeddings.shape[1])
        index.add(embeddings.astype('float32'))
        faiss.write_index(index, FAISS_INDEX_FILE)
        with open(CORPUS_HASH_FILE, 'w') as f:
            f.write(current_hash)
        print(f"  - Saved new index to cache ({index.ntotal} vectors from {len(all_chunks)} chunks).")

    if args.index_only:
        print(f"\n✅ Index-only mode: FAISS index ready with {index.ntotal} vectors "
              f"from {len(all_chunks)} chunks across {len(set(chunk_to_filename_map))} files.")
        return
```

- [ ] **Step 4: Add the `search_query:` prefix to the RAG query embedding**

Replace:
```python
    query_embedding = embed_model.encode(["microbiome common data model, experimental factors, and analysis methods"])
```
with:
```python
    query_embedding = embed_model.encode(
        ["search_query: microbiome common data model, experimental factors, and analysis methods"]
    )
```

- [ ] **Step 5: Add the `--index-only` CLI flag**

Replace:
```python
    parser = argparse.ArgumentParser(description="Advanced terminology extractor for scientific papers.")
    parser.add_argument("--model", type=str, default=LLM_MODEL_NAME, help="LLM model name to use.")
    parser.add_argument("--file", type=str, default=None, help="Run on a single file instead of the whole directory.")
    args = parser.parse_args()
```
with:
```python
    parser = argparse.ArgumentParser(description="Advanced terminology extractor for scientific papers.")
    parser.add_argument("--model", type=str, default=LLM_MODEL_NAME, help="LLM model name to use.")
    parser.add_argument("--file", type=str, default=None, help="Run on a single file instead of the whole directory.")
    parser.add_argument("--index-only", action="store_true",
                         help="Only build/update the FAISS index (Phase 1), skip LLM term extraction (Phases 2-6).")
    args = parser.parse_args()
```

- [ ] **Step 6: Verify the file is syntactically valid**

Run:
```bash
python -m py_compile "papers_txt/others/extraction.py"
```
Expected: no output, exit code 0 (this only checks syntax — `faiss`/`sentence_transformers`/`openai`/`thefuzz` aren't installed yet, so it can't be run end-to-end until Task 10).

- [ ] **Step 7: Commit**

```bash
cd "C:\Users\jkalra\Documents\Microbiome-CDM"
git add papers_txt/others/extraction.py
git commit -m "fix: make corpus index script portable and cache-safe

- INPUT_DIRECTORY was a hardcoded /home/jkalra/... absolute path;
  now resolved relative to the script's own location.
- FAISS index cache was existence-only (trusted a stale index
  forever); now invalidated via a content hash of papers_txt/'s
  file list, sizes, and mtimes.
- Embedding model switched from all-MiniLM-L6-v2 to
  nomic-ai/nomic-embed-text-v1.5 with task prefixes, matching
  llm_terms/core/semantic_deduplicator.py's choice elsewhere in
  this project (previously two different embedding spaces for the
  same kind of task).
- LLM_MODEL_NAME default corrected to an available local Ollama
  model (previous default, 'dee', doesn't exist in Ollama).
- Added --index-only flag to rebuild the FAISS index without
  requiring a running LLM (Phase 1 only).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 10: Install FAISS/sentence-transformers and rebuild the index

**Files:**
- None created/modified — sandbox environment + regenerated binary data artifacts (`papers_txt/others/corpus_index.faiss`, `papers_txt/others/corpus_embeddings.npy`, `papers_txt/others/corpus_index.hash`).

**Interfaces:**
- Produces: a fresh FAISS index covering every file currently in `papers_txt/` (matches the corpus after Task 8's cleanup commit — untracked from git, but still present on disk).

- [ ] **Step 1: Install the required packages**

Run:
```bash
python -m pip install faiss-cpu sentence-transformers openai thefuzz tqdm
```
Expected: installs succeed. This pulls in `torch` transitively (sentence-transformers' dependency) — expect a multi-minute, multi-GB download. If any package fails to find a compatible wheel for this Python version, stop and report the exact error rather than trying workarounds — package availability for very new Python versions is outside this plan's control.

- [ ] **Step 2: Run the index-only rebuild**

Run:
```bash
cd "papers_txt/others" && python extraction.py --index-only
```
Expected output ends with a line like:
```
✅ Index-only mode: FAISS index ready with <N> vectors from <N> chunks across <M> files.
```
where `<M>` matches the current file count in `papers_txt/` (check with `ls papers_txt/*.txt | wc -l` beforehand and compare).

- [ ] **Step 3: Verify the artifacts were written**

Run:
```bash
ls -la papers_txt/others/corpus_index.faiss papers_txt/others/corpus_embeddings.npy papers_txt/others/corpus_index.hash
```
Expected: all three files exist with a modification time from this run (not the old committed-then-untracked ones).

- [ ] **Step 4: Verify cache invalidation works**

Run the same command again immediately, with no corpus changes:
```bash
cd "papers_txt/others" && python extraction.py --index-only
```
Expected output includes:
```
- Loading existing FAISS index from cache (corpus unchanged).
```
(confirms the hash check works — second run doesn't re-embed).

- [ ] **Step 5: No commit needed**

These are data artifacts covered by `.gitignore`'s existing `papers_txt/` rule (from the earlier cleanup commit) — they stay local, untracked, exactly as intended. Nothing to commit for this task.

---

## Post-plan note

Phases 2–6 of `extraction.py` (LLM-based term extraction, definition, categorization) were **not** run as part of this plan — they need a working `LLM_MODEL_NAME` and take significantly longer (500 files × LLM calls). The default model name is now corrected to `qwen3.5:9b` (confirmed available locally), so running the full script without `--index-only` is possible whenever the user wants to kick that off separately.
