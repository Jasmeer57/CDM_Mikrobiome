#!/usr/bin/env python3
"""
Add paper context to entities using embedding-based semantic search.

This script:
1. Loads the entities from cdm_entities_final_v2.json
2. Uses sentence embeddings to find the most relevant sentence from papers for each entity
3. Adds paper_context field with the actual sentence from the paper
4. Saves to cdm_entities_final_v3.json
"""

_CDM_ROOT = next(p for p in __import__("pathlib").Path(__file__).resolve().parents
                 if (p / ".cdm_root").is_file())  # repo root, found at run time
import json
import re
import sys
import logging
from pathlib import Path
from typing import Dict, Tuple, List
import numpy as np

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

try:
    from sentence_transformers import SentenceTransformer
    import torch
except ImportError:
    logger.error("Please install: pip install sentence-transformers torch")
    sys.exit(1)


def split_into_sentences(text: str) -> List[str]:
    """Split text into sentences."""
    # Simple sentence splitting - can be improved
    sentences = re.split(r'(?<=[.!?])\s+', text)
    return [s.strip() for s in sentences if len(s.strip()) > 20]


def extract_context_window(text: str, match_start: int, match_end: int, window_words: int = 30) -> Tuple[str, int]:
    """Extract a window of words around the match."""
    lines_before = text[:match_start].count('\n')
    line_number = lines_before + 1

    text_before = text[:match_start]
    text_after = text[match_end:]

    words_before = text_before.split()
    window_before = words_before[-window_words:] if len(words_before) > window_words else words_before

    words_after = text_after.split()
    window_after = words_after[:window_words] if len(words_after) > window_words else words_after

    matched_term = text[match_start:match_end]
    context = ' '.join(window_before) + ' ' + matched_term + ' ' + ' '.join(window_after)
    context = re.sub(r'\s+', ' ', context).strip()

    return context, line_number


def find_term_context_regex(term: str, papers: Dict[str, str], window_words: int = 30) -> Tuple[str, str]:
    """Find context using regex with multiple fallback strategies."""
    # Strategy 1: Exact word boundary match
    for paper_id, paper_text in papers.items():
        pattern = re.compile(rf'\b{re.escape(term)}\b', re.IGNORECASE)
        match = pattern.search(paper_text)
        if match:
            context, line_number = extract_context_window(paper_text, match.start(), match.end(), window_words)
            location = f"{paper_id}:{line_number}"
            return context, location

    # Strategy 2: Case-insensitive substring match (no word boundaries)
    for paper_id, paper_text in papers.items():
        if term.lower() in paper_text.lower():
            idx = paper_text.lower().find(term.lower())
            context, line_number = extract_context_window(paper_text, idx, idx + len(term), window_words)
            location = f"{paper_id}:{line_number}"
            return context, location

    # Strategy 3: Match individual words for multi-word terms
    if len(term.split()) > 1:
        words = term.split()
        for paper_id, paper_text in papers.items():
            # Try to find any 2+ word combination
            for i in range(len(words) - 1):
                partial = ' '.join(words[i:i+2])
                pattern = re.compile(rf'\b{re.escape(partial)}\b', re.IGNORECASE)
                match = pattern.search(paper_text)
                if match:
                    context, line_number = extract_context_window(paper_text, match.start(), match.end(), window_words)
                    location = f"{paper_id}:{line_number}"
                    return context, location

    # Strategy 4: Match any single word (last resort)
    if len(term.split()) > 1:
        words = term.split()
        for paper_id, paper_text in papers.items():
            for word in words:
                if len(word) > 3:  # Only meaningful words
                    pattern = re.compile(rf'\b{re.escape(word)}\b', re.IGNORECASE)
                    match = pattern.search(paper_text)
                    if match:
                        context, line_number = extract_context_window(paper_text, match.start(), match.end(), window_words)
                        location = f"{paper_id}:{line_number}"
                        return context, location

    # Strategy 5: Find ANY sentence that contains at least one character from the term
    for paper_id, paper_text in papers.items():
        sentences = split_into_sentences(paper_text)
        for sent in sentences:
            # Check if any significant word from term appears
            term_words = set([w.lower().strip('.,;:') for w in term.split() if len(w) > 3])
            sent_words = set([w.lower().strip('.,;:') for w in sent.split()])
            overlap = term_words & sent_words
            if overlap:
                # Found at least one matching word
                word = list(overlap)[0]
                idx = sent.lower().find(word)
                if idx >= 0:
                    abs_idx = paper_text.find(sent[:100]) + idx
                    context, line_number = extract_context_window(paper_text, abs_idx, abs_idx + len(word), window_words)
                    location = f"{paper_id}:{line_number}"
                    return context, location

    return "", ""


