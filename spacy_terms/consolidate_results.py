import os
import json
import pandas as pd
import argparse
from pathlib import Path
from typing import List, Dict
from tqdm import tqdm
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def consolidate_results(input_dir: str, output_file_base: str):
    """
    Reads all *_ensemble_results.json files from input_dir and consolidates them.
    Produces:
    1. {output_file_base}_all_occurrences.csv: Every term instance with paper source.
    2. {output_file_base}_corpus_summary.csv: Unique terms with corpus frequency.
    """
    input_path = Path(input_dir)
    json_files = list(input_path.glob("*_ensemble_results.json"))
    
    if not json_files:
        logger.warning(f"No JSON results found in {input_dir}")
        return

    logger.info(f"Found {len(json_files)} result files. Consolidating...")
    
    all_occurrences = []
    
    for json_file in tqdm(json_files, desc="Reading files"):
        try:
            with open(json_file, 'r') as f:
                data = json.load(f)
                
            paper_id = data.get('file', json_file.stem)
            terms = data.get('terms', [])
            
            for term_data in terms:
                raw_term = term_data.get('term', '')
                if not raw_term: continue
                
                # --- Cleaning ---
                # 1. Normalize whitespace (remove newlines)
                clean_term = " ".join(raw_term.split())
                
                # 2. Normalize unicode (ligatures)
                import unicodedata
                clean_term = unicodedata.normalize('NFKC', clean_term)
                
                # 3. Filter Generic/Methodological Terms
                # (Simple heuristic: if it ends with 'analysis', 'data', 'study', etc.)
                lower_term = clean_term.lower()
                blocklist = ['analysis', 'data', 'study', 'evaluation', 'variable', 'method', 'result', 'conclusion', 'background', 'aim', 'objective']
                if any(lower_term.endswith(x) for x in blocklist) or any(x in lower_term for x in ['copyright', 'author', 'et al']):
                    continue
                    
                # Flatten basic info
                row = {
                    'paper_id': paper_id,
                    'term': clean_term, # Use cleaned term
                    'score': term_data.get('score'),
                    'in_paper_frequency': term_data.get('frequency'),
                    'source_models': ",".join(term_data.get('source_model', '').split(',')), 
                    'is_valid': term_data.get('validation', {}).get('is_valid', 'N/A')
                }
                
                # Add mapping info
                if 'mappings' in term_data:
                    for source, matches in term_data['mappings'].items():
                        if matches:
                            row[f'mapping_{source}'] = matches[0].get('id')
                            
                all_occurrences.append(row)
                
        except Exception as e:
            logger.error(f"Error reading {json_file}: {e}")

    # 1. Save All Occurrences
    df_all = pd.DataFrame(all_occurrences)
    all_out = f"{output_file_base}_all_occurrences.csv"
    df_all.to_csv(all_out, index=False)
    logger.info(f"Saved all occurrences to {all_out} ({len(df_all)} rows)")
    
    # 2. Create Corpus Summary (Unique Terms)
    if not df_all.empty:
        # Create normalized column for grouping
        df_all['term_lower'] = df_all['term'].str.lower()
        
        # Group by normalized term
        summary = df_all.groupby('term_lower').agg({
            'term': lambda x: x.mode().iloc[0] if not x.mode().empty else x.iloc[0], # Most frequent casing
            'paper_id': 'nunique',  # Count of unique papers
            'in_paper_frequency': 'sum', # Total frequency
            'score': 'mean',
            'is_valid': 'first'
        }).reset_index(drop=True)
        
        summary.rename(columns={'paper_id': 'paper_count', 'in_paper_frequency': 'total_frequency'}, inplace=True)
        summary.sort_values(['paper_count', 'total_frequency'], ascending=[False, False], inplace=True)
        
        # --- Semantic Quality Filter (New) ---
        logger.info("Running Semantic Quality Filter...")
        try:
            from sentence_transformers import SentenceTransformer, util
            
            # Load model (lightweight)
            model = SentenceTransformer('all-MiniLM-L6-v2')
            
            # Prototypes of generic/noise concepts
            NOISE_PROTOTYPES = [
                "scientific study", "research analysis", "statistical method", "data collection",
                "experimental result", "clinical trial", "literature review", "author contribution",
                "funding source", "conflict of interest", "copyright statement", "figure legend",
                "table caption", "supplementary material", "university department", "correspondence address",
                "p-value", "confidence interval", "standard deviation", "sample size"
            ]
            
            terms = summary['term'].tolist()
            
            # Encode terms and noise
            term_embeddings = model.encode(terms, convert_to_tensor=True)
            noise_embeddings = model.encode(NOISE_PROTOTYPES, convert_to_tensor=True)
            
            scores = util.cos_sim(term_embeddings, noise_embeddings)
            
            keep_indices = []
            for i in range(len(terms)):
                if scores[i].max().item() < 0.75:
                    keep_indices.append(i)
            
            summary = summary.iloc[keep_indices].reset_index(drop=True)
            logger.info(f"Semantic Filter: {len(terms)} -> {len(summary)} terms")
            
        except ImportError:
            logger.warning("Skipping semantic filter (missing dependencies)")
        except Exception as e:
            logger.warning(f"Semantic filter failed: {e}")

        # --- Corpus-Level Typo Correction ---
        logger.info("Running corpus-level typo correction...")
        try:
            from rapidfuzz import fuzz
            # Model already loaded above if available
            
            # Get terms and frequencies (re-fetch after filtering)
            terms = summary['term'].tolist()
            freqs = summary['total_frequency'].tolist()
            
            # Re-compute embeddings for filtered terms
            embeddings = model.encode(terms, convert_to_tensor=True)
            cosine_scores = util.cos_sim(embeddings, embeddings)
            
            # Map of corrections: bad_term -> good_term
            corrections = {}
            keep_indices = set(range(len(terms)))
            
            for i in range(len(terms)):
                if i not in keep_indices: continue
                
                for j in range(i + 1, len(terms)):
                    if j not in keep_indices: continue
                    
                    # Check semantic similarity first (fastest filter if using matrix)
                    if cosine_scores[i][j] < 0.90: continue
                    
                    # Check lexical similarity
                    if fuzz.ratio(terms[i], terms[j]) < 90: continue
                    
                    # Merge j into i (since i is more frequent due to sort)
                    corrections[terms[j]] = terms[i]
                    keep_indices.discard(j)
                    
                    # Update frequency
                    summary.at[i, 'total_frequency'] += summary.at[j, 'total_frequency']
                    summary.at[i, 'paper_count'] += summary.at[j, 'paper_count'] # Approximation
            
            # Filter DataFrame
            summary = summary.iloc[list(keep_indices)]
            logger.info(f"Corrected {len(corrections)} typos")
            
        except ImportError:
            logger.warning("Skipping typo correction (missing dependencies)")
        except Exception as e:
            logger.warning(f"Typo correction failed: {e}")
            
        summary_out = f"{output_file_base}_corpus_summary.csv"
        summary.to_csv(summary_out, index=False)
        logger.info(f"Saved corpus summary to {summary_out} ({len(summary)} unique terms)")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Consolidate SciSpaCy Results")
    parser.add_argument("--input_dir", default="output_ensemble_full", help="Directory containing result JSONs")
    parser.add_argument("--output_base", default="consolidated_results", help="Base name for output files")
    args = parser.parse_args()
    
    consolidate_results(args.input_dir, args.output_base)
