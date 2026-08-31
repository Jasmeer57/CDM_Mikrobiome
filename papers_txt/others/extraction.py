import os
import re
import json
import time
import requests
import argparse
import numpy as np
import faiss
from openai import OpenAI
from collections import defaultdict
from tqdm import tqdm
from thefuzz import process as fuzzy_process
from sentence_transformers import SentenceTransformer, util

# --- Configuration ---
# Set the directory containing your .txt paper files
INPUT_DIRECTORY = "/home/jkalra/Downloads/CDM/papers_txt"
# The name of the final JSON output file
OUTPUT_FILE = "master_terminology_dictionary.json"
# The name for the cached embeddings and FAISS index files
EMBEDDINGS_FILE = "corpus_embeddings.npy"
FAISS_INDEX_FILE = "corpus_index.faiss"

# --- Model & Processing Parameters ---
# Model to use for LLM tasks (ensure this is running in Ollama)
LLM_MODEL_NAME = "dee"
# Model for creating text embeddings
EMBEDDING_MODEL_NAME = 'all-MiniLM-L6-v2'
# Threshold for fuzzy string matching to merge similar terms
FUZZY_DEDUP_THRESHOLD = 90
# Threshold for semantic similarity to merge conceptually similar terms
SEMANTIC_DEDUP_THRESHOLD = 0.95
# Number of top terms to include in the final report
TOP_K_TERMS = 50
# Number of text chunks to retrieve for the RAG-based extraction
RAG_RETRIEVAL_COUNT = 30
# Max examples to find for each term
MAX_EXAMPLES_PER_TERM = 3

# --- Scoring Weights ---
# These weights are used to calculate the final confidence_score
SCORE_WEIGHT_RELEVANCE = 0.5 # Based on frequency and quality
SCORE_WEIGHT_SEMANTIC = 0.5 # Based on similarity to the core topic

# --- LLM Client Setup for Local Ollama ---
try:
    client = OpenAI(
        base_url="http://localhost:11434/v1",
        api_key="ollama"  # Required by the library, but not used by Ollama
    )
    print("✅ OpenAI client configured for Ollama.")
except Exception as e:
    print(f"❌ Error configuring OpenAI client for Ollama: {e}")
    print("   Please ensure Ollama is running and the model is available.")
    exit()

# --- Gold Standard & Boost Keywords ---
# These keywords help identify high-value terms for the "is_gold_standard" flag
# and are used in quality scoring.
CDM_CORE_KEYWORDS = {
    'diversity', 'richness', 'evenness', 'alpha_diversity', 'beta_diversity',
    'pcoa', 'nmds', 'otu', 'asv', 'qiime', 'mothur', 'dada2', 'unifrac', 'bray_curtis',
    'metadata', 'sample', 'host', 'patient', 'subject_id', 'age', 'sex', 'gender',
    'bmi', 'treatment', 'control_group', 'read_count', 'sequencing_depth', 'quality_score',
    'sequencing_protocol', 'taxonomy', 'abundance', 'relative_abundance',
    'cag', 'co_abundance_group', 'gene', 'ko', 'kegg', 'picrust', 'lefse',
    'cluster', 'correlation', 'network', 'microbiome', 'microbiota', 'gut', 'fecal',
    '16s_rrna', 'species', 'genus', 'family', 'order', 'class', 'phylum'
}

def load_stopwords():
    """Downloads a generic list of stopwords to filter out common, non-technical words."""
    url = "https://gist.githubusercontent.com/eyturner/3d56f6a194f411af9f29df4c9d4a4e6e/raw/63b6dbaf2719392cb2c55eb07a6b1d4e758cc16d/20k.txt"
    try:
        response = requests.get(url)
        response.raise_for_status()
        stopwords = set(response.text.strip().split('\n'))
        print(f"  - Loaded {len(stopwords)} stopwords.")
        return stopwords
    except Exception as e:
        print(f"⚠️ Warning: Could not download stopwords: {e}. Proceeding without them.")
        return set()

