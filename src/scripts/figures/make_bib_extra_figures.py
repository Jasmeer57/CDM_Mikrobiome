"""Additional figures for the BiB submission, modelled on the figure types of comparable papers (BugSigDB, Chen et al.
2025, MINERVA, DiMB-RE, HunFlair2, GMrepo). Every number is computed from the frozen CDM 3.0.3 (read-only), the
result summaries or the entity registry; nothing is typed in.

  figA_resource_overview      papers by year, condition, body site, country
  figB_traced_example         one finding traced from the sentence to the CDM rows (CC BY paper)
  figC_ner_error_breakdown    correct / wrong type / not an entity per NER configuration
  figD_quality_quantity       valid entities found vs share valid, per configuration
  figE_benchmark_transfer     public BioRED F1 vs corpus grounding, per entity type
  figF_taxon_condition        reported directions per genus x condition, with independent BugSigDB consensus
  figG_speed_quality          seconds per document vs BioRED F1
  figH_validation_layers      found in evidence / passed each judge, per catalogue table
  fig3_cdm_architecture       10 modules, 33 entities, row counts and population status

    python make_bib_extra_figures.py      # normally: sbatch make_bib_extra_figures.sbatch
"""
from __future__ import annotations

import csv
import json
import re
import sqlite3
import sys
import textwrap
from collections import Counter, defaultdict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

import make_bib_figures as M  # noqa: E402  (palette, style helpers, loaded summaries)

ROOT = M.ROOT
sys.path.insert(0, str(ROOT / "src/scripts/bugsigdb_comparison"))
import compare as BC  # noqa: E402  (taxonomy, BugSigDB and country helpers)

CDM = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
QQ = json.load(open(ROOT / "outputs/results/benchmark/ner_quality_quantity_2026-11-03/summary.json"))
BA = json.load(open(ROOT / "paper/publication/final_validation/benchmark/benchmark_analysis.json"))
FAIR = json.load(open(ROOT / "outputs/results/benchmark/ner_fair_bench/fair_ner_metrics.json"))
JS = json.load(open(ROOT / "paper/publication/final_validation/evidence_judge/judge_summary.json"))
DS = json.load(open(ROOT / "paper/publication/final_validation/evidence_judge/deterministic_summary.json"))
REGISTRY = ROOT / "releases/cdm_v3/3.0.3/remediation/UPDATED_ENTITY_REGISTRY_PROPOSAL.csv"
S1, S2, S3 = M.SERIES
NEUTRAL = "#c9c8c3"
KCOL = {"trained": S1, "zero": S2, "llm": S3}

# Condition categories: fixed keyword rules, applied identically to our papers and to BugSigDB conditions.
CONDITIONS = [
    ("Colorectal cancer", r"colorectal|colon cancer|rectal cancer|\bcrc\b|adenoma"),
    ("IBD", r"crohn|ulcerative colitis|inflammatory bowel|\bibd\b"),
    ("IBS", r"irritable bowel|\bibs\b"),
    ("Obesity", r"obes|overweight|bariatric"),
    ("Diabetes", r"diabet|\bt[12]d\b|insulin resistance"),
    ("Liver disease", r"cirrho|liver disease|nafld|masld|nash|steatohepatitis|cholangitis|hepatitis"),
    ("C. difficile", r"difficile|\bcdi\b"),
    ("HIV", r"\bhiv\b|human immunodeficiency"),
    ("Cardiovascular", r"cardiovascular|hypertension|atheroscl|heart failure|coronary"),
    ("Kidney disease", r"kidney|renal|dialysis"),
    ("Allergy / asthma", r"asthma|allerg|atopic|eczema|rhinitis"),
    ("Autism", r"autis|\basd\b"),
    ("Parkinson's", r"parkinson"),
    ("Depression / psychiatric", r"depress|schizophren|bipolar|anxiety"),
    ("Multiple sclerosis", r"multiple sclerosis"),
    ("Rheumatic disease", r"rheumatoid|arthritis|lupus|spondyl"),
    ("Critical illness / sepsis", r"critical(ly)? ill|intensive care|\bicu\b|sepsis"),
    ("Cancer (other)", r"cancer|tumou?r|carcinoma|leuk(a)?emia|lymphoma|melanoma"),
]


