#!/usr/bin/env python3
"""Stage 56 phase 2: entity linking for the canonical entity registry.

CPU-only (intelsr_short). Deterministic-first cascade with a hard wall-clock
budget (entity_linking.budget_seconds, default 4.5h inside a 6h sbatch):

  T0  OMOP exact     persisted offline index over CONCEPT.csv (standard
                     concepts, valid only: invalid_reason empty) +
                     CONCEPT_SYNONYM.csv, domain-filtered. Index v2.
  T1  OMOP fuzzy     rapidfuzz.cdist token_sort_ratio (workers=-1, batched
                     per domain - one multithreaded C call, not per entity).
                     >=95 = top lexical band, but a high lexical score is
                     never sufficient evidence alone: every shortlisted
                     candidate still passes T2. Multiple distinct concepts
                     at the top lexical score -> ambiguous (kept, all
                     candidates recorded).
  T2  embed confirm  all-MiniLM-L6-v2 cosine over the T1 shortlists (>=85):
                     link iff top>=0.80 and margin over 2nd >=0.05; band
                     0.75..0.80 or low margin -> review_required (kept,
                     candidate recorded with full evidence).
  T3  APIs           D01 microorganisms (and microbe-suffixed labels): Entrez
                     taxonomy -> OLS ncbitaxon -> UMLS CUI -> BioPortal,
                     disk-cached, rate-limited and call-capped; reruns are
                     offline. API errors are LOOKUP_FAILED, never
                     NO_MATCH_FOUND.

Domain routing: D06->Spec Anatomic Site, D07->Condition, D12->Drug,
D10->Measurement/Observation. D01 never hits OMOP (no taxonomy in OMOP).
Everything else records 'ineligible_for_omop' and, if not microbe-like,
stays resolved=unresolved (recorded, never guessed).

Downgrade-only: an existing link is never removed; failures record reason
codes and candidate evidence. Soft deadline: entities processed
mention_count desc, so budget exhaustion lands on the least-cited tail,
which gets 'unresolved_time_budget_exhausted'.
"""
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import pipeline.common as C

STAGE = "stage56_entity_linking"
RUN_STAGE = "stage56_triples_canonicalize"
OMOP_DIR = Path(os.environ.get("HMCV2_OMOP_DIR", str(Path.home() / "omop_v5")))
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
INDEX_VERSION = 2        # v2: valid concepts only (invalid_reason filter)

OMOP_DOMAIN_BY_CORPUS = {          # corpus domain -> OMOP domain_ids
    "D06": ("Spec Anatomic Site",),
    "D07": ("Condition",),
    "D12": ("Drug",),
    "D10": ("Measurement", "Observation"),
}
API_PRIMARY = {"D01"}              # Entrez/UMLS/BioPortal tier

FUZZ_AUTO = 95.0                   # >= links without rerank
FUZZ_SHORTLIST = 85.0              # >= goes to embed rerank
FUZZ_TOPK = 50
EMBED_THRESHOLD = 0.80
EMBED_MARGIN = 0.05
EMBED_REVIEW = 0.75                # >= review_required (below auto-accept)
MIN_ENTITIES_FOR_BATCH = 1

# Mapping-relation vocabulary (spec §7). EXACT_MATCH = validated identifier
# or verified exact preferred-label equivalence; MAPPED_TO_STANDARD_CONCEPT =
# source label mapped onto an OMOP standard concept (original label kept in
# the entity record); AMBIGUOUS/CONFLICTING/... describe blocked candidates.
MAPPING_RELATIONS = {
    "T0_exact": "EXACT_MATCH",
    "T0_synonym": "EXACT_MATCH",          # synonym-of-standard, recorded
    "T0_multi_syn": "MAPPED_TO_STANDARD_CONCEPT",
    "T1_fuzzy": "MAPPED_TO_STANDARD_CONCEPT",   # never EXACT_MATCH
    "T2_rerank": "MAPPED_TO_STANDARD_CONCEPT",
    "ambiguous": "AMBIGUOUS",
    "conflicting": "CONFLICTING_MAPPINGS",
    "no_match": "NO_MATCH_FOUND",
    "lookup_fail": "LOOKUP_FAILED",
    "review_required": "UNVERIFIED",      # plausible, unreviewed
    "api_link": "EXACT_MATCH",            # exact-label API hit, labeled
}

ENTREZ_INTERVAL = 0.35             # NCBI asks <=3 rps without key
UMLS_INTERVAL = 0.12
BIOPORTAL_INTERVAL = 0.12
BIOPORTAL_MAX_CALLS = 2500
OLS_INTERVAL = 0.12
OLS_MAX_CALLS = 2500


def log(msg):
    print(f"[{STAGE}] {msg}", flush=True)


def canon_norm(s: str) -> str:
    if s is None:
        return ""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def word_norm(s: str) -> str:
    """Whitespace-normalized lowercase used for T1 fuzzy (token_sort needs
    real word boundaries; alnum-collapsed strings would destroy them)."""
    if s is None:
        return ""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ",
                                      (s or "").lower())).strip()


MICROBE_SUFFIXES = ("bacter", "bacill", "coccus", "myces", "phyte", "virus",
                    "viridae", "ella", "monas", "phyllum", "cetes", "biont",
                    "archaea", "fungus", "fungi", "yeast")