def preprocess_text(text):
    """Removes common boilerplate sections like references from the end of a paper."""
    noise_pattern = re.compile(
        r"(\n\s*(?:References|Acknowledgements?|Author Contributions?|Funding|Competing interests?)\s*.*?)(?=\n\s*\w|\Z)",
        re.DOTALL | re.IGNORECASE
    )
    return re.sub(noise_pattern, "\n", text)

def clean_and_validate_term(term_str, stopwords_set):
    """
    Cleans a raw extracted term into a standardized snake_case format and validates it
    against a set of rules to filter out noise. This function is aggressively tuned to
    remove conversational junk from the LLM output.
    """
    if not isinstance(term_str, str) or len(term_str.split()) > 7:
        return None

    # Remove list-like prefixes (a., 1., b))
    cleaned = re.sub(r'^[a-z0-9]\s*[\)\.]\s*', '', term_str.strip())
    
    # Standardize to snake_case
    cleaned = re.sub(r'[\s-]+', '_', cleaned.lower())
    
    # Remove any characters that are not alphanumeric or underscore
    cleaned = re.sub(r'[^\w_]', '', cleaned).strip('_')

    # Aggressively strip common conversational/junk prefixes from the LLM
    junk_prefixes = [
        'and_', 'with_', 'the_', 'a_', 'b_', 'c_', 'd_', 'eg_', 'keywords_', 
        'in_', 'of_', 'to_', 'for_', 'on_', 'is_', 'which_', 'suggesting_'
    ]
    for prefix in junk_prefixes:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
    
    cleaned = cleaned.strip('_')

    # Final validation checks
    if len(cleaned) < 4:
        return None
    if re.fullmatch(r'[\d_.,]+', cleaned) or re.fullmatch(r'(19|20)\d{2}', cleaned):
        return None
    if not re.search(r'[a-z]', cleaned): # Must contain at least one letter
        return None
    if re.search(r'^(fig|figure|table|additional_file)s?_\w*\d*$', cleaned):
        return None
    if 'et_al' in cleaned or not re.match(r'^[a-z0-9_]+$', cleaned):
        return None
    if cleaned.startswith('_') or cleaned.endswith('_') or '__' in cleaned:
        return None
    if cleaned in stopwords_set:
        return None
    if len(cleaned.split('_')) > 7:
        return None
        
    return cleaned

def robust_split_terms(llm_response):
    """Splits the LLM's comma-separated string of terms into a list."""
    response = re.sub(r'^.*?:\s*', '', llm_response, flags=re.IGNORECASE)
    response = re.sub(r'\s*<.*?>\s*', '', response)
    response = re.sub(r'\n\s*\d+\.\s*', ',', response)
    response = re.sub(r'[\n;]', ',', response)
    parts = [s.strip() for s in response.split(',') if s.strip()]
    return [p.strip().strip('"\'') for p in parts]

def get_text_chunks(directory, files_to_process=None):
    """
    Reads specified .txt files, preprocesses them, and splits them into overlapping chunks.
    If files_to_process is None, it processes all files in the directory.
    """
    all_chunks = []
    chunk_to_filename_map = []
    files = [f for f in os.listdir(directory) if f.endswith('.txt')]
    if files_to_process:
        files = [f for f in files if f in files_to_process]

    for filename in tqdm(files, desc="Chunking Documents"):
        filepath = os.path.join(directory, filename)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                text = preprocess_text(f.read())
            words = text.split()
            for i in range(0, len(words), 75):
                chunk = " ".join(words[i:i+150])
                if chunk.strip():
                    all_chunks.append(chunk)
                    chunk_to_filename_map.append(filename)
        except Exception as e:
            print(f"⚠️ Warning: Could not read or process {filename}: {e}")
    return all_chunks, chunk_to_filename_map

