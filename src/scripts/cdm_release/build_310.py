"""Build and freeze CDM 3.1.0 = frozen CDM 3.0.3 + the cleaned / enriched / repaired layers of 2026-11-09/10.

    python3 src/scripts/cdm_release/build_310.py

- copies releases/cdm_v3/3.0.3/microbiome_cdm_v3.db (verified sha256) to a staging file;
- adds NEW tables only (the 44 tables of 3.0.3 keep every row; run_metadata gets updated version keys and
  cdm_change_log gets appended rows, both logged);
- verifies: every 3.0.3 table has the same row count; every new table has the row count of its source file;
- writes releases/cdm_v3/3.1.0/{microbiome_cdm_v3.1.0.db, README.md, CHANGES_310.md, build_310.py, sources/*.json,
  MANIFEST.sha256}, makes them read-only and appends releases/RELEASES.md.
Refuses to run if releases/cdm_v3/3.1.0 already exists.
"""
from __future__ import annotations

import csv
import datetime
import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import sys
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
SRC_DB = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
SRC_SHA = "5d23ba87d29ac7a6de831e66b35c0f42bc10312132cf20dd0191526b8b041e3e"
OUT = ROOT / "releases/cdm_v3/3.1.0"
DB_NAME = "microbiome_cdm_v3.1.0.db"
R = ROOT / "outputs/results"
csv.field_size_limit(sys.maxsize)

# new table -> (source file, provenance, description)
NEW = {
    "term_dedup_map": (R / "clean_vocabulary_2026-11-10/term_id_map.csv", "DETERMINISTIC+EMBEDDING",
                       "every canonical term -> canonical term after exact/fuzzy/abbreviation/embedding dedup; kept flag"),
    "concept_curie_map": (R / "clean_vocabulary_2026-11-10/concept_id_map.csv", "DETERMINISTIC+EMBEDDING",
                          "every accepted concept IRI -> CURIE -> canonical concept after dedup; kept flag"),
    "term_curation": (R / "clean_vocabulary_2026-11-10/terms_all.csv", "MODEL_JUDGEMENT (DeepSeek-V4.1-Flash, FhGenie)",
                      "canonical terms after dedup with relevance verdict (KEEP/UNSURE/NOT_A_CONCEPT/IRRELEVANT) and kept flag"),
    "concept_curation": (R / "clean_vocabulary_2026-11-10/concepts_all.csv", "MODEL_JUDGEMENT (DeepSeek-V4.1-Flash, FhGenie)",
                         "canonical concepts after dedup with relevance verdict and kept flag"),
    "term_concept_map_clean": (R / "clean_vocabulary_2026-11-10/term_concept_map_clean.csv", "DERIVED",
                               "accepted mappings remapped to canonical term and concept ids; dropped items removed"),
    "term_enrichment": (R / "enriched_terminology_2026-11-09/terms_enriched.csv.gz", "SOURCE_ + MODEL_ columns",
                        "one row per 3.0.3 term: extracted definitions and paper full forms (SOURCE_), contextual "
                        "definition, kind, full form, synonyms (MODEL_, Qwen3.5-4B)"),
    "mapping_enrichment": (R / "enriched_terminology_2026-11-09/mappings_enriched.csv.gz", "SOURCE_ + MODEL_ columns",
                           "one row per accepted mapping: ontology definition and synonyms (SOURCE_, BioPortal/OLS/UMLS/"
                           "NCBI), model description where the ontology has none (MODEL_)"),
    "triple_repair": (R / "triple_repair_2026-11-09/repaired.jsonl", "MODEL_JUDGEMENT (Qwen3.5-4B, schema-constrained)",
                      "one row per 3.0.3 triple: checked/specific relation or exit, direction, verified cue, endpoint fixes"),
    "triple_tier": (R / "triple_repair_2026-11-09/tiers.csv", "DETERMINISTIC",
                    "gates (cue found, anchored, domain-range, endpoints) and Tier 1/2/3 per triple"),
}


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def read_rows(p: Path):
    if p.suffix == ".jsonl":
        last = {}
        for line in open(p, encoding="utf-8"):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            last[r.get("canonical_triple_id") or len(last)] = r          # latest row per triple wins
        rows = list(last.values())
        cols = list(dict.fromkeys(k for r in rows for k in r))
        return cols, [[json.dumps(r.get(c), ensure_ascii=False) if isinstance(r.get(c), (list, dict)) else r.get(c)
                       for c in cols] for r in rows]
    opener = gzip.open if p.suffix == ".gz" else open
    with opener(p, "rt", encoding="utf-8", newline="") as f:
        rd = csv.reader((l.replace("\x00", "") for l in f))
        cols = next(rd)
        return cols, list(rd)


