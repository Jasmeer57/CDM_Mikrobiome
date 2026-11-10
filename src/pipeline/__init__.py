"""Consolidated Microbiome-CDM pipeline: extraction -> CDM build -> release gates.

Stage packages are numbered in pipeline order.  Shared infrastructure
(`config`, `paths`, `utils`, `common`, `llmio`) lives at this level so that
stage modules can use ``from ..config import ...``.
"""

__version__ = "1.0.0"
