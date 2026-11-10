#!/usr/bin/env python3
"""Exact -> fuzzy -> embedding deduplication of CDM terms and accepted ontology concepts.

Context-aware: the embedding pass needs BOTH the name (SapBERT) and the contextual
definition (MiniLM; term definitions from term_definitions_llm_2026-11-09, ontology
definitions for concepts) to agree.

Guards (any one blocks a merge, in every pass):
  type      different CDM type
  number    different digit runs (IL-6/IL-8, 16S/18S, CD4/CD8, strain numbers)
  letter    different single-letter tokens (vitamin B/D, hepatitis B/C, type A/B)
  sign      different +/- markers (CD4+ / CD4-)
  prefix    opposite prefixes on the same stem (hyper/hypo, pre/post, intra/extra...)
  protected one side has a protected word the other lacks (receptor, inhibitor, alpha...)
  concept   both terms have an accepted ontology concept and they differ
  taxon     organism names merge only if same NCBI taxon, abbreviation with identical
            epithet (B. fragilis = Bacteroides fragilis), or differing only by
            spp./genus/bacteria - otherwise different taxa are never merged
  ontology  (concepts) two concepts from the same ontology are never merged

Nothing is applied to the CDM: output is a new labelled layer of merge proposals in
outputs/results/concept_dedup_2026-11-09/<entity>/.

  python dedup_three_pass.py --entity terms --stages exact,fuzzy        # CPU
  python dedup_three_pass.py --entity terms --stages exact,fuzzy,embed  # GPU job
"""
import argparse
import collections
import json
import re
import sqlite3
import time
import unicodedata
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
DB = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
DEFS = ROOT / "outputs/results/term_definitions_llm_2026-11-09/all/definitions.jsonl"
ONTO = ROOT / "outputs/results/ontology_definitions_2026-11-09/concept_ontology_info.jsonl"
CURIE_MAP = ROOT / "outputs/results/concept_dedup_2026-11-09/stage_a/concept_curie_map.tsv"
OUT_BASE = ROOT / "outputs/results/concept_dedup_2026-11-09"

FUZZY_MIN = 92.0
NAME_COS_MIN = 0.90       # SapBERT, name vs name
NAME_COS_MIN_EVID = 0.85  # when an abbreviation/synonym link supports the pair
CTX_COS_MIN = 0.80        # MiniLM, contextual definition vs contextual definition
TOPK = 10
SAPBERT = "cambridgeltl/SapBERT-from-PubMedBERT-fulltext"
MINILM = "sentence-transformers/all-MiniLM-L6-v2"

GREEK = {"α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "ε": "epsilon", "κ": "kappa",
         "λ": "lambda", "μ": "u", "µ": "u", "ω": "omega", "θ": "theta", "σ": "sigma", "τ": "tau",
         "ζ": "zeta", "η": "eta", "ι": "iota", "ν": "nu", "ξ": "xi", "π": "pi", "ρ": "rho",
         "φ": "phi", "χ": "chi", "ψ": "psi"}
PROTECTED = {
    "alpha", "beta", "gamma", "delta", "epsilon", "kappa", "lambda", "omega", "theta", "sigma", "tau",
    "receptor", "receptors", "ligand", "inhibitor", "inhibitors", "antagonist", "agonist", "antibody",
    "antibodies", "anti", "non", "not", "no", "without", "free", "deficient", "deficiency", "resistant",
    "resistance", "sensitive", "susceptible", "knockout", "ko", "mutant", "wild", "wt", "null",
    "positive", "negative", "pos", "neg", "male", "female", "men", "women", "acute", "chronic",
    "early", "late", "high", "low", "increased", "decreased", "total", "serum", "plasma", "fecal",
    "faecal", "urinary", "oral", "gut", "vaginal", "skin", "infant", "infants", "children", "adult",
    "adults", "maternal", "neonatal", "primary", "secondary", "type", "subtype", "precursor",
    "metabolism", "biosynthesis", "degradation", "transport", "pathway", "gene", "genes", "protein",
    "proteins", "mrna", "rna", "dna", "level", "levels", "ratio", "index", "score", "risk", "virus",
    "phage", "fungi", "fungal", "archaea", "small", "large", "short", "long", "chain", "upper", "lower",
}
OPP_PREFIXES = ["hyper", "hypo", "pre", "post", "intra", "extra", "inter", "endo", "exo", "pro",
                "anti", "over", "under", "up", "down", "hetero", "homo", "mono", "di", "tri", "poly",
                "uni", "bi", "ortho", "para", "meta", "in", "ex", "an", "non", "de", "un"]
