"""Build releases/zenodo_frozen: the public deposit, derived from the frozen releases (never modified).

Rights rules (proposed policy, pending the legal/library review of 179 papers). "Withheld" = papers whose
proposed_release_decision is not INCLUDE_TEXT (i.e. not CC BY / CC0). A "window" is any 50-character run of a
withheld paper's whitespace-normalised text; values are probed every 10 characters (so any verbatim run of >= 59
characters is caught).
  R1  text-bearing columns (section text, abstract, quotes, evidence spans, sentences, definition passages) are
      emptied for withheld papers; in gap_evidence JSON the `quote` and `conflict` entries are removed;
  R2  any other text value of a withheld paper containing a withheld window is emptied;
  R3  a value of a text-included paper containing a withheld window that is NOT in its own paper's text is emptied;
  R4  a value without a paper (terms, mappings, triple labels, …) containing a withheld window that occurs in no
      text-included paper is emptied.
  Exempt (not paper text): bibliographic metadata (title, authors, journal, doi), ontology concept labels,
  compendium (SRA-derived) tables.
Matching modes (--match): "ws" (default; the frozen deposit) compares whitespace-normalised 50-character windows,
probed every 10 characters. "alnum" compares windows of 40 letters/digits after lower-casing and removing everything
else (spaces, punctuation, hyphens, arrows), probed every 5; it also catches copies that differ from the paper only in
punctuation, hyphenation or line breaks (1,308 such strings were found in the frozen deposit on 2026-11-05).
Vocabulary labels (--vocab-labels): "all" (default; the frozen deposit) ships every concept label. "allowlist" blanks
the concept_label of every concept whose vocabulary is not in VOCABULARY_LABEL_ALLOWLIST.csv (UMLS, SNOMED CT, MedDRA,
OMIM, Read codes, NDDF, ... and every OMOP concept whose vocabulary_id is not listed); identifiers are always kept.
The list holds vocabularies whose providers publish an open licence; entries are PROPOSED until the rights reviewer
confirms them (blocker B23).
Identifiers, offsets, hashes and short values are kept. Every emptied value is counted in RELEASE_REDACTION_LOG.csv;
verify_zenodo_frozen.py re-checks the result independently.

    python build_zenodo_frozen.py            # refuses to overwrite an existing build
    python build_zenodo_frozen.py --out releases/zenodo_r2 --match alnum
"""
from __future__ import annotations

import ast
import csv
import gzip
import io
import json
import re
import shutil
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
REL = ROOT / "releases"
OUT = REL / "zenodo_frozen"
CDM = REL / "cdm_v3/3.0.3"
CAT = REL / "data_catalogue_v3/3.1.1"
TERM = REL / "terminology/1.0.1"
MD = REL / "frozen_output/01_corpus/segmented_sections_markdown"
RIGHTS = ROOT / "paper/publication/rights/PAPER_RIGHTS_MATRIX.csv"
FV = ROOT / "paper/publication/final_validation"
W, STRIDE = 50, 10
MATCH = {"ws": (50, 10), "alnum": (40, 5)}
MODE = "ws"
ALLOWLIST = Path(__file__).resolve().parent / "VOCABULARY_LABEL_ALLOWLIST.csv"
OMOP_INDEX = ROOT / "outputs/results/omop_vocab/omop_index.sqlite"
OMOP_VOCAB = {"MeSH": "MESH", "NCIt": "NCIT", "Mondo": "MONDO", "HPO": "HP"}   # OMOP vocabulary_id -> allow-list key
csv.field_size_limit(sys.maxsize)

TEXT_COLS = {"section_text_original", "abstract", "evidence_text", "evidence_span", "supporting_sentence",
             "supporting_sentence_clipped", "source_sentence", "definition_text"}
EXEMPT_COLS = {"title", "authors", "journal", "doi", "concept_label", "standard_concept_label"}
EXEMPT_TABLES = {"compendium_project", "compendium_sample", "compendium_sample_tag", "concept", "release_rights"}
log = Counter()


def ws(s):
    return re.sub(r"\s+", " ", s or "").strip()


def key(s):
    """Normalisation used for matching: whitespace only ("ws") or letters/digits only, lower case ("alnum")."""
    return ws(s) if MODE == "ws" else re.sub(r"[^0-9a-z]", "", (s or "").lower())


