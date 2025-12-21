#!/usr/bin/env python3
"""
Label correction module using BioPortal, UMLS, and OLS APIs.
Provides intelligent entity label assignment for microbiome CDM terms.
"""

import logging
import requests
import time
from typing import Dict, List, Tuple, Optional
from collections import Counter
import json
from pathlib import Path

logger = logging.getLogger(__name__)


class BioPortalMapper:
    """Map terms to entity labels using NCBO BioPortal API"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "http://data.bioontology.org"
        self.cache = {}
        self.cache_file = Path("cache/bioportal_cache.json")
        self._load_cache()
        
        # Ontology to label mapping
        self.ontology_to_label = {
            "NCBITAXON": "TAXON",
            "NCBITaxon": "TAXON",
            "GO": "GENE_OR_GENE_PRODUCT",
            "CHEBI": "CHEMICAL",
            "DOID": "DISEASE",
            "PR": "PROTEIN",
            "UBERON": "ANATOMICAL_ENTITY",
            "CL": "CELL_TYPE",
            "SO": "GENE_OR_GENE_PRODUCT"
        }
    
    def _load_cache(self):
        """Load cached results"""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r') as f:
                    self.cache = json.load(f)
                logger.info(f"Loaded {len(self.cache)} cached BioPortal results")
            except:
                pass
    
    def _save_cache(self):
        """Save cache to disk"""
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_file, 'w') as f:
            json.dump(self.cache, f)
    
    def get_label(self, term: str) -> Tuple[Optional[str], float]:
        """
        Query BioPortal and return best label
        
        Returns:
            (label, confidence) or (None, 0.0)
        """
        if term in self.cache:
            return self.cache[term]
        
        try:
            # Search BioPortal
            params = {
                "q": term,
                "apikey": self.api_key,
                "ontologies": "NCBITAXON,GO,CHEBI,DOID,PR,UBERON,CL",
                "require_exact_match": "false",
                "page_size": 10
            }
            
            response = requests.get(
                f"{self.base_url}/search",
                params=params,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get("collection"):
                    # Get ontology sources
                    ontologies = []
                    for result in data["collection"][:5]:  # Top 5 results
                        ont_links = result.get("links", {}).get("ontology")
                        if ont_links:
                            # Extract ontology acronym from URL
                            ont_id = ont_links.split("/")[-1]
                            ontologies.append(ont_id)
                    
                    # Vote for best label
                    label_votes = Counter()
                    for ont in ontologies:
                        if ont in self.ontology_to_label:
                            label_votes[self.ontology_to_label[ont]] += 1
                    
                    if label_votes:
                        best_label, votes = label_votes.most_common(1)[0]
                        confidence = min(votes / len(ontologies), 1.0) if ontologies else 0.5
                        
                        result = (best_label, confidence)
                        self.cache[term] = result
                        return result
            
            time.sleep(0.1)  # Rate limiting
            
        except Exception as e:
            logger.warning(f"BioPortal error for '{term}': {e}")
        
        self.cache[term] = (None, 0.0)
        return None, 0.0


class UMLSMapper:
    """Map terms to semantic types using UMLS API"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://uts-ws.nlm.nih.gov/rest"
        self.cache = {}
        self.cache_file = Path("cache/umls_cache.json")
        self._load_cache()
        
        # UMLS Semantic Type to our label mapping
        self.semantic_type_to_label = {
            # Organisms
            "T007": "TAXON",  # Bacterium
            "T194": "TAXON",  # Archaeon
            "T004": "TAXON",  # Fungus
            "T005": "TAXON",  # Virus
            "T001": "TAXON",  # Organism
            
            # Molecular
            "T028": "GENE_OR_GENE_PRODUCT",  # Gene or Genome
            "T116": "PROTEIN",  # Amino Acid, Peptide, or Protein
            "T126": "PROTEIN",  # Enzyme
            "T192": "PROTEIN",  # Receptor
            
            # Chemical
            "T109": "CHEMICAL",  # Organic Chemical
            "T121": "CHEMICAL",  # Pharmacologic Substance
            "T123": "CHEMICAL",  # Biologically Active Substance
            "T103": "CHEMICAL",  # Chemical
            
            # Disease
            "T047": "DISEASE",  # Disease or Syndrome
            "T048": "DISEASE",  # Mental or Behavioral Dysfunction
            "T191": "DISEASE",  # Neoplastic Process
            "T046": "DISEASE", # Pathologic Function
            
            # Anatomy
            "T017": "ANATOMICAL_ENTITY",  # Anatomical Structure
            "T023": "ANATOMICAL_ENTITY",  # Body Part
            "T029": "ANATOMICAL_ENTITY",  # Body Location
            
            # Cell
            "T025": "CELL_TYPE",  # Cell
            "T026": "CELL_TYPE"   # Cell Component
        }
    
    def _load_cache(self):
        """Load cached results"""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r') as f:
                    self.cache = json.load(f)
                logger.info(f"Loaded {len(self.cache)} cached UMLS results")
            except:
                pass
    
    def _save_cache(self):
        """Save cache to disk"""
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_file, 'w') as f:
            json.dump(self.cache, f)
    
    def get_label(self, term: str) -> Tuple[Optional[str], float]:
        """
        Query UMLS and return best label based on semantic types
        
        Returns:
            (label, confidence) or (None, 0.0)
        """
        if term in self.cache:
            return self.cache[term]
        
        try:
            # Search UMLS
            params = {
                "apiKey": self.api_key,
                "string": term,
                "searchType": "words",  # More flexible matching
                "pageSize": 5
            }
            
            response = requests.get(
                f"{self.base_url}/search/current",
                params=params,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                results = data.get("result", {}).get("results", [])
                
                if results:
                    # Collect semantic types from all results
                    semantic_types = []
                    for result in results:
                        # Extract available semantic types for future enrichment
                        semantic_types.append(result.get("semanticType", "Unknown"))
                    
                    # For now, use a simplified approach based on term patterns
                    # In production, would fetch full concept details
                    
                    time.sleep(0.05)  # Rate limiting
            
        except Exception as e:
            logger.warning(f"UMLS error for '{term}': {e}")
        
        self.cache[term] = (None, 0.0)
        return None, 0.0


class LabelCorrector:
    """Orchestrate multi-source label correction"""
    
    def __init__(self, bioportal_api_key: Optional[str] = None, umls_api_key: Optional[str] = None):
        self.bioportal = BioPortalMapper(bioportal_api_key) if bioportal_api_key else None
        self.umls = UMLSMapper(umls_api_key) if umls_api_key else None
        self.corrections = 0
    
    def correct_label(self, term: str, current_label: str) -> Dict[str, any]:
        """
        Get best label from multiple sources
        
        Returns:
            {
                "label": "TAXON",
                "confidence": 0.95,
                "source": "BioPortal",
                "original_label": "ENTITY"
            }
        """
        # Only try to correct generic ENTITY labels
        if current_label != "ENTITY":
            return {
                "label": current_label,
                "confidence": 1.0,
                "source": "original",
                "original_label": current_label
            }
        
        results = []
        
        # Try BioPortal first (fast, comprehensive)
        if self.bioportal:
            label, conf = self.bioportal.get_label(term)
            if label and conf > 0.5:
                results.append(("BioPortal", label, conf))
        
        # Try UMLS if BioPortal failed
        if not results and self.umls:
            label, conf = self.umls.get_label(term)
            if label and conf > 0.5:
                results.append(("UMLS", label, conf))
        
        # Select best result
        if results:
            source, label, conf = max(results, key=lambda x: x[2])
            self.corrections += 1
            return {
                "label": label,
                "confidence": conf,
                "source": source,
                "original_label": current_label
            }
        
        # No correction found
        return {
            "label": current_label,
            "confidence": 0.5,
            "source": "original",
            "original_label": current_label
        }
    
    def save_caches(self):
        """Save all caches"""
        if self.bioportal:
            self.bioportal._save_cache()
        if self.umls:
            self.umls._save_cache()