def looks_microbe(label: str, nlab: str) -> bool:
    tail = nlab[-10:]
    return any(s in nlab for s in MICROBE_SUFFIXES) or any(
        s in tail for s in MICROBE_SUFFIXES)


# --------------------------------------------------------------------------
# OMOP index
# --------------------------------------------------------------------------

def load_omop_index(omop_dir: Path = None) -> dict:
    """norm_label -> [(concept_id, display_name, omop_domain, vocab, is_std)].

    Only entries usable for linking are stored: standard concepts and
    synonyms of kept-domain concepts (marked with the core concept's std
    flag). Persisted to <omop_dir>/omop_index.json; rebuilt only when
    CONCEPT.csv is newer. Missing pack -> {} (recorded, APIs still work).
    """
    omop_dir = Path(omop_dir or OMOP_DIR)
    concept_csv = omop_dir / "CONCEPT.csv"
    synonym_csv = omop_dir / "CONCEPT_SYNONYM.csv"
    idx_path = omop_dir / "omop_index.json"
    if not concept_csv.exists():
        log(f"WARN: no OMOP pack under {omop_dir}; T0/T1/T2 skipped")
        return {}
    if idx_path.exists() and idx_path.stat().st_mtime >= concept_csv.stat().st_mtime:
        idx = json.loads(idx_path.read_text(encoding="utf-8"))
        if idx.get("__index_version__") != INDEX_VERSION:
            log(f"OMOP index v{idx.get('__index_version__')} != "
                f"v{INDEX_VERSION}; rebuilding")
        else:
            log(f"OMOP index v{INDEX_VERSION} loaded from disk: "
                f"{len(idx)-1} labels")
            return idx

    keep = {d for tup in OMOP_DOMAIN_BY_CORPUS.values() for d in tup}
    t0 = time.time()
    core = {}                       # concept_id -> (name, dom, vocab, std)
    n_invalid = 0
    with concept_csv.open(encoding="utf-8", errors="replace") as fh:
        header = fh.readline().rstrip("\n").split("\t")
        col = {n: i for i, n in enumerate(header)}
        for line in fh:
            p = line.rstrip("\n").split("\t")
            if len(p) < len(header) or p[col["domain_id"]] not in keep:
                continue
            if p[col["invalid_reason"]].strip():
                n_invalid += 1                       # deprecated/outdated
                continue
            core[p[col["concept_id"]]] = (
                p[col["concept_name"]], p[col["domain_id"]],
                p[col["vocabulary_id"]], p[col["standard_concept"]] == "S")
    log(f"CONCEPT: {len(core)} kept concepts "
        f"({n_invalid} invalid skipped, {round(time.time()-t0,1)}s)")

    index = defaultdict(list)
    for cid, (name, dom, vocab, std) in core.items():
        index[canon_norm(name)].append([cid, name, dom, vocab, std])
    if synonym_csv.exists():
        nsyn = 0
        with synonym_csv.open(encoding="utf-8", errors="replace") as fh:
            header = fh.readline().rstrip("\n").split("\t")
            col = {n: i for i, n in enumerate(header)}
            for line in fh:
                p = line.rstrip("\n").split("\t")
                if len(p) < len(header):
                    continue
                hit = core.get(p[col["concept_id"]])
                if hit is None:
                    continue
                syn = p[col["concept_synonym_name"]]
                if syn:
                    index[canon_norm(syn)].append(
                        [p[col["concept_id"]], syn, hit[1], hit[2], hit[3]])
                    nsyn += 1
        log(f"CONCEPT_SYNONYM: {nsyn} synonyms")
    # word-normalized lookup for T1 fuzzy (token_sort needs word boundaries;
    # alnum-collapsed keys would destroy them)
    word_index = defaultdict(list)
    for key, entries in index.items():
        for en in entries:
            word_index[word_norm(en[1])].append(en)
    idx = dict(index)
    idx["__index_version__"] = INDEX_VERSION
    idx["__word_index__"] = {k: [list(x) for x in v]
                             for k, v in word_index.items()}
    tmp = idx_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(idx), encoding="utf-8")
    os.replace(tmp, idx_path)
    log(f"OMOP index persisted: {len(idx)-1} labels "
        f"({round(time.time()-t0,1)}s)")
    return idx


# --------------------------------------------------------------------------
# HTTP + disk cache helpers
# --------------------------------------------------------------------------

class CapClient:
    """RateLimitedClient with a hard call cap + error capture (never raises
    to the caller; failures return (None, reason))."""
    def __init__(self, interval: float, cap: int = None):
        self.inner = C.RateLimitedClient(min_interval=interval)
        self.cap = cap
        self.calls = 0
        self.errors = 0
        self.exhausted = False
        self.offline_reason = None

    def get(self, url: str, params: dict, headers: dict = None, apikey_env: str = None):
        if apikey_env and not os.environ.get(apikey_env):
            return None, "no_api_key"
        if self.cap is not None and self.calls >= self.cap:
            self.exhausted = True
            return None, "cap_exhausted"
        self.calls += 1
        try:
            return self.inner.get_json(url, params, headers or {}), "ok"
        except Exception as e:                     # record, never crash
            self.errors += 1
            return None, f"api_error:{getattr(e, 'code', type(e).__name__)}"


