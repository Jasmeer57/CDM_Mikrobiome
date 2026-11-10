"""Centralized path resolution for the Microbiome-CDM repository.

Purpose
-------
Every location the code reads or writes is resolved here, relative to a repo
root that is *discovered at run time* — never a hard-coded absolute path. Moving
or cloning the repository therefore needs no code changes, and relocating a
folder needs a change in one place.

Repo root
---------
:data:`REPO_ROOT` is, in order of precedence:

1. ``$CDM_REPO_ROOT`` if set and non-empty;
2. the nearest ancestor of this file that contains the marker file
   ``.cdm_root``.

Layout (since 2026-10-30)
-------------------------
``src/`` code · ``pipelines/`` corpus_v2, llm_terms, corpus_pipeline ·
``data/`` inputs · ``outputs/`` results, logs, scratch · ``releases/`` frozen
bundles · ``paper/`` manuscript · ``docs/``. See the README's "Repository
layout" section for the old-to-new map.

Behavior contract
------------------
* Every path is returned as an absolute :class:`pathlib.Path`, independent of
  the caller's CWD.
* Environment overrides are read **at call time**, not at import time, so
  tests can use ``monkeypatch.setenv`` without re-importing the module.

Environment variables
---------------------
=========================  ==================================  ==================================================
Variable                   Resolver                            Default
=========================  ==================================  ==================================================
``CDM_REPO_ROOT``          :data:`REPO_ROOT`                   nearest ancestor holding ``.cdm_root``
``CDM_PAPERS_TXT``         :func:`papers_txt`                  ``<repo>/data/papers_txt``
``CDM_PDFS``               :func:`pdfs_dir`                     ``<repo>/data/pdfs``
``CDM_FULLTEXT``           :func:`corpus_fulltext_dir`          ``<repo>/data/fulltext``
``CDM_SAMPLES_PAPER``      :func:`samples_paper_dir`            ``<repo>/data/168000-samples-paper``
``CDM_BIOPROJECT_EXPORT``  :func:`bioproject_export`            ``<repo>/data/bioproject_data_export.json``
``CDM_SEGMENTED_MD``       :func:`segmented_markdown_dir`       ``<repo>/data/segmented_sections_markdown``
``CDM_NER_TOOLS``          :func:`ner_tools_dir`                ``~/tools/ner_tools``
=========================  ==================================  ==================================================

``ner_tools`` is the one default outside the repo: the bundled JDK and Java NER
tools (~6 GB) live in ``~/tools/ner_tools`` to keep the repo lean.

Note on "fulltext"
------------------
Two distinct directories are called "fulltext" in this project, so they are
exposed under different names rather than one ambiguous ``fulltext_dir``:

* :func:`corpus_fulltext_dir` — ``data/fulltext/``, which
  ``src/scripts/download_corpus_pdfs.py`` writes 73 JATS XMLs into.
* :func:`samples_fulltext_dir` — ``data/168000-samples-paper/fulltext/``, which
  ``build_hm_corpus.py`` reads for DOI/PMID/PMCID and licensing metadata.
"""
from __future__ import annotations

import os
from pathlib import Path

#: Name of the marker file at the repository root.
ROOT_MARKER = ".cdm_root"

#: Environment variable name for each resolvable location.
ENV_REPO_ROOT = "CDM_REPO_ROOT"
ENV_PAPERS_TXT = "CDM_PAPERS_TXT"
ENV_PDFS = "CDM_PDFS"
ENV_FULLTEXT = "CDM_FULLTEXT"
ENV_SAMPLES_PAPER = "CDM_SAMPLES_PAPER"
ENV_BIOPROJECT_EXPORT = "CDM_BIOPROJECT_EXPORT"
ENV_SEGMENTED_MD = "CDM_SEGMENTED_MD"
ENV_NER_TOOLS = "CDM_NER_TOOLS"


def find_repo_root(start: Path | str | None = None) -> Path:
    """Return the repository root.

    ``$CDM_REPO_ROOT`` wins if set; otherwise walk up from *start* (default:
    this file) to the first directory containing :data:`ROOT_MARKER`.
    """
    raw = os.environ.get(ENV_REPO_ROOT)
    if raw and raw.strip():
        return Path(raw).expanduser().resolve()
    here = Path(start or __file__).resolve()
    for candidate in (here, *here.parents):
        if (candidate / ROOT_MARKER).is_file():
            return candidate
    raise RuntimeError(
        f"cannot find the repo root: no {ROOT_MARKER} above {here}; "
        f"set {ENV_REPO_ROOT}")