def main():
    if OUT.exists():
        raise SystemExit(f"{OUT} exists; refusing to overwrite a release")
    if sha(SRC_DB) != SRC_SHA:
        raise SystemExit("3.0.3 database checksum mismatch")
    for t, (p, _, _) in NEW.items():
        if not p.exists():
            raise SystemExit(f"missing source for {t}: {p}")
    stage = ROOT / "outputs/scratch" / f"cdm_310_staging_{os.getpid()}"
    stage.mkdir(parents=True)
    db = stage / DB_NAME
    shutil.copy2(SRC_DB, db)
    os.chmod(db, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
    con = sqlite3.connect(db)
    before = {t: con.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
              for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    srcinfo = {}
    for t, (p, prov, desc) in NEW.items():
        cols, rows = read_rows(p)
        con.execute(f'CREATE TABLE "{t}" (' + ", ".join(f'"{c}" TEXT' for c in cols) + ")")
        con.executemany(f'INSERT INTO "{t}" VALUES (' + ",".join("?" * len(cols)) + ")",
                        [r + [None] * (len(cols) - len(r)) if len(r) < len(cols) else r[:len(cols)] for r in rows])
        key = next((c for c in ("term_id", "canonical_triple_id", "concept_iri", "canonical_concept_id", "curie") if c in cols), None)
        if key:
            con.execute(f'CREATE INDEX "ix_{t}_{key}" ON "{t}"("{key}")')
        srcinfo[t] = {"source": str(p.relative_to(ROOT)), "sha256": sha(p), "rows": len(rows), "columns": cols,
                      "provenance": prov, "description": desc}
        con.execute("INSERT INTO cdm_change_log VALUES (?,?,?,?,?,?)",
                    ("310", "ADD_TABLE", t, f"{desc} [{prov}] from {p.relative_to(ROOT)}", len(rows), f'DROP TABLE "{t}";'))
    con.execute("CREATE TABLE release_provenance_310 (table_name TEXT, source TEXT, source_sha256 TEXT, rows INTEGER, "
                "provenance TEXT, description TEXT)")
    con.executemany("INSERT INTO release_provenance_310 VALUES (?,?,?,?,?,?)",
                    [(t, i["source"], i["sha256"], i["rows"], i["provenance"], i["description"]) for t, i in srcinfo.items()])
    for k, v in (("cdm_version", "3.1.0"), ("built_at", now), ("derived_from_310", f"releases/cdm_v3/3.0.3 (sha256 {SRC_SHA})"),
                 ("build_310", "src/scripts/cdm_release/build_310.py"),
                 ("status_310", "frozen 2026-11-10 on the first author's instruction; project-lead approval pending")):
        if con.execute("SELECT 1 FROM run_metadata WHERE key=?", (k,)).fetchone():
            con.execute("UPDATE run_metadata SET value=? WHERE key=?", (v, k))
        else:
            con.execute("INSERT INTO run_metadata VALUES (?,?)", (k, v))
    con.commit()
    # ---- verification
    after = {t: con.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
             for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    problems = []
    for t, n in before.items():
        expect = n + (len(NEW) if t == "cdm_change_log" else 0) + (3 if t == "run_metadata" else 0)
        if t not in ("cdm_change_log", "run_metadata") and after[t] != n:
            problems.append(f"{t}: {n} -> {after[t]}")
    for t, i in srcinfo.items():
        if after[t] != i["rows"]:
            problems.append(f"{t}: {after[t]} rows vs source {i['rows']}")
    if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        problems.append("integrity_check failed")
    con.execute("VACUUM")
    con.close()
    if problems:
        raise SystemExit("VERIFICATION FAILED: " + "; ".join(problems) + f" (staging kept at {stage})")
    # ---- release files
    OUT.mkdir(parents=True)
    shutil.move(str(db), OUT / DB_NAME)
    shutil.copy2(__file__, OUT / "build_310.py")
    (OUT / "sources").mkdir()
    json.dump(srcinfo, open(OUT / "sources/new_tables_310.json", "w"), indent=1)
    json.dump({"tables_3_0_3": before, "tables_3_1_0": after}, open(OUT / "sources/row_counts.json", "w"), indent=1)
    s = {t: i["rows"] for t, i in srcinfo.items()}
    (OUT / "README.md").write_text(f"""# Microbiome-CDM 3.1.0 (frozen {now[:10]})

**CDM 3.0.3 unchanged + the cleaned, enriched and repaired layers of 2026-11-09/10 as new tables.**
Status: frozen on the first author's instruction; **project-lead approval pending** (development freeze of 2026-11-02;
see paper/publication/final_validation/CHANGE_RECORD.md). 3.0.3 remains in releases/cdm_v3/3.0.3 and is still the
version cited by the manuscript and the claims register until they are switched.

- Database: `{DB_NAME}` (SQLite). All 44 tables of 3.0.3 with identical rows (run_metadata: version keys updated;
  cdm_change_log: one row per added table, step "310").
- New tables ({len(NEW)} + release_provenance_310), source files and checksums in `sources/new_tables_310.json`:
""" + "\n".join(f"  - `{t}` ({s[t]:,} rows) - {NEW[t][2]} [{NEW[t][1]}]" for t in NEW) + f"""

Key figures (new layers, not yet registered): terms 162,409 -> 157,815 after dedup -> 116,755 kept; accepted concepts
13,330 IRIs -> 12,657 CURIEs -> 12,182 after dedup -> 11,912 kept; accepted mappings 18,272 -> 15,769 clean rows;
triples 25,788 (unchanged) with checked relations: 8,307 specific with a verified cue, Tier 1/2/3 = 1,794 / 6,263 / 17,731.

Columns or tables marked MODEL are model-generated or model-judged (Qwen3.5-4B on local vLLM; DeepSeek-V4.1-Flash via
the Fraunhofer Genie gateway for the relevance screens) and are not curated. Contains paper-derived text: internal;
any public deposit must be rights-filtered like releases/zenodo_frozen.

Verify: `sha256sum -c MANIFEST.sha256`. Rebuild: `python3 build_310.py` (from the repo root, with 3.1.0 absent).
""", encoding="utf-8")
    (OUT / "CHANGES_310.md").write_text("# Changes 3.0.3 -> 3.1.0\n\n" + "\n".join(
        f"- ADD TABLE `{t}`: {i['rows']:,} rows from `{i['source']}` (sha256 {i['sha256'][:16]}...) [{i['provenance']}]"
        for t, i in srcinfo.items()) + "\n- ADD TABLE `release_provenance_310`.\n- run_metadata: cdm_version 3.1.0, built_at, "
        "derived_from_310, build_310, status_310.\n- No row of any 3.0.3 table removed or changed (row counts in sources/row_counts.json).\n",
        encoding="utf-8")
    files = sorted(p for p in OUT.rglob("*") if p.is_file())
    (OUT / "MANIFEST.sha256").write_text("".join(f"{sha(p)}  {p.relative_to(OUT)}\n" for p in files), encoding="utf-8")
    msha = sha(OUT / "MANIFEST.sha256")
    for p in list(OUT.rglob("*")) + [OUT]:
        p.chmod(p.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    with open(ROOT / "releases/RELEASES.md", "a", encoding="utf-8") as f:
        f.write(f"| {now[:10]} | cdm_v3 | 3.1.0 | build_310.py | {msha} | Claude Code (first author's instruction) | "
                f"3.0.3 + clean vocabulary, enrichment, triple repair/tiers as new tables; 3.0.3 rows unchanged; "
                f"project-lead approval pending; manuscript still cites 3.0.3 |\n")
    shutil.rmtree(stage, ignore_errors=True)
    print(json.dumps({"release": str(OUT.relative_to(ROOT)), "manifest_sha256": msha, "new_tables": s}, indent=1))


if __name__ == "__main__":
    main()