TAXON_FILLER = {"spp", "sp", "genus", "bacteria", "bacterium", "species"}
ROMAN = {"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii"}


# ---------------------------------------------------------------- normalisation
def base(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = "".join(GREEK.get(ch, ch) for ch in s)
    s = s.replace("−", "-").replace("–", "-").replace("þ", "+").lower().strip()  # þ: PDF artefact for +
    s = s.replace("æ", "ae").replace("ae", "e").replace("oe", "e")  # haem/hem, faecal/fecal, oesophagus
    s = re.sub(r"(?<=[a-z0-9])\s?\+(?=\W|$)", " pos ", s)
    s = re.sub(r"(?<=[a-z0-9])-(?=\s*$)", " neg ", s)
    return s


def tokens(s: str) -> list:
    return [t for t in re.split(r"[^a-z0-9.]+", base(s)) if t and t != "."]


def depl(t: str) -> str:
    if len(t) > 4 and t.endswith("s") and not re.search(r"(ss|us|is|ies|ics|ys)$", t):
        return t[:-1]
    return t


def exact_key(s: str, organism: bool) -> str:
    toks = [t.strip(".") for t in tokens(s)]
    if toks and not organism:
        toks[-1] = depl(toks[-1])
    return "".join(toks)


def spaced(s: str) -> str:
    return " ".join(t.strip(".") for t in tokens(s))


SAFE_SUFFIX = {"s", "es", "ed", "d", "al", "e"}
FOOTNOTE = {"a", "b", "c", "d", "e"}  # stray superscript letters: Canadab, Rodionovd


def fuzzy_ok(a, b):
    """Fuzzy may only fix ONE word, and only harmlessly: a suffix variant (-s/-es/-ed/-al),
    a stray footnote letter (Canada/Canadam), or a single-letter typo in a long word
    whose rare spelling is rare in the corpus. Blocks breath/breadth, regimens/regimes,
    'chemotherapy drugs'/'chemotherapy drug use'."""
    from rapidfuzz.distance import Levenshtein
    ta = [depl(t) for t in spaced(a["text"]).split()]
    tb = [depl(t) for t in spaced(b["text"]).split()]
    ca, cb = collections.Counter(ta), collections.Counter(tb)
    xa, xb = list((ca - cb).elements()), list((cb - ca).elements())
    if not xa and not xb:
        return True
    if len(xa) != 1 or len(xb) != 1:
        return False
    x, y = xa[0], xb[0]
    s, l = (x, y) if len(x) <= len(y) else (y, x)
    if l.startswith(s):
        extra = l[len(s):]
        return extra in SAFE_SUFFIX or (extra in FOOTNOTE and len(s) >= 5 and not re.search(r"\d", s))
    if min(len(x), len(y)) >= 9 and Levenshtein.distance(x, y) == 1:
        rare, common = sorted((a["mentions"], b["mentions"]))
        return rare <= 1 and common >= 5
    return False


SYMBOL = re.compile(r"^(?=.*[A-Z0-9])[A-Za-z0-9\-]{2,10}$")  # one-token gene/protein-like symbol
EMBED_FILLER = {"the", "of", "a", "an", "and", "from", "in", "for", "with", "members", "member", "only",
                "step", "steps", "spp", "sp", "species", "genus", "genera"}


def explained(a_text, b_text, strong):
    """Embedding merges are applied only if the wording difference is fully explained:
    same content words (order, plural, filler aside), or every extra word is part of an
    acronym expansion of a word on the other side (NK <-> natural killer), or a strong
    whole-string link (LLM full form, ontology synonym, initials). Otherwise -> review."""
    def toks(t):
        return [depl(x.strip(".")) for x in tokens(t) if x.strip(".") not in EMBED_FILLER]
    ta, tb = toks(a_text), toks(b_text)
    sa, sb = set(ta), set(tb)
    if sa == sb and sa:
        return "same_words"
    if strong:
        return "full_form_or_synonym"
    xa, xb = [t for t in ta if t not in sb], [t for t in tb if t not in sa]
    for short, long_ in ((xa, xb), (xb, xa)):
        if len(short) == 1 and len(long_) >= 2 and short[0] == "".join(w[0] for w in long_):
            return "acronym_expansion"
        if not short and len(long_) >= 2 and "".join(w[0] for w in long_) in (sa & sb):
            return "acronym_expansion"  # "human immunodeficiency virus (HIV) infection" vs "HIV infection"
    return None


BINOMIAL = re.compile(r"^[A-Z][a-z]+ [a-z]{3,}")
ABBREV = re.compile(r"^[A-Z]\.\s?[a-z]{3,}")


def is_taxon(e) -> bool:
    # BINOMIAL alone is not used: "Wilcoxon matched-pairs" or "Statistical evaluation" look binomial
    return (e["type"] == "ORGANISM" or (e.get("curie") or "").startswith("NCBITaxon:")
            or bool(ABBREV.match(e["text"])))


# ---------------------------------------------------------------- guards
def digits(s):
    return sorted(re.findall(r"\d+", base(s)))


def singles(s):
    # single letters / roman numerals; a genus initial ("B." in "B. fragilis") and digits are not letters
    return sorted(t for t in (x for x in tokens(s) if not x.endswith("."))
                  if (len(t) == 1 and t.isalpha()) or t in ROMAN)


def acronym(a: str, b: str) -> bool:
    """True if one string is the initials of the other: SCFA <-> short-chain fatty acids."""
    for short, long_ in ((a, b), (b, a)):
        s = re.sub(r"[^a-z]", "", base(short))
        words = [w for w in re.split(r"[^a-z]+", base(long_)) if w and w not in ("of", "and", "the", "in")]
        if 2 <= len(s) <= 8 and len(words) >= 2 and len(re.sub(r"[^a-z0-9]", "", base(short))) == len(s):
            if s in ("".join(w[0] for w in words), "".join(w[0] for w in words)[:len(s)]) and len(s) >= len(words) - 1:
                if s == "".join(w[0] for w in words):
                    return True
    return False


def signs(s):
    t = tokens(s)
    return sorted(x for x in t if x in ("pos", "neg"))


def opposite_prefix(a_toks, b_toks):
    for x in a_toks:
        for y in b_toks:
            if x == y:
                continue
            for p in OPP_PREFIXES:
                for q in OPP_PREFIXES:
                    if p != q and x.startswith(p) and y.startswith(q) and x[len(p):] == y[len(q):] and len(x) - len(p) >= 3:
                        return True
            for p in OPP_PREFIXES:  # prefix on one side only: "toxic" vs "nontoxic"
                if (x == p + y or y == p + x) and min(len(x), len(y)) >= 3:
                    return True
    return False


def taxon_ok(a, b) -> bool:
    ca, cb = a.get("curie") or "", b.get("curie") or ""
    if ca.startswith("NCBITaxon:") and ca == cb:
        return True
    ta = [depl(t.strip(".")) for t in tokens(a["text"]) if t.strip(".") not in TAXON_FILLER]
    tb = [depl(t.strip(".")) for t in tokens(b["text"]) if t.strip(".") not in TAXON_FILLER]
    if not ta or ta == tb:
        return bool(ta)
    if len(ta) != len(tb):
        return False
    raw_a, raw_b = tokens(a["text"]), tokens(b["text"])
    full = False
    for i, (x, y) in enumerate(zip(ta, tb)):
        if x == y:
            if i == 0:
                full = True
            continue
        if i == 0:  # genus position: abbreviation allowed (B. <-> Bacteroides)
            xa = any(t == x + "." for t in raw_a) or len(x) == 1
            ya = any(t == y + "." for t in raw_b) or len(y) == 1
            if xa and not ya and y.startswith(x):
                full = True
                continue
            if ya and not xa and x.startswith(y):
                full = True
                continue
        return False  # epithet/strain differs -> different taxon
    return full


def guard(a, b, entity, evid=False):
    """Return None if the pair may merge, else the blocking reason.

    evid=True means an abbreviation/synonym link (LLM full form, ontology synonym, or
    initials) connects the two; then only the word-level checks are skipped - numbers,
    letters, signs, concepts and taxa still apply."""
    if a["type"] != b["type"]:
        return "type"
    if entity == "concepts" and a["ontology"] == b["ontology"]:
        return "ontology"
    ca, cb = a.get("curie"), b.get("curie")
    if entity == "terms" and ca and cb and ca != cb:
        return "concept"
    if digits(a["text"]) != digits(b["text"]):
        return "number"
    if SYMBOL.match(a["text"].strip()) and SYMBOL.match(b["text"].strip()) and exact_key(a["text"], True) != exact_key(b["text"], True):
        return "symbol"  # PSMC2 vs PSME2, CXCL8 vs CXCL9: different gene/protein symbols
    if singles(a["text"]) != singles(b["text"]):
        return "letter"
    if signs(a["text"]) != signs(b["text"]):
        return "sign"
    evid = evid or acronym(a["text"], b["text"])
    ta = {depl(t.strip(".")) for t in tokens(a["text"])}
    tb = {depl(t.strip(".")) for t in tokens(b["text"])}
    if not evid and (ta ^ tb) & {depl(p) for p in PROTECTED}:
        return "protected"
    if not evid and opposite_prefix(ta - tb, tb - ta):
        return "prefix"
    if (is_taxon(a) or is_taxon(b)) and not taxon_ok(a, b):
        return "taxon"
    return None


# ---------------------------------------------------------------- loading
def load_terms():
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    curie = {}
    for line in open(CURIE_MAP, encoding="utf-8").read().splitlines()[1:]:
        cid, cu, *_ = line.split("\t")
        curie[cid] = cu
    t2c = {t: curie.get(c, c) for t, c in db.execute(
        "select term_id, concept_id from term_concept_map where mapping_disposition_reviewed='ACCEPTED'")}
    defs = {}
    with open(DEFS, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            defs[r["term_id"]] = r
    ents = []
    for tid, term, ctype, mc in db.execute("select term_id, term, cdm_type, coalesce(mention_count,0) from canonical_term"):
        d = defs.get(tid, {})
        ev = {exact_key(x, False) for x in [d.get("full_form") or ""] + list(d.get("synonyms") or []) if x}
        ff = {exact_key(d.get("full_form") or "", False)} - {""}
        ents.append({"id": tid, "text": term or "", "type": ctype or "ENTITY", "curie": t2c.get(tid),
                     "ctx": d.get("definition") or "", "status": d.get("status") or "",
                     "mentions": mc, "evid": ev - {""}, "strong": ff})
    return ents


def load_concepts():
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = [l.split("\t") for l in open(CURIE_MAP, encoding="utf-8").read().splitlines()[1:]]
    acc = {cid: cu for cid, cu, a, *_ in rows if a == "1"}
    label = dict(db.execute("select concept_id, concept_label from concept"))
    ctype = collections.defaultdict(collections.Counter)
    for cid, ty in db.execute("""select m.concept_id, t.cdm_type from term_concept_map m
                                 join canonical_term t using(term_id)
                                 where m.mapping_disposition_reviewed='ACCEPTED'"""):
        ctype[acc.get(cid)][ty] += 1
    info = {}
    with open(ONTO, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            info[acc.get(r["concept_id"], r["concept_id"])] = r
    by_curie = collections.defaultdict(list)
    for cid, cu in acc.items():
        by_curie[cu].append(cid)
    ents = []
    for cu, cids in by_curie.items():
        lab = next((label.get(c) for c in cids if label.get(c)), "") or ""
        r = info.get(cu, {})
        ents.append({"id": cu, "text": lab, "type": (ctype[cu].most_common(1) or [("ENTITY", 0)])[0][0],
                     "curie": cu, "ontology": cu.split(":")[0] if ":" in cu and not cu.startswith("http") else cu.rsplit("/", 1)[0],
                     "ctx": r.get("definition") or "", "status": "DEFINED", "mentions": sum(ctype[cu].values()),
                     "evid": {exact_key(s, False) for s in (r.get("synonyms") or []) if s},
                     "strong": {exact_key(s, False) for s in (r.get("synonyms") or []) if s}})  # ontology synonyms are sourced
    return ents


# ---------------------------------------------------------------- union-find
class UF:
    def __init__(self, n, ents):
        self.p = list(range(n)); self.e = ents

    def find(self, i):
        while self.p[i] != i:
            self.p[i] = self.p[self.p[i]]; i = self.p[i]
        return i

    def rep(self, i):
        return self.find(i)

    def union(self, i, j):
        a, b = self.find(i), self.find(j)
        if a == b:
            return False
        def rank(k):  # a full name heads the cluster before an abbreviation (B. infantis), then most mentions
            return (not ABBREV.match(self.e[k]["text"] or ""), self.e[k]["mentions"], -k)
        if rank(b) > rank(a):
            a, b = b, a
        self.p[b] = a
        return True


# ---------------------------------------------------------------- passes
def pass_exact(ents, uf, edges, blocked, entity):
    groups = collections.defaultdict(list)
    for i, e in enumerate(ents):
        k = exact_key(e["text"], is_taxon(e))
        if k:
            groups[(e["type"], k)].append(i)
    n = 0
    for (ty, k), idx in groups.items():
        if len(idx) < 2:
            continue
        idx.sort(key=lambda i: -ents[i]["mentions"])
        head = idx[0]
        for j in idx[1:]:
            why = guard(ents[head], ents[j], entity) if entity == "concepts" or ents[head].get("curie") else None
            if why in ("ontology", "concept"):
                blocked[why] += 1; continue
            if uf.union(head, j):
                edges.append((head, j, "exact", 100.0, "")); n += 1
    return n


def pass_fuzzy(ents, uf, edges, blocked, entity, samples):
    from rapidfuzz import fuzz, process
    reps = sorted({uf.find(i) for i in range(len(ents))})
    buckets = collections.defaultdict(list)
    for i in reps:
        s = spaced(ents[i]["text"])
        if len(s.replace(" ", "")) >= 4:
            buckets[(ents[i]["type"], s.replace(" ", "")[:2])].append(i)
    cand = []
    for key, idx in buckets.items():
        if len(idx) < 2:
            continue
        strs = [spaced(ents[i]["text"]) for i in idx]
        for a0 in range(0, len(idx), 2000):
            M = process.cdist(strs[a0:a0 + 2000], strs, scorer=fuzz.ratio, score_cutoff=FUZZY_MIN,
                              workers=-1, dtype="uint8")
            for ra, row in enumerate(M):
                a = a0 + ra
                for b in row.nonzero()[0]:
                    if b > a:
                        cand.append((float(row[b]), idx[a], idx[b]))
    cand.sort(reverse=True)
    n = 0
    for sc, i, j in cand:
        why = guard(ents[i], ents[j], entity) or guard(ents[uf.find(i)], ents[uf.find(j)], entity)
        if not why and not (fuzzy_ok(ents[i], ents[j]) and fuzzy_ok(ents[uf.find(i)], ents[uf.find(j)])):
            why = "fuzzy_word_change"
        if why:
            blocked[why] += 1
            if len(samples[why]) < 40:
                samples[why].append({"pass": "fuzzy", "score": sc, "a": ents[i]["text"], "b": ents[j]["text"], "type": ents[i]["type"]})
            continue
        if uf.union(i, j):
            edges.append((i, j, "fuzzy", sc, "")); n += 1
    return n


ABBR_RX = re.compile(r"^([A-Z])\.\s?([a-z]{3,})((?:\s+(?:subsp\.|var\.|ser\.)?\s*[a-z]{3,})*)$")
FULL_RX = re.compile(r"^([A-Z][a-z]{2,})\s+([a-z]{3,})((?:\s+(?:subsp\.|var\.|ser\.)?\s*[a-z]{3,})*)$")


def pass_abbrev(ents, uf, edges, blocked, entity, samples):
    """Genus abbreviation: 'L. crispatus' -> 'Lactobacillus crispatus', only if exactly ONE genus in the
    corpus fits the initial + epithet (L. casei is left alone: Lactobacillus or Lacticaseibacillus).
    Same CDM type, or the abbreviation is untyped ENTITY. All other guards still apply."""
    if entity != "terms":
        return 0
    reps = sorted({uf.find(i) for i in range(len(ents))})
    full = collections.defaultdict(lambda: collections.defaultdict(list))  # (initial, rest) -> genus -> [idx]
    for i in reps:
        m = FULL_RX.match(ents[i]["text"].strip())
        if m and m.group(2) not in TAXON_FILLER:
            full[(m.group(1)[0], (m.group(2) + m.group(3)).lower())][m.group(1).lower()].append(i)
    n = 0
    for i in reps:
        m = ABBR_RX.match(ents[i]["text"].strip())
        if not m or m.group(2) in TAXON_FILLER:
            continue
        cands = full.get((m.group(1), (m.group(2) + m.group(3)).lower()))
        if not cands:
            continue
        if len(cands) > 1:  # fold genus spellings that differ only by a typo/plural (Bifobacterium, Kklebsiella)
            from rapidfuzz.distance import Levenshtein
            order = sorted(cands, key=lambda g: -sum(ents[k]["mentions"] for k in cands[g]))
            folded = {}
            for g in order:
                home = next((h for h in folded if Levenshtein.distance(g, h) <= 2 or g.startswith(h[:-1]) or h.startswith(g[:-1])), None)
                folded.setdefault(home or g, []).extend(cands[g])
            cands = folded
        if len(cands) > 1:
            blocked["abbrev_ambiguous"] += 1
            if len(samples["abbrev_ambiguous"]) < 40:
                samples["abbrev_ambiguous"].append({"pass": "abbrev", "a": ents[i]["text"],
                                                    "genera": sorted(cands)})
            continue
        targets = next(iter(cands.values()))
        ea = ents[i]
        tgt = [j for j in targets if ents[j]["type"] == ea["type"]] or \
              ([j for j in targets if ents[j]["type"] == "ORGANISM"] if ea["type"] == "ENTITY" else [])
        if not tgt:
            blocked["abbrev_type"] += 1
            continue
        j = max(tgt, key=lambda k: ents[k]["mentions"])
        why = guard({**ea, "type": ents[j]["type"]}, ents[j], entity)
        if why:
            blocked[why] += 1
            continue
        if uf.union(j, i):
            edges.append((j, i, "abbrev", 100.0, f"genus initial -> {ents[j]['text']}"))
            n += 1
    return n


def pass_embed(ents, uf, edges, blocked, entity, samples, review):
    import numpy as np
    import torch
    from sentence_transformers import SentenceTransformer
    from transformers import AutoModel, AutoTokenizer
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    reps = sorted({uf.find(i) for i in range(len(ents))
                   if ents[i]["status"] not in ("NOT_A_CONCEPT", "NON_CONCEPT") and len(ents[i]["text"]) >= 3})
    reps = sorted({uf.find(i) for i in reps})
    names = [ents[i]["text"] for i in reps]
    tok = AutoTokenizer.from_pretrained(SAPBERT)
    mdl = AutoModel.from_pretrained(SAPBERT).to(dev).eval()
    embs = []
    with torch.no_grad():
        for s in range(0, len(names), 512):
            x = tok(names[s:s + 512], padding=True, truncation=True, max_length=32, return_tensors="pt").to(dev)
            embs.append(torch.nn.functional.normalize(mdl(**x).last_hidden_state[:, 0], dim=-1).cpu())
    N = torch.cat(embs).numpy().astype("float32")
    st = SentenceTransformer(MINILM, device=dev)
    ctx_text = [f"{ents[i]['text']}: {ents[i]['ctx']}" if ents[i]["ctx"] else "" for i in reps]
    has_ctx = np.array([bool(t) for t in ctx_text])
    C = st.encode([t or "-" for t in ctx_text], batch_size=512, normalize_embeddings=True,
                  convert_to_numpy=True, show_progress_bar=False).astype("float32")
    by_type = collections.defaultdict(list)
    for k, i in enumerate(reps):
        by_type[ents[i]["type"]].append(k)
    cand = []
    for ty, ks in by_type.items():
        if len(ks) < 2:
            continue
        T = torch.from_numpy(N[ks]).to(dev)
        for s in range(0, len(ks), 4096):
            sims = T[s:s + 4096] @ T.T
            v, nn = sims.topk(min(TOPK + 1, len(ks)), dim=1)
            v, nn = v.cpu().numpy(), nn.cpu().numpy()
            for r in range(v.shape[0]):
                a = ks[s + r]
                for c in range(v.shape[1]):
                    b = ks[nn[r, c]]
                    if b <= a or v[r, c] < NAME_COS_MIN_EVID:
                        continue
                    cand.append((float(v[r, c]), a, b))
    cand.sort(reverse=True)
    n = 0
    for ncos, a, b in cand:
        i, j = reps[a], reps[b]
        ei, ej = ents[i], ents[j]
        ki, kj = exact_key(ei["text"], False), exact_key(ej["text"], False)
        evid = (kj in ei["evid"]) or (ki in ej["evid"])
        ccos = float(C[a] @ C[b]) if has_ctx[a] and has_ctx[b] else None
        if ncos < NAME_COS_MIN and not evid:
            continue
        if ccos is not None and ccos < CTX_COS_MIN:
            blocked["context"] += 1
            if len(samples["context"]) < 40:
                samples["context"].append({"pass": "embed", "name_cos": round(ncos, 3), "ctx_cos": round(ccos, 3),
                                           "a": ei["text"], "b": ej["text"], "type": ei["type"]})
            continue
        if ccos is None and not evid:
            blocked["no_context"] += 1
            continue
        why = guard(ei, ej, entity, evid) or guard(ents[uf.find(i)], ents[uf.find(j)], entity, evid)
        if why:
            blocked[why] += 1
            if len(samples[why]) < 40:
                samples[why].append({"pass": "embed", "name_cos": round(ncos, 3), "a": ei["text"], "b": ej["text"], "type": ei["type"]})
            continue
        strong = (kj in ei["strong"]) or (ki in ej["strong"]) or acronym(ei["text"], ej["text"])
        how = explained(ei["text"], ej["text"], strong)
        ri, rj = ents[uf.find(i)], ents[uf.find(j)]
        if how and (ri is ei and rj is ej or explained(ri["text"], rj["text"],
                    exact_key(rj["text"], False) in ri["strong"] or exact_key(ri["text"], False) in rj["strong"]
                    or acronym(ri["text"], rj["text"]))):
            if uf.union(i, j):
                edges.append((i, j, "embed", round(ncos, 3), f"{how} ctx={ccos if ccos is None else round(ccos, 3)}"))
                n += 1
        else:
            review.append({"a_id": ei["id"], "a": ei["text"], "b_id": ej["id"], "b": ej["text"], "type": ei["type"],
                           "name_cos": round(ncos, 3), "ctx_cos": None if ccos is None else round(ccos, 3),
                           "llm_synonym_link": bool(evid),
                           "why_review": "wording differs beyond order/plural/filler/acronym; may be broader/narrower or related, not identical"})
    return n


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--entity", choices=["terms", "concepts"], required=True)
    ap.add_argument("--stages", default="exact,fuzzy,embed")
    a = ap.parse_args()
    stages = a.stages.split(",")
    out = OUT_BASE / a.entity
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    ents = load_terms() if a.entity == "terms" else load_concepts()
    uf = UF(len(ents), ents)
    edges, blocked, samples = [], collections.Counter(), collections.defaultdict(list)
    counts = {}
    if "exact" in stages:
        counts["exact"] = pass_exact(ents, uf, edges, blocked, a.entity)
        print(f"exact: {counts['exact']} merges  ({time.time() - t0:.0f}s)", flush=True)
    if "fuzzy" in stages:
        counts["fuzzy"] = pass_fuzzy(ents, uf, edges, blocked, a.entity, samples)
        print(f"fuzzy: {counts['fuzzy']} merges  ({time.time() - t0:.0f}s)", flush=True)
    if "fuzzy" in stages or "abbrev" in stages:
        counts["abbrev"] = pass_abbrev(ents, uf, edges, blocked, a.entity, samples)
        print(f"abbrev: {counts['abbrev']} merges  ({time.time() - t0:.0f}s)", flush=True)
    if "embed" in stages:
        review = []
        counts["embed"] = pass_embed(ents, uf, edges, blocked, a.entity, samples, review)
        counts["embed_review_pairs"] = len(review)
        with open(out / "embed_review.jsonl", "w", encoding="utf-8") as f:
            for r in sorted(review, key=lambda r: (-r["name_cos"], r["type"])):
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"embed: {counts['embed']} merges  ({time.time() - t0:.0f}s)", flush=True)

    clusters = collections.defaultdict(list)
    for i in range(len(ents)):
        clusters[uf.find(i)].append(i)
    how = {j: (s, sc, ev) for i, j, s, sc, ev in edges}
    multi = {r: m for r, m in clusters.items() if len(m) > 1}
    with open(out / "clusters.jsonl", "w", encoding="utf-8") as f:
        for r, m in sorted(multi.items(), key=lambda x: -len(x[1])):
            f.write(json.dumps({
                "canonical_id": ents[r]["id"], "canonical": ents[r]["text"], "type": ents[r]["type"],
                "members": [{"id": ents[i]["id"], "text": ents[i]["text"], "mentions": ents[i]["mentions"],
                             "pass": how.get(i, ("canonical",))[0], "score": how.get(i, (0, None))[1],
                             "evidence": how.get(i, (0, 0, ""))[2]} for i in m]}, ensure_ascii=False) + "\n")
    with open(out / "dedup_map.tsv", "w", encoding="utf-8") as f:
        f.write("id\ttext\tcanonical_id\tcanonical\tpass\n")
        for i, e in enumerate(ents):
            r = uf.find(i)
            f.write(f"{e['id']}\t{e['text']}\t{ents[r]['id']}\t{ents[r]['text']}\t{how.get(i, ('canonical' if i == r else '',))[0]}\n")
    (out / "blocked_samples.json").write_text(json.dumps(samples, indent=1, ensure_ascii=False))
    by_pass_type = collections.Counter((s, ents[j]["type"]) for i, j, s, sc, ev in edges)
    summary = {
        "entity": a.entity, "source": "CDM 3.0.3 read-only + 2026-11-09 definition layers",
        "items": len(ents), "distinct_after": len(clusters), "merged_away": len(ents) - len(clusters),
        "merges_by_pass": counts, "clusters_with_duplicates": len(multi),
        "blocked_by_guard": dict(blocked.most_common()),
        "merges_by_pass_and_type": {f"{s}|{t}": n for (s, t), n in sorted(by_pass_type.items())},
        "thresholds": {"fuzzy_ratio_min": FUZZY_MIN, "sapbert_name_cos_min": NAME_COS_MIN,
                       "sapbert_name_cos_min_with_abbrev_or_synonym": NAME_COS_MIN_EVID,
                       "minilm_context_cos_min": CTX_COS_MIN, "topk": TOPK},
        "models": {"name": SAPBERT, "context": MINILM} if "embed" in stages else None,
        "note": "merge PROPOSALS; frozen CDM unchanged; new labelled layer needing lead approval (CHANGE_RECORD)",
        "seconds": round(time.time() - t0),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
