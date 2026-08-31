"""Audit entity quality across LLM and spaCy runs."""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import json, glob, csv, re
from collections import Counter

def is_garbage(term):
    if not term or len(term) < 3:
        return "too_short"
    if re.match(r'^[\d≤≥<>=+\-]+\s*$', term):
        return "numeric_or_symbol"
    if re.match(r'^[A-Z][a-z]+-\d+$', term):
        return "author_fragment"
    if 'partment' in term.lower() or 'hiroko' in term.lower():
        return "affiliation"
    if term.lower() in {'nucleic acids res', 'demon-', 'ated', 'bi dobacterium', 'ples'}:
        return "truncated_or_journal"
    if re.match(r'^[ACGT]{10,}$', term):
        return "dna_sequence"
    if term.endswith('-') or term.startswith('-'):
        return "hyphen_fragment"
    return None

llm_dir = r'C:\Users\jkalra\Documents\Microbiome-CDM\paper_claims\_llm_runs\*.cdm_entities.json'
spacy_dir = r'C:\Users\jkalra\Documents\Microbiome-CDM\paper_claims\_spacy_runs\*.spacy_ner.csv'

print("=== LLM ENTITY AUDIT ===")
llm_terms = []
for f in sorted(glob.glob(llm_dir)):
    d = json.load(open(f))
    cdm = d.get("results", {}).get("cdm_entities", {})
    for etype, lst in cdm.items():
        for e in lst:
            term = e.get("entity", "")
            llm_terms.append((term, etype))

print(f"Total LLM entity mentions: {len(llm_terms)}")
garbage = [(t, et, is_garbage(t)) for t, et in llm_terms if is_garbage(t)]
print(f"Garbage LLM entities: {len(garbage)}")
for reason, cnt in Counter(g for _, _, g in garbage).most_common():
    print(f"  {reason}: {cnt}")
    for t, et, _ in [(t, et, g) for t, et, g in garbage if g == reason][:5]:
        print(f"    '{t}' ({et})")

print()
print("=== SPACY ENTITY AUDIT ===")
spacy_terms = []
for f in sorted(glob.glob(spacy_dir)):
    with open(f, encoding="utf-8", errors="replace", newline="") as fh:
        content = fh.read().replace("\x00", "")
    import io as _io
    r = csv.DictReader(_io.StringIO(content))
    for row in r:
        term = row.get("term", "").strip()
        label = row.get("labels", "").strip()
        if term:
            spacy_terms.append((term, label))

print(f"Total spaCy entity mentions: {len(spacy_terms)}")
garbage_s = [(t, lb, is_garbage(t)) for t, lb in spacy_terms if is_garbage(t)]
print(f"Garbage spaCy entities: {len(garbage_s)}")
for reason, cnt in Counter(g for _, _, g in garbage_s).most_common():
    print(f"  {reason}: {cnt}")
    for t, lb, _ in [(t, lb, g) for t, lb, g in garbage_s if g == reason][:5]:
        print(f"    '{t}' ({lb})")

print()
print("=== TYPE DISTRIBUTION ===")
print("LLM types:", Counter(et for _, et in llm_terms).most_common())
print("spaCy types:", Counter(lb for _, lb in spacy_terms).most_common())
