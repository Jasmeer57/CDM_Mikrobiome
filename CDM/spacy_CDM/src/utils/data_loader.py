"""
Data loading utility for the microbiome term extraction pipeline.
"""

import logging
from pathlib import Path
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


class DataLoader:
    """Handles loading of input documents from various formats."""

    def __init__(self, config):
        self.config = config

    def load_documents(self, input_dir: str) -> List[Dict[str, Any]]:
        """
        Load documents from the input directory.

        Args:
            input_dir: Directory containing input files

        Returns:
            List of document dictionaries
        """
        input_path = Path(input_dir)
        if not input_path.exists():
            raise FileNotFoundError(f"Input directory not found: {input_dir}")

        documents = []
        file_count = 0

        # Get all supported files
        for ext in self.config.file_extensions:
            for file_path in sorted(input_path.glob(f"*{ext}")):
                if self.config.max_files and file_count >= self.config.max_files:
                    logger.info(f"Reached maximum file limit: {self.config.max_files}")
                    break

                try:
                    content = file_path.read_text(encoding=self.config.encoding)
                    documents.append({
                        'file_id': file_path.stem,
                        'file_path': str(file_path),
                        'content': content,
                        'size': len(content),
                        'extension': ext
                    })
                    file_count += 1
                    logger.debug(f"📖 Loaded: {file_path.name} ({len(content):,} chars)")

                except Exception as e:
                    logger.error(f"❌ Error loading {file_path}: {e}")
                    if not self.config.continue_on_error:
                        raise

        logger.info(f"✅ Loaded {len(documents)} documents from {input_dir}")
        return documents