#!/usr/bin/env python3
"""Section-level agreement analysis: LLM NER vs the CPU NER ensemble.

WHAT THIS IS
------------
There is **no gold standard** for entity extraction over the 453-paper corpus.
Everything in the output is therefore **inter-model agreement / consensus**, not
accuracy. No precision, recall or F1 is reported, and none can be derived from
this script. Treat the numbers as "how much do the systems overlap and what does
each contribute", nothing more.

WHAT IT COMPARES
----------------
Two section-level NER outputs that share the same (paper, section_id) unit
scheme and the same section-relative character offsets, because both are
produced by cdm_pipeline.ner.runner_sections.load_sections:

  --cpu_csv  releases/zenodo_v1/ner_453_sections/all_ner_sections_combined.csv
             7 CPU models, native labels (one of them emits only generic
             ENTITY), whole-document -> per-section units.
  --llm_csv  an LLM section CSV (qwen_sections_ner.csv from the Ollama Cell-7c
             run, or vllm_sections_ner.csv from qwen_sections_vllm.py).

Label spaces differ by design, so every metric is computed twice:
  * type-agnostic  -> normalized surface-form sets  (comparable across systems)
  * type-aware     -> (CDM type, normalized form) sets, restricted to the label
                      vocabulary both sides actually emit.

UNITS
-----
The default universe is the **intersection** of the two systems' units, so that
neither side is penalised for a section the other never processed. Coverage
gaps are reported separately in the scope section rather than silently averaged
into the agreement numbers.

Usage
-----
    PYTHONPATH=src python src/scripts/vllm_termpop/compare_llm_vs_ner.py \
        --cpu_csv releases/zenodo_v1/ner_453_sections/all_ner_sections_combined.csv \
        --llm_csv releases/zenodo_v1/qwen_sections_ner/qwen_sections_ner.csv \
        --llm_name qwen-ollama-cell7c \
        --out_dir outputs/results/llm_vs_ner_comparison/ollama

Outputs (in --out_dir)
----------------------
    comparison.json          full machine-readable result
    summary.txt              human-readable report
    scope.csv                per-system scope + unit-set reconciliation
    pairwise.csv             LLM vs each CPU model (global + per-unit + typed)
    per_model.csv            per-model scope, types, dates, unique terms
    type_agreement.csv       per-CDM-type agreement (shared vocabulary only)
    unique_terms.csv         terms only one side found, ranked by #units
    unique_terms_excl_generic.csv
                             same, but CPU side excludes generic-label models
    per_unit_overlap.csv     per-unit detail on the common universe
    units_missing_<side>.csv units a system never covered
"""
import argparse
import csv
import io
import json
import re
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── normalization ────────────────────────────────────────────────────────────
# Aggressive-but-documented: NFKC, casefold, whitespace collapse, strip
# surrounding punctuation/digits from citation glue ("dysbiosis[49" -> the
# trailing digit moves inside, so we also drop a trailing bracket-number group).
_CITE = re.compile(r"\s*\[\d+(?:\s*[,\-–]\s*\d+)*\]?\s*$")
_WS = re.compile(r"\s+")
# Edge filler to strip: never brackets/quotes here — those are handled by the
# balance-aware pass below so "(BMI)" does not degrade into "(bmi".
_EDGE = " \t\r\n.,;:!?*_—–…-"
_BRACKETS = {"(": ")", "[": "]", "{": "}", "<": ">"}
_CLOSERS = set(_BRACKETS.values())


def _strip_unbalanced_brackets(t):
    """Strip only brackets that do NOT wrap the term.

    "(bmi)" -> kept; "(bmi" -> leading "(" stripped; "bmi)" -> trailing ")"
    stripped. Preserves balanced wrapping like "bmi (kg/m2)".
    """
    changed = True
    while changed and t:
        changed = False
        if t[0] in _BRACKETS and t.count(t[0]) > t.count(_BRACKETS[t[0]]):
            t = t[1:].strip(_EDGE + " ")
            changed = True
        if t and t[-1] in _CLOSERS and t.count(t[-1]) > sum(
                t.count(o) for o, c in _BRACKETS.items() if c == t[-1]):
            t = t[:-1].strip(_EDGE + " ")
            changed = True
        # a wrapping pair whose interior is empty adds nothing
        if len(t) >= 2 and t[0] in _BRACKETS and t[-1] == _BRACKETS[t[0]] and not t[1:-1].strip():
            t = ""
            changed = True
    return t


