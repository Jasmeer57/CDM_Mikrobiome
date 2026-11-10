"""Conformal prediction for mapping confidence calibration.

Split conformal prediction (SCP) provides distribution-free prediction sets
with finite-sample coverage guarantees. Applied here to ontology mapping:
  - Nonconformity score = 1 - confidence (from _confidence())
  - Calibration set: mappings with known-correct labels (KB-curated or exact string match)
  - Test set: all remaining mappings
  - Output: prediction sets at user-specified alpha (1 - coverage level)

Optionally applies Benjamini-Hochberg FDR control on the conformal p-values
for per-mapping error control.

Usage:
    from cdm_pipeline.export.conformal import calibrate_mappings
    calibrate_mappings(db_path, alpha=0.1)
"""
import math
import sqlite3
from pathlib import Path
from typing import List, Tuple

from ..config import CDM_OUTPUT_DIR


def _bh_fdr(pvalues: List[float], alpha: float = 0.05) -> List[bool]:
    """Benjamini-Hochberg FDR correction.

    Returns a list of booleans (same length) indicating whether each p-value
    is significant at the given FDR level.
    """
    n = len(pvalues)
    indexed = sorted(enumerate(pvalues), key=lambda x: x[1])
    rejected = [False] * n
    max_k = 0
    for rank, (orig_idx, pval) in enumerate(indexed, 1):
        if pval <= (rank / n) * alpha:
            max_k = rank
    for rank, (orig_idx, _) in enumerate(indexed, 1):
        if rank <= max_k:
            rejected[orig_idx] = True
    return rejected


def calibrate_mappings(db_path: Path, alpha: float = 0.1, fdr_alpha: float = 0.05):
    """Apply split conformal prediction to ontology mappings in the DB.

    Adds a `conformal_pvalue` and `conformal_in_set` column to the
    controlled_vocabularies table, indicating whether each mapping is in the
    prediction set at coverage level (1 - alpha).

    Args:
        db_path: Path to the SQLite DB
        alpha: Miscoverage level (0.1 → 90% coverage)
        fdr_alpha: FDR level for BH correction of conformal p-values
    """
    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()

    # Add columns if not present
    try:
        c.execute("ALTER TABLE controlled_vocabularies ADD COLUMN conformal_pvalue REAL")
        c.execute("ALTER TABLE controlled_vocabularies ADD COLUMN conformal_in_set BOOLEAN DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # Columns already exist

    # Calibration set: KB-curated or exact string match (confidence = 1.0)
    cal_rows = c.execute("""
        SELECT cv.id, cv.mapping_confidence
        FROM controlled_vocabularies cv
        JOIN entities e ON cv.entity_id = e.id
        WHERE cv.mapping_source LIKE '%kb%' OR cv.mapping_confidence >= 0.99
    """).fetchall()

    # Test set: all other mappings
    test_rows = c.execute("""
        SELECT cv.id, cv.mapping_confidence
        FROM controlled_vocabularies cv
        WHERE cv.mapping_source NOT LIKE '%kb%' AND cv.mapping_confidence < 0.99
    """).fetchall()

    if not cal_rows:
        print("Conformal CP: no calibration set available (need KB-curated or exact matches)")
        conn.close()
        return

    # Nonconformity scores from calibration set
    cal_scores = sorted([1.0 - (r[1] or 0.5) for r in cal_rows])
    n_cal = len(cal_scores)

    # Conformal p-value for each test mapping
    test_pvalues = []
    for cv_id, conf in test_rows:
        score = 1.0 - (conf or 0.5)
        # p-value = (rank of score in calibration set + 1) / (n_cal + 1)
        rank = sum(1 for s in cal_scores if s <= score)
        pval = (rank + 1) / (n_cal + 1)
        test_pvalues.append((cv_id, pval))

    # Threshold for prediction set: ceil((1 - alpha) * (n_cal + 1)) / (n_cal + 1)
    threshold_rank = math.ceil((1 - alpha) * (n_cal + 1))
    if threshold_rank > n_cal:
        threshold_rank = n_cal
    pval_threshold = cal_scores[threshold_rank - 1] if threshold_rank > 0 else float('inf')

    # Update conformal p-values
    for cv_id, pval in test_pvalues:
        c.execute("UPDATE controlled_vocabularies SET conformal_pvalue=? WHERE id=?",
                  (pval, cv_id))

    # BH-FDR on p-values
    if fdr_alpha and test_pvalues:
        pvals = [p for _, p in test_pvalues]
        rejected = _bh_fdr(pvals, alpha=fdr_alpha)
        for (cv_id, _), is_in_set in zip(test_pvalues, rejected):
            c.execute("UPDATE controlled_vocabularies SET conformal_in_set=? WHERE id=?",
                      (1 if is_in_set else 0, cv_id))

    conn.commit()

    n_in_set = sum(1 for _, p in test_pvalues if p <= pval_threshold)
    n_fdr = sum(1 for _, p in test_pvalues if p <= fdr_alpha / len(test_pvalues)) if test_pvalues else 0

    print(f"Conformal CP: calibration set={n_cal}, test set={len(test_rows)}, "
          f"in prediction set (α={alpha}): {n_in_set}/{len(test_rows)}")

    conn.close()


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Conformal prediction calibration for CDM mappings")
    p.add_argument("--db", type=Path, default=CDM_OUTPUT_DIR / "microbiome_cdm.db")
    p.add_argument("--alpha", type=float, default=0.1, help="Miscoverage level (default: 0.1 = 90% coverage)")
    p.add_argument("--fdr-alpha", type=float, default=0.05, help="FDR level for BH correction")
    args = p.parse_args()
    calibrate_mappings(args.db, alpha=args.alpha, fdr_alpha=args.fdr_alpha)
