"""Direct comparison of the frozen CDM 3.0.3 (catalogue 3.1.1 findings and metadata) with BugSigDB.

Rules, thresholds and endpoints are pre-registered in scoring_schema.json; every compared item is written as one
record of answer_template.schema.json (items.jsonl) and validated. The CDM is opened read-only and its sha256 is
checked against the schema before anything is computed. No text leaves the machine.

    python compare.py preregister    # hash the schema + template into the output folder (before the run)
    python compare.py run            # normally via: sbatch src/scripts/bugsigdb_comparison/compare.sbatch
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import random
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
HERE = Path(__file__).resolve().parent
SCHEMA = json.loads((HERE / "scoring_schema.json").read_text())
TEMPLATE = json.loads((HERE / "answer_template.schema.json").read_text())
OUT = ROOT / "outputs/results/benchmark/bugsigdb_comparison_2026-11-03"
EXCLUDED_SECTIONS = {"References", "Acknowledgements"}

SEQ_TYPES = [("16S", r"16\s?s"), ("ITS", r"\bits\d?\b|internal transcribed"), ("18S", r"18\s?s"),
             ("WMS", r"shotgun|whole[- ]?(genome|metagenom)|\bwms\b|\bwgs\b"),
             ("PCR", r"\bqpcr\b|quantitative (real[- ]time )?pcr|real[- ]time (quantitative )?pcr"),
             ("RNA-Seq", r"rna[- ]?seq|metatranscriptom")]
PLATFORMS = [("Illumina", r"illumina|miseq|hiseq|novaseq|nextseq|iseq|genome analyzer"),
             ("Roche454", r"\b454\b|pyroseq|roche|gs[- ]?flx|titanium"),
             ("Ion Torrent", r"ion torrent|ion s5|ion pgm|ion proton|ion gene"),
             ("PacBio", r"pacbio|pacific biosciences|sequel"), ("Nanopore", r"nanopore|minion|gridion|promethion"),
             ("Sanger", r"sanger"), ("BGI/MGI", r"bgiseq|dnbseq|mgiseq|\bbgi\b")]
TESTS = [("LEfSe", r"lefse|lda effect size|linear discriminant analysis effect size"),
         ("Mann-Whitney/Wilcoxon", r"mann[- ]?whitney|wilcoxon|rank[- ]sum"),
         ("DESeq2", r"deseq"), ("edgeR", r"edger"), ("MaAsLin", r"maaslin"), ("Kruskal-Wallis", r"kruskal"),
         ("t-test", r"t[- ]test|student"), ("ANCOM", r"ancom"), ("ALDEx2", r"aldex"),
         ("metagenomeSeq", r"metagenomeseq|zero[- ]inflated gaussian"), ("negative binomial", r"negative binomial"),
         ("logistic regression", r"logistic regression"),
         ("linear model", r"linear regression|linear model|generali[sz]ed linear|mixed[- ]effects?|linear mixed"),
         ("Spearman", r"spearman"), ("Pearson", r"pearson"), ("Fisher", r"fisher"),
         ("chi-squared", r"chi[- ]?squ|chi2|χ2"), ("ANOVA", r"anova"), ("random forest", r"random forest"),
         ("PERMANOVA", r"permanova|adonis")]
RULES = {"sequencing_type": SEQ_TYPES, "platform": PLATFORMS, "statistical_test": TESTS}
BSDB_COL = {"sequencing_type": "Sequencing type", "platform": "Sequencing platform", "statistical_test": "Statistical test",
            "country": "Location of subjects", "body_site": "Body site", "condition": "Condition"}
EMBED_FIELDS = ("body_site", "condition", "group_name")


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def classes(text: str, rules) -> set[str]:
    t = (text or "").lower()
    return {name for name, rx in rules if re.search(rx, t)}


def regions(text: str) -> set[int]:
    out = set()
    for m in re.finditer(r"(?i)\bv\s?([1-9])(?:\s*(?:-|–|—|to|through|/|and|&|\+)\s*v?\s?([1-9])\b|\s?v([1-9])\b)?", text or ""):
        a, b = int(m.group(1)), int(m.group(2) or m.group(3) or m.group(1))
        out.update(range(min(a, b), max(a, b) + 1))
    return out


def country_index():
    import pycountry
    names, alpha = {}, {"USA": "US", "UK": "GB", "PRC": "CN", "UAE": "AE"}
    norm = lambda s: " " + re.sub(r"[^a-z]+", " ", s.lower()).strip() + " "
    for c in pycountry.countries:
        for n in {c.name, getattr(c, "common_name", ""), getattr(c, "official_name", "")} - {""}:
            names[norm(n)] = c.alpha_2
    for n, a in {"usa": "US", "united states": "US", "america": "US", "u s a": "US", "u s": "US", "korea": "KR",
                 "south korea": "KR", "republic of korea": "KR", "england": "GB", "scotland": "GB", "wales": "GB",
                 "britain": "GB", "great britain": "GB", "russia": "RU", "iran": "IR", "vietnam": "VN", "taiwan": "TW",
                 "czech republic": "CZ", "turkey": "TR", "holland": "NL", "the netherlands": "NL",
                 "tanzania": "TZ", "bolivia": "BO", "venezuela": "VE", "hong kong": "HK"}.items():
        names[norm(n)] = a

    def countries(s: str) -> set[str]:
        low = norm(s or "")
        out = {code for n, code in names.items() if n in low}
        out |= {alpha[t] for t in re.findall(r"\b[A-Z]{2,3}\b", s or "") if t in alpha}
        return out
    return countries


def ints(v) -> set[int]:
    return {int(x) for x in re.findall(r"\b\d{1,6}\b", str(v or "")) if int(x) > 0}


def pieces(s: str) -> list[str]:
    return [p.strip() for p in re.split(r";|,|\||\s+vs\.?\s+|\s+versus\s+", s or "") if 2 <= len(p.strip()) <= 200]


def lex(s: str) -> str:
    return " " + re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip() + " "


def source_class(s: str) -> str:
    t = (s or "").lower()
    return ("Supplement" if "suppl" in t or re.search(r"\bs\d", t) else "Figure" if "fig" in t else
            "Table" if "table" in t else "Text" if t else "Not stated")


def group_by(items, key):
    g = defaultdict(list)
    for i in items:
        g[i[key]].append(i)
    return g


def direction_chance(det):
    if not det:
        return None
    b = Counter(i["dirs"][0][0] for i in det)
    o = Counter(i["dirs"][1][0] for i in det)
    n = len(det)
    return round(sum(b[d] * o[d] for d in ("up", "down")) / (n * n), 4)


def wilson(k: int, n: int):
    if not n:
        return None
    z, p = 1.959964, k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return [round(c - h, 4), round(c + h, 4)]


def boot(items, ok, papers, rng):
    """Paper-cluster percentile bootstrap of an item-level proportion."""
    by = defaultdict(list)
    for it in items:
        by[it["paper_id"]].append(ok(it))
    ps = [p for p in papers if by[p]]
    if not ps:
        return None
    vals = []
    for _ in range(SCHEMA["uncertainty"]["bootstrap"]["replicates"]):
        s = [x for p in (rng.choice(ps) for _ in ps) for x in by[p]]
        vals.append(sum(s) / len(s))
    vals.sort()
    return [round(vals[int(0.025 * len(vals))], 4), round(vals[int(0.975 * len(vals)) - 1], 4)]


# ------------------------------------------------------------------ inputs
def load_bugsigdb():
    p = ROOT / SCHEMA["inputs"]["bugsigdb"]["path"]
    csv.field_size_limit(sys.maxsize)
    txt = p.read_text(encoding="utf-8")
    header, body = txt.split("\n", 1)
    return header.lstrip("# ").strip(), list(csv.DictReader(io.StringIO(body)))


def load_taxonomy():
    raw = ROOT / "data/reference_kg/raw"
    parent, rank, name = {}, {}, {}
    with open(raw / "nodes.dmp", encoding="utf-8") as fh:
        for line in fh:
            f = line.split("\t|\t", 3)
            parent[int(f[0])], rank[int(f[0])] = int(f[1]), f[2]
    with open(raw / "names.dmp", encoding="utf-8") as fh:
        for line in fh:
            if "scientific name" in line:
                f = line.split("\t|\t")
                name[int(f[0])] = f[1]
    lifted = {}

    def genus(t: int) -> int:
        if t in lifted:
            return lifted[t]
        g, x, seen = t, t, 0
        while x in parent and seen < 60:
            if rank[x] == "genus":
                g = x
                break
            if parent[x] == x:
                break
            x, seen = parent[x], seen + 1
        lifted[t] = g
        return g
    return parent, rank, name, genus


def taxa_ids(s: str) -> set[int]:
    return {int(x) for x in re.findall(r"NCBITaxon:(\d+)", s or "")}


# ------------------------------------------------------------------ run
def cmd_preregister():
    OUT.mkdir(parents=True, exist_ok=True)
    lines = [f"{sha256(HERE / f)}  {f}" for f in ("scoring_schema.json", "answer_template.schema.json")]
    (OUT / "PREREGISTRATION.sha256").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


def cmd_run(skip_embed: bool):
    pre = OUT / "PREREGISTRATION.sha256"
    if not pre.exists():
        sys.exit("run `compare.py preregister` first")
    for line in pre.read_text().splitlines():
        h, f = line.split()
        if sha256(HERE / f) != h:
            sys.exit(f"{f} changed after pre-registration")
    for key in ("cdm", "bugsigdb", "ncbi_taxonomy_nodes", "ncbi_taxonomy_names"):
        got = sha256(ROOT / SCHEMA["inputs"][key]["path"])
        if got != SCHEMA["inputs"][key]["sha256"]:
            sys.exit(f"input {key} does not match the registered sha256")
    print("pre-registration and input hashes verified", flush=True)

    rng = random.Random(SCHEMA["uncertainty"]["bootstrap"]["seed"])
    c = sqlite3.connect(f"file:{ROOT / SCHEMA['inputs']['cdm']['path']}?mode=ro", uri=True)
    q = lambda sql, *a: c.execute(sql, a).fetchall()
    export, rows = load_bugsigdb()
    parent, rank, tname, genus = load_taxonomy()
    countries = country_index()
    print("taxonomy loaded:", len(parent), "nodes", flush=True)

    # papers present in both
    by_pmid = {str(p): i for i, p in q("SELECT paper_id, pmid FROM paper WHERE pmid IS NOT NULL AND pmid != ''")}
    by_doi = {d.lower().strip(): i for i, d in q("SELECT paper_id, doi FROM paper WHERE doi IS NOT NULL AND doi != ''")}
    sig = defaultdict(list)
    how = Counter()
    for r in rows:
        pm = (r.get("PMID") or "").split(".")[0]
        pid = by_pmid.get(pm) if pm else None
        if pid:
            how["pmid"] += 1
        else:
            pid = by_doi.get((r.get("DOI") or "").lower().strip())
            how["doi"] += bool(pid)
        if pid:
            sig[pid].append(r)
    papers = sorted(sig)
    print(f"{len(papers)} papers, {sum(map(len, sig.values()))} signatures", flush=True)

    # ---------------- our side, per paper
    ours_tax = {src: defaultdict(lambda: defaultdict(set)) for src in ("catalogue", "all")}
    dmap = SCHEMA["our_findings"]["direction_map"]
    for pid, ids, d, srcname in q("SELECT paper_id, taxon_ncbi_ids, direction, claim_source FROM claim "
                                  "WHERE taxon_ncbi_ids IS NOT NULL AND taxon_ncbi_ids != ''"):
        for t in taxa_ids(ids):
            for src in ("catalogue", "all") if srcname == "catalogue_v3_1" else ("all",):
                ours_tax[src][pid][t]
                if d in dmap:
                    ours_tax[src][pid][t].add(dmap[d])

    cand = {f: defaultdict(list) for f in SCHEMA["fields"] if f != "taxon"}
    spec = {"assay": ("assay_type", "assay_type_normalized", "target_gene_or_region", "primer_or_probe", "sequencing_platform",
                      "statistical_methods", "software_tools", "bioinformatics_pipeline"),
            "study": ("assay_type", "target_gene_region", "sequencing_platform", "statistical_methods", "country_region",
                      "num_participants_reported", "num_biological_samples_reported", "body_sites", "specimen_types",
                      "health_conditions", "exposures_interventions", "comparator_control_group"),
            "cohort": ("country_or_region", "participant_count", "sample_count", "health_status", "cohort_label"),
            "sample": ("sample_count", "body_site", "body_site_normalized", "sample_type_normalized")}
    vals = defaultdict(lambda: defaultdict(list))  # pid -> "table.col" -> values
    for tbl, cols in spec.items():
        for r in q(f"SELECT paper_id, {', '.join(cols)} FROM {tbl}"):
            for col, v in zip(cols, r[1:]):
                if v not in (None, ""):
                    vals[r[0]][f"{tbl}.{col}"].append(str(v))
    for r in q("SELECT paper_id, comparison_or_exposure, population_subgroup FROM claim WHERE claim_source = 'catalogue_v3_1'"):
        for col, v in zip(("comparison_or_exposure", "population_subgroup"), r[1:]):
            if v not in (None, ""):
                vals[r[0]][f"claim.{col}"].append(str(v))
    for f, fs in SCHEMA["fields"].items():
        for pid in papers:
            if f == "taxon":
                continue
            raw = [v for col in fs["ours_from"] for v in vals[pid].get(col, [])]
            cand[f][pid] = list(dict.fromkeys(raw))

    # ---------------- reference side, per paper
    ref = {f: defaultdict(lambda: defaultdict(list)) for f in SCHEMA["fields"]}   # field -> pid -> value -> [BSDB IDs]
    bsdb_dir = defaultdict(lambda: defaultdict(set))
    bsdb_leaf_name = {}
    sig_source = {}
    for pid in papers:
        for r in sig[pid]:
            sid = r["BSDB ID"]
            sig_source[sid] = r.get("Source") or ""
            d = {"increased": "up", "decreased": "down"}.get(r["Abundance in Group 1"])
            if d:
                lineages = [x for x in (r["NCBI Taxonomy IDs"] or "").split(";") if x.strip()]
                names = (r["MetaPhlAn taxon names"] or "").split(",")
                for k, lin in enumerate(lineages):
                    if not lin.split("|")[-1].strip().isdigit():
                        continue  # "NA": signature without a taxon
                    leaf = int(lin.split("|")[-1])
                    ref["taxon"][pid][str(leaf)].append(sid)
                    bsdb_dir[pid][leaf].add(d)
                    if len(names) == len(lineages):
                        bsdb_leaf_name[leaf] = re.sub(r"^[a-z]__", "", names[k].split("|")[-1])
            for f, col in BSDB_COL.items():
                v = (r.get(col) or "").strip()
                if v and v != "NA":
                    for part in (v.split(",") if f in ("body_site", "statistical_test", "country") else [v]):
                        ref[f][pid][part.strip()].append(sid)
            if r.get("Sequencing type") == "16S" and r.get("16S variable region", "NA") not in ("", "NA"):
                ref["region_16s"][pid][r["16S variable region"]].append(sid)
            for g in ("Group 0", "Group 1"):
                n = (r.get(f"{g} sample size") or "").split(".")[0]
                if n.isdigit() and int(n) > 0:
                    ref["group_size"][pid][n].append(sid)
                gn = (r.get(f"{g} name") or "").strip()
                if gn and gn != "NA":
                    ref["group_name"][pid][gn].append(sid)

    # ---------------- scorers: (bsdb value, candidate strings of a paper) -> (verdict, score, our_values)
    def score_rule(f):
        rules = RULES[f]

        def s(v, cs):
            b = classes(v, rules)
            if not b:
                return "UNCLASSIFIED", None, []
            ours = {k for x in cs for k in classes(x, rules)}
            if not ours:
                return "OURS_MISSING", None, []
            return ("MATCH" if b & ours else "MISMATCH"), None, sorted(ours)
        return s

    def score_region(v, cs):
        b = {int(x) for x in v if x.isdigit()}
        sets = [regions(x) for x in cs]
        sets = [x for x in sets if x]
        if not sets:
            return "OURS_MISSING", None, []
        union = set().union(*sets)
        vals_ = sorted({"V" + "-V".join(map(str, sorted(x))) for x in sets})[:10]
        if any(x == b for x in sets) or union == b:
            return "MATCH", None, vals_
        return ("PARTIAL" if union & b else "MISMATCH"), None, vals_

    def score_country(v, cs):
        b = countries(v)
        if not b:
            return "UNCLASSIFIED", None, []
        ours = {k for x in cs for k in countries(x)}
        if not ours:
            return "OURS_MISSING", None, []
        return ("MATCH" if b & ours else "MISMATCH"), None, sorted(ours)

    def score_int(v, cs):
        ours = {k for x in cs for k in ints(x)}
        if not ours:
            return "OURS_MISSING", None, []
        return ("MATCH" if int(v) in ours else "MISMATCH"), None, [str(x) for x in sorted(ours)][:10]

    scorers = {"sequencing_type": (score_rule("sequencing_type"), "rule_class"),
               "platform": (score_rule("platform"), "rule_class"),
               "statistical_test": (score_rule("statistical_test"), "rule_class"),
               "region_16s": (score_region, "region_set"), "country": (score_country, "country"),
               "group_size": (score_int, "integer")}

    # ---------------- embeddings
    emb = {}
    if not skip_embed:
        emb = embed_all(ref, cand, papers)

    items, chance, field_stats = [], {}, {}
    text_cache = {}

    def paper_text(pid):
        if pid not in text_cache:
            text_cache[pid] = "\n".join(t for t, in q("SELECT section_text_original FROM section WHERE paper_id = ? "
                                                       "AND section_type NOT IN (?, ?)", pid, *EXCLUDED_SECTIONS) if t)
        return text_cache[pid]

    def adjudicate(pid, f, v, ours):
        t = paper_text(pid)
        if f == "region_16s":
            bsdb_in = {int(x) for x in v if x.isdigit()} <= regions(t)
            ours_in = any({int(d) for d in re.findall(r"\d", o)} <= regions(t) for o in ours)
        elif f == "country":
            tc = countries(t)
            bsdb_in, ours_in = bool(countries(v) & tc), bool(set(ours) & tc)
        else:
            tc = classes(t, RULES[f])
            bsdb_in, ours_in = bool(classes(v, RULES[f]) & tc), bool(set(ours) & tc)
        return {(True, True): "BOTH_IN_TEXT", (True, False): "BSDB_ONLY_IN_TEXT",
                (False, True): "OURS_ONLY_IN_TEXT", (False, False): "NEITHER_IN_TEXT"}[(bsdb_in, ours_in)]

    def rec(pid, f, sids, v, ours, method, verdict, score=None, thr=None, lexm=None, direction=None, adj=None):
        items.append({"item_id": f"{pid}:{f}:{len(items):06d}", "paper_id": pid, "field": f,
                      "bsdb_signatures": sorted(set(sids)), "bsdb_value": v, "our_values": [o[:200] for o in ours][:10],
                      "method": method, "score": score, "threshold": thr, "lexical_match": lexm, "verdict": verdict,
                      "direction": direction, "adjudication": adj})

    # ---- taxa
    def tax_verdict(leaf, mine):
        if not mine:
            return "OURS_MISSING", []
        if leaf in mine:
            return "MATCH", [str(leaf)]
        g = genus(leaf)
        hit = [t for t in mine if genus(t) == g]
        return ("PARTIAL", [str(t) for t in hit]) if hit else ("MISMATCH", [])

    tax_summary = {}
    for src in ("catalogue", "all"):
        cov, sup, dirs = Counter(), Counter(), Counter()
        cov_items, sup_items = [], []
        for pid in papers:
            mine = ours_tax[src].get(pid, {})
            for leaf_s, sids in ref["taxon"][pid].items():
                leaf = int(leaf_s)
                v, hit = tax_verdict(leaf, mine)
                cov[v] += 1
                direction = None
                if v in ("MATCH", "PARTIAL"):
                    od = set().union(*(mine[int(h)] for h in hit))
                    bd = bsdb_dir[pid][leaf]
                    agr = ("SAME" if bd == od else "OPPOSITE") if len(bd) == 1 and len(od) == 1 else "UNDETERMINED"
                    direction = {"bsdb": sorted(bd), "ours": sorted(od), "agreement": agr}
                    dirs[agr] += 1
                it = {"paper_id": pid, "verdict": v, "agr": direction and direction["agreement"],
                      "src": source_class(sig_source.get(sorted(set(sids))[0], "")),
                      "dirs": (sorted(direction["bsdb"]), sorted(direction["ours"])) if direction else None}
                cov_items.append(it)
                if src == "catalogue":
                    rec(pid, "taxon", sids, f"NCBITaxon:{leaf} {tname.get(leaf, bsdb_leaf_name.get(leaf, '?'))}",
                        [f"NCBITaxon:{h} {tname.get(int(h), '?')}" for h in hit], "exact_id" if v == "MATCH" else "lineage_genus",
                        v, direction=direction)
            ref_genera = {genus(int(x)) for x in ref["taxon"][pid]}
            ref_exact = {int(x) for x in ref["taxon"][pid]}
            for t in mine:
                v = "MATCH" if t in ref_exact else "PARTIAL" if genus(t) in ref_genera else "NOT_IN_REFERENCE"
                sup[v] += 1
                sup_items.append({"paper_id": pid, "verdict": v})
                if src == "catalogue":
                    rec(pid, "our_taxon", [], None, [f"NCBITaxon:{t} {tname.get(t, '?')}"],
                        "exact_id" if v == "MATCH" else "lineage_genus", v)
        # cross-paper chance for coverage and support
        ck = cn = sk = sn = 0
        for p in papers:
            for o in papers:
                if o == p or not ours_tax[src].get(o):
                    continue
                for leaf_s in ref["taxon"][p]:
                    cn += 1
                    ck += tax_verdict(int(leaf_s), ours_tax[src][o])[0] in ("MATCH", "PARTIAL")
                rg = {genus(int(x)) for x in ref["taxon"][p]}
                for t in ours_tax[src][o]:
                    sn += 1
                    sk += genus(t) in rg
        n = len(cov_items)
        k = sum(i["verdict"] in ("MATCH", "PARTIAL") for i in cov_items)
        kx = sum(i["verdict"] == "MATCH" for i in cov_items)
        ns, ks = len(sup_items), sum(i["verdict"] != "NOT_IN_REFERENCE" for i in sup_items)
        det = [i for i in cov_items if i["agr"] in ("SAME", "OPPOSITE")]
        kd = sum(i["agr"] == "SAME" for i in det)
        ch, chs = ck / cn if cn else None, sk / sn if sn else None
        tax_summary[src] = {
            "bsdb_items": n, "verdicts": dict(cov),
            "coverage": round(k / n, 4) if n else None, "coverage_wilson": wilson(k, n),
            "coverage_bootstrap": boot(cov_items, lambda i: i["verdict"] in ("MATCH", "PARTIAL"), papers, rng),
            "coverage_chance": round(ch, 4) if ch is not None else None,
            "coverage_chance_corrected": round((k / n - ch) / (1 - ch), 4) if n and ch is not None and ch < 1 else None,
            "exact_coverage": round(kx / n, 4) if n else None, "exact_coverage_wilson": wilson(kx, n),
            "papers_with_our_taxa": sum(1 for p in papers if ours_tax[src].get(p)),
            "our_items": ns, "support_verdicts": dict(sup),
            "support_rate": round(ks / ns, 4) if ns else None, "support_wilson": wilson(ks, ns),
            "support_bootstrap": boot(sup_items, lambda i: i["verdict"] != "NOT_IN_REFERENCE", papers, rng),
            "support_chance": round(chs, 4) if chs is not None else None,
            "direction": dict(dirs), "direction_determinable": len(det),
            "direction_same": round(kd / len(det), 4) if det else None, "direction_same_wilson": wilson(kd, len(det)),
            "direction_same_bootstrap": boot(det, lambda i: i["agr"] == "SAME", papers, rng),
            # post-hoc: agreement expected from the up/down base rates of the determinable pairs
            "posthoc_direction_chance": direction_chance(det),
            # post-hoc: coverage by where BugSigDB took the signature from
            "posthoc_coverage_by_source": {
                src_: {"items": len(g), "coverage": round(sum(i["verdict"] in ("MATCH", "PARTIAL") for i in g) / len(g), 4),
                       "wilson": wilson(sum(i["verdict"] in ("MATCH", "PARTIAL") for i in g), len(g))}
                for src_, g in sorted(group_by(cov_items, "src").items())},
        }
        print(src, json.dumps(tax_summary[src]), flush=True)

    # ---- metadata fields
    for f in [x for x in SCHEMA["fields"] if x != "taxon"]:
        fitems = []
        if f in EMBED_FIELDS:
            if not emb:
                continue
            res = emb[f]
            for pid in papers:
                for v, sids in ref[f][pid].items():
                    r = res["obs"][(pid, v)]
                    rec(pid, f, sids, v, r["best"], "embedding", r["verdict"], r["score"], res["threshold"], r["lexical"])
                    fitems.append({"paper_id": pid, "verdict": r["verdict"], "lexical": r["lexical"]})
            chance_rate = res["chance"]
        else:
            fn, method = scorers[f]
            ck = cn = 0
            for pid in papers:
                for v, sids in ref[f][pid].items():
                    verdict, sc, ours = fn(v, cand[f][pid])
                    adj = adjudicate(pid, f, v, ours) if verdict == "MISMATCH" and f != "group_size" else None
                    rec(pid, f, sids, v, ours, method, verdict, adj=adj)
                    strict = None
                    if f in RULES and verdict in ("MATCH", "MISMATCH"):  # post-hoc: our class set == BugSigDB's
                        strict = set(ours) == {k for x in ref[f][pid] for k in classes(x, RULES[f])}
                    fitems.append({"paper_id": pid, "verdict": verdict, "adj": adj, "strict": strict})
                    if verdict in ("MATCH", "PARTIAL", "MISMATCH"):
                        for o in papers:
                            if o != pid:
                                vo = fn(v, cand[f][o])[0]
                                if vo in ("MATCH", "PARTIAL", "MISMATCH"):
                                    cn += 1
                                    ck += vo == "MATCH"
            chance_rate = ck / cn if cn else None
        scored = [i for i in fitems if i["verdict"] != "UNCLASSIFIED"]
        both = [i for i in scored if i["verdict"] in ("MATCH", "PARTIAL", "MISMATCH")]
        k = sum(i["verdict"] == "MATCH" for i in both)
        conc = k / len(both) if both else None
        field_stats[f] = {
            "items": len(fitems), "unclassified": len(fitems) - len(scored),
            "verdicts": dict(Counter(i["verdict"] for i in fitems)),
            "completeness": round(len(both) / len(scored), 4) if scored else None,
            "concordance": round(conc, 4) if conc is not None else None, "concordance_wilson": wilson(k, len(both)),
            "concordance_bootstrap": boot(both, lambda i: i["verdict"] == "MATCH", papers, rng),
            "chance": round(chance_rate, 4) if chance_rate is not None else None,
            "chance_corrected": round((conc - chance_rate) / (1 - chance_rate), 4)
            if conc is not None and chance_rate is not None and chance_rate < 1 else None,
            "adjudication": dict(Counter(i.get("adj") for i in fitems if i.get("adj"))),
        }
        st = [i["strict"] for i in fitems if i.get("strict") is not None]
        if st:
            field_stats[f]["posthoc_strict_set_equal"] = round(sum(st) / len(st), 4)
            field_stats[f]["posthoc_strict_wilson"] = wilson(sum(st), len(st))
        if f in EMBED_FIELDS:
            field_stats[f]["threshold"] = emb[f]["threshold"]
            field_stats[f]["lexical_match"] = round(sum(bool(i["lexical"]) for i in both) / len(both), 4) if both else None
            field_stats[f]["sensitivity_minilm"] = emb[f].get("sensitivity")
        print(f, json.dumps(field_stats[f]), flush=True)

    # ---- validate every record against the answer template
    import jsonschema
    val = jsonschema.Draft202012Validator(TEMPLATE)
    bad = [(i["item_id"], e.message) for i in items for e in val.iter_errors(i)]
    if bad:
        sys.exit(f"{len(bad)} records violate the answer template, e.g. {bad[:3]}")

    # ---- ontology currency (measured, not asserted)
    def currency(leaves):
        leaves = set(leaves)
        present = {t for t in leaves if t in parent}
        named = {t for t in present if t in bsdb_leaf_name}
        diff = sorted(t for t in named if bsdb_leaf_name[t] != tname.get(t))
        return {"distinct_taxa": len(leaves), "absent_from_snapshot": len(leaves - present),
                "absent_examples": sorted(leaves - present)[:10], "with_bsdb_name": len(named),
                "name_differs_from_current": len(diff),
                "name_examples": [[t, bsdb_leaf_name[t], tname.get(t)] for t in diff[:10]]}
    all_leaves = set()
    for r in rows:
        for lin in (r["NCBI Taxonomy IDs"] or "").split(";"):
            if lin.split("|")[-1].strip().isdigit():
                leaf = int(lin.split("|")[-1])
                all_leaves.add(leaf)
        names = (r["MetaPhlAn taxon names"] or "").split(",")
        lins = [x for x in (r["NCBI Taxonomy IDs"] or "").split(";") if x.strip()]
        if len(names) == len(lins):
            for lin, nm in zip(lins, names):
                if lin.split("|")[-1].strip().isdigit():
                    bsdb_leaf_name.setdefault(int(lin.split("|")[-1]), re.sub(r"^[a-z]__", "", nm.split("|")[-1]))
    ours_ids = {t for p in ours_tax["all"].values() for t in p}
    curated = Counter((re.findall(r"\b(?:19|20)\d\d\b", r.get("Curated date") or "") or ["NA"])[-1]
                      for p in papers for r in sig[p])
    ontology = {"taxonomy_snapshot": (ROOT / "data/reference_kg/raw/DOWNLOADED_AT").read_text().strip(),
                "bugsigdb_export": export,
                "bugsigdb_overlap": currency(int(x) for p in papers for x in ref["taxon"][p]),
                "bugsigdb_full_dump": currency(all_leaves),
                "cdm_findings_absent_from_snapshot": len(ours_ids - set(parent)),
                "cdm_findings_distinct_taxa": len(ours_ids),
                "overlap_signatures_curated_year": dict(sorted(curated.items()))}

    # ---- write
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "items.jsonl", "w", encoding="utf-8") as fh:
        for i in items:
            fh.write(json.dumps(i, ensure_ascii=False) + "\n")
    summary = {"protocol": "scoring_schema.json v" + SCHEMA["version"], "bugsigdb_export": export,
               "paper_match": dict(how), "papers": len(papers),
               "signatures": sum(len(sig[p]) for p in papers),
               "signatures_with_direction": sum(1 for p in papers for r in sig[p]
                                                if r["Abundance in Group 1"] in ("increased", "decreased")),
               "taxa": tax_summary, "fields": field_stats, "ontology_currency": ontology,
               "items_written": len(items), "embedding_skipped": skip_embed,
               "code_sha256": sha256(Path(__file__).resolve())}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    write_report(summary)
    files = sorted(p for p in OUT.iterdir() if p.is_file() and p.name != "MANIFEST.sha256")
    (OUT / "MANIFEST.sha256").write_text("".join(f"{sha256(p)}  {p.name}\n" for p in files))
    print("written:", OUT.relative_to(ROOT))


def embed_all(ref, cand, papers):
    """Max-cosine scores of each BugSigDB value against its own paper's candidates and against every other paper's
    (cross-paper null). Threshold = 95th percentile of the null, per field and model."""
    import numpy as np
    import torch
    from transformers import AutoModel, AutoTokenizer

    def encoder(spec):
        tok = AutoTokenizer.from_pretrained(spec["id"], revision=spec["revision"])
        m = AutoModel.from_pretrained(spec["id"], revision=spec["revision"]).eval()
        dev = "cuda" if torch.cuda.is_available() else "cpu"
        m.to(dev)

        def enc(texts):
            out = []
            for i in range(0, len(texts), 256):
                b = tok(texts[i:i + 256], padding=True, truncation=True, max_length=spec["max_length"], return_tensors="pt").to(dev)
                with torch.no_grad():
                    h = m(**b).last_hidden_state
                mask = b["attention_mask"].unsqueeze(-1).float()
                v = h[:, 0] if spec["pooling"] == "cls" else (h * mask).sum(1) / mask.sum(1)
                out.append(torch.nn.functional.normalize(v, dim=-1).cpu().numpy())
            return np.concatenate(out) if out else np.zeros((0, 1))
        return enc

    res = {}
    for which in ("primary_model", "sensitivity_model"):
        spec = SCHEMA["embedding"][which]
        enc = encoder(spec)
        for f in EMBED_FIELDS:
            cp = {p: list(dict.fromkeys(x for s in cand[f][p] for x in pieces(s))) for p in papers}
            strings = sorted({x for v in cp.values() for x in v} | {v for p in papers for v in ref[f][p]})
            idx = {s: i for i, s in enumerate(strings)}
            E = enc(strings)
            M = {p: E[[idx[x] for x in cp[p]]] if cp[p] else None for p in papers}

            def best(v, p):
                if M[p] is None:
                    return None, None
                sims = M[p] @ E[idx[v]]
                j = int(sims.argmax())
                return float(sims[j]), cp[p][j]
            null = [best(v, o)[0] for p in papers for v in ref[f][p] for o in papers if o != p]
            null = sorted(x for x in null if x is not None)
            thr_raw = float(np.percentile(null, 95)) if null else None
            thr = round(thr_raw, 4) if null else None
            obs, k, n = {}, 0, 0
            for p in papers:
                for v in ref[f][p]:
                    s, b = best(v, p)
                    if s is None:
                        obs[(p, v)] = {"verdict": "OURS_MISSING", "score": None, "best": [], "lexical": None}
                        continue
                    lv = lex(v)
                    lx = any(lv in lex(x) or (len(lex(x)) > 4 and lex(x) in lv) for x in cp[p])
                    verdict = "MATCH" if s >= thr_raw else "MISMATCH"
                    obs[(p, v)] = {"verdict": verdict, "score": round(s, 4), "best": [b], "lexical": lx}
                    n += 1
                    k += verdict == "MATCH"
            if which == "primary_model":
                res[f] = {"threshold": thr, "obs": obs, "chance": 0.05,
                          "null_n": len(null)}
            else:
                res[f]["sensitivity"] = {"model": spec["id"], "threshold": thr,
                                         "concordance": round(k / n, 4) if n else None, "n": n}
            print(f"embedding {which} {f}: threshold {thr}, observed {k}/{n}", flush=True)
    return res


def write_report(s):
    t, f = s["taxa"]["catalogue"], s["fields"]
    pct = lambda x: "–" if x is None else f"{100 * x:.1f}%"
    ci = lambda x: "–" if not x else f"{100 * x[0]:.1f}–{100 * x[1]:.1f}"
    L = ["# Direct comparison with BugSigDB (human-curated signatures)", "",
         f"*Frozen CDM 3.0.3 / catalogue 3.1.1 versus BugSigDB export {s['bugsigdb_export']}. Protocol pre-registered in "
         "`src/scripts/bugsigdb_comparison/scoring_schema.json` (hash in `PREREGISTRATION.sha256`); one record per item in "
         "`items.jsonl`, validated against `answer_template.schema.json`.*", "",
         "These numbers are **concordance with human curation**, not accuracy. BugSigDB curates selected signatures per "
         "paper, so taxa we report that BugSigDB lacks are not counted as errors, and disagreements are adjudicated "
         "against the paper text.", "",
         f"**Overlap:** {s['papers']} papers ({s['paper_match']}), {s['signatures']} signatures "
         f"({s['signatures_with_direction']} with a direction).", "",
         "## Taxa (catalogue findings)", "", "| Measure | Value | 95% Wilson | 95% paper bootstrap | Chance |", "|---|---:|---:|---:|---:|",
         f"| BugSigDB taxa covered (exact or same genus) | {pct(t['coverage'])} of {t['bsdb_items']} | {ci(t['coverage_wilson'])} | "
         f"{ci(t['coverage_bootstrap'])} | {pct(t['coverage_chance'])} |",
         f"| BugSigDB taxa covered, exact NCBI ID | {pct(t['exact_coverage'])} | {ci(t['exact_coverage_wilson'])} | | |",
         f"| Our taxa also in BugSigDB (support, not precision) | {pct(t['support_rate'])} of {t['our_items']} | "
         f"{ci(t['support_wilson'])} | {ci(t['support_bootstrap'])} | {pct(t['support_chance'])} |",
         f"| Same direction (matched, determinable n={t['direction_determinable']}) | {pct(t['direction_same'])} | "
         f"{ci(t['direction_same_wilson'])} | {ci(t['direction_same_bootstrap'])} | |", "",
         f"Chance-corrected coverage: {t['coverage_chance_corrected']}. Coverage verdicts: {t['verdicts']}. "
         f"All CDM findings (secondary): {pct(s['taxa']['all']['coverage'])} coverage.", "",
         f"Post-hoc: direction agreement expected from base rates {pct(t['posthoc_direction_chance'])}. "
         "Coverage by BugSigDB signature source: " + "; ".join(f"{k} {pct(v['coverage'])} of {v['items']}" for k, v in t["posthoc_coverage_by_source"].items()) + ".", "",
         "## Study metadata", "",
         "| Field | Items | Our value present | Concordance | 95% Wilson | 95% paper bootstrap | Chance | Chance-corrected | Disagreements adjudicated |",
         "|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    for k, v in f.items():
        L.append(f"| {k} | {v['items']} | {pct(v['completeness'])} | {pct(v['concordance'])} | {ci(v['concordance_wilson'])} | "
                 f"{ci(v['concordance_bootstrap'])} | {pct(v['chance'])} | {v['chance_corrected']} | {v['adjudication'] or ''} |")
    emb = [k for k in f if "threshold" in f[k]]
    if emb:
        L += ["", "Embedding fields (SapBERT; threshold = 95th percentile of the cross-paper null, so chance = 5% by construction):", ""]
        L += [f"- {k}: threshold {f[k]['threshold']}, lexical match {pct(f[k]['lexical_match'])}, "
              f"MiniLM sensitivity {pct((f[k]['sensitivity_minilm'] or {}).get('concordance'))}" for k in emb]
    strict = [k for k in f if "posthoc_strict_set_equal" in f[k]]
    if strict:
        L += ["", "Post-hoc (not pre-registered) strict measure for rule fields: our set of classes for the paper equals BugSigDB's set, which removes the leniency of 'any of our values matches':", ""]
        L += [f"- {k}: {pct(f[k]['posthoc_strict_set_equal'])} ({ci(f[k]['posthoc_strict_wilson'])})" for k in strict]
    L += ["", "## Deviations from the pre-registered protocol", "",
          "- Scoring rules, thresholds and endpoints: none changed (hashes verified at run time).",
          "- Implementation fixes after failed runs (before any complete result): BugSigDB lineages given as `NA` are skipped; adjudication is not applied to the integer field group_size (no text rule exists); the embedding threshold is compared unrounded (it was compared after rounding to 4 decimals, which can fail identical strings at a threshold of 1.0).",
          "- Added post-hoc, labelled as such: the strict set-equality measure, the base-rate chance for direction agreement, and taxon coverage by BugSigDB signature source."]
    o = s["ontology_currency"]
    L += ["", "## Taxonomy currency (measured)", "",
          f"Our NCBI Taxonomy snapshot: {o['taxonomy_snapshot']}.", "",
          f"- BugSigDB taxa on the overlap papers: {o['bugsigdb_overlap']['distinct_taxa']}; absent from our snapshot: "
          f"{o['bugsigdb_overlap']['absent_from_snapshot']}; leaf name differs from the current scientific name: "
          f"{o['bugsigdb_overlap']['name_differs_from_current']} of {o['bugsigdb_overlap']['with_bsdb_name']}.",
          f"- Whole BugSigDB dump: {o['bugsigdb_full_dump']['distinct_taxa']} taxa; absent: "
          f"{o['bugsigdb_full_dump']['absent_from_snapshot']}; name differs: {o['bugsigdb_full_dump']['name_differs_from_current']}.",
          f"- Our findings: {o['cdm_findings_distinct_taxa']} taxa; absent from the snapshot: {o['cdm_findings_absent_from_snapshot']}.",
          f"- Overlap signatures by curation year: {o['overlap_signatures_curated_year']}."]
    (OUT / "REPORT.md").write_text("\n".join(L) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["preregister", "run"])
    ap.add_argument("--skip-embed", action="store_true", help="smoke test without the embedding models")
    a = ap.parse_args()
    cmd_preregister() if a.cmd == "preregister" else cmd_run(a.skip_embed)


if __name__ == "__main__":
    main()
