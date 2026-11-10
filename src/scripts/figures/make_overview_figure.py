"""Overview block diagram of the whole protocol for the BiB manuscript (upper-level flowchart).

Every number is read from the manuscript claims register (paper/publication/final_validation/MANUSCRIPT_CLAIMS_REGISTER.csv)
through make_bib_figures.n(); nothing is typed in. Palette and save() are shared with make_bib_figures.py.

  fig_overview                       manuscript Figure 1 (supersedes fig1_protocol): corpus -> extraction ->
                                     normalisation -> CDM 3.0.3 -> frozen releases, and the evaluation layer.
                                     All fonts >= 6.5 pt at 7.0 in width; 600 dpi PNG + vector PDF.
  fig_overview_INTERNAL_with_cdm31   the same plus the CDM 3.1 candidate repair band. NOT for the manuscript: the
                                     repair counts are not in the claims register; they are read from
                                     outputs/results/cdm_v3_3.1_deepseek_repair/stage_*_qwen/validation/summary.json.

Written with an AI coding assistant (Claude Code); declare in the manuscript's AI statement.

    python make_overview_figure.py
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

import make_bib_figures as M  # noqa: E402

REPAIR = M.ROOT / "outputs/results/cdm_v3_3.1_deepseek_repair"


def repair_counts():
    """Counts for the CDM 3.1 repair band, summed from the stage validation summaries (no typed-in numbers)."""
    ld = lambda s: M.json.load(open(REPAIR / f"stage_{s}_qwen/validation/summary.json"))  # noqa: E731
    b, h, i = ld("b_terms"), ld("h_definitions"), ld("i_mapping")
    bd, hd = b["decisions"], h["decisions"]
    pick = lambda d, key: sum(v for k, v in d.items() if key in k.split("|"))  # noqa: E731
    return {"terms": b["terms"], "not_term": pick(bd, "FLAG_NOT_A_TERM"), "retype": pick(bd, "CHANGE_TYPE"),
            "defs": h["items"], "def_acc": pick(hd, "ACCEPTED_COMPUTATIONALLY"), "def_rej": pick(hd, "REJECTED"),
            "def_unres": pick(hd, "UNRESOLVED"), "maps": i["mapping_rows"],
            "map_acc": i["decisions"]["ACCEPTED_COMPUTATIONALLY"], "map_rej": i["decisions"]["REJECTED"],
            "prev_acc_kept": i["previously_two_model_ACCEPTED_now"]["ACCEPTED_COMPUTATIONALLY"]}

n = M.n
BLUE, ORANGE, AQUA = M.SERIES
INK, INK2, SURFACE = M.INK, M.INK2, M.SURFACE
FS, FSS, FT = 7.0, 6.5, 7.5    # body / small / title font sizes (pt) at 7.0 in width; BiB print floor ~6.5 pt
U = 0.07                       # inches per drawing unit, both axes (100 units = 7.0 in)


def box(ax, x, y, w, h, title=None, body=None, col=BLUE, fill=SURFACE, dashed=False, head=4.4, title_fs=FT):
    ls = (0, (3, 2)) if dashed else "-"
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=0.8", fc=fill, ec=col, lw=0.8, ls=ls))
    top = y + h
    if title:
        ax.add_patch(FancyBboxPatch((x, top - head), w, head, boxstyle="round,pad=0,rounding_size=0.8",
                                    fc=col if not dashed else "white", ec=col, lw=0.8, ls=ls))
        ax.text(x + w / 2, top - head / 2, title, ha="center", va="center", fontsize=title_fs, fontweight="bold",
                color="white" if not dashed else col)
        top -= head
    if body:
        ax.text(x + w / 2, top - 1.2, body, ha="center", va="top", fontsize=FS, color=INK, linespacing=1.25)


def sub(ax, x, y, w, h, text, col=BLUE, fs=FSS, fill="white", dashed=False, bold=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=0.5", fc=fill, ec=col, lw=0.6,
                                ls=(0, (3, 2)) if dashed else "-"))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs, color=INK, linespacing=1.2,
            fontweight="bold" if bold else "normal")


def stack(ax, x, w, top, items, gap=1.0, col=BLUE):
    """Place sub-boxes top-down; items = [(text, height)]. Returns the y of the last box's bottom."""
    for t, h in items:
        top -= h
        sub(ax, x + 1.0, top, w - 2.0, h, t, col=col)
        top -= gap
    return top + gap


