#!/usr/bin/env python3
"""One-shot offline enrichment of the human-microbiome corpus v1 records.

Populates Layer 2 (study metadata) and evidence links in the per-paper JSON
records using ONLY data already on disk:

  1. releases/v3.0-cdm/cdm/microbiome_cdm.db  `projects` table
     (BioProject accession -> title, DOI link, sample_type, condition,
      subjects, amplicon region, extraction kit, geo, age stats, counts)
  2. same DB, `samples` table (per-project sample counts)
  3. same DB, `entity_project_mentions` + `entities`
     (per-paper entity mentions with character offsets)

What records gain (all provenance-tracked, never overwriting existing
non-empty values; re-runs only fill what is still null/empty):

  publication.title / doi / source_url
  study_metadata.population_description / number_of_samples /
      country_or_region / health_conditions / exposures / sample_size_reported
  microbiome_metadata.body_sites / sample_types / target_genes_or_regions /
      dna_extraction_methods / sequencing_strategy
  exposures_and_interventions.antibiotics / probiotics / dietary_exposures
  evidence_links: top entity mentions per CDM type, each with the exact
      section_id it occurs in (resolved via full_text.sections offsets)
  enrichment block: per-field provenance notes

Usage (offline, runs in ~seconds):
    python enrich_corpus_records.py \
        --records outputs/results/human_microbiome_corpus_v1 \
        --db releases/v3.0-cdm/cdm/microbiome_cdm.db
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import sqlite3
from collections import Counter
from pathlib import Path

VERSION = "1.1.0"
MAX_MENTIONS_PER_TYPE = 12

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("enrich")


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def accession_from_record(rec: dict):
    """PRJ accession from the source file name (papers are named by accession)."""
    src = (
        rec.get("source", {}).get("relative_path")
        or rec.get("full_text", {}).get("original_file")
        or ""
    )
    name = str(src).rsplit("/", 1)[-1]
    if name.startswith("PRJ") and name.endswith(".txt"):
        return name[:-4]
    return None


def load_projects(db: Path) -> dict:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    projects = {r["project_id"]: dict(r) for r in con.execute("select * from projects")}
    counts = dict(con.execute("select project_id, count(*) from samples group by project_id"))
    con.close()
    for acc, p in projects.items():
        p["_n_samples"] = counts.get(acc, 0)
    return projects


def load_mentions(db: Path, per_type_cap: int = MAX_MENTIONS_PER_TYPE) -> dict:
    """Per-accession mentions; keep the most frequent terms per entity_type."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    per_acc = {}
    q = (
        "select m.project_id, m.char_start, m.char_end, m.source_model, "
        "       e.term, e.entity_type, e.UMLS_ID "
        "from entity_project_mentions m join entities e on e.id = m.entity_id"
    )
    for r in con.execute(q):
        per_acc.setdefault(r["project_id"], []).append(dict(r))
    con.close()

    out = {}
    for acc, ms in per_acc.items():
        freq = Counter(m["term"] for m in ms)
        by_type = {}
        for m in sorted(ms, key=lambda m: -freq[m["term"]]):
            lst = by_type.setdefault(m["entity_type"], [])
            if len(lst) < per_type_cap:
                lst.append(m)
        out[acc] = by_type
    return out


def resolve_section(rec: dict, char_start: int):
    """section_id for a char offset via the record's full_text.sections index."""
    secs = rec.get("full_text", {}).get("sections") or []
    for s in secs:
        st, en = s.get("start_char"), s.get("end_char")
        if st is None:
            continue
        if en is not None and st <= char_start < en:
            return s.get("section_id")
        if en is None and st <= char_start:
            return s.get("section_id")
    return None


def is_empty(v) -> bool:
    if v is None:
        return True
    if isinstance(v, str):
        return v.strip() == "" or v.strip().lower() in {"not_reported", "unknown", "unclear"}
    if isinstance(v, (list, dict, tuple)):
        return len(v) == 0
    return False