def extract_terms_from_full_text(text_content, filename, model_name, stopwords_set):
    """Extracts terms from the full text of a single document with a stricter prompt."""
    print(f"  - Extracting terms from full text of {filename}...")
    prompt = (
        "You are an expert ontology creator for a microbiome Common Data Model. "
        "From the text below, extract up to 50 key technical terms. "
        "Focus on specific concepts related to methods, data, and analysis. "
        "YOU MUST ONLY return a single line of comma-separated snake_case terms. "
        "DO NOT include sentences, explanations, or any text before or after the list. "
        "DO NOT start terms with conjunctions, articles, or list markers (e.g., 'and', 'a', '1.'). "
        "Example: gut_microbiota,16s_rrna,alpha_diversity,pcoa_analysis"
        f"\n\n--- FULL TEXT ---\n{text_content}\n--- END TEXT ---"
    )
    try:
        completion = client.chat.completions.create(
            model=model_name, messages=[{"role": "user", "content": prompt}]
        )
        raw_response = completion.choices[0].message.content.strip()
        raw_terms = robust_split_terms(raw_response)
        valid_terms = [clean_and_validate_term(t, stopwords_set) for t in raw_terms]
        return [t for t in valid_terms if t]
    except Exception as e:
        print(f"    - Error extracting terms from {filename}: {e}")
        return []

def extract_terms_with_rag(context_chunks, model_name, stopwords_set):
    """Uses a RAG approach to extract high-quality 'gold standard' terms with a stricter prompt."""
    print("  - Performing RAG-based extraction...")
    context_str = "\n---\n".join(context_chunks)
    prompt = (
        "You are a 'golden standard' ontology creator for a microbiome Common Data Model. "
        "From the text below, identify the most important recurring concepts. "
        "Focus on experimental variables, methods, taxonomic ranks, and analysis metrics. "
        "YOU MUST ONLY return a single line of comma-separated snake_case terms. "
        "DO NOT include sentences, explanations, or any text before or after the list. "
        "DO NOT start terms with conjunctions, articles, or list markers (e.g., 'and', 'a', '1.'). "
        "Example: gut_microbiota,16s_rrna,alpha_diversity,pcoa_analysis"
        f"\n\n--- CONTEXT EXCERPTS ---\n{context_str}\n--- END EXCERPTS ---"
    )
    try:
        completion = client.chat.completions.create(
            model=model_name, messages=[{"role": "user", "content": prompt}]
        )
        raw_response = completion.choices[0].message.content.strip()
        raw_terms = robust_split_terms(raw_response)
        valid_terms = [clean_and_validate_term(t, stopwords_set) for t in raw_terms]
        return [t for t in valid_terms if t]
    except Exception as e:
        print(f"    - RAG extraction error: {e}")
        return []

def define_and_categorize_batch(terms_list, model_name):
    """Uses the LLM to generate both a definition and a category for a batch of terms."""
    print(f"\nDefining and categorizing {len(terms_list)} unique concepts...")
    results = {}
    term_chunks = [terms_list[i:i+25] for i in range(0, len(terms_list), 25)]
    categories = [
        "Taxonomic Rank", "Methodology", "Data Analysis", "Biological Concept",
        "Metric", "Study Population", "Genetic Component", "Bioinformatics Tool",
        "Database", "Statistical Method", "Uncategorized"
    ]
    for chunk in tqdm(term_chunks, desc="Defining & Categorizing Batches"):
        prompt = (
            "You are a bio-ontology expert. For each term below, provide a concise, one-sentence definition "
            f"and assign it to ONE of the following categories: {', '.join(categories)}. "
            "Return ONLY a valid JSON object with the format: "
            "{\"term1\": {\"definition\": \"def1\", \"category\": \"cat1\"}, ...}. No other text."
            f"\n\nTerms: {', '.join(chunk)}"
        )
        try:
            completion = client.chat.completions.create(
                model=model_name, messages=[{"role": "user", "content": prompt}]
            )
            response_text = completion.choices[0].message.content
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                chunk_res = json.loads(json_match.group(0))
                if isinstance(chunk_res, dict):
                    results.update(chunk_res)
        except Exception as e:
            print(f"    - Batch definition/categorization error: {e}")
            for term in chunk:
                if term not in results:
                    results[term] = {"definition": "Definition not found.", "category": "Uncategorized"}
    return results

