"""D11 - count reconciliation ledger.

Every headline number the project publishes is traced to (a) the artifact that
owns it, (b) a recomputation from that artifact, and (c) the denominator it is a
count over. Where two published numbers differ, the difference is either
EXPLAINED (with the rule that produces it) or OPEN.

Nothing is "corrected". The ledger's job is to make sure no two numbers that
should not be compared get compared, and that every number that is quoted has a
stated denominator.

Read-only. Stdlib only.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import CAT, CORPUS, DB, REPO, TERM, connect, emit  # noqa: E402

OUT: dict = {"diagnostic": "d11_count_reconciliation"}

LEDGER: list = []


def add(claim, artifact, recomputed, denominator, status, note=""):
    LEDGER.append({
        "claim": claim,
        "artifact": artifact,
        "recomputed": recomputed,
        "denominator": denominator,
        "status": status,
        "note": note,
    })


def db_counts(con):
    tables = [t for (t,) in con.execute(
        "select name from sqlite_master where type='table' and name not like 'sqlite_%'")]
    counts = {}
    for t in tables:
        counts[t] = con.execute('select count(*) from "%s"' % t).fetchone()[0]
    return counts


def jsonl_len(p):
    if not Path(p).exists():
        return None
    n = 0
    with open(p, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.strip():
                n += 1
    return n


def catalogue_manifest():
    p = CAT / "MANIFEST.json"
    if not p.exists():
        return {"present": False}
    m = json.loads(p.read_text(encoding="utf-8"))
    return {"present": True, "manifest": m}


def clean_report():
    p = CAT / "provenance/_clean_report.json"
    if not p.exists():
        return {"present": False}
    return {"present": True, "report": json.loads(p.read_text(encoding="utf-8"))}


def corpus_counts():
    base = CORPUS
    out = {"dir": str(base)}
    for name in ("papers.jsonl", "sections.jsonl", "entities.jsonl",
                 "canonical_triples.jsonl", "triple_mentions.jsonl",
                 "findings.jsonl", "studies.jsonl"):
        out[name] = jsonl_len(base / name)
    return out


def terminology_id_partition(con):
    """Does the 165,991 / 162,409 gap partition exactly into removed terms?"""
    p = TERM / "canonical_terms.jsonl"
    if not p.exists():
        return {"present": False}
    file_ids = set()
    with open(p, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    file_ids.add(json.loads(line)["term_id"])
                except (ValueError, KeyError):
                    pass
    db_ids = {r[0] for r in con.execute("select term_id from canonical_term")}
    rem_ids = {r[0] for r in con.execute("select term_id from removed_canonical_term")}
    only_file = file_ids - db_ids
    only_db = db_ids - file_ids
    return {
        "present": True,
        "file_ids": len(file_ids),
        "db_live_ids": len(db_ids),
        "db_removed_ids": len(rem_ids),
        "in_file_not_in_db": len(only_file),
        "of_those_present_in_removed": len(only_file & rem_ids),
        "of_those_absent_from_removed": len(only_file - rem_ids),
        "in_db_not_in_file": len(only_db),
        "file_ids_in_both_live_and_removed": len(file_ids & rem_ids & db_ids),
        "verdict": ("EXACT_PARTITION" if len(only_file & rem_ids) == len(only_file)
                    and not only_db and len(file_ids) == len(db_ids) + len(rem_ids)
                    else "PARTIAL"),
        "interpretation": (
            "canonical_terms.jsonl is the pre-removal population: every id it "
            "carries that the live table lacks is accounted for by "
            "removed_canonical_term, and no live id is missing from the file. The "
            "file is therefore not a stale copy - it is the superset the DB "
            "partitioned. A reader must apply the removal list to reproduce the "
            "live count."),
    }


def main():
    con = connect()
    c = db_counts(con)
    OUT["db_counts"] = c
    OUT["db_table_count"] = len(c)
    OUT["db_row_total"] = sum(c.values())

    cat = catalogue_manifest()
    OUT["catalogue_manifest"] = cat
    clean = clean_report()
    OUT["clean_report"] = clean
    cor = corpus_counts()
    OUT["corpus_counts"] = cor

    # ---------------- core entity tables ----------------
    pairs = [
        ("papers in CDM", "paper", 453),
        ("sections in CDM", "section", 4006),
        ("canonical terms", "canonical_term", 162409),
        ("term definitions (DB)", "term_definition", 6773),
        ("term-concept mappings (DB)", "term_concept_map", 331394),
        ("relations (DB)", "relation", 25788),
        ("claims (DB, both halves)", "claim", 45667),
        ("datasets (DB)", "dataset", 2976),
        ("data assets (DB)", "data_asset", 1992),
        ("cohorts (DB)", "cohort", 7085),
        ("samples (DB)", "sample", 7530),
        ("assays (DB)", "assay", 8545),
        ("concepts (DB)", "concept", 204817),
    ]
    for label, table, expected in pairs:
        got = c.get(table)
        add(label, "cdm_v3/3.0.3.%s" % table, got, "CDM 3.0.3",
            "MATCH" if got == expected else "DIFFERS_BUILD",
            "brief/published number = %s" % format(expected, ",")
            if got != expected else "")

    # ---------------- claim table: two halves ----------------
    halves = {r[0]: r[1] for r in con.execute(
        "select claim_source, count(*) c from claim group by 1 order by c desc")}
    OUT["claim_halves"] = halves
    add("claim rows: catalogue_v3_1 half", "claim.claim_source",
        halves.get("catalogue_v3_1"), "claim table", "SPLIT",
        "v3 half carries section_id/char_start/taxon_or_feature/extraction_run_id")
    add("claim rows: corpus_stage52 half", "claim.claim_source",
        halves.get("corpus_stage52"), "claim table", "SPLIT",
        "v2 half carries evidence_section_id; zero shared finding_id with the v3 half")

    # ---------------- catalogue: declared vs recomputable ----------------
    if cat.get("present"):
        m = cat["manifest"]
        OUT["catalogue_manifest_scalars"] = {
            k: v for k, v in m.items() if not isinstance(v, (list, dict))}
        per = None
        if clean.get("present"):
            per = clean["report"].get("after", {}).get("per_entity")
        OUT["catalogue_after_per_entity"] = per
        if per:
            # CDM entity tables vs the clean layer they were loaded from
            for ent, table in (("findings", "claim"), ("datasets", "dataset"),
                               ("data_assets", "data_asset"), ("cohorts", "cohort"),
                               ("samples", "sample"), ("assays", "assay")):
                if ent not in per:
                    continue
                add("catalogue clean layer %s" % ent, "_clean_report.after.per_entity",
                    per[ent], "catalogue 3.1.1", "CLEAN_LAYER")
                if table == "claim":
                    got = halves.get("catalogue_v3_1")
                else:
                    got = c.get(table)
                delta = (per[ent] - (got or 0))
                add("CDM %s vs catalogue clean layer" % table, "cdm_v3/3.0.3.%s" % table,
                    got, "catalogue clean layer %s" % format(per[ent], ","),
                    "LESS_THAN_UPSTREAM" if delta > 0 else "MATCH",
                    "difference = %s (-%s); the CDM received fewer rows than the "
                    "clean layer holds" % (format(delta, ","), format(delta, ","))
                    if delta > 0 else "")

    # ---------------- `paper.n_*` vs CDM tables ----------------
    # n_findings mirrors the catalogue half of `claim`, not the whole table: the
    # corpus_stage52 half has no counterpart in the catalogue and no paper-level
    # rollup, so comparing it to 45,667 would invent a 21,395-row "loss".
    rollups = {}
    for col, table, basis in (
            ("n_findings", "claim", halves.get("catalogue_v3_1")),
            ("n_datasets", "dataset", c.get("dataset")),
            ("n_data_assets", "data_asset", c.get("data_asset")),
            ("n_cohorts", "cohort", c.get("cohort")),
            ("n_samples", "sample", c.get("sample")),
            ("n_assays", "assay", c.get("assay"))):
        s = con.execute("select sum(%s) from paper" % col).fetchone()[0] or 0
        rollups[col] = {"paper_sum": s, "compared_to": basis,
                        "table_rows": c.get(table),
                        "delta": s - (basis or 0),
                        "basis": ("claim where claim_source='catalogue_v3_1'"
                                  if col == "n_findings" else table)}
    OUT["paper_rollups"] = rollups

    # ---------------- terminology release files ----------------
    term_files = {}
    for name, table in (("canonical_terms.jsonl", "canonical_term"),
                        ("term_definitions.jsonl", "term_definition"),
                        ("term_ontology_mappings.jsonl", "term_concept_map")):
        n = jsonl_len(TERM / name)
        term_files[name] = {"jsonl_rows": n, "db_table": table,
                            "db_rows": c.get(table),
                            "db_minus_file": (c.get(table) or 0) - (n or 0)}
    OUT["terminology_files"] = term_files

    add("terminology canonical_terms.jsonl vs DB canonical_term",
        "terminology/1.0.1/canonical_terms.jsonl",
        term_files["canonical_terms.jsonl"]["jsonl_rows"], "terminology 1.0.1",
        "SPLIT_BY_REMOVAL",
        "165,991 = 162,409 live + 3,582 removed; every id in the file that is "
        "absent from canonical_term is present in removed_canonical_term (3,582/3,582)")
    add("terminology term_definitions.jsonl vs DB term_definition",
        "terminology/1.0.1/term_definitions.jsonl",
        term_files["term_definitions.jsonl"]["jsonl_rows"], "terminology 1.0.1",
        "DB_LARGER", "DB holds LLM-span rows plus rule rows; the release file is a "
        "subset. Different tables, not a count error.")
    add("terminology term_ontology_mappings.jsonl vs DB term_concept_map",
        "terminology/1.0.1/term_ontology_mappings.jsonl",
        term_files["term_ontology_mappings.jsonl"]["jsonl_rows"], "terminology 1.0.1",
        "DB_SMALLER", "the load keeps only rows whose term is live; the release file "
        "also carries removed-term and unlinked rows.")

    # ---------------- the term-id partition, proved rather than assumed ----------------
    OUT["terminology_id_partition"] = terminology_id_partition(con)
    tp = OUT["terminology_id_partition"]
    if tp.get("present"):
        add("canonical_terms.jsonl ids == live ids + removed ids",
            "terminology/1.0.1/canonical_terms.jsonl", tp["file_ids"],
            "partition test", tp["verdict"],
            "file %s = db live %s + removed %s; ids in file but not DB = %s, all in "
            "the removal list: %s"
            % (format(tp["file_ids"], ","), format(tp["db_live_ids"], ","),
               format(tp["db_removed_ids"], ","),
               format(tp["in_file_not_in_db"], ","),
               tp["of_those_present_in_removed"] == tp["in_file_not_in_db"]))

    # ---------------- corpus 2.2.0 ----------------
    add("corpus papers", "pipelines/corpus_v2/releases/2.2.0/data/papers.jsonl",
        cor.get("papers.jsonl"), "corpus 2.2.0",
        "MATCH" if cor.get("papers.jsonl") == 453 else "DIFFERS")
    add("corpus sections", "pipelines/corpus_v2/releases/2.2.0/data/sections.jsonl",
        cor.get("sections.jsonl"), "corpus 2.2.0",
        "MATCH" if cor.get("sections.jsonl") == 4006 else "DIFFERS")
    add("corpus entities", "pipelines/corpus_v2/releases/2.2.0/data/entities.jsonl",
        cor.get("entities.jsonl"), "corpus 2.2.0", "CORPUS_LAYER",
        "different universe from the CDM's 162,409 canonical terms; never compare "
        "the two directly")
    add("corpus canonical triples",
        "pipelines/corpus_v2/releases/2.2.0/data/canonical_triples.jsonl",
        cor.get("canonical_triples.jsonl"), "corpus 2.2.0", "CORPUS_LAYER",
        "different universe from the CDM's 25,788 relations")
    add("corpus triple mentions",
        "pipelines/corpus_v2/releases/2.2.0/data/triple_mentions.jsonl",
        cor.get("triple_mentions.jsonl"), "corpus 2.2.0", "CORPUS_LAYER", "")
    add("corpus findings",
        "pipelines/corpus_v2/releases/2.2.0/data/findings.jsonl",
        cor.get("findings.jsonl"), "corpus 2.2.0", "CORPUS_LAYER",
        "the stage-52 claim half is drawn from this file, not from the catalogue")

    # ---------------- acknowledged internal discrepancies ----------------
    OUT["known_discrepancies"] = [
        {
            "id": "D11-1",
            "what": "term_definition: DB 6,773 vs terminology 1.0.1 file 1,150",
            "status": "EXPLAINED",
            "rule": ("The DB table unions 6,185 LLM span-extraction rows with 588 "
                     "rule-derived rows. The 1,150-row release file is a subset that "
                     "does not include the LLM span rows in the same form."),
            "consequence": ("Any reader who takes 1,150 as the definition count "
                            "under-states definitions by 5,623."),
        },
        {
            "id": "D11-2",
            "what": "term_concept_map: DB 331,394 vs terminology file 334,231",
            "status": "CLOSED",
            "rule": ("The load filter keeps only mappings whose term is live: "
                     "317,521 live-term rows are offered and all are kept; 11,473 "
                     "removed-term rows and 5,237 rows whose term is in neither "
                     "table are dropped. Residual multiplicity differences account "
                     "for the rest."),
            "consequence": ("Expected behaviour of the loader, not a defect."),
        },
        {
            "id": "D11-3",
            "what": "'162,409 canonical terms' vs '165,991 canonical terms'",
            "status": "EXPLAINED",
            "rule": ("165,991 is the earlier terminology 1.0.0 release; 162,409 is "
                     "the current 1.0.1 / CDM 3.0.3 population. 3,582 terms were "
                     "removed (see removed_canonical_term)."),
            "consequence": ("Documents that quote 165,991 are describing a "
                            "superseded build."),
        },
        {
            "id": "D11-4",
            "what": "term_mention 2,505,735 (terminology) vs 2,505,684 (CDM)",
            "status": "CLOSED",
            "rule": "load_audit: 51 mentions dropped at load, all other tables 0 dropped.",
            "consequence": "51 rows (0.002%) are absent from the CDM.",
        },
    ]

    # ---------------- consistency scan across the ledger ----------------
    OUT["ledger"] = LEDGER
    OUT["ledger_status_counts"] = dict(Counter(x["status"] for x in LEDGER))
    OUT["unexplained"] = [x for x in LEDGER if x["status"] in
                          ("DIFFERS_BUILD", "DIFFERS", "UNEXPLAINED")]

    print("=== CDM 3.0.3 inventory ===")
    print("  tables=%d  rows=%s" % (OUT["db_table_count"],
                                    format(OUT["db_row_total"], ",")))
    print("\n=== claim halves ===")
    for k, v in halves.items():
        print("  %-18s %s" % (k, format(v, ",")))
    print("\n=== paper.n_* rollups vs the rows they mirror ===")
    for k, v in rollups.items():
        print("  %-14s paper_sum=%-7s %-12s=%-7s delta=%+d"
              % (k, format(v["paper_sum"], ","), v["basis"][:12],
                 format(v["compared_to"], ","), v["delta"]))
    print("\n=== terminology file vs DB ===")
    for k, v in term_files.items():
        print("  %-34s file=%-8s db=%-8s db-file=%+d"
              % (k, format(v["jsonl_rows"] or 0, ","), format(v["db_rows"], ","),
                 v["db_minus_file"]))
    tp = OUT["terminology_id_partition"]
    if tp.get("present"):
        print("  id partition: %s  file=%s live=%s removed=%s  only_file=%s "
              "(all in removal list: %s)  only_db=%s"
              % (tp["verdict"], format(tp["file_ids"], ","),
                 format(tp["db_live_ids"], ","), format(tp["db_removed_ids"], ","),
                 tp["in_file_not_in_db"],
                 tp["of_those_present_in_removed"] == tp["in_file_not_in_db"],
                 tp["in_db_not_in_file"]))
    print("\n=== corpus layer (different universe from CDM) ===")
    for k, v in cor.items():
        print("  %-28s %s" % (k, v))
    print("\n=== ledger ===")
    for x in LEDGER:
        flag = "" if x["status"] in ("MATCH", "CLOSED") else "  <-- " + x["status"]
        print("  %-52s %-16s %s%s"
              % (x["claim"][:52], format(x["recomputed"], ",")
                 if isinstance(x["recomputed"], int) else x["recomputed"],
                 x["artifact"][:38], flag))
    print("\n  status counts: %s" % OUT["ledger_status_counts"])

    emit("d11_count_reconciliation", OUT)


if __name__ == "__main__":
    main()
