"""GPU gap stages (docs/gpu_gap_plan.md) on top of gaplib.

    python gap_stages.py build --stage G1            # count/preview requests (no GPU)
    python gap_stages.py run   --stage G1 --shard 0 --nshards 8 --host http://127.0.0.1:8000
    python gap_stages.py apply --stage G1            # CPU: accept answers, write outputs
    python gap_stages.py prep                        # CPU: compendium/studies pre-fill (C0)
    python gap_stages.py finalize                    # CPU: merge G5, write catalogue_v3_1

Catalogue data flow (each step writes a new directory under outputs/results/gap_runs/):
    catalogue_v3_vocab -> C0 prefill -> G1/G2 -> G3 (+G3B tie-break) -> G4 relink
                       -> finalize (+G5 interventions) -> catalogue_v3_1
CDM/terminology stages (independent): E (embeddings) -> G6, G7 ; G8 ; G9.

Acceptance rules are deterministic and live in the apply_* functions: a model
value is only written with an exact source quote; originals are kept in
`gap_changes`; `field_sources` records where every filled value came from.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

import gaplib as G

csv.field_size_limit(sys.maxsize)

R = G.RESULTS
GD = G.GAP_DIR
BASE = R / "catalogue_v3_vocab"
ENTITIES = ("datasets", "data_assets", "cohorts", "samples", "assays", "findings")
MISSING = {"NOT_REPORTED", "NOT_APPLICABLE", "NOT_ACCESSIBLE", "CONFLICTING"}
STAGE_MODEL = {"G1": "qwen", "G2": "qwen", "G3": "gemma", "G3B": "llama", "G5": "qwen",
               "G6": "gemma", "G7": "gemma", "G8": "qwen", "G9": "gemma", "G11": "qwen", "G11B": "gemma"}


def stage_dir(stage):
    return GD / stage


# ── catalogue I/O ────────────────────────────────────────────────────────────
def headers(cat_dir):
    out = {}
    for e in ENTITIES:
        with open(Path(cat_dir) / f"catalogue_{e}.csv", newline="", encoding="utf-8") as fh:
            out[e] = next(csv.reader(fh))
    return out


def save_catalogue(out_dir, records, src_dir, extra_cols=()):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    G.write_jsonl(out_dir / "catalogue_records.jsonl", records)
    hdr = headers(src_dir)
    for e in ENTITIES:
        cols = hdr[e] + [c for c in ("field_sources", "gap_changes", *extra_cols) if c not in hdr[e]]
        with open(out_dir / f"catalogue_{e}.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for r in records:
                if r["entity_type"] == e:
                    w.writerow({k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)
                                for k, v in r["fields"].items()})
    for name in ("catalogue_papers.csv", "_removed.jsonl", "_v2_to_v3_map.csv",
                 "_link_report.json", "_clean_report.json"):
        src = Path(src_dir) / name
        if src.exists() and not (out_dir / name).exists():
            shutil.copy2(src, out_dir / name)


def note_change(f, field, old, new, source):
    ch = f.get("gap_changes") or {}
    if isinstance(ch, str):
        ch = json.loads(ch) if ch else {}
    ch.setdefault(field, {"original": old})
    ch[field].update(new=new, source=source)
    f["gap_changes"] = ch
    fs = f.get("field_sources") or {}
    if isinstance(fs, str):
        fs = json.loads(fs) if fs else {}
    fs[field] = source
    f["field_sources"] = fs


def empty(v):
    return v is None or (isinstance(v, str) and not v.strip())


def papers_table():
    with open(BASE / "catalogue_papers.csv", newline="", encoding="utf-8") as fh:
        return {p["paper_id"]: p for p in csv.DictReader(fh)}


# ── C0: deterministic pre-fill from the compendium and studies.jsonl ─────────
SEQ_ASSAYS = {"16S rRNA amplicon sequencing", "ITS amplicon sequencing", "18S rRNA amplicon sequencing",
              "amplicon sequencing", "shotgun metagenomic sequencing", "metatranscriptomics",
              "whole genome sequencing", "sequencing (unspecified)"}


def prep(args):
    out = GD / "C0_prefill"
    recs = G.load_records(BASE)
    papers = papers_table()
    proj = {}
    with open(G.REPO_ROOT / "data/168000-samples-paper/projects.csv", newline="", encoding="utf-8-sig") as fh:
        for p in csv.DictReader(fh):
            proj[p["project"].strip()] = p
    studies = {json.loads(l)["paper_id"]: json.loads(l)
               for l in open(G.REPO_ROOT / "pipelines/corpus_v2/data/studies.jsonl", encoding="utf-8")}
    n = Counter()
    by_paper = defaultdict(list)
    for r in recs:
        by_paper[r["paper_id"]].append(r)
    for pid, rs in by_paper.items():
        bp = papers.get(pid, {}).get("bioproject", "").strip()
        comp = proj.get(bp)
        st = studies.get(pid, {})
        seq = [r for r in rs if r["entity_type"] == "assays"
               and r["fields"].get("assay_type_normalized") in SEQ_ASSAYS]
        # compendium: amplicon region and kit for the paper's 16S assays (project-level facts)
        if comp:
            for r in seq:
                f = r["fields"]
                if f.get("assay_type_normalized") != "16S rRNA amplicon sequencing":
                    continue
                amp = (comp.get("amplicon") or "").strip()
                if amp and amp.lower() not in ("na", "unknown") and empty(f.get("target_gene_or_region")):
                    note_change(f, "target_gene_or_region", "", f"16S rRNA {amp.upper()}", "compendium_projects_csv")
                    f["target_gene_or_region"] = f"16S rRNA {amp.upper()}"
                    n["compendium.target_gene_or_region"] += 1
                kit = (comp.get("kit") or "").strip()
                if kit and empty(f.get("dna_extraction_method")):
                    note_change(f, "dna_extraction_method", "", kit, "compendium_projects_csv")
                    f["dna_extraction_method"] = kit
                    n["compendium.dna_extraction_method"] += 1
        # studies.jsonl: a single sequencing assay in the paper takes the study-level platform
        plat = st.get("sequencing_platform")
        plat = plat if isinstance(plat, str) else ""
        if plat and plat.upper() not in MISSING and len(seq) == 1 and empty(seq[0]["fields"].get("sequencing_platform")):
            note_change(seq[0]["fields"], "sequencing_platform", "", plat, "corpus_studies_jsonl")
            seq[0]["fields"]["sequencing_platform"] = plat
            n["studies.sequencing_platform"] += 1
    save_catalogue(out, recs, BASE)
    (out / "_prep_report.json").write_text(json.dumps(dict(n), indent=2) + "\n")
    print(json.dumps(dict(n), indent=1))


# ── blocks of paper text (shared by G1, G8) ──────────────────────────────────
SKIP_SECTIONS = re.compile(r"reference|bibliograph|acknowledg|author contribution|conflict|competing|"
                           r"funding|declaration|consent|abbreviation", re.I)


@lru_cache(maxsize=None)
def paper_blocks(pid, limit=12000, include_all=False):
    """Concatenate a paper's body sections into <=limit-char blocks with headers."""
    secs = [(sid, path, text) for sid, path, text in G.paper_sections(pid)
            if text.strip() and (include_all or not SKIP_SECTIONS.search(path or ""))]
    blocks, cur, size = [], [], 0
    for sid, path, text in secs:
        for a, b in G.chunk_text(text, limit):
            piece = text[a:b]
            if cur and size + len(piece) > limit:
                blocks.append(cur)
                cur, size = [], 0
            cur.append((sid, path, piece))
            size += len(piece)
    if cur:
        blocks.append(cur)
    return blocks