def find_term_examples(term, aliases, all_chunks, chunk_map):
    """Scans text chunks to find and return a few example sentences for a given term."""
    examples = set()
    all_forms_spaced = [t.replace('_', ' ') for t in [term] + list(aliases)]
    pattern = re.compile(r'\b(' + '|'.join(re.escape(f) for f in all_forms_spaced) + r')\b', re.IGNORECASE)
    for chunk in all_chunks:
        if len(examples) >= MAX_EXAMPLES_PER_TERM: break
        if pattern.search(chunk):
            sentences = re.split(r'(?<=\.)\s+', chunk)
            for sentence in sentences:
                if pattern.search(sentence):
                    cleaned_sentence = sentence.strip().replace('\n', ' ')
                    if cleaned_sentence:
                        examples.add(cleaned_sentence)
                        if len(examples) >= MAX_EXAMPLES_PER_TERM: break
    return list(examples)

def calculate_quality_score(term):
    """Calculates a heuristic quality score for a term."""
    score = 0.5
    if '_' in term: score += 0.2
    if term in CDM_CORE_KEYWORDS: score += 0.3
    return min(score, 1.0)

def main():
    """Main function to orchestrate the entire terminology extraction pipeline."""
    start_time = time.time()
    parser = argparse.ArgumentParser(description="Advanced terminology extractor for scientific papers.")
    parser.add_argument("--model", type=str, default=LLM_MODEL_NAME, help="LLM model name to use.")
    parser.add_argument("--file", type=str, default=None, help="Run on a single file instead of the whole directory.")
    args = parser.parse_args()
    model_name = args.model

    if not os.path.exists(INPUT_DIRECTORY) or not os.listdir(INPUT_DIRECTORY):
        print(f"❌ Error: Input directory '{INPUT_DIRECTORY}' is empty or not found.")
        return

    all_files_in_dir = [f for f in os.listdir(INPUT_DIRECTORY) if f.endswith('.txt')]
    files_for_extraction = all_files_in_dir
    output_file = OUTPUT_FILE

    if args.file:
        if args.file in all_files_in_dir:
            print(f"--- Running in SINGLE-FILE mode: {args.file} ---")
            files_for_extraction = [args.file]
            output_file = f"single_file_analysis_{os.path.splitext(args.file)[0]}.json"
        else:
            print(f"❌ Error: File '{args.file}' not found in '{INPUT_DIRECTORY}'.")
            return
    else:
        print(f"--- Running in BATCH mode on {len(all_files_in_dir)} files ---")

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

    print("\n--- Phase 2: Extracting terms using hybrid approach ---")
    stopwords_set = load_stopwords()
    term_to_sources = defaultdict(set)
    term_refinement_status = defaultdict(bool)
    query_embedding = embed_model.encode(["microbiome common data model, experimental factors, and analysis methods"])
    _, I = index.search(query_embedding.astype('float32'), RAG_RETRIEVAL_COUNT)
    retrieved_chunks = [all_chunks[i] for i in I[0]]
    rag_terms = extract_terms_with_rag(retrieved_chunks, model_name, stopwords_set)
    for term in rag_terms:
        for i in I[0]:
            term_to_sources[term].add(chunk_to_filename_map[i])
    print(f"  - Extracted {len(rag_terms)} initial terms from RAG pass.")

    for filename in files_for_extraction:
        filepath = os.path.join(INPUT_DIRECTORY, filename)
        with open(filepath, 'r', encoding='utf-8') as f:
            full_text = preprocess_text(f.read())
        full_text_terms = extract_terms_from_full_text(full_text, filename, model_name, stopwords_set)
        for term in full_text_terms:
            term_to_sources[term].add(filename)
            term_refinement_status[term] = True
    print(f"  - Completed full-text extraction pass.")

    print(f"\n--- Phase 3: Deduplicating {len(term_to_sources)} total terms ---")
    corpus_terms = list(term_to_sources.keys())
    final_sources = term_to_sources.copy()
    aliases = defaultdict(set)
    if len(corpus_terms) > 1:
        corpus_embs = embed_model.encode(corpus_terms, convert_to_tensor=True, show_progress_bar=True)
        clusters = util.community_detection(corpus_embs, min_community_size=2, threshold=SEMANTIC_DEDUP_THRESHOLD)
        for cluster in clusters:
            cluster_terms = [corpus_terms[i] for i in cluster]
            canonical = max(cluster_terms, key=lambda t: (len(final_sources.get(t, [])), len(t)))
            for t in cluster_terms:
                if t != canonical:
                    final_sources[canonical].update(final_sources.pop(t, set()))
                    term_refinement_status[canonical] = term_refinement_status[canonical] or term_refinement_status.pop(t, False)
                    aliases[canonical].add(t)
    print(f"  - After semantic dedup: {len(final_sources)} terms")

    print("\n--- Phase 4: Enriching final concepts ---")
    final_concepts = list(final_sources.keys())
    enriched_data = define_and_categorize_batch(final_concepts, model_name)

    print("\n--- Phase 5: Scoring and ranking all concepts ---")
    total_files_in_corpus = len(all_files_in_dir)
    scored_terms = []
    
    if final_concepts:
        term_embeddings = embed_model.encode(final_concepts, show_progress_bar=True, convert_to_numpy=True)
        similarities = util.cos_sim(query_embedding, term_embeddings)[0].numpy()

    for i, term in enumerate(tqdm(final_concepts, desc="Final Scoring")):
        sources = final_sources[term]
        file_count = len(sources)
        
        relevance_score = (file_count / total_files_in_corpus) * 0.7 + calculate_quality_score(term) * 0.3
        semantic_score = similarities[i]

        confidence_score = (relevance_score * SCORE_WEIGHT_RELEVANCE) + (semantic_score * SCORE_WEIGHT_SEMANTIC)

        is_gold = term in CDM_CORE_KEYWORDS or term_refinement_status.get(term, False)
        term_info = enriched_data.get(term, {"definition": "Definition not found.", "category": "Uncategorized"})
        
        scored_terms.append({
            "canonical_term": term,
            "primary_form": term.replace('_', ' '),
            "entity_label": term.replace('_', ' ').title(),
            "gold_category": term_info['category'],
            "frequency": file_count,
            "file_count": file_count,
            "relevance_score": round(relevance_score, 2),
            "semantic_score": round(float(semantic_score), 2),
            "is_gold_standard": is_gold,
            "model_sources": [model_name],
            "examples": find_term_examples(term, aliases.get(term, set()), all_chunks, chunk_to_filename_map),
            "definition": term_info['definition'],
            "aliases": sorted(list(aliases.get(term, []))),
            "source_files": sorted(list(sources)),
            "confidence_score": round(confidence_score, 4),
            "metrics": {
                "corpus_frequency": file_count,
                "quality_score": round(calculate_quality_score(term), 2),
                "semantic_similarity": round(float(semantic_score), 2)
            }
        })

    ranked = sorted(scored_terms, key=lambda x: x['confidence_score'], reverse=True)

    print("\n--- Phase 6: Generating final report ---")
    final_ranked_terms = ranked
    if args.file:
         final_ranked_terms = [term for term in ranked if args.file in term['source_files']]

    report = {
        "report_metadata": {
            "total_files_in_corpus": total_files_in_corpus,
            "files_in_this_run": files_for_extraction,
            "llm_model_used": model_name,
            "embedding_model_used": EMBEDDING_MODEL_NAME,
            "total_unique_concepts_found": len(ranked),
            "concepts_in_report": len(final_ranked_terms[:TOP_K_TERMS]),
            "top_k_selected": TOP_K_TERMS
        },
        "scored_terms": final_ranked_terms[:TOP_K_TERMS]
    }

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2)

    end_time = time.time()
    print(f"\n✅ Done! Report saved to '{output_file}'.")
    print(f"   Total execution time: {end_time - start_time:.2f} seconds.")

if __name__ == "__main__":
    main()

