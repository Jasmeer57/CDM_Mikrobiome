"""Biomni-powered triple validation and enrichment.

Uses Stanford's Biomni A1 agent (https://biomni.stanford.edu) with Ollama as the LLM
backend to validate and enrich triples extracted by extractor.py.

Two-phase hybrid pipeline:
  Phase 1 (extractor.py): Ollama/Qwen extracts raw triples from paper text
  Phase 2 (this module):   Biomni A1 agent (Ollama/Qwen inside) validates triples

The agent receives compact triples (not full paper text), so context window
pressure is minimal.  The agent reasons about:
  - Entity type correctness (e.g. "centenarians" should be CLINICAL not ORGANISM)
  - Relation direction (e.g. depleted_in: organism→disease, not disease→organism)
  - Biological plausibility (e.g. can a CHEMICAL really "produce" a CLINICAL outcome?)
  - Confidence calibration (downgrade hedged or speculative triples)

Usage:
    from cdm_pipeline.triples.biomni_validator import BiomniValidator
    validator = BiomniValidator(model="qwen3.5:9b")
    result = validator.validate_paper_triples(paper_id, triples)
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# ── CDM types (mirrors extractor.py) ──
CDM_ENTITY_TYPES = [
    "ORGANISM", "CHEMICAL", "DISEASE", "PROTEIN", "DNA_RNA", "CELL_TYPE",
    "GENOMICS", "PATHWAY", "LAB_METHOD", "DATA_ANALYSIS", "SAMPLE_METHOD",
    "CLINICAL", "EXPERIMENTAL_METHOD", "STUDY_DESIGN",
]
# ── Predicates: import the 26-predicate canonical set from predicate_synonyms
# so the validator's prompt stays in sync with extractor.py. (Originally this
# was a hard-coded 14-predicate list that would have rejected the 12 new
# predicates added in the EFRE-parity upgrade.)
try:
    from ..quality.predicate_synonyms import CANONICAL_PREDICATES
    CDM_RELATION_TYPES = sorted(CANONICAL_PREDICATES)
except ImportError:
    CDM_RELATION_TYPES = [
        "associated_with", "treats", "treated_by", "produces", "produced_by",
        "disrupts", "depleted_in", "enriched_in", "co_occurs_with",
        "encodes", "expresses", "part_of_pathway", "participates_in", "implicated_in",
    ]

# ── Ollama defaults ──
DEFAULT_MODEL = os.environ.get("BIOMNI_MODEL", "qwen3.5:9b")
DEFAULT_DATA_PATH = os.environ.get("BIOMNI_DATA_PATH", "/tmp/biomni_data")
NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "32768"))
NUM_PREDICT = int(os.environ.get("OLLAMA_NUM_PREDICT", "16384"))
MAX_RETRIES = 3
VALIDATE_BATCH_SIZE = 40
TIMEOUT = 600  # 10 min per paper
NO_THINKING = "You are a knowledge graph validator. Do not show your reasoning. Return ONLY the JSON array requested."


def _ensure_ollama_host() -> str:
    """Ensure OLLAMA_HOST has http:// prefix (same fix as extractor.py)."""
    raw = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
    if raw and not raw.startswith("http://") and not raw.startswith("https://"):
        raw = f"http://{raw}"
        os.environ["OLLAMA_HOST"] = raw
    return raw