def block_text(pid, block, i, n):
    parts = [f"PAPER {pid} — passage {i + 1} of {n}"]
    for sid, path, piece in block:
        parts.append(f"\n=== SECTION {sid}: {path} ===\n{piece}")
    return "\n".join(parts)


# ── G1: field completion with NOT_REPORTED ───────────────────────────────────
G1_FIELDS = {
    "cohorts": ["country_or_region", "participant_count", "age_summary", "sex_or_gender_reporting",
                "health_status", "inclusion_criteria", "exclusion_criteria"],
    "samples": ["collection_method", "collection_timepoint", "storage_condition", "preservation_method",
                "sample_count"],
    "datasets": ["repository_name", "repository_accession", "data_availability_status", "access_conditions"],
    "assays_seq": ["sequencing_platform", "target_gene_or_region", "primer_or_probe", "dna_extraction_method",
                   "library_preparation", "bioinformatics_pipeline", "taxonomic_database"],
    "assays_pcr": ["primer_or_probe", "dna_extraction_method"],
    "assays_comp": ["software_tools", "statistical_methods"],
}
COUNT_FIELDS = {"participant_count", "sample_count"}
# A quote existing is not enough: the value must be the right KIND of thing and
# be supported by the quote. Smoke test (2 papers) showed e.g. PUBLIC taken from
# a Creative Commons notice and "16S rRNA sequencing" given as a platform.
FIELD_PATTERNS = {
    "sequencing_platform": r"illumina|miseq|hiseq|novaseq|nextseq|iseq|ion (torrent|s5|pgm)|pacbio|sequel|nanopore|"
                           r"minion|gridion|promethion|454|gs ?flx|bgiseq|dnbseq|mgiseq|sanger|abi ",
    "target_gene_or_region": r"16s|18s|\bits\d?\b|\bv\d|region|gene|rrna|rdna",
    "primer_or_probe": r"\b\d{3,4}\s?[fr]\b|5['′]|primer|probe|[acgtrykmswbdhvn]{15,}",
    "dna_extraction_method": r"kit|extract|qiagen|qiaamp|mo ?bio|powersoil|powerfecal|zymo|phenol|chloroform|"
                             r"bead|lysis|chemagic|maxwell|omega|mag",
    "library_preparation": r"librar|nextera|truseq|kit|tagment|adapter|barcod|index",
    "bioinformatics_pipeline": r"qiime|dada2|mothur|usearch|vsearch|uparse|unoise|deblur|kraken|bracken|metaphlan|"
                               r"humann|lotus|ng-tax|pipeline|trimmomatic|cutadapt|kneaddata|picrust",
    "taxonomic_database": r"silva|greengenes|\brdp\b|ncbi|gtdb|unite|ezbio|homd|refseq|genbank|database",
    "statistical_methods": r"test|regression|anova|permanova|adonis|wilcoxon|mann|kruskal|t-test|lefse|deseq|"
                           r"edger|maaslin|ancom|model|correlat|spearman|pearson|fisher|chi|random forest|bonferroni|fdr",
    "storage_condition": r"°|º|-\s?\d{2}|freez|frozen|room temperature|refrigerat|ice|stored|kept",
    "preservation_method": r"rnalater|ethanol|omnigene|buffer|stabili|frozen|freez|glycerol|dry ice|preserv",
    "collection_timepoint": r"day|week|month|year|baseline|visit|hour|time|before|after|pre|post|onset|birth|age",
    "collection_method": r"swab|collect|kit|tube|container|self|biops|aspirat|brush|catcher|sampl",
    "repository_name": r"\bsra\b|\bena\b|ncbi|geo\b|bioproject|ddbj|qiita|mg-?rast|zenodo|figshare|github|dryad|"
                       r"metabolights|\bega\b|dbgap|\bgsa\b|archive|repository|mendeley|massive|pride",
}
AVAIL_PATTERNS = {
    "PUBLIC": r"deposit|available (at|in|from|under|on|through|via)|accession|repository|archive|bioproject|"
              r"\bsra\b|\bena\b|\bgeo\b|prj[nde]|zenodo|figshare|github",
    "UPON_REQUEST": r"request",
    "CONTROLLED": r"controlled|restricted|dbgap|\bega\b|application|data access committee|agreement",
    "NOT_DEPOSITED": r"not (been )?(be )?(deposited|available|publicly|shared)|cannot be (shared|deposited)",
    "LINK_ONLY": r"https?://|www\.",
    "EMBARGOED": r"embargo",
}


# The QUOTE must be about the right thing, too (sample of 12 accepted fills
# after the full run: country from an author affiliation, "23 persons" as a
# sample count, "processed and stored" as a storage condition).
QUOTE_REQUIRES = {
    "sample_count": r"sample|specimen|swab|biops|stool|fec|faec|aspirat|collected",
    "participant_count": r"participant|subject|patient|individual|volunteer|child|infant|adult|women|men|people|"
                         r"donor|case|control|enrol|recruit|cohort|pair|mother",
    "storage_condition": r"°|º|−\s?\d{2}|-\s?\d{2}\s?°?c|freez|frozen|room temperature|refrigerat|liquid nitrogen|dry ice|4\s?°",
    "inclusion_criteria": r"inclu|eligib|criteri|enrol|recruit|aged|age of|diagnos",
    "exclusion_criteria": r"exclu|not eligible|were not included|criteri",
    "collection_method": r"collect|swab|biops|kit|tube|container|catcher|aspirat|brush|self-",
    "age_summary": r"\bage|aged|year|month|week|day|old|median|mean|±|range",
    "access_conditions": r"access|request|restrict|controlled|data use|agreement|application|embargo",
}
AFFILIATION = re.compile(r"universit|department|faculty|institute|hospital,|medical center|school of|"
                         r"\b\d{5}\b|e-?mail|correspond|@", re.I)


def value_supported(fld, val, quote):
    """Field-specific check that the quote supports the value."""
    q, v = quote.lower(), str(val).lower()
    req = QUOTE_REQUIRES.get(fld)
    if req and not re.search(req, q):
        return False
    if fld == "country_or_region" and AFFILIATION.search(quote):
        return False  # author affiliations are not where the study took place
    if fld == "storage_condition":
        return bool(re.search(QUOTE_REQUIRES["storage_condition"], v))
    if fld == "age_summary" and re.fullmatch(r"\s*(19|20)\d{2}\s*", v):
        return False  # a bare year is not an age
    if fld == "data_availability_status":
        pat = AVAIL_PATTERNS.get(str(val).upper())
        if str(val).upper() == "PUBLIC" and re.search(r"creative ?commons|licen[cs]e|copyright|open access", q):
            return False  # licence notices are not data-availability statements
        return bool(pat and re.search(pat, q))
    if fld == "repository_accession":
        import clean_catalogue as cc
        ids = cc.find_accessions(str(val))
        return bool(ids) and all(a.lower() in q for _, a in ids)
    pat = FIELD_PATTERNS.get(fld)
    if pat and not re.search(pat, v):
        return False
    toks = [t for t in re.findall(r"[a-z0-9]+", v) if len(t) > 1]
    return bool(toks) and sum(t in q for t in toks) / len(toks) >= 0.6
