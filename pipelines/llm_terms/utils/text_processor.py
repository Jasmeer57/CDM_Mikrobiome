"""
Text Processing Utilities for CDM Pipeline
"""

import logging
from typing import List, Tuple
import re

logger = logging.getLogger(__name__)

class TextProcessor:
    """Utility class for text processing operations."""

    @staticmethod
    def chunk_text(text: str, chunk_size: int = 5000, overlap: int = 150) -> List[Tuple[str, int]]:
        """Split text into overlapping chunks for processing."""
        if not text or len(text) <= chunk_size:
            return [(text, 1)] if text else []

        chunks = []
        chunk_num = 1

        for i in range(0, len(text), chunk_size - overlap):
            chunk = text[i:i + chunk_size]
            if len(chunk.strip()) > 100:  # Only process substantial chunks
                chunks.append((chunk, chunk_num))
                chunk_num += 1

        logger.info(f"📊 Created {len(chunks)} chunks ({chunk_size} chars, {overlap} overlap)")
        return chunks

    @staticmethod
    def clean_text(text: str) -> str:
        """Clean and normalize text."""
        if not text:
            return ""

        # Remove excessive whitespace
        text = re.sub(r'\s+', ' ', text)

        # Remove non-printable characters except common ones
        text = re.sub(r'[^\x20-\x7E\n\t\r]', '', text)

        # Normalize line endings
        text = re.sub(r'\r\n|\r', '\n', text)

        return text.strip()

    @staticmethod
    def extract_sentences(text: str) -> List[str]:
        """Extract sentences from text."""
        sentences = []
        # Simple sentence splitting
        for sentence in re.split(r'[.!?]+', text):
            sentence = sentence.strip()
            if len(sentence) > 10:  # Only keep substantial sentences
                sentences.append(sentence)
        return sentences

    @staticmethod
    def calculate_text_stats(text: str) -> dict:
        """Calculate basic text statistics."""
        if not text:
            return {"char_count": 0, "word_count": 0, "sentence_count": 0}

        words = text.split()
        sentences = TextProcessor.extract_sentences(text)

        return {
            "char_count": len(text),
            "word_count": len(words),
            "sentence_count": len(sentences),
            "avg_word_length": sum(len(word) for word in words) / len(words) if words else 0,
            "reading_time_minutes": len(words) / 200  # Average reading speed
        }