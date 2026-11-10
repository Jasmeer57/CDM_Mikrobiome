#!/usr/bin/env python3
"""Generate main.tex — Briefings in Bioinformatics (Problem Solving Protocol) submission
scaffold with the registry-verified, BiB-formatted bibliography baked in as \\bibitem's.

RULES OF THIS FILE (per ../manuscript_bib/BIB_MANUSCRIPT_PLAN.md and OUP policy):
  - The PROSE is NOT written here. Every section is a placeholder tagged with its
    plan source and word budget. BiB does not accept LLM-drafted text; the authors
    write the prose from the claim register (../../final_validation/MANUSCRIPT_CLAIMS_REGISTER.csv).
  - The bibliography IS generated here, entry format from
    ../submission_readiness/references_source/render_bib_style.py (registry-verified
    2026-11-07). Provisional numbering = pipeline-phase order; the plan requires
    re-numbering by first appearance once the prose is placed.
Regenerate with:  python3 gen_latex.py
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
RS = HERE.parent / "submission_readiness" / "references_source"
sys.path.insert(0, str(RS))
from render_bib_style import SECTION, entry  # noqa: E402

PLAN = f"{HERE.parent / 'manuscript_bib' / 'BIB_MANUSCRIPT_PLAN.md'}"
DATE = "2026-11-07"


def texify(s: str) -> str:
    # escape TeX specials FIRST (input text contains no backslashes), italics after
    for ch, esc in (("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"),
                    ("$", r"\$"), ("#", r"\#"), ("_", r"\_"),
                    ("{", r"\{"), ("}", r"\}"), ("~", r"\textasciitilde{}"),
                    ("^", r"\textasciicircum{}")):
        s = s.replace(ch, esc)
    return re.sub(r"\*(.+?)\*", r"\\emph{\1}", s)


SECTIONS = [  # (heading, source notes, budget, claim tags)
    ("Introduction: the problem", "draft 00_introduction.md; gap vs BugSigDB, MiDRED, DiMB-RE, MINERVA, Higashi et al.", "~550", "R1-R6"),
    ("Protocol overview", "draft 01_methods...; Figure 1; C01-C08", "~350", "C01-C08"),
    ("Stage 1: Corpus and sectioning", "draft 01_methods... Corpus", "~250", ""),
    ("Stage 2: Entity extraction with multiple programs", "draft 01_methods... Entity mention extraction + NER benchmark; Table 1", "~550", "H03-H07, L01-L04"),
    ("Stage 3: Normalisation and vocabulary mapping", "draft 01_methods... Canonical terms; guarded mapping, two-model adjudication", "~400", "T, P"),
    ("Stage 4: Catalogue and CDM", "draft 01_methods...; Figure 2", "~450", "K, M"),
    ("Stage 5: Evaluation without human annotation", "draft 01_methods... Computational validation + 05_supplement... Method; Figure 3; rule: concordance, not accuracy", "~700", "N01-N11"),
    ("Results: what each program contributed", "draft 02_results.md 3-7; 04/05 supplements; Figure 4, Table 2", "~900", "L05-L12, E, J, N02-N08"),
    ("Recommendations", "new interpretive text; Table 3", "~300", ""),
    ("Limitations", "draft 03_discussion.md Limitations + Structure is not semantics", "~300", ""),
]

ENDMATTER = ["Key Points (3-5 sentences, plan §5)", "Data availability (deposited bundles)",
             "Funding", "Conflict of interest", "AI-use statement (required by OUP policy)",
             "Reference list (below; BiB style)"]

BODY = r"""\documentclass[11pt,a4paper]{article}
\usepackage[margin=2.5cm]{geometry}
\usepackage[T1]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage{booktabs}
\setlength{\parskip}{6pt}
\setlength{\parindent}{0pt}

%% ------------------------------------------------------------------
%% Problem Solving Protocol -- PROSE IS NOT WRITTEN HERE.
%% BiB does not accept papers drafted by LLMs. The authors write the
%% text from the claim register; every section below is a placeholder
%% carrying its source and word budget. RE-NUMBER the bibliography by
%% first appearance once prose is placed (BiB numbering rule).
%% ------------------------------------------------------------------

