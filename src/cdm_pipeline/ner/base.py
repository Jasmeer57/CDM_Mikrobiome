"""Abstract base class for NER models.

All NER models in the pipeline inherit from :class:`BaseNERModel` and implement
two methods:

* :meth:`load`       — load the model into memory (GPU/CPU placement happens here)
* :meth:`predict_text` — extract entities from raw text, returning a list of
  dicts with keys ``start``, ``end``, ``text``, ``label``.

The shared :meth:`run` method handles paper iteration, progress reporting,
incremental mode, and CSV saving — so individual model classes stay small.
"""
import csv
import io
import sys
import time
from pathlib import Path

from ..config import PAPERS_DIR, NER_OUTPUT_DIR


class BaseNERModel:
    """Base class for all NER models.

    Subclasses must set:
        name         — short identifier (used in CSV ``model`` column)
        output_file  — CSV filename (relative to NER_OUTPUT_DIR)

    Subclasses must implement:
        load()       — load model into memory
        predict_text(text, base_offset=0) → list[dict]

    Args:
        entity_types: list of entity type labels this model can emit.
            Defaults to ``CDM_TYPES`` from config. Override per-domain.
        threshold: confidence threshold (model-specific interpretation).
        chunk_size: character chunk size for long text splitting.
        report_every: progress print interval (number of papers).
    """

    name = "base"
    output_file = "base_ner.csv"

    def __init__(self, entity_types=None, threshold=0.5, chunk_size=2000,
                 report_every=10, **kwargs):
        if entity_types is None:
            from ..config import CDM_TYPES
            entity_types = CDM_TYPES
        self.entity_types = list(entity_types)
        self.threshold = threshold
        self.chunk_size = chunk_size
        self.report_every = report_every
        self.model = None
        self._loaded = False

    # ── to implement ──

    def load(self):
        """Load the model into memory. Sets ``self.model`` and ``self._loaded``."""
        raise NotImplementedError

    def predict_text(self, text, base_offset=0):
        """Extract entities from text.

        Returns:
            list of dict with keys: start, end, text, label
            (offsets are absolute, i.e. base_offset + relative offset)
        """
        raise NotImplementedError

    # ── shared logic ──

    def _ensure_loaded(self):
        if not self._loaded:
            self.load()
            self._loaded = True

    def map_label(self, raw_label):
        """Map a model-specific label to a CDM type. Override per model."""
        return raw_label

    def run(self, papers, paper_dir=None, incremental=False, output_path=None):
        """Run this model on a list of paper filenames.

        Args:
            papers: list of filenames (e.g. ``"PRJNA12345.txt"``)
            paper_dir: directory containing the paper files (default: PAPERS_DIR)
            incremental: if True, skip papers already present in the output CSV
            output_path: override the default output CSV path

        Returns:
            (results, elapsed) where results is a list of tuples:
            (term, label, model_name, paper, char_start, char_end)
        """
        self._ensure_loaded()

        paper_dir = Path(paper_dir) if paper_dir else PAPERS_DIR
        if output_path is None:
            output_path = NER_OUTPUT_DIR / self.output_file
        else:
            output_path = Path(output_path)

        existing_results = []
        if incremental and output_path.exists():
            with open(output_path, encoding="utf-8", errors="replace") as f:
                content = f.read().replace("\x00", "")
                existing_results = list(csv.DictReader(io.StringIO(content)))
            done = set(r["paper"] for r in existing_results)
            papers = [p for p in papers if p not in done]
            print("[%s] Incremental: %d done, %d remaining" % (
                self.name, len(done), len(papers)))

        if not papers:
            print("[%s] Nothing to do." % self.name)
            return [], 0.0

        print("[%s] Running on %d papers" % (self.name, len(papers)))
        all_results = []
        t0 = time.time()

        for idx, paper_file in enumerate(papers):
            path = paper_dir / paper_file
            text = path.read_text(encoding="utf-8", errors="replace")
            preds = self.predict_text(text)

            for p in preds:
                all_results.append((
                    p["text"].strip(),
                    p["label"],
                    self.name,
                    paper_file,
                    p["start"],
                    p["end"],
                ))

            if (idx + 1) % self.report_every == 0 or idx == len(papers) - 1:
                elapsed = time.time() - t0
                rate = (idx + 1) / elapsed if elapsed > 0 else 0
                remaining = (len(papers) - idx - 1) / rate if rate > 0 else 0
                print("  [%s] %d/%d papers (%d ents, %.1fs, ETA %.0fs)" % (
                    self.name, idx + 1, len(papers), len(all_results),
                    elapsed, remaining))
                sys.stdout.flush()

        elapsed = time.time() - t0
        print("[%s] Done: %d entities from %d papers in %.1fs" % (
            self.name, len(all_results), len(papers), elapsed))

        # Save CSV
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fields = ["term", "labels", "model", "paper", "char_start", "char_end"]
        merged = existing_results + [
            dict(zip(fields, r)) for r in all_results
        ]
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(merged)
        print("[%s] Saved %d rows to %s" % (self.name, len(merged), output_path))

        return all_results, elapsed

    def run_on_docs(self, docs):
        """Run on pre-loaded documents (for benchmarking).

        Args:
            docs: list of (doc_id, text, gold_entities)

        Returns:
            (results, elapsed) where results is list of (doc_id, predictions)
            with predictions as list of {start, end, text, label}
        """
        self._ensure_loaded()

        results = []
        t0 = time.time()
        for idx, (doc_id, text, gold) in enumerate(docs):
            preds = self.predict_text(text)
            results.append((doc_id, preds))
            if (idx + 1) % 500 == 0 or idx == len(docs) - 1:
                print("  [%s] %d/%d docs (%.1fs)" % (
                    self.name, idx + 1, len(docs), time.time() - t0))

        elapsed = time.time() - t0
        print("[%s] Done: %d docs in %.1fs" % (self.name, len(docs), elapsed))
        return results, elapsed