def norm_term(t):
    t = unicodedata.normalize("NFKC", t or "")
    t = t.casefold().strip()
    t = _WS.sub(" ", t)
    t = _CITE.sub("", t)          # drop trailing "[49" / "[49]" / "[49, 50"
    t = t.strip(_EDGE)
    t = _strip_unbalanced_brackets(t)
    t = t.strip(_EDGE)
    t = _WS.sub(" ", t)
    return t


CPU_SECTION_MARKERS = ("abstract", "introduction", "background", "method",
                       "result", "discussion", "conclusion")


class Layer:
    """Per-unit entity store for one system (one model, or one ensemble)."""

    def __init__(self, name):
        self.name = name
        self.terms = defaultdict(set)       # unit -> {norm}
        self.typed = defaultdict(set)       # unit -> {(type, norm)}
        self.spans = defaultdict(set)       # unit -> {(norm, start)}
        self.by_type = Counter()            # type -> rows
        self.by_unit_type = defaultdict(set)  # unit -> {type}
        self.rows = 0
        self.bad_type = 0

    def add(self, unit, term, typ, start):
        t = (term or "").strip()
        if not t:
            return
        try:
            s = int(start)
        except (TypeError, ValueError):
            s = -1
        n = norm_term(t)
        if not n:
            return
        self.terms[unit].add(n)
        self.typed[unit].add((typ, n))
        self.spans[unit].add((n, s))
        self.by_type[typ] += 1
        self.by_unit_type[unit].add(typ)
        self.rows += 1

    # ── derived ──
    @property
    def units(self):
        return set(self.terms)

    def global_terms(self):
        g = set()
        for v in self.terms.values():
            g |= v
        return g

    def global_typed(self):
        g = set()
        for v in self.typed.values():
            g |= v
        return g

    def types(self):
        return set(self.by_type)


GENERIC_TYPE_SETS = frozenset({frozenset({"ENTITY"})})


def is_generic_model(layer):
    """True when a model's whole label vocabulary is unusable for CDM typing.

    en_core_sci_lg is the known case: it tags every span ``ENTITY``, so it adds
    bulk surface forms but no type information. Such models inflate the raw
    ensemble's term count without adding any typed signal.
    """
    t = layer.types()
    return bool(t) and frozenset(t) in GENERIC_TYPE_SETS


class _UnionMap:
    """dict.get-alike that unions the same key across several Layers, lazily.

    The full ensemble layers already hold ~1.7M set entries each, so materialising
    a second copy (the generic-excluded ensemble) would roughly double resident
    memory. Metrics only touch a handful of units at a time, so unioning on
    demand is cheap and keeps memory flat.
    """

    __slots__ = ("_layers", "_attr")

    def __init__(self, layers, attr):
        self._layers = layers
        self._attr = attr

    def get(self, u, default=None):
        s = set()
        for L in self._layers:
            v = getattr(L, self._attr).get(u)
            if v:
                s |= v
        return s if s else default

    def items(self):
        for L in self._layers:
            for kv in getattr(L, self._attr).items():
                yield kv


class UnionLayer:
    """Read-only union of several Layers; same interface as Layer, no copying."""

    def __init__(self, name, layers):
        self.name = name
        self._layers = list(layers)
        self.terms = _UnionMap(self._layers, "terms")
        self.typed = _UnionMap(self._layers, "typed")
        self.spans = _UnionMap(self._layers, "spans")

    @property
    def units(self):
        u = set()
        for L in self._layers:
            u |= set(L.terms)
        return u

    @property
    def rows(self):
        return sum(L.rows for L in self._layers)

    @property
    def by_type(self):
        c = Counter()
        for L in self._layers:
            c.update(L.by_type)
        return c

    @property
    def by_unit_type(self):
        d = defaultdict(set)
        for L in self._layers:
            for u, s in L.by_unit_type.items():
                d[u] |= s
        return d

    def global_terms(self):
        g = set()
        for L in self._layers:
            g |= L.global_terms()
        return g

    def global_typed(self):
        g = set()
        for L in self._layers:
            g |= L.global_typed()
        return g

    def types(self):
        t = set()
        for L in self._layers:
            t |= L.types()
        return t


def read_csv_rows(path):
    """Yield dict rows from a possibly-large CSV without holding a second copy."""
    txt = Path(path).read_text(encoding="utf-8", errors="replace").replace("\x00", "")
    with io.StringIO(txt) as fh:
        rdr = csv.DictReader(fh)
        fields = rdr.fieldnames or []
        for row in rdr:
            yield row, fields