def arrow(ax, p, q, col=INK2, ls="-"):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle="-|>", mutation_scale=7, color=col, lw=0.8, ls=ls, zorder=5,
                                 shrinkA=0, shrinkB=0))


def note(ax, x, y, s, col=INK2):
    ax.text(x, y, s, ha="center", va="top", fontsize=FSS, color=col, style="italic", linespacing=1.2)


def draw(with_repair: bool):
    hh, eh, rh = 48.0, 21.0, 19.0
    H = hh + 7.0 + eh + (6.0 + rh if with_repair else 0) + 1.0
    fig, ax = plt.subplots(figsize=(100 * U, H * U))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, H)
    ax.axis("off")
    y0 = H - hh - 0.5                                   # bottom of the main row
    top = y0 + hh - 4.4 - 1.0                           # first content line under a column title
    qwen = int(M.REG["M04"]["stated"]) + int(M.REG["M05"]["stated"])
    w, g = 18.6, 1.75
    xs = [i * (w + g) for i in range(5)]

    # 1 Corpus
    box(ax, xs[0], y0, w, hh, "1  Corpus", f"{n('C01')} BioProjects\n{n('C02')} publications\n{n('C07')} sections")
    stack(ax, xs[0], w, top - 8.5, [
        (f"Papers cited by a\nhuman gut\ncompendium\n({n('C05')} of\n{n('C06')}\nsamples linked)", 15.0)])
    stack(ax, xs[0], w, y0 + 10.0, [("Licence check:\nopen vs.\nrestricted text", 8.5)], col=ORANGE)

    # 2 Extraction
    box(ax, xs[1], y0, w, hh, "2  Extraction")
    stack(ax, xs[1], w, top, [
        (f"Trained and\nzero-shot NER\n{n('M03')}", 8.5),
        (f"Small open LLM\n(Qwen3.5, 2 runs)\n{qwen:,}", 8.5),
        (f"MeSH dictionary\n{n('M06')}\n(no unique terms)", 8.5)])
    ax.text(xs[1] + w / 2, y0 + 6.0, f"{n('M01')}\nmentions with\ntext positions", ha="center",
            va="center", fontsize=FS, color=INK, fontweight="bold", linespacing=1.2)

    # 3 Normalisation
    box(ax, xs[2], y0, w, hh, "3  Normalisation", title_fs=7.0)
    b = stack(ax, xs[2], w, top, [
        (f"Canonical terms\n{n('T02')}\n(14 types;\n{n('T03')} removed)", 11.0),
        (f"Ontology mapping\n{n('P01')}\ncandidates,\n{n('P02')} kept;\n{n('P05')} accepted\n(2 models agree)",
         15.5)])
    note(ax, xs[2] + w / 2, b - 1.5, "BioPortal, OLS,\nUMLS, OMOP,\nNCBI Taxonomy")

    # 4 CDM 3.0.3
    box(ax, xs[3], y0, w, hh, "4  CDM 3.0.3")
    b = stack(ax, xs[3], w, top, [
        ("Terms, mappings,\ndefinitions", 5.6),
        (f"Study catalogue\n{n('K01')} records\n({n('K02')} findings;\n{n('K03')} values\ngap-filled)",
         12.0),
        ("Evidence quotes\nlinked to their\ntext position", 8.0),
        (f"Relation triples\n{n('R01')}; graph of\n{n('Q01', 0)} nodes", 8.0)])
    note(ax, xs[3] + w / 2, b - 0.8, "SQLite; provenance\nfor every row")

    # 5 Releases
    box(ax, xs[4], y0, w, hh, "5  Releases", col=AQUA)
    b = stack(ax, xs[4], w, top, [("CDM 3.0.3\n(SQLite)", 7.0), ("Data catalogue\n3.1.1", 7.0),
                                  ("Terminology\n1.0.1", 7.0)], gap=1.5, col=AQUA)
    note(ax, xs[4] + w / 2, b - 1.5, "frozen, versioned;\nSHA-256 manifests;\npublic deposit\nafter rights review")

    for i in range(4):
        arrow(ax, (xs[i] + w, y0 + hh / 2), (xs[i + 1], y0 + hh / 2))

    # Evaluation band
    ey = y0 - 7.0 - eh
    box(ax, 0, ey, 100, eh, "Evaluation (computational only; no human annotation)", col=ORANGE)
    ev = ["Structural checks\nhashes, text\npositions, links\nbetween tables",
          "Evidence checks\nvalue is in its\nquote; metadata\nre-found by a\nsecond method",
          "LLM judges\nscore terms,\nvalues, triples\n(a screen, not\naccuracy)",
          "Curated\nreferences\nBugSigDB, CTD,\nDisbiome",
          "NER benchmarks\nBC5CDR,\nBioRED, S1000;\ncorpus NER vs.\nreferences",
          "Use cases\nresearch queries\nvs. keyword\nsearch; IBD\nexample"]
    ew = (100 - 2.0 - 1.0 * (len(ev) - 1)) / len(ev)
    for j, t in enumerate(ev):
        sub(ax, 1.0 + j * (ew + 1.0), ey + 1.2, ew, eh - 6.6, t, col=ORANGE)
    for c in (1, 3):
        arrow(ax, (xs[c] + w / 2, y0), (xs[c] + w / 2, ey + eh), col=ORANGE)

    # CDM 3.1 candidate repair (internal version only; not in the manuscript figure)
    if with_repair:
        r = repair_counts()
        ry = ey - 6.0 - rh
        box(ax, 0, ry, 100, rh, "INTERNAL - CDM 3.1 candidate: evidence-checked repair (not released)", col=BLUE,
            dashed=True)
        steps = ["Inputs\nread-only 3.0.3,\nrights-aware",
                 "Local Qwen3.5-9B\n(4-bit) proposals;\nvalidators decide",
                 f"Terms {r['terms']:,}\n{r['not_term']:,} not a\nterm; {r['retype']:,}\nretyped",
                 f"Definitions {r['defs']:,}\n{r['def_acc']:,} accepted\n{r['def_rej']:,} rejected\n"
                 f"{r['def_unres']:,} unresolved",
                 f"Mappings {r['maps']:,}\n{r['map_acc']:,} accepted\n{r['map_rej']:,} rejected\n"
                 f"{r['prev_acc_kept']:,} of {n('P05')}\nkept"]
        sw = (100 - 2.0 - 2.5 * (len(steps) - 1)) / len(steps)
        for j, t in enumerate(steps):
            x = 1.0 + j * (sw + 2.5)
            sub(ax, x, ry + 1.2, sw, rh - 6.6, t, dashed=True)
            if j:
                arrow(ax, (x - 2.5, ry + 1.2 + (rh - 6.6) / 2), (x, ry + 1.2 + (rh - 6.6) / 2), col=BLUE)
        arrow(ax, (50, ey), (50, ry + rh), col=BLUE, ls=(0, (3, 2)))
    M.save(fig, "fig_overview_INTERNAL_with_cdm31" if with_repair else "fig_overview")
    plt.close(fig)


if __name__ == "__main__":
    draw(False)
    draw(True)
    print("written:", M.OUT / "figures" / "fig_overview.pdf", "(manuscript Figure 1) and",
          "fig_overview_INTERNAL_with_cdm31.pdf (not for the manuscript)")
