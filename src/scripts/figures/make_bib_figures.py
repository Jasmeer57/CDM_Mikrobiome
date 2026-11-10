"""Figures and tables for the Briefings in Bioinformatics submission (plan: paper/publication/manuscript_bib/).

Every number is read from the claims register or a result summary, never typed in. Static print figures
(PDF + 600 dpi PNG), light mode only; palette = first three categorical slots of the dataviz reference
palette (validated all-pairs, light) plus a neutral grey for chance baselines.

    python make_bib_figures.py
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
OUT = ROOT / "paper/publication/manuscript_bib"
REG = {r["claim_id"]: r for r in csv.DictReader(open(ROOT / "paper/publication/final_validation/MANUSCRIPT_CLAIMS_REGISTER.csv", encoding="utf-8"))}
LJ = json.load(open(ROOT / "outputs/results/benchmark/llm_judge_deepseek_v4_flash/summary.json"))
BS = json.load(open(ROOT / "outputs/results/benchmark/bugsigdb_comparison_2026-11-03/summary.json"))
TR = json.load(open(ROOT / "outputs/results/benchmark/triple_reference_check_2026-11-03/summary.json"))

SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]          # blue, orange, aqua (validated, all pairs, light)
CHANCE, INK, INK2, GRID, SURFACE = "#8a8985", "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 7, "axes.edgecolor": INK2, "axes.labelcolor": INK,
                     "xtick.color": INK2, "ytick.color": INK2, "axes.linewidth": 0.6, "xtick.major.width": 0.6,
                     "ytick.major.width": 0.6, "figure.facecolor": "white", "axes.facecolor": "white",
                     "pdf.fonttype": 42, "svg.fonttype": "none"})

KIND = {"trained": "Trained NER", "zero": "Zero-shot NER", "llm": "Small open LLM"}
MODEL_IDS = {  # from src/cdm_pipeline/ner/registry.py and src/scripts/ner_fair_bench/
    "bert_chemical": "alvaroalon2/biobert_chemical_ner", "bert_disease": "alvaroalon2/biobert_diseases_ner",
    "bert_genetic": "alvaroalon2/biobert_genetic_ner", "scibert_jnlpba": "fran-martinez/scibert_scivocab_cased_ner_jnlpba",
    "hunflair2": "hunflair/hunflair2-ner", "scispacy_bc5cdr": "en_ner_bc5cdr_md (scispaCy)",
    "scispacy_craft": "en_ner_craft_md (scispaCy)", "scispacy_jnlpba": "en_ner_jnlpba_md (scispaCy)",
    "scispacy_bionlp13cg": "en_ner_bionlp13cg_md (scispaCy)", "gliner_v25_medium": "gliner-community/gliner_medium-v2.5",
    "gliner_v25_biomed": "Ihor/gliner-large-v2.5-biomed", "gliner2_base": "fastino/gliner2-base-v1",
    "gliner2_large": "fastino/gliner2-large-v1", "gemma": "google/gemma-4-E4B-it-qat-w4a16-ct", "qwen": "Qwen/Qwen3.5-4B",
    "llama": "hugging-quants/Meta-Llama-3.1-8B-Instruct-AWQ-INT4", "mistral": "TechxGenus/Mistral-7B-Instruct-v0.3-AWQ",
    "phi": "thesven/Phi-3.5-mini-instruct-awq", "deepseek": "casperhansen/deepseek-r1-distill-qwen-7b-awq"}


def kind(cfg):
    return "llm" if cfg.startswith("llm_") else "zero" if cfg.startswith("gliner") else "trained"


def model_id(cfg):
    return MODEL_IDS.get(cfg.split("_")[1], "?") + (" (3-shot)" if cfg.endswith("_fs") else " (zero-shot)") \
        if cfg.startswith("llm_") else MODEL_IDS.get(cfg, "?")


def n(cid, i=None):
    v = REG[cid]["stated"]
    v = v.split("/")[i] if i is not None else v
    return f"{int(float(v)):,}" if float(v).is_integer() else v


def save(fig, name):
    (OUT / "figures").mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / "figures" / f"{name}.pdf", bbox_inches="tight")
    fig.savefig(OUT / "figures" / f"{name}.png", dpi=600, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------- Figure 1: the protocol
def fig1():
    qwen = int(REG["M04"]["stated"]) + int(REG["M05"]["stated"])
    stages = [
        ("1  Corpus", f"{n('C01')} BioProjects\n{n('C02')} publications\n{n('C07')} sections", "BioProject → paper\nlinking; sectioning"),
        ("2  Extraction", f"{n('M01')} mentions\nNER {n('M03')}\nQwen3.5 {qwen:,}\nMeSH {n('M06')}",
         "trained + zero-shot NER,\nsmall LLMs, gazetteer"),
        ("3  Normalisation", f"{n('T02')} terms\n(from {n('T01')})\n{n('P01')} → {n('P02')}\nmapping candidates\n{n('P05')} accepted\n(two models agree)",
         "BioPortal, OLS, UMLS,\nOMOP, NCBI Taxonomy"),
        ("4  CDM", f"{n('K01')} records\n({n('K02')} findings)\n{TR['triples']:,} triples\nCDM 3.0.3 (SQLite)",
         "LLM extraction, anchored\nquotes, char offsets"),
        ("5  Evaluation", "structural checks\nvalue in evidence\nmodel judges\nBugSigDB, CTD", "no human annotation;\npre-registered scoring"),
    ]
    fig, ax = plt.subplots(figsize=(7.0, 2.35))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 40)
    ax.axis("off")
    w, gap = 18.2, 2.2
    for i, (title, body, tools) in enumerate(stages):
        x = i * (w + gap)
        col = SERIES[0] if i < 4 else SERIES[1]
        ax.add_patch(FancyBboxPatch((x, 14), w, 22, boxstyle="round,pad=0,rounding_size=1.0", fc=SURFACE, ec=col, lw=0.9))
        ax.add_patch(FancyBboxPatch((x, 33), w, 4.5, boxstyle="round,pad=0,rounding_size=1.0", fc=col, ec=col, lw=0.9))
        ax.text(x + w / 2, 35.25, title, ha="center", va="center", color="white", fontsize=6.6, fontweight="bold")
        ax.text(x + w / 2, 32, body, ha="center", va="top", color=INK, fontsize=5.9, linespacing=1.3)
        ax.text(x + w / 2, 12.6, tools, ha="center", va="top", color=INK2, fontsize=5.9, linespacing=1.25, style="italic")
        if i < 4:
            ax.add_patch(FancyArrowPatch((x + w + 0.2, 25), (x + w + gap - 0.2, 25), arrowstyle="-|>", mutation_scale=6,
                                         color=INK2, lw=0.8, zorder=5))
    save(fig, "fig1_protocol")


# ---------------------------------------------------------------- Figure 4: what each program contributed
def wbar(ax, y, val, ci, color, label=True, fmt="{:.1f}%"):
    ax.barh(y, val, height=0.62, color=color, edgecolor="white", linewidth=0.8)
    if ci:
        ax.plot([ci[0], ci[1]], [y, y], color=INK2, lw=0.7, solid_capstyle="butt")
    if label:
        ax.text((ci[1] if ci else val) + 1.5, y, fmt.format(val), va="center", ha="left", color=INK, fontsize=6)


def style(ax, xlabel, xmax=100):
    ax.set_xlim(0, xmax)
    ax.xaxis.grid(True, color=GRID, lw=0.5)
    ax.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.set_xlabel(xlabel, fontsize=6.5, color=INK2)


def fig4():
    fig = plt.figure(figsize=(7.0, 6.4))
    gs = fig.add_gridspec(3, 2, width_ratios=[1.0, 1], hspace=0.62, wspace=0.95)
    # (a) DeepSeek-judged validity per NER configuration
    ax = fig.add_subplot(gs[:, 0])
    rows = sorted(((100 * v["distinct"]["valid_type"] / v["distinct"]["d"], k) for k, v in LJ["benchmark"].items()))
    for y, (val, k) in enumerate(rows):
        wbar(ax, y, val, None, SERIES[list(KIND).index(kind(k))])
    ax.set_yticks(range(len(rows)), [k for _, k in rows], fontsize=6)
    style(ax, "Distinct strings judged valid and correctly typed (%)", 75)
    ax.set_title("a  NER configurations (DeepSeek-judged, 453 papers)", loc="left", fontsize=7, fontweight="bold", color=INK)
    ax.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=SERIES[i]) for i in range(3)], labels=list(KIND.values()),
              loc="lower right", fontsize=6, frameon=True, framealpha=1, edgecolor="white")
    # (b) BugSigDB metadata concordance vs chance
    ax = fig.add_subplot(gs[0, 1])
    fields = [("region_16s", "16S region"), ("country", "Country"), ("condition", "Condition †"),
              ("statistical_test", "Statistical test"), ("group_size", "Group size"), ("group_name", "Group name †")]
    for y, (f, lab) in enumerate(reversed(fields)):
        s = BS["fields"][f]
        wbar(ax, y, 100 * s["concordance"], [100 * x for x in s["concordance_wilson"]], SERIES[0])
        ax.plot([100 * s["chance"]] * 2, [y - 0.36, y + 0.36], color=CHANCE, lw=1.6)
    ax.set_yticks(range(len(fields)), [lab for _, lab in reversed(fields)], fontsize=6)
    style(ax, "Concordance with BugSigDB (%); grey tick = chance")
    ax.set_title("b  Study metadata vs human curation", loc="left", fontsize=7, fontweight="bold", color=INK)
    # (c) taxon coverage by signature source
    ax = fig.add_subplot(gs[1, 1])
    src = BS["taxa"]["catalogue"]["posthoc_coverage_by_source"]
    order = ["Supplement", "Figure", "Table", "Text"]
    for y, k in enumerate(order):
        s = src[k]
        wbar(ax, y, 100 * s["coverage"], [100 * x for x in s["wilson"]], SERIES[0])
    ax.set_yticks(range(len(order)), [f"{k} (n={src[k]['items']})" for k in order], fontsize=6)
    style(ax, "BugSigDB taxa covered by catalogue findings (%)")
    ax.set_title("c  Taxon coverage by where BugSigDB found it", loc="left", fontsize=7, fontweight="bold", color=INK)
    # (d) triples: taxon in BugSigDB for the same paper, by cleaning stratum
    ax = fig.add_subplot(gs[2, 1])
    st = TR["bugsigdb"]["support"]
    order = [("dropped", "Dropped by cleaning"), ("kept", "Kept by cleaning"), ("all", "All triples")]
    for y, (k, lab) in enumerate(order):
        wbar(ax, y, 100 * st[k]["rate"], [100 * x for x in st[k]["wilson"]], SERIES[0])
    ch = 100 * TR["bugsigdb"]["support_chance"]
    ax.axvline(ch, color=CHANCE, lw=1.2, ls=(0, (3, 2)))
    ax.text(ch + 1, 2.55, f"chance {ch:.1f}%", color=INK2, fontsize=5.8, va="center")
    ax.set_yticks(range(len(order)), [f"{lab} (n={st[k]['n']})" for k, lab in order], fontsize=6)
    style(ax, "Triple's taxon in BugSigDB for the same paper (%)")
    ax.set_ylim(-0.6, 2.9)
    ax.set_title("d  Microbe triples vs BugSigDB", loc="left", fontsize=7, fontweight="bold", color=INK)
    fig.text(0.53, 0.005, "Whiskers: 95% Wilson intervals.  † SapBERT embedding match, threshold from a cross-paper null.",
             fontsize=5.8, color=INK2)
    save(fig, "fig4_results")


# ---------------------------------------------------------------- tables
def write_table(name, header, rows, note=""):
    (OUT / "tables").mkdir(parents=True, exist_ok=True)
    with open(OUT / "tables" / f"{name}.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)
    md = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)] + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    (OUT / "tables" / f"{name}.md").write_text("\n".join(md) + ("\n\n" + note if note else "") + "\n")


def tables():
    rows = []
    for k, v in sorted(LJ["benchmark"].items(), key=lambda kv: (list(KIND).index(kind(kv[0])), kv[0])):
        d, m = v["distinct"], v["mentions"]
        rows.append([k, KIND[kind(k)], model_id(k), f"{d['d']:,}", f"{100 * d['valid_type'] / d['d']:.1f}", f"{100 * m['valid'] / m['d']:.1f}"])
    write_table("table1_programs", ["Configuration", "Kind", "Model", "Distinct strings", "Valid + correctly typed (%)",
                                    "Valid, mention-weighted (%)"], rows,
                "Judged by DeepSeek-V4-Flash from the string alone (model judgement, not accuracy). Other programs in the protocol: "
                "Qwen3.5-4B (catalogue and triple extraction), Llama-3.1-8B and Mistral-7B (evidence judges), "
                "DeepSeek-R1-Distill-Qwen-7B (term review, mapping adjudication), DeepSeek-V4-Flash (validity judge, relabelling), "
                "SapBERT and all-MiniLM-L6-v2 (embedding matches); BioPortal, OLS, UMLS, OMOP and NCBI Taxonomy (vocabulary mapping).")
    lab = {"sequencing_type": "Sequencing type", "region_16s": "16S variable region", "platform": "Sequencing platform",
           "country": "Country", "statistical_test": "Statistical test", "group_size": "Group sample size",
           "body_site": "Body site", "condition": "Condition", "group_name": "Group name"}
    rows = []
    for f, s in BS["fields"].items():
        wl = s["concordance_wilson"]
        method = "SapBERT" if "threshold" in s else "rule"
        rows.append([lab[f], method, s["items"], f"{100 * s['completeness']:.1f}", f"{100 * s['concordance']:.1f}",
                     f"{100 * wl[0]:.1f}–{100 * wl[1]:.1f}", f"{100 * s['chance']:.1f}", s["chance_corrected"],
                     f"{100 * s['lexical_match']:.1f}" if s.get("lexical_match") is not None else "",
                     f"{100 * s['posthoc_strict_set_equal']:.1f}" if "posthoc_strict_set_equal" in s else ""])
    write_table("table2_bugsigdb_fields", ["Field", "Method", "Items", "Our value present (%)", "Concordance (%)", "95% Wilson",
                                           "Chance (%)", "Chance-corrected", "Lexical match (%)", "Strict set equality (%, post hoc)"], rows,
                f"{BS['papers']} papers, {BS['signatures']} BugSigDB signatures. Body site: the embedding threshold is 1.0 because most "
                "papers sample faeces, so the lexical match is the informative measure. Sequencing type and platform are nearly "
                "uniform in this corpus (chance above 90%).")
    rows = [
        ["Structural integrity", "keys, cardinalities, provenance chain, section hashes", "none (deterministic)", "no", "C08, K11"],
        ["Value in evidence", "is each catalogue value found in its anchored quote / section", "the paper's own text", "no", "K08–K10, K14"],
        ["Model judges (catalogue)", "is each value supported by its evidence", "Llama-3.1-8B, Mistral-7B", "no", "E, J claims"],
        ["Model judge (all entities, triples)", "valid entity / correct type / well-formed triple", "DeepSeek-V4-Flash", "no", "L01–L15"],
        ["Human-curated reference", "study metadata, taxa, direction; triples", "BugSigDB (47 papers)", "indirect (curators)", "N01–N11, XR01–XR04"],
        ["Curated knowledge base", "chemical–disease, gene–disease triples", "CTD", "indirect (curators)", "XR05–XR06"],
    ]
    write_table("table3_evaluation_layers", ["Layer", "What is tested", "Reference", "Human input", "Claims"], rows,
                "No layer is human annotation of this corpus. Absence from a reference is reported as 'not in reference', never as an error.")


if __name__ == "__main__":
    fig1()
    fig4()
    tables()
    print("written to", OUT.relative_to(ROOT))
