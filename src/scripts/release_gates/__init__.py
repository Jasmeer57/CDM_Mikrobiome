"""Release gates for the Microbiome CDM data products.

The only supported entry point is::

    python -m scripts.release_gates.check_all --release <path>

See ``README.md`` in this directory for the gate catalogue.
"""

from .core import Ctx, GateResult  # noqa: F401

__all__ = ["Ctx", "GateResult"]
