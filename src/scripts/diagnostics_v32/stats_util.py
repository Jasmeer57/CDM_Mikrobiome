"""Small shared statistics helpers for the 2026-11-11 reviewer diagnostics (Wilson CI, Cohen's kappa, bootstrap).
Written with Claude Code (declare)."""
from __future__ import annotations

import math
import random
from collections import Counter

Z = 1.959964


def wilson(k, n, z=Z):
    """95% Wilson interval in percent, or None when n == 0."""
    if not n:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(100 * (c - h), 1), round(100 * (c + h), 1)]


def prop(k, n):
    return {"k": k, "n": n, "pct": round(100 * k / n, 1) if n else None, "wilson95": wilson(k, n)}


def kappa(a, b):
    n = len(a)
    if not n:
        return None
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb.get(k, 0) for k in ca) / (n * n)
    return None if pe == 1 else (po - pe) / (1 - pe)


def boot_ci(pairs, stat, reps=2000, seed=20261111):
    """Percentile bootstrap (resampling items) of stat(list_of_pairs); returns [lo, hi] rounded to 3 dp."""
    rng = random.Random(seed)
    vals = []
    for _ in range(reps):
        s = [pairs[rng.randrange(len(pairs))] for _ in pairs]
        v = stat(s)
        if v is not None:
            vals.append(v)
    if not vals:
        return None
    vals.sort()
    return [round(vals[int(0.025 * len(vals))], 3), round(vals[int(0.975 * len(vals)) - 1], 3)]


def kappa_with_ci(a, b, reps=2000):
    pairs = list(zip(a, b))
    k = kappa(a, b)
    return {"kappa": None if k is None else round(k, 3), "n": len(pairs),
            "bootstrap95": boot_ci(pairs, lambda s: kappa([x for x, _ in s], [y for _, y in s]), reps)}
