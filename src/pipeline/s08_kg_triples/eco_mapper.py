"""ECO Evidence Code Mapper — maps evidence text to ECO ontology classes via embeddings.

Uses Ollama bge-m3 (or nomic-embed-text) to embed ECO class labels + definitions
(+ ancestor path + custom aliases) and query evidence text, then matches via
cosine similarity.

ECO = Evidence & Conclusion Ontology (https://purl.obolibrary.org/obo/eco.owl)

Strategy:
  - Parse all non-obsolete ECO classes from the OWL file.
  - Build enriched embedding text for each class: label + definition + ancestor
    labels + custom microbiome-relevant aliases.
  - At query time, embed the evidence text and rank all classes by cosine
    similarity. Return top-k above threshold.
  - Optionally restrict to a curated subset of ~100 mid-level classes that are
    most relevant to microbiome research (avoids overly specific protein/genomics
    leaf nodes that dominate generic queries).
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import requests

log = logging.getLogger(__name__)

# This module lives at <repo>/src/pipeline/s08_kg_triples/, so the repo root is
# parents[3] (parents[2] would be src/ -- the original layout predates the move
# of cdm_pipeline/ under src/).
ECO_OWL_PATH = Path(__file__).resolve().parents[3] / "data" / "reference" / "ontologies" / "eco_canonical.owl"
EMBED_MODEL = os.environ.get("ECO_EMBED_MODEL", "bge-m3:latest")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
CACHE_PATH = Path(__file__).resolve().parents[3] / "data" / "reference" / "ontologies" / "eco_embeddings_v2.npz"
TOP_K_DEFAULT = 5
SIMILARITY_THRESHOLD = 0.30
BATCH_SIZE = 64

# Curated subset of ECO classes most relevant to microbiome research.
# These are mid-level classes that avoid overly specific protein/genomics leaves.
# Key: ECO ID -> list of extra alias phrases to add to the embedding text.
CURATED_SUBSET: dict[str, list[str]] = {
    # --- Top-level ---
    "ECO_0000000": ["evidence", "scientific evidence"],
    # --- Experimental evidence branch ---
    "ECO_0000006": ["experimental evidence", "laboratory experiment", "wet lab experiment", "in vitro experiment", "in vivo experiment"],
    "ECO_0000220": ["sequencing assay evidence", "DNA sequencing", "RNA sequencing", "metagenomic sequencing", "amplicon sequencing", "16S rRNA sequencing", "whole genome sequencing", "shotgun sequencing"],
    "ECO_0000219": ["nucleotide sequencing assay evidence", "nucleotide sequencing", "DNA sequencing", "genomic sequencing"],
    "ECO_0000295": ["RNA-sequencing evidence", "RNA-seq", "transcriptome sequencing", "gene expression profiling by RNA-seq"],
    "ECO_0001560": ["single-cell RNA-sequencing evidence", "scRNA-seq", "single cell transcriptomics"],
    "ECO_0000008": ["expression pattern evidence", "gene expression", "transcript expression", "protein expression"],
    "ECO_0000009": ["transcript expression evidence", "mRNA expression", "transcriptomics"],
    "ECO_0000010": ["protein expression evidence", "protein abundance", "proteomics"],
    "ECO_0005516": ["molecule detection assay evidence", "molecule detection", "biomolecule detection", "analyte detection"],
    "ECO_0005517": ["protein detection assay evidence", "protein detection", "protein identification", "immunoassay"],
    "ECO_0000267": ["enzyme-linked immunoabsorbent assay evidence", "ELISA", "enzyme-linked immunosorbent assay"],
    "ECO_0001055": ["immunohistochemistry evidence", "IHC", "immunohistochemistry"],
    "ECO_0001053": ["immunocytochemistry evidence", "ICC", "immunocytochemistry"],
    "ECO_0000007": ["immunofluorescence evidence", "IF", "immunofluorescence staining"],
    "ECO_0005504": ["spectrometry evidence", "mass spectrometry", "spectrometry", "MS"],
    "ECO_0005526": ["MALDI-TOF mass spectrometry evidence", "MALDI-TOF", "matrix-assisted laser desorption ionization"],
    "ECO_0001094": ["macroscopy evidence", "macroscopic observation", "visual inspection", "gross examination"],
    "ECO_0001830": ["host colonization assay evidence", "host colonization", "host-microbe interaction assay"],
    "ECO_0001833": ["infection assay evidence", "infection assay", "host infection experiment"],
    "ECO_0006252": ["magnetic resonance evidence", "MRI", "NMR", "magnetic resonance imaging"],
    "ECO_0000231": ["quantitative polymerase chain reaction evidence", "qPCR", "quantitative PCR", "real-time PCR", "RT-PCR"],
    "ECO_0000360": ["biological target-disease association via drug evidence", "drug-target association", "drug-disease association"],
    # --- Similarity evidence branch ---
    "ECO_0000041": ["similarity evidence", "sequence similarity", "homology", "sequence comparison"],
    "ECO_0000044": ["sequence similarity evidence", "sequence similarity", "BLAST", "sequence homology"],
    "ECO_0000200": ["sequence alignment evidence", "sequence alignment", "multiple sequence alignment"],
    "ECO_0000206": ["BLAST evidence", "BLAST", "basic local alignment search tool"],
    "ECO_0000201": ["sequence orthology evidence", "orthology", "ortholog identification"],
    "ECO_0000080": ["phylogenetic evidence", "phylogenetics", "phylogenetic tree", "evolutionary relationship", "taxonomic classification by phylogeny"],
    "ECO_0000057": ["phenotypic similarity evidence", "phenotypic similarity", "phenotype comparison"],
    "ECO_0000177": ["genomic context evidence", "genomic context", "gene neighborhood", "synteny"],
    # --- Inferential evidence branch ---
    "ECO_0000361": ["inferential evidence", "inference", "deduction", "scientific inference", "genome assembly", "genome annotation", "functional annotation", "gene prediction"],
    "ECO_0000205": ["curator inference", "manual curation", "expert curation", "literature curation", "systematic literature review", "meta-analysis", "literature review", "narrative review"],
    "ECO_0000001": ["inference from background scientific knowledge", "background knowledge", "scientific reasoning"],
    "ECO_0000362": ["computational inference", "algorithm-based inference", "statistical analysis", "correlation analysis", "differential expression analysis", "DESeq2", "bioinformatics analysis", "statistical test", "enrichment analysis", "pathway analysis"],
    "ECO_0006185": ["author inference", "author claim", "author statement", "author assertion", "authors concluded", "authors suggest", "authors propose", "we conclude", "we hypothesize", "we speculate"],
    "ECO_0007647": ["curator inference from authoritative source", "authoritative source curation", "expert consensus"],
    "ECO_0007645": ["curator inference from journal publication", "journal publication curation", "literature-based curation"],
    "ECO_0007646": ["curator inference from book", "book curation", "textbook reference"],
    "ECO_0007636": ["curator inference from database", "database curation", "database-derived annotation"],
    # --- High throughput evidence branch ---
    "ECO_0006055": ["high throughput evidence", "high-throughput", "high throughput screening", "large-scale experiment"],
    "ECO_0007004": ["high throughput direct assay evidence", "high throughput assay", "large-scale assay", "high-throughput screening"],
    "ECO_0007006": ["high throughput expression pattern evidence", "high throughput expression", "large-scale expression profiling", "microarray"],
    # --- Documented statement evidence branch ---
    "ECO_0006151": ["documented statement evidence", "documented statement", "reported observation", "clinical observation", "clinical trial", "randomized controlled trial", "cohort study", "case-control study", "epidemiological study", "cross-sectional study", "longitudinal study", "patient cohort"],
    "ECO_0000311": ["imported information", "imported data", "external database reference"],
    "ECO_0006152": ["medical practitioner statement evidence", "clinical diagnosis", "medical practitioner statement", "physician report", "clinical assessment"],
    "ECO_0006153": ["self-reported individual statement evidence", "self-reported data", "patient self-report", "questionnaire response", "survey response", "dietary questionnaire", "food frequency questionnaire"],
    # --- Computational evidence branch ---
    "ECO_0007672": ["computational evidence", "computational analysis", "in silico analysis", "bioinformatics"],
    "ECO_0008000": ["machine learning method evidence", "machine learning", "ML", "deep learning", "neural network", "classifier", "predictive model"],
    "ECO_0008013": ["neural network method evidence", "neural network", "deep learning", "convolutional neural network", "CNN", "transformer model"],
    "ECO_0008001": ["deep learning neural network method evidence", "deep learning", "DNN", "deep neural network"],
    "ECO_0008010": ["support vector machine evidence", "support vector machine", "SVM"],
    "ECO_0008002": ["rule-based machine learning method evidence", "rule-based learning", "decision tree", "random forest"],
    "ECO_0008011": ["string-matching method evidence", "string matching", "text mining", "pattern matching", "regular expression"],
    "ECO_0006340": ["molecular dynamics evidence", "molecular dynamics simulation", "MD simulation"],
    "ECO_0006341": ["computational structure modeling evidence", "structure prediction", "computational modeling", "protein structure prediction"],
    # --- In situ ---
    "ECO_0001836": ["in situ hybridization evidence", "in situ hybridization", "ISH", "FISH", "fluorescence in situ hybridization"],
    # --- Microscopy ---
    "ECO_0001094": ["macroscopy evidence", "macroscopic observation", "visual inspection", "gross examination", "microscopy", "microscopic examination", "light microscopy"],
    # --- Biological system reconstruction ---
    "ECO_0000088": ["biological system reconstruction evidence", "biological system reconstruction", "network reconstruction", "pathway reconstruction", "metabolic network reconstruction"],
    # --- No evidence ---
    "ECO_0000035": ["no evidence data found", "no evidence", "unsupported claim"],
}


@dataclass
class ECOClass:
    id: str
    uri: str
    label: str
    definition: str
    parents: list[str] = field(default_factory=list)
    parent_labels: list[str] = field(default_factory=list)
    ancestor_labels: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)


@dataclass
class ECOResult:
    eco_id: str
    label: str
    definition: str
    score: float
    parents: list[str]


def parse_eco_owl(owl_path: Path = ECO_OWL_PATH) -> list[ECOClass]:
    """Parse ECO OWL/RDF XML and return non-obsolete classes with labels + definitions."""
    text = owl_path.read_text(encoding="utf-8")
    raw = re.findall(
        r'<owl:Class rdf:about="(http://purl\.obolibrary\.org/obo/ECO_\d+)">(.*?)</owl:Class>',
        text,
        re.DOTALL,
    )
    records: list[ECOClass] = []
    for uri, body in raw:
        cid = uri.split("/")[-1]
        label_m = re.search(r"<rdfs:label>([^<]+)</rdfs:label>", body)
        def_m = re.search(r"<obo:IAO_0000115>([^<]+)</obo:IAO_0000115>", body)
        parents = re.findall(
            r'<rdfs:subClassOf rdf:resource="(http://purl\.obolibrary\.org/obo/ECO_\d+)"', body
        )
        parent_ids = [p.split("/")[-1] for p in parents]
        label = label_m.group(1) if label_m else ""
        if not label or label.startswith("obsolete"):
            continue
        definition = def_m.group(1) if def_m else ""
        records.append(
            ECOClass(
                id=cid,
                uri=uri,
                label=label,
                definition=definition,
                parents=parent_ids,
            )
        )
    # Fill parent labels
    label_map = {r.id: r.label for r in records}
    for r in records:
        r.parent_labels = [label_map.get(p, "?") for p in r.parents]

    # Compute ancestor labels (transitive closure)
    def ancestors(cid: str, seen: set | None = None) -> set[str]:
        if seen is None:
            seen = set()
        rec = label_map.get(cid)
        if rec is None:
            return seen
        for pid in records_by_id.get(cid, ECOClass("", "", "", "", [])).parents:
            if pid not in seen:
                seen.add(pid)
                ancestors(pid, seen)
        return seen

    records_by_id = {r.id: r for r in records}
    for r in records:
        anc_ids = ancestors(r.id) - {r.id}
        r.ancestor_labels = [label_map.get(a, "?") for a in anc_ids if a in label_map]

    # Add curated aliases
    for r in records:
        if r.id in CURATED_SUBSET:
            r.aliases = CURATED_SUBSET[r.id]

    log.info("Parsed %d non-obsolete ECO classes from %s", len(records), owl_path.name)
    return records


def _build_embed_text(c: ECOClass) -> str:
    """Build enriched embedding text for an ECO class.

    Combines: label + definition + ancestor labels + curated aliases.
    """
    parts = [c.label]
    if c.definition:
        parts.append(c.definition)
    if c.parent_labels:
        parts.extend(c.parent_labels)
    if c.ancestor_labels:
        parts.extend(c.ancestor_labels[:5])
    if c.aliases:
        parts.extend(c.aliases)
    return " | ".join(parts)


def _embed_batch(texts: list[str], model: str = EMBED_MODEL) -> np.ndarray:
    """Embed a batch of texts via Ollama /api/embed."""
    resp = requests.post(
        f"{OLLAMA_HOST}/api/embed",
        json={"model": model, "input": texts},
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()
    return np.array(data["embeddings"], dtype=np.float32)


def _embed_single(text: str, model: str = EMBED_MODEL) -> np.ndarray:
    """Embed a single text via Ollama /api/embed."""
    resp = requests.post(
        f"{OLLAMA_HOST}/api/embed",
        json={"model": model, "input": [text]},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    return np.array(data["embeddings"][0], dtype=np.float32)


def build_eco_index(
    classes: list[ECOClass],
    cache_path: Path = CACHE_PATH,
    model: str = EMBED_MODEL,
    use_curated_only: bool = True,
) -> tuple[np.ndarray, list[str]]:
    """Build (or load cache of) ECO embedding index.

    Args:
        classes: All parsed ECO classes.
        cache_path: Where to cache the .npz file.
        model: Ollama embedding model name.
        use_curated_only: If True, only embed classes in CURATED_SUBSET.
            If False, embed all non-obsolete classes.

    Returns (embeddings [N, D], ids [N]).
    """
    if use_curated_only:
        subset = [c for c in classes if c.id in CURATED_SUBSET]
        log.info("Using curated subset: %d classes", len(subset))
        classes = subset

    cache_key = f"{len(classes)}_{use_curated_only}"
    if cache_path.exists():
        data = np.load(cache_path, allow_pickle=True)
        if str(data["cache_key"]) == cache_key:
            embeddings = data["embeddings"]
            ids = data["ids"].tolist()
            log.info("Cache hit: %d embeddings, dim=%d", embeddings.shape[0], embeddings.shape[1])
            return embeddings, ids
        log.warning("Cache stale, rebuilding")

    log.info("Embedding %d ECO classes with %s (batch=%d)...", len(classes), model, BATCH_SIZE)
    texts = [_build_embed_text(c) for c in classes]

    all_embeddings = []
    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        emb = _embed_batch(batch, model)
        all_embeddings.append(emb)
        n_batches = -(-len(texts) // BATCH_SIZE)
        log.info("  ECO embed batch %d/%d (%d texts)", i // BATCH_SIZE + 1, n_batches, len(batch))

    embeddings = np.vstack(all_embeddings)
    ids = [c.id for c in classes]

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(cache_path, embeddings=embeddings, ids=np.array(ids), cache_key=np.array(cache_key))
    log.info("Cached %d embeddings to %s", len(ids), cache_path)
    return embeddings, ids


def _normalize(vec: np.ndarray) -> np.ndarray:
    """L2-normalize a vector or matrix."""
    norm = np.linalg.norm(vec, axis=-1, keepdims=True)
    norm = np.where(norm == 0, 1, norm)
    return vec / norm


class ECOMapper:
    """Map evidence text to ECO classes via embedding similarity.

    Uses a curated subset of ~60 mid-level ECO classes most relevant to
    microbiome research, enriched with ancestor labels and custom aliases.
    """

    def __init__(
        self,
        owl_path: Path = ECO_OWL_PATH,
        cache_path: Path = CACHE_PATH,
        model: str = EMBED_MODEL,
        use_curated_only: bool = True,
    ):
        self.classes = parse_eco_owl(owl_path)
        self._by_id: dict[str, ECOClass] = {c.id: c for c in self.classes}
        self.embeddings, self.ids = build_eco_index(
            self.classes, cache_path, model, use_curated_only
        )
        self.embeddings_n = _normalize(self.embeddings)
        log.info(
            "ECOMapper ready: %d classes, dim=%d, model=%s",
            len(self.ids),
            self.embeddings.shape[1],
            model,
        )

    def map_evidence(
        self,
        evidence_text: str,
        top_k: int = TOP_K_DEFAULT,
        threshold: float = SIMILARITY_THRESHOLD,
    ) -> list[ECOResult]:
        """Map an evidence text to the top-k closest ECO classes.

        Args:
            evidence_text: Free text describing the evidence (e.g., the source
                sentence or a description of the experimental method).
            top_k: Number of top matches to return.
            threshold: Minimum cosine similarity to include.

        Returns:
            List of ECOResult sorted by descending similarity.
        """
        query_emb = _normalize(_embed_single(evidence_text))
        scores = self.embeddings_n @ query_emb
        ranked = np.argsort(-scores)[:top_k]
        results: list[ECOResult] = []
        for idx in ranked:
            score = float(scores[idx])
            if score < threshold:
                break
            eco = self._by_id[self.ids[idx]]
            results.append(
                ECOResult(
                    eco_id=eco.id,
                    label=eco.label,
                    definition=eco.definition,
                    score=score,
                    parents=eco.parent_labels,
                )
            )
        return results

    def map_evidence_batch(
        self,
        evidence_texts: list[str],
        top_k: int = TOP_K_DEFAULT,
        threshold: float = SIMILARITY_THRESHOLD,
    ) -> list[list[ECOResult]]:
        """Map a batch of evidence texts (more efficient than individual calls)."""
        all_results: list[list[ECOResult]] = []
        for i in range(0, len(evidence_texts), BATCH_SIZE):
            batch = evidence_texts[i : i + BATCH_SIZE]
            emb = _embed_batch(batch)
            emb_n = _normalize(emb)
            scores = emb_n @ self.embeddings_n.T  # [B, N]
            for j in range(len(batch)):
                row_scores = scores[j]
                ranked = np.argsort(-row_scores)[:top_k]
                results: list[ECOResult] = []
                for idx in ranked:
                    score = float(row_scores[idx])
                    if score < threshold:
                        break
                    eco = self._by_id[self.ids[idx]]
                    results.append(
                        ECOResult(
                            eco_id=eco.id,
                            label=eco.label,
                            definition=eco.definition,
                            score=score,
                            parents=eco.parent_labels,
                        )
                    )
                all_results.append(results)
        return all_results

    def best_match(self, evidence_text: str, threshold: float = SIMILARITY_THRESHOLD) -> Optional[ECOResult]:
        """Return the single best ECO match, or None if below threshold."""
        results = self.map_evidence(evidence_text, top_k=1, threshold=threshold)
        return results[0] if results else None