def fill(dest: dict, key: str, value, provenance: str, notes: list, transform=None):
    """Set dest[key] = value only if currently empty; never overwrite. Returns True if set."""
    if is_empty(dest.get(key)) and not is_empty(value):
        dest[key] = transform(value) if transform else value
        notes.append(f"{key}<-{provenance}")
        return True
    return False


def as_list(x):
    if x is None:
        return None
    if isinstance(x, (list, tuple)):
        return list(x)
    return [x]


def enrich_record(rec: dict, proj, mentions_by_type) -> dict:
    notes = []
    pub = rec.setdefault("publication", {})
    sm = rec.setdefault("study_metadata", {})
    mm = rec.setdefault("microbiome_metadata", {})
    ex = rec.setdefault("exposures_and_interventions", {})
    qp = rec.setdefault("quality_and_provenance", {})

    if proj:
        # ── publication ────────────────────────────────────────
        fill(pub, "title", proj.get("title"), "v3.0_projects.title", notes)
        link = proj.get("link") or ""
        if is_empty(pub.get("doi")) and "doi.org/" in link:
            fill(pub, "doi", link.split("doi.org/")[-1], "v3.0_projects.link", notes)
        if is_empty(pub.get("source_url")):
            fill(pub, "source_url", link or None, "v3.0_projects.link", notes)
        fill(
            sm,
            "data_accessions",
            [f"BioProject:{proj['project_id']}"],
            "v3.0_projects.project_id",
            notes,
        )

        # ── study_metadata (Layer 2) ───────────────────────────
        fill(sm, "population_description", proj.get("subjects"), "v3.0_projects.subjects", notes)
        fill(sm, "number_of_samples", proj.get("_n_samples") or None, "v3.0_cdm.samples", notes)
        fill(
            sm,
            "country_or_region",
            as_list(proj.get("geo_locations")),
            "v3.0_projects.geo_locations",
            notes,
        )
        fill(
            sm,
            "health_conditions",
            as_list(proj.get("condition")),
            "v3.0_projects.condition",
            notes,
        )
        fill(
            sm, "health_conditions", as_list(proj.get("diseases")), "v3.0_projects.diseases", notes
        )
        fill(
            sm,
            "exposures",
            [
                v
                for v in (
                    proj.get("diet_types"),
                    proj.get("smoking_status"),
                    proj.get("antibiotic_history"),
                    proj.get("probiotic_use"),
                )
                if v and not is_empty(v)
            ],
            "v3.0_projects.exposure_flags",
            notes,
        )
        found = proj.get("biosample_n_samples_found")
        if found:
            fill(
                sm,
                "sample_size_reported",
                f"{found} biosamples (NMDC catalogue)",
                "v3.0_projects.biosample_n_samples_found",
                notes,
            )
        if proj.get("age_min") is not None and proj.get("age_max") is not None:
            fill(
                sm,
                "population_description",
                f"ages {proj['age_min']}-{proj['age_max']} yrs, mean {proj.get('age_mean')}"
                + (f"; {proj['subjects']}" if proj.get("subjects") else ""),
                "v3.0_projects.age_min/max",
                notes,
            )

        # ── microbiome_metadata (MIxS-style) ───────────────────
        fill(mm, "body_sites", as_list(proj.get("body_site")), "v3.0_projects.body_site", notes)
        fill(
            mm, "sample_types", as_list(proj.get("sample_type")), "v3.0_projects.sample_type", notes
        )
        fill(
            mm,
            "target_genes_or_regions",
            as_list(proj.get("amplicon")),
            "v3.0_projects.amplicon",
            notes,
        )
        fill(mm, "dna_extraction_methods", as_list(proj.get("kit")), "v3.0_projects.kit", notes)
        if is_empty(mm.get("sequencing_strategy")) and not is_empty(proj.get("amplicon")):
            mm["sequencing_strategy"] = ["amplicon"]
            notes.append("sequencing_strategy<-v3.0_projects.amplicon")

        # ── exposures_and_interventions ────────────────────────
        if not is_empty(proj.get("antibiotic_history")):
            fill(
                ex,
                "antibiotics",
                as_list(proj.get("antibiotic_history")),
                "v3.0_projects.antibiotic_history",
                notes,
            )
        if not is_empty(proj.get("probiotic_use")):
            fill(
                ex,
                "probiotics",
                as_list(proj.get("probiotic_use")),
                "v3.0_projects.probiotic_use",
                notes,
            )
        if not is_empty(proj.get("diet_types")):
            fill(
                ex,
                "dietary_exposures",
                as_list(proj.get("diet_types")),
                "v3.0_projects.diet_types",
                notes,
            )

    # ── evidence links from NER entity mentions ─────────────────
    if mentions_by_type:
        links = []
        for _etype, ms in sorted(mentions_by_type.items()):
            for m in ms:
                if m.get("char_start") is None:
                    continue  # PubTator3 rows carry no offsets
                links.append(
                    {
                        "term": m["term"],
                        "entity_type": m["entity_type"],
                        "umls_id": m.get("UMLS_ID"),
                        "source_model": m["source_model"],
                        "evidence_locator": f"chars {m['char_start']}-{m['char_end']}",
                        "section_id": resolve_section(rec, m["char_start"]),
                    }
                )
        if links:
            rec["evidence_links"] = links
            notes.append(
                f"evidence_links<-v3.0_cdm.entity_project_mentions ({len(links)} mentions)"
            )
        qp["evidence_link_count"] = len(links)

    prev = rec.get("enrichment") or {}
    rec["enrichment"] = {
        "v3_projects_matched": proj is not None,
        "schema_version": VERSION,
        "enriched_at": now(),
        "fields_filled_this_run": notes,
        "fields_filled_previous_run": prev.get("fields_filled_this_run", []),
    }
    return rec


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--records",
        default="outputs/results/human_microbiome_corpus_v1",
        help="corpus root (containing records/ subdir)",
    )
    ap.add_argument("--db", default="releases/v3.0-cdm/cdm/microbiome_cdm.db")
    ap.add_argument("--max-mentions-per-type", type=int, default=MAX_MENTIONS_PER_TYPE)
    args = ap.parse_args()

    rec_dir = Path(args.records) / "records"
    db = Path(args.db)
    if not rec_dir.is_dir():
        log.error("records dir not found: %s", rec_dir)
        return 2
    if not db.is_file():
        log.error("db not found: %s", db)
        return 2

    log.info("Loading v3.0 CDM projects + sample counts ...")
    projects = load_projects(db)
    log.info("  %d projects", len(projects))
    log.info("Loading entity mentions ...")
    mentions = load_mentions(db, per_type_cap=args.max_mentions_per_type)
    log.info("  %d papers with mentions", len(mentions))

    n_total = n_changed = n_matched = 0
    type_link_counts = Counter()
    for jf in sorted(rec_dir.glob("*/*.json")):
        n_total += 1
        try:
            rec = json.loads(jf.read_text())
        except Exception as e:
            log.warning("bad record %s: %s", jf, e)
            continue
        acc = accession_from_record(rec)
        proj = projects.get(acc)
        ment = mentions.get(acc)
        if proj:
            n_matched += 1
        before = json.dumps(rec, sort_keys=True)
        rec = enrich_record(rec, proj, ment)
        after = json.dumps(rec, sort_keys=True)
        if after != before:
            tmp = jf.with_suffix(".json.tmp")
            tmp.write_text(after)
            tmp.replace(jf)  # atomic write
            n_changed += 1
        for link in rec.get("evidence_links", []):
            type_link_counts[link["entity_type"]] += 1

    log.info("Records: %d  matched-to-projects: %d  enriched: %d", n_total, n_matched, n_changed)
    log.info("Evidence links by type: %s", dict(type_link_counts.most_common()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
