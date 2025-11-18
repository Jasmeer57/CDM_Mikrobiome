"""
Modules package for scientific term extraction pipeline
"""

from .terms_extractor import TermsExtractor
from .deduplication import ComprehensiveDeduplicator

__all__ = [
    'TermsExtractor',
    'ComprehensiveDeduplicator'
]