TRANSIENT_REASONS = ("api_error:", "cap_exhausted", "no_api_key")


def _ck(cache, cachefile, key, fn):
    """Cache-through: disk cache hit avoids the network entirely.
    API failures are NOT cached - a failed lookup is never evidence of
    no-match; only genuine results (linked/ambiguous/no_match) persist."""
    if key in cache:
        return cache[key]
    out = fn()
    reason = str(out.get("reason", ""))
    if not reason.startswith(TRANSIENT_REASONS):
        cache[key] = out
        if len(cache) % 250 == 0:
            _flush(cache, cachefile)
    return out


def _flush(cache, cachefile):
    tmp = cachefile.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache), encoding="utf-8")
    os.replace(tmp, cachefile)


# --------------------------------------------------------------------------
# API tier lookups (T3)
# --------------------------------------------------------------------------

def entrez_taxid(label, client, cache, cachefile):
    key = f"entrez::{canon_norm(label)}"
    ts = C.now_utc()

    def call():
        d, st = client.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            {"db": "taxonomy", "retmode": "json", "term": label})
        if d is None:
            return {"status": "unresolved", "reason": st}
        ids = (d.get("esearchresult") or {}).get("idlist") or []
        if len(ids) == 1:
            return {"status": "linked", "ncbi_tax_id": str(ids[0]),
                    "source": "entrez_taxonomy_esearch",
                    "retrieved_at": ts}
        if ids:
            return {"status": "ambiguous", "reason": "multiple_taxids",
                    "ncbi_tax_id_candidates": [str(i) for i in ids[:5]],
                    "retrieved_at": ts}
        return {"status": "unresolved", "reason": "no_match",
                "retrieved_at": ts}

    return _ck(cache, cachefile, key, call)


OLS_API = "https://www.ebi.ac.uk/ols/api"


def ols_label(label, client, cache, cachefile):
    """OLS exact search restricted to ncbitaxon (keyless public API).
    Species-level labels only link species-level classes; strain-level
    hits (label contains ' strain '/' str. '/ATCC) are kept as evidence,
    not auto-linked."""
    key = f"ols::{canon_norm(label)}"
    ts = C.now_utc()

    def call():
        d, st = client.get(
            f"{OLS_API}/search",
            {"q": label, "exact": "true", "ontology": "ncbitaxon",
             "rows": "5"})
        if d is None:
            return {"status": "unresolved", "reason": st}
        docs = ((d.get("response") or {}).get("docs")) or []
        if not docs:
            return {"status": "unresolved", "reason": "no_match",
                    "retrieved_at": ts}
        # exact label match only; prefer docs whose label equals the query
        wnl = word_norm(label)
        exact = [x for x in docs if word_norm(x.get("label", "")) == wnl]
        if not exact:
            return {"status": "unresolved", "reason": "no_exact_label_match",
                    "candidates": [{"obo_id": x.get("obo_id"),
                                    "label": x.get("label")}
                                   for x in docs[:5]],
                    "retrieved_at": ts}
        top = exact[0]
        return {"status": "linked",
                "ols_ontology_id": top.get("ontology_name"),
                "ols_ontology_prefix": top.get("ontology_prefix"),
                "ols_term_id": top.get("obo_id") or top.get("short_form"),
                "ols_term_label": top.get("label"),
                "source": "ols_search_ncbitaxon",
                "retrieved_at": ts}

    return _ck(cache, cachefile, key, call)


def umls_cui(label, client, cache, cachefile):
    key = f"umls::{canon_norm(label)}"
    ts = C.now_utc()

    def call():
        d, st = client.get(
            "https://uts-ws.nlm.nih.gov/rest/search/current",
            {"string": label, "searchType": "exact",
             "apiKey": os.environ.get("UMLS_API_KEY", "")},
            apikey_env="UMLS_API_KEY")
        if d is None:
            return {"status": "unresolved", "reason": st}
        res = (d.get("result") or {}).get("results") or []
        if res:
            r0 = res[0]
            return {"status": "linked", "umls_cui": r0["ui"],
                    "match_name": r0.get("name"),
                    "root_source": r0.get("rootSource"),
                    "semantic_type": r0.get("semanticTypes") or [],
                    "source": "umls_uts_search",
                    "retrieved_at": ts}
        return {"status": "unresolved", "reason": "no_match",
                "retrieved_at": ts}

    return _ck(cache, cachefile, key, call)


def bioportal_id(label, client, cache, cachefile):
    key = f"bioportal::{canon_norm(label)}"
    ts = C.now_utc()

    def call():
        d, st = client.get(
            "https://data.bioontology.org/search",
            {"q": label, "exact": "1", "page": "1"},
            headers={"Authorization":
                     f"apikey token={os.environ.get('BIOPORTAL_API_KEY', '')}"},
            apikey_env="BIOPORTAL_API_KEY")
        if d is None:
            return {"status": "unresolved", "reason": st}
        res = d.get("collection") or []
        if res:
            # guard: a search hit whose preferred label does not match the
            # queried label is not an equivalence - keep as evidence only
            pl = word_norm(res[0].get("prefLabel", ""))
            if pl != word_norm(label):
                return {"status": "unresolved",
                        "reason": "no_exact_preflabel_match",
                        "candidates": [{"bioportal_id": r.get("@id"),
                                        "prefLabel": r.get("prefLabel")}
                                       for r in res[:5]],
                        "retrieved_at": ts}
            r0 = res[0]
            return {"status": "linked", "bioportal_id": r0.get("@id"),
                    "match_preflabel": r0.get("prefLabel"),
                    "source": "bioportal_search",
                    "retrieved_at": ts}
        return {"status": "unresolved", "reason": "no_match",
                "retrieved_at": ts}

    return _ck(cache, cachefile, key, call)


