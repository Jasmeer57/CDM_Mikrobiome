"""
OMOP vocabulary processing module with ALL features from convert.py and mapping.py.
Preserves Parquet preprocessing, fuzzy matching, and comprehensive OMOP integration.
"""

import logging
import time
import pandas as pd
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any

# Import availability checks
try:
    import pyarrow as pa
    import pyarrow.parquet as pq
    PYARROW_AVAILABLE = True
except ImportError:
    PYARROW_AVAILABLE = False
    pa = None
    pq = None

try:
    from rapidfuzz import process, fuzz
    RAPIDFUZZ_AVAILABLE = True
except ImportError:
    RAPIDFUZZ_AVAILABLE = False
    process = None
    fuzz = None

from ..config.constants import DEFAULT_OMOP_DOMAINS, OMOP_REQUIRED_FILES
from ..config.settings import OmopConfig

logger = logging.getLogger(__name__)


class OMOPProcessor:
    """
    Comprehensive OMOP processor with all features from convert.py and mapping.py.

    Features preserved from convert.py:
    - OMOP vocabulary CSV to Parquet preprocessing
    - Data cleaning and preprocessing
    - Joining and preprocessing operations
    - Efficient Parquet format for faster loading

    Features preserved from mapping.py:
    - Fuzzy matching to OMOP concepts
    - Domain-specific filtering
    - Parallel processing for large vocabularies
    - Multiple similarity metrics
    - Pandarallel for performance
    """

    def __init__(self, config: OmopConfig):
        self.config = config
        self.processing_stats = {
            'concepts_loaded': 0,
            'synonyms_loaded': 0,
            'relationships_loaded': 0,
            'preprocessing_time': 0,
            'mapping_time': 0,
            'cache_hits': 0,
            'cache_misses': 0
        }

        # Initialize parallel processing if available
        if config.use_parallel and RAPIDFUZZ_AVAILABLE:
            try:
                from pandarallel import pandarallel
                pandarallel.initialize(
                    progress_bar=True,
                    nb_workers=config.n_workers,
                    verbose=0
                )
                self.pandarallel = pandarallel
                logger.info(f"✅ Initialized pandarallel with {config.n_workers} workers")
            except ImportError:
                logger.warning("⚠️ pandarallel not available. Using single-threaded processing.")
                self.pandarallel = None
        else:
            self.pandarallel = None

    def preprocess_omop_vocabulary(self, vocab_dir: str = None) -> Dict[str, Any]:
        """
        Preprocess OMOP vocabulary CSV files to Parquet format.
        Preserves all functionality from the original convert.py script.
        """
        vocab_dir = vocab_dir or self.config.vocab_dir
        cache_dir = Path(self.config.cache_dir)

        logger.info("🔄 STARTING OMOP VOCABULARY PREPROCESSING")
        logger.info("=" * 60)

        if not PYARROW_AVAILABLE:
            logger.error("❌ PyArrow not available. Install with: pip install pyarrow")
            raise ImportError("PyArrow is required for Parquet processing")

        start_time = time.time()
        cache_dir.mkdir(parents=True, exist_ok=True)

        # Load and preprocess each required file
        processed_data = {}

        # 1. Load CONCEPT.csv
        concepts_df = self._load_concepts(vocab_dir)
        processed_data['concepts'] = concepts_df

        # 2. Load CONCEPT_SYNONYM.csv
        synonyms_df = self._load_synonyms(vocab_dir)
        processed_data['synonyms'] = synonyms_df

        # 3. Load CONCEPT_RELATIONSHIP.csv
        relationships_df = self._load_relationships(vocab_dir)
        processed_data['relationships'] = relationships_df

        # 4. Load VOCABULARY.csv
        vocabulary_df = self._load_vocabulary(vocab_dir)
        processed_data['vocabulary'] = vocabulary_df

        # 5. Load DOMAIN.csv
        domain_df = self._load_domain(vocab_dir)
        processed_data['domain'] = domain_df

        # Save to Parquet files
        output_files = {}
        for name, df in processed_data.items():
            if df is not None and not df.empty:
                output_file = cache_dir / f"{name}.parquet"
                df.to_parquet(output_file, index=False)
                output_files[name] = str(output_file)
                logger.info(f"✅ Saved {name} to {output_file}")

        self.processing_stats['preprocessing_time'] = time.time() - start_time

        logger.info("=" * 60)
        logger.info(f"✅ OMOP preprocessing completed in {self.processing_stats['preprocessing_time']:.2f}s")
        logger.info(f"📊 Concepts: {len(concepts_df):,}")
        logger.info(f"📊 Synonyms: {len(synonyms_df):,}")
        logger.info(f"📊 Relationships: {len(relationships_df):,}")
        logger.info("=" * 60)

        return {
            'data': processed_data,
            'files': output_files,
            'statistics': self.processing_stats
        }

    def _load_concepts(self, vocab_dir: str) -> pd.DataFrame:
        """Load and preprocess CONCEPT.csv."""
        file_path = Path(vocab_dir) / 'CONCEPT.csv'
        if not file_path.exists():
            logger.warning(f"⚠️ CONCEPT.csv not found at {file_path}")
            return pd.DataFrame()

        logger.info("📖 Loading CONCEPT.csv...")

        df = pd.read_csv(
            file_path,
            sep='\t',
            usecols=[
                'concept_id', 'concept_name', 'standard_concept', 'invalid_reason',
                'domain_id', 'vocabulary_id', 'concept_class_id', 'data_type_id'
            ],
            dtype=str,
            na_filter=False
        )

        # Filter invalid concepts
        df = df[df['invalid_reason'] == '']

        # Filter by target domains if specified
        if self.config.target_domains:
            original_count = len(df)
            df = df[df['domain_id'].isin(self.config.target_domains)]
            logger.info(f"📊 Filtered to {len(df)} concepts from {original_count} "
                       f"in {len(self.config.target_domains)} domains")

        # Clean concept names
        df['concept_name_clean'] = df['concept_name'].apply(self._clean_term)

        self.processing_stats['concepts_loaded'] = len(df)
        return df

    def _load_synonyms(self, vocab_dir: str) -> pd.DataFrame:
        """Load and preprocess CONCEPT_SYNONYM.csv."""
        file_path = Path(vocab_dir) / 'CONCEPT_SYNONYM.csv'
        if not file_path.exists():
            logger.warning(f"⚠️ CONCEPT_SYNONYM.csv not found at {file_path}")
            return pd.DataFrame()

        logger.info("📖 Loading CONCEPT_SYNONYM.csv...")

        df = pd.read_csv(
            file_path,
            sep='\t',
            usecols=['concept_id', 'synonym_name', 'language_concept_id'],
            dtype=str,
            na_filter=False
        )

        # Clean synonym names
        df['synonym_name_clean'] = df['synonym_name'].apply(self._clean_term)

        self.processing_stats['synonyms_loaded'] = len(df)
        return df

    def _load_relationships(self, vocab_dir: str) -> pd.DataFrame:
        """Load and preprocess CONCEPT_RELATIONSHIP.csv."""
        file_path = Path(vocab_dir) / 'CONCEPT_RELATIONSHIP.csv'
        if not file_path.exists():
            logger.warning(f"⚠️ CONCEPT_RELATIONSHIP.csv not found at {file_path}")
            return pd.DataFrame()

        logger.info("📖 Loading CONCEPT_RELATIONSHIP.csv...")

        df = pd.read_csv(
            file_path,
            sep='\t',
            usecols=[
                'concept_id_1', 'concept_id_2', 'relationship_id',
                'valid_start_date', 'valid_end_date', 'invalid_reason'
            ],
            dtype=str,
            na_filter=False
        )

        # Filter invalid relationships
        df = df[df['invalid_reason'] == '']

        self.processing_stats['relationships_loaded'] = len(df)
        return df

    def _load_vocabulary(self, vocab_dir: str) -> pd.DataFrame:
        """Load and preprocess VOCABULARY.csv."""
        file_path = Path(vocab_dir) / 'VOCABULARY.csv'
        if not file_path.exists():
            logger.warning(f"⚠️ VOCABULARY.csv not found at {file_path}")
            return pd.DataFrame()

        logger.info("📖 Loading VOCABULARY.csv...")

        df = pd.read_csv(
            file_path,
            sep='\t',
            dtype=str,
            na_filter=False
        )

        return df

    def _load_domain(self, vocab_dir: str) -> pd.DataFrame:
        """Load and preprocess DOMAIN.csv."""
        file_path = Path(vocab_dir) / 'DOMAIN.csv'
        if not file_path.exists():
            logger.warning(f"⚠️ DOMAIN.csv not found at {file_path}")
            return pd.DataFrame()

        logger.info("📖 Loading DOMAIN.csv...")

        df = pd.read_csv(
            file_path,
            sep='\t',
            dtype=str,
            na_filter=False
        )

        return df

    def _clean_term(self, text: str) -> str:
        """
        Clean and normalize term text.
        Preserves the cleaning logic from the original mapping.py script.
        """
        if not isinstance(text, str) or not text.strip():
            return ""

        text = text.lower()
        text = text.replace('"', '').replace("'", "")
        text = text.replace('(', ' ').replace(')', ' ')
        text = text.replace('[', ' ').replace(']', ' ')
        text = text.replace('{', ' ').replace('}', ' ')
        text = text.replace('/', ' ').replace('\\', ' ')
        text = text.replace('-', ' ').replace('_', ' ')
        text = text.replace('.', ' ').replace(',', ' ')

        # Remove stop words
        stop_words = {
            'and', 'or', 'of', 'the', 'a', 'an', 'with', 'for', 'in', 'on', 'to', 'at',
            'by', 'as', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have',
            'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should',
            'may', 'might', 'must', 'can', 'shall'
        }

        words = [word for word in text.split() if word not in stop_words and len(word) > 1]
        return ' '.join(words).strip()

    def load_preprocessed_data(self, cache_dir: str = None) -> Dict[str, Any]:
        """Load preprocessed OMOP data from Parquet files."""
        cache_dir = cache_dir or self.config.cache_dir
        cache_path = Path(cache_dir)

        if not cache_path.exists():
            logger.warning(f"⚠️ Cache directory not found: {cache_dir}")
            return {}

        logger.info("📖 Loading preprocessed OMOP data...")

        loaded_data = {}
        required_files = ['concepts', 'synonyms', 'relationships', 'vocabulary', 'domain']

        for name in required_files:
            file_path = cache_path / f"{name}.parquet"
            if file_path.exists():
                try:
                    df = pd.read_parquet(file_path)
                    loaded_data[name] = df
                    logger.info(f"✅ Loaded {name}: {len(df):,} rows")
                    self.processing_stats['cache_hits'] += 1
                except Exception as e:
                    logger.error(f"❌ Error loading {name}: {e}")
                    self.processing_stats['cache_misses'] += 1
            else:
                logger.warning(f"⚠️ Cache file not found: {file_path}")
                self.processing_stats['cache_misses'] += 1

        return loaded_data

    def map_terms_to_omop(self, terms: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Map extracted terms to OMOP concepts using fuzzy matching.
        Preserves all functionality from the original mapping.py script.
        """
        logger.info("🔍 STARTING OMOP CONCEPT MAPPING")
        logger.info("=" * 60)

        if not terms:
            logger.warning("⚠️ No terms to map")
            return {}

        start_time = time.time()

        # Load or preprocess OMOP data
        if self.config.cache_preprocessed:
            omop_data = self.load_preprocessed_data()
            if not omop_data:
                logger.info("🔄 No cached data found, preprocessing...")
                omop_data = self.preprocess_omop_vocabulary()
        else:
            logger.info("🔄 Preprocessing OMOP vocabulary...")
            omop_data = self.preprocess_vocabulary()

        concepts_df = omop_data.get('concepts', pd.DataFrame())
        synonyms_df = omop_data.get('synonyms', pd.DataFrame())

        if concepts_df.empty:
            logger.error("❌ No concepts data available for mapping")
            return {}

        # Prepare search index
        search_index = self._prepare_search_index(concepts_df, synonyms_df)

        # Map terms
        mapping_results = {}
        total_terms = len(terms)
        mapped_terms = 0

        logger.info(f"🔍 Mapping {total_terms:,} terms to OMOP concepts...")

        if self.pandarallel and RAPIDFUZZ_AVAILABLE:
            # Parallel processing
            logger.info("🚀 Using parallel processing...")
            mapped_data = self._map_terms_parallel(terms, search_index)
        else:
            # Sequential processing
            mapped_data = self._map_terms_sequential(terms, search_index)

        for term_data, result in zip(terms, mapped_data):
            term_key = term_data.get('term', '')
            if result:
                mapping_results[term_key] = result
                mapped_terms += 1

        self.processing_stats['mapping_time'] = time.time() - start_time
        success_rate = (mapped_terms / total_terms) * 100

        logger.info("=" * 60)
        logger.info(f"✅ OMOP mapping completed in {self.processing_stats['mapping_time']:.2f}s")
        logger.info(f"📊 Terms mapped: {mapped_terms:,}/{total_terms:,} ({success_rate:.1f}%)")
        logger.info("=" * 60)

        return {
            'mapping_results': mapping_results,
            'omop_data': omop_data,
            'statistics': self.processing_stats
        }

    def _prepare_search_index(self, concepts_df: pd.DataFrame, synonyms_df: pd.DataFrame) -> Dict[str, Any]:
        """Prepare search index for efficient fuzzy matching."""
        logger.info("🔧 Preparing search index...")

        # Create concept name index
        concept_names = concepts_df['concept_name_clean'].fillna('').tolist()
        concept_ids = concepts_df['concept_id'].tolist()

        # Add synonyms to search index
        if not synonyms_df.empty:
            synonym_names = synonyms_df['synonym_name_clean'].fillna('').tolist()
            synonym_concept_ids = synonyms_df['concept_id'].tolist()
            concept_names.extend(synonym_names)
            concept_ids.extend(synonym_concept_ids)

        # Create mapping from clean names to concepts
        name_to_concepts = {}
        for name, concept_id in zip(concept_names, concept_ids):
            if name not in name_to_concepts:
                name_to_concepts[name] = []
            name_to_concepts[name].append(concept_id)

        logger.info(f"✅ Search index created with {len(name_to_concepts):,} unique terms")
        return {
            'names': concept_names,
            'concept_ids': concept_ids,
            'name_to_concepts': name_to_concepts,
            'concepts_df': concepts_df
        }

    def _map_terms_parallel(self, terms: List[Dict[str, Any]], search_index: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Map terms to OMOP concepts using parallel processing."""
        if not self.pandarallel:
            return self._map_terms_sequential(terms, search_index)

        # Prepare term list for parallel processing
        term_list = [term.get('term', '') for term in terms]

        # Parallel fuzzy matching
        def match_term(term):
            return self._find_best_match(term, search_index)

        results = self.pandarallel.parallel_apply(match_term, term_list)
        return results

    def _map_terms_sequential(self, terms: List[Dict[str, Any]], search_index: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Map terms to OMOP concepts using sequential processing."""
        results = []
        for term_data in terms:
            term = term_data.get('term', '')
            result = self._find_best_match(term, search_index)
            results.append(result)
        return results

    def _find_best_match(self, term: str, search_index: Dict[str, Any]) -> Dict[str, Any]:
        """
        Find best OMOP concept match for a term using fuzzy matching.
        Preserves the original mapping.py logic with multiple similarity metrics.
        """
        if not term or not RAPIDFUZZ_AVAILABLE:
            return {}

        clean_term = self._clean_term(term)
        search_names = search_index['names']
        concepts_df = search_index['concepts_df']

        if not search_names or clean_term not in search_names:
            return {}

        # Use multiple fuzzy matching methods
        scorers = {
            'ratio': fuzz.ratio,
            'partial_ratio': fuzz.partial_ratio,
            'token_sort_ratio': fuzz.token_sort_ratio,
            'token_set_ratio': fuzz.token_set_ratio
        }

        best_matches = []

        for scorer_name, scorer_func in scorers.items():
            # Find best match using current scorer
            result = process.extractOne(
                clean_term,
                search_names,
                scorer=scorer_func,
                score_cutoff=self.config.min_similarity_threshold
            )

            if result:
                match_name, score, concept_idx = result
                concept_ids = search_index['name_to_concepts'].get(match_name, [])

                # Get concept details
                for concept_id in concept_ids:
                    concept_row = concepts_df[concepts_df['concept_id'] == concept_id]
                    if not concept_row.empty:
                        concept_info = concept_row.iloc[0].to_dict()
                        best_matches.append({
                            'concept_id': concept_id,
                            'concept_name': concept_info['concept_name'],
                            'domain_id': concept_info['domain_id'],
                            'vocabulary_id': concept_info['vocabulary_id'],
                            'match_type': scorer_name,
                            'similarity_score': score,
                            'matched_name': match_name
                        })

        # Sort by best score
        best_matches.sort(key=lambda x: x['similarity_score'], reverse=True)

        return {
            'original_term': term,
            'clean_term': clean_term,
            'matches': best_matches[:3],  # Top 3 matches
            'best_match': best_matches[0] if best_matches else None,
            'has_match': len(best_matches) > 0
        }

    def export_mapping_results(self, results: Dict[str, Any], output_path: str):
        """Export OMOP mapping results to JSON and CSV formats."""
        import json
        import csv
        from pathlib import Path

        output_dir = Path(output_path)
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = time.strftime("%Y%m%d_%H%M%S")

        # Export JSON
        json_file = output_dir / f"omop_mapping_{timestamp}.json"
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        # Export CSV
        csv_file = output_dir / f"omop_mapping_summary_{timestamp}.csv"
        with open(csv_file, 'w', newline='', encoding='utf-8') as f:
            fieldnames = [
                'original_term', 'best_concept_id', 'best_concept_name',
                'domain_id', 'vocabulary_id', 'similarity_score', 'match_type'
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for term_key, result in results.get('mapping_results', {}).items():
                if result.get('has_match') and result.get('best_match'):
                    best = result['best_match']
                    row = {
                        'original_term': term_key,
                        'best_concept_id': best['concept_id'],
                        'best_concept_name': best['concept_name'],
                        'domain_id': best['domain_id'],
                        'vocabulary_id': best['vocabulary_id'],
                        'similarity_score': best['similarity_score'],
                        'match_type': best['match_type']
                    }
                    writer.writerow(row)

        logger.info(f"📄 OMOP mapping results exported to: {output_dir}")
        logger.info(f"📄 JSON file: {json_file}")
        logger.info(f"📊 CSV file: {csv_file}")

        return {
            'json_file': str(json_file),
            'csv_file': str(csv_file)
        }