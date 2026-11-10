#!/usr/bin/env python3
"""
audit_cdm.py - diagnostic audit of the Microbiome CDM SQLite database.

Read-only. Introspects the schema first, then runs whatever checks the
schema supports. Prints a human-readable report and (with --json) dumps a
machine-readable blob.

Usage:
    python -m cdm_pipeline.audit.audit_cdm --db paper/_multi_ner_runs/cdm_output/microbiome_cdm.db
    python -m cdm_pipeline.audit.audit_cdm --db <path> --papers papers_txt --json audit.json

Checks:
  S1  schema inventory
  E1  entity type distribution
  E2  junk / degenerate surface forms
  E3  document-frequency distribution (is the DF cutoff right?)
  E4  duplicate entities (same normalized string, same canonical id)
  E5  cross-model type disagreement
  M1  mapping coverage AND type-appropriateness crosstab
  M2  CURIE / vocabulary-prefix hygiene
  M3  ORGANISM -> NCBITaxon coverage (gates the compendium join)
  R1  relationship type distribution
  R2  referential integrity, self-loops, duplicate/reciprocal edges
  R3  significance columns: how many edges survive q<0.05
  R4  confidence distribution per edge type
  R5  provenance completeness
  P1  mention offset spot-check against papers_txt
  X1  per-model unique contribution (Claim C honesty check)
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict

# ---------------------------------------------------------------- utilities

RESULTS: dict = {}
FINDINGS: list = []


def flag(severity: str, code: str, msg: str) -> None:
    """Record a finding. severity in {INFO, WARN, ERROR}."""
    FINDINGS.append({"severity": severity, "check": code, "message": msg})
    prefix = {"INFO": "  .", "WARN": "  !", "ERROR": "  X"}[severity]
    print(f"{prefix} [{code}] {msg}")


def header(title: str) -> None:
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")


def tables(con) -> list[str]:
    return [
        r[0]
        for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    ]


def columns(con, table: str) -> list[str]:
    try:
        return [r[1] for r in con.execute(f'PRAGMA table_info("{table}")').fetchall()]
    except sqlite3.Error:
        return []


def pick(cands: list[str], available: list[str]) -> str | None:
    """First candidate column name that exists (case-insensitive)."""
    lower = {c.lower(): c for c in available}
    for c in cands:
        if c.lower() in lower:
            return lower[c.lower()]
    return None


def count(con, table: str, where: str = "") -> int:
    sql = f'SELECT COUNT(*) FROM "{table}"'
    if where:
        sql += f" WHERE {where}"
    try:
        return con.execute(sql).fetchone()[0]
    except sqlite3.Error as e:
        flag("WARN", "SQL", f"{sql[:60]}... failed: {e}")
        return -1


def pct(n: int, d: int) -> str:
    return f"{100.0 * n / d:.1f}%" if d else "n/a"


# ---------------------------------------------------------------- S1 schema

def check_schema(con) -> dict:
    header("S1  Schema inventory")
    schema = {}
    for t in sorted(tables(con)):
        cols = columns(con, t)
        n = count(con, t)
        schema[t] = {"rows": n, "columns": cols}
        print(f"  {t:<28} {n:>10,} rows  ({len(cols)} cols)")
        print(f"       {', '.join(cols)}")
    RESULTS["schema"] = schema
    return schema


# ---------------------------------------------------------------- entities

JUNK_PATTERNS = [
    (r"^\W+$", "punctuation only"),
    (r"^\d+$", "digits only"),
    (r"^.$", "single character"),
    (r"^(the|and|of|in|for|with|from|study|studies|patient|patients|sample|"
     r"samples|data|result|results|method|methods|analysis|group|groups|"
     r"level|levels|effect|effects|control|controls)$", "stopword-like"),
    (r"^\s|\s$", "leading/trailing whitespace"),
    (r"[\x00-\x1f]", "control characters"),
    (r"^(fig|figure|table|supplementary|et al)\b", "document furniture"),
]


def check_entities(con, schema) -> None:
    if "entities" not in schema:
        flag("ERROR", "E0", "no 'entities' table found - skipping entity checks")
        return
    cols = schema["entities"]["columns"]
    c_term = pick(["term", "name", "canonical_name", "entity", "label"], cols)
    c_type = pick(["entity_type", "cdm_type", "type"], cols)
    c_papers = pick(["paper_count", "n_papers", "doc_count", "document_count"], cols)
    c_id = pick(["entity_id", "id", "rowid"], cols)

    if not c_term:
        flag("ERROR", "E0", "cannot identify a term column in 'entities'")
        return

    total = schema["entities"]["rows"]

    # E1 type distribution
    header("E1  Entity type distribution")
    if c_type:
        rows = con.execute(
            f'SELECT "{c_type}", COUNT(*) FROM entities GROUP BY 1 ORDER BY 2 DESC'
        ).fetchall()
        RESULTS["entity_types"] = {str(k): v for k, v in rows}
        for k, v in rows:
            print(f"  {str(k):<24} {v:>8,}  {pct(v, total)}")
        if len(rows) > 20:
            flag("WARN", "E1", f"{len(rows)} distinct types - CDM_TYPES defines 14")
        nulls = count(con, "entities", f'"{c_type}" IS NULL OR "{c_type}"=""')
        if nulls:
            flag("WARN", "E1", f"{nulls:,} entities have no type ({pct(nulls, total)})")
    else:
        flag("WARN", "E1", "no entity_type column found")

    # E2 junk surface forms
    header("E2  Degenerate surface forms")
    terms = [
        (r[0], r[1] if len(r) > 1 else None)
        for r in con.execute(
            f'SELECT "{c_term}"' + (f', "{c_id}"' if c_id else "") + " FROM entities"
        ).fetchall()
    ]
    junk = defaultdict(list)
    for term, eid in terms:
        if term is None:
            junk["null term"].append(eid)
            continue
        s = str(term)
        for pat, name in JUNK_PATTERNS:
            if re.search(pat, s, flags=re.I):
                junk[name].append(s)
                break
        else:
            if len(s) > 100:
                junk["over 100 chars"].append(s[:60] + "...")
    RESULTS["junk_entities"] = {k: len(v) for k, v in junk.items()}
    if junk:
        for name, items in sorted(junk.items(), key=lambda kv: -len(kv[1])):
            sev = "ERROR" if len(items) > total * 0.01 else "WARN"
            sample = ", ".join(repr(str(x)) for x in items[:5])
            flag(sev, "E2", f"{len(items):,} {name}: {sample}")
    else:
        print("  clean")

    # E3 document-frequency distribution
    header("E3  Document-frequency distribution")
    if c_papers:
        dfs = [
            r[0]
            for r in con.execute(
                f'SELECT "{c_papers}" FROM entities WHERE "{c_papers}" IS NOT NULL'
            ).fetchall()
        ]
        if dfs:
            dfs.sort(reverse=True)
            n_docs = max(dfs)
            print(f"  max DF = {n_docs}  median = {statistics.median(dfs)}")
            for thresh in (0.5, 0.4, 0.3, 0.2, 0.1, 0.05):
                cut = thresh * n_docs
                n = sum(1 for d in dfs if d >= cut)
                print(f"  DF >= {thresh:.0%} of corpus ({cut:.0f} docs): {n:,} entities")
            RESULTS["df_percentiles"] = {
                f"p{p}": dfs[int(len(dfs) * (1 - p / 100))] for p in (50, 90, 99)
            }
            top = con.execute(
                f'SELECT "{c_term}", "{c_papers}" FROM entities '
                f'ORDER BY "{c_papers}" DESC LIMIT 25'
            ).fetchall()
            print("\n  Top 25 by document frequency (eyeball these):")
            for t, d in top:
                print(f"    {d:>5}  {t}")
            flag(
                "INFO",
                "E3",
                "if the top-25 list is dominated by generic terms, the DF cutoff "
                "is too permissive",
            )
    else:
        flag("WARN", "E3", "no paper_count column - cannot assess the DF cutoff")

    # E4 duplicates
    header("E4  Duplicate entities")
    norm = lambda s: re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()
    by_norm = defaultdict(list)
    for term, eid in terms:
        if term is not None:
            by_norm[norm(term)].append(term)
    dupes = {k: v for k, v in by_norm.items() if len(v) > 1}
    RESULTS["duplicate_normalized_terms"] = len(dupes)
    if dupes:
        flag(
            "WARN",
            "E4",
            f"{len(dupes):,} normalized strings map to >1 entity row "
            f"(dedup did not fully converge)",
        )
        for k, v in list(sorted(dupes.items(), key=lambda kv: -len(kv[1])))[:8]:
            print(f"    {len(v):>3}x  {v[:4]}")
    else:
        print("  no normalized-string collisions")

    # E5 cross-model type disagreement
    header("E5  Cross-model NER agreement")
    ner_cols = [c for c in cols if c.lower().startswith("ner_")]
    if ner_cols and c_type:
        print(f"  NER source columns: {', '.join(ner_cols)}")
        sums = con.execute(
            "SELECT " + ", ".join(f'SUM("{c}")' for c in ner_cols) + " FROM entities"
        ).fetchone()
        for c, s in zip(ner_cols, sums):
            print(f"  {c:<20} {int(s or 0):>8,}  {pct(int(s or 0), total)}")
        # entities found by exactly one model = unique contribution
        expr = " + ".join(f'COALESCE("{c}",0)' for c in ner_cols)
        for c in ner_cols:
            n = count(con, "entities", f'{expr} = 1 AND COALESCE("{c}",0) = 1')
            print(f"  unique to {c:<18} {n:>8,}  {pct(n, total)}")
            RESULTS.setdefault("unique_contribution", {})[c] = n
        n_multi = count(con, "entities", f"{expr} >= 2")
        n_one = count(con, "entities", f"{expr} = 1")
        flag(
            "INFO",
            "E5",
            f"{n_one:,} entities ({pct(n_one, total)}) found by exactly one model; "
            f"{n_multi:,} by two or more. Single-model entities are your "
            f"precision risk and your Claim B population.",
        )
    else:
        flag("WARN", "E5", "no ner_* boolean columns found")


# ---------------------------------------------------------------- mappings

TYPE_APPROPRIATE = {
    "ORGANISM":        {"NCBITAXON", "GTDB", "SNOMEDCT", "MESH", "NCIT", "UMLS"},
    "CHEMICAL":        {"CHEBI", "MESH", "RXNORM", "SNOMEDCT", "NCIT", "UMLS"},
    "DISEASE":         {"MONDO", "DOID", "SNOMEDCT", "ICD9CM", "ICD10", "OMIM",
                        "MESH", "HP", "UMLS"},
    "PATHWAY":         {"REACTOME", "GO", "WIKIPATHWAYS", "CHEBI", "UMLS"},
    "PROTEIN":         {"PR", "GO", "CHEBI", "MESH", "HGNC", "NCBITAXON", "UMLS"},
    "DNA_RNA":         {"SO", "SEQUENCE", "GENEPIO", "MESH", "NCIT", "UMLS"},
    "CELL_TYPE":       {"CL", "CLO", "MESH", "NCIT", "UMLS"},
    "SAMPLE_METHOD":   {"OBI", "NCIT", "MESH", "UMLS"},
    "LAB_METHOD":      {"OBI", "NCIT", "ERO", "MESH", "UMLS"},
    "DATA_ANALYSIS":   {"STATO", "OBI", "EDAM", "NCIT", "UMLS"},
    "EXPERIMENTAL_METHOD": {"OBI", "ERO", "NCIT", "UMLS"},
    "STUDY_DESIGN":    {"OBI", "SNOMEDCT", "NCIT", "UMLS"},
    "GENOMICS":        {"OBI", "SO", "NCIT", "MESH", "UMLS"},
    "CLINICAL":        {"SNOMEDCT", "NCIT", "LOINC", "MESH", "UMLS"},
}
SUSPECT_FOR_MICROBIOME = {"LOINC", "LNC", "CPT4", "HCPCS", "NDC"}


def check_mappings(con, schema) -> None:
    tname = None
    for cand in ("controlled_vocabularies", "cv_mappings", "mappings", "entity_mappings"):
        if cand in schema:
            tname = cand
            break
    if not tname:
        flag("ERROR", "M0", "no controlled-vocabulary mapping table found")
        return

    cols = schema[tname]["columns"]
    c_vocab = pick(["vocabulary_name", "vocabulary", "vocab", "source", "ontology", "prefix"], cols)
    c_code = pick(["code", "concept_id", "identifier", "curie", "id", "iri"], cols)
    c_ent = pick(["entity_id", "entity", "term_id"], cols)
    total = schema[tname]["rows"]

    header(f"M1  Mapping coverage and type-appropriateness ({tname})")
    if c_vocab:
        rows = con.execute(
            f'SELECT "{c_vocab}", COUNT(*) FROM "{tname}" GROUP BY 1 ORDER BY 2 DESC'
        ).fetchall()
        RESULTS["vocab_counts"] = {str(k): v for k, v in rows}
        for k, v in rows[:30]:
            mark = "  <-- suspect for microbiome" if str(k).upper() in SUSPECT_FOR_MICROBIOME else ""
            print(f"  {str(k):<20} {v:>8,}  {pct(v, total)}{mark}")

        # M2 prefix hygiene: aliases of the same vocabulary
        header("M2  Vocabulary prefix hygiene")
        seen = [str(k).upper().replace("_", "").replace("-", "") for k, _ in rows]
        alias_groups = defaultdict(list)
        for (k, _), norm in zip(rows, seen):
            alias_groups[norm.rstrip("CT").rstrip("S")].append(k)
        collisions = {k: v for k, v in alias_groups.items() if len(set(v)) > 1}
        if collisions:
            for k, v in collisions.items():
                flag("ERROR", "M2", f"same vocabulary under multiple names: {sorted(set(v))}")
        else:
            print("  no obvious alias collisions")
        for k, v in rows:
            if str(k).upper() in SUSPECT_FOR_MICROBIOME:
                flag(
                    "WARN",
                    "M2",
                    f"{v:,} mappings to {k} - manually review 50 of these; "
                    f"lab-observation vocabularies rarely fit microbiome entities",
                )

        # type-appropriateness crosstab, if we can join to entities
        if c_ent and "entities" in schema:
            ecols = schema["entities"]["columns"]
            e_type = pick(["entity_type", "cdm_type", "type"], ecols)
            e_id = pick(["entity_id", "id"], ecols)
            if e_type and e_id:
                header("M1b  type x vocabulary crosstab")
                q = (
                    f'SELECT e."{e_type}", m."{c_vocab}", COUNT(*) '
                    f'FROM "{tname}" m JOIN entities e ON m."{c_ent}" = e."{e_id}" '
                    f"GROUP BY 1,2"
                )
                try:
                    cross = con.execute(q).fetchall()
                except sqlite3.Error as e:
                    flag("WARN", "M1b", f"join failed: {e}")
                    cross = []
                by_type = defaultdict(Counter)
                for t, v, n in cross:
                    by_type[str(t)][str(v)] = n
                bad = {}
                for t, counter in sorted(by_type.items()):
                    allowed = TYPE_APPROPRIATE.get(t.upper())
                    tot = sum(counter.values())
                    print(f"\n  {t}  ({tot:,} mappings)")
                    for v, n in counter.most_common(8):
                        ok = ""
                        if allowed is not None:
                            ok = "  OK" if v.upper() in {a.upper() for a in allowed} else "  <-- off-type"
                        print(f"    {v:<18} {n:>7,}  {pct(n, tot)}{ok}")
                    if allowed is not None:
                        good = sum(
                            n for v, n in counter.items()
                            if v.upper() in {a.upper() for a in allowed}
                        )
                        bad[t] = (good, tot)
                        if tot and good / tot < 0.5:
                            flag(
                                "ERROR",
                                "M1b",
                                f"{t}: only {pct(good, tot)} of mappings go to an "
                                f"appropriate vocabulary - VOCAB_PRIORITY is not "
                                f"being enforced for this type",
                            )
                RESULTS["type_appropriate"] = {
                    k: {"appropriate": g, "total": t} for k, (g, t) in bad.items()
                }

        # M3 ORGANISM -> NCBITaxon, gates the compendium join
        header("M3  ORGANISM -> NCBITaxon coverage (gates the compendium join)")
        if c_ent and "entities" in schema:
            ecols = schema["entities"]["columns"]
            e_type = pick(["entity_type", "cdm_type", "type"], ecols)
            e_id = pick(["entity_id", "id"], ecols)
            if e_type and e_id:
                n_org = count(con, "entities", f"UPPER(\"{e_type}\") = 'ORGANISM'")
                q = (
                    f'SELECT COUNT(DISTINCT e."{e_id}") FROM entities e '
                    f'JOIN "{tname}" m ON m."{c_ent}" = e."{e_id}" '
                    f"WHERE UPPER(e.\"{e_type}\") = 'ORGANISM' "
                    f"AND UPPER(m.\"{c_vocab}\") LIKE 'NCBITAX%'"
                )
                try:
                    n_tax = con.execute(q).fetchone()[0]
                except sqlite3.Error:
                    n_tax = -1
                print(f"  ORGANISM entities:            {n_org:,}")
                print(f"  with an NCBITaxon mapping:    {n_tax:,}  ({pct(n_tax, n_org)})")
                RESULTS["organism_ncbitaxon"] = {"organisms": n_org, "mapped": n_tax}
                if n_org and n_tax / max(n_org, 1) < 0.6:
                    flag(
                        "ERROR",
                        "M3",
                        "under 60% of ORGANISM entities carry an NCBITaxon id. "
                        "The literature-to-compendium join will silently drop most "
                        "rows. Fix this before attempting the replication study.",
                    )

                # M3b: NCBITaxon tier distribution (precision check)
                cv_cols = schema.get("controlled_vocabularies", {}).get("columns", [])
                if "mapping_tier" in cv_cols:
                    q_tiers = (
                        f'SELECT m.mapping_tier, COUNT(DISTINCT e."{e_id}") '
                        f'FROM controlled_vocabularies m '
                        f'JOIN entities e ON m.entity_id = e."{e_id}" '
                        f"WHERE UPPER(e.\"{e_type}\") = 'ORGANISM' "
                        f"AND UPPER(m.vocabulary_name) LIKE 'NCBITAX%' "
                        f"GROUP BY m.mapping_tier"
                    )
                    try:
                        tier_rows = con.execute(q_tiers).fetchall()
                        print("  NCBITaxon mapping tier distribution:")
                        for tier, n in tier_rows:
                            label = {1: "exact [Scientific Name]",
                                     2: "synonym [All Names]",
                                     3: "broad (unqualified)"}.get(tier, f"tier {tier}")
                            print(f"    tier {tier} ({label}): {n:,}")
                        tier3 = sum(n for t, n in tier_rows if t == 3)
                        if tier3 > n_tax * 0.3 if n_tax > 0 else False:
                            flag("WARN", "M3b",
                                 f"tier 3 (broad search) accounts for {pct(tier3, n_tax)} "
                                 f"of NCBITaxon mappings — precision may be degraded. "
                                 f"Use tiers 1-2 only for the compendium join.")
                    except sqlite3.Error:
                        pass
                else:
                    flag("WARN", "M3b",
                         "no mapping_tier column in controlled_vocabularies — "
                         "cannot assess NCBITaxon mapping precision per tier")


# ------------------------------------------------------------ relationships

def check_relationships(con, schema) -> None:
    if "relationships" not in schema:
        flag("ERROR", "R0", "no 'relationships' table")
        return
    cols = schema["relationships"]["columns"]
    total = schema["relationships"]["rows"]
    c_type = pick(["relationship_type", "predicate", "rel_type", "type"], cols)
    c_src = pick(["source", "subject", "source_id", "head"], cols)
    c_tgt = pick(["target", "object", "target_id", "tail"], cols)
    c_conf = pick(["confidence", "score", "confidence_score"], cols)
    c_q = pick(["q_value", "qvalue", "fdr", "padj"], cols)
    c_p = pick(["p_value", "pvalue"], cols)
    c_npmi = pick(["npmi", "npm_i", "nmpi"], cols)
    c_co = pick(["co_occurrence_count", "cooccurrence_count", "support"], cols)
    c_doc = pick(["source_doc", "paper_doi", "document_id", "pmid", "paper_id", "evidence_doc"], cols)
    c_off = pick(["char_start", "start", "offset_start"], cols)

    header("R1  Relationship type distribution")
    if c_type:
        rows = con.execute(
            f'SELECT "{c_type}", COUNT(*) FROM relationships GROUP BY 1 ORDER BY 2 DESC'
        ).fetchall()
        RESULTS["relationship_types"] = {str(k): v for k, v in rows}
        cooc = 0
        for k, v in rows:
            print(f"  {str(k):<24} {v:>8,}  {pct(v, total)}")
            if "CO_OCCUR" in str(k).upper() or "UNASSERTED" in str(k).upper():
                cooc += v

        if cooc and cooc / max(total, 1) > 0.25:
            # Check if co-occurrence edges are significance-tested
            c_stype = pick(["source_type"], cols)
            cooc_tested = 0
            cooc_total = 0
            if c_stype and c_q:
                try:
                    row = con.execute(
                        f'SELECT COUNT(*), '
                        f'SUM(CASE WHEN "{c_q}" IS NOT NULL AND "{c_q}" < 0.05 THEN 1 ELSE 0 END) '
                        f'FROM relationships WHERE '
                        f'"{c_stype}" = "co_occurrence" OR '
                        f'LOWER("{c_type}") LIKE "%co_occur%"'
                    ).fetchone()
                    cooc_total, cooc_tested = row[0], row[1]
                except sqlite3.Error:
                    pass

            if cooc_tested and cooc_tested == cooc_total:
                flag(
                    "WARN",
                    "R1",
                    f"{cooc:,} of {total:,} edges ({pct(cooc, total)}) are co-occurrence "
                    f"(all FDR<0.05 significance-tested). Report separately from "
                    f"asserted relations in headline counts.",
                )
            else:
                flag(
                    "ERROR",
                    "R1",
                    f"{cooc:,} of {total:,} edges ({pct(cooc, total)}) are co-occurrence "
                    f"({cooc_tested:,}/{cooc_total:,} significance-tested). "
                    f"These must be reported separately from asserted relations and "
                    f"excluded from headline counts.",
                )

    header("R2  Referential integrity")
    if c_src and c_tgt:
        self_loops = count(con, "relationships", f'"{c_src}" = "{c_tgt}"')
        if self_loops:
            flag("ERROR", "R2", f"{self_loops:,} self-loops")
        nulls = count(
            con, "relationships", f'"{c_src}" IS NULL OR "{c_tgt}" IS NULL'
        )
        if nulls:
            flag("ERROR", "R2", f"{nulls:,} edges with a null endpoint")
        # dangling endpoints
        if "entities" in schema:
            ecols = schema["entities"]["columns"]
            e_id = pick(["entity_id", "id", "term", "name"], ecols)
            if e_id:
                for side, col in (("source", c_src), ("target", c_tgt)):
                    try:
                        n = con.execute(
                            f'SELECT COUNT(*) FROM relationships r '
                            f'LEFT JOIN entities e ON r."{col}" = e."{e_id}" '
                            f"WHERE e.\"{e_id}\" IS NULL"
                        ).fetchone()[0]
                    except sqlite3.Error:
                        n = 0
                    if n:
                        flag("ERROR", "R2", f"{n:,} edges whose {side} is not in entities")
        # reciprocal duplicates
        try:
            n_recip = con.execute(
                f'SELECT COUNT(*) FROM relationships a JOIN relationships b '
                f'ON a."{c_src}" = b."{c_tgt}" AND a."{c_tgt}" = b."{c_src}"'
                + (f' AND a."{c_type}" = b."{c_type}"' if c_type else "")
            ).fetchone()[0]
            if n_recip:
                flag(
                    "WARN",
                    "R2",
                    f"{n_recip:,} reciprocal edge pairs - symmetric predicates should "
                    f"be stored once with a canonical endpoint ordering",
                )
        except sqlite3.Error:
            pass
        # orphan rate
        if "entities" in schema:
            ecols = schema["entities"]["columns"]
            e_id = pick(["entity_id", "id", "term", "name"], ecols)
            if e_id:
                try:
                    connected = con.execute(
                        f'SELECT COUNT(DISTINCT x) FROM ('
                        f'SELECT "{c_src}" AS x FROM relationships '
                        f'UNION SELECT "{c_tgt}" FROM relationships)'
                    ).fetchone()[0]
                    n_ent = schema["entities"]["rows"]
                    print(f"  connected entities: {connected:,} / {n_ent:,} "
                          f"({pct(connected, n_ent)})")
                    RESULTS["orphan_rate"] = 1 - connected / max(n_ent, 1)
                    if connected / max(n_ent, 1) < 0.35:
                        flag(
                            "WARN",
                            "R2",
                            f"{pct(n_ent - connected, n_ent)} of entities are orphans",
                        )
                except sqlite3.Error:
                    pass

    header("R3  Significance filtering")
    for name, col in (("p_value", c_p), ("q_value", c_q), ("npmi", c_npmi),
                      ("co_occurrence_count", c_co)):
        if not col:
            flag("WARN", "R3", f"no {name} column")
            continue
        nn = count(con, "relationships", f'"{col}" IS NOT NULL')
        print(f"  {name:<22} populated on {nn:,} / {total:,} ({pct(nn, total)})")
    if c_q:
        sig = count(con, "relationships", f'"{c_q}" < 0.05')
        print(f"  edges with q < 0.05:   {sig:,}  ({pct(sig, total)})")
        RESULTS["significant_edges"] = sig
    if c_co:
        low = count(con, "relationships", f'"{c_co}" < 5 AND "{c_co}" IS NOT NULL')
        if low:
            flag(
                "WARN",
                "R3",
                f"{low:,} edges rest on fewer than 5 co-occurrences. G-test "
                f"approximation is unreliable there - use Fisher exact or drop them.",
            )

    header("R4  Confidence distribution by edge type")
    if c_conf and c_type:
        rows = con.execute(
            f'SELECT "{c_type}", COUNT(*), MIN("{c_conf}"), AVG("{c_conf}"), '
            f'MAX("{c_conf}") FROM relationships GROUP BY 1 ORDER BY 2 DESC'
        ).fetchall()
        for t, n, lo, avg, hi in rows:
            print(f"  {str(t):<24} n={n:>7,}  [{lo:.3f}, {hi:.3f}]  mean={avg:.3f}")
        vals = [r[0] for r in con.execute(
            f'SELECT "{c_conf}" FROM relationships WHERE "{c_conf}" IS NOT NULL'
        ).fetchall()]
        if vals:
            hist = Counter(round(v, 1) for v in vals)
            print("\n  histogram (0.1 bins):")
            for b in sorted(hist):
                bar = "#" * min(60, int(60 * hist[b] / max(hist.values())))
                print(f"    {b:.1f}  {hist[b]:>7,}  {bar}")
            spikes = [b for b, n in hist.items() if n > len(vals) * 0.25]
            if spikes:
                flag(
                    "WARN",
                    "R4",
                    f"confidence mass concentrated at {spikes} - a hardcoded prior "
                    f"rather than a calibrated score",
                )

    header("R5  Provenance completeness")
    c_stype = pick(["source_type"], cols)
    if c_stype:
        type_dist = con.execute(
            f'SELECT "{c_stype}", COUNT(*) FROM relationships GROUP BY 1'
        ).fetchall()
        print("  source_type distribution:")
        for st, n in type_dist:
            print(f"    {st}: {n:,}")
    else:
        flag("WARN", "R5", "no source_type column - cannot distinguish edge provenance type")

    # Check edge_evidence table
    if "edge_evidence" in schema:
        ev_count = schema["edge_evidence"]["rows"]
        ev_per_rel = con.execute(
            "SELECT COUNT(DISTINCT relationship_id), COUNT(*) FROM edge_evidence"
        ).fetchone()
        print(f"  edge_evidence: {ev_count:,} rows across {ev_per_rel[0]:,} relationships")
        if ev_count == 0:
            flag("ERROR", "R5", "edge_evidence table is empty - edges have no per-paper provenance")
    else:
        flag("WARN", "R5", "no edge_evidence table - per-paper provenance not captured")

    if c_doc and c_stype:
        missing = count(con, "relationships",
                        f'("{c_doc}" IS NULL OR "{c_doc}" = "") AND "{c_stype}" != "co_occurrence"')
        flag(
            "ERROR" if missing > total * 0.05 else "INFO",
            "R5",
            f"{missing:,} edges ({pct(missing, total)}) have no source document (non-co-occurrence)",
        )
    elif c_doc:
        missing = count(con, "relationships", f'"{c_doc}" IS NULL OR "{c_doc}" = ""')
        flag(
            "ERROR" if missing > total * 0.05 else "INFO",
            "R5",
            f"{missing:,} edges ({pct(missing, total)}) have no source document",
        )
    elif c_stype:
        # With source_type, paper_doi may be NULL for co-occurrence edges (provenance in edge_evidence)
        no_ev = count(con, "relationships", f'"{c_stype}" = "co_occurrence"') - \
            con.execute("SELECT COUNT(DISTINCT relationship_id) FROM edge_evidence").fetchone()[0] \
            if "edge_evidence" in schema else total
        if no_ev > 0:
            flag("WARN", "R5",
                 f"{no_ev:,} co-occurrence edges have no edge_evidence rows")
    else:
        flag("ERROR", "R5", "no source-document column and no source_type - edges are unciteable")
    if not c_off:
        flag(
            "WARN",
            "R5",
            "no character offsets on relationships - cannot show the sentence that "
            "supports an edge, and cannot evaluate against GutBrainIE mention-level RE",
        )


# ------------------------------------------------------------ offset check

def check_offsets(con, schema, papers_dir: str | None) -> None:
    header("P1  Mention offset spot-check")
    if not papers_dir or not os.path.isdir(papers_dir):
        flag("WARN", "P1", "papers dir not supplied or not found - skipped")
        return
    tname = next((t for t in ("mentions", "extracted_entities", "entity_mentions", "entity_project_mentions")
                  if t in schema), None)
    if not tname:
        flag("WARN", "P1", "no mentions table found")
        return
    cols = schema[tname]["columns"]
    c_text = pick(["text", "mention", "surface_form", "term", "span", "paper_context"], cols)
    c_start = pick(["char_start", "start", "start_char", "offset_start"], cols)
    c_end = pick(["char_end", "end", "end_char", "offset_end"], cols)
    c_doc = pick(["document_id", "paper_id", "source_doc", "paper_doi", "project_id", "accession", "pmid"], cols)
    if not all([c_text, c_start, c_end, c_doc]):
        flag(
            "WARN",
            "P1",
            f"mentions table lacks offsets/doc id (found: text={c_text}, "
            f"start={c_start}, end={c_end}, doc={c_doc}) - offsets cannot be verified",
        )
        return

    rows = con.execute(
        f'SELECT "{c_doc}", "{c_start}", "{c_end}", "{c_text}" FROM "{tname}" '
        f'WHERE "{c_start}" IS NOT NULL ORDER BY RANDOM() LIMIT 200'
    ).fetchall()
    cache: dict[str, str] = {}
    ok = bad = missing = 0
    examples = []
    for doc, s, e, txt in rows:
        key = str(doc)
        if key not in cache:
            path = None
            for cand in (key, f"{key}.txt"):
                p = os.path.join(papers_dir, cand)
                if os.path.isfile(p):
                    path = p
                    break
            cache[key] = open(path, encoding="utf-8", errors="replace").read() if path else ""
        body = cache[key]
        if not body:
            missing += 1
            continue
        try:
            got = body[int(s):int(e)]
        except (TypeError, ValueError):
            bad += 1
            continue
        if got.strip() == str(txt).strip():
            ok += 1
        else:
            bad += 1
            if len(examples) < 5:
                examples.append((key, s, e, txt, got[:40]))
    print(f"  checked {ok + bad} mentions ({missing} docs not found on disk)")
    print(f"  offsets correct: {ok}   incorrect: {bad}  ({pct(ok, ok + bad)} correct)")
    RESULTS["offset_accuracy"] = {"ok": ok, "bad": bad, "missing_docs": missing}
    for ex in examples:
        print(f"    {ex[0]} [{ex[1]}:{ex[2]}] expected {ex[3]!r} got {ex[4]!r}")
    if bad:
        flag(
            "ERROR",
            "P1",
            f"{bad} of {ok + bad} sampled offsets do not resolve to the stored text. "
            f"Likely an encoding or normalization step shifting positions.",
        )


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True, help="path to microbiome_cdm.db")
    ap.add_argument("--papers", default=None, help="path to data/papers_txt/ for P1")
    ap.add_argument("--json", default=None, help="write machine-readable results here")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    random.seed(args.seed)
    if not os.path.isfile(args.db):
        print(f"error: no such database: {args.db}", file=sys.stderr)
        return 2

    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    con.create_function("REGEXP", 2, lambda p, s: bool(re.search(p, s or "")))

    print(f"auditing {args.db} ({os.path.getsize(args.db) / 1e6:.1f} MB)")
    schema = check_schema(con)
    check_entities(con, schema)
    check_mappings(con, schema)
    check_relationships(con, schema)
    check_offsets(con, schema, args.papers)

    header("SUMMARY")
    sev = Counter(f["severity"] for f in FINDINGS)
    print(f"  ERROR {sev['ERROR']}   WARN {sev['WARN']}   INFO {sev['INFO']}")
    for f in FINDINGS:
        if f["severity"] == "ERROR":
            print(f"  X [{f['check']}] {f['message']}")

    RESULTS["findings"] = FINDINGS
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(RESULTS, fh, indent=2, default=str)
        print(f"\nwrote {args.json}")
    con.close()
    return 1 if sev["ERROR"] else 0


if __name__ == "__main__":
    sys.exit(main())