# --------------------------------------------------------------------------
# embedding helper
# --------------------------------------------------------------------------

class Embedder:
    def __init__(self, model_name=MODEL_NAME):
        from sentence_transformers import SentenceTransformer
        self.model_name = model_name
        self.m = SentenceTransformer(model_name)
        self._cache = {}

    def embed(self, labels):
        labels = list(labels)
        missing = [l for l in labels if l not in self._cache]
        if missing:
            v = self.m.encode(missing, convert_to_numpy=True,
                              normalize_embeddings=True,
                              show_progress_bar=False)
            for l, row in zip(missing, v):
                self._cache[l] = row
        if not labels:
            return np.zeros((0, 384), dtype=np.float32)
        return np.stack([self._cache[l] for l in labels])


class LazyEmbedder:
    """MiniLM is only needed when T2 rerank actually fires; don't pay
    the model load when every entity resolves at T0/T1."""

    def __init__(self, model_name=MODEL_NAME):
        self.model_name = model_name
        self._inner = None

    def embed(self, labels):
        if self._inner is None:
            self._inner = Embedder(self.model_name)
        return self._inner.embed(labels)


# --------------------------------------------------------------------------
# link application (downgrade-only) + candidate records
# --------------------------------------------------------------------------

def _cand(e, n, source_system, concept_id, concept_label, relation,
          disposition, method, tier, lexical=None, combined=None,
          extra=None, evidence=None, retrieved_at=None, run_id=None):
    """One candidate mapping record (spec 10A/10C). Scores are None when
    not computed; nothing is fabricated."""
    rec = {
        "mapping_id": f"HMCV2-MAP-{n:06d}",
        "entity_id": e["entity_id"],
        "entity_mention_id": None,
        "original_label": e.get("display_label"),
        "normalized_label": e.get("normalized_label"),
        "entity_type": (e.get("entity_types_observed") or [None])[0],
        "entity_domain": "/".join(e.get("domains_observed") or []),
        "source_system": source_system,
        "source_concept_id": concept_id,
        "source_concept_label": concept_label,
        "mapping_relation": relation,
        "candidate_rank": None,
        "lexical_score": lexical,
        "semantic_compatibility_score": None,
        "context_compatibility_score": None,
        "combined_score": combined,
        "score_method_version": "lex-fuzz-token_sort@1+minilm-cos@1",
        "definition": None,
        "semantic_type": None,
        "parent_concept_ids": None,
        "validity_status": "valid" if source_system == "OMOP" else None,
        "mapping_disposition": disposition,
        "mapping_method": method,
        "linking_tier": tier,
        "evidence": evidence,
        "retrieved_at": retrieved_at,
        "lookup_status": ("lookup_ok" if evidence is not None
                          else "not_applicable_offline"),
        "review_status": "pending_human_review" if disposition ==
                         "REVIEW_REQUIRED" else "not_reviewed",
        "run_id": run_id,
    }
    if extra:
        rec.update(extra)
    return rec


class _CandSink:
    """Collects candidate records with deterministic sequential ids."""

    def __init__(self, run_id):
        self.run_id = run_id
        self.items = []
        self._n = 0

    def add(self, e, source_system, concept_id, concept_label, relation,
            disposition, method, tier, lexical=None, combined=None,
            extra=None, evidence=None, retrieved_at=None, rank=None):
        self._n += 1
        rec = _cand(e, self._n, source_system, concept_id, concept_label,
                    relation, disposition, method, tier, lexical=lexical,
                    combined=combined, extra=extra, evidence=evidence,
                    retrieved_at=retrieved_at, run_id=self.run_id)
        if rank is not None:
            rec["candidate_rank"] = rank
        self.items.append(rec)
        return rec


def _apply_link(e, method, tier, confidence, omop=None, taxid=None,
                cui=None, bio=None, ols=None, evidence=None):
    if omop is not None:
        cid, name, dom, vocab, std = omop
        e["omop_concept_id"] = f"OMOP:{cid}"
        e["omop_concept_name"] = name
        e["omop_domain_id"] = dom
        e["omop_vocabulary_id"] = vocab
        e["omop_is_standard"] = bool(std)
    if taxid:
        e["ncbi_tax_id"] = str(taxid)
    if cui:
        e["umls_cui"] = cui
    if bio:
        e["bioportal_id"] = bio
    if ols:
        e["ols_term_id"] = ols.get("ols_term_id")
        e["ols_ontology_id"] = ols.get("ols_ontology_id")
    if evidence:
        e["link_evidence"] = evidence
    e["resolution_method"] = method
    e["linking_tier"] = tier
    e["link_confidence"] = round(float(confidence), 3)
    e["entity_resolution_status"] = "linked_vocabulary_v1"
    e["external_linking_status"] = "linked"
    e["mapping_disposition"] = "AUTO_ACCEPTED"
    return "linked"