class Rules:
    def __init__(self, text, withheld):
        self.text, self.withheld = text, withheld
        self.index = set()
        for p in withheld:
            t = text.get(p, "")
            self.index.update(hash(t[i:i + W]) for i in range(0, max(0, len(t) - W + 1)))
        self.included_text = " ".join(t for p, t in text.items() if p not in withheld)

    def leaks(self, v, pid):
        """True if value v (of paper pid, or None) must be emptied under R2-R4."""
        if not isinstance(v, str) or len(v) < W:
            return False
        v = key(v)
        hit = [v[i:i + W] for i in range(0, len(v) - W + 1, STRIDE) if hash(v[i:i + W]) in self.index]
        if not hit:
            return False
        if pid in self.withheld:
            return True                                                    # R2
        if pid:
            return not all(h in self.text.get(pid, "") for h in hit)       # R3
        return not all(h in self.included_text for h in hit)               # R4


def vocabulary_of(concept_id: str, service: str | None) -> str:
    """Vocabulary key of a CDM concept (upper case), from its identifier form. OMOP ids return 'OMOP' (resolved later)."""
    cid, svc = concept_id or "", (service or "").lower()
    if re.fullmatch(r"C\d{7}", cid):
        return "UMLS"
    if cid.startswith("NCBITaxon:"):
        return "NCBITAXON"
    if svc == "omop" and cid.isdigit():
        return "OMOP"
    for pat in (r"purl\.bioontology\.org/ontology/([A-Za-z0-9_\-]+)/", r"purl\.obolibrary\.org/obo/([A-Za-z]+)_"):
        m = re.search(pat, cid)
        if m:
            return m.group(1).upper()
    if "id.nlm.nih.gov/mesh/" in cid or (svc == "mesh" and re.fullmatch(r"[CDQ]\d+", cid)):
        return "MESH"
    if "Thesaurus.owl#" in cid:
        return "NCIT"
    if "snomed.info/" in cid:
        return "SNOMEDCT"
    return "OTHER"


def restrict_vocab_labels(c):
    """Blank concept labels of vocabularies not on the allow-list (B23). Returns counts per vocabulary."""
    allow = {r["vocabulary"].upper() for r in csv.DictReader(open(ALLOWLIST, encoding="utf-8"))}
    rows = c.execute("SELECT rowid, concept_id, source_service FROM concept WHERE concept_label IS NOT NULL AND concept_label != ''").fetchall()
    voc = {rid: vocabulary_of(cid, svc) for rid, cid, svc in rows}
    omop_ids = [int(cid) for rid, cid, svc in rows if voc[rid] == "OMOP"]
    omop_vocab = {}
    if omop_ids:
        o = sqlite3.connect(f"file:{OMOP_INDEX}?mode=ro", uri=True)
        for i in range(0, len(omop_ids), 900):
            chunk = omop_ids[i:i + 900]
            for cid, v in o.execute(f"SELECT concept_id, vocabulary_id FROM concept WHERE concept_id IN ({','.join('?' * len(chunk))})", chunk):
                omop_vocab[cid] = v
        o.close()
    kept, blanked = Counter(), Counter()
    for rid, cid, svc in rows:
        v = voc[rid]
        if v == "OMOP":
            ov = omop_vocab.get(int(cid), "UNKNOWN")
            v = OMOP_VOCAB.get(ov, "OMOP:" + ov)
        if v in allow:
            kept[v] += 1
        else:
            c.execute("UPDATE concept SET concept_label = NULL WHERE rowid = ?", (rid,))
            blanked[v] += 1
    for v, n in blanked.items():
        log[("concept", "concept_label", f"B23_VOCAB_NOT_ALLOWLISTED:{v}")] += n
    print(f"  concept labels: kept {sum(kept.values()):,} {dict(kept.most_common())}; blanked {sum(blanked.values()):,}", flush=True)
    return kept, blanked


def clean_gap_evidence(v):
    try:
        g = json.loads(v)
    except ValueError:
        g = ast.literal_eval(v)
    if isinstance(g, dict):
        for e in g.values():
            if isinstance(e, dict):
                e.pop("quote", None)
                e.pop("conflict", None)
    return json.dumps(g, ensure_ascii=False)


def redact_record(rec, rules, where, pid, skip=()):
    """Apply R1-R4 to a flat dict in place (catalogue CSV row / JSONL record). Returns rec."""
    for k, v in list(rec.items()):
        if k in skip or k in EXEMPT_COLS or k == "paper_id" or v in (None, ""):
            continue
        if isinstance(v, dict):      # nested fields are checked one by one, as the verifier walks them
            redact_record(v, rules, f"{where}.{k}", pid)
            continue
        if isinstance(v, list):
            for i, x in enumerate(v):
                if isinstance(x, dict):
                    redact_record(x, rules, f"{where}.{k}", pid)
                elif rules.leaks(x, pid):
                    v[i] = None
                    log[(where, k, "R2-R4_VERBATIM")] += 1
            continue
        if not isinstance(v, str):
            continue
        if pid in rules.withheld and k in TEXT_COLS:
            rec[k] = None
            log[(where, k, "R1_TEXT_COLUMN")] += 1
        elif pid in rules.withheld and k == "gap_evidence":
            rec[k] = clean_gap_evidence(v)
            log[(where, k, "R1_QUOTES_REMOVED")] += 1
            if rules.leaks(rec[k], pid):
                rec[k] = None
                log[(where, k, "R2-R4_VERBATIM")] += 1
        elif rules.leaks(v, pid):
            rec[k] = None
            log[(where, k, "R2-R4_VERBATIM")] += 1
    return rec


