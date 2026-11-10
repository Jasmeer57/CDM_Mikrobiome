"""Find sentences in a draft that share long word sequences with other texts. Reports; never rewrites.

    python .opencode/skills/text-overlap-check/overlap_check.py DRAFT [--sources GLOB ...] [--n 8] [--min-share 0.3]
                                                                  [--log-model NAME] [--json]

Default sources (each labelled, because the right action depends on the kind of source):
  ai_notes        paper/publication/manuscript_draft/*.md, paper/publication/submission_readiness/*.md,
                  paper/publication/manuscript_bib/*.md, docs/reports/*.md   (notes written with AI tools)
  corpus_papers   data/papers_txt/*.txt                                      (published papers; add --corpus)
Extra --sources GLOBs are labelled 'other' unless given as LABEL=GLOB (e.g. own_preprint=paper/preprint/*.txt).
A sentence is reported when at least --min-share of its word n-grams occur in one source; the longest shared
run of words is shown so the author can see what matches.
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
LOG = ROOT / "paper/publication/submission_readiness/AI_ASSIST_LOG.md"
DEFAULT = [("ai_notes", g) for g in ("paper/publication/manuscript_draft/*.md",
                                     "paper/publication/submission_readiness/*.md",
                                     "paper/publication/manuscript_bib/*.md", "docs/reports/*.md")]
WORD = re.compile(r"[a-z0-9]+(?:[.,'-][a-z0-9]+)*")


def clean(text: str, tex: bool) -> str:
    if tex:
        text = re.sub(r"(?<!\\)%.*", "", text)
        text = re.sub(r"\\(?:cite|ref|label|eqref|includegraphics)\*?(?:\[[^\]]*\])?\{[^}]*\}", " ", text)
        text = re.sub(r"\\[a-zA-Z]+\*?", " ", text)
        text = text.replace("{", " ").replace("}", " ")
    return text


def words(text: str):
    return WORD.findall(text.lower())


def sentences(text: str):
    """(start_line, sentence) pairs."""
    out, buf, start = [], [], None
    for i, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            if buf:
                out.append((start, " ".join(buf)))
                buf, start = [], None
            continue
        for part in re.split(r"(?<=[.!?])\s+(?=[A-Z\[(])", line.strip()):
            if start is None:
                start = i
            buf.append(part)
            if re.search(r"[.!?]$", part):
                out.append((start, " ".join(buf)))
                buf, start = [], None
    if buf:
        out.append((start, " ".join(buf)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("draft", type=Path)
    ap.add_argument("--sources", nargs="*", default=[], help="extra GLOBs (relative to repo root), optionally LABEL=GLOB")
    ap.add_argument("--corpus", action="store_true", help="also index the 453 corpus papers (slower, ~1-2 GB RAM)")
    ap.add_argument("--no-default", action="store_true", help="skip the default ai_notes sources")
    ap.add_argument("--n", type=int, default=8, help="n-gram length in words")
    ap.add_argument("--min-share", type=float, default=0.3)
    ap.add_argument("--log-model")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    draft = a.draft.resolve()

    specs = [] if a.no_default else list(DEFAULT)
    if a.corpus:
        specs.append(("corpus_papers", "data/papers_txt/*.txt"))
    for s in a.sources:
        lab, _, g = s.rpartition("=")
        specs.append((lab or "other", g))
    files = []
    for lab, g in specs:
        for p in sorted(ROOT.glob(g)):
            if p.resolve() != draft and p.is_file():
                files.append((lab, p))

    index = defaultdict(set)                            # hash(n-gram) -> source indexes
    for k, (lab, p) in enumerate(files):
        w = words(clean(p.read_text(encoding="utf-8", errors="replace"), p.suffix == ".tex"))
        for i in range(len(w) - a.n + 1):
            index[hash(" ".join(w[i:i + a.n]))].add(k)

    hits = []
    for line, sent in sentences(clean(draft.read_text(encoding="utf-8"), draft.suffix == ".tex")):
        w = words(sent)
        if len(w) < a.n:
            continue
        grams = [hash(" ".join(w[i:i + a.n])) for i in range(len(w) - a.n + 1)]
        per_src = defaultdict(list)
        for i, g in enumerate(grams):
            for k in index.get(g, ()):
                per_src[k].append(i)
        if not per_src:
            continue
        k, pos = max(per_src.items(), key=lambda kv: len(kv[1]))
        share = len(pos) / len(grams)
        if share < a.min_share:
            continue
        best, run, prev, s0, bs = 0, 0, None, 0, 0     # longest run of consecutive matching n-grams
        for i in pos:
            run, s0 = (run + 1, s0) if prev is not None and i == prev + 1 else (1, i)
            if run > best:
                best, bs = run, s0
            prev = i
        lab, p = files[k]
        hits.append({"line": line, "share": round(share, 2), "source_kind": lab,
                     "source": str(p.relative_to(ROOT)), "shared_run": " ".join(w[bs:bs + best + a.n - 1]),
                     "sentence": sent[:300], "other_sources": len(per_src) - 1})

    out = {"draft": str(draft.relative_to(ROOT)) if draft.is_relative_to(ROOT) else str(draft),
           "sources_indexed": len(files), "n": a.n, "min_share": a.min_share, "flagged": hits}
    if a.json:
        print(json.dumps(out, indent=1))
    else:
        print(f"# Overlap check: {out['draft']} ({len(files)} sources, {a.n}-word sequences, share ≥ {a.min_share})\n")
        for h in sorted(hits, key=lambda h: -h["share"]):
            print(f"- L{h['line']} [{h['source_kind']}] {int(100 * h['share'])}% of sequences in {h['source']}"
                  + (f" (+{h['other_sources']} other sources)" if h["other_sources"] else ""))
            print(f"    longest shared run: \"{h['shared_run']}\"")
        print(f"\n{len(hits)} sentence(s) flagged.")
    if a.log_model:
        new = not LOG.exists()
        with open(LOG, "a", encoding="utf-8") as f:
            if new:
                f.write("# AI-assistance log (for the BiB AI-use declaration)\n\n"
                        "| Date | Tool / model | File | What the tool did | Flags |\n|---|---|---|---|---|\n")
            f.write(f"| {datetime.date.today()} | {a.log_model} | {out['draft']} | text-overlap-check: reported "
                    f"overlapping sentences (no text written) | {len(hits)} sentence(s) |\n")


if __name__ == "__main__":
    main()
