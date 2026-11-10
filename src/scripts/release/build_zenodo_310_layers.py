"""Add the CDM 3.1.0 layers to a public deposit folder built by build_zenodo_frozen.py (run before verify / seal).

    python src/scripts/release/build_zenodo_310_layers.py --out releases/zenodo_r2_310

Reads the frozen CDM 3.1.0 (read-only) and writes cdm_310_layers/<table>.csv.gz for its 10 new tables, plus
cdm_310_layers/LAYER_REDACTION_LOG.csv and README_310_LAYERS.md. Same rights rules as the base build (alnum matching:
40 letters/digits, stride 5), plus:
  L1  model-generated fields (definition, full form, synonyms) flagged by
      outputs/results/rights/DEFINITIONS_RIGHTS_FLAGS_2026-11-10.csv (a 40-character span found only in withheld
      papers) are emptied; quoted paper definitions (SOURCE_extracted_definitions) and paper full forms are emptied
      when they come from a paper whose text is withheld;
  L2  ontology labels, definitions and synonyms of vocabularies not on VOCABULARY_LABEL_ALLOWLIST.csv are emptied
      (B23); identifiers are kept;
  L3  triple cues (verbatim fragments of the evidence sentence) are kept only when every source paper is text-included;
  R4  any other value containing a withheld window that occurs in no text-included paper is emptied.
The frozen 3.1.0 database is not changed. Written with Claude Code (declare).
"""
from __future__ import annotations

import csv
import gzip
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_zenodo_frozen as Z  # noqa: E402

DB = ROOT / "releases/cdm_v3/3.1.0/microbiome_cdm_v3.1.0.db"
FLAGS = ROOT / "outputs/results/rights/DEFINITIONS_RIGHTS_FLAGS_2026-11-10.csv"
TABLES = ["term_dedup_map", "concept_curie_map", "term_curation", "concept_curation", "term_concept_map_clean",
          "term_enrichment", "mapping_enrichment", "triple_repair", "triple_tier", "release_provenance_310"]