def main():
    global OUT, W, STRIDE, MODE
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", help="output folder: relative to the repository root, or absolute (default releases/zenodo_frozen)")
    ap.add_argument("--match", choices=sorted(MATCH), default="ws")
    ap.add_argument("--vocab-labels", choices=["all", "allowlist"], default="all")
    a = ap.parse_args()
    if a.out:
        OUT = ROOT / a.out
    MODE = a.match
    W, STRIDE = MATCH[MODE]
    print(f"output {OUT}; matching {MODE}: window {W}, stride {STRIDE}", flush=True)
    if OUT.exists():
        sys.exit(f"{OUT} exists; refusing to overwrite")
    rights = {r["paper_id"]: r for r in csv.DictReader(open(RIGHTS, encoding="utf-8"))}
    withheld = {p for p, r in rights.items() if r["proposed_release_decision"] != "INCLUDE_TEXT"}
    print(f"papers {len(rights)}; text shipped {len(rights) - len(withheld)}; withheld {len(withheld)}", flush=True)
    for d in ("cdm", "catalogue", "terminology", "corpus/markdown", "rights", "validation"):
        (OUT / d).mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(f"file:{CDM / 'microbiome_cdm_v3.db'}?mode=ro", uri=True)
    text = {}
    for pid, t in src.execute("SELECT paper_id, section_text_original FROM section"):
        text[pid] = text.get(pid, "") + (" " if MODE == "ws" else "") + key(t)
    rules = Rules(text, withheld)
    print(f"indexed {len(rules.index):,} withheld windows", flush=True)

    # ---------- CDM ----------
    db = OUT / "cdm/microbiome_cdm_v3.0.3_public.db"
    shutil.copy2(CDM / "microbiome_cdm_v3.db", db)
    db.chmod(0o644)
    c = sqlite3.connect(db)
    wh = sorted(withheld)
    qm = ",".join("?" * len(wh))
    for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
        if t in EXEMPT_TABLES:
            continue
        cols = [(r[1], (r[2] or "").upper()) for r in c.execute(f'PRAGMA table_info("{t}")')]
        has_pid = "paper_id" in [n for n, _ in cols]
        tcols = [n for n, ty in cols if ty in ("TEXT", "") and n != "paper_id" and n not in EXEMPT_COLS]
        if t == "type_harmonization":
            log[(t, "context", "R4_ALL_ROWS_NO_PAPER_ID")] += c.execute(
                "UPDATE type_harmonization SET context=NULL WHERE context IS NOT NULL").rowcount
            tcols = [x for x in tcols if x != "context"]
        if not tcols:
            continue
        if has_pid:
            for col in [x for x in tcols if x in TEXT_COLS | {"gap_evidence"}]:
                log[(t, col, "R1_TEXT_COLUMN")] += c.execute(
                    f'UPDATE "{t}" SET "{col}"=NULL WHERE paper_id IN ({qm}) AND "{col}" IS NOT NULL', wh).rowcount
        cond = " OR ".join(f'length("{x}") >= {W}' for x in tcols)
        sel = ", ".join(f'"{x}"' for x in tcols)
        upd = []
        for row in c.execute(f'SELECT rowid, {"paper_id" if has_pid else "NULL"}, {sel} FROM "{t}" WHERE {cond}'):
            for x, v in zip(tcols, row[2:]):
                if rules.leaks(v, row[1]):
                    upd.append((x, row[0]))
        for x, rid in upd:
            c.execute(f'UPDATE "{t}" SET "{x}"=NULL WHERE rowid=?', (rid,))
            log[(t, x, "R2-R4_VERBATIM")] += 1
        print(f"  {t}: {len(upd)} values emptied by R2-R4", flush=True)
    if a.vocab_labels == "allowlist":
        restrict_vocab_labels(c)
        shutil.copy2(ALLOWLIST, OUT / "rights" / ALLOWLIST.name)
    c.execute("CREATE TABLE release_rights (paper_id TEXT PRIMARY KEY, licence TEXT, text_layer TEXT)")
    c.executemany("INSERT INTO release_rights VALUES (?,?,?)",
                  [(p, r["licence"], "TEXT_INCLUDED" if p not in withheld else "TEXT_WITHHELD_PENDING_RIGHTS_REVIEW")
                   for p, r in sorted(rights.items())])
    c.commit()

    # ---------- catalogue tables ----------
    for f in sorted((CAT / "tables").glob("*.csv")):
        rows = list(csv.DictReader(io.StringIO(open(f, encoding="utf-8").read().replace("\0", ""))))
        for r in rows:
            redact_record(r, rules, f"catalogue/{f.name}", r.get("paper_id"))
            if r.get("paper_id") in withheld and "evidence_redacted" in r and not r["evidence_redacted"]:
                r["evidence_redacted"] = "LICENCE"
        with open(OUT / "catalogue" / f.name, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)

    # ---------- terminology ----------
    for name in ("canonical_terms.jsonl", "term_ontology_mappings.jsonl", "term_definitions.jsonl"):
        with open(TERM / name, encoding="utf-8") as fi, open(OUT / "terminology" / name, "w", encoding="utf-8") as fo:
            for line in fi:
                d = json.loads(line)
                fo.write(json.dumps(redact_record(d, rules, f"terminology/{name}", d.get("paper_id")),
                                    ensure_ascii=False) + "\n")
    for name in ("README.md", "ontology_registry.json", "terminology_taxonomy.json", "canonical_terms_summary.json"):
        shutil.copy2(TERM / name, OUT / "terminology" / name)

    # ---------- corpus ----------
    with gzip.open(OUT / "corpus/sections.jsonl.gz", "wt", encoding="utf-8") as fo:
        for r in src.execute("SELECT section_record_id, paper_id, section_id_original, section_name_original, "
                             "section_name_normalized, section_type, section_order, character_count, word_count, "
                             "text_hash_sha256, section_text_original FROM section ORDER BY paper_id, section_order"):
            d = dict(zip(("section_record_id", "paper_id", "section_id", "section_name", "section_name_normalized",
                          "section_type", "section_order", "character_count", "word_count", "text_sha256", "text"), r))
            if d["paper_id"] in withheld:
                d["text"] = None
            fo.write(json.dumps(d, ensure_ascii=False) + "\n")
    src.close()
    for p in sorted(set(rights) - withheld):
        if (MD / f"{p}.md").exists():
            shutil.copy2(MD / f"{p}.md", OUT / "corpus/markdown" / f"{p}.md")

    # ---------- rights, docs, validation, logs ----------
    with open(OUT / "rights/PAPER_LICENCES.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["paper_id", "bioproject", "doi", "journal", "licence", "licence_url", "text_layer"])
        for p, r in sorted(rights.items()):
            w.writerow([p, r["bioproject"], r["doi"], r["journal"], r["licence"], r["licence_url"],
                        "TEXT_INCLUDED" if p not in withheld else "TEXT_WITHHELD_PENDING_RIGHTS_REVIEW"])
    dic = list(csv.DictReader(open(CDM / "remediation/CDM_COLUMN_DICTIONARY.csv", encoding="utf-8")))
    for r in dic:
        redact_record(r, rules, "cdm/CDM_COLUMN_DICTIONARY.csv", None)
    with open(OUT / "cdm/CDM_COLUMN_DICTIONARY.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(dic[0]))
        w.writeheader()
        w.writerows(dic)
    shutil.copy2(CDM / "remediation/VOCABULARY_REFERENCE.md", OUT / "cdm/VOCABULARY_REFERENCE.md")
    for f in (FV / "MASTER_VALIDATION_REPORT.md", FV / "BENCHMARK_FINAL_ANALYSIS.md",
              ROOT / "outputs/results/benchmark/ner_fair_bench/FAIR_NER_BENCHMARK.md",
              ROOT / "outputs/results/benchmark/ner_corpus_bench/CORPUS_NER_BENCHMARK.md"):
        shutil.copy2(f, OUT / "validation" / f.name)
    rows = [(*k, v) for k, v in sorted(log.items())]
    c.execute("CREATE TABLE release_redaction (table_or_file TEXT, column_name TEXT, rule TEXT, values_emptied INTEGER)")
    c.executemany("INSERT INTO release_redaction VALUES (?,?,?,?)", rows)
    c.commit()
    c.execute("VACUUM")
    c.close()
    with open(OUT / "RELEASE_REDACTION_LOG.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["table_or_file", "column", "rule", "values_emptied"])
        w.writerows(rows)
    print("values emptied:", sum(log.values()))


if __name__ == "__main__":
    main()
