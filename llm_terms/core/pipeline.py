"""
CDM Pipeline Core Orchestrator
"""

import os
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional
from core.llm_client import LLMClient
from extractors.entity_extractor import CDMEntityExtractor
from core.semantic_deduplicator import SemanticDeduplicator
from core.entity_filter import EntityFilter
from core.biomedical_deduplicator import BioMistralDeduplicator
from biomedical.biomistral_validator import BioMistralValidator, BioMistralConfig
from mappers.omop_mapper import OMOPMapper
from mappers.umls import UMLSMapper
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
                 mapping_confidence_threshold: float = 0.7):
        self.config = config or PipelineConfig()
        self.llm_client = LLMClient(model or self.config.default_model, base_url or self.config.default_base_url)
        self.extractor = CDMEntityExtractor(self.llm_client)
        self.entity_config = CDMEntityConfig()
        self.semantic_deduplicator = SemanticDeduplicator(semantic_model, semantic_threshold)
        self.entity_filter = EntityFilter(strict_mode=True)

        # Initialize biomedical and mapping components
        self.enable_biomistral = enable_biomistral
        self.enable_biomistral_deduplication = enable_biomistral_deduplication
        self.enable_omop_mapping = enable_omop_mapping
        self.enable_umls_mapping = enable_umls_mapping
        self.enable_comprehensive_mapping = enable_comprehensive_mapping
        self.mapping_confidence_threshold = mapping_confidence_threshold

        if enable_biomistral:
            from biomedical.biomistral_validator import BioMistralValidator, BioMistralConfig
            biomistral_config = BioMistralConfig(model_name=biomistral_model)
            self.biomistral_validator = BioMistralValidator(biomistral_config)

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

    def chunk_text(self, text: str, chunk_size: int = None) -> List[tuple]:
        """Split text into overlapping chunks."""
        if chunk_size is None:
            chunk_size = self.extractor.calculate_optimal_chunk_size(len(text))

        overlap = self.extractor.calculate_overlap(chunk_size)

        chunks = []
        chunk_num = 1

        for i in range(0, len(text), chunk_size - overlap):
            chunk = text[i:i + chunk_size]
            if len(chunk) > 100:  # Only process substantial chunks
                chunks.append((chunk, chunk_num))
                chunk_num += 1

        logger.info(f"📊 Created {len(chunks)} chunks ({chunk_size} chars, {overlap} overlap)")
        return chunks

    def extract_entities(self, text: str, chunk_size: int = None) -> List[Dict]:
        """Extract CDM entities from text using parallel processing."""
        logger.info(f"🔍 Starting CDM entity extraction from {len(text)} characters")

        # Chunk the text
        chunks = self.chunk_text(text, chunk_size)

        # Process chunks in parallel
        all_entities = []
        with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
            futures = [executor.submit(self.extractor.extract_entities_from_chunk, chunk) for chunk in chunks]

            for future in as_completed(futures):
                try:
                    chunk_num, chunk_entities = future.result(timeout=self.llm_client.config['timeout'])
                    all_entities.extend(chunk_entities)
                except Exception as e:
                    logger.error(f"Error processing chunk: {e}")

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
            cleaned_entities = self.biomistral_validator.correct_entity_types(cleaned_entities)
            logger.info(f"✅ BioMistral validation: {len(cleaned_entities)} entities processed")

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
        unique_entities = filtered_entities

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
                'confidence': entity['confidence'],
                'source': entity['source']
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