def conditions(text: str) -> set[str]:
    t = (text or "").lower()
    hits = {name for name, rx in CONDITIONS if re.search(rx, t)}
    if "Colorectal cancer" in hits:
        hits.discard("Cancer (other)")
    return hits


def country_fn():
    """Country rules of the BugSigDB comparison, minus continent names ("North America" is not the USA)."""
    base = BC.country_index()

    def f(text):
        t = re.sub(r"(?i)\b(north|south|latin|central)\s+america\b|\bafrican[- ]american\b", " ", text or "")
        t = re.sub(r"(?i)(?<!united states of )\bamerica\b", " ", t)
        return base(t)
    return f


def db():
    return sqlite3.connect(f"file:{CDM}?mode=ro", uri=True)


def hbars(ax, labels, values, color=S1, fmt="{:,}", xlabel=""):
    y = np.arange(len(labels))[::-1]
    ax.barh(y, values, height=0.62, color=color, edgecolor="white", linewidth=0.8)
    for yy, v in zip(y, values):
        ax.text(v + max(values) * 0.015, yy, fmt.format(v), va="center", fontsize=5.8, color=M.INK)
    ax.set_yticks(y, labels, fontsize=6)
    M.style(ax, xlabel, max(values) * 1.18)


def title(ax, s):
    ax.set_title(s, loc="left", fontsize=7, fontweight="bold", color=M.INK)


# ------------------------------------------------------------------ A: resource overview
def paper_conditions(c):
    out = {}
    for pid, t, hc in c.execute("SELECT p.paper_id, p.title, s.health_conditions FROM paper p LEFT JOIN study s USING (paper_id)"):
        out[pid] = conditions(f"{t} {hc}")
    return out


def figA(c):
    fig, axs = plt.subplots(2, 2, figsize=(7.0, 5.0), gridspec_kw={"hspace": 0.55, "wspace": 0.75})
    years = Counter(y for (y,) in c.execute("SELECT publication_year FROM paper") if y)
    ys = sorted(years)
    ax = axs[0, 0]
    ax.bar(range(len(ys)), [years[y] for y in ys], color=S1, edgecolor="white", linewidth=0.8, width=0.7)
    ax.set_xticks(range(len(ys)), ys, rotation=90, fontsize=5.8)
    ax.yaxis.grid(True, color=M.GRID, lw=0.5)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.set_ylabel("Papers", fontsize=6.5, color=M.INK2)
    missing = sum(1 for (y,) in c.execute("SELECT publication_year FROM paper") if not y)
    title(ax, f"a  Publication year (n={sum(years.values())}; {missing} without year)")
    cond = Counter(x for v in paper_conditions(c).values() for x in v)
    top = cond.most_common(12)
    hbars(axs[0, 1], [k for k, _ in top], [v for _, v in top], xlabel="Papers (keyword rules on title + condition)")
    title(axs[0, 1], "b  Conditions studied (top 12)")
    sites = c.execute("SELECT body_site_normalized, COUNT(DISTINCT paper_id) FROM sample WHERE body_site_normalized != '' "
                      "GROUP BY 1 ORDER BY 2 DESC LIMIT 10").fetchall()
    hbars(axs[1, 0], [s for s, _ in sites], [n for _, n in sites], xlabel="Papers with a sample group from this site")
    title(axs[1, 0], "c  Body sites (top 10)")
    countries = country_fn()
    import pycountry
    per = defaultdict(set)
    for pid, a in c.execute("SELECT paper_id, country_region FROM study UNION ALL SELECT paper_id, country_or_region FROM cohort"):
        for code in countries(a or ""):
            per[code].add(pid)
    top = sorted(per.items(), key=lambda kv: -len(kv[1]))[:12]
    name = lambda code: {"US": "USA", "GB": "UK", "KR": "South Korea", "CN": "China"}.get(code) or pycountry.countries.get(alpha_2=code).name
    hbars(axs[1, 1], [name(k) for k, _ in top], [len(v) for _, v in top], xlabel="Papers (country named in study or cohort)")
    n_with = len(set().union(*per.values()))
    title(axs[1, 1], f"d  Countries (top 12; {n_with} papers with a country)")
    M.save(fig, "figA_resource_overview")