G1_SYSTEM = """You complete records of a human-microbiome data catalogue from ONE passage of a paper.
For each ITEM (a record already extracted from this paper) and each of its listed empty_fields,
report the value ONLY if this passage states it for THAT record.

RULES
1. Copy a verbatim quote (<=300 characters) from the passage that states the value.
2. Never infer, compute or generalise. If the passage does not state it for that record, omit it.
3. Counts must be integers written in the quote.
4. data_availability_status must be one of PUBLIC, CONTROLLED, EMBARGOED, UPON_REQUEST, NOT_DEPOSITED, LINK_ONLY.
5. Return ONLY JSON: {"fills": [{"id": "...", "field": "...", "value": "...", "quote": "..."}]}.
   Return {"fills": []} if nothing in this passage applies."""


def g1_group(r):
    e, f = r["entity_type"], r["fields"]
    if e != "assays":
        return e if e in G1_FIELDS else None
    t = f.get("assay_type_normalized") or ""
    if t in SEQ_ASSAYS:
        return "assays_seq"
    if t in ("quantitative PCR", "PCR"):
        return "assays_pcr"
    if f.get("assay_class") == "COMPUTATIONAL":
        return "assays_comp"
    return None


def build_G1(src=GD / "C0_prefill"):
    import link_catalogue as lc
    recs = G.load_records(src)
    by = defaultdict(lambda: defaultdict(list))
    for r in recs:
        g = g1_group(r)
        if not g:
            continue
        miss = [fld for fld in G1_FIELDS[g] if empty(r["fields"].get(fld))]
        if miss:
            by[r["paper_id"]][g].append({"id": G.rec_id(r),
                                         "record": lc._clip(lc.summarise(r["entity_type"], r["fields"]), 200),
                                         "empty_fields": miss})
    reqs = []
    for pid in sorted(by):
        blocks = paper_blocks(pid)
        for i, b in enumerate(blocks):
            prefix = block_text(pid, b, i, len(blocks))
            for g, items in sorted(by[pid].items()):
                for j in range(0, len(items), 15):
                    reqs.append(G.Request(key=f"G1|{pid}|{g}|{i}|{j}", system=G1_SYSTEM, prefix=prefix,
                                          items=items[j:j + 15], suffix="Answer for these items only.",
                                          max_tokens=2048,
                                          meta={"paper": pid, "group": g, "block": i, "nblocks": len(blocks)}))
    return reqs


def apply_G1(src=GD / "C0_prefill", out=GD / "G1" / "catalogue"):
    recs = G.load_records(src)
    res, failed = G.load_results(stage_dir("G1"))
    reqs = build_G1(src)
    byid = {G.rec_id(r): r for r in recs}
    block_of = {}
    for rq in reqs:
        block_of[rq.key] = rq
    # which (paper, group) had every block answered -> NOT_REPORTED allowed
    complete = defaultdict(lambda: True)
    for rq in reqs:
        if rq.key not in res:
            complete[(rq.meta["paper"], rq.meta["group"])] = False
    stats = Counter()
    found = {}  # (id, field) -> (value, sid, a, b, slice)
    proposed = set()
    for key, ans in res.items():
        rq = block_of.get(key)
        if rq is None:
            continue
        pid = rq.meta["paper"]
        blocks = paper_blocks(pid)
        block = blocks[rq.meta["block"]]
        ok_ids = {it["id"]: set(it["empty_fields"]) for it in rq.items}
        for fill in G.flatten(ans, "fills"):
            rid, fld = str(fill.get("id")), str(fill.get("field"))
            val, quote = str(fill.get("value") or "").strip(), str(fill.get("quote") or "")
            if val and val.upper() not in MISSING:
                proposed.add((rid, fld))  # something was said: never NOT_REPORTED
            if rid not in ok_ids or fld not in ok_ids[rid] or not val or val.upper() in MISSING:
                stats["G1.rejected_shape"] += 1
                continue
            hit = None
            for sid, path, piece in block:
                h = G.anchor(quote, piece)
                if h:
                    hit = (sid, h)
                    break
            if not hit:
                stats["G1.rejected_quote_not_found"] += 1
                continue
            if fld in COUNT_FIELDS:
                if len(hit[1][2]) < 30 or not re.search(QUOTE_REQUIRES[fld], hit[1][2].lower()):
                    stats["G1.rejected_count_wrong_kind"] += 1
                    continue
                digits = re.sub(r"[,\s]", "", val)
                if not digits.isdigit() or digits not in re.sub(r"[,\s]", "", hit[1][2]):
                    stats["G1.rejected_count_not_in_quote"] += 1
                    continue
                val = int(digits)
            if fld == "data_availability_status":
                if val.upper() not in AVAIL_PATTERNS:
                    stats["G1.rejected_vocab"] += 1
                    continue
                val = val.upper()
            if fld not in COUNT_FIELDS and not value_supported(fld, val, hit[1][2]):
                stats["G1.rejected_value_not_supported"] += 1
                continue
            prev = found.get((rid, fld))
            if prev and str(prev[0]).lower() != str(val).lower():
                found[(rid, fld)] = ("CONFLICTING", None, None, None, f"{prev[0]} | {val}")
                continue
            found.setdefault((rid, fld), (val, hit[0], hit[1][0], hit[1][1], hit[1][2]))
    for (rid, fld), (val, sid, a, b, quote) in found.items():
        f = byid[rid]["fields"]
        note_change(f, fld, f.get(fld, ""), val, "G1_qwen")
        ev = f.get("gap_evidence") or {}
        ev[fld] = {"section_id": sid, "char_start": a, "char_end": b, "quote": quote} if sid else {"conflict": quote}
        f["gap_evidence"] = ev
        f[fld] = val
        stats["G1.filled" if val != "CONFLICTING" else "G1.conflicting"] += 1
    for r in recs:
        g = g1_group(r)
        if not g:
            continue
        for fld in G1_FIELDS[g]:
            if empty(r["fields"].get(fld)):
                if (G.rec_id(r), fld) in proposed:
                    stats["G1.left_blank_unverified_proposal"] += 1
                elif complete[(r["paper_id"], g)]:
                    r["fields"][fld] = "NOT_REPORTED"
                    note_change(r["fields"], fld, "", "NOT_REPORTED", "G1_checked_all_passages")
                    stats["G1.not_reported"] += 1
                else:
                    stats["G1.left_blank_incomplete"] += 1
    stats["G1.failed_requests"] = len(failed)
    apply_G2(recs, stats)
    save_catalogue(out, recs, src, extra_cols=("gap_evidence",))
    (out / "_G1_report.json").write_text(json.dumps(dict(stats), indent=2) + "\n")
    print(json.dumps(dict(stats), indent=1))


# ── G2: paper-level fields ───────────────────────────────────────────────────
DOMAINS = ["GUT", "ORAL", "SKIN", "VAGINAL_UROGENITAL", "RESPIRATORY", "BLOOD_SYSTEMIC", "MILK",
           "MULTI_SITE", "METHODS_TECHNICAL", "NON_HUMAN", "OTHER"]
DESIGNS = ["CROSS_SECTIONAL", "CASE_CONTROL", "PROSPECTIVE_COHORT", "RETROSPECTIVE_COHORT", "RCT",
           "NON_RANDOMIZED_INTERVENTION", "CASE_REPORT_OR_SERIES", "METHODOLOGICAL", "IN_VITRO_OR_ANIMAL",
           "REVIEW_OR_META_ANALYSIS", "OTHER"]