\title{Microbiome-CDM: An LLM-driven common data model and knowledge
extraction pipeline for human microbiome literature}
\author{<<authors>>}
\date{}

\begin{document}
\maketitle

\section*{Abstract}
PLACEHOLDER (plan abstract row, \textasciitilde200 words): the problem, the protocol, three headline results.
% authors write; drafts anchor: paper/publication/manuscript_draft/

\paragraph{Keywords.} microbiome; common data model; named entity recognition; large language models; text mining; data provenance % up to 6

"""

def placeholders(sec):
    h, src, w, claims = sec
    tag = ("; claim IDs " + claims) if claims else ""
    return (f"\\section{{{h}}}\n"
            f"PLACEHOLDER ({w} words per {texify(PLAN)}, section map 2026-11-03) --- {texify(src)}{tag}.\\\\\n"
            "BiB policy: prose written by the authors only.\n")


TEX = BODY
for s in SECTIONS:
    TEX += placeholders(s) + "\n"
TEX += "\\section*{Endmatter (placeholders)}\n\\begin{itemize}\n" + "\n".join(f"\\item {texify(x)}" for x in ENDMATTER) + "\n\\end{itemize}\n\n"

# figure/table slots
FIGS = [("fig1_protocol.pdf", "Protocol flowchart: 5 stages, programs per stage, counts on arrows"),
        ("fig_overview.pdf", "CDM architecture and provenance spine (Figure 2 slot; plan FIGURE_PLAN F3)"),
        ("figE_benchmark_transfer.pdf", "Evaluation layers (Figure 3 slot)"),
        ("fig4_results.pdf", "Per-program results (Figure 4 slot)")]
TEX += "\\section*{Figures (slots)}\n"
TEX += "\\\\\n".join(f"Slot for \\texttt{{{f.replace('_', chr(92) + '_')}}} --- {texify(c)}" for f, c in FIGS) + "\n\n"
TEX += "\\section*{Tables (slots)}\n"
TEX += ("Table 1: programs and their roles (from tables/table1\\_programs.csv -- plan Table 1);\\\\"
        "Table 2: results by program (plan Table 2);\\\\"
        "Table 3: recommendations / decision guide (plan Table 3).\n\n")

# verified accounting table (all numbers traceable; for the authors' use, not prose)
TEX += r"""\section*{Verification accounting (verified data for the authors; regenerate from the merged evidence file)}

\begin{table}[h]
\centering
\begin{tabular}{lrr}
\toprule
Evidence-anchored verdict (2026-11-07, \emph{DeepSeek-V4.1-Flash}) & $n$ & share \\
\midrule
SUPPORTED & 14{,}363 & 55.7\% \\
PARTIAL & 5{,}780 & 22.4\% \\
NOT\_SUPPORTED & 4{,}618 & 17.9\% \\
CONFLICTS & 860 & 3.3\% \\
NO\_EVIDENCE (quote judged unusable) & 93 & 0.4\% \\
unjudged (69 no-evidence rows; 5 unparsed after retries) & 74 & 0.3\% \\
\midrule
total canonical triples & 25{,}788 & 100\% \\
\bottomrule
\end{tabular}
\caption{Model judgements, not accuracy and not human validation.
Source: \texttt{outputs/results/evidence\_judge\_all\_2026-11-07/REPORT.md} +
\texttt{merged\_triples.csv.gz} (string-level judges of 2026-11-03 and 2026-11-07 are context
columns there).}
\end{table}
""" + ""

# bibliography
TEX += "\\begin{thebibliography}{55}\n%\n%% GENERATED 2026-11-07 from\n%% ../submission_readiness/references_source/bibliography.json (Crossref/PubMed/arXiv/HF/GitHub API, 56 records, 0 errors).\n%% Provisional numbering = pipeline-phase order; RENUMBER by first appearance\n%% before submission and cite [n] (before punctuation) in the prose.\n%%\n"
n = 0
for _sec, keys in SECTION:
    for k in keys:
        n += 1
        TEX += f"\\bibitem{{{k}}}\n{texify(entry(k))}\n"
TEX += "\\end{thebibliography}\n\n\\end{document}\n"

out = HERE / "main.tex"
out.write_text(TEX, encoding="utf-8")
print(f"wrote {out} ({n} bibitems)")
