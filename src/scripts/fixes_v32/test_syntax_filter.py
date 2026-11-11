"""Constructed checks for the Fix B syntactic filter (sentences written from general knowledge; no benchmark data).

    PYTHONPATH=<scispacy model overlay> python src/scripts/fixes_v32/test_syntax_filter.py

Prints each case with status and dependency edges; exits non-zero if an expectation fails. Written with Claude Code (declare).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import syntax_filter as SF  # noqa: E402

CASES = [  # (sentence, a, b, expected connected)
    ("Faecalibacterium prausnitzii was depleted in patients with Crohn's disease.", "Faecalibacterium prausnitzii", "Crohn's disease", True),
    ("Butyrate improves intestinal barrier function.", "Butyrate", "intestinal barrier function", True),
    ("Bacteroides, Prevotella and Ruminococcus were detected in all samples.", "Bacteroides", "Prevotella", False),
    ("Bacteroides, Prevotella and Ruminococcus were detected in all samples.", "Prevotella", "samples", True),
    ("We observed a positive correlation between Akkermansia and insulin sensitivity.", "Akkermansia", "insulin sensitivity", True),
    ("Akkermansia and insulin sensitivity were positively correlated.", "Akkermansia", "insulin sensitivity", True),
    ("Stool samples were collected at baseline, and serum IL-6 was measured by ELISA.", "Stool samples", "ELISA", False),
    ("Escherichia coli produces colibactin, a genotoxin linked to colorectal cancer.", "colibactin", "colorectal cancer", True),
    ("Lactobacillus reuteri reduced inflammation in mice fed a high-fat diet.", "Lactobacillus reuteri", "inflammation", True),
    ("Inflammatory bowel disease manifests as chronic diarrhoea and abdominal pain.", "Inflammatory bowel disease", "chronic diarrhoea", True),
    ("Metformin, aspirin and statins are common medications in older adults.", "Metformin", "aspirin", False),
    ("Dysbiosis is driven by antibiotic exposure in early life.", "Dysbiosis", "antibiotic exposure", True),
    ("Clostridioides difficile infection; Helicobacter pylori gastritis.", "Clostridioides difficile infection", "Helicobacter pylori gastritis", False),
    ("Rifaximin increased Bifidobacterium and decreased Veillonella.", "Rifaximin", "Veillonella", True),
    ("Patients were recruited in Bonn, and Bacteroides was quantified by qPCR.", "Patients", "qPCR", False),
    ("Short-chain fatty acids contribute to colonic health.", "Short-chain fatty acids", "colonic health", True),
]


def main():
    nlp = SF.load()
    bad = 0
    for s, a, b, exp in CASES:
        doc = nlp(SF.norm_text(s))
        r = SF.judge(doc, a, b, nlp_tok=nlp.tokenizer)
        ok = r["connected"] == exp
        bad += not ok
        print("OK  " if ok else "MISS", f"{r['status']:22} {r['edges']}  [{a}] / [{b}]  :: {s}")
        if not ok:
            print("     parse:", [(t.text, t.dep_, t.head.text, t.pos_) for t in doc])
    print(f"{len(CASES) - bad}/{len(CASES)} as expected")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