G2_SYSTEM = f"""You classify ONE paper for a human-microbiome data catalogue from its abstract and methods.
Return ONLY JSON:
{{"keywords": [...], "keywords_quote": "...",
  "primary_research_domain": one of {DOMAINS}, "domain_quote": "...",
  "human_study_design": one of {DESIGNS}, "design_quote": "...",
  "data_availability_status": one of PUBLIC|CONTROLLED|UPON_REQUEST|NOT_DEPOSITED|LINK_ONLY|NOT_REPORTED,
  "availability_quote": "..."}}
RULES: keywords ONLY if the text has an explicit keywords line (else []). Every quote is copied verbatim
from the text (<=300 chars) and supports the value. Use NOT_REPORTED for availability only if no
data-availability statement is in the text."""


def build_G2():
    papers = papers_table()
    reqs = []
    for pid in sorted(papers):
        p = papers[pid]
        secs = G.paper_sections(pid)
        avail = [t for _, path, t in secs if re.search(r"data avail|data access|accession|availability", path, re.I)]
        meth = [t for _, path, t in secs if re.search(r"method|material", path, re.I)]
        abstract = (p.get("abstract") or "")[:4000]
        text = (f"TITLE: {p.get('title', '')}\n\nABSTRACT: {abstract}\n\n"
                + "".join(f"\n=== {s[0]} ===\n{s[2][:4000]}" for s in secs if re.search(r"keyword", s[1], re.I))
                + "\n\n=== METHODS (start) ===\n" + (meth[0][:5000] if meth else "")
                + "\n\n=== DATA AVAILABILITY ===\n" + "\n".join(a[:2500] for a in avail[:2]))
        reqs.append(G.Request(key=f"G2|{pid}", system=G2_SYSTEM, prefix=text, items=[{"id": pid}],
                              suffix="Classify this paper.", max_tokens=800, meta={"paper": pid}))
    return reqs


def apply_G2(recs, stats):
    res, _ = G.load_results(stage_dir("G2"))
    papers = papers_table()
    out = []
    for pid, p in papers.items():
        a = res.get(f"G2|{pid}") or {}
        blob = (p.get("title", "") + " " + (p.get("abstract") or "") + " "
                + " ".join(t for _, _, t in G.paper_sections(pid)))
        row = {"paper_id": pid}

        def q_ok(q):
            return bool(q) and G.anchor(q, blob) is not None

        kw = a.get("keywords") if isinstance(a.get("keywords"), list) else []
        row["keywords"] = "; ".join(str(k) for k in kw) if kw and q_ok(a.get("keywords_quote")) else ""
        row["primary_research_domain"] = a.get("primary_research_domain") if (
            a.get("primary_research_domain") in DOMAINS and q_ok(a.get("domain_quote"))) else ""
        row["human_study_design"] = a.get("human_study_design") if (
            a.get("human_study_design") in DESIGNS and q_ok(a.get("design_quote"))) else ""
        av = a.get("data_availability_status")
        row["data_availability_status"] = av if av == "NOT_REPORTED" or (
            av in {"PUBLIC", "CONTROLLED", "UPON_REQUEST", "NOT_DEPOSITED", "LINK_ONLY"}
            and q_ok(a.get("availability_quote"))) else ""
        for k in ("keywords", "primary_research_domain", "human_study_design", "data_availability_status"):
            stats[f"G2.{k}_filled"] += bool(row[k])
        out.append(row)
    G.write_jsonl(GD / "G2" / "paper_fields.jsonl", out)


# ── G3: verify-and-repair (Gemma) and G3B tie-break (Llama) ─────────────────
DATA_FIELDS = {
    "datasets": ["dataset_title", "dataset_description", "dataset_type", "dataset_role", "repository_name",
                 "repository_accession", "dataset_url", "data_availability_status", "original_or_reused"],
    "data_assets": ["asset_name", "asset_type", "format", "description", "repository_url", "accession"],
    "cohorts": ["cohort_label", "cohort_role", "population_description", "country_or_region", "participant_count",
                "sample_count", "age_summary", "sex_or_gender_reporting", "health_status"],
    "samples": ["body_site", "sample_type", "collection_method", "collection_timepoint", "storage_condition",
                "sample_count"],
    "assays": ["assay_type", "target_gene_or_region", "sequencing_platform", "primer_or_probe",
               "dna_extraction_method", "bioinformatics_pipeline", "software_tools", "statistical_methods"],
    "findings": ["taxon_or_feature", "direction", "outcome", "comparison_or_exposure", "body_site",
                 "effect_measure", "effect_estimate", "p_value"],
}
INVALID = ["TABLE_OR_FIGURE_TEXT", "METHODS_TEXT_NOT_A_RECORD", "CITED_OTHER_STUDY", "REAGENT_OR_FILE",
           "WRONG_ENTITY_TYPE", "EMPTY_OR_MEANINGLESS"]
DIRS = ["INCREASE", "DECREASE", "NO_ASSOCIATION", "MIXED", "NOT_STATED"]
G3_SYSTEM = f"""You audit records machine-extracted from human-microbiome papers. Each ITEM has the
record type, its values, and the source text around its evidence. Judge every item:

- "valid": false if the item is not a real record of its type in THIS paper. Reason, one of {INVALID}:
  table rows, figure legends or axis text; methods prose that is not a dataset/cohort/sample/assay;
  a cohort/finding/assay of another study the paper only cites; a reagent, kit, figure or file listed as a
  dataset; a record of the wrong type (e.g. a population listed as a data asset); empty or meaningless.
- "fixes": for a VALID item, fields whose value is wrong for this record. action "CLEAR" (the field holds the
  wrong kind of thing, e.g. sample_type "microbiota", target_gene_or_region "OTUs", a group n as sample_count)
  or "SET" with the correct value and a verbatim quote from the source text.
- For findings only: "primary" = YES if it is a result of THIS paper's own data, NO if it reports prior
  literature or another study; "direction" one of {DIRS} as the text states it.
Return ONLY JSON: {{"results": [{{"id": "...", "valid": true, "reason": "", "fixes":
[{{"field": "...", "action": "CLEAR|SET", "value": "", "quote": ""}}], "primary": "YES|NO|UNSURE",
"direction": "..."}}]}}. One entry per item."""
G3B_SYSTEM = f"""You check machine-extracted records from human-microbiome papers. For each ITEM decide:
"valid": false if it is not a real record of its type in THIS paper (table text, figure legend, methods prose,
another study's cohort/result that is only cited, a reagent or file as a dataset, wrong type, empty), else true;
for findings also "primary" (YES = this paper's own result, NO = cited/background) and "direction"
(one of {DIRS}, as stated in the text).
Return ONLY JSON: {{"results": [{{"id": "...", "valid": true, "primary": "YES|NO|UNSURE", "direction": "..."}}]}}."""


def g3_item(r, sec_texts, window=1000):
    f = r["fields"]
    vals = {k: str(f.get(k))[:200] for k in DATA_FIELDS[r["entity_type"]]
            if not empty(f.get(k)) and str(f.get(k)) not in MISSING}
    text = sec_texts.get((r["paper_id"], r.get("section_id")), ("", ""))[1]
    cs = r.get("char_start")
    if isinstance(cs, int) and text:
        lo, hi = max(0, cs - window), min(len(text), (r.get("char_end") or cs) + window)
    else:
        lo, hi = 0, min(len(text), 2 * window)
    return {"id": G.rec_id(r), "type": r["entity_type"][:-1], "section": r.get("section_path", ""),
            "values": vals, "evidence": str(f.get("evidence_text", ""))[:300],
            "source_text": " ".join(text[lo:hi].split())}


