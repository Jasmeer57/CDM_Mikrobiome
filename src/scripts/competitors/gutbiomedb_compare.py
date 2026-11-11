"""GutBiomeDB (Zhai et al., NAR 2026, doi 10.1093/nar/gkag1125) vs the Microbiome-CDM study catalogue, per BioProject.

GutBiomeDB re-uses the Abdill et al. 2025 profiles for the same 482 BioProjects and adds manually curated disease,
life-stage, sex and country metadata. That makes it a curated reference for our study-level fields. We compare, for the
BioProjects present in both resources:
  - country: our LLM-from-text value (study_provenance llm value) and our released value (deterministic, compendium
    geo_loc_name) against GutBiomeDB's curated country / country_list (ISO 3166 alpha-2);
  - health conditions: our LLM-from-text phrases and our released value (compendium projects.csv condition) against
    GutBiomeDB's curated disease labels -- matched by the same local Qwen3.5-9B (task gbdb of competitor_llm_runner.py),
    both directions (coverage of their labels; support of our phrases);
  - sequencing platform (both sides ultimately SRA-derived; reported as a sanity check) and 16S region (GutBiomeDB marks
    its region as "(est.)", so this is concordance with an estimate, not with curation).
All numbers are agreement with GutBiomeDB, not accuracy: GutBiomeDB is curated but not a published gold standard with
inter-annotator agreement.

Stages:
  --fetch    download /api/project-list, /api/project-detail (each project, 1 req/s), /api/disease-display-names,
             /api/disease-ontology from https://gutbiomedb.online into outputs/scratch/competitors/gutbiomedb/data
             (+ MANIFEST); generic User-Agent.
  --prepare  write data/gbdb_condition_pairs.jsonl for the LLM matcher.
  --score    read llm_runs/gbdb/*.jsonl, write outputs/results/competitor_compare_2026-11-11/gutbiomedb/{SUMMARY.json,
             REPORT.md, per_project.csv}.
Run with the vllm venv python (pycountry). CDM 3.1.0 read-only.
Written with Claude Code (declare).
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _cstats import RESULTS, SCRATCH, dump, wilson, write_manifest  # noqa: E402

BASE = "https://gutbiomedb.online/api"
D = SCRATCH / "gutbiomedb/data"
OUT = RESULTS / "gutbiomedb"
DB310 = ROOT / "releases/cdm_v3/3.1.0/microbiome_cdm_v3.1.0.db"
UA = {"User-Agent": "cdm-compare/1.0"}
NONCOND = re.compile(r"^(healthy|health|control|controls|healthy controls?|none|not[_ ]reported|na|n/a|unknown|missing|normal|"
                     r"healthy volunteers?|healthy subjects?|healthy individuals?|healthy adults?|-|)$", re.I)


def get(path, params=None):
    u = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    for k in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=120) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            print("retry", u, repr(e)[:120], flush=True)
            time.sleep(5 * (k + 1))
    raise RuntimeError(u)


def fetch():
    D.mkdir(parents=True, exist_ok=True)
    pl = get("/project-list")
    dump(pl, D / "project_list.json")
    for name, path in (("disease_display_names", "/disease-display-names"), ("disease_ontology", "/disease-ontology"),
                       ("data_stats", "/data-stats")):
        dump(get(path), D / f"{name}.json")
    det = {}
    pd = D / "project_detail.jsonl"
    if pd.exists():
        det = {json.loads(l)["project_id"]: 1 for l in open(pd, encoding="utf-8")}
    with open(pd, "a", encoding="utf-8") as f:
        for p in pl["projects"]:
            if p["project_id"] in det:
                continue
            f.write(json.dumps(get("/project-detail", {"project_id": p["project_id"]}), ensure_ascii=False) + "\n")
            f.flush()
            time.sleep(1.0)
    write_manifest(D, "https://gutbiomedb.online/api (project-list, project-detail, disease-display-names, disease-ontology, data-stats)",
                   "Site JSON-LD declares MIT (https://opensource.org/licenses/MIT); article CC BY-NC 4.0",
                   f"retrieved {time.strftime('%Y-%m-%d')}", "Local comparison only; not redistributed.")
    print(len(pl["projects"]), "projects fetched")


def prov_llm(prov, field, value):
    """Our LLM-from-text value for a field: the value itself when the field came from the LLM, else the rejected LLM
    value recorded in study_provenance (None if the LLM gave nothing)."""
    p = (prov or {}).get(field) or {}
    if p.get("source") == "llm_section_text":
        return value
    return p.get("llm_value_rejected")


def cdm_studies():
    c = sqlite3.connect(f"file:{DB310}?mode=ro", uri=True)
    rows = {}
    for (pid, bp, cr, iso, hc, sp, tgr, prov) in c.execute(
            "SELECT paper_id, bioproject, country_region, country_iso_from_compendium, health_conditions, sequencing_platform, "
            "target_gene_region, study_provenance FROM study"):
        pv = json.loads(prov) if prov else {}
        rows.setdefault(bp, []).append({"paper_id": pid, "country_released": cr, "country_iso_released": iso,
                                        "country_llm": prov_llm(pv, "country_region", cr), "cond_released": hc,
                                        "cond_llm": prov_llm(pv, "health_conditions", hc), "platform_released": sp,
                                        "platform_llm": prov_llm(pv, "sequencing_platform", sp), "region": tgr,
                                        "region_llm": prov_llm(pv, "target_gene_region", tgr),
                                        "cond_source": (pv.get("health_conditions") or {}).get("source"),
                                        "country_source": (pv.get("country_region") or {}).get("source")})
    return rows


def phrases(s):
    if not s:
        return []
    out = []
    for x in re.split(r"[;,|/]| and |\n", s):
        x = " ".join(x.split()).strip(" .")
        if x and not NONCOND.match(x) and len(x) < 120:
            out.append(x)
    return list(dict.fromkeys(out))[:20]


def prepare():
    gb = {p["project_id"]: p for p in (json.loads(l) for l in open(D / "project_detail.jsonl", encoding="utf-8"))}
    disp = json.load(open(D / "disease_display_names.json"))
    disp = disp if isinstance(disp, dict) else {}
    onto = json.load(open(D / "disease_ontology.json"))
    ours = cdm_studies()
    n = 0
    with open(D / "gbdb_condition_pairs.jsonl", "w", encoding="utf-8") as f:
        for bp, recs in sorted(ours.items()):
            if bp not in gb:
                continue
            labels = [x for x in gb[bp].get("diseases", []) if not NONCOND.match(x) and "control" not in x.lower()
                      and (onto.get(x) or {}).get("category") != "Control"]
            labels = [f"{x} ({disp[x]})" if isinstance(disp.get(x), str) and disp[x].lower() != x.lower() else x for x in labels]
            for r in recs:
                for var in ("llm", "released"):
                    ph = phrases(r[f"cond_{var}"])
                    if not labels and not ph:
                        continue
                    f.write(json.dumps({"key": f"{bp}|{r['paper_id']}|{var}", "bioproject": bp, "paper_id": r["paper_id"], "variant": var,
                                        "gbdb_labels": labels, "cdm_phrases": ph}, ensure_ascii=False) + "\n")
                    n += 1
    print(n, "pairs written")


def iso_of(text):
    import pycountry
    if not text:
        return set()
    out = set()
    t = text.lower()
    special = {"usa": "US", "u.s.": "US", "united states": "US", "uk": "GB", "united kingdom": "GB", "england": "GB",
               "scotland": "GB", "wales": "GB", "south korea": "KR", "korea": "KR", "russia": "RU", "iran": "IR",
               "vietnam": "VN", "taiwan": "TW", "czech republic": "CZ", "the netherlands": "NL", "holland": "NL",
               "tanzania": "TZ", "bolivia": "BO", "venezuela": "VE", "hong kong": "HK", "laos": "LA", "syria": "SY",
               "ivory coast": "CI", "côte d'ivoire": "CI", "burkina faso": "BF", "democratic republic of the congo": "CD"}
    for k, v in special.items():
        if re.search(r"(?<![a-z])" + re.escape(k) + r"(?![a-z])", t):
            out.add(v)
    for c in pycountry.countries:
        for nm in {c.name, getattr(c, "common_name", c.name), getattr(c, "official_name", c.name)}:
            if len(nm) > 3 and re.search(r"(?<![a-z])" + re.escape(nm.lower()) + r"(?![a-z])", t):
                out.add(c.alpha_2)
    return out


def norm_platform(s):
    """Set of platform families named in s (a paper may name several, e.g. MiSeq for 16S and HiSeq for shotgun)."""
    s = (s or "").lower()
    out = set()
    for k in ("novaseq", "hiseq", "miseq", "nextseq", "iseq", "454", "ion torrent", "ion s5", "ion pgm", "pacbio", "pacific biosciences",
              "nanopore", "minion", "bgiseq", "dnbseq", "genome analyzer"):
        if k in s:
            out.add({"ion s5": "ion torrent", "ion pgm": "ion torrent", "dnbseq": "bgiseq", "minion": "nanopore",
                     "pacific biosciences": "pacbio"}.get(k, k))
    return frozenset(out) or None


def norm_region(s):
    s = (s or "").lower().replace(" ", "")
    m = re.findall(r"v(\d)", s)
    return "-".join(sorted(set(m))) if m else None


def score():
    OUT.mkdir(parents=True, exist_ok=True)
    gb = {p["project_id"]: p for p in (json.loads(l) for l in open(D / "project_detail.jsonl", encoding="utf-8"))}
    ours = cdm_studies()
    shared = sorted(set(ours) & set(gb))
    summ = {"gutbiomedb_projects": len(gb), "cdm_bioprojects": len(ours), "shared_bioprojects": len(shared),
            "cdm_only": sorted(set(ours) - set(gb))[:50], "gbdb_only_n": len(set(gb) - set(ours))}
    # --- country -------------------------------------------------------------------------------------------------------
    per, ctry = [], {}
    for var in ("llm", "released"):
        prim = anyl = n = none = 0
        for bp in shared:
            g = gb[bp]
            gprim = g.get("country")
            glist = {x for x in g.get("country_list", []) if x and x != "unknown"}
            if not gprim or gprim == "unknown":
                continue
            for r in ours[bp]:
                val = r[f"country_{var}"]
                if var == "released":
                    iso = {x.strip() for x in (r["country_iso_released"] or "").split(",") if len(x.strip()) == 2} or iso_of(val)
                else:
                    iso = iso_of(val)
                if not iso:
                    none += 1
                    continue
                n += 1
                prim += gprim in iso
                anyl += bool(iso & (glist | {gprim}))
        ctry[var] = {"n_projects_with_value": n, "n_without_value_or_unmapped": none,
                     "primary_country_match": wilson(prim, n), "any_country_overlap": wilson(anyl, n)}
    summ["country"] = ctry
    # --- platform / region ------------------------------------------------------------------------------------------------
    for fld, fn, gk in (("platform", norm_platform, "instrument"), ("region", norm_region, "region_16s")):
        res = {}
        for var in ("llm", "released"):
            k = n = 0
            for bp in shared:
                gv = fn(gb[bp].get(gk))
                if not gv:
                    continue
                for r in ours[bp]:
                    ov = fn(r[f"{fld}_{var}" if f"{fld}_{var}" in r else fld])
                    if not ov:
                        continue
                    n += 1
                    k += bool(ov & gv) if fld == "platform" else ov == gv
            res[var] = wilson(k, n)
        if fld == "region":
            res["gbdb_region_values"] = dict(Counter(gb[bp].get(gk) for bp in shared).most_common(6))
        summ[fld] = res
    summ["region"]["note"] = "GutBiomeDB region_16s is marked '(est.)' (estimated), not curated"
    summ["platform"]["note"] = ("agreement = the GutBiomeDB platform family is among the families named on our side; released value and "
                                "GutBiomeDB are both SRA instrument metadata; the LLM value is from the paper text")
    # --- conditions (LLM matcher) -----------------------------------------------------------------------------------------
    ans = [json.loads(l) for f in sorted(glob.glob(str(RESULTS / "llm_runs/gbdb/*.jsonl"))) for l in open(f, encoding="utf-8")]
    cond = {}
    for var in ("llm", "released"):
        A = [a for a in ans if a["variant"] == var and a.get("answer")]
        lab_k = lab_n = ph_k = ph_n = proj_any = proj_n = 0
        failed = sum(1 for a in ans if a["variant"] == var and not a.get("answer"))
        for a in A:
            ca = {x["n"]: x["covered"] for x in a["answer"]["a"] if isinstance(x.get("n"), int)}
            cb = {x["n"]: x["match"] for x in a["answer"]["b"] if isinstance(x.get("n"), int)}
            if a["gbdb_labels"] and a["cdm_phrases"]:
                proj_n += 1
                proj_any += any(ca.get(i) for i in range(len(a["gbdb_labels"])))
            if a["cdm_phrases"]:
                lab_n += len(a["gbdb_labels"])
                lab_k += sum(1 for i in range(len(a["gbdb_labels"])) if ca.get(i))
            for i in range(len(a["cdm_phrases"])):
                m = cb.get(i)
                if m in ("MATCH", "NO_MATCH"):
                    ph_n += 1
                    ph_k += m == "MATCH"
            per.append({"bioproject": a["bioproject"], "paper_id": a["paper_id"], "variant": var, "gbdb_labels": "; ".join(a["gbdb_labels"]),
                        "cdm_phrases": "; ".join(a["cdm_phrases"]),
                        "labels_covered": sum(1 for i in range(len(a["gbdb_labels"])) if ca.get(i)),
                        "phrases_matched": sum(1 for m in cb.values() if m == "MATCH")})
        noval = sum(1 for a in A if a["gbdb_labels"] and not a["cdm_phrases"])
        healthy_only = sum(1 for a in A if not a["gbdb_labels"] and a["cdm_phrases"])
        cond[var] = {"n_project_paper_pairs": len(A), "llm_failures": failed,
                     "gbdb_label_coverage": wilson(lab_k, lab_n),
                     "cdm_phrase_support": wilson(ph_k, ph_n),
                     "project_any_label_matched": wilson(proj_any, proj_n),
                     "pairs_gbdb_has_disease_cdm_none": noval, "pairs_gbdb_healthy_only_cdm_has_condition": healthy_only}
    summ["conditions"] = cond
    summ["conditions"]["matcher"] = "Qwen3.5-9B AWQ (local vLLM), prompt GBDB_PROMPT in competitor_llm_runner.py; matcher errors not hand-checked"
    with open(OUT / "per_project.csv", "w", newline="", encoding="utf-8") as f:
        if per:
            w = csv.DictWriter(f, fieldnames=list(per[0]))
            w.writeheader()
            w.writerows(per)
    dump(summ, OUT / "SUMMARY.json")
    print(json.dumps({k: v for k, v in summ.items() if k != "cdm_only"}, indent=1)[:4000])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--score", action="store_true")
    a = ap.parse_args()
    if a.fetch:
        fetch()
    if a.prepare:
        prepare()
    if a.score:
        score()