def _mark_unresolved(e, reason, evidence=None):
    if e.get("external_linking_status") == "linked":
        return "already_linked"
    e["resolution_method"] = f"none_{reason}"
    e["entity_resolution_status"] = "unresolved_string_match_v1"
    e["external_linking_status"] = f"unresolved_{reason}"
    e["mapping_disposition"] = "UNRESOLVED"
    if evidence:
        e["link_evidence"] = evidence
    return f"unresolved_{reason}"


def _mark_review(e, method, tier, confidence, omop=None, evidence=None):
    """REVIEW_REQUIRED: plausible candidate, human judgment pending.
    Entity keeps unresolved status (nothing is asserted); candidate is
    recorded with full evidence."""
    e["resolution_method"] = f"review_required_{method}"
    e["entity_resolution_status"] = "unresolved_string_match_v1"
    e["external_linking_status"] = "review_required"
    e["mapping_disposition"] = "REVIEW_REQUIRED"
    e["linking_tier"] = tier
    e["link_confidence"] = round(float(confidence), 3)
    if omop is not None:
        e["review_candidate_omop_concept_id"] = f"OMOP:{omop[0]}"
        e["review_candidate_omop_name"] = omop[1]
    if evidence:
        e["link_evidence"] = evidence
    return "review_required"


# --------------------------------------------------------------------------
# main driver
# --------------------------------------------------------------------------