def build_validation_prompt(paper_id: str, triples: List[Dict]) -> str:
    """Build the task prompt for the Biomni agent to validate triples."""
    triples_json = json.dumps(triples, indent=2, ensure_ascii=False)
    types_str = ", ".join(CDM_ENTITY_TYPES)
    rels_str = ", ".join(CDM_RELATION_TYPES)

    return f"""You are a strict biomedical knowledge graph curator.  Validate the
following triples extracted from microbiome paper {paper_id}.

## Validation Criteria

For each triple, evaluate these 4 dimensions:

### 1. ENTITY TYPE CORRECTNESS
Common errors to fix:
- Patient groups ("HIV+ adults", "centenarians", "patients") typed as ORGANISM or DISEASE → should be CLINICAL
- Gene clusters ("CAGs", "operons", "gene clusters") typed as ORGANISM → should be GENOMICS
- Bacterial species typed as DISEASE, or diseases typed as ORGANISM
- Dietary patterns ("high fiber diet") typed as DISEASE → should be CLINICAL
- Biomarkers ("CD4 count", "alpha diversity") typed as DISEASE → should be CLINICAL or GENOMICS

### 2. RELATION DIRECTION
- depleted_in: subject=ORGANISM (that is depleted), object=CLINICAL/DISEASE (where it is depleted)
- enriched_in: subject=ORGANISM (that is enriched), object=CLINICAL/DISEASE (where it is enriched)
- treats: subject=agent/drug, object=DISEASE
- treated_by: subject=DISEASE, object=agent/drug
- produces: subject=ORGANISM, object=CHEMICAL
- produced_by: subject=CHEMICAL, object=ORGANISM

If the subject and object are swapped (e.g., "HIV+ adults depleted_in Faecalibacterium"
where HIV+ adults is not an organism), SWAP the subject and object strings AND their types.

### 3. BIOLOGICAL PLAUSIBILITY — REJECT if implausible
REJECT a triple if:
- The evidence text does not actually support the claimed relation
- The relation is biologically nonsensical (e.g., a CHEMICAL "expresses" a gene)
- The triple is trivially true and uninformative (e.g., "bacteria associated_with humans")
- The evidence is too vague or speculative to support a specific triple
- The triple duplicates another triple with slightly different surface form

### 4. CONFIDENCE CALIBRATION
- Downgrade to ≤0.5 if the evidence is hedged ("may", "could", "suggested")
- Downgrade to ≤0.3 if the relation is inferred rather than explicitly stated
- Set to 0.0 and REJECT if the evidence contradicts the triple

## Output Format

Return ONLY a JSON array (no markdown, no code blocks, no prose).
Each object must have:
  - subject, predicate, object: the (possibly corrected) triple
  - subject_type, object_type: corrected entity types
  - confidence: adjusted confidence (0.0–1.0)
  - action: "keep" (no changes needed), "correct" (something was fixed), or "reject" (triple is wrong/implausible)
  - correction_note: what was changed, or why rejected

IMPORTANT:
- Use "keep" when nothing needs changing. Use "correct" ONLY when you actually changed something.
- Include ALL triples in the output — both kept/corrected AND rejected.
- Only REJECT triples that are clearly wrong or unsupported. Expect to reject 5–15% of triples.
- If a triple is reasonable but slightly imprecise, prefer "correct" over "reject".
- When in doubt, keep rather than reject.

Valid entity types: {types_str}
Valid predicates: {rels_str}

## TRIPLES TO VALIDATE
{triples_json}

Return ONLY the JSON array now:"""


def parse_solution(raw_response: str, paper_id: str = "") -> List[Dict]:
    """Extract JSON array from the agent's <solution> tag.

    Fallback: try to find JSON array anywhere in the response.
    """
    if not raw_response:
        return []

    # Try <solution> tag first
    match = re.search(r'<solution>\s*(.*?)\s*</solution>', raw_response, re.DOTALL)
    if match:
        raw = match.group(1).strip()
    else:
        raw = raw_response.strip()

    # Parse JSON — reuse extractor.py's multi-tier parser
    from .extractor import parse_json_response
    triples = parse_json_response(raw, paper_id)
    return triples