log = Counter()


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = ROOT / a.out
    if not (out / "rights/PAPER_LICENCES.csv").exists():
        sys.exit(f"{out} is not a base build (run build_zenodo_frozen.py + finalize first)")
    lay = out / "cdm_310_layers"
    if lay.exists():
        sys.exit(f"{lay} exists; refusing to overwrite")
    lay.mkdir()
    Z.MODE, (Z.W, Z.STRIDE) = "alnum", Z.MATCH["alnum"]
    rights = {r["paper_id"]: r["proposed_release_decision"] for r in csv.DictReader(open(Z.RIGHTS, encoding="utf-8"))}
    withheld = {p for p, d in rights.items() if d != "INCLUDE_TEXT"}
    src = sqlite3.connect(f"file:{Z.CDM / 'microbiome_cdm_v3.db'}?mode=ro", uri=True)
    text = {}
    for pid, t in src.execute("SELECT paper_id, section_text_original FROM section"):
        text[pid] = text.get(pid, "") + Z.key(t)
    rules = Z.Rules(text, withheld)
    print(f"indexed {len(rules.index):,} withheld windows", flush=True)

    flags = {r["term_id"]: r for r in csv.DictReader(open(FLAGS, encoding="utf-8"))}
    allow = {r["vocabulary"].upper() for r in csv.DictReader(open(Z.ALLOWLIST, encoding="utf-8"))}
    omop = sqlite3.connect(f"file:{Z.OMOP_INDEX}?mode=ro", uri=True) if Z.OMOP_INDEX.exists() else None
    vcache = {}

    def vocab_ok(cid, service="", ontology=""):
        k = (cid, service)
        if k not in vcache:
            v = Z.vocabulary_of(cid, service)
            if v == "OMOP":
                ov = omop.execute("SELECT vocabulary_id FROM concept WHERE concept_id=?", (int(cid),)).fetchone() if omop else None
                v = Z.OMOP_VOCAB.get(ov[0], "OMOP:" + ov[0]) if ov else "OMOP:UNKNOWN"
            if v == "OTHER" and ontology:
                v = ontology.upper()
            vcache[k] = v in allow
        return vcache[k]

    def blank(t, col, rule):
        log[(t, col, rule)] += 1
        return ""

    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    for t in TABLES:
        cur = c.execute(f'SELECT * FROM "{t}"')
        cols = [d[0] for d in cur.description]
        n = 0
        with gzip.open(lay / f"{t}.csv.gz", "wt", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            for r in cur:
                r = {k: ("" if r[k] is None else r[k]) for k in cols}
                f = flags.get(r.get("term_id", ""))
                # L1 definitions layer
                if t in ("term_enrichment", "term_curation") and f:
                    for col, fk in (("MODEL_definition", "model_definition_withheld_span"), ("definition", "model_definition_withheld_span"),
                                    ("MODEL_full_form", "model_full_form_withheld_span"), ("full_form", "model_full_form_withheld_span"),
                                    ("MODEL_synonyms", "model_synonyms_withheld_span"), ("synonyms", "model_synonyms_withheld_span"),
                                    ("SOURCE_extracted_definitions", "source_definitions_from_non_open_paper")):
                        if col in r and r[col] and f[fk] == "1":
                            r[col] = blank(t, col, "L1_DEFINITIONS_FLAG")
                if t == "term_enrichment" and r["SOURCE_paper_full_form"] and r["SOURCE_paper_full_form_paper"] in withheld:
                    r["SOURCE_paper_full_form"] = blank(t, "SOURCE_paper_full_form", "L1_WITHHELD_PAPER")
                # L2 vocabularies
                if t == "concept_curation" and not vocab_ok(r["concept_id"], "", r["ontology"]):
                    for col in ("label", "definition", "synonyms"):
                        if r[col]:
                            r[col] = blank(t, col, "L2_B23_VOCAB")
                if t == "mapping_enrichment" and not vocab_ok(r["concept_id"], r["ontology_service"]):
                    for col in ("concept_label", "SOURCE_ontology_definition", "SOURCE_ontology_synonyms"):
                        if r[col]:
                            r[col] = blank(t, col, "L2_B23_VOCAB")
                    if r["concept_definition_final_origin"] == "ONTOLOGY" and r["concept_definition_final"]:
                        r["concept_definition_final"] = blank(t, "concept_definition_final", "L2_B23_VOCAB")
                if t == "term_enrichment" and r["accepted_concepts"]:
                    items = []
                    for it in r["accepted_concepts"].split("; "):
                        m = re.fullmatch(r"(.*) \(([^()]+)\)", it)
                        if not m:
                            items = None
                            break
                        items.append(it if vocab_ok(m.group(2)) else f"({m.group(2)})")
                    new = "; ".join(items) if items is not None else ""
                    if new != r["accepted_concepts"]:
                        log[(t, "accepted_concepts", "L2_B23_VOCAB_LABELS")] += 1
                        r["accepted_concepts"] = new
                # L3 triple cues
                if t == "triple_repair" and r["cue"]:
                    pids = json.loads(r["paper_ids"] or "[]")
                    if not pids or any(p in withheld for p in pids):
                        r["cue"] = blank(t, "cue", "L3_CUE_WITHHELD_PAPER")
                # R4 generic verbatim scan
                for col in cols:
                    v = r[col]
                    if isinstance(v, str) and v and rules.leaks(v, None):
                        r[col] = blank(t, col, "R4_VERBATIM")
                w.writerow(r)
                n += 1
        print(f"{t}: {n:,} rows", flush=True)
        log[(t, "*", "ROWS")] = n
    with open(lay / "LAYER_REDACTION_LOG.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["table", "column", "rule", "values_emptied_or_rows"])
        for (t, col, rule), n in sorted(log.items()):
            w.writerow([t, col, rule, n])
    print(json.dumps({f"{t}|{c_}|{r_}": n for (t, c_, r_), n in sorted(log.items())}, indent=1))


if __name__ == "__main__":
    main()