# ------------------------------------------------------------------ B: traced example
def figB(c):
    pid = "HMPAPER_000258"
    rows = c.execute("""SELECT finding_id, taxon_or_feature, taxon_ncbi_ids, taxon_ncbi_names, direction, comparison_or_exposure,
                               body_site, evidence_text, COALESCE(evidence_section_id, section_id), char_start, char_end, extraction_model, extraction_run_id,
                               cohort_id, assay_id
                        FROM claim WHERE paper_id = ? AND claim_source = 'catalogue_v3_1' AND taxon_ncbi_ids LIKE 'NCBITaxon:%'
                        AND direction IN ('INCREASE','DECREASE','increased','decreased') AND evidence_text != ''""", (pid,)).fetchall()
    rows.sort(key=lambda r: len(r[7] or ""))
    f = rows[0]
    (fid, taxon, tids, tnames, direction, comp, site, ev, sec, cs, ce, model, prompt, coh, assay) = f
    p = c.execute("SELECT title, doi, pmcid, license_name, journal, publication_year FROM paper WHERE paper_id = ?", (pid,)).fetchone()
    srow = c.execute("SELECT section_name_normalized, character_count, text_hash_sha256 FROM section "
                     "WHERE paper_id = ? AND section_id_original = ?", (pid, sec)).fetchone() or ("?", 0, "")
    fig, ax = plt.subplots(figsize=(7.0, 3.6))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 60)
    ax.axis("off")

    def box(x, y, w, h, head, body, col, fs=5.6):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=1.0", fc=M.SURFACE, ec=col, lw=0.9))
        ax.add_patch(FancyBboxPatch((x, y + h - 4), w, 4, boxstyle="round,pad=0,rounding_size=1.0", fc=col, ec=col, lw=0.9))
        ax.text(x + 1.2, y + h - 2, head, va="center", color="white", fontsize=6.2, fontweight="bold")
        ax.text(x + 1.2, y + h - 5.4, body, va="top", color=M.INK, fontsize=fs, linespacing=1.3)

    def arrow(a, b, label=""):
        ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=6, color=M.INK2, lw=0.8))
        if label:
            ax.text((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + 1.2, label, ha="center", fontsize=5.2, color=M.INK2, style="italic")

    wrap = lambda s, w: "\n".join(textwrap.wrap(s, w))
    box(1, 31, 30, 28, "Paper (CC BY)", wrap(p[0], 40) + f"\n{p[4]} {p[5]}\ndoi:{p[1]}\n{p[2]} · {pid}", S1)
    box(1, 1, 30, 27, f"Section: {srow[0]}", f"{srow[1]:,} characters\nSHA-256 {srow[2][:16]}…\n\nEvidence quote, chars {cs}–{ce}:\n"
        + wrap(f"“{ev.strip()}”", 42)[:420], S1, fs=5.3)
    tid = re.findall(r"NCBITaxon:\d+", tids)[0]
    box(36, 17, 30, 42, "Catalogue finding", f"{fid}\n\ntaxon: {taxon}\n  → {tid}\n     ({tnames.split(';')[0].strip()})\ndirection: {direction}\n"
        f"comparison:\n  {wrap(comp or '–', 30).replace(chr(10), chr(10) + '  ')}\nbody site: {site or '–'}\ncohort: {coh or '–'}\nassay: {assay or '–'}", S2)
    box(71, 31, 28, 28, "Provenance", f"model: {model}\nrun: {(prompt or '–')[:22]}…\nquote anchored to\n  {sec}, chars {cs}–{ce}\nsection hash verified", S3)
    box(71, 1, 28, 27, "CDM 3.0.3 rows", "PAPER → SECTION\n  → CLAIM_EVIDENCE → CLAIM\nCLAIM → COHORT, ASSAY\nCLAIM → NCBI Taxonomy\nEXTRACTION_RUN → CLAIM", S1)
    arrow((31, 44), (36, 44), "")
    arrow((31, 15), (36, 25), "anchored quote")
    arrow((66, 44), (71, 44))
    arrow((66, 25), (71, 15))
    M.save(fig, "figB_traced_example")
    return {"paper": pid, "finding": fid, "doi": p[1]}


# ------------------------------------------------------------------ C: error breakdown
def figC():
    rows = []
    for k, v in M.LJ["benchmark"].items():
        d = v["distinct"]
        rows.append((k, d["valid_type"] / d["d"], (d["valid"] - d["valid_type"]) / d["d"], (d["d"] - d["valid"]) / d["d"]))
    rows.sort(key=lambda r: r[1])
    fig, ax = plt.subplots(figsize=(5.0, 5.2))
    y = np.arange(len(rows))
    for i, (lab, col) in enumerate([("Valid entity, correct type", S1), ("Valid entity, wrong type", S2), ("Not an entity", NEUTRAL)]):
        left = [sum(r[1 + j] for j in range(i)) * 100 for r in rows]
        ax.barh(y, [r[1 + i] * 100 for r in rows], left=left, height=0.66, color=col, edgecolor="white", linewidth=0.8, label=lab)
    for yy, r in zip(y, rows):
        ax.text(1, yy, f"{100 * r[1]:.0f}", va="center", fontsize=5.4, color="white", fontweight="bold")
    ax.set_yticks(y, [f"{r[0]}  ({M.KIND[M.kind(r[0])].split()[0]})" for r in rows], fontsize=5.8)
    M.style(ax, "Distinct strings, judged by DeepSeek (%)")
    ax.legend(loc="upper center", bbox_to_anchor=(0.45, 1.06), ncol=3, fontsize=5.8, frameon=False)
    M.save(fig, "figC_ner_error_breakdown")


# ------------------------------------------------------------------ D: quality vs quantity
def figD():
    fig, ax = plt.subplots(figsize=(5.0, 3.6))
    pc = QQ["per_config"]
    for k, d in pc.items():
        ax.scatter(d["valid_typed_distinct"] / 1000, d["quality_pct"], s=22, color=KCOL[M.kind(k)], edgecolor="white", linewidth=0.8, zorder=3)
    best_q = sorted(pc, key=lambda k: -pc[k]["quality_pct"])[:3]
    best_n = sorted(pc, key=lambda k: -pc[k]["valid_typed_distinct"])[:3]
    for k in dict.fromkeys(best_q + best_n + ["hunflair2", "llm_qwen_fs", "llm_llama_zs", "llm_gemma_zs"]):
        d = pc[k]
        off = {"llm_gemma_zs": (-4, -9), "bert_disease": (5, -3), "gliner2_large": (4, -9)}.get(k, (4, 3))
        ax.annotate(k, (d["valid_typed_distinct"] / 1000, d["quality_pct"]), xytext=off, textcoords="offset points",
                    fontsize=5.4, color=M.INK, ha="right" if off[0] < 0 else "left")
    ax.grid(True, color=M.GRID, lw=0.5)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.set_xlabel("Valid, correctly typed distinct entities found (thousands)", fontsize=6.5, color=M.INK2)
    ax.set_ylabel("Share of output valid and correctly typed (%)", fontsize=6.5, color=M.INK2)
    ax.set_xlim(0, max(d["valid_typed_distinct"] for d in pc.values()) / 1000 * 1.18)
    ax.set_ylim(0, 70)
    ax.legend(handles=[plt.Line2D([], [], marker="o", ls="", color=KCOL[k], markersize=5) for k in KCOL],
              labels=list(M.KIND.values()), loc="upper right", fontsize=5.8, frameon=False)
    title(ax, f"Quality and quantity on all {QQ['papers']} papers")
    M.save(fig, "figD_quality_quantity")


# ------------------------------------------------------------------ E: benchmark transfer
def figE():
    pv = BA["public_vs_corpus"]
    types = [("DiseaseOrPhenotypicFeature", "Disease"), ("ChemicalEntity", "Chemical"), ("GeneOrGeneProduct", "Gene"),
             ("OrganismTaxon", "Organism")]
    fig, axs = plt.subplots(1, 4, figsize=(7.0, 2.1), sharey=False, gridspec_kw={"wspace": 0.45})
    for ax, (t, lab) in zip(axs, types):
        pts = pv["pairs"][t]
        for p_ in pts:
            k = "llm" if p_["kind"].startswith("LLM") else "zero" if "zero" in p_["kind"] else "trained"
            ax.scatter(p_["biored_exact_f1"], p_["corpus_grounded_pct"], s=14, color=KCOL[k], edgecolor="white", linewidth=0.6, zorder=3)
        ax.grid(True, color=M.GRID, lw=0.5)
        ax.set_axisbelow(True)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        rho = pv["correlation"][t]["spearman_f1_vs_grounding"]
        title(ax, f"{lab}  ρ = {rho:.2f}")
        ax.set_xlabel("BioRED exact F1", fontsize=6, color=M.INK2)
        ax.tick_params(labelsize=5.6)
    axs[0].set_ylabel("Grounded on corpus (%)", fontsize=6, color=M.INK2)
    axs[-1].legend(handles=[plt.Line2D([], [], marker="o", ls="", color=KCOL[k], markersize=4) for k in KCOL],
                   labels=list(M.KIND.values()), fontsize=5.4, frameon=False, loc="upper left", bbox_to_anchor=(1.0, 1.0))
    M.save(fig, "figE_benchmark_transfer")


# ------------------------------------------------------------------ F: taxon x condition
def figF(c):
    parent, rank, tname, genus = BC.load_taxonomy()
    pcond = paper_conditions(c)
    dmap = {"INCREASE": 1, "increased": 1, "DECREASE": -1, "decreased": -1}
    ours = defaultdict(lambda: defaultdict(set))   # (genus, condition) -> direction -> papers
    for pid, ids, d in c.execute("SELECT paper_id, taxon_ncbi_ids, direction FROM claim WHERE claim_source = 'catalogue_v3_1' "
                                 "AND taxon_ncbi_ids LIKE 'NCBITaxon:%'"):
        if d not in dmap:
            continue
        for t in {int(x) for x in re.findall(r"NCBITaxon:(\d+)", ids)}:
            g = genus(t)
            if g not in rank or rank[g] != "genus":
                continue
            for cond in pcond.get(pid, ()):
                ours[(g, cond)][dmap[d]].add(pid)
    # independent BugSigDB consensus: exclude signatures from papers in our corpus
    pm = {str(x) for (x,) in c.execute("SELECT pmid FROM paper WHERE pmid != ''")}
    dois = {x.lower() for (x,) in c.execute("SELECT doi FROM paper WHERE doi != ''")}
    _, rows = BC.load_bugsigdb()
    bs = defaultdict(Counter)
    for r in rows:
        if (r.get("PMID") or "").split(".")[0] in pm or (r.get("DOI") or "").lower() in dois:
            continue
        d = {"increased": 1, "decreased": -1}.get(r["Abundance in Group 1"])
        if not d:
            continue
        cs = conditions(r.get("Condition") or "")
        for lin in (r["NCBI Taxonomy IDs"] or "").split(";"):
            leaf = lin.split("|")[-1].strip()
            if not leaf.isdigit():
                continue
            g = genus(int(leaf))
            if g in rank and rank[g] == "genus":
                for cond in cs:
                    bs[(g, cond)][d] += 1
    cells = {k: v for k, v in ours.items() if len(v[1] | v[-1]) >= 2}
    cond_n = Counter(k[1] for k in cells)
    gen_n = Counter(k[0] for k in cells)
    conds = [k for k, _ in cond_n.most_common(10)]
    gens = [g for g, _ in gen_n.most_common(60) if sum((g, cc) in cells for cc in conds) >= 2][:22]
    mat = np.full((len(gens), len(conds)), np.nan)
    agree = Counter()
    fig, ax = plt.subplots(figsize=(6.2, 6.9))
    fig.subplots_adjust(bottom=0.2)
    for i, g in enumerate(gens):
        for j, cc in enumerate(conds):
            v = cells.get((g, cc))
            if not v:
                continue
            up, dn = len(v[1]), len(v[-1])
            mat[i, j] = (up - dn) / (up + dn)
            b = bs.get((g, cc), Counter())
            nb = b[1] + b[-1]
            mark = ""
            if nb >= 3 and max(b[1], b[-1]) / nb >= 2 / 3 and up != dn:
                same = (b[1] > b[-1]) == (up > dn)
                mark = "✓" if same else "✗"
                agree["same" if same else "opposite"] += 1
            ax.text(j, i, f"{up + dn}{mark}", ha="center", va="center", fontsize=5.0,
                    color="white" if abs(mat[i, j]) > 0.6 else M.INK)
    cmap = LinearSegmentedColormap.from_list("div", ["#1c5cab", "#f0efec", "#c43b3a"])
    im = ax.imshow(mat, cmap=cmap, vmin=-1, vmax=1, aspect="auto")
    ax.set_xticks(range(len(conds)), conds, rotation=40, ha="right", fontsize=6)
    ax.set_yticks(range(len(gens)), [tname.get(g, str(g)) for g in gens], fontsize=6, style="italic")
    ax.set_xticks(np.arange(-0.5, len(conds)), minor=True)
    ax.set_yticks(np.arange(-0.5, len(gens)), minor=True)
    ax.grid(which="minor", color="white", lw=1.2)
    ax.tick_params(which="both", length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    cb = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02, ticks=[-1, 0, 1])
    cb.ax.set_yticklabels(["all decreased", "mixed", "all increased"], fontsize=5.6)
    cb.outline.set_visible(False)
    tot = sum(agree.values())
    title(ax, "Reported direction per genus and condition (catalogue findings)")
    fig.text(0.02, 0.01, f"Cell number = papers reporting the genus up or down for that condition. ✓/✗ = same/opposite to the independent "
             f"BugSigDB consensus\n(signatures from papers outside our corpus; ≥3 signatures, ≥2/3 one direction): {agree['same']} of {tot} "
             f"comparable cells agree. Reported findings, not a meta-analysis.", fontsize=5.4, color=M.INK2)
    M.save(fig, "figF_taxon_condition")
    return {"cells_compared": tot, "same": agree["same"], "opposite": agree["opposite"], "genera": len(gens), "conditions": conds}


# ------------------------------------------------------------------ G: speed vs quality
def figG():
    fig, ax = plt.subplots(figsize=(5.0, 3.4))
    pts = []
    for key, v in FAIR.items():
        if not key.startswith("biored__") or "full_schema" not in v:
            continue
        m = v["meta"]
        if not m.get("sec_per_doc") or m["model"] in ("pubtator3", "scispacy_lg"):
            continue
        k = M.kind(m["model"])
        cpu = "CPU" in (m.get("device") or "")
        f1 = 100 * v["full_schema"]["exact"]["F1"]
        pts.append((m["model"], m["sec_per_doc"], f1))
        ax.scatter(m["sec_per_doc"], f1, s=22, marker="s" if cpu else "o", color=KCOL[k], edgecolor="white", linewidth=0.8, zorder=3)
    show = {"hunflair2": (4, 2), "llm_qwen_fs": (4, 3), "llm_gemma_zs": (4, 2), "gliner_v25_biomed": (-4, 4),
            "llm_llama_zs": (-4, 5), "bert_chemical": (4, -7)}
    for name, x, y in pts:
        if name in show:
            dx, dy = show[name]
            ax.annotate(name, (x, y), xytext=(dx, dy), textcoords="offset points", fontsize=5.3, color=M.INK,
                        ha="right" if dx < 0 else "left")
    ax.set_xscale("log")
    ax.grid(True, color=M.GRID, lw=0.5, which="major")
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.set_xlabel("Seconds per abstract (log scale; BioRED test set)", fontsize=6.5, color=M.INK2)
    ax.set_ylabel("BioRED exact F1, all types (%)", fontsize=6.5, color=M.INK2)
    h = [plt.Line2D([], [], marker="o", ls="", color=KCOL[k], markersize=5) for k in KCOL]
    h += [plt.Line2D([], [], marker="o", ls="", color=M.INK2, markersize=5), plt.Line2D([], [], marker="s", ls="", color=M.INK2, markersize=5)]
    ax.legend(handles=h, labels=list(M.KIND.values()) + ["GPU (A40)", "CPU (8 cores)"], fontsize=5.6, frameon=False,
              loc="upper left", bbox_to_anchor=(1.01, 1.0))
    title(ax, "Speed and accuracy on the public benchmark")
    M.save(fig, "figG_speed_quality")


# ------------------------------------------------------------------ H: validation layers
def figH():
    tables = ["claim", "cohort", "sample", "assay", "dataset", "data_asset"]
    label = {"claim": "Findings", "cohort": "Cohorts", "sample": "Sample groups", "assay": "Assays", "dataset": "Datasets", "data_asset": "Data assets"}
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(7.0, 3.4), gridspec_kw={"width_ratios": [1, 1.6], "wspace": 0.6})
    vals = []
    for t in tables:
        d = DS.get(f"{t}|text_in_evidence", {})
        n = d.get("FOUND", 0) + d.get("NOT_FOUND", 0)
        vals.append(100 * d.get("FOUND", 0) / n if n else 0)
    y = np.arange(len(tables))[::-1]
    a1.barh(y, vals, height=0.62, color=S1, edgecolor="white", linewidth=0.8)
    for yy, v in zip(y, vals):
        a1.text(v + 1.5, yy, f"{v:.0f}%", va="center", fontsize=5.6, color=M.INK)
    a1.set_yticks(y, [label[t] for t in tables], fontsize=6)
    M.style(a1, "Text values found in their evidence (%)", 100)
    title(a1, "a  Deterministic check")
    cats = [("PASS", "Supported", S1), ("UNCERTAIN", "Uncertain", NEUTRAL), ("FAIL", "Not supported", S2), ("INVALID", "Invalid answer", "#8a8985")]
    rows, ylab = [], []
    for t in tables:
        for j, jn in (("llama", "Llama"), ("mistral", "Mistral")):
            d = JS[j]["fields"].get(f"{t}|text_value", {})
            n = sum(d.values()) or 1
            rows.append([100 * d.get(c_, 0) / n for c_, _, _ in cats])
            ylab.append(f"{label[t]} · {jn}")
    yy = np.arange(len(rows))[::-1]
    left = np.zeros(len(rows))
    for i, (_, lab, col) in enumerate(cats):
        v = np.array([r[i] for r in rows])
        a2.barh(yy, v, left=left, height=0.7, color=col, edgecolor="white", linewidth=0.6, label=lab)
        left += v
    a2.set_yticks(yy, ylab, fontsize=5.6)
    M.style(a2, "Text values judged by each model (%)", 100)
    a2.legend(fontsize=5.6, frameon=False, ncol=4, loc="lower center", bbox_to_anchor=(0.45, 1.0))
    a2.text(0, 1.11, "b  Model judges (Llama also took part in curation)", transform=a2.transAxes, fontsize=7, fontweight="bold", color=M.INK)
    M.save(fig, "figH_validation_layers")


