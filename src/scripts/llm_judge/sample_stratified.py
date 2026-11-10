"""P3 - deterministic stratified sample of the three judge inputs.

  triples  : 2,500  stratified by relation
  mappings : 5,000  stratified by mapping_relation
  records  : 2,500  stratified by entity_type

Ranking: sha1("judge-v1|" + item_id); take the smallest K per stratum with K
allocated proportionally to stratum size (largest-remainder). Deterministic.

Writes $OUTD/labeled/sample_input.jsonl and sample_strata.json.
"""

_CDM_ROOT = next(p for p in __import__("pathlib").Path(__file__).resolve().parents
                 if (p / ".cdm_root").is_file())  # repo root, found at run time
import argparse
import hashlib
import json
import os

ROOT = str(_CDM_ROOT)
OUTD = os.path.join(ROOT, "outputs/logs", "gold_standard")
LAB = os.path.join(OUTD, "labeled")

SPECS = [
    ("triples", "triples_input.jsonl", "relation", 2500),
    ("mappings", "mappings_input.jsonl", "mapping_relation", 5000),
    ("records", "records_input.jsonl", "entity_type", 2500),
]


def rank(item_id):
    return hashlib.sha1(("judge-v1|" + str(item_id)).encode()).hexdigest()


def load(path):
    rows = []
    with open(path) as fh:
        for line in fh:
            rows.append(json.loads(line))
    return rows


def stratum_key(row, field):
    # mappings_input carries no mapping_relation column; recover via the
    # original file keyed by item_id at load time (handled by caller).
    v = row.get(field)
    return v if v not in (None, "") else "(none)"


def allocate(counts, total):
    """Largest-remainder proportional allocation, capped at stratum size."""
    grand = sum(counts.values())
    if grand == 0:
        return {k: 0 for k in counts}
    raw = {k: total * c / grand for k, c in counts.items()}
    base = {k: int(v) for k, v in raw.items()}
    rem = total - sum(base.values())
    order = sorted(counts, key=lambda k: (-(raw[k] - base[k]), k))
    i = 0
    while rem > 0:
        k = order[i % len(order)]
        if base[k] < counts[k]:
            base[k] += 1
            rem -= 1
        i += 1
        if i > 10 * len(order) + 10:
            break
    return base


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--indir", default=LAB)
    ap.add_argument("--outdir", default=LAB)
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)

    # mapping_relation is not in mappings_input.jsonl (by design: the judge must
    # not see it). Recover the stratum label read-only from the source file,
    # keyed by mapping_id, for sampling/stratification only.
    map_rel = {}
    src = os.path.join(ROOT, "outputs/results", "terminology_v1", "term_ontology_mappings.jsonl")
    with open(src) as fh:
        for line in fh:
            d = json.loads(line)
            map_rel[d.get("mapping_id")] = d.get("mapping_relation") or "(none)"

    all_rows = []
    strata = {}
    for name, fname, field, total in SPECS:
        rows = load(os.path.join(args.indir, fname))
        for r in rows:
            if name == "mappings":
                r["_stratum"] = map_rel.get(r["item_id"], "(none)")
            else:
                r["_stratum"] = stratum_key(r, field)
        by = {}
        for r in rows:
            by.setdefault(r["_stratum"], []).append(r)
        counts = {k: len(v) for k, v in by.items()}
        alloc = allocate(counts, total)
        chosen = []
        for k in sorted(by):
            pool = sorted(by[k], key=lambda r: rank(r["item_id"]))[:alloc[k]]
            chosen.extend(pool)
        for r in chosen:
            r["artifact"] = name
            r["item_id"] = r["item_id"]
        all_rows.extend(chosen)
        strata[name] = {
            "requested": total,
            "selected": len(chosen),
            "strata": {k: {"population": counts[k], "selected": alloc[k]}
                       for k in sorted(by)},
        }
        print("%-9s selected %5d / requested %5d  (%d strata)"
              % (name, len(chosen), total, len(counts)))

    # stable output ordering: artifact, then stratum, then sha1 rank
    all_rows.sort(key=lambda r: (r["artifact"], r["_stratum"], rank(r["item_id"])))
    out = os.path.join(args.outdir, "sample_input.jsonl")
    with open(out, "w") as fh:
        for r in all_rows:
            # strip the internal stratum label so it can never leak into a prompt
            # (mapping_relation must stay hidden from the judge).
            r.pop("_stratum", None)
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(os.path.join(args.outdir, "sample_strata.json"), "w") as fh:
        json.dump({"total": len(all_rows), "artifacts": strata}, fh, indent=1)
    print("total sample:", len(all_rows), "->", out)


if __name__ == "__main__":
    main()