def find_term_context_embeddings(term: str, papers: Dict[str, str],
                                   model: SentenceTransformer,
                                   top_k: int = 5,
                                   min_similarity: float = 0.2) -> Tuple[str, str, List[Dict]]:
    """
    Find most relevant context using semantic search.

    Returns:
        Tuple of (best_context, location, all_matches)
        where all_matches is a list of {sentence, paper_id, similarity}
    """
    term_embedding = model.encode(term, convert_to_tensor=True)

    all_sentences = []
    for paper_id, paper_text in papers.items():
        sentences = split_into_sentences(paper_text)
        for sent in sentences:
            # Check if term is mentioned (exact or partial match) - MORE AGGRESSIVE
            term_lower = term.lower()
            sent_lower = sent.lower()

            # Check for any mention of term or its parts
            if len(term.split()) > 1:  # Multi-word term
                # Check full term or any 2-word combination
                if term_lower in sent_lower:
                    all_sentences.append({'sentence': sent, 'paper_id': paper_id})
                else:
                    # Check for partial matches (2+ word combinations)
                    words = term.split()
                    for i in range(len(words) - 1):
                        partial = ' '.join(words[i:i+2]).lower()
                        if partial in sent_lower:
                            all_sentences.append({'sentence': sent, 'paper_id': paper_id})
                            break
            else:  # Single word term
                words = sent.split()
                # Check exact match with punctuation variations
                if term_lower in [w.lower().strip('.,;:') for w in words]:
                    all_sentences.append({'sentence': sent, 'paper_id': paper_id})
                # Check substring for short forms
                elif len(term) > 4 and term_lower in sent_lower:
                    all_sentences.append({'sentence': sent, 'paper_id': paper_id})

    # If we found sentences mentioning the term, rank by similarity
    if all_sentences:
        # Encode sentences
        sentence_texts = [s['sentence'] for s in all_sentences]
        sentence_embeddings = model.encode(sentence_texts, convert_to_tensor=True)

        # Compute similarities
        similarities = torch.nn.functional.cosine_similarity(
            term_embedding.unsqueeze(0),
            sentence_embeddings,
            dim=1
        )

        # Get top matches
        top_indices = torch.argsort(similarities, descending=True)[:top_k]

        matches = []
        for idx in top_indices:
            sim = similarities[idx].item()
            if sim >= min_similarity:
                matches.append({
                    'sentence': all_sentences[idx]['sentence'],
                    'paper_id': all_sentences[idx]['paper_id'],
                    'similarity': sim
                })

        if matches:
            best = matches[0]
            # Try to find line number
            paper_text = papers[best['paper_id']]
            match_start = paper_text.find(best['sentence'][:100])
            line_number = paper_text[:match_start].count('\n') + 1 if match_start >= 0 else 0
            location = f"{best['paper_id']}:{line_number}"
            return best['sentence'], location, matches
        else:
            # Even if similarity is low, return the best match
            best_idx = torch.argmax(similarities).item()
            best = all_sentences[best_idx]
            paper_text = papers[best['paper_id']]
            match_start = paper_text.find(best['sentence'][:100])
            line_number = paper_text[:match_start].count('\n') + 1 if match_start >= 0 else 0
            location = f"{best['paper_id']}:{line_number}"
            return best['sentence'], location, []

    return "", "", []


def load_papers(papers_dir: str = str(_CDM_ROOT / "data/papers_txt")) -> Dict[str, str]:
    """Load all papers from the papers directory."""
    papers_path = Path(papers_dir)
    if not papers_path.exists():
        logger.warning(f"Papers directory not found: {papers_dir}")
        return {}

    papers = {}
    for paper_file in papers_path.glob("*.txt"):
        try:
            paper_id = paper_file.stem
            with open(paper_file, 'r', errors='ignore') as f:
                papers[paper_id] = f.read()
        except Exception as e:
            logger.warning(f"Failed to load paper {paper_file}: {e}")

    logger.info(f"Loaded {len(papers)} papers from {papers_dir}")
    return papers


