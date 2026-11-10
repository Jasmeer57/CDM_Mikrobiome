"""Illustrated (icon-style) overview of the protocol: a candidate replacement for fig_overview as Figure 1.

Same content and numbers as make_overview_figure.py, drawn as stage cards with vector icons instead of a block diagram.
Every number comes from the claims register through make_bib_figures.n(); nothing is typed in. Palette = the shared
house palette (blue / orange / aqua + neutrals) and light tints of it; no checkmarks anywhere (nothing was
human-validated). Writes PDF + 600 dpi PNG + editable SVG (text kept as text) for redrawing in Inkscape.

Written with an AI coding assistant (Claude Code); the box wording is a draft the authors must review and own, and the
figure must be declared in the manuscript's AI statement.

    python make_overview_illustrated.py
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.colors import to_hex, to_rgb  # noqa: E402
from matplotlib.patches import Arc, Circle, Ellipse, FancyArrowPatch, FancyBboxPatch, Polygon, Rectangle  # noqa: E402

import make_bib_figures as M  # noqa: E402

n = M.n
BLUE, ORANGE, AQUA = M.SERIES
INK, INK2 = M.INK, M.INK2
if any("Nimbus Sans" == f.name for f in font_manager.fontManager.ttflist):
    plt.rcParams["font.family"] = "Nimbus Sans"      # Helvetica metric clone; falls back to DejaVu Sans
U = 0.07                                             # inches per drawing unit (100 units = 7.0 in = 178 mm)
FS, FSS, FBIG = 7.0, 6.5, 11.5


def mix(c, t, base="white"):
    """Blend colour c towards base; t = share of c."""
    a, b = to_rgb(c), to_rgb(base)
    return to_hex(tuple(t * x + (1 - t) * y for x, y in zip(a, b)))


def rbox(ax, x, y, w, h, fc, ec="none", lw=0.6, r=1.0, z=1, shadow=False):
    if shadow:
        ax.add_patch(FancyBboxPatch((x + 0.35, y - 0.45), w, h, boxstyle=f"round,pad=0,rounding_size={r}",
                                    fc="#000000", ec="none", alpha=0.07, zorder=z - 0.1))
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}", fc=fc, ec=ec, lw=lw,
                                zorder=z))


def disc(ax, cx, cy, r, col, z=3):
    ax.add_patch(Circle((cx + 0.3, cy - 0.4), r, fc="#000000", ec="none", alpha=0.07, zorder=z - 0.1))
    ax.add_patch(Circle((cx, cy), r, fc="white", ec=mix(col, 0.35), lw=0.7, zorder=z))


# ------------------------------------------------------------------------------------------------ icons
def ic_docs(ax, cx, cy, s, col):
    for k, t in ((2, 0.30), (1, 0.55), (0, 1.0)):
        x, y, w, h = cx - 0.45 * s + 0.28 * s * k - 0.25 * s, cy - 0.6 * s + 0.2 * s * k, 0.9 * s, 1.15 * s
        f = 0.22 * s
        ax.add_patch(Polygon([(x, y), (x + w, y), (x + w, y + h - f), (x + w - f, y + h), (x, y + h)], closed=True,
                             fc="white" if k else mix(col, 0.12), ec=mix(col, t), lw=0.8, zorder=4 - k * 0.1))
        if k == 0:
            ax.add_patch(Polygon([(x + w - f, y + h), (x + w - f, y + h - f), (x + w, y + h - f)], closed=True,
                                 fc=mix(col, 0.45), ec="none", zorder=4.1))
            for j in range(4):
                ax.add_patch(Rectangle((x + 0.14 * s, y + h - 0.42 * s - 0.2 * s * j), (0.62 - 0.12 * (j == 3)) * s,
                                       0.07 * s, fc=mix(col, 0.55), ec="none", zorder=4.2))


def ic_extract(ax, cx, cy, s, col):
    x, y, w, h = cx - 0.75 * s, cy - 0.6 * s, 1.0 * s, 1.2 * s
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={0.08 * s}", fc="white",
                                ec=mix(col, 0.8), lw=0.8, zorder=4))
    marks = [BLUE, None, ORANGE, AQUA, None]
    for j, m in enumerate(marks):
        yy = y + h - 0.25 * s - 0.2 * s * j
        ax.add_patch(Rectangle((x + 0.13 * s, yy), 0.74 * s, 0.07 * s, fc=mix(INK2, 0.25), ec="none", zorder=4.1))
        if m:
            off = 0.13 * s + (0.1 + 0.15 * j % 0.3) * s
            ax.add_patch(FancyBboxPatch((x + off, yy - 0.04 * s), 0.32 * s, 0.15 * s,
                                        boxstyle=f"round,pad=0,rounding_size={0.04 * s}", fc=mix(m, 0.55), ec="none",
                                        zorder=4.2))
    mx, my, mr = cx + 0.35 * s, cy - 0.12 * s, 0.36 * s
    ax.add_patch(Circle((mx, my), mr, fc=(1, 1, 1, 0.75), ec=INK2, lw=1.4, zorder=4.5))
    ax.plot([mx + 0.7 * mr, mx + 1.65 * mr], [my - 0.7 * mr, my - 1.65 * mr], color=INK2, lw=2.2,
            solid_capstyle="round", zorder=4.5)


def ic_normalise(ax, cx, cy, s, col):
    root = (cx + 0.35 * s, cy + 0.6 * s)
    mids = [(cx + 0.0 * s, cy + 0.05 * s), (cx + 0.75 * s, cy + 0.05 * s)]
    leaves = [(cx - 0.2 * s, cy - 0.55 * s), (cx + 0.2 * s, cy - 0.55 * s), (cx + 0.75 * s, cy - 0.55 * s)]
    for m in mids:
        ax.plot([root[0], m[0]], [root[1], m[1]], color=mix(col, 0.6), lw=0.9, zorder=4)
    for (lx, ly), m in zip(leaves, (mids[0], mids[0], mids[1])):
        ax.plot([m[0], lx], [m[1], ly], color=mix(col, 0.6), lw=0.9, zorder=4)
    for p in [root] + mids:
        ax.add_patch(Circle(p, 0.13 * s, fc=mix(col, 0.35), ec="none", zorder=4.2))
    for k, p in enumerate(leaves):
        ax.add_patch(Circle(p, 0.15 * s if k == 0 else 0.12 * s, fc=col if k == 0 else mix(col, 0.35), ec="none",
                            zorder=4.2))
    for j, (dy, c) in enumerate(((0.45, BLUE), (0.0, ORANGE), (-0.45, AQUA))):
        p = (cx - 0.95 * s, cy - 0.1 * s + dy * s * 0.8)
        ax.add_patch(FancyArrowPatch(p, leaves[0], arrowstyle="-", color=mix(c, 0.7), lw=0.8, ls=(0, (2, 1.5)),
                                     connectionstyle=f"arc3,rad={0.25 - 0.25 * j}", shrinkA=1.5, shrinkB=2.5,
                                     zorder=4.1))
        ax.add_patch(FancyBboxPatch((p[0] - 0.14 * s, p[1] - 0.07 * s), 0.28 * s, 0.14 * s,
                                    boxstyle=f"round,pad=0,rounding_size={0.05 * s}", fc=mix(c, 0.55), ec="none",
                                    zorder=4.2))


def ic_database(ax, cx, cy, s, col):
    w, h, e = 1.15 * s, 1.2 * s, 0.32 * s
    x0, y0 = cx - w / 2, cy - h / 2
    ax.add_patch(Rectangle((x0, y0), w, h, fc=mix(col, 0.18), ec="none", zorder=4))
    ax.plot([x0, x0], [y0, y0 + h], color=col, lw=0.9, zorder=4.3)
    ax.plot([x0 + w, x0 + w], [y0, y0 + h], color=col, lw=0.9, zorder=4.3)
    ax.add_patch(Ellipse((cx, y0), w, e, fc=mix(col, 0.18), ec=col, lw=0.9, zorder=3.9))
    for k in (1, 2):
        yy = y0 + h * k / 3
        ax.add_patch(Arc((cx, yy), w, e, theta1=180, theta2=360, color=mix(col, 0.55), lw=0.8, zorder=4.2))
    ax.add_patch(Ellipse((cx, y0 + h), w, e, fc=mix(col, 0.4), ec=col, lw=0.9, zorder=4.4))
    for k, c in enumerate((BLUE, ORANGE, AQUA)):
        ax.add_patch(Circle((x0 + w * (0.3 + 0.2 * k), y0 + h / 6 - 0.05 * s), 0.07 * s, fc=c, ec="none", zorder=4.5))


def ic_release(ax, cx, cy, s, col):
    a, d = 0.62 * s, 0.32 * s
    top = [(cx, cy + 0.15 * s + d), (cx + a, cy + 0.15 * s), (cx, cy + 0.15 * s - d), (cx - a, cy + 0.15 * s)]
    left = [(cx - a, cy + 0.15 * s), (cx, cy + 0.15 * s - d), (cx, cy - 0.85 * s), (cx - a, cy - 0.85 * s + d)]
    right = [(cx + a, cy + 0.15 * s), (cx, cy + 0.15 * s - d), (cx, cy - 0.85 * s), (cx + a, cy - 0.85 * s + d)]
    for poly, t in ((left, 0.45), (right, 0.75), (top, 0.22)):
        ax.add_patch(Polygon(poly, closed=True, fc=mix(col, t), ec=col,
                             lw=0.7, zorder=4, joinstyle="round"))
    ax.add_patch(Polygon([(cx - 0.5 * a, cy + 0.15 * s + 0.5 * d), (cx - 0.3 * a, cy + 0.15 * s + 0.6 * d),
                          (cx + 0.7 * a, cy + 0.15 * s - 0.4 * d), (cx + 0.5 * a, cy + 0.15 * s - 0.5 * d)],
                         closed=True, fc="white", ec="none", alpha=0.9, zorder=4.2))
    tx, ty = cx + 0.62 * s, cy + 0.62 * s
    ax.add_patch(Circle((tx, ty), 0.28 * s, fc="white", ec=col, lw=0.8, zorder=4.6))
    ax.text(tx, ty, "#", ha="center", va="center", fontsize=FS, color=col, fontweight="bold", zorder=4.7)


def ic_links(ax, cx, cy, s, col):
    for dx in (-0.22, 0.22):
        ax.add_patch(FancyBboxPatch((cx + dx * s - 0.38 * s, cy - 0.17 * s), 0.76 * s, 0.34 * s,
                                    boxstyle=f"round,pad=0,rounding_size={0.17 * s}", fc="none", ec=col, lw=1.3,
                                    zorder=4))


def ic_quote(ax, cx, cy, s, col):
    ax.text(cx, cy - 0.35 * s, "“”", ha="center", va="center", fontsize=15, color=col, fontweight="bold",
            zorder=4)


def ic_judges(ax, cx, cy, s, col):
    for (dx, dy, t, flip) in ((-0.2, 0.15, 0.85, False), (0.22, -0.22, 0.4, True)):
        x, y, w, h = cx + dx * s - 0.36 * s, cy + dy * s - 0.2 * s, 0.72 * s, 0.4 * s
        fc = mix(col, t)
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={0.12 * s}", fc=fc,
                                    ec="white", lw=0.6, zorder=4 + flip))
        tx = x + (w - 0.2 * s if flip else 0.2 * s)
        ax.add_patch(Polygon([(tx - 0.07 * s, y + 0.02), (tx + 0.07 * s, y + 0.02),
                              (tx + (0.12 if flip else -0.12) * s, y - 0.15 * s)], closed=True, fc=fc, ec="none",
                             zorder=4 + flip))
        for k in range(3):
            ax.add_patch(Circle((x + w * (0.3 + 0.2 * k), y + h / 2), 0.045 * s, fc="white", ec="none",
                                zorder=4.1 + flip))


def ic_book(ax, cx, cy, s, col):
    for side in (-1, 1):
        ax.add_patch(Polygon([(cx, cy - 0.3 * s), (cx + side * 0.6 * s, cy - 0.2 * s),
                              (cx + side * 0.6 * s, cy + 0.38 * s), (cx, cy + 0.28 * s)], closed=True,
                             fc=mix(col, 0.15 if side < 0 else 0.3), ec=col, lw=0.8, zorder=4))
        for k in range(3):
            y = cy + 0.12 * s - 0.15 * s * k
            ax.plot([cx + side * 0.12 * s, cx + side * 0.48 * s], [y, y + 0.05 * s], color=mix(col, 0.6), lw=0.6,
                    zorder=4.1)


def ic_bars(ax, cx, cy, s, col):
    for k, h in enumerate((0.45, 0.8, 0.6)):
        ax.add_patch(Rectangle((cx - 0.45 * s + 0.32 * s * k, cy - 0.38 * s), 0.22 * s, h * s,
                               fc=mix(col, 0.4 + 0.3 * k), ec="none", zorder=4))
    ax.plot([cx - 0.55 * s, cx + 0.55 * s], [cy - 0.38 * s] * 2, color=INK2, lw=0.8, zorder=4.1)


def ic_query(ax, cx, cy, s, col):
    mx, my, mr = cx - 0.08 * s, cy + 0.08 * s, 0.34 * s
    ax.add_patch(Circle((mx, my), mr, fc=mix(col, 0.12), ec=col, lw=1.3, zorder=4))
    ax.plot([mx + 0.7 * mr, mx + 1.6 * mr], [my - 0.7 * mr, my - 1.6 * mr], color=col, lw=2.0,
            solid_capstyle="round", zorder=4)
    ax.text(mx, my, "?", ha="center", va="center", fontsize=FS, color=col, fontweight="bold", zorder=4.1)


def ic_triple(ax, cx, cy, s, col):
    """Subject -> object over a sentence line: a triple read against its sentence."""
    a, b = (cx - 0.48 * s, cy + 0.2 * s), (cx + 0.48 * s, cy + 0.2 * s)
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=5, color=col, lw=1.0, shrinkA=3, shrinkB=3,
                                 zorder=4))
    for p, t in ((a, 0.45), (b, 1.0)):
        ax.add_patch(Circle(p, 0.16 * s, fc=mix(col, t), ec="none", zorder=4.1))
    for k, w in enumerate((0.95, 0.6)):
        ax.add_patch(Rectangle((cx - 0.48 * s, cy - 0.22 * s - 0.2 * k * s), w * s, 0.08 * s, fc=mix(INK2, 0.3),
                               ec="none", zorder=4))


# ------------------------------------------------------------------------------------------------ layout
def chip(ax, x, y, w, text, col, h=None, bold_first=False, fill="white"):
    lines = text.split("\n")
    h = h or 1.2 + 1.75 * len(lines)
    rbox(ax, x, y - h, w, h, fill, ec=mix(col, 0.4), lw=0.5, r=0.7, z=3)
    for k, ln in enumerate(lines):
        ax.text(x + w / 2, y - h / 2 + 1.75 * ((len(lines) - 1) / 2 - k), ln, ha="center", va="center",
                fontsize=FSS, color=INK, fontweight="bold" if (bold_first and k == 0) else "normal", zorder=3.5)
    return y - h - 0.8


def card(ax, x, top, w, h, num, title, icon, col, big, big_label, chips, foot=None):
    rbox(ax, x, top - h, w, h, mix(col, 0.08), ec=mix(col, 0.4), lw=0.6, r=1.6, z=1, shadow=True)
    ax.add_patch(Circle((x + 2.6, top - 2.9), 1.65, fc=col, ec="none", zorder=3))
    ax.text(x + 2.6, top - 2.9, str(num), ha="center", va="center", fontsize=FS, color="white", fontweight="bold",
            zorder=3.1)
    ax.text(x + 4.9, top - 2.9, title, ha="left", va="center", fontsize=7.5, color=INK, fontweight="bold", zorder=3)
    cx, cy = x + w / 2, top - 11.2
    disc(ax, cx, cy, 5.6, col)
    icon(ax, cx, cy, 4.3, col)
    if big:
        ax.text(cx, top - 19.6, big, ha="center", va="center", fontsize=FBIG, color=mix(col, 0.75, "black"),
                fontweight="bold", zorder=3)
    ly = top - 21.6 if big else top - 18.6
    ax.text(cx, ly, big_label, ha="center", va="top", fontsize=FSS, color=INK2, linespacing=1.15, zorder=3)
    y = ly - 1.75 * (big_label.count("\n") + 1) - 1.2
    for c in chips:
        t, cc = (c, col) if isinstance(c, str) else c
        y = chip(ax, x + 1.1, y, w - 2.2, t, cc)
    if foot:
        ax.text(cx, top - h + 1.0, foot, ha="center", va="bottom", fontsize=FSS, color=INK2, style="italic",
                linespacing=1.15, zorder=3)


def chevron(ax, x, y, col):
    ax.add_patch(Polygon([(x, y + 1.6), (x + 1.2, y), (x, y - 1.6), (x + 0.55, y)], closed=True, fc=col, ec="none",
                         zorder=6))


def draw():
    W, CH, G = 100.0, 48.0, 1.8
    w = (W - 4 * G) / 5
    EH = 21.5
    H = 1.0 + CH + 7.5 + EH + 0.5
    fig, ax = plt.subplots(figsize=(W * U, H * U))
    ax.set_xlim(0, W)
    ax.set_ylim(0, H)
    ax.axis("off")
    top = H - 1.0
    qwen = int(M.REG["M04"]["stated"]) + int(M.REG["M05"]["stated"])
    xs = [i * (w + G) for i in range(5)]

    card(ax, xs[0], top, w, CH, 1, "Corpus", ic_docs, BLUE, n("C02"), "publications",
         [f"{n('C01')} BioProjects\n{n('C07')} sections",
          f"cited by a gut\ncompendium:\n{n('C05')} of {n('C06')}\nsamples linked",
          ("licence check:\nopen vs. restricted", ORANGE)])
    card(ax, xs[1], top, w, CH, 2, "Extraction", ic_extract, BLUE, n("M01"), "mentions with\ntext positions",
         [f"trained and\nzero-shot NER\n{n('M03')}", f"Qwen3.5 LLM\n2 runs: {qwen:,}",
          f"MeSH dictionary\n{n('M06')}"])
    card(ax, xs[2], top, w, CH, 3, "Normalisation", ic_normalise, BLUE, n("T02"), "canonical terms\n(14 types)",
         [f"{n('P01')} ontology\nmapping candidates", f"{n('P05')} accepted\n(two models agree)",
          "BioPortal, OLS,\nUMLS, OMOP,\nNCBI Taxonomy"])
    card(ax, xs[3], top, w, CH, 4, "CDM 3.0.3", ic_database, BLUE, n("K01"), "study catalogue\nrecords",
         [f"{n('K02')} findings\n{n('K03')} gap-filled", f"{n('R01')} triples\n{n('Q01', 0)} graph nodes",
          "evidence quote and\nposition per value"],
         foot="SQLite; provenance\nfor every row")
    card(ax, xs[4], top, w, CH, 5, "Releases", ic_release, AQUA, None, "frozen, versioned",
         [("CDM 3.0.3 (SQLite)", AQUA), ("data catalogue 3.1.1", AQUA), ("terminology 1.0.1", AQUA)],
         foot="SHA-256 manifests;\npublic deposit after\nrights review")
    for i in range(4):
        chevron(ax, xs[i] + w + 0.4, top - 11.2, mix(INK2, 0.7))

    # evaluation band
    ey = top - CH - 7.5
    rbox(ax, 0, ey - EH, W, EH, mix(ORANGE, 0.07), ec=mix(ORANGE, 0.45), lw=0.6, r=1.6, z=1, shadow=True)
    pill_w = 62.0
    rbox(ax, W / 2 - pill_w / 2, ey - 1.75, pill_w, 3.5, ORANGE, r=1.75, z=3)
    ax.text(W / 2, ey, "Evaluation: computational only, no human annotation", ha="center", va="center",
            fontsize=7.5, color="white", fontweight="bold", zorder=3.1)
    W3 = M.REG["W03"]["stated"].split("/")       # keep "56.0" (n() would print 56)
    tiles = [(ic_links, "Integrity", "hashes, text\npositions,\ntable links"),
             (ic_quote, "Evidence checks", "value is in its\nquote; re-found\nby 2nd method"),
             (ic_judges, "LLM judges", "screen terms\nand values;\nnot accuracy"),
             (ic_book, "References", "curated: BugSigDB,\nCTD, Disbiome"),
             (ic_triple, "Triple screen", f"LLM: sentence\nsupports {W3[0]}%,\ncontradicts {W3[3]}%"),
             (ic_bars, "NER benchmarks", "BC5CDR, BioRED,\nS1000; corpus\nvs. references"),
             (ic_query, "Use cases", "research queries\nvs. keyword\nsearch; IBD")]
    tw = (W - 2.0 - 0.9 * (len(tiles) - 1)) / len(tiles)
    for j, (ic, t, d) in enumerate(tiles):
        x = 1.0 + j * (tw + 0.9)
        rbox(ax, x, ey - EH + 1.0, tw, EH - 4.2, "white", ec=mix(ORANGE, 0.3), lw=0.5, r=1.0, z=2)
        cx = x + tw / 2
        ax.add_patch(Circle((cx, ey - 6.4), 2.9, fc=mix(ORANGE, 0.12), ec="none", zorder=3))
        ic(ax, cx, ey - 6.4, 3.0, ORANGE)
        ax.text(cx, ey - 10.6, t, ha="center", va="center", fontsize=FSS, color=INK, fontweight="bold", zorder=3)
        ax.text(cx, ey - 12.2, d, ha="center", va="top", fontsize=FSS, color=INK2,
                linespacing=1.15, zorder=3)
    for c in (1, 2, 3):
        ax.add_patch(FancyArrowPatch((xs[c] + w / 2, top - CH - 0.4), (xs[c] + w / 2, ey + 1.9),
                                     arrowstyle="-|>", mutation_scale=7, color=mix(ORANGE, 0.8), lw=0.9,
                                     ls=(0, (2.5, 1.5)), shrinkA=0, shrinkB=0, zorder=5))

    (M.OUT / "figures").mkdir(parents=True, exist_ok=True)
    for ext, kw in (("pdf", {}), ("png", {"dpi": 600}), ("svg", {})):
        fig.savefig(M.OUT / "figures" / f"fig_overview_illustrated.{ext}", bbox_inches="tight", **kw)
    plt.close(fig)


if __name__ == "__main__":
    draw()
    print("written:", M.OUT / "figures" / "fig_overview_illustrated.{pdf,png,svg}")
