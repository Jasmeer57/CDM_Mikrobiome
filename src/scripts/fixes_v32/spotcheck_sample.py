"""Hand spot-check sample: 40 random 3.2.0-candidate values per field (seed 20261111, fixed before sampling).
Unit = a paper-level value (one key with its first evidence span), because record-level values repeat the paper's
value across that paper's assay records. CITED_PROTOCOL values are eligible. Writes spotcheck_sample.csv with the
evidence span and +-300 characters of context; verdict / reason columns are filled by hand (spotcheck_verdicts.csv).
    python src/scripts/fixes_v32/spotcheck_sample.py
Written with Claude Code (declare).
"""
from __future__ import annotations

import csv
import json
import random
import sqlite3
import sys
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(Path(__file__).resolve().parent))
import gazetteer as G  # noqa: E402

SEED, N = 20261111, 40


def main():
    c = sqlite3.connect(f"file:{ROOT / 'releases/cdm_v3/3.0.3/microbiome_cdm_v3.db'}?mode=ro", uri=True)
    sec = {(p, s): t for p, s, t in c.execute("SELECT paper_id, section_id_original, section_text_original FROM section")}
    units = {"dna_extraction_method": [], "sequencing_platform": []}
    for o in map(json.loads, open(G.OUT / "paper_values_v32.jsonl", encoding="utf-8")):
        if o["field"] in units:
            for v in o["values"]:
                units[o["field"]].append((o["paper_id"], v["value"], v["field_source"], v["field_confidence"], v["evidence"][0]))
        elif o["field"] == "dna_extraction_method_cited_protocol":
            units["dna_extraction_method"].append((o["paper_id"], "CITED_PROTOCOL", "llm_only", "low", o["evidence"][0]))
    rows = []
    for f, us in units.items():
        rng = random.Random(f"{SEED}-{f}")
        for i, (pid, val, src, conf, e) in enumerate(rng.sample(sorted(us, key=lambda u: (u[0], u[1])), min(N, len(us)))):
            t = sec[(pid, e["section_id"])]
            rows.append({"field": f, "n": i + 1, "paper_id": pid, "value": val, "field_source": src, "field_confidence": conf,
                         "section_id": e["section_id"], "start": e["start"], "end": e["end"], "evidence_span": t[e["start"]:e["end"]],
                         "context": " ".join(t[max(0, e["start"] - 300):e["end"] + 300].split()), "verdict": "", "reason": ""})
    with open(G.OUT / "spotcheck_sample.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(len(rows), "rows; pools:", {f: len(u) for f, u in units.items()})


if __name__ == "__main__":
    main()