def add_paper_context(input_file: str, output_file: str,
                      papers_dir: str = str(_CDM_ROOT / "data/papers_txt"),
                      batch_size: int = 100,
                      use_embeddings: bool = True,
                      model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> dict:
    """
    Add paper context to entities using embeddings or regex.

    Args:
        input_file: Path to input JSON file
        output_file: Path to output JSON file
        papers_dir: Directory containing paper text files
        batch_size: Progress update interval
        use_embeddings: Use semantic search (True) or regex (False)
        model_name: Sentence transformer model name

    Returns:
        Statistics dictionary
    """
    logger.info(f"Loading entities from {input_file}")
    with open(input_file, 'r') as f:
        data = json.load(f)

    entities = data['results']
    logger.info(f"Processing {len(entities)} entities")

    # Load papers
    papers = load_papers(papers_dir)

    # Load model if using embeddings
    model = None
    if use_embeddings:
        logger.info(f"Loading embedding model: {model_name}")
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        logger.info(f"Using device: {device}")
        model = SentenceTransformer(model_name, device=device)

    stats = {
        "total": len(entities),
        "paper_context_added": 0,
        "regex_fallback": 0,
        "no_paper_found": 0,
    }

    for i, entity in enumerate(entities):
        term = entity.get('term', '')

        # Skip if already has paper_context
        if 'paper_context' in entity and entity['paper_context']:
            stats['paper_context_added'] += 1
            continue

        context = ""
        location = ""

        if use_embeddings and model:
            # Try semantic search first
            context, location, matches = find_term_context_embeddings(term, papers, model)
            if not context:
                # Fallback to regex
                context, location = find_term_context_regex(term, papers)
                if context:
                    stats['regex_fallback'] += 1
        else:
            # Use regex only
            context, location = find_term_context_regex(term, papers)

        if context:
            entity['paper_context'] = context
            entity['paper_location'] = location
            stats['paper_context_added'] += 1

            # Log first few
            if stats['paper_context_added'] <= 10:
                logger.info(f"[{i+1}/{len(entities)}] '{term}' at {location}")
                logger.info(f"  Context: {context[:120]}...")
        else:
            stats['no_paper_found'] += 1

        # Progress update
        if (i + 1) % batch_size == 0:
            progress = (i + 1) / len(entities) * 100
            logger.info(f"Progress: {i+1}/{len(entities)} ({progress:.1f}%) - "
                       f"Context added: {stats['paper_context_added']}, "
                       f"Regex fallback: {stats.get('regex_fallback', 0)}, "
                       f"Not found: {stats['no_paper_found']}")

    # Save results
    logger.info(f"Saving entities to {output_file}")
    with open(output_file, 'w') as f:
        json.dump(data, f, indent=2)
    logger.info(f"✓ Saved to {output_file}")

    return stats


def print_statistics(stats: dict):
    """Print summary statistics."""
    print("\n" + "="*80)
    print("PAPER CONTEXT ADDITION SUMMARY")
    print("="*80)
    print(f"Total entities processed:      {stats['total']:,}")
    print(f"Paper context added:          {stats['paper_context_added']:,}")
    if 'regex_fallback' in stats:
        print(f"Regex fallback:               {stats['regex_fallback']:,}")
    print(f"No paper found:               {stats['no_paper_found']:,}")
    print("="*80)

    total_processed = stats['paper_context_added'] + stats['no_paper_found']
    success_rate = (stats['paper_context_added'] / total_processed * 100) if total_processed > 0 else 0
    print(f"Success rate (found in papers): {success_rate:.1f}%")
    print("="*80)
    print("\nNote: Each entity now has 'paper_context'")
    print("      and 'paper_location' (paper_id:line_number) fields")
    print("="*80)


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Add paper context to entities using embeddings or regex"
    )
    parser.add_argument(
        "--input",
        default="knowledge_graph/cdm_entities_final_v2.json",
        help="Input JSON file with entities"
    )
    parser.add_argument(
        "--output",
        default="knowledge_graph/cdm_entities_final_v3.json",
        help="Output JSON file with paper context added"
    )
    parser.add_argument(
        "--papers-dir",
        default=str(_CDM_ROOT / "data/papers_txt"),
        help="Directory containing paper text files"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Progress update interval (default: 100)"
    )
    parser.add_argument(
        "--use-regex-only",
        action="store_true",
        help="Use regex search only (faster, less accurate)"
    )
    parser.add_argument(
        "--model",
        default="sentence-transformers/all-MiniLM-L6-v2",
        help="Sentence transformer model (default: all-MiniLM-L6-v2)"
    )

    args = parser.parse_args()

    print("="*80)
    print("ADD PAPER CONTEXT TO ENTITIES")
    print("="*80)
    print(f"Input:        {args.input}")
    print(f"Output:       {args.output}")
    print(f"Papers dir:   {args.papers_dir}")
    print(f"Method:       {'Regex only' if args.use_regex_only else 'Embeddings + Regex fallback'}")
    if not args.use_regex_only:
        print(f"Model:        {args.model}")
    print("="*80)
    print("")

    stats = add_paper_context(
        args.input,
        args.output,
        papers_dir=args.papers_dir,
        batch_size=args.batch_size,
        use_embeddings=not args.use_regex_only,
        model_name=args.model
    )

    print_statistics(stats)

    print(f"\n✓ Entities with paper context saved to: {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