def load_systems(cpu_csv, llm_csv, llm_name):
    """Build Layer per CPU model plus one ensemble layer and the LLM layer."""
    per_model = {}
    ensemble = Layer("cpu-ensemble")
    fields_seen = set()
    t0 = time.time()
    n = 0
    for row, fields in read_csv_rows(cpu_csv):
        fields_seen |= set(fields)
        unit = (row.get("paper"), row.get("section_id"))
        m = row.get("model") or "?"
        lay = per_model.get(m)
        if lay is None:
            lay = per_model[m] = Layer(m)
        typ = row.get("labels") or ""
        term = row.get("term") or ""
        start = row.get("char_start")
        lay.add(unit, term, typ, start)
        ensemble.add(unit, term, typ, start)
        n += 1
        if n % 500000 == 0:
            print("  ... %d cpu rows (%.0fs)" % (n, time.time() - t0), flush=True)
    print("  loaded %d CPU rows across %d models (%.0fs)"
          % (n, len(per_model), time.time() - t0), flush=True)

    llm = Layer(llm_name)
    n = 0
    for row, fields in read_csv_rows(llm_csv):
        fields_seen |= set(fields)
        unit = (row.get("paper"), row.get("section_id"))
        llm.add(unit, row.get("term") or "", row.get("labels") or "", row.get("char_start"))
        n += 1
    print("  loaded %d LLM rows (%s)" % (n, llm_name), flush=True)
    return per_model, ensemble, llm, sorted(fields_seen)


# ── metrics ──────────────────────────────────────────────────────────────────
def jaccard(a, b):
    if not a and not b:
        return None
    u = len(a | b)
    return (len(a & b) / u) if u else None


def pooled_jaccard(la, lb, units):
    """Micro Jaccard: pooled intersections over pooled unions, within units."""
    inter = union = 0
    for u in units:
        A = la.terms.get(u) or set()
        B = lb.terms.get(u) or set()
        inter += len(A & B)
        union += len(A | B)
    return (inter / union) if union else None, inter, union


