"""Shared helpers for the competitor comparisons (src/scripts/competitors/): Wilson intervals, document-level bootstrap
for P/R/F1, manifest writing (SHA-256 of downloaded files). No inputs/outputs of its own.
Written with Claude Code (declare)."""
from __future__ import annotations

import hashlib
import json
import math
import random
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
SCRATCH = ROOT / "outputs/scratch/competitors"
RESULTS = ROOT / "outputs/results/competitor_compare_2026-11-11"


def wilson(k, n, z=1.959964):
    """Wilson score 95% interval for k/n -> dict(k, n, p, lo, hi)."""
    if n == 0:
        return {"k": k, "n": 0, "p": None, "lo": None, "hi": None}
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return {"k": k, "n": n, "p": round(p, 4), "lo": round(max(0.0, c - h), 4), "hi": round(min(1.0, c + h), 4)}


def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def prf_boot(units, n_boot=2000, seed=20261111):
    """units: list of (tp, fp, fn) per resampling unit (document / sentence). Returns P/R/F1 with percentile 95% CIs
    from a cluster bootstrap over units, plus Wilson intervals for P (tp/(tp+fp)) and R (tp/(tp+fn))."""
    T = [sum(u[i] for u in units) for i in range(3)]
    p, r, f = prf(*T)
    rng = random.Random(seed)
    bs = []
    for _ in range(n_boot):
        s = [units[rng.randrange(len(units))] for _ in units]
        bs.append(prf(*[sum(u[i] for u in s) for i in range(3)]))
    q = lambda xs, a: sorted(xs)[int(a * (len(xs) - 1))]
    out = {"tp": T[0], "fp": T[1], "fn": T[2], "n_units": len(units)}
    for name, v, i in (("precision", p, 0), ("recall", r, 1), ("f1", f, 2)):
        xs = [b[i] for b in bs]
        out[name] = {"value": round(v, 4), "boot_lo": round(q(xs, 0.025), 4), "boot_hi": round(q(xs, 0.975), 4)}
    out["precision"]["wilson"] = wilson(T[0], T[0] + T[1])
    out["recall"]["wilson"] = wilson(T[0], T[0] + T[2])
    return out


def macro_f1_boot(pairs, labels, n_boot=2000, seed=20261111):
    """pairs: list of (gold, pred). Accuracy (Wilson) + macro-F1 over `labels` with bootstrap CI + per-class P/R/F1."""
    def macro(ps):
        fs = []
        for l in labels:
            tp = sum(1 for g, p in ps if g == l and p == l)
            fp = sum(1 for g, p in ps if g != l and p == l)
            fn = sum(1 for g, p in ps if g == l and p != l)
            fs.append(prf(tp, fp, fn)[2])
        return sum(fs) / len(fs)
    rng = random.Random(seed)
    bs = sorted(macro([pairs[rng.randrange(len(pairs))] for _ in pairs]) for _ in range(n_boot))
    per = {}
    for l in labels:
        tp = sum(1 for g, p in pairs if g == l and p == l)
        fp = sum(1 for g, p in pairs if g != l and p == l)
        fn = sum(1 for g, p in pairs if g == l and p != l)
        P, R, F = prf(tp, fp, fn)
        per[l] = {"n_gold": tp + fn, "n_pred": tp + fp, "precision": round(P, 4), "recall": round(R, 4), "f1": round(F, 4),
                  "recall_wilson": wilson(tp, tp + fn)}
    acc = wilson(sum(1 for g, p in pairs if g == p), len(pairs))
    return {"n": len(pairs), "accuracy_micro_f1": acc, "macro_f1": {"value": round(macro(pairs), 4), "boot_lo": round(bs[int(.025 * (n_boot - 1))], 4),
            "boot_hi": round(bs[int(.975 * (n_boot - 1))], 4)}, "per_class": per}


def confusion(pairs):
    m = {}
    for g, p in pairs:
        m.setdefault(g, {}).setdefault(p, 0)
        m[g][p] += 1
    return m


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def write_manifest(dirpath, source, licence, version, notes=""):
    """MANIFEST.json + MANIFEST.sha256 for every file under dirpath (excluding the manifests)."""
    dirpath = Path(dirpath)
    files = sorted(p for p in dirpath.rglob("*") if p.is_file() and not p.name.startswith("MANIFEST"))
    lines = [f"{sha256(p)}  {p.relative_to(dirpath)}" for p in files]
    (dirpath / "MANIFEST.sha256").write_text("\n".join(lines) + "\n")
    (dirpath / "MANIFEST.json").write_text(json.dumps({"source": source, "licence": licence, "version": version,
                                                       "notes": notes, "n_files": len(files)}, indent=1) + "\n")


def dump(obj, path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n")
