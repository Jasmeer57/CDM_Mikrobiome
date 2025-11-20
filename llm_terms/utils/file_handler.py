"""
File Handling Utilities for CDM Pipeline
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class FileHandler:
    """Utility class for file operations."""

    @staticmethod
    def read_text_file(file_path: str) -> str:
        """Read text from file with proper encoding."""
        try:
            path = Path(file_path)
            if not path.exists():
                raise FileNotFoundError(f"File not found: {file_path}")

            if not path.is_file():
                raise ValueError(f"Path is not a file: {file_path}")

            with open(path, 'r', encoding='utf-8') as f:
                text = f.read()

            logger.info(f"📄 Loaded file: {file_path} ({len(text)} characters)")
            return text

        except UnicodeDecodeError:
            # Try with different encodings
            for encoding in ['latin-1', 'cp1252', 'utf-16']:
                try:
                    with open(path, 'r', encoding=encoding) as f:
                        text = f.read()
                    logger.warning(f"📄 Used encoding {encoding} for: {file_path}")
                    return text
                except:
                    continue
            raise Exception(f"Could not decode file: {file_path}")
        except Exception as e:
            logger.error(f"Error reading file {file_path}: {e}")
            raise

    @staticmethod
    def write_json_results(results: Dict[str, Any], output_path: str, indent: int = 2) -> bool:
        """Write results to JSON file with proper formatting."""
        try:
            path = Path(output_path)

            # Create directory if it doesn't exist
            path.parent.mkdir(parents=True, exist_ok=True)

            # Write JSON file
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=indent, ensure_ascii=False)

            logger.info(f"💾 Results saved to: {output_path}")
            return True

        except Exception as e:
            logger.error(f"Error writing results to {output_path}: {e}")
            return False

    @staticmethod
    def create_output_filename(input_path: str, suffix: str = "_entities", extension: str = ".json") -> str:
        """Create output filename based on input path."""
        input_path = Path(input_path)
        output_name = input_path.stem + suffix + extension
        return str(input_path.parent / output_name)

    @staticmethod
    def validate_input_file(file_path: str) -> bool:
        """Validate input file exists and is readable."""
        try:
            path = Path(file_path)
            return path.exists() and path.is_file() and os.access(path, os.R_OK)
        except:
            return False

    @staticmethod
    def get_file_stats(file_path: str) -> Dict[str, Any]:
        """Get file statistics."""
        try:
            path = Path(file_path)
            stat = path.stat()

            return {
                "name": path.name,
                "size_bytes": stat.st_size,
                "size_mb": round(stat.st_size / (1024 * 1024), 2),
                "modified": time.ctime(stat.st_mtime),
                "extension": path.suffix.lower(),
                "readable": os.access(path, os.R_OK)
            }
        except Exception as e:
            logger.error(f"Error getting file stats for {file_path}: {e}")
            return {}

    @staticmethod
    def backup_existing_file(file_path: str, backup_suffix: str = "_backup") -> Optional[str]:
        """Create backup of existing file."""
        try:
            path = Path(file_path)
            if not path.exists():
                return None

            backup_path = path.with_name(path.stem + backup_suffix + path.suffix)

            if backup_path.exists():
                # Add timestamp if backup already exists
                timestamp = int(time.time())
                backup_path = path.with_name(path.stem + backup_suffix + f"_{timestamp}" + path.suffix)

            # Copy file to backup location
            import shutil
            shutil.copy2(path, backup_path)

            logger.info(f"🔄 Created backup: {backup_path}")
            return str(backup_path)

        except Exception as e:
            logger.error(f"Error creating backup of {file_path}: {e}")
            return None

    @staticmethod
    def ensure_directory(directory_path: str) -> bool:
        """Ensure directory exists."""
        try:
            path = Path(directory_path)
            path.mkdir(parents=True, exist_ok=True)
            return True
        except Exception as e:
            logger.error(f"Error creating directory {directory_path}: {e}")
            return False