def mean_unit_jaccard(la, lb, units):
    vals = []
    for u in units:
        j = jaccard(la.terms.get(u) or set(), lb.terms.get(u) or set())
        if j is not None:
            vals.append(j)
    return (sum(vals) / len(vals)) if vals else None, len(vals)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cpu_csv", required=True)
    ap.add_argument("--llm_csv", required=True)
    ap.add_argument("--llm_name", default="llm")
    ap.add_argument("--out_dir", required=True)
    ap.add_argument("--top_unique", type=int, default=300)
    args = ap.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    print("[%s] loading" % time.strftime("%H:%M:%S"))
    per_model, ensemble, llm, _ = load_systems(args.cpu_csv, args.llm_csv, args.llm_name)

    # Secondary CPU ensemble with generic-label-only models removed. A model
    # whose entire label vocabulary is {"ENTITY"} (en_core_sci_lg) contributes
    # bulk surface forms but no type information, so including it inflates the
    # CPU term count and depresses measured agreement for reasons unrelated to
    # extraction quality. Both ensembles are reported; neither replaces the other.
    generic_models = sorted(m for m, L in per_model.items() if is_generic_model(L))
    typed_models = [L for m, L in sorted(per_model.items())
                    if m not in set(generic_models)]
    ens_typed = (UnionLayer("cpu-ensemble-excl-generic", typed_models)
                 if generic_models and typed_models else ensemble)
    print("[%s] generic-label-only models excluded from secondary ensemble: %s"
          % (time.strftime("%H:%M:%S"), ", ".join(generic_models) or "(none)"))

    cpu_units = ensemble.units
    llm_units = llm.units
    common = sorted(cpu_units & llm_units)
    print("[%s] cpu units=%d llm units=%d common=%d"
          % (time.strftime("%H:%M:%S"), len(cpu_units), len(llm_units), len(common)))

    # ── scope ────────────────────────────────────────────────────────────────
    systems = [ensemble, ens_typed, llm] + sorted(per_model.values(), key=lambda L: L.name)
    scope_rows = []
    for L in systems:
        scope_rows.append({
            "system": L.name,
            "papers": len({u[0] for u in L.units}),
            "units": len(L.units),
            "rows": L.rows,
            "distinct_terms": len(L.global_terms()),
            "distinct_typed": len(L.global_typed()),
            "n_types": len(L.types()),
            "types": ";".join(sorted(L.types())),
            "units_on_common": len(L.units & set(common)),
        })
    scope_rows.append({
        "system": "__common_universe__",
        "papers": len({u[0] for u in common}),
        "units": len(common),
        "rows": "", "distinct_terms": "", "distinct_typed": "",
        "n_types": "", "types": "",
        "units_on_common": len(common),
    })
    _write_csv(out / "scope.csv", scope_rows)

    # coverage gaps, explicit (not silently averaged away)
    cpu_only = sorted(cpu_units - llm_units)
    llm_only = sorted(llm_units - cpu_units)
    path_of = {}
    for u, v in ensemble.by_unit_type.items():
        path_of.setdefault(u, "")
    with open(out / "units_missing_from_llm.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["paper", "section_id", "cpu_models_present", "cpu_distinct_terms"])
        for u in cpu_only:
            w.writerow([u[0], u[1],
                        ";".join(sorted(m for m, L in per_model.items() if u in L.terms)),
                        len(ensemble.terms.get(u) or [])])
    with open(out / "units_missing_from_cpu.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["paper", "section_id", "llm_distinct_terms"])
        for u in llm_only:
            w.writerow([u[0], u[1], len(llm.terms.get(u) or [])])

    # ── per-model scope ──────────────────────────────────────────────────────
    perf = []
    for m, L in sorted(per_model.items()):
        perf.append({"model": m, "papers": len({u[0] for u in L.units}),
                     "units": len(L.units), "rows": L.rows,
                     "distinct_terms": len(L.global_terms()),
                     "types": ";".join(sorted(L.types())),
                     "units_shared_with_llm": len(L.units & llm_units)})
    _write_csv(out / "per_model.csv", perf)

    # ── pairwise LLM vs each CPU model ───────────────────────────────────────
    llm_g, ens_g = llm.global_terms(), ensemble.global_terms()
    pairwise = []
    for m, L in sorted(per_model.items(), key=lambda kv: kv[0]):
        g = L.global_terms()
        micro, inter, union = pooled_jaccard(llm, L, common)
        macro, ntmp = mean_unit_jaccard(llm, L, common)
        shared_types = llm.types() & L.types()
        typed_inter = 0
        for u in common:
            A = {t for t in llm.typed.get(u) or set() if t[0] in shared_types}
            B = {t for t in L.typed.get(u) or set() if t[0] in shared_types}
            typed_inter += len(A & B)
        typed_union = 0
        for u in common:
            A = {t for t in llm.typed.get(u) or set() if t[0] in shared_types}
            B = {t for t in L.typed.get(u) or set() if t[0] in shared_types}
            typed_union += len(A | B)
        pairwise.append({
            "model": m,
            "common_units": len(common),
            "jaccard_global": _r(jaccard(llm_g, g)),
            "jaccard_pooled_within_unit": _r(micro),
            "jaccard_mean_per_unit": _r(macro),
            "llm_only_terms": len(llm_g - g),
            "model_only_terms": len(g - llm_g),
            "shared_terms": len(llm_g & g),
            "shared_types": ";".join(sorted(shared_types)),
            "jaccard_typed_pooled": _r(typed_inter / typed_union) if typed_union else "",
            "pooled_inter": inter, "pooled_union": union, "units_scored": ntmp,
        })
    # ensemble row
    micro, inter, union = pooled_jaccard(llm, ensemble, common)
    macro, ntmp = mean_unit_jaccard(llm, ensemble, common)
    shared_types = llm.types() & ensemble.types()
    ti = tu = 0
    for u in common:
        A = {t for t in llm.typed.get(u) or set() if t[0] in shared_types}
        B = {t for t in ensemble.typed.get(u) or set() if t[0] in shared_types}
        ti += len(A & B)
        tu += len(A | B)
    pairwise.append({
        "model": "cpu-ensemble (union of all CPU models)",
        "common_units": len(common),
        "jaccard_global": _r(jaccard(llm_g, ens_g)),
        "jaccard_pooled_within_unit": _r(micro),
        "jaccard_mean_per_unit": _r(macro),
        "llm_only_terms": len(llm_g - ens_g),
        "model_only_terms": len(ens_g - llm_g),
        "shared_terms": len(llm_g & ens_g),
        "shared_types": ";".join(sorted(shared_types)),
        "jaccard_typed_pooled": _r(ti / tu) if tu else "",
        "pooled_inter": inter, "pooled_union": union, "units_scored": ntmp,
    })

    # secondary ensemble row: generic-label-only models dropped
    ens2_g = ens_typed.global_terms()
    ens2_types = ens_typed.types()
    micro2, inter2, union2 = pooled_jaccard(llm, ens_typed, common)
    macro2, ntmp2 = mean_unit_jaccard(llm, ens_typed, common)
    shared2 = llm.types() & ens2_types
    ti2 = tu2 = 0
    for u in common:
        A = {t for t in llm.typed.get(u) or set() if t[0] in shared2}
        B = {t for t in ens_typed.typed.get(u) or set() if t[0] in shared2}
        ti2 += len(A & B)
        tu2 += len(A | B)
    pairwise.append({
        "model": "cpu-ensemble-excl-generic (%d models%s)"
                 % (len(typed_models),
                    "" if not generic_models else ", dropped " + "+".join(generic_models)),
        "common_units": len(common),
        "jaccard_global": _r(jaccard(llm_g, ens2_g)),
        "jaccard_pooled_within_unit": _r(micro2),
        "jaccard_mean_per_unit": _r(macro2),
        "llm_only_terms": len(llm_g - ens2_g),
        "model_only_terms": len(ens2_g - llm_g),
        "shared_terms": len(llm_g & ens2_g),
        "shared_types": ";".join(sorted(shared2)),
        "jaccard_typed_pooled": _r(ti2 / tu2) if tu2 else "",
        "pooled_inter": inter2, "pooled_union": union2, "units_scored": ntmp2,
    })
    _write_csv(out / "pairwise.csv", pairwise)

    # ── per-type agreement (shared vocabulary only) ──────────────────────────
    type_rows = []
    for typ in sorted(llm.types() | ensemble.types()):
        la = set()
        ea = set()
        for u in common:
            la |= {n for t, n in llm.typed.get(u) or set() if t == typ}
            ea |= {n for t, n in ensemble.typed.get(u) or set() if t == typ}
        type_rows.append({
            "type": typ,
            "llm_rows": llm.by_type.get(typ, 0),
            "cpu_rows": ensemble.by_type.get(typ, 0),
            "llm_distinct_terms": len(la),
            "cpu_distinct_terms": len(ea),
            "shared_terms": len(la & ea),
            "jaccard": _r(jaccard(la, ea)),
            "only_llm": len(la - ea),
            "only_cpu": len(ea - la),
            "both_emit_type": "yes" if (typ in llm.types() and typ in ensemble.types()) else "no",
        })
    _write_csv(out / "type_agreement.csv", type_rows)

    # ── unique contribution (term -> #units, on the common universe) ─────────
    def df(layer, terms_ok=None):
        d = Counter()
        for u in common:
            for n in layer.terms.get(u) or set():
                if terms_ok is None or n in terms_ok:
                    d[n] += 1
        return d

    llm_df = df(llm)
    ens_df = df(ensemble)
    only_llm = Counter({n: c for n, c in llm_df.items() if n not in ens_g})
    only_ens = Counter({n: c for n, c in ens_df.items() if n not in llm_g})
    with open(out / "unique_terms.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["side", "term", "n_units", "example_paper", "n_models_cpu"])
        ex = {}
        for u in common:
            for n in llm.terms.get(u) or set():
                ex.setdefault(("llm", n), u)
            for n in ensemble.terms.get(u) or set():
                ex.setdefault(("cpu", n), u)
        cpu_term_models = Counter()
        for m, L in per_model.items():
            for n in L.global_terms():
                cpu_term_models[n] += 1
        for n, c in only_llm.most_common(args.top_unique):
            u = ex.get(("llm", n))
            w.writerow(["only_llm", n, c, "%s/%s" % u if u else "", 0])
        for n, c in only_ens.most_common(args.top_unique):
            u = ex.get(("cpu", n))
            w.writerow(["only_cpu_ensemble", n, c, "%s/%s" % u if u else "",
                        cpu_term_models.get(n, 0)])

    # same ranking against the generic-excluded ensemble, so the CPU-only list
    # is not just en_core_sci_lg's bulk surface forms
    only_ens2 = Counter({n: c for n, c in ens_df.items() if n not in ens2_g})
    with open(out / "unique_terms_excl_generic.csv", "w", newline="",
              encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["side", "term", "n_units", "example_paper",
                    "n_models_cpu_excl_generic"])
        cpu2_term_models = Counter()
        for L in typed_models:
            for n in L.global_terms():
                cpu2_term_models[n] += 1
        for n, c in only_llm.most_common(args.top_unique):
            u = ex.get(("llm", n))
            w.writerow(["only_llm", n, c, "%s/%s" % u if u else "", 0])
        for n, c in only_ens2.most_common(args.top_unique):
            u = ex.get(("cpu", n))
            w.writerow(["only_cpu_ensemble_excl_generic", n, c,
                        "%s/%s" % u if u else "", cpu2_term_models.get(n, 0)])
    print("[%s] excl-generic: %d CPU-only terms (vs %d with generic models)"
          % (time.strftime("%H:%M:%S"), len(only_ens2), len(only_ens)))

    # ── per-unit overlap on the common universe ──────────────────────────────
    with open(out / "per_unit_overlap.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["paper", "section_id", "llm_terms", "cpu_terms", "shared",
                    "jaccard", "llm_only", "cpu_only",
                    "llm_spans_matching_cpu", "llm_spans_total",
                    "cpu_models_with_hits"])
        for u in common:
            A = llm.terms.get(u) or set()
            B = ensemble.terms.get(u) or set()
            ls = llm.spans.get(u) or set()
            cs = ensemble.spans.get(u) or set()
            lm = len(ls & cs)
            w.writerow([u[0], u[1], len(A), len(B), len(A & B),
                        _r(jaccard(A, B)), len(A - B), len(B - A),
                        lm, len(ls),
                        sum(1 for L in per_model.values() if u in L.terms)])

    # ── headline stats ───────────────────────────────────────────────────────
    span_inter = span_total = 0
    unit_llm_unique = unit_cpu_unique = 0
    for u in common:
        ls = llm.spans.get(u) or set()
        cs = ensemble.spans.get(u) or set()
        span_inter += len(ls & cs)
        span_total += len(ls)
        A = llm.terms.get(u) or set()
        B = ensemble.terms.get(u) or set()
        if A - B:
            unit_llm_unique += 1
        if B - A:
            unit_cpu_unique += 1

    result = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "cpu_csv": str(args.cpu_csv), "llm_csv": str(args.llm_csv),
        "llm_name": args.llm_name,
        "method": ("inter-model agreement only; no gold standard exists, so "
                   "precision/recall/F1 are NOT computable from these data"),
        "scope": {
            "cpu_papers": len({u[0] for u in cpu_units}),
            "llm_papers": len({u[0] for u in llm_units}),
            "cpu_units": len(cpu_units), "llm_units": len(llm_units),
            "common_units": len(common),
            "cpu_only_units": len(cpu_only), "llm_only_units": len(llm_only),
            "universe": "intersection of both systems' units",
        },
        "agreement_llm_vs_cpu_ensemble": {
            "ensemble_definition": "cpu-ensemble (union of all CPU models)",
            "jaccard_global_terms": _r(jaccard(llm_g, ens_g)),
            "jaccard_pooled_within_unit": _r(pooled_jaccard(llm, ensemble, common)[0]),
            "jaccard_mean_per_unit": _r(mean_unit_jaccard(llm, ensemble, common)[0]),
            "jaccard_typed_pooled": _r(ti / tu) if tu else None,
            "llm_only_terms": len(llm_g - ens_g),
            "cpu_only_terms": len(ens_g - llm_g),
            "shared_terms": len(llm_g & ens_g),
            "llm_distinct_terms": len(llm_g),
            "cpu_distinct_terms": len(ens_g),
            "llm_span_exact_match_rate": _r(span_inter / span_total) if span_total else None,
            "units_with_llm_unique_terms": unit_llm_unique,
            "units_with_cpu_unique_terms": unit_cpu_unique,
        },
        "agreement_llm_vs_cpu_ensemble_excl_generic": {
            "ensemble_definition": ("cpu-ensemble-excl-generic (%d models; dropped "
                                    "generic-label-only: %s)"
                                    % (len(typed_models),
                                       ", ".join(generic_models) or "none")),
            "jaccard_global_terms": _r(jaccard(llm_g, ens2_g)),
            "jaccard_pooled_within_unit": _r(pooled_jaccard(llm, ens_typed, common)[0]),
            "jaccard_mean_per_unit": _r(mean_unit_jaccard(llm, ens_typed, common)[0]),
            "jaccard_typed_pooled": _r(ti2 / tu2) if tu2 else None,
            "llm_only_terms": len(llm_g - ens2_g),
            "cpu_only_terms": len(ens2_g - llm_g),
            "shared_terms": len(llm_g & ens2_g),
            "llm_distinct_terms": len(llm_g),
            "cpu_distinct_terms": len(ens2_g),
            "cpu_rows": ens_typed.rows,
            "llm_span_exact_match_rate": _r(span_inter / span_total) if span_total else None,
        },
        "label_caveat": ("CPU models emit native labels; en_core_sci_lg emits only "
                         "generic ENTITY and en_ner_craft_md also emits GO. The raw "
                         "ensemble is dominated by en_core_sci_lg's generic-ENTITY "
                         "rows, so the excl-generic ensemble is the fairer "
                         "term-level comparison and the two are reported side by "
                         "side. Type-aware numbers are restricted to the shared CDM "
                         "vocabulary."),
    }
    (out / "comparison.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

    _write_summary(out / "summary.txt", result, scope_rows, pairwise, type_rows,
                   only_llm, only_ens, cpu_only, llm_only,
                   only_ens2=only_ens2, generic_models=generic_models)
    print("[%s] wrote %s" % (time.strftime("%H:%M:%S"), out))
    print(json.dumps(result["agreement_llm_vs_cpu_ensemble"], indent=2))
    print(json.dumps(result["agreement_llm_vs_cpu_ensemble_excl_generic"], indent=2))


def _r(x):
    if x is None:
        return ""
    return round(x, 6) if isinstance(x, float) else x


def _write_csv(path, rows):
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def _write_summary(path, result, scope, pairwise, type_rows, only_llm, only_ens,
                   cpu_only, llm_only, only_ens2=None, generic_models=()):
    L = []
    a = result["agreement_llm_vs_cpu_ensemble"]
    a2 = result.get("agreement_llm_vs_cpu_ensemble_excl_generic") or {}
    s = result["scope"]
    L.append("=" * 78)
    L.append("SECTION-LEVEL NER AGREEMENT: LLM vs CPU ensemble")
    L.append("=" * 78)
    L.append("Generated        : %s" % result["generated"])
    L.append("CPU source       : %s" % result["cpu_csv"])
    L.append("LLM source       : %s  (%s)" % (result["llm_csv"], result["llm_name"]))
    L.append("")
    L.append("!! METHOD CAVEAT: this is INTER-MODEL AGREEMENT, not accuracy.")
    L.append("   No gold standard exists for this corpus, so precision/recall/F1")
    L.append("   cannot be computed here. High agreement != correct; a shared")
    L.append("   error counts as agreement. Do not report these as accuracy.")
    L.append("")
    L.append("-" * 78)
    L.append("SCOPE")
    L.append("-" * 78)
    L.append("  CPU corpus      : %d papers / %d units" % (s["cpu_papers"], s["cpu_units"]))
    L.append("  LLM corpus      : %d papers / %d units" % (s["llm_papers"], s["llm_units"]))
    L.append("  common universe : %d units  <- all metrics use this" % s["common_units"])
    L.append("  units CPU only  : %d  (see units_missing_from_llm.csv)" % s["cpu_only_units"])
    L.append("  units LLM only  : %d  (see units_missing_from_cpu.csv)" % s["llm_only_units"])
    L.append("")
    L.append("-" * 78)
    L.append("HEADLINE AGREEMENT (common universe, %d units)" % s["common_units"])
    L.append("-" * 78)
    L.append("  TWO CPU ENSEMBLES ARE REPORTED. The raw ensemble includes")
    L.append("  en_core_sci_lg, which labels every span generic ENTITY and therefore")
    L.append("  inflates CPU term counts with no type signal. The second ensemble")
    L.append("  drops such models, which is the fairer term-level comparison.")
    if generic_models:
        L.append("  models dropped from ensemble 2: %s" % ", ".join(generic_models))
    L.append("")
    L.append("  %-38s %12s %12s" % ("", "ensemble 1", "ensemble 2"))
    L.append("  %-38s %12s %12s"
             % ("CPU ensemble definition", "all models", "excl generic"))
    L.append("  %-38s %12s %12s"
             % ("CPU distinct terms", a["cpu_distinct_terms"], a2.get("cpu_distinct_terms", "")))
    if a2.get("cpu_rows"):
        L.append("  %-38s %12s %12s"
                 % ("CPU rows", "", a2["cpu_rows"]))
    L.append("  %-38s %12s %12s"
             % ("shared terms", a["shared_terms"], a2.get("shared_terms", "")))
    L.append("  %-38s %12s %12s"
             % ("only LLM", a["llm_only_terms"], a2.get("llm_only_terms", "")))
    L.append("  %-38s %12s %12s"
             % ("only CPU", a["cpu_only_terms"], a2.get("cpu_only_terms", "")))
    L.append("")
    L.append("  %-38s %12s %12s"
             % ("term Jaccard (global)", a["jaccard_global_terms"],
                a2.get("jaccard_global_terms", "")))
    L.append("  %-38s %12s %12s"
             % ("term Jaccard (pooled within unit)", a["jaccard_pooled_within_unit"],
                a2.get("jaccard_pooled_within_unit", "")))
    L.append("  %-38s %12s %12s"
             % ("term Jaccard (mean per unit)", a["jaccard_mean_per_unit"],
                a2.get("jaccard_mean_per_unit", "")))
    L.append("  %-38s %12s %12s"
             % ("typed Jaccard (pooled)", a["jaccard_typed_pooled"],
                a2.get("jaccard_typed_pooled", "")))
    L.append("  %-38s %12s %12s"
             % ("LLM spans exactly at a CPU span", a["llm_span_exact_match_rate"],
                a2.get("llm_span_exact_match_rate", "")))
    L.append("  %-38s %12s" % ("LLM distinct terms", a["llm_distinct_terms"]))
    L.append("  %-38s %12d / %d"
             % ("units where LLM found something new",
                a["units_with_llm_unique_terms"], s["common_units"]))
    L.append("  %-38s %12d / %d"
             % ("units where CPU found something new",
                a["units_with_cpu_unique_terms"], s["common_units"]))
    L.append("")
    L.append("-" * 78)
    L.append("PER-SYSTEM SCOPE")
    L.append("-" * 78)
    for r in scope:
        if r["system"].startswith("__"):
            continue
        L.append("  %-34s papers=%-4s units=%-5s rows=%-9s terms=%-7s types=%s"
                 % (r["system"], r["papers"], r["units"], r["rows"],
                    r["distinct_terms"], r["n_types"]))
    L.append("")
    L.append("-" * 78)
    L.append("LLM vs EACH CPU MODEL (common universe)")
    L.append("-" * 78)
    L.append("  %-42s %8s %8s %8s" % ("model", "Jglob", "Jpooled", "Jtyped"))
    for r in pairwise:
        L.append("  %-42s %8s %8s %8s"
                 % (r["model"][:42], r["jaccard_global"],
                    r["jaccard_pooled_within_unit"], r["jaccard_typed_pooled"]))
    L.append("")
    L.append("-" * 78)
    L.append("PER-TYPE AGREEMENT (types emitted by both sides)")
    L.append("-" * 78)
    L.append("  %-16s %10s %10s %9s %8s %8s"
             % ("type", "LLM terms", "CPU terms", "shared", "Jaccard", "both"))
    for r in sorted(type_rows, key=lambda x: -(x["llm_rows"] or 0)):
        if r["both_emit_type"] != "yes":
            continue
        L.append("  %-16s %10s %10s %9s %8s %8s"
                 % (r["type"], r["llm_distinct_terms"], r["cpu_distinct_terms"],
                    r["shared_terms"], r["jaccard"], r["both_emit_type"]))
    L.append("")
    L.append("  types only one side emits:")
    for r in type_rows:
        if r["both_emit_type"] != "yes":
            L.append("    %-16s LLM_rows=%-8s CPU_rows=%s"
                     % (r["type"], r["llm_rows"], r["cpu_rows"]))
    L.append("")
    L.append("-" * 78)
    L.append("WHAT EACH SIDE CONTRIBUTES (top terms unique to one side, #units)")
    L.append("-" * 78)
    L.append("  LLM-only (not in any CPU model):")
    for n, c in only_llm.most_common(15):
        L.append("     %-44s %5d" % (n[:44], c))
    L.append("  CPU-only (not in the LLM output, raw ensemble; dominated by")
    L.append("  en_core_sci_lg generic-ENTITY surface forms):")
    for n, c in only_ens.most_common(15):
        L.append("     %-44s %5d" % (n[:44], c))
    if a2:
        L.append("")
        L.append("  CPU-only (not in the LLM output, generic-excluded ensemble):")
        for n, c in only_ens2.most_common(15):
            L.append("     %-44s %5d" % (n[:44], c))
    L.append("")
    L.append("-" * 78)
    L.append("COVERAGE GAPS (not averaged into the metrics above)")
    L.append("-" * 78)
    L.append("  %d CPU units have no LLM counterpart." % len(cpu_only))
    L.append("  %d LLM units have no CPU counterpart." % len(llm_only))
    L.append("  Centre-path sections (Introduction/Background/Conclusion) are")
    L.append("  deliberately excluded by the historical Cell-7c LLM skip rule and")
    L.append("  appear here as CPU-only units rather than as disagreement.")
    L.append("")
    L.append("Files: comparison.json, scope.csv, pairwise.csv, per_model.csv,")
    L.append("       type_agreement.csv, unique_terms.csv, unique_terms_excl_generic.csv,")
    L.append("       per_unit_overlap.csv, units_missing_from_llm.csv,")
    L.append("       units_missing_from_cpu.csv")
    Path(path).write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