class BiomniValidator:
    """Triple validation via direct Ollama /api/chat calls.

    Originally designed around Stanford's Biomni A1 agent, but the agent loop
    and langchain_ollama were bypassed to ensure `think: false` is properly
    passed as a top-level API parameter for Qwen3 models.  The LLM's parametric
    knowledge is used for validation (no retrieval/datalake).

    Usage:
        from cdm_pipeline.triples.biomni_validator import BiomniValidator
        validator = BiomniValidator(model="qwen3.5:9b")
        result = validator.validate_paper_triples(paper_id, triples)
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        data_path: str = DEFAULT_DATA_PATH,
        temperature: float = 0,
        use_datalake: bool = False,
    ):
        self.model = model
        self.temperature = temperature
        self.use_datalake = use_datalake
        self.data_path = data_path
        self._agent = None
        self._init_error = None

        # Ensure Ollama host is properly formatted
        host = _ensure_ollama_host()
        logger.info(f"BiomniValidator: OLLAMA_HOST={host}, model={model}")

    def _get_agent(self):
        """Lazily initialize the Biomni A1 agent."""
        if self._agent is not None:
            return self._agent

        if self._init_error is not None:
            raise RuntimeError(f"Biomni init previously failed: {self._init_error}")

        try:
            from biomni.agent import A1
            from biomni.config import default_config

            # Configure Biomni defaults for Ollama
            default_config.llm = self.model
            default_config.source = "Ollama"
            default_config.temperature = self.temperature

            # Skip datalake download unless explicitly requested
            expected_files = None if self.use_datalake else []

            logger.info("Initializing Biomni A1 agent (Ollama backend)...")
            agent = A1(
                path=self.data_path,
                llm=self.model,
                source="Ollama",
                use_tool_retriever=False,
                expected_data_lake_files=expected_files,
            )

            # Increase context window for ChatOllama
            self._patch_llm_context(agent)

            self._agent = agent
            logger.info("Biomni A1 agent ready")
            return agent

        except Exception as e:
            self._init_error = str(e)
            logger.error(f"Failed to initialize Biomni agent: {e}")
            raise

    def _patch_llm_context(self, agent):
        """Patch the agent's LLM to use a larger context window and disable thinking."""
        llm = agent.llm
        # ChatOllama from langchain_ollama supports num_ctx
        if hasattr(llm, 'num_ctx'):
            llm.num_ctx = NUM_CTX
            logger.info(f"Set num_ctx={NUM_CTX} on {type(llm).__name__}")
        elif hasattr(llm, 'model_kwargs'):
            llm.model_kwargs.setdefault('options', {})['num_ctx'] = NUM_CTX
            logger.info(f"Set options.num_ctx={NUM_CTX} via model_kwargs on {type(llm).__name__}")
        else:
            logger.warning(
                f"Cannot set num_ctx on {type(llm).__name__} — "
                f"context window may be too small for large inputs"
            )

        # Disable thinking mode for Qwen3 models (prevents verbose reasoning output)
        # Qwen3 models use /api/chat with think parameter; langchain_ollama passes
        # model_kwargs through to the API.
        model_name = getattr(llm, 'model', '') or ''
        if 'qwen3' in model_name.lower():
            if hasattr(llm, 'model_kwargs'):
                llm.model_kwargs['think'] = False
            else:
                llm.model_kwargs = {'think': False}
            logger.info(f"Disabled thinking mode for {model_name}")

    def _call_ollama_direct(self, prompt: str, paper_id: str) -> Optional[str]:
        """Call Ollama /api/chat directly with think=false (like extractor.py).

        This bypasses langchain_ollama and Biomni's agent loop entirely,
        giving full control over the API payload including the top-level
        `think` parameter for Qwen3 models.
        """
        host = _ensure_ollama_host()
        endpoint = f"{host.rstrip('/')}/api/chat"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": NO_THINKING},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "think": False,
            "format": None,
            "options": {
                "temperature": self.temperature,
                "top_p": 0.9,
                "seed": 42,
                "num_ctx": NUM_CTX,
                "num_predict": NUM_PREDICT,
            },
        }

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = requests.post(endpoint, json=payload, timeout=TIMEOUT)
                if resp.status_code == 200:
                    data = resp.json()
                    msg = data.get("message", {})
                    raw = msg.get("content", "").strip()
                    if not raw:
                        logger.warning(f"[{paper_id}] Empty response (attempt {attempt})")
                        time.sleep(5 * attempt)
                        continue
                    return raw
                else:
                    logger.error(f"[{paper_id}] Ollama HTTP {resp.status_code}: {resp.text[:200]}")
                    time.sleep(10 * attempt)
            except requests.exceptions.Timeout:
                logger.warning(f"[{paper_id}] Timeout (attempt {attempt}/{MAX_RETRIES})")
                time.sleep(10)
            except requests.exceptions.ConnectionError as e:
                logger.warning(f"[{paper_id}] Connection error (attempt {attempt}/{MAX_RETRIES}): {e}")
                time.sleep(10 * attempt)

        return None

    def validate_paper_triples(
        self,
        paper_id: str,
        triples: List[Dict],
    ) -> Dict:
        """Validate triples for a single paper using direct Ollama API calls.

        Triples are batched in groups of VALIDATE_BATCH_SIZE to avoid LLM
        output truncation (num_predict limit).  Results are merged.

        Args:
            paper_id: Paper identifier (e.g. "PRJEB12345")
            triples: List of triple dicts from extractor.py

        Returns:
            {
                "paper_id": str,
                "n_input": int,
                "n_kept": int,
                "n_corrected": int,
                "n_rejected": int,
                "validated_triples": List[Dict],
                "rejected_triples": List[Dict],
                "elapsed_s": float,
                "timestamp": str,
            }
        """
        if not triples:
            return {
                "paper_id": paper_id,
                "n_input": 0,
                "n_kept": 0,
                "n_corrected": 0,
                "n_rejected": 0,
                "validated_triples": [],
                "rejected_triples": [],
                "elapsed_s": 0.0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        t0 = time.time()

        # Batch triples to avoid LLM output truncation
        all_kept: List[Dict] = []
        all_corrected: List[Dict] = []
        all_rejected: List[Dict] = []
        n_implicit_rejected = 0

        n_batches = (len(triples) + VALIDATE_BATCH_SIZE - 1) // VALIDATE_BATCH_SIZE
        for i in range(0, len(triples), VALIDATE_BATCH_SIZE):
            batch = triples[i : i + VALIDATE_BATCH_SIZE]
            batch_task = build_validation_prompt(paper_id, batch)
            raw_response = self._call_ollama_direct(batch_task, paper_id)

            if raw_response is None:
                logger.error(f"[{paper_id}] Batch {i//VALIDATE_BATCH_SIZE + 1}/{n_batches}: LLM failed, keeping batch as-is")
                all_kept.extend(batch)
                continue

            validated = parse_solution(str(raw_response), paper_id)

            kept, corrected, rejected = [], [], []
            for vt in validated:
                if not isinstance(vt, dict):
                    continue
                action = str(vt.get("action", "keep")).strip().lower()
                if action == "reject":
                    rejected.append(vt)
                elif action == "correct":
                    corrected.append(vt)
                else:
                    kept.append(vt)

            n_returned = len(kept) + len(corrected) + len(rejected)
            n_missing = len(batch) - n_returned
            if n_missing > 0:
                logger.info(f"[{paper_id}] Batch {i//VALIDATE_BATCH_SIZE + 1}/{n_batches}: {n_missing} implicit rejects")
                n_implicit_rejected += n_missing

            all_kept.extend(kept)
            all_corrected.extend(corrected)
            all_rejected.extend(rejected)

        all_validated = all_kept + all_corrected
        elapsed = time.time() - t0
        total_rejected = len(all_rejected) + n_implicit_rejected

        logger.info(
            f"[{paper_id}] Validation: {len(triples)} input → "
            f"{len(all_kept)} kept, {len(all_corrected)} corrected, "
            f"{total_rejected} rejected ({elapsed:.0f}s, {n_batches} batches)"
        )

        return {
            "paper_id": paper_id,
            "n_input": len(triples),
            "n_kept": len(all_kept),
            "n_corrected": len(all_corrected),
            "n_rejected": total_rejected,
            "validated_triples": all_validated,
            "rejected_triples": all_rejected,
            "elapsed_s": round(elapsed, 1),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def validate_batch(
        self,
        papers_triples: Dict[str, List[Dict]],
        output_dir: Path,
        checkpoint_path: Path,
    ) -> Dict:
        """Validate triples for multiple papers with checkpoint/resume.

        Args:
            papers_triples: {paper_id: [triple, ...]}
            output_dir: Directory for per-paper JSON outputs
            checkpoint_path: Path to checkpoint.json
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        # Load checkpoint
        cp = {"done": {}, "errors": {}, "started": None}
        if checkpoint_path.exists():
            with open(checkpoint_path, encoding="utf-8") as f:
                cp = json.load(f)
        if not cp.get("started"):
            cp["started"] = datetime.now(timezone.utc).isoformat()

        done = set(cp["done"].keys())
        todo = [(pid, trps) for pid, trps in papers_triples.items() if pid not in done]

        total = len(papers_triples)
        remaining = len(todo)
        logger.info(f"Biomni validation: {len(done)} done, {remaining} remaining (of {total} total)")

        t0 = time.time()
        processed = 0

        for pid, trps in todo:
            paper_t0 = time.time()
            out_path = output_dir / f"{pid}.validated.json"

            try:
                result = self.validate_paper_triples(pid, trps)

                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(result, f, indent=2, ensure_ascii=False)

                elapsed = time.time() - paper_t0
                cp["done"][pid] = {
                    "time": round(elapsed, 1),
                    "n_input": result["n_input"],
                    "n_kept": result["n_kept"],
                    "n_corrected": result["n_corrected"],
                    "n_rejected": result["n_rejected"],
                    "output": str(out_path),
                    "completed": datetime.now(timezone.utc).isoformat(),
                }

                logger.info(
                    f"[{len(done) + processed + 1}/{total}] {pid}: "
                    f"{result['n_input']} → {result['n_kept'] + result['n_corrected']} "
                    f"({elapsed:.0f}s)"
                )

            except Exception as ex:
                elapsed = time.time() - paper_t0
                cp["errors"][pid] = {
                    "error": str(ex)[:300],
                    "time": round(elapsed, 1),
                }
                logger.error(f"[{pid}] ERROR: {ex}")

            processed += 1
            if processed % 5 == 0:
                self._save_checkpoint(cp, checkpoint_path)
                rate = processed / (time.time() - t0) if time.time() > t0 else 0
                eta = (remaining - processed) / rate / 60 if rate > 0 else 0
                logger.info(
                    f"  Checkpoint: {processed}/{remaining}. "
                    f"Rate: {rate:.2f}/min. ETA: {eta:.1f}h"
                )

        self._save_checkpoint(cp, checkpoint_path)

        total_time = time.time() - t0
        summary = {
            "model": self.model,
            "total_papers": total,
            "successful": len(cp["done"]),
            "failed": len(cp.get("errors", {})),
            "total_kept": sum(v.get("n_kept", 0) for v in cp["done"].values()),
            "total_corrected": sum(v.get("n_corrected", 0) for v in cp["done"].values()),
            "total_rejected": sum(v.get("n_rejected", 0) for v in cp["done"].values()),
            "elapsed_min": round(total_time / 60, 1),
            "completed": datetime.now(timezone.utc).isoformat(),
        }

        summary_path = output_dir / "validation_summary.json"
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        logger.info(f"Validation complete: {summary}")
        return summary

    @staticmethod
    def _save_checkpoint(cp, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cp, f, indent=2, ensure_ascii=False)