def build_G3(src=GD / "G1" / "catalogue", stage="G3", only=None):
    if not Path(src).exists():  # smoke tests before G1 has been applied
        src = GD / "C0_prefill"
    recs = G.load_records(src)
    sec = G.sections()
    items = [g3_item(r, sec) for r in recs
             if r["fields"].get("record_source") != "corpus_bioproject_link"
             and (only is None or G.rec_id(r) in only)]
    items.sort(key=lambda it: it["id"])
    system = G3_SYSTEM if stage == "G3" else G3B_SYSTEM
    return [G.Request(key=f"{stage}|{items[j]['id']}", system=system, prefix="Audit these records.",
                      items=items[j:j + 8], suffix="One result per item.", max_tokens=3000)
            for j in range(0, len(items), 8)]


def g3_flagged(src=GD / "G1" / "catalogue"):
    """Items G3B must re-check: Gemma said invalid, or changes primary/direction."""
    res, _ = G.load_results(stage_dir("G3"))
    if not Path(src).exists():
        src = GD / "C0_prefill"
    recs = {G.rec_id(r): r for r in G.load_records(src)}
    flagged = set()
    for ans in res.values():
        for x in G.flatten(ans, "results"):
            rid = str(x.get("id"))
            r = recs.get(rid)
            if not r:
                continue
            f = r["fields"]
            if x.get("valid") is False:
                flagged.add(rid)
            if r["entity_type"] == "findings":
                if x.get("primary") in ("YES", "NO") and x["primary"] != f.get("is_primary_finding"):
                    flagged.add(rid)
                if x.get("direction") in DIRS and x["direction"] != f.get("direction"):
                    flagged.add(rid)
    return flagged