#: Repo root, discovered once at import. Independent of CWD.
REPO_ROOT = find_repo_root()

# ── top-level groups ─────────────────────────────────────────────────────────
SRC_DIR = REPO_ROOT / "src"
PIPELINES_DIR = REPO_ROOT / "pipelines"
DATA_DIR = REPO_ROOT / "data"
OUTPUTS_DIR = REPO_ROOT / "outputs"
RELEASES_DIR = REPO_ROOT / "releases"
PAPER_DIR = REPO_ROOT / "paper"
DOCS_DIR = REPO_ROOT / "docs"

# ── fixed locations inside the groups ────────────────────────────────────────
SCRIPTS_DIR = SRC_DIR / "scripts"
CORPUS_V2_DIR = PIPELINES_DIR / "corpus_v2"
LLM_TERMS_DIR = PIPELINES_DIR / "llm_terms"
RESULTS_DIR = OUTPUTS_DIR / "results"
LOGS_DIR = OUTPUTS_DIR / "logs"
SCRATCH_DIR = OUTPUTS_DIR / "scratch"
FROZEN_OUTPUT_DIR = RELEASES_DIR / "frozen_output"
DATA_CATALOGUE_DIR = RELEASES_DIR / "data_catalogue"
ZENODO_V1_DIR = RELEASES_DIR / "zenodo_v1"


def _resolve(env_var: str, default: Path) -> Path:
    """Resolve *env_var* if set, else *default*.

    An env var may be absolute or relative; relative values are resolved
    against the current working directory, matching how a user-supplied CLI
    path would behave. An empty or whitespace-only value is treated as unset so
    that ``CDM_PAPERS_TXT=`` in a shell does not silently point at the CWD.
    """
    raw = os.environ.get(env_var)
    if raw is None or not raw.strip():
        return default
    return Path(raw).expanduser().resolve()


def papers_txt() -> Path:
    """Directory of per-paper ``<PRJ-accession>.txt`` files (the 453-paper corpus)."""
    return _resolve(ENV_PAPERS_TXT, DATA_DIR / "papers_txt")


def pdfs_dir() -> Path:
    """Directory of retrieved corpus PDFs (written by ``download_corpus_pdfs.py``)."""
    return _resolve(ENV_PDFS, DATA_DIR / "pdfs")


def corpus_fulltext_dir() -> Path:
    """``data/fulltext/`` of JATS XMLs retrieved by ``download_corpus_pdfs.py``."""
    return _resolve(ENV_FULLTEXT, DATA_DIR / "fulltext")


def samples_paper_dir() -> Path:
    """``data/168000-samples-paper/`` — Abdill 2025 compendium metadata and fulltext."""
    return _resolve(ENV_SAMPLES_PAPER, DATA_DIR / "168000-samples-paper")


def samples_fulltext_dir() -> Path:
    """``<samples_paper_dir>/fulltext/`` — per-project article XMLs + ``manifest.csv``.

    Nested under :func:`samples_paper_dir`, so it moves with it when
    ``CDM_SAMPLES_PAPER`` is overridden. Distinct from :func:`corpus_fulltext_dir`.
    """
    return samples_paper_dir() / "fulltext"


def bioproject_export() -> Path:
    """``data/bioproject_data_export.json`` — NCBI BioProject metadata export."""
    return _resolve(ENV_BIOPROJECT_EXPORT, DATA_DIR / "bioproject_data_export.json")


def segmented_markdown_dir() -> Path:
    """``data/segmented_sections_markdown/`` — the 453 ``HMPAPER_*.md`` section files."""
    return _resolve(ENV_SEGMENTED_MD, DATA_DIR / "segmented_sections_markdown")


def ner_tools_dir() -> Path:
    """``ner_tools/`` — bundled JDK 8 (``java/``), Java NER tools (``tools/``), ``downloads/``."""
    return _resolve(ENV_NER_TOOLS, Path.home() / "tools" / "ner_tools")
