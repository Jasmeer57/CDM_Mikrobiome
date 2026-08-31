"""
Build a ground-truth "is_correct" set for Claim D from cross-source agreement.

An entity is considered correct if it appears in:
  - 2+ LLM extractions across different papers, OR
  - 1+ LLM extraction AND 1+ spaCy NER detection (any model)

This is a non-circular proxy: it doesn't use the LLM's own confidence
score as the ground truth label.
"""
import sys, io, csv, json
from pathlib import Path
from collections import defaultdict

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LLM_DIR = REPO_ROOT / "paper_claims" / "_llm_runs"
SPACY_DIR = REPO_ROOT / "paper_claims" / "_spacy_runs"


def norm(t):
    return (t or "").strip().lower()


def load_llm_by_norm(llm_dir: Path):
    """norm -> list of (term, type, paper, confidence)"""
    out = defaultdict(list)
    for j in sorted(llm_dir.glob("*.cdm_entities.json")):
        try:
            d = json.loads(j.read_text(encoding="utf-8"))
        except Exception:
            continue
        paper = j.stem.replace(".cdm_entities", "")
        inner = d.get("results", {}).get("cdm_entities", {}) or {}
        for etype, lst in inner.items():
            for e in (lst or []):
                term = e.get("entity") or e.get("term")
                if not term:
                    continue
                out[norm(term)].append((term.strip(), etype, paper, float(e.get("confidence") or 0)))
    return out


def load_spacy_set(spacy_dir: Path):
    out = defaultdict(list)
    for j in sorted(spacy_dir.glob("*.spacy_ner.csv")):
        paper = j.stem.replace(".spacy_ner", "")
        try:
            with open(j, "r", encoding="utf-8", newline="") as f:
                r = csv.DictReader(f)
                for row in r:
                    term = (row.get("term") or "").strip()
                    label = (row.get("labels") or "").strip()
                    if not term or len(term) < 2 or label == "ENTITY":
                        continue
                    out[norm(term)].append((term, label, paper))
        except Exception:
            continue
    return out


def main():
    llm = load_llm_by_norm(LLM_DIR)
    spc = load_spacy_set(SPACY_DIR)

    # For every LLM entity, decide if "correct" using cross-source / cross-paper.
    gold = {}
    n_2plus_papers = 0
    n_cross_source = 0
    n_total = 0
    for n, recs in llm.items():
        papers = {r[2] for r in recs}
        in_spacy = n in spc
        is_correct = (len(papers) >= 2) or in_spacy
        # record the original term form
        gold[recs[0][0]] = bool(is_correct)
        n_total += 1
        if len(papers) >= 2: n_2plus_papers += 1
        if in_spacy: n_cross_source += 1

    print(f"LLM entity norms: {n_total}")
    print(f"  >=2 papers:    {n_2plus_papers}")
    print(f"  in spaCy vocab: {n_cross_source}")
    print(f"  correct:        {sum(gold.values())}")
    print(f"  not correct:    {sum(1 for v in gold.values() if not v)}")

    out = Path(__file__).parent / "gold.json"
    out.write_text(json.dumps(gold, indent=2), encoding="utf-8")
    print(f"\nWrote: {out}")


if __name__ == "__main__":
    main()