def apply_G3(src=GD / "G1" / "catalogue", out=GD / "G3" / "catalogue"):
    recs = G.load_records(src)
    byid = {G.rec_id(r): r for r in recs}
    sec = G.sections()
    a_res, a_fail = G.load_results(stage_dir("G3"))
    b_res, _ = G.load_results(stage_dir("G3B"))
    A = {str(x.get("id")): x for ans in a_res.values() for x in G.flatten(ans, "results")}
    B = {str(x.get("id")): x for ans in b_res.values() for x in G.flatten(ans, "results")}
    stats = Counter()
    removed, kept = [], []
    for r in recs:
        rid, f, e = G.rec_id(r), r["fields"], r["entity_type"]
        a, b = A.get(rid), B.get(rid)
        if a is None:
            stats["G3.no_answer"] += 1
            kept.append(r)
            continue
        if a.get("valid") is False and b is not None and b.get("valid") is False:
            reason = a.get("reason") if a.get("reason") in INVALID else "INVALID"
            f["v3_status"] = f"REMOVED:G3_{reason}"
            removed.append(r)
            stats[f"G3.removed.{reason}"] += 1
            continue
        if a.get("valid") is False:
            stats["G3.invalid_not_confirmed"] += 1
        text = sec.get((r["paper_id"], r.get("section_id")), ("", ""))[1]
        for fx in a.get("fixes") or []:
            fld = fx.get("field")
            if fld not in DATA_FIELDS[e] or fld in ("direction",) or empty(f.get(fld)):
                continue
            if fx.get("action") == "CLEAR":
                note_change(f, fld, f.get(fld), "", "G3_gemma_clear")
                f[fld] = ""
                stats["G3.field_cleared"] += 1
            elif fx.get("action") == "SET" and fx.get("value"):
                hit = G.anchor(fx.get("quote"), text)
                if hit and str(fx["value"]).lower() in hit[2].lower():
                    note_change(f, fld, f.get(fld), fx["value"], "G3_gemma_set")
                    f[fld] = fx["value"]
                    stats["G3.field_set"] += 1
                else:
                    stats["G3.set_rejected_no_quote"] += 1
        if e == "findings":
            for fld, key, ok in (("is_primary_finding", "primary", ("YES", "NO")), ("direction", "direction", DIRS)):
                va, vb = a.get(key), (b or {}).get(key)
                if va in ok and va != f.get(fld):
                    if vb == va:
                        note_change(f, fld, f.get(fld), va, "G3_gemma+llama")
                        f[fld] = va
                        if fld == "is_primary_finding":
                            f["is_primary_finding_source"] = "G3"
                        stats[f"G3.{fld}_changed"] += 1
                    else:
                        stats[f"G3.{fld}_disagreement_kept"] += 1
        kept.append(r)
    save_catalogue(out, kept, src, extra_cols=("gap_evidence",))
    with open(out / "_removed.jsonl", "a", encoding="utf-8") as fh:
        for r in removed:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    status = {G.rec_id(r): r["fields"]["v3_status"] for r in removed}
    with open(src / "_v2_to_v3_map.csv", newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    for row in rows[1:]:
        if row[2] in status:
            row[3] = status[row[2]]
    with open(out / "_v2_to_v3_map.csv", "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)
    stats["G3.failed_requests"] = len(a_fail)
    stats["G3.kept"] = len(kept)
    (out / "_G3_report.json").write_text(json.dumps(dict(stats), indent=2) + "\n")
    print(json.dumps(dict(stats), indent=1))


# ── G5: interventions ────────────────────────────────────────────────────────
INTERVENTIONS = ["DIET_OR_FIBRE", "PROBIOTIC", "PREBIOTIC_OR_SYNBIOTIC", "ANTIBIOTIC", "OTHER_DRUG",
                 "FECAL_MICROBIOTA_TRANSPLANT", "SURGERY_OR_PROCEDURE", "VACCINE", "EXERCISE_OR_LIFESTYLE",
                 "INFECTION_OR_DISEASE_STATE", "ENVIRONMENT_OR_GEOGRAPHY", "AGE_OR_DEVELOPMENT",
                 "SEX_OR_GENETICS", "METHOD_OR_TECHNICAL", "NOT_AN_INTERVENTION"]
G5_SYSTEM = f"""You classify the exposure or comparison of findings from human-microbiome papers.
For each ITEM (a text string) give "category", one of {INTERVENTIONS}, and "agent": the named
compound, drug, probiotic strain, food or procedure if the string names one (else "").
Return ONLY JSON: {{"results": [{{"id": "...", "category": "...", "agent": "..."}}]}}."""


def g5_strings():
    recs = G.load_records(BASE)
    strs = Counter(str(r["fields"].get("comparison_or_exposure") or "").strip()
                   for r in recs if r["entity_type"] == "findings")
    for l in open(G.REPO_ROOT / "pipelines/corpus_v2/data/studies.jsonl", encoding="utf-8"):
        v = json.loads(l).get("exposures_interventions")
        for s in (v if isinstance(v, list) else [v]):
            if isinstance(s, str):
                strs[s.strip()] += 1
            elif isinstance(s, dict):
                strs[str(s.get("value") or s.get("text") or "").strip()] += 1
    return sorted(s for s in strs if s and s.upper() not in MISSING)


def build_G5():
    strs = g5_strings()
    items = [{"id": f"S{i:06d}", "text": s[:200]} for i, s in enumerate(strs)]
    return [G.Request(key=f"G5|{j}", system=G5_SYSTEM, prefix="Classify these exposures.",
                      items=items[j:j + 40], suffix="One result per item.", max_tokens=3000)
            for j in range(0, len(items), 40)]


def g5_lookup():
    strs = g5_strings()
    res, _ = G.load_results(stage_dir("G5"))
    by = {str(x.get("id")): x for ans in res.values() for x in G.flatten(ans, "results")}
    out = {}
    for i, s in enumerate(strs):
        x = by.get(f"S{i:06d}")
        if x and x.get("category") in INTERVENTIONS:
            out[s] = (x["category"], str(x.get("agent") or "")[:120])
    return out


# ── G6/G7 candidates come from gap_embed.py; G6/G7 adjudication ──────────────
G6_SYSTEM = """You link entity labels from knowledge triples (human-microbiome papers) to canonical terms.
For each ITEM choose the candidate term_id that denotes the SAME concept as "label" (same entity, not a
broader or related one), or "NONE". Return ONLY JSON: {"results": [{"id": "...", "term_id": "...|NONE"}]}."""
CDM_TYPES = ["ORGANISM", "PROTEIN", "CHEMICAL", "DISEASE", "DNA_RNA", "CELL_TYPE", "SAMPLE_METHOD", "LAB_METHOD",
             "DATA_ANALYSIS", "PATHWAY", "EXPERIMENTAL_METHOD", "STUDY_DESIGN", "GENOMICS", "CLINICAL"]
G7_SYSTEM = f"""You assign entity types to terms from human-microbiome papers. For each ITEM give "type", one
of {CDM_TYPES} or "UNRESOLVED", the type that fits the term as used in its context.
If "candidates" are given, also pick the candidate term_id that is the SAME term (spelling/synonym), or "NONE".
Return ONLY JSON: {{"results": [{{"id": "...", "type": "...", "term_id": "...|NONE"}}]}}."""


def build_from_candidates(stage, fname, system, batch):
    p = stage_dir("E") / fname
    if not p.exists():
        sys.exit(f"missing {p}: run the E (embedding) job first")
    items = [json.loads(l) for l in open(p, encoding="utf-8")]
    return [G.Request(key=f"{stage}|{j}", system=system, prefix="Decide for these items.",
                      items=items[j:j + batch], suffix="One result per item.", max_tokens=3000)
            for j in range(0, len(items), batch)]


def apply_candidates(stage, fname, out_name):
    items = {json.loads(l)["id"]: json.loads(l) for l in open(stage_dir("E") / fname, encoding="utf-8")}
    res, failed = G.load_results(stage_dir(stage))
    rows, stats = [], Counter()
    for ans in res.values():
        for x in G.flatten(ans, "results"):
            it = items.get(str(x.get("id")))
            if not it:
                continue
            cand = {c["term_id"] for c in it.get("candidates") or []}
            tid = x.get("term_id")
            row = {"id": it["id"], **{k: v for k, v in it.items() if k != "candidates"}}
            row["term_id_llm"] = tid if tid in cand else ""
            if "type" in x:
                row["type_llm"] = x["type"] if x["type"] in CDM_TYPES or x["type"] == "UNRESOLVED" else ""
            stats["linked" if row["term_id_llm"] else "none"] += 1
            rows.append(row)
    G.write_jsonl(stage_dir(stage) / out_name, rows)
    stats["failed_requests"] = len(failed)
    (stage_dir(stage) / f"_{stage}_report.json").write_text(json.dumps(dict(stats), indent=2) + "\n")
    print(json.dumps(dict(stats), indent=1))


# ── G8: source-grounded definitions ──────────────────────────────────────────
G8_SYSTEM = """You extract definitions that a scientific paper itself states.
From the passage, list every term the authors explicitly DEFINE or EXPAND: abbreviation expansions
("short-chain fatty acids (SCFAs)"), explicit definitions ("X is defined as ...", "X, a ..., ..."),
glossary entries. Copy the defining text verbatim (<=300 chars). Do not add definitions from your own
knowledge. Return ONLY JSON: {"definitions": [{"term": "...", "kind": "ABBREVIATION_EXPANSION|EXPLICIT_AUTHOR_DEFINITION|GLOSSARY_DEFINITION", "quote": "..."}]}."""


def build_G8():
    papers = papers_table()
    reqs = []
    for pid in sorted(papers):
        blocks = paper_blocks(pid, limit=10000, include_all=True)
        for i, b in enumerate(blocks):
            reqs.append(G.Request(key=f"G8|{pid}|{i}", system=G8_SYSTEM, prefix=block_text(pid, b, i, len(blocks)),
                                  items=[{"id": f"{pid}|{i}"}], suffix="List the definitions in this passage.",
                                  max_tokens=3000, meta={"paper": pid, "block": i}))
    return reqs


def apply_G8():
    import clean_catalogue as cc
    res, failed = G.load_results(stage_dir("G8"))
    canon = {}
    for l in open(G.REPO_ROOT / "releases/frozen_output/02_data_catalogue/terminology/canonical_terms.jsonl",
                  encoding="utf-8"):
        t = json.loads(l)
        canon.setdefault(cc._norm_map(t["term"])[0], []).append(t["term_id"])
    rows, stats, seen = [], Counter(), set()
    reqs = {rq.key: rq for rq in build_G8()}
    for key, ans in res.items():
        rq = reqs.get(key)
        if not rq:
            continue
        pid = rq.meta["paper"]
        block = paper_blocks(pid, limit=10000, include_all=True)[rq.meta["block"]]
        for d in G.flatten(ans, "definitions"):
            term, quote = str(d.get("term") or "").strip(), str(d.get("quote") or "")
            hit = None
            for sid, _, piece in block:
                h = G.anchor(quote, piece, min_ratio=1.0)
                if h:
                    hit = (sid, h)
                    break
            if not term or not hit or term.lower() not in hit[1][2].lower():
                stats["rejected"] += 1
                continue
            full = G.sections()[(pid, hit[0])][1]
            off = full.find(hit[1][2])
            k = (pid, term.lower(), hit[1][2])
            if k in seen:
                continue
            seen.add(k)
            ids = canon.get(cc._norm_map(term)[0], [])
            rows.append({"paper_id": pid, "section_id": hit[0], "term": term, "canonical_term_ids": ids,
                         "definition_source": d.get("kind") if d.get("kind") in (
                             "ABBREVIATION_EXPANSION", "EXPLICIT_AUTHOR_DEFINITION", "GLOSSARY_DEFINITION")
                         else "EXPLICIT_AUTHOR_DEFINITION",
                         "definition_text": hit[1][2], "char_start": off if off >= 0 else None,
                         "char_end": off + len(hit[1][2]) if off >= 0 else None,
                         "provenance_class": "SOURCE_DERIVED", "extraction_method": "LLM_SPAN_EXTRACTION:qwen3.5-4b",
                         "review_status": "REVIEW_REQUIRED"})
            stats["kept"] += 1
            stats["linked_to_canonical"] += bool(ids)
    G.write_jsonl(stage_dir("G8") / "term_definitions_llm.jsonl", rows)
    stats["failed_requests"] = len(failed)
    stats["distinct_canonical_terms_defined"] = len({i for r in rows for i in r["canonical_term_ids"]})
    (stage_dir("G8") / "_G8_report.json").write_text(json.dumps(dict(stats), indent=2) + "\n")
    print(json.dumps(dict(stats), indent=1))


# ── G9: ontology-mapping adjudication ────────────────────────────────────────
MAPPINGS = G.REPO_ROOT / "releases/frozen_output/02_data_catalogue/terminology/mapping_guards_v2/mapping_remapped.jsonl"
G9_SYSTEM = """You audit ontology mappings for terms from human-microbiome papers. For each ITEM decide how the
concept relates to the term (as a term of the given type): EXACT (same concept), BROADER (concept is more
general), NARROWER (more specific), RELATED (associated but different), or WRONG (unrelated / wrong sense).
Return ONLY JSON: {"results": [{"id": "...", "relation": "EXACT|BROADER|NARROWER|RELATED|WRONG"}]}."""


def build_G9():
    items = []
    for l in open(MAPPINGS, encoding="utf-8"):
        m = json.loads(l)
        if not m.get("is_canonical_candidate"):
            continue
        items.append({"id": m["mapping_id"], "term": m["term"][:120], "type": m.get("cdm_type"),
                      "concept": str(m.get("concept_label") or "")[:120],
                      "source": m.get("source_service") or m.get("ontology_source")})
    items.sort(key=lambda x: x["id"])
    return [G.Request(key=f"G9|{items[j]['id']}", system=G9_SYSTEM, prefix="Audit these mappings.",
                      items=items[j:j + 30], suffix="One result per item.", max_tokens=2500)
            for j in range(0, len(items), 30)]


def apply_G9():
    res, failed = G.load_results(stage_dir("G9"))
    rel = {str(x.get("id")): x.get("relation") for ans in res.values() for x in G.flatten(ans, "results")}
    stats, rows = Counter(), []
    for l in open(MAPPINGS, encoding="utf-8"):
        m = json.loads(l)
        if not m.get("is_canonical_candidate"):
            continue
        r = rel.get(m["mapping_id"])
        r = r if r in ("EXACT", "BROADER", "NARROWER", "RELATED", "WRONG") else None
        disp = m.get("mapping_disposition")
        if r == "WRONG":
            disp = "REJECTED"
        elif r in ("BROADER", "NARROWER", "RELATED"):
            disp = "REVIEW_REQUIRED"
        rows.append({"mapping_id": m["mapping_id"], "term_id": m["term_id"], "concept_id": m.get("concept_id"),
                     "relation_llm": r, "mapping_relation_original": m.get("mapping_relation"),
                     "mapping_disposition_original": m.get("mapping_disposition"),
                     "mapping_disposition_after_g9": disp, "adjudicator": "gemma-4-E4B"})
        stats[f"relation.{r}"] += 1
    G.write_jsonl(stage_dir("G9") / "mapping_adjudication.jsonl", rows)
    stats["failed_requests"] = len(failed)
    (stage_dir("G9") / "_G9_report.json").write_text(json.dumps(dict(stats), indent=2) + "\n")
    print(json.dumps(dict(stats), indent=1))


# ── finalize: merge G5 into the relinked catalogue ───────────────────────────
# Data fields only: bookkeeping columns legitimately hold NOT_STATED / UNKNOWN
# (direction_original, finding_source, direction_llm) — 3.1.0 blanked them by mistake.
DATA_ONLY = {e: set(flds) - {"direction"} | set(G1_FIELDS.get(e, [])) for e, flds in DATA_FIELDS.items()}
DATA_ONLY["assays"] |= set(G1_FIELDS["assays_seq"] + G1_FIELDS["assays_comp"])


def finalize(args):
    src = GD / "G4" / "catalogue"
    out = R / "catalogue_v3_1_pre_vocab"
    recs = G.load_records(src)
    look = g5_lookup()
    n = Counter()
    # Repairs found by the v3.1 QA gate (first finalize run failed closed):
    import clean_catalogue as cc
    live = {G.rec_id(r) for r in recs}
    for r in recs:
        f = r["fields"]
        # 1. links to records that G3 removed
        for k in ("dataset_id", "cohort_id", "assay_id"):
            if k == G.ID_FIELD[r["entity_type"]] or empty(f.get(k)) or str(f[k]) in MISSING:
                continue
            ids = [i.strip() for i in str(f[k]).split(";") if i.strip()]
            keep = [i for i in ids if i in live]
            if keep != ids:
                note_change(f, k, f[k], "; ".join(keep), "finalize_drop_link_to_removed_record")
                f[k] = "; ".join(keep)
                n["links_to_removed_dropped"] += 1
        # 2. placeholders written by model fixes
        for k, v in list(f.items()):
            if isinstance(v, str) and v.strip() and v.strip() not in MISSING and k not in cc.VOCAB_KEEP \
                    and k in DATA_ONLY.get(r["entity_type"], ()) \
                    and v.strip().lower().strip(" .") in cc.PLACEHOLDERS - {"0"}:
                note_change(f, k, v, "", "finalize_placeholder_blanked")
                f[k] = ""
                n["placeholders_blanked"] += 1
        # 3. counts must be plain plausible integers; else revert to the pre-G3 value
        ch = f.get("gap_changes") or {}
        for k in COUNT_FIELDS:
            v = f.get(k)
            if empty(v) or str(v) in MISSING:
                continue
            ok = isinstance(v, int) or (isinstance(v, str) and v.strip().isdigit())
            lim = cc.PARTICIPANT_MAX if k == "participant_count" else cc.SAMPLE_MAX
            if ok and int(v) <= lim:
                f[k] = int(v)
                continue
            orig = (ch.get(k) or {}).get("original", "")
            orig_ok = isinstance(orig, int) or (isinstance(orig, str) and orig.strip().isdigit())
            new = int(orig) if orig_ok and int(orig) <= lim else ""
            note_change(f, k, v, new, "finalize_count_reverted")
            f[k] = new
            n["counts_reverted"] += 1
    for r in recs:
        if r["entity_type"] != "findings":
            continue
        s = str(r["fields"].get("comparison_or_exposure") or "").strip()
        cat, agent = look.get(s, ("", ""))
        r["fields"]["intervention_category"], r["fields"]["intervention_agent"] = cat, agent
        n["with_category" if cat else "without"] += 1
    pf = {json.loads(l)["paper_id"]: json.loads(l) for l in open(GD / "G2" / "paper_fields.jsonl", encoding="utf-8")}
    save_catalogue(out, recs, src, extra_cols=("gap_evidence", "intervention_category", "intervention_agent"))
    with open(src / "catalogue_papers.csv", newline="", encoding="utf-8") as fh:
        rd = csv.DictReader(fh)
        cols = list(rd.fieldnames) + [c for c in ("data_availability_status", "field_sources") if c not in rd.fieldnames]
        rows = list(rd)
    for p in rows:
        g2 = pf.get(p["paper_id"], {})
        src_map = {}
        for k in ("keywords", "primary_research_domain", "human_study_design", "data_availability_status"):
            if g2.get(k) and empty(p.get(k)):
                p[k] = g2[k]
                src_map[k] = "G2_qwen"
        p["field_sources"] = json.dumps(src_map) if src_map else ""
    with open(out / "catalogue_papers.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    (out / "_finalize_report.json").write_text(json.dumps(dict(n), indent=2) + "\n")
    print(json.dumps(dict(n), indent=1))


# ── G11: term taxonomy (terminology_taxonomy.json), two independent classifiers ──
TAXONOMY = G.REPO_ROOT / "releases/terminology/1.0.0/terminology_taxonomy.json"
CDM_DB = G.REPO_ROOT / "releases/cdm_v3/3.0.1/microbiome_cdm_v3.db"
G11_INPUT = GD / "G11" / "terms_input.jsonl"


@lru_cache(maxsize=1)
def taxonomy():
    t = json.loads(TAXONOMY.read_text())
    subs = {s["category_id"]: s for s in t["subcategories"]}
    return t, subs


def g11_system():
    t, subs = taxonomy()
    lines = []
    for u in t["upper_categories"]:
        lines.append(f"\n{u['category_id']}: {' '.join(u['category_definition'].split())} "
                     f"Excludes: {' '.join((u.get('exclusion_criteria') or '').split())}")
        for sid in u["subcategory_ids"]:
            sc = subs[sid]
            ex = ", ".join(sc.get("positive_examples") or [])
            lines.append(f"  - {sid}: {' '.join(sc['category_definition'].split())}" + (f" (e.g. {ex})" if ex else ""))
    return ("You classify scientific terms from human-microbiome papers into a fixed two-level taxonomy. "
            "For each ITEM choose the ONE subcategory id below that says what the term itself denotes, using the "
            "term, its entity type and its context sentence. Use \"UNCERTAIN\" when the term is not a scientific "
            "concept, is too generic, or fits no subcategory. Never invent ids.\n\nTAXONOMY:" + "\n".join(lines) +
            '\n\nReturn ONLY JSON: {"results": [{"id": "...", "sub": "<subcategory id or UNCERTAIN>"}]}')


def g11_input():
    """One row per live canonical term with one context sentence (a CDM 3.0.1 mention with the same term_norm)."""
    if G11_INPUT.exists():
        return [json.loads(l) for l in open(G11_INPUT, encoding="utf-8")]
    import sqlite3
    c = sqlite3.connect(f"file:{CDM_DB}?mode=ro", uri=True)
    ctx = {}
    for norm, surf, sent in c.execute("SELECT normalized_mention, surface_form, supporting_sentence FROM term_mention "
                                      "WHERE supporting_sentence IS NOT NULL"):
        if norm in ctx or not surf:
            continue
        sent = " ".join(sent.split())
        i = max(0, sent.find(surf))
        ctx[norm] = sent[max(0, i - 110):i + len(surf) + 110]
    rows = [{"id": f"t{n}", "term_id": tid, "term": term[:150], "type": typ, "context": ctx.get(norm, "")}
            for n, (tid, term, norm, typ) in enumerate(c.execute(
                "SELECT term_id, term, term_norm, cdm_type FROM canonical_term ORDER BY term_id"))]
    G.write_jsonl(G11_INPUT, rows)
    return rows


def build_G11(stage="G11", batch=40):
    items = [{k: r[k] for k in ("id", "term", "type", "context")} for r in g11_input()]
    system = g11_system()
    return [G.Request(key=f"{stage}|{j}", system=system, prefix="Classify these terms.",
                      items=items[j:j + batch], suffix="One result per item, same ids.", max_tokens=2500)
            for j in range(0, len(items), batch)]


def apply_G11():
    """Combine Qwen (G11) and Gemma (G11B): a category is assigned only where both agree."""
    t, subs = taxonomy()
    uppers = {u["category_id"] for u in t["upper_categories"]}
    valid = set(subs) | uppers | {"UNCERTAIN"}   # an upper-level id counts as a category-only vote
    parent = lambda x: subs[x]["parent_category_id"] if x in subs else (x if x in uppers else None)
    rows = g11_input()
    votes = {}
    failed = {}
    for stage in ("G11", "G11B"):
        res, failed[stage] = G.load_results(stage_dir(stage))
        v = {}
        for ans in res.values():
            for x in G.flatten(ans, "results"):
                sub = str(x.get("sub") or "").strip().upper()
                v[str(x.get("id"))] = sub if sub in valid else "INVALID"
        votes[stage] = v
    out, st = [], Counter()
    for r in rows:
        a, b = votes["G11"].get(r["id"], "MISSING"), votes["G11B"].get(r["id"], "MISSING")
        pa, pb = parent(a), parent(b)
        if a in subs and a == b:
            status, cat, sub = "AGREED", pa, a
        elif pa and pa == pb:
            status, cat, sub = "PARENT_AGREED", pa, ""
        elif a == b == "UNCERTAIN":
            status, cat, sub = "UNCERTAIN", "UNCERTAIN", ""
        elif pa and pb:
            status, cat, sub = "CONFLICTING", "", ""
        else:   # one model UNCERTAIN / missing / invalid
            status, cat, sub = "SINGLE_MODEL", "", ""
        st[status] += 1
        out.append({"term_id": r["term_id"], "taxonomy_version": f"{t['taxonomy_id']} {t['version']}",
                    "category": cat, "subcategory": sub, "agreement_status": status,
                    "sub_qwen": a, "sub_gemma": b, "classification_method": "G11 Qwen3.5-4B + G11B Gemma-4-E4B",
                    "review_status": "REVIEW_REQUIRED"})
    G.write_jsonl(stage_dir("G11") / "term_taxonomy.jsonl", out)
    by_cat = Counter(o["category"] for o in out if o["category"])
    rep = {"terms": len(out), "status": dict(st), "by_category": dict(by_cat.most_common()),
           "failed_requests": {k: len(v) for k, v in failed.items()},
           "agreement_pct_sub": round(100 * st["AGREED"] / max(1, len(out)), 1)}
    (stage_dir("G11") / "_G11_report.json").write_text(json.dumps(rep, indent=1) + "\n")
    print(json.dumps(rep, indent=1))


# ── CLI ──────────────────────────────────────────────────────────────────────
BUILD = {"G1": build_G1, "G2": build_G2, "G5": build_G5, "G8": build_G8, "G9": build_G9,
         "G3": lambda: build_G3(),
         "G3B": lambda: build_G3(stage="G3B", only=g3_flagged()),
         "G6": lambda: build_from_candidates("G6", "g6_candidates.jsonl", G6_SYSTEM, 20),
         "G7": lambda: build_from_candidates("G7", "g7_candidates.jsonl", G7_SYSTEM, 30),
         "G11": lambda: build_G11("G11"), "G11B": lambda: build_G11("G11B")}
APPLY = {"G1": lambda: apply_G1(), "G3": lambda: apply_G3(), "G8": apply_G8, "G9": apply_G9,
         "G6": lambda: apply_candidates("G6", "g6_candidates.jsonl", "triple_entity_links.jsonl"),
         "G7": lambda: apply_candidates("G7", "g7_candidates.jsonl", "type_harmonization.jsonl"),
         "G11": apply_G11}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "run", "apply", "prep", "finalize"])
    ap.add_argument("--stage")
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--nshards", type=int, default=1)
    ap.add_argument("--host", default="http://127.0.0.1:8000")
    ap.add_argument("--parallel", type=int, default=96)
    ap.add_argument("--limit_papers", type=int, default=0, help="smoke test: first N papers' requests only")
    args = ap.parse_args(argv)
    if args.cmd == "prep":
        return prep(args)
    if args.cmd == "finalize":
        return finalize(args)
    if args.cmd == "apply":
        return APPLY[args.stage]()
    reqs = BUILD[args.stage]()
    if args.limit_papers:
        keep = sorted({rq.meta.get("paper") or rq.key for rq in reqs})[:args.limit_papers]
        reqs = [rq for rq in reqs if (rq.meta.get("paper") or rq.key) in set(keep)]
    if args.cmd == "build":
        sizes = sorted(len(rq.user()) for rq in reqs)
        print(f"{args.stage}: {len(reqs)} requests, {sum(len(rq.items) for rq in reqs)} items, "
              f"prompt chars median {sizes[len(sizes) // 2] if sizes else 0} max {sizes[-1] if sizes else 0}")
        return 0
    mine = [rq for rq in reqs if G.shard_of(rq.key, args.nshards) == args.shard]
    log = G.log_to(stage_dir(args.stage) / f"run.shard{args.shard}.log")
    log(f"{args.stage} shard {args.shard}/{args.nshards}: {len(mine)} of {len(reqs)} requests")
    errors = G.run_requests(mine, stage_dir(args.stage) / f"responses.shard{args.shard}.jsonl",
                            args.host, STAGE_MODEL[args.stage], parallel=args.parallel, log=log)
    log(f"done, {errors} failed requests")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
