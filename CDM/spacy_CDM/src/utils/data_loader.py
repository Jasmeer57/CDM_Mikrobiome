"""
Data loading utilities for the pipeline
"""

import logging
import json
import csv
from pathlib import Path
from typing import List, Dict, Any, Optional, Union, Iterator
import re

from src.config.settings import PipelineConfig

logger = logging.getLogger(__name__)


class DataLoader:
    """Load and process various data formats"""

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.supported_extensions = {'.txt', '.csv', '.json', '.tsv'}

    def detect_encoding(self, file_path: Path) -> str:
        """Detect file encoding - simplified version"""
        # Try common encodings in order
        encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']

        for encoding in encodings:
            try:
                with open(file_path, 'r', encoding=encoding) as f:
                    f.read(1000)  # Try to read first 1000 chars
                logger.debug(f"Detected encoding: {encoding}")
                return encoding
            except UnicodeDecodeError:
                continue

        logger.warning(f"Could not detect encoding for {file_path}, using utf-8")
        return 'utf-8'

    def load_text_file(self, file_path: Path) -> Optional[str]:
        """Load a text file with encoding detection"""
        try:
            encoding = self.detect_encoding(file_path)
            with open(file_path, 'r', encoding=encoding) as f:
                content = f.read()
            logger.info(f"✅ Loaded text file: {file_path} ({len(content)} characters)")
            return content
        except Exception as e:
            logger.error(f"❌ Failed to load text file {file_path}: {e}")
            return None

    def load_json_file(self, file_path: Path) -> Optional[Union[Dict, List]]:
        """Load a JSON file"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            logger.info(f"✅ Loaded JSON file: {file_path}")
            return data
        except Exception as e:
            logger.error(f"❌ Failed to load JSON file {file_path}: {e}")
            return None

    def load_csv_file(self, file_path: Path, delimiter: str = ',') -> Optional[List[Dict[str, Any]]]:
        """Load a CSV file"""
        try:
            encoding = self.detect_encoding(file_path)
            with open(file_path, 'r', encoding=encoding) as f:
                # Auto-detect delimiter
                sample = f.read(1024)
                f.seek(0)

                if '\t' in sample and ',' not in sample:
                    delimiter = '\t'

                reader = csv.DictReader(f, delimiter=delimiter)
                data = list(reader)

            logger.info(f"✅ Loaded CSV file: {file_path} ({len(data)} rows)")
            return data
        except Exception as e:
            logger.error(f"❌ Failed to load CSV file {file_path}: {e}")
            return None

    def extract_text_from_document(self, content: str, file_extension: str) -> Optional[str]:
        """Extract text content from various document types"""
        try:
            # For now, handle basic text files
            # Could be extended to handle PDF, DOCX, etc.
            if file_extension in {'.txt', '.md', '.json', '.csv', '.tsv'}:
                return content
            else:
                logger.warning(f"Unsupported file type: {file_extension}")
                return None
        except Exception as e:
            logger.error(f"Failed to extract text from document: {e}")
            return None

    def chunk_text(self, text: str, chunk_size: int = None, overlap: int = None) -> List[str]:
        """Chunk text for processing"""
        if chunk_size is None:
            chunk_size = self.config.processing.chunk_size
        if overlap is None:
            overlap = self.config.processing.overlap

        if len(text) <= chunk_size:
            return [text]

        chunks = []
        start = 0

        while start < len(text):
            end = start + chunk_size

            # Don't cut off in the middle of a word if possible
            if end < len(text):
                # Find the last space before chunk_size
                last_space = text.rfind(' ', start, end)
                if last_space > start:
                    end = last_space

            chunks.append(text[start:end])

            # Move start position with overlap
            start = max(start + 1, end - overlap)

        logger.info(f"Chunked text into {len(chunks)} chunks (size: {chunk_size}, overlap: {overlap})")
        return chunks

    def find_files(self, input_dir: Path, pattern: str = "*") -> List[Path]:
        """Find files in directory matching pattern"""
        try:
            files = list(input_dir.glob(pattern))
            # Filter to supported extensions
            supported_files = [f for f in files if f.suffix.lower() in self.supported_extensions]
            logger.info(f"Found {len(supported_files)} supported files in {input_dir}")
            return supported_files
        except Exception as e:
            logger.error(f"Error finding files in {input_dir}: {e}")
            return []

    def load_documents(self, input_dir: str, max_files: int = -1) -> Iterator[Dict[str, Any]]:
        """Load documents from directory"""
        input_path = Path(input_dir)
        if not input_path.exists():
            logger.error(f"Input directory does not exist: {input_dir}")
            return

        files = self.find_files(input_path)

        if max_files > 0:
            files = files[:max_files]
            logger.info(f"Limited to {max_files} files")

        for file_path in files:
            try:
                logger.info(f"Processing file: {file_path}")

                # Load file content
                if file_path.suffix.lower() == '.json':
                    data = self.load_json_file(file_path)
                    if data is None:
                        continue

                    # Handle different JSON structures
                    if isinstance(data, dict):
                        # Look for text content in common keys
                        content = None
                        for key in ['text', 'content', 'body', 'abstract', 'full_text']:
                            if key in data and isinstance(data[key], str):
                                content = data[key]
                                break

                        if content is None:
                            # Convert dict to JSON string as fallback
                            content = json.dumps(data, indent=2)

                    elif isinstance(data, list):
                        # Handle list of documents
                        for i, item in enumerate(data):
                            if isinstance(item, dict):
                                for key in ['text', 'content', 'body', 'abstract', 'full_text']:
                                    if key in item and isinstance(item[key], str):
                                        yield {
                                            'file_id': f"{file_path.stem}_{i}",
                                            'file_path': str(file_path),
                                            'content': item[key],
                                            'size': len(item[key]),
                                            'extension': file_path.suffix,
                                            'metadata': item
                                        }
                                        break
                        continue

                    else:
                        content = str(data)

                else:
                    content = self.load_text_file(file_path)
                    if content is None:
                        continue

                # Clean and prepare content
                content = self.extract_text_from_document(content, file_path.suffix)
                if content is None:
                    continue

                # Create document dictionary
                doc = {
                    'file_id': file_path.stem,
                    'file_path': str(file_path),
                    'content': content,
                    'size': len(content),
                    'extension': file_path.suffix
                }

                logger.debug(f"Loaded document: {doc['file_id']} ({doc['size']} chars)")
                yield doc

            except Exception as e:
                logger.error(f"Error processing file {file_path}: {e}")
                continue

    def validate_document(self, doc: Dict[str, Any]) -> bool:
        """Validate document structure and content"""
        required_fields = ['file_id', 'file_path', 'content', 'size', 'extension']

        for field in required_fields:
            if field not in doc:
                logger.error(f"Missing required field: {field}")
                return False

        if not isinstance(doc['content'], str):
            logger.error("Content must be a string")
            return False

        if len(doc['content']) < 10:
            logger.warning(f"Document {doc['file_id']} has very short content ({len(doc['content'])} chars)")

        return True