# ------------------------------------------------------------------ CDM architecture
def fig3(c):
    reg = list(csv.DictReader(open(REGISTRY, encoding="utf-8")))
    tables = {t: c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    mods = defaultdict(list)
    for r in reg:
        mods[r["module"]].append(r)
    grid = {  # (column, row): linked modules sit side by side or one above the other
        "M1_source_documents": (0, 0), "M2_document_structure": (1, 0), "M4_terminology": (2, 0), "M5_semantic_mappings": (3, 0),
        "M3_processing": (4, 0), "M9_quality_review": (0, 1), "M8_evidence": (1, 1), "M7_findings": (2, 1),
        "M6_research_context": (3, 1), "M10_catalogue_releases": (4, 1)}
    nice = lambda m: m.split("_", 1)[0] + " " + m.split("_", 1)[1].replace("_", " ")
    fig, ax = plt.subplots(figsize=(7.0, 4.4))
    ax.set_xlim(0, 100)
    ax.set_ylim(-4, 66)
    ax.axis("off")
    w, gap, eh = 19.2, 1.0, 3.7
    pos = {}

    def fmt(n):
        return f"{n / 1e6:.1f}M" if n >= 1e6 else f"{n / 1e3:.0f}k" if n >= 1e4 else f"{n:,}"
    for m, (col, row) in grid.items():
        ents = mods[m]
        x = col * (w + gap)
        top = 62 if row == 0 else 29
        h = 5.0 + eh * len(ents) + 0.8
        ax.add_patch(FancyBboxPatch((x, top - h), w, h, boxstyle="round,pad=0,rounding_size=0.9", fc="white", ec=M.INK2, lw=0.7))
        ax.text(x + w / 2, top - 2.2, nice(m), ha="center", va="center", fontsize=5.2, fontweight="bold", color=M.INK)
        pos[m] = (x, top - h, w, h)
        for j, r in enumerate(ents):
            ey = top - 4.6 - eh * (j + 1) + 0.5
            n = tables.get(r["entity"].lower())
            if r["status"] == "PLANNED":
                fc, ec, ls, txt, val = "white", M.CHANCE, (0, (1, 1.5)), M.INK2, "0"
            elif n is None:
                fc, ec, ls, txt, val = "white", S1, (0, (3, 2)), M.INK, ""
            elif r["status"] == "PARTIAL_POPULATED":
                fc, ec, ls, txt, val = "#cde2fb", S1, "-", M.INK, fmt(n)
            else:
                fc, ec, ls, txt, val = S1, S1, "-", "white", fmt(n)
            ax.add_patch(FancyBboxPatch((x + 0.8, ey), w - 1.6, eh - 0.6, boxstyle="round,pad=0,rounding_size=0.5",
                                        fc=fc, ec=ec, lw=0.7, ls=ls))
            ax.text(x + 1.5, ey + (eh - 0.6) / 2, r["entity"], va="center", fontsize=4.0 if len(r["entity"]) > 17 else 4.2, color=txt)
            ax.text(x + w - 1.5, ey + (eh - 0.6) / 2, val, va="center", ha="right", fontsize=4.2, color=txt)

    def link(a, b, label):
        xa, ya, wa, ha = pos[a]
        xb, yb, wb, hb = pos[b]
        if abs(xa - xb) < 1:             # one above the other
            p1, p2 = (xa + wa / 2, ya), (xb + wb / 2, yb + hb)
            lx, ly, ha_ = p1[0] + 0.8, (p1[1] + p2[1]) / 2, "left"
        else:                            # side by side
            yl = min(ya + ha, yb + hb) - 3.2
            p1, p2 = ((xa + wa, yl), (xb, yl)) if xb > xa else ((xa, yl), (xb + wb, yl))
            lx, ly, ha_ = (p1[0] + p2[0]) / 2, yl + 1.2, "center"
        ax.add_patch(FancyArrowPatch(p1, p2, arrowstyle="-|>", mutation_scale=5, color=M.INK2, lw=0.7))
        ax.text(lx, ly, label, ha=ha_, fontsize=4.3, color=M.INK2, style="italic")
    link("M1_source_documents", "M2_document_structure", "")
    link("M2_document_structure", "M4_terminology", "")
    link("M4_terminology", "M5_semantic_mappings", "")
    link("M2_document_structure", "M8_evidence", "anchored text")
    link("M8_evidence", "M7_findings", "")
    link("M4_terminology", "M7_findings", "triple terms")
    link("M6_research_context", "M7_findings", "")
    leg = [(S1, S1, "-", "populated table"), ("#cde2fb", S1, "-", "partially populated"),
           ("white", S1, (0, (3, 2)), "embedded in another table"), ("white", M.CHANCE, (0, (1, 1.5)), "planned (0 rows)")]
    for i, (fc, ec, ls, lab) in enumerate(leg):
        ax.add_patch(FancyBboxPatch((1 + i * 24, -3.4), 3, 2.0, boxstyle="round,pad=0,rounding_size=0.4", fc=fc, ec=ec, lw=0.8, ls=ls))
        ax.text(5 + i * 24, -2.4, lab, va="center", fontsize=5.2, color=M.INK)
    ax.text(0, 64.5, f"CDM 3.0.3: {len(reg)} entities in 10 modules, row counts from the released database. Every record also links "
            "to its PAPER and EXTRACTION_RUN (M3).", fontsize=5.2, color=M.INK2)
    M.save(fig, "fig3_cdm_architecture")
    return {"entities": len(reg), "status": dict(Counter(r["status"] for r in reg)),
            "embedded": [r["entity"] for r in reg if r["entity"].lower() not in tables and r["status"] != "PLANNED"]}


if __name__ == "__main__":
    c = db()
    out = {}
    figA(c)
    out["B"] = figB(c)
    figC()
    figD()
    figE()
    figG()
    figH()
    out["cdm"] = fig3(c)
    out["F"] = figF(c)
    (M.OUT / "figures" / "extra_figures_facts.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(json.dumps(out, indent=1, ensure_ascii=False))