def run_linking(entities: list, budget_seconds: float = 16200.0,
                offline: bool = False, omop_dir: Path = None) -> tuple:
    t_start = time.time()
    soft_deadline = t_start + budget_seconds
    run_id = os.environ.get(
        "HMCV2_LINK_RUN_ID",
        f"HMCV2-LINK-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime(t_start))}")
    sink = _CandSink(run_id)
    cachefile = C.CORPUS_DIR / "data" / "entity_link_cache.json"
    cachefile.parent.mkdir(parents=True, exist_ok=True)
    cache = {}
    if cachefile.exists():
        try:
            cache = json.loads(cachefile.read_text(encoding="utf-8"))
        except Exception:
            cache = {}
    cache0 = len(cache)

    outcome = Counter()
    per_domain = defaultdict(Counter)
    budget_exhausted = []

    # deterministic processing order: most-cited first
    ents = sorted(entities,
                  key=lambda e: (-e.get("mention_count_total", 0),
                                 e["normalized_label"]))

    # ---- T0: exact OMOP match -------------------------------------------
    index = load_omop_index(omop_dir) if not offline else \
        load_omop_index(omop_dir)
    elapsed_idx = time.time() - t_start

    omop_pending = []          # T1 candidates: (entity, corpus_doms)
    for e in ents:
        doms = {d for d in (e.get("domains_observed") or [])
                if d in OMOP_DOMAIN_BY_CORPUS}
        e["_omop_doms"] = doms
        if not doms:
            continue                       # routed to API tier / left resolved
        if e.get("external_linking_status") == "linked":
            outcome["already_linked"] += 1
            continue
        if time.time() > soft_deadline:
            break
        entries = index.get(e["normalized_label"]) or []
        stds = [en for en in entries if en[4]]
        if len(stds) == 1:
            en = stds[0]
            _apply_link(e, "omop_exact_standard", "T0", 0.99,
                        omop=tuple(en))
            sink.add(e, "OMOP", f"OMOP:{en[0]}", en[1],
                     "EXACT_MATCH",
                     "AUTO_ACCEPTED", "omop_exact_standard", "T0",
                     combined=0.99, rank=1,
                     evidence=[{"concept_id": en[0], "name": en[1],
                               "vocab": en[3], "source_system": "OMOP"}],
                     retrieved_at=None, extra={"validity_status": "valid"})
            outcome["linked_T0_omop_exact"] += 1
            per_domain["/".join(sorted(doms))]["linked_T0_omop_exact"] += 1
        elif len(stds) > 1:
            cids = sorted({s[0] for s in stds})
            if len(cids) == 1:
                en = stds[0]
                _apply_link(e, "omop_exact_standard_multi_synonym", "T0",
                            0.98, omop=tuple(en))
                sink.add(e, "OMOP", f"OMOP:{en[0]}", en[1],
                         "MAPPED_TO_STANDARD_CONCEPT",
                         "AUTO_ACCEPTED",
                         "omop_exact_standard_multi_synonym", "T0",
                         combined=0.98, rank=1,
                         evidence=[{"concept_id": s[0], "name": s[1],
                                    "vocab": s[3], "std": True}
                                   for s in stds[:10]])
                outcome["linked_T0_omop_exact"] += 1
            else:
                _mark_unresolved(e, "ambiguous_multi_standard",
                                 evidence=[{"concept_id": s[0], "name": s[1],
                                            "vocab": s[3]}
                                           for s in stds[:10]])
                for rank, s in enumerate(stds[:10], 1):
                    sink.add(e, "OMOP", f"OMOP:{s[0]}", s[1], "AMBIGUOUS",
                             "UNRESOLVED", "ambiguous_multi_standard", "T0",
                             rank=rank,
                             evidence=[{"concept_id": s[0], "name": s[1],
                                        "vocab": s[3]}])
                outcome["unresolved_ambiguous_multi_standard"] += 1
        elif entries:
            _mark_unresolved(e, "no_standard_concept",
                             evidence=[{"concept_id": en[0], "name": en[1],
                                        "vocab": en[3], "std": bool(en[4])}
                                       for en in entries[:10]])
            outcome["unresolved_no_standard_concept"] += 1
        else:
            omop_pending.append((e, doms))          # no exact hit -> T1

    # ---- T1: batched fuzzy per corpus domain ------------------------------
    t1_by_cdom = defaultdict(list)          # cdom -> [(entity, doms)]
    for e, doms in omop_pending:
        if e.get("external_linking_status") == "linked":
            continue
        if time.time() > soft_deadline:
            break
        for d in sorted(doms):
            t1_by_cdom[d].append((e, doms))

    if index and t1_by_cdom:
        from rapidfuzz import fuzz, process
        embedder = LazyEmbedder()

        # pool: word-normalized key + entry per OMOP domain
        pool_by_cdom = {}
        word_index = index.get("__word_index__") or {}
        for cdom, odoms in OMOP_DOMAIN_BY_CORPUS.items():
            labels, entries = [], []
            seen = set()
            for od in odoms:
                for key, ents_ in word_index.items():
                    for en in ents_:
                        if en[2] != od:
                            continue
                        sig = (key, en[0])
                        if sig in seen:
                            continue
                        seen.add(sig)
                        labels.append(key)
                        entries.append(en)
            pool_by_cdom[cdom] = (labels, entries)
            log(f"T1 pool {cdom} ({'/'.join(odoms)}): {len(labels)} labels")

        for cdom, group in sorted(t1_by_cdom.items()):
            if time.time() > soft_deadline:
                for e, doms in group:
                    if e.get("external_linking_status") != "linked":
                        _mark_unresolved(e, "time_budget_exhausted")
                        budget_exhausted.append(e["entity_id"])
                        outcome["unresolved_time_budget_exhausted"] += 1
                continue
            labels, entries = pool_by_cdom.get(cdom, ([], []))
            if not labels:
                for e, doms in group:
                    _mark_unresolved(e, "no_omop_pool_for_domain")
                    outcome["unresolved_no_omop_pool_for_domain"] += 1
                continue
            queries = [word_norm(e["display_label"]) for e, _ in group]
            log(f"T1 cdist: {len(queries)} queries x {len(labels)} "
                f"labels ({cdom})")
            sim = process.cdist(queries, labels,
                                scorer=fuzz.token_sort_ratio,
                                score_cutoff=FUZZ_SHORTLIST,
                                dtype=np.uint8, workers=-1)
            # rows: score per query (0 = below cutoff)
            for qi, (e, doms) in enumerate(group):
                row = sim[qi]
                nz = np.nonzero(row)[0]
                if nz.size == 0:
                    other_doms = doms - {cdom}
                    # NOTE: fixed 2026-10-24 — this condition previously
                    # passed the scalar bool `e.get(...) not in (None,"linked")`
                    # to all(), which raises TypeError ('bool' object is not
                    # iterable) on the first shortlist miss. The guard below
                    # (and the marking it enables) is unchanged: only
                    # single-domain entities that are not already linked are
                    # concluded as no_omop_match; multi-domain entities may
                    # still match in a later corpus-domain pool.
                    if not other_doms or (
                            e.get("external_linking_status") not in
                            (None, "linked")):
                        if e.get("external_linking_status") not in \
                                ("linked",) and len(doms) == 1:
                            _mark_unresolved(e, "no_omop_match")
                            outcome["unresolved_no_omop_match"] += 1
                    continue
                top_idx = nz[np.argsort(-row[nz])][:FUZZ_TOPK]
                best = float(row[top_idx[0]])
                top_entries = [entries[i] for i in top_idx]
                # ---- T2: embed confirmation/rerank shortlist -----------
                # lexical >=95 no longer auto-links alone; every shortlisted
                # candidate passes the embedding check (a high lexical
                # score is never sufficient evidence by itself).
                if time.time() > soft_deadline:
                    _mark_unresolved(e, "time_budget_exhausted")
                    budget_exhausted.append(e["entity_id"])
                    outcome["unresolved_time_budget_exhausted"] += 1
                    continue
                cand_names = [en[1] for en in top_entries]
                qmat = embedder.embed([e["display_label"]])
                cmat = embedder.embed(cand_names)
                sims = (qmat @ cmat.T)[0]
                order = np.argsort(-sims)
                top = top_entries[order[0]]
                top_sim = float(sims[order[0]])
                margin = top_sim - (float(sims[order[1]])
                                    if len(order) > 1 else 0.0)
                evidence = [{"concept_id": top_entries[j][0],
                             "name": top_entries[j][1],
                             "fuzz": int(row[top_idx[j]]),
                             "cos": round(float(sims[j]), 3)}
                            for j in order[:10]]
                if best >= FUZZ_AUTO:
                    cids_at_best = sorted({en[0] for en in top_entries
                                           if float(row[top_idx[0]]) == best})
                    if len(cids_at_best) > 1:
                        _mark_unresolved(e, "fuzzy_ambiguous_top_score",
                                         evidence=[
                                             {"concept_id": en[0],
                                              "name": en[1],
                                              "score": best}
                                             for en in top_entries[:10]])
                        for rank, en in enumerate(top_entries[:10], 1):
                            sink.add(e, "OMOP", f"OMOP:{en[0]}", en[1],
                                     "AMBIGUOUS", "UNRESOLVED",
                                     "fuzzy_ambiguous_top_score", "T1/T2",
                                     lexical=best, rank=rank,
                                     evidence=evidence)
                        outcome["unresolved_fuzzy_ambiguous_top_score"] += 1
                        continue
                if top_sim >= EMBED_THRESHOLD and margin >= EMBED_MARGIN:
                    method = ("omop_fuzzy_token_sort" if best >= FUZZ_AUTO
                              else "omop_fuzzy_embed_rerank")
                    _apply_link(e, method, "T2" if best < FUZZ_AUTO else "T1",
                                top_sim, omop=tuple(top),
                                evidence=evidence)
                    sink.add(e, "OMOP", f"OMOP:{top[0]}", top[1],
                             "MAPPED_TO_STANDARD_CONCEPT",
                             "AUTO_ACCEPTED", method,
                             "T2" if best < FUZZ_AUTO else "T1",
                             lexical=best, combined=round(top_sim, 3),
                             rank=1, evidence=evidence)
                    outcome["linked_T2_embed_rerank"] += 1
                    per_domain[cdom]["linked_T2_embed_rerank"] += 1
                elif top_sim >= EMBED_REVIEW:
                    _mark_review(e, "omop_candidate", "T2", top_sim,
                                 omop=tuple(top), evidence=evidence)
                    sink.add(e, "OMOP", f"OMOP:{top[0]}", top[1],
                             "UNVERIFIED", "REVIEW_REQUIRED",
                             "omop_candidate_review", "T2",
                             lexical=best, combined=round(top_sim, 3),
                             rank=1, evidence=evidence)
                    outcome["review_required_embed_band"] += 1
                else:
                    _mark_unresolved(e, "below_threshold_or_low_margin",
                                     evidence=evidence)
                    for rank, j in enumerate(order[:5], 1):
                        sink.add(e, "OMOP",
                                 f"OMOP:{top_entries[j][0]}",
                                 top_entries[j][1], "NO_MATCH_FOUND",
                                 "UNRESOLVED", "below_threshold_or_low_margin",
                                 "T2", lexical=best,
                                 combined=round(float(sims[j]), 3),
                                 rank=rank, evidence=evidence)
                    outcome["unresolved_below_threshold_or_low_margin"] += 1

    # ---- T3: APIs (D01 + microbe-like stragglers) -------------------------
    client_e = CapClient(ENTREZ_INTERVAL)
    client_o = CapClient(OLS_INTERVAL, cap=OLS_MAX_CALLS)
    client_u = CapClient(UMLS_INTERVAL)
    client_b = CapClient(BIOPORTAL_INTERVAL, cap=BIOPORTAL_MAX_CALLS)
    t3_start = time.time()

    for e in ents:
        if e.get("external_linking_status") in ("linked", "review_required"):
            continue
        if time.time() > soft_deadline:
            _mark_unresolved(e, "time_budget_exhausted")
            budget_exhausted.append(e["entity_id"])
            outcome["unresolved_time_budget_exhausted"] += 1
            continue
        doms = set(e.get("domains_observed") or [])
        is_api_eligible = bool(doms & API_PRIMARY) or \
            looks_microbe(e["display_label"], e["normalized_label"])
        if not is_api_eligible:
            if e.get("external_linking_status") in (None, "pending_stage57"):
                _mark_unresolved(e, "ineligible_no_linker_for_domain")
            outcome["left_ineligible_for_api_tier"] += 1
            continue
        if offline:
            _mark_unresolved(e, "offline_mode_api_skipped")
            outcome["unresolved_offline_mode_api_skipped"] += 1
            continue
        label = e["display_label"]
        dom_key = "/".join(sorted(doms)) or "D??"
        ent = entrez_taxid(label, client_e, cache, cachefile)
        if ent.get("status") == "linked":
            _apply_link(e, "entrez_taxonomy", "T3", 0.95,
                        taxid=ent["ncbi_tax_id"], evidence=[ent])
            sink.add(e, "NCBI_TAXONOMY", ent["ncbi_tax_id"], label,
                     "EXACT_MATCH", "AUTO_ACCEPTED", "entrez_taxonomy",
                     "T3", combined=0.95, rank=1, evidence=[ent],
                     retrieved_at=ent.get("retrieved_at"),
                     extra={"source_system": "Entrez",
                            "source_ontology_id": "ncbitaxon"})
            outcome["linked_T3_entrez"] += 1
            per_domain[dom_key]["linked_T3_entrez"] += 1
            continue
        if ent.get("status") == "ambiguous":
            _mark_unresolved(e, "entrez_multiple_taxids", evidence=[ent])
            outcome["unresolved_entrez_multiple_taxids"] += 1
            continue
        o = ols_label(label, client_o, cache, cachefile)
        if o.get("status") == "linked":
            _apply_link(e, "ols_ncbitaxon", "T3", 0.95, ols=o,
                        evidence=[o])
            sink.add(e, "OLS", o["ols_term_id"], o["ols_term_label"],
                    "EXACT_MATCH", "AUTO_ACCEPTED", "ols_ncbitaxon", "T3",
                    combined=0.95, rank=1, evidence=[o],
                    retrieved_at=o.get("retrieved_at"),
                    extra={"source_ontology_id": o["ols_ontology_prefix"]})
            outcome["linked_T3_ols"] += 1
            per_domain[dom_key]["linked_T3_ols"] += 1
            continue
        if str(o.get("reason", "")).startswith(TRANSIENT_REASONS):
            # a failed lookup is NOT no-match: stays LOOKUP_FAILED
            _mark_unresolved(e, f"lookup_failed_ols:{o['reason']}",
                             evidence=[ent, o])
            sink.add(e, "OLS", None, None, "LOOKUP_FAILED", "LOOKUP_FAILED",
                     "ols_ncbitaxon", "T3", evidence=o)
            outcome["unresolved_lookup_failed_ols"] += 1
            continue
        u = umls_cui(label, client_u, cache, cachefile)
        if u.get("status") == "linked":
            _apply_link(e, "umls_uts_search", "T3", 0.90,
                        cui=u["umls_cui"], evidence=[u])
            sink.add(e, "UMLS", u["umls_cui"], u.get("match_name"),
                     "EXACT_MATCH", "AUTO_ACCEPTED", "umls_uts_search",
                     "T3", combined=0.90, rank=1, evidence=u,
                     retrieved_at=u.get("retrieved_at"))
            outcome["linked_T3_umls"] += 1
            per_domain[dom_key]["linked_T3_umls"] += 1
            continue
        if str(u.get("reason", "")).startswith(TRANSIENT_REASONS):
            _mark_unresolved(e, f"lookup_failed_umls:{u['reason']}",
                             evidence=[ent, o, u])
            sink.add(e, "UMLS", None, None, "LOOKUP_FAILED", "LOOKUP_FAILED",
                     "umls_uts_search", "T3", evidence=u)
            outcome["unresolved_lookup_failed_umls"] += 1
            continue
        b = bioportal_id(label, client_b, cache, cachefile)
        if b.get("status") == "linked":
            _apply_link(e, "bioportal_search", "T3", 0.85,
                        bio=b["bioportal_id"], evidence=[b])
            sink.add(e, "BIOPORTAL", b["bioportal_id"],
                     b.get("match_preflabel"), "EXACT_MATCH",
                     "AUTO_ACCEPTED", "bioportal_search", "T3",
                     combined=0.85, rank=1, evidence=b,
                     retrieved_at=b.get("retrieved_at"))
            outcome["linked_T3_bioportal"] += 1
            per_domain[dom_key]["linked_T3_bioportal"] += 1
            continue
        _mark_unresolved(e, "api_no_match",
                         evidence=[ent, o, u, b])
        outcome["unresolved_api_no_match"] += 1

    _flush(cache, cachefile)

    # candidate mapping records (one per plausible candidate, incl. every
    # ambiguous/blocked hit) ship as their own artifact
    if sink.items:
        C.write_jsonl(C.CORPUS_DIR / "data" /
                      "candidate_entity_mappings.jsonl", sink.items)

    # disposition tallies across the emitted candidate-mapping records
    # (one entity may contribute more than one record: every plausible
    # candidate is kept, never silently dropped)
    disp = Counter(r["mapping_disposition"] for r in sink.items)
    rel_inv = Counter(r["mapping_relation"] for r in sink.items)

    report = {
        "stage": RUN_STAGE,
        "model": MODEL_NAME,
        "offline_mode": offline,
        "budget_seconds": budget_seconds,
        "wall_seconds": round(time.time() - t_start, 1),
        "omop_index_seconds": round(elapsed_idx, 1),
        "entities_total": len(ents),
        "candidate_mapping_records": len(sink.items),
        "mapping_dispositions": dict(disp),
        "mapping_relations": dict(rel_inv),
        "run_id": run_id,
        "outcomes": dict(outcome),
        "per_domain_outcomes": {k: dict(v) for k, v in per_domain.items()},
        "budget_exhausted_count": len(budget_exhausted),
        "budget_exhausted_entity_ids_first20": budget_exhausted[:20],
        "api_calls": {"entrez": client_e.calls, "ols": client_o.calls,
                      "umls": client_u.calls,
                      "bioportal": client_b.calls},
        "api_errors": {"entrez": client_e.errors, "ols": client_o.errors,
                       "umls": client_u.errors,
                       "bioportal": client_b.errors},
        "api_caps": {"ols": OLS_MAX_CALLS,
                     "bioportal": BIOPORTAL_MAX_CALLS},
        "api_cache_size_before": cache0,
        "api_cache_size_after": len(cache),
        "thresholds": {"fuzz_auto": FUZZ_AUTO,
                        "fuzz_shortlist": FUZZ_SHORTLIST,
                        "fuzz_topk": FUZZ_TOPK,
                        "embed_threshold": EMBED_THRESHOLD,
                        "embed_margin": EMBED_MARGIN,
                        "embed_review": EMBED_REVIEW},
        "omop_dir": str(OMOP_DIR),
    }
    # strip internal routing key from records
    for e in ents:
        e.pop("_omop_doms", None)
    return ents, report, sink.items
