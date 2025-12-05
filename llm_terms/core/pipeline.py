"""
CDM Pipeline Core Orchestrator
"""

import os
import logging
import re
import time
import json
from pathlib import Path
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional
from core.llm_client import LLMClient
from extractors.entity_extractor import CDMEntityExtractor
from core.semantic_deduplicator import SemanticDeduplicator
from core.entity_filter import EntityFilter
from core.biomedical_deduplicator import BioMistralDeduplicator
from core.term_corrector import MiniLMTermCorrector
from core.relevance_scorer import MicrobiomeRelevanceScorer
from biomedical.biomistral_validator import BioMistralValidator, BioMistralConfig
from mappers.mapping import ComprehensiveMapper
from config.cdm_config import CDMEntityConfig, PipelineConfig

logger = logging.getLogger(__name__)



class CDMEntityPipeline:
    """Main CDM entity extraction pipeline with semantic deduplication."""

    def __init__(self, model: str = None, base_url: str = None, config: PipelineConfig = None,
                 semantic_model: str = "all-MiniLM-L6-v2", semantic_threshold: float = 0.8,
                 enable_biomistral: bool = False, biomistral_model: str = "biomistral-7B",
                 enable_biomistral_deduplication: bool = False, biomistral_dedup_model: str = "biomistral:7b",
                 enable_omop_mapping: bool = False, enable_umls_mapping: bool = False,
                 umls_api_key: str = None, enable_comprehensive_mapping: bool = False,
                 mapping_confidence_threshold: float = 0.7,
                 enable_correction: bool = False, enable_llm_correction: bool = False,
                 api_key: str = "EMPTY", bioportal_api_key: str = None,
                 enable_scispacy_linking: bool = False):
        self.config = config or PipelineConfig()
        self.llm_client = LLMClient(model or self.config.default_model, base_url or self.config.default_base_url, api_key=api_key)
        
        self.extractor = CDMEntityExtractor(self.llm_client)
        self.entity_config = CDMEntityConfig()
        self.semantic_deduplicator = SemanticDeduplicator(semantic_model, semantic_threshold)

        self.entity_filter = EntityFilter(strict_mode=True)
        self.relevance_scorer = MicrobiomeRelevanceScorer()
        self.term_corrector = MiniLMTermCorrector(semantic_model, 0.9)

        # Initialize biomedical and mapping components
        self.enable_biomistral = enable_biomistral
        self.enable_biomistral_deduplication = enable_biomistral_deduplication
        self.enable_omop_mapping = enable_omop_mapping
        self.enable_umls_mapping = enable_umls_mapping
        self.enable_comprehensive_mapping = enable_comprehensive_mapping
        self.mapping_confidence_threshold = mapping_confidence_threshold
        self.enable_correction = enable_correction
        self.enable_llm_correction = enable_llm_correction

        if enable_biomistral:
            from biomedical.biomistral_validator import BioMistralValidator, BioMistralConfig
            biomistral_config = BioMistralConfig(model_name=biomistral_model)
            self.biomistral_validator = BioMistralValidator(biomistral_config, llm_client=self.llm_client)

        if enable_biomistral_deduplication:
            self.biomistral_deduplicator = BioMistralDeduplicator(
                llm_client=self.llm_client,
                biomistral_model=biomistral_dedup_model,
                semantic_model=semantic_model
            )
            logger.info(f"✅ BioMistral deduplication enabled with model: {biomistral_dedup_model}")

        if enable_comprehensive_mapping:
            from mappers.mapping import ComprehensiveMapper
            # Get OMOP vocab directory from environment or default
            omop_vocab_dir = os.environ.get('OMOP_VOCAB_DIR', '/home/jkalra/Documents/CDM/omop_vocab')

            self.comprehensive_mapper = ComprehensiveMapper(
                umls_api_key=umls_api_key,
                bioportal_api_key=bioportal_api_key,
                use_local_omop=True,  # Use local mapper by default
                omop_vocab_dir=omop_vocab_dir,
                fuzzy_threshold=95,
                max_matches=3,
                cache_mappings=True
            )
            logger.info(f"🗂️  Comprehensive mapping initialized with OMOP vocab: {omop_vocab_dir}")

    def validate_prerequisites(self) -> bool:
        """Validate that the pipeline can run."""
        if not self.llm_client.is_available():
            logger.error(f"LLM service not available at {self.llm_client.base_url}")
            return False

        available_models = self.llm_client.get_available_models()
        if self.llm_client.model not in available_models:
            logger.error(f"Model {self.llm_client.model} not available. Available models: {available_models}")
            return False

        logger.info(f"✅ LLM service available with model: {self.llm_client.model}")
        return True

    def extract_entities(self, text: str, chunk_size: int = None) -> List[Dict]:
        """Extract CDM entities using Windowed Multi-Pass Strategy (Fast & Comprehensive)."""
        logger.info(f"🔍 Starting Windowed Multi-Pass Extraction on {len(text)} characters")

        all_entities = []
        text_len = len(text)
        
        # Define Windows (from Reference Script)
        # Pass 1: 0-8000
        # Pass 2: 0-8000
        # Pass 3: 10000-18000 (or 0-8000 if short)
        # Pass 4: 15000-23000 (or 0-8000 if short)
        # Pass 5: 20000-28000 (or 0-8000 if short)
        # Pass 6: 25000-35000 (or 0-8000 if short)
        
        # Helper to get safe window
        def get_window(start, length):
            if text_len < start: return ""
            end = min(start + length, text_len)
            return text[start:end]

        # Prepare Pass Data
        pass_configs = [
            (text[0:8000], 1),
            (text[0:8000], 2),
            (get_window(10000, 8000) if text_len > 10000 else text[0:min(text_len, 8000)], 3),
            (get_window(15000, 8000) if text_len > 15000 else text[0:min(text_len, 8000)], 4)
        ]

        # Run Passes 1-4 in Parallel
        logger.info(f"🔄 Running Passes 1-4 in parallel ({len(pass_configs)} tasks)...")
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [
                executor.submit(self.extractor.run_extraction_pass, (p_text, p_num, []))
                for p_text, p_num in pass_configs
                if p_text.strip() # Only run if text is not empty
            ]
            
            for future in as_completed(futures):
                try:
                    pass_entities = future.result()
                    all_entities.extend(pass_entities)
                except Exception as e:
                    logger.error(f"Error in extraction pass: {e}")

        # Collect unique terms so far for Pass 5 context
        unique_terms = list(set([e['entity'] for e in all_entities]))
        logger.info(f"📊 Terms after Passes 1-4: {len(unique_terms)}")

        # Conditional Pass 5 (Catch-all)
        if len(unique_terms) < 100:
            logger.info("⚠️  Term count low. Running Pass 5 (Catch-all)...")
            p5_text = get_window(20000, 8000) if text_len > 20000 else text[0:min(text_len, 8000)]
            if p5_text.strip():
                p5_entities = self.extractor.run_extraction_pass((p5_text, 5, unique_terms))
                all_entities.extend(p5_entities)

        # Conditional Pass 6 (Aggressive)
        unique_terms = list(set([e['entity'] for e in all_entities]))
        if len(unique_terms) < 50:
            logger.info("⚠️  Term count still low. Running Pass 6 (Aggressive)...")
            p6_text = get_window(25000, 10000) if text_len > 25000 else text[0:min(text_len, 10000)]
            if p6_text.strip():
                p6_entities = self.extractor.run_extraction_pass((p6_text, 6, []))
                all_entities.extend(p6_entities)

        # Post-process entities with semantic deduplication
        processed_entities = self.post_process_entities(all_entities, use_semantic=True)

        logger.info(f"✅ Extraction complete: {len(processed_entities)} unique entities")
        return processed_entities

    def post_process_entities(self, entities: List[Dict], use_semantic: bool = False) -> List[Dict]:
        """Clean, deduplicate, and sort entities with optional semantic deduplication."""
        logger.info(f"🔄 Post-processing {len(entities)} entities")

        # Basic cleaning and validation
        cleaned_entities = []
        for entity_data in entities:
            # Clean entity name
            cleaned_entity = re.sub(r'[^a-zA-Z0-9\s\-\._]', '', entity_data['entity']).strip()

            # Validation checks
            if (not cleaned_entity or
                len(cleaned_entity) < 2 or
                len(cleaned_entity) > 100 or
                entity_data['confidence'] < self.config.min_confidence):
                continue

            entity_data['entity'] = cleaned_entity
            cleaned_entities.append(entity_data)

        logger.info(f"✅ Basic validation: {len(entities)} → {len(cleaned_entities)} entities")

        # Apply BioMistral biomedical validation if enabled
        if self.enable_biomistral:
            logger.info("🔄 Applying BioMistral biomedical validation...")
            cleaned_entities = self.biomistral_validator.validate_entity_list(cleaned_entities)
            if self.enable_llm_correction:
                cleaned_entities = self.biomistral_validator.correct_entity_types(cleaned_entities)
            logger.info(f"✅ BioMistral validation: {len(cleaned_entities)} entities processed")

        # Apply MiniLM term correction
        if self.enable_correction:
            logger.info("🔧 Applying MiniLM term correction...")
            cleaned_entities = self.term_corrector.correct_terms(cleaned_entities)

        # Apply comprehensive mapping if enabled
        if self.enable_comprehensive_mapping:
            logger.info("🔄 Applying comprehensive biomedical mapping...")
            cleaned_entities = self.comprehensive_mapper.map_entity_list_comprehensive(cleaned_entities)
            logger.info(f"✅ Comprehensive mapping: {len(cleaned_entities)} entities processed")

        # Apply semantic deduplication if requested
        if use_semantic:
            logger.info("🔄 Applying semantic deduplication...")
            semantically_deduplicated = self.semantic_deduplicator.apply_semantic_deduplication(cleaned_entities)
            logger.info(f"✅ Semantic deduplication: {len(cleaned_entities)} → {len(semantically_deduplicated)} entities")
            unique_entities = semantically_deduplicated
        else:
            # Traditional string-based deduplication
            seen_entities = set()
            unique_entities = []
            for entity_data in cleaned_entities:
                key = (entity_data['entity'].lower().strip(), entity_data['entity_type'])
                if key not in seen_entities:
                    seen_entities.add(key)
                    unique_entities.append(entity_data)

        # Apply BioMistral biomedical deduplication if enabled
        if self.enable_biomistral_deduplication:
            logger.info("🔬 Applying BioMistral biomedical deduplication...")
            biomistral_deduplicated, duplicate_groups = self.biomistral_deduplicator.deduplicate_entities(
                entities=unique_entities,
                biomistral_threshold=0.7,
                semantic_threshold=0.85,
                use_biomistral=True
            )
            logger.info(f"✅ BioMistral deduplication: {len(unique_entities)} → {len(biomistral_deduplicated)} entities")
            logger.info(f"🔗 Found {len(duplicate_groups)} biomedical duplicate groups")

            # Export duplicate analysis for parsing
            self.biomistral_deduplicator.export_duplicate_analysis("biomistral_duplicate_analysis.json")

            unique_entities = biomistral_deduplicated

        # Apply comprehensive entity filtering and quality control
        logger.info("🔍 Applying comprehensive entity filtering and quality control...")
        filtered_entities = self.entity_filter.apply_comprehensive_filtering(unique_entities)
        logger.info(f"✅ Comprehensive filtering: {len(unique_entities)} → {len(filtered_entities)} high-quality entities")
        
        # Apply microbiome relevance scoring
        logger.info("📊 Calculating microbiome relevance scores...")
        scored_entities = self.relevance_scorer.score_entities(filtered_entities)
        unique_entities = scored_entities

        # Sort by entity type priority and confidence
        entity_type_order = {entity_type: config['priority']
                           for entity_type, config in self.entity_config.ENTITY_TYPES.items()}

        unique_entities.sort(
            key=lambda x: (entity_type_order.get(x['entity_type'], 99), -x['confidence'])
        )

        # Cap maximum entities
        final_entities = unique_entities[:self.config.max_entities]
        logger.info(f"✅ Final result: {len(final_entities)} entities (max: {self.config.max_entities})")

        return final_entities

    def generate_statistics(self, entities: List[Dict]) -> Dict:
        """Generate extraction statistics."""
        type_counts = {}
        confidence_sum = 0
        source_counts = {}

        for entity in entities:
            entity_type = entity['entity_type']
            type_counts[entity_type] = type_counts.get(entity_type, 0) + 1
            confidence_sum += entity['confidence']

            source = entity['source']
            source_counts[source] = source_counts.get(source, 0) + 1

        avg_confidence = confidence_sum / len(entities) if entities else 0

        return {
            'total_entities': len(entities),
            'entity_type_distribution': type_counts,
            'average_confidence': round(avg_confidence, 3),
            'source_distribution': source_counts,
            'unique_entity_types': len(type_counts)
        }

    def save_results(self, entities: List[Dict], output_path: str, text_stats: Dict = None):
        """Save extraction results to JSON file."""
        # Group entities by type
        grouped_entities = {}
        for entity in entities:
            entity_type = entity['entity_type']
            if entity_type not in grouped_entities:
                grouped_entities[entity_type] = []

            # Build entity data with all fields including mappings
            entity_data = {
                'entity': entity['entity'],
                'context': entity['context'],
                'definition': entity.get('definition', ''),
                'aliases': entity.get('aliases', []),
                'examples': entity.get('examples', []),
                'confidence': entity['confidence'],
                'source': entity['source'],
                'microbiome_relevance_score': entity.get('microbiome_relevance_score', 0.0)
            }

            # Add OMOP mappings if available (direct or from comprehensive mapping)
            omop_mappings = None
            has_omop_mapping = False
            best_omop_confidence = 0.0
            omop_domain_id = None
            omop_concept_count = 0

            # Check for direct OMOP mappings
            if 'omop_mappings' in entity:
                omop_mappings = entity['omop_mappings']
                has_omop_mapping = entity['has_omop_mapping']
                best_omop_confidence = entity['best_omop_confidence']
                omop_domain_id = entity['omop_domain_id']
                omop_concept_count = entity['omop_concept_count']

            # Check for OMOP mappings in comprehensive mapping
            elif 'comprehensive_mapping' in entity:
                comp_mapping = entity['comprehensive_mapping']
                if comp_mapping.get('omop_count', 0) > 0:
                    omop_mappings = comp_mapping.get('omop_mappings', [])
                    has_omop_mapping = True
                    omop_concept_count = comp_mapping.get('omop_count', 0)
                    if omop_mappings:
                        best_omop_confidence = comp_mapping.get('best_confidence', 0.0)
                        omop_domain_id = omop_mappings[0].get('domain_id') if omop_mappings else None

            # Add OMOP mapping data to entity if available
            if omop_mappings:
                entity_data['omop_mappings'] = omop_mappings
                entity_data['has_omop_mapping'] = has_omop_mapping
                entity_data['best_omop_confidence'] = best_omop_confidence
                entity_data['omop_domain_id'] = omop_domain_id
                entity_data['omop_concept_count'] = omop_concept_count

            # Add comprehensive mapping if available
            if 'comprehensive_mapping' in entity:
                entity_data['comprehensive_mapping'] = entity['comprehensive_mapping']

            grouped_entities[entity_type].append(entity_data)

        # Generate statistics
        stats = self.generate_statistics(entities)

        # Create results structure
        results = {
            'metadata': {
                'timestamp': time.time(),
                'model_used': self.llm_client.model,
                'pipeline_version': '1.0.0',
                'extraction_config': {
                    'min_confidence': self.config.min_confidence,
                    'max_entities': self.config.max_entities,
                    'max_workers': self.config.max_workers
                }
            },
            'text_statistics': text_stats or {},
            'extraction_statistics': stats,
            'results': {
                'entity_type_counts': {k: len(v) for k, v in grouped_entities.items()},
                'cdm_entities': grouped_entities
            }
        }

        # Write to file
        import json
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2)

        logger.info(f"💾 Results saved to {output_path}")

        # Log summary
        logger.info(f"📊 Extraction Summary:")
        for entity_type, count in stats['entity_type_distribution'].items():
            logger.info(f"   {entity_type}: {count} entities")
        logger.info(f"   Average confidence: {stats['average_confidence']:.3f}")

    def run(self, text: str, output_path: str, chunk_size: int = None) -> bool:
        """Run the complete CDM entity extraction pipeline."""
        try:
            # Validate prerequisites
            if not self.validate_prerequisites():
                return False

            # Text statistics
            text_stats = {
                'character_count': len(text),
                'word_count': len(text.split()),
                'estimated_reading_time': len(text.split()) / 200  # words per minute
            }

            logger.info(f"📄 Text analysis: {text_stats['character_count']} chars, {text_stats['word_count']} words")

            # Extract entities
            start_time = time.time()
            entities = self.extract_entities(text, chunk_size)
            extraction_time = time.time() - start_time

            # Save results
            self.save_results(entities, output_path, text_stats)

            logger.info(f"⚡ Pipeline completed in {extraction_time:.1f} seconds")
            logger.info(f"📊 Total unique entities: {len(entities)}")

            return True

        except Exception as e:
            logger.error(f"Pipeline execution failed: {e}")
            return False

    def consolidate_results(self, processed_dir: str, output_file: str):
        """Consolidate processed JSON files into a single output."""
        processed_path = Path(processed_dir)
        output_path = Path(output_file)
        
        logger.info(f"📂 Reading processed files from {processed_path}")
        
        all_entities = []
        files_processed = 0
        
        for file_path in processed_path.glob("*.json"):
            try:
                with open(file_path, 'r') as f:
                    data = json.load(f)
                    
                if isinstance(data, list):
                    entities = data
                elif isinstance(data, dict) and 'entities' in data:
                    entities = data['entities']
                elif isinstance(data, dict) and 'results' in data:
                     # Handle already flattened results if needed, but usually we consolidate raw entities
                     # For now, assume we are consolidating raw entities from checkpoints/processed files
                     entities = data['results'] if isinstance(data['results'], list) else []
                else:
                    logger.warning(f"⚠️ Unknown format in {file_path.name}")
                    continue
                    
                for entity in entities:
                    if 'source_file' not in entity:
                        entity['source_file'] = file_path.stem + ".txt"
                        
                all_entities.extend(entities)
                files_processed += 1
                
            except Exception as e:
                logger.error(f"❌ Failed to read {file_path.name}: {e}")

        logger.info(f"✅ Loaded {len(all_entities)} entities from {files_processed} files")

        # Deduplicate
        logger.info("🔄 Running semantic deduplication...")
        deduplicated_entities = self.semantic_deduplicator.apply_semantic_deduplication(all_entities)
        
        # Save
        logger.info(f"💾 Saving consolidated results to {output_path}")
        self.save_results(deduplicated_entities, str(output_path))
        logger.info("🎉 Consolidation complete!")

    def apply_mappings_to_file(self, input_file: str):
        """Apply mappings to an existing JSON file."""
        input_path = Path(input_file)
        logger.info(f"📂 Reading entities from {input_path}")
        
        with open(input_path, 'r') as f:
            data = json.load(f)
            
        if isinstance(data, dict) and 'results' in data:
            entities = data['results']['cdm_entities']
            # Flatten for mapping if it's the structured format
            flat_entities = []
            for etype, elist in entities.items():
                for e in elist:
                    e['entity_type'] = etype # Ensure type is preserved
                    flat_entities.append(e)
            entities = flat_entities
            is_flat = True 
            is_structured = True
        elif isinstance(data, list):
            entities = data
            is_flat = False
            is_structured = False
        else:
            logger.error("❌ Unknown file format")
            return

        logger.info(f"🚀 Starting mapping for {len(entities)} entities...")
        
        updated_entities = []
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = []
            for entity in entities:
                futures.append(executor.submit(self._process_mapping_entity, entity, is_flat))
                
            for future in tqdm(as_completed(futures), total=len(entities)):
                updated_entities.append(future.result())
        
        # Save results
        # If structured, we can just use save_results which re-groups them
        # But save_results expects a list of entities with 'entity_type'
        self.save_results(updated_entities, str(input_path))
        logger.info(f"💾 Mapped results saved to {input_path}")

    def _process_mapping_entity(self, entity: Dict, is_flat: bool) -> Dict:
        """Process a single entity for mapping."""
        term = entity.get('term') if is_flat else entity.get('entity')
        entity_type = entity.get('entity_type') or entity.get('categories')
        
        if not term:
            return entity
            
        # Check if mapping is missing
        needs_mapping = False
        if is_flat:
            if not entity.get('Bioportal') or not entity.get('OLS'):
                needs_mapping = True
        else:
            if 'comprehensive_mapping' not in entity:
                needs_mapping = True
                
        if needs_mapping and self.comprehensive_mapper:
            try:
                # Map using comprehensive mapper
                mapping_result = self.comprehensive_mapper.map_entity_comprehensive(term, entity_type)
                
                if is_flat:
                    bioportal_list = mapping_result.get('bioportal_mappings', [])
                    bioportal = bioportal_list[0].get('concept_id', '') if bioportal_list else ''
                    
                    ols_list = mapping_result.get('ols_mappings', [])
                    ols = ols_list[0].get('iri', '') if ols_list else ''
                    
                    if bioportal: entity['Bioportal'] = bioportal
                    if ols: entity['OLS'] = ols
                    
                    # Also update UMLS/OMOP if missing
                    umls_list = mapping_result.get('umls_mappings', [])
                    umls = umls_list[0].get('umls_cui', '') if umls_list else ''
                    if umls and not entity.get('UMLS_ID'): entity['UMLS_ID'] = umls
                    
                else:
                    entity['comprehensive_mapping'] = mapping_result
                    
            except Exception:
                pass
                
        return entity

    def enrich_definitions(self, input_file: str):
        """Enrich existing entities with Definitions, Aliases, and Examples using LLM."""
        input_path = Path(input_file)
        logger.info(f"📂 Reading entities for enrichment from {input_path}")
        
        with open(input_path, 'r') as f:
            data = json.load(f)
            
        # Handle structure
        if isinstance(data, dict) and 'results' in data and 'cdm_entities' in data['results']:
            # Structured format
            entities_map = data['results']['cdm_entities']
            all_entities = []
            for etype, elist in entities_map.items():
                for e in elist:
                    e['entity_type'] = etype # Ensure type is present
                    all_entities.append(e)
            entities = all_entities
            is_structured = True
        elif isinstance(data, list):
            entities = data
            is_structured = False
        else:
            logger.error("❌ Unknown format")
            return

        logger.info(f"🚀 Starting enrichment for {len(entities)} entities...")
        
        # Filter entities that need enrichment
        to_enrich = [e for e in entities if not e.get('definition') or not e.get('aliases')]
        logger.info(f"ℹ️  {len(to_enrich)} entities need enrichment")
        
        # Batch process
        batch_size = 20
        for i in tqdm(range(0, len(to_enrich), batch_size)):
            batch = to_enrich[i:i+batch_size]
            self._enrich_batch(batch)
            
        # Save results
        self.save_results(entities, str(input_path))
        logger.info(f"💾 Enriched results saved to {input_path}")

    def _enrich_batch(self, batch: List[Dict]):
        """Enrich a batch of entities using LLM."""
        if not batch: return
        
        terms = [e.get('entity', e.get('term')) for e in batch]
        terms_str = "\n".join([f"- {t} ({e.get('entity_type', 'UNKNOWN')})" for t, e in zip(terms, batch)])
        
        prompt = f"""You are a biomedical expert. Provide Definition, Aliases, and Examples for the following terms.
        
TERMS:
{terms_str}

OUTPUT FORMAT:
- [Term] | Definition: [Brief definition] | Aliases: [Alias1, Alias2] | Examples: [Ex1, Ex2]

Provide one line per term. Start immediately.
"""
        try:
            response = self.llm_client.call_llm(prompt)
            lines = response.strip().split('\n')
            
            # Parse response and update entities
            results_map = {}
            for line in lines:
                parts = line.split('|')
                if len(parts) < 2: continue
                
                term_part = parts[0].strip()
                # Remove bullet and type if present
                term_match = re.match(r'^(?:[\-\*0-9\.]+\s*)?(.+?)(?:\s*\(.*\))?$', term_part)
                if term_match:
                    term_clean = term_match.group(1).strip()
                    
                    definition = ""
                    aliases = []
                    examples = []
                    
                    for part in parts[1:]:
                        part = part.strip()
                        if part.lower().startswith("definition:"):
                            definition = part[11:].strip()
                        elif part.lower().startswith("aliases:"):
                            aliases_str = part[8:].strip()
                            if aliases_str and aliases_str.lower() != "none":
                                aliases = [a.strip() for a in aliases_str.split(',')]
                        elif part.lower().startswith("examples:"):
                            examples_str = part[9:].strip()
                            if examples_str and examples_str.lower() != "none":
                                examples = [e.strip() for e in examples_str.split(',')]
                                
                    results_map[term_clean.lower()] = {
                        'definition': definition,
                        'aliases': aliases,
                        'examples': examples
                    }
            
            # Update batch objects
            for entity in batch:
                term = entity.get('entity', entity.get('term', '')).strip()
                if term.lower() in results_map:
                    res = results_map[term.lower()]
                    if not entity.get('definition'): entity['definition'] = res['definition']
                    if not entity.get('aliases'): entity['aliases'] = ", ".join(res['aliases'])
                    if not entity.get('examples'): entity['examples'] = "; ".join(res['examples'])
                    
        except Exception as e:
            logger.error(f"Enrichment batch failed: {e}")
