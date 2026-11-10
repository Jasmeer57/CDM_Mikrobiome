"""PubTator-format Java NER tools (DNorm, TaggerOne, GNormPlus, tmChem) over section bodies.

These tools ship as Java command-line applications that consume **PubTator flat
format** — ``<id>|t|<title>`` then ``<id>|a|<abstract>`` — and emit tab-separated
mentions in *title+abstract* coordinates. They have no Python API, so the whole
protocol below is a port of the notebook (``pipeline_standalone.ipynb`` Cells 3-5),
which already established the conventions empirically. Those conventions are not
cosmetic; each one fixes a concrete failure:

1. **Sentinel title.** The tools require a non-empty title; an empty one breaks
   BANNER/TaggerOne parsing. We submit ``section_id`` as the title and subtract
   ``len(title) + 1`` (the space separator) from every returned offset.

2. **One line per section.** ``\\n`` becomes a space in the *tool text only*, with
   the length unchanged, so offsets stay aligned.

3. **Literal ``|`` becomes ``!``.** PubTator uses ``|`` as its field delimiter, so
   markdown table pipes corrupt the record. The substitution is length-preserving.

4. **Terminal sentence break.** A trailing punctuation run can make BANNER emit an
   empty sentence and crash the JVM, so a single ``.`` is appended when the last
   char is not already terminal. Spans reaching into that ``.`` are rejected by
   the bounds check rather than silently accepted.

5. **Ligature expansion.** U+FB00-FB06 (``ﬁ`` -> ``fi``) are expanded in the tool
   text only, because the tools do not tokenize them. Expansion *changes length*,
   so offsets are mapped back through :class:`ToolText`, which **rejects** a span
   that cuts a ligature instead of widening it — widening would silently produce a
   term that does not match the source slice.

Every emitted row is slice-verified against the original section text
(``text[start:end] == term``) before it is kept, so an offset bug cannot reach the
output CSV. Rows that fail are counted and reported, never dropped silently.

**Availability.** All four notebook tools are available. ``tmChem`` is fetched from
``https://www.ncbi.nlm.nih.gov/CBBresearch/Lu/Demo/tmTools/download/tmChem/tmChemM1-0.0.2.tgz``
(the ``ftp.ncbi.nlm.nih.gov/pub/lu/`` tree genuinely has no ``tmChem`` directory, which
is what earlier probes were pointed at) and is self-contained, so chemical coverage
comes from tmChem *and* TaggerOne-Chemical as two independent views.

Abbreviation resolution uses Ab3P-v1.5 (``https://ftp.ncbi.nlm.nih.gov/pub/wilbur/``),
built locally; ``make test`` reproduces NCBI's shipped gold-standard output exactly.
Both DNorm and tmChem receive the Ab3P *directory* as their third argument and invoke
``./identify_abbr`` inside it, so abbreviation-resolved normalization now runs instead
of degrading. If that directory is absent the two tools degrade exactly as DNorm did
before: normalization still completes and is verified (``MESH:D016481``,
``MESH:D013274``), but abbreviations are not expanded.
"""

import csv
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

# ── label -> CDM type registry (ported verbatim from the notebook, registry-0.2) ──
CDM_MAPPING_REGISTRY = [
    # label, target, status, source  -- audited labels first
    dict(label="disease",               target="DISEASE",      status="MAPPED",          source="audit:OK"),
    dict(label="chemical",              target="CHEMICAL",     status="MAPPED",          source="audit:OK"),
    dict(label="simple_chemical",       target="CHEMICAL",     status="MAPPED",          source="audit:OK"),
    dict(label="amino_acid",            target="CHEMICAL",     status="MAPPED",          source="audit:OK"),
    dict(label="chebi",                 target="CHEMICAL",     status="REVIEW_REQUIRED", source="audit:TOO_BROAD"),
    dict(label="cancer",                target="DISEASE",      status="REVIEW_REQUIRED", source="audit:TOO_BROAD"),
    dict(label="pathological_formation", target="DISEASE",     status="REVIEW_REQUIRED", source="audit:TOO_BROAD"),
    dict(label="gene",                  target="GENOMICS",     status="MAPPED",          source="audit:OK"),
    dict(label="gene/protein",          target="GENOMICS",     status="MAPPED",          source="audit:OK"),
    dict(label="gene/family",           target="GENOMICS",     status="MAPPED",          source="audit:OK"),
    dict(label="gene/family/protein",   target="GENOMICS",     status="MAPPED",          source="audit:OK"),
    dict(label="domain",                target="GENOMICS",     status="MAPPED",          source="audit:OK"),
    dict(label="genetic",               target="GENOMICS",     status="REVIEW_REQUIRED", source="audit:TOO_BROAD"),
    dict(label="dna",                    target="GENOMICS",    status="REVIEW_REQUIRED", source="audit:TOO_BROAD"),
    dict(label="protein",               target="PROTEIN",      status="REVIEW_REQUIRED", source="audit:TOO_BROAD"),
    dict(label="gene_or_gene_product",  target="PROTEIN",      status="REVIEW_REQUIRED", source="audit:TOO_BROAD"),
    dict(label="ggp",                   target="PROTEIN",      status="REVIEW_REQUIRED", source="audit:TOO_BROAD"),
    dict(label="go",                    target="PATHWAY",      status="REVIEW_REQUIRED", source="audit:TOO_BROAD"),
    dict(label="so",                    target="DNA_RNA",      status="REVIEW_REQUIRED", source="audit:TOO_BROAD"),
    dict(label="cell_type",             target="CELL_TYPE",    status="MAPPED",          source="audit:OK"),
    dict(label="cell type",             target="CELL_TYPE",    status="MAPPED",          source="audit:OK"),
    dict(label="cell",                  target="CELL_TYPE",    status="REVIEW_REQUIRED", source="audit:WRONG_hybrid"),
    dict(label="cellular_component",    target="CELL_TYPE",    status="REVIEW_REQUIRED", source="audit:TOO_BROAD"),
    dict(label="cl",                    target="CELL_TYPE",    status="MAPPED",          source="audit:OK"),
    dict(label="species",               target="ORGANISM",     status="REVIEW_REQUIRED", source="audit:TOO_BROAD"),
    dict(label="taxon",                target="ORGANISM",     status="REVIEW_REQUIRED", source="audit:TOO_BROAD"),
    dict(label="organism",             target="ORGANISM",     status="REVIEW_REQUIRED", source="audit:TOO_BROAD"),
    # SILENT_PASSTHROUGH fixed: genus/strain previously passed through unmapped; both are ORGANISM.
    dict(label="genus",                target="ORGANISM",     status="MAPPED",          source="audit:SILENT_PASSTHROUGH_FIX"),
    dict(label="strain",               target="ORGANISM",     status="MAPPED",          source="audit:SILENT_PASSTHROUGH_FIX"),
    # wrong or no schema slot -> UNMAPPED_* sentinel (NEEDS_SCHEMA proposes BODY_SITE/SPECIMEN in rationale)
    dict(label="rna",                   target="UNMAPPED_RNA", status="UNMAPPED",       source="audit:WRONG"),
    dict(label="cell_line",             target="UNMAPPED_CELL_LINE", status="UNMAPPED",  source="audit:WRONG"),
    dict(label="cell line",             target="UNMAPPED_CELL_LINE", status="UNMAPPED",  source="audit:WRONG"),
    dict(label="organ",                 target="UNMAPPED_ORGAN", status="UNMAPPED",      source="audit:WRONG"),
    dict(label="tissue",                target="UNMAPPED_TISSUE", status="UNMAPPED",     source="audit:WRONG"),
    dict(label="multi_tissue_structure", target="UNMAPPED_MULTI_TISSUE_STRUCTURE", status="UNMAPPED", source="audit:WRONG"),
    dict(label="organism_substance",    target="UNMAPPED_SPECIMEN", status="UNMAPPED",   source="audit:NEEDS_SCHEMA:proposed_BODY_SITE"),
    dict(label="organism_subdivision",  target="UNMAPPED_ORGANISM_SUBDIVISION", status="UNMAPPED", source="audit:NEEDS_SCHEMA"),
    dict(label="anatomical_system",     target="UNMAPPED_ANATOMICAL_SYSTEM", status="UNMAPPED", source="audit:NEEDS_SCHEMA"),
    dict(label="immaterial_anatomical_entity", target="UNMAPPED_IMMATERIAL_ANATOMICAL_ENTITY", status="UNMAPPED", source="audit:NEEDS_SCHEMA"),
    # rule labels (pipeline-owned label spaces)
    dict(label="kit",                  target="LAB_METHOD",    status="MAPPED",          source="rule"),
    dict(label="platform",             target="LAB_METHOD",    status="MAPPED",          source="rule"),
    dict(label="primer",               target="LAB_METHOD",    status="MAPPED",          source="rule"),
    dict(label="assay",                target="LAB_METHOD",    status="MAPPED",          source="rule"),
    dict(label="amplicon_region",       target="LAB_METHOD",    status="MAPPED",          source="rule"),
    dict(label="software",             target="DATA_ANALYSIS", status="MAPPED",          source="rule"),
    dict(label="reference_db",         target="DATA_ANALYSIS", status="MAPPED",          source="rule"),
    dict(label="taxon_mesh",            target="ORGANISM",     status="MAPPED",          source="rule"),
    dict(label="taxon_abbrev",         target="ORGANISM",      status="MAPPED",          source="rule"),
]
_CDM_MAP = {e["label"].lower(): e for e in CDM_MAPPING_REGISTRY}

# Ligatures expanded in the tool text only (U+FB00-FB06).
LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi",
             "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"}

# Tool placeholders are MISSING ids, never entity ids ("-1" from tmChem etc.).
PLACEHOLDER_IDS = {"", "-1", "-", "none", "null", "n/a", "nan", "cui-less"}
CUI_RE = re.compile(r"^C\d{7}$")

TOOL_FIELDS = ["term", "labels", "model", "paper", "section_id", "section_path",
               "char_start", "char_end", "norm", "norm_raw", "norm_status",
               "norm_vocab", "cdm_type", "mapping_status"]


def cdm_of(label, model):
    """Map a raw tool label to a CDM type via the versioned registry, pass through if unknown."""
    ent = _CDM_MAP.get((label or "").strip().lower())
    if ent is not None:
        return ent["target"]
    L = (label or "").strip()
    return L if L else "UNMAPPED_" + model


def mapping_status(label, cdm_type):
    """Registry status for a label; unknown labels are MAPPED only if the target is a real type."""
    ent = _CDM_MAP.get((label or "").strip().lower())
    if ent is not None:
        return ent["status"]
    from cdm_pipeline.config import CDM_TYPES
    return "MAPPED" if cdm_type in CDM_TYPES else "UNMAPPED"


def clean_norm(raw):
    """-> (norm, status) with status VALID | PLACEHOLDER | MISSING."""
    s = (raw or "").strip()
    if not s:
        return "", "MISSING"
    if s.lower() in PLACEHOLDER_IDS:
        return "", "PLACEHOLDER"
    return s, "VALID"


def norm_vocab(model, label, norm):
    """Vocabulary of a normalized id (MESH/CHEBI/OMIM prefix, UMLS CUI shape, GNormPlus numbering)."""
    if not norm:
        return ""
    if ":" in norm:
        return norm.split(":", 1)[0].upper()
    if CUI_RE.match(norm):
        return "UMLS"
    if model == "GNormPlus":
        return "NCBIGene" if label.lower() == "gene" else "NCBITaxon"
    return "UNKNOWN"


def partial_word(text, s, e):
    """True if [s, e) starts or ends inside an alphanumeric run."""
    return bool((s > 0 and text[s - 1].isalnum() and text[s].isalnum()) or
                (e < len(text) and text[e - 1].isalnum() and text[e].isalnum()))


class ToolText:
    """Original section text plus its ligature-normalized form and a map back to original offsets.

    When the text holds no ligature the mapping is the identity, which is the
    common case (1,359 ligature/typographic characters across the whole corpus).
    """

    def __init__(self, orig):
        self.orig = orig
        self.identity = not any(ch in LIGATURES for ch in orig)
        if self.identity:
            self.norm = orig
            return
        n2o, first, last, parts = [], [], [], []
        for i, ch in enumerate(orig):
            rep = LIGATURES.get(ch, ch)
            parts.append(rep)
            for k in range(len(rep)):
                n2o.append(i)
                first.append(k == 0)
                last.append(k == len(rep) - 1)
        self.norm = "".join(parts)
        self.n2o, self.first, self.last = n2o, first, last

    def to_orig(self, s, e):
        """Map tool span [s, e) to original offsets; returns (os, oe) or a reject reason."""
        if not (0 <= s < e <= len(self.norm)):
            return "OUT_OF_TEXT"
        if self.identity:
            os_, oe = s, e
        else:
            if not (self.first[s] and self.last[e - 1]):
                # span starts or ends inside an expanded ligature: widening would
                # emit a term that does not match the source slice, so reject it.
                return "LIGATURE_SPLIT"
            os_, oe = self.n2o[s], self.n2o[e - 1] + 1
        if self.orig[os_:oe] != self.norm[s:e] and self.identity:
            return "SLICE_MISMATCH"
        return (os_, oe)


def flat1(s):
    """Replace newlines with spaces (same length) so a section fits PubTator's one-line abstract."""
    return re.sub(r"\n", " ", s)


def build_batch(units):
    """Build the global PubTator batch: one article per NON-EMPTY section unit.

    Zero-character units (the 453 ``front/(preamble)`` placeholders, exactly one per
    paper) are **excluded**: they cannot contain an entity, and DNorm aborts the whole
    run with ``IllegalArgumentException: Invalid abstract text="N|a|"`` on an empty
    abstract field. This is a tool constraint, not a coverage decision — the units are
    reported as ``empty_units_skipped`` in the summary.

    Returns ``(records, batch_map)`` where ``records`` is a list of
    ``(idx, cid, sid, path, title, abstract_sanitized)`` and ``batch_map`` maps
    ``idx`` to the same tuple. The sanitization rules are the notebook's and are
    each length-preserving except ligature expansion, which ``ToolText`` undoes.
    """
    records = []
    for idx, u in enumerate([u for u in units if (u["text"] or "").strip()], start=1):
        tt = ToolText(u["text"] or "")
        title = u["section_id"]  # sentinel: non-empty, no spaces
        san = flat1(tt.norm).replace("|", "!")
        if san and san[-1] not in '.!?)]"\'':
            san = san + "."
        records.append((idx, u["cid"], u["section_id"], u["path"], title, san))
    return records, {r[0]: r for r in records}


def write_pubtator_batch(path, records):
    """Write PubTator records as ``<id>|t|title`` / ``<id>|a|abstract`` pairs with a blank terminator.

    The trailing blank line per record is required: GNormPlus drops the final
    article of a batch that does not end in a newline-terminated blank line.
    """
    path = Path(path)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for idx, _cid, _sid, _path, title, abstract in records:
            f.write("%d|t|%s\n%d|a|%s\n\n" % (idx, title, idx, abstract))
    return path


def parse_pubtator_output(path):
    """Parse tool output into dicts with idx/start/end/term/label/norm in title+abstract coords."""
    recs = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for ln in f:
            ln = ln.rstrip("\n")
            if not ln:
                continue
            parts = ln.split("\t")
            if len(parts) >= 5 and parts[1].isdigit() and parts[2].isdigit():
                recs.append(dict(idx=int(parts[0]), start=int(parts[1]), end=int(parts[2]),
                                 term=parts[3], label=parts[4],
                                 norm=parts[5] if len(parts) > 5 else ""))
    return recs


# A tool may report a start that drifts from the true occurrence while echoing the
# input text byte-identically (DNorm does this, non-monotonically within one
# article). Corrections are bounded so a re-anchor can never wander to a distant
# coincidental mention.
MAX_REANCHOR_DRIFT = 64


def reanchor(text, term, st0, max_drift=MAX_REANCHOR_DRIFT):
    """Return the start of the unique occurrence of ``term`` nearest ``st0``.

    Returns ``None`` unless exactly one occurrence is strictly closest and that
    occurrence lies within ``max_drift``. Ambiguity is never resolved by guessing.
    """
    if not term:
        return None
    occs, k = [], text.find(term)
    while k >= 0:
        occs.append(k)
        k = text.find(term, k + 1)
    if not occs:
        return None
    ranked = sorted((abs(o - st0), o) for o in occs)
    if ranked[0][0] > max_drift:
        return None
    if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
        return None
    return ranked[0][1]


def pubtator_to_rows(recs, model, batch_map, unit_index, skip=None):
    """Convert tool records to CSV rows in ORIGINAL section coordinates.

    Every span is shifted past the sentinel title, slice-verified against the
    sanitized tool text, then mapped back through ``ToolText``. Records that fail
    any check are counted (``slice_fails`` / ``out_of_text`` / ``ligature_split``)
    and excluded, so an offset bug shows up in the summary rather than in the CSV.

    A span whose start drifts is re-anchored to the unique nearest occurrence of
    the term (see ``reanchor``) and counted as ``reanchored``; the corrected span
    must still slice-verify, so recovery never weakens the check.

    Returns ``(rows, stats)``.
    """
    rows = []
    stats = {"records": len(recs), "slice_fails": 0, "out_of_text": 0,
             "ligature_split": 0, "skipped": 0, "kept": 0, "reanchored": 0}
    for r in recs:
        if skip and skip(r):
            stats["skipped"] += 1
            continue
        meta = batch_map.get(r["idx"])
        if meta is None:
            stats["skipped"] += 1
            continue
        _idx, cid, sid, _path, title, abstract_s = meta
        st0 = r["start"] - (len(title) + 1)
        en0 = r["end"] - (len(title) + 1)
        if st0 < 0 or en0 > len(abstract_s):
            stats["out_of_text"] += 1
            continue
        if abstract_s[st0:en0] != r["term"]:
            # The tool saw the sanitized text; a mismatch means its reported start
            # drifted. Recover only when the term has exactly one nearest
            # occurrence; the recovered span must slice-verify like any other.
            alt = reanchor(abstract_s, r["term"], st0)
            if alt is None or abstract_s[alt:alt + len(r["term"])] != r["term"]:
                stats["slice_fails"] += 1
                continue
            st0, en0 = alt, alt + len(r["term"])
            stats["reanchored"] += 1
        unit = unit_index[(cid, sid)]
        tt = ToolText(unit["text"] or "")
        mapped = tt.to_orig(st0, en0)
        if isinstance(mapped, str):
            key = "ligature_split" if mapped == "LIGATURE_SPLIT" else "out_of_text"
            stats[key] += 1
            continue
        os_, oe = mapped
        term = tt.orig[os_:oe]
        if tt.orig[os_:oe] != tt.norm[st0:en0] and tt.identity:
            stats["slice_fails"] += 1
            continue
        norm, status = clean_norm(r["norm"])
        cdm = cdm_of(r["label"], model)
        # The corpus source text carries U+0000 ligature-loss artifacts (see the
        # frozen_output 04_ner README, "Known corpus artifact"): a few papers_txt
        # files lost fl/fi ligatures at PDF extraction and the NUL survives into
        # the section text. Tools tag through it faithfully, so the slice above
        # is exact, but NUL bytes break many CSV consumers (Python's csv module
        # raises "_csv.Error: line contains NUL" on read). Strip at emission to
        # match the lossy-concat/load_csv_safe convention. Offsets stay valid:
        # src/scripts/verify_ner_offsets.py classifies these rows as ``nul_explained``
        # (slice.strip-NUL == term) rather than mismatches.
        term = term.replace("\x00", "")
        rows.append({
            "term": term,
            "labels": r["label"],
            "model": model,
            "paper": cid,
            "section_id": sid,
            "section_path": unit["path"],
            "char_start": os_,
            "char_end": oe,
            "norm": norm,
            "norm_raw": r["norm"] or "",
            "norm_status": status,
            "norm_vocab": norm_vocab(model, r["label"], norm),
            "cdm_type": cdm,
            "mapping_status": mapping_status(r["label"], cdm),
        })
        stats["kept"] += 1
    return rows, stats


def _abs_java(java_bin):
    """Return an absolute java executable path.

    ``shutil.which`` handles bare names on ``$PATH``; anything containing a
    separator is resolved against the current directory so it survives the
    per-tool ``cwd`` change.
    """
    if os.sep in str(java_bin):
        return str(Path(java_bin).resolve())
    found = shutil.which(java_bin)
    return found or java_bin


def _dnorm_classpath(tdir):
    """DNorm classpath with Lucene pinned FIRST.

    ``libs/*`` looks correct but is not: ``mallet-deps.jar`` bundles a *stale*
    ``org/apache/lucene/util/Constants`` class that lacks the ``JRE_IS_64BIT`` field
    ``lucene-core-3.6.0`` needs (Lucene 4 removed it, Mallet ships a later Lucene). Java
    expands a wildcard in unspecified order, so whichever ``Constants`` wins decides the
    run: with Mallet's, DNorm dies immediately with ``NoSuchFieldError: JRE_IS_64BIT``
    on *every* JDK including the JDK 8 the notebook used. Naming the Lucene jars
    explicitly ahead of the rest fixes it deterministically.

    Returns:
        Classpath string with ``lucene-core`` and ``lucene-analyzers`` first. Paths are
        absolute: the JVM runs with ``cwd`` set to the tool directory, so a relative
        entry would resolve against the wrong base.
    """
    libs = sorted((tdir / "libs").glob("*.jar"))
    first = [p for p in libs if p.name.startswith("lucene-")]
    rest = [p for p in libs if not p.name.startswith("lucene-")]
    return ":".join(str(p.resolve()) for p in first + rest)


# Directory name of the tmChem distribution inside the tools root.
TMCHEM_DIR = "tmChemM1-0.0.2"


def _ab3p_dir(tools_root):
    """Directory holding ``identify_abbr`` + ``path_Ab3P``, or ``""`` when absent.

    DNorm and tmChem both take an Ab3P *folder* as an argument and shell out to
    ``./identify_abbr`` **with that folder as the child process cwd**; Ab3P then reads
    ``path_Ab3P`` to locate ``WordData/``. Handing either tool a *file* (the old
    ``GNormPlusJava/Ab3P``) makes the JVM raise ``error=20, Not a directory``, and an
    empty argument makes it raise ``error=2, No such file or directory`` — Java reports
    the latter as ``(in directory "")``, which hides the real cause.

    The resolved folder is the locally built Ab3P-v1.5 tree (its ``make test`` target
    reproduces NCBI's shipped gold standard exactly). Returning ``""`` is a supported
    state: both tools then degrade to no abbreviation expansion but still normalize.
    """
    cand = Path(tools_root) / "Ab3P-v1.5"
    exe = cand / "identify_abbr"
    if exe.is_file() and os.access(str(exe), os.X_OK):
        return str(cand)
    return ""


def _run_java(args, cwd, log_path, timeout):
    """Run a Java tool, capturing stdout+stderr to a log file. Returns (ok, elapsed, detail)."""
    t0 = time.time()
    try:
        with open(log_path, "w", encoding="utf-8", errors="replace") as log:
            proc = subprocess.run(args, cwd=str(cwd), stdout=log, stderr=subprocess.STDOUT,
                                  timeout=timeout)
        elapsed = time.time() - t0
        return proc.returncode == 0, elapsed, "exit=%d" % proc.returncode
    except subprocess.TimeoutExpired:
        return False, time.time() - t0, "TIMEOUT after %ss" % timeout
    except Exception as exc:  # noqa: BLE001 — record, never kill the run
        return False, time.time() - t0, "%s: %s" % (type(exc).__name__, exc)


def run_tools(tools_root, units, out_dir, java_bin="java", timeout=21600,
              run_tag="v1", models=None):
    """Run the staged Java tools over section ``units`` and write one CSV per tool.

    Args:
        tools_root: directory holding ``DNorm-0.0.7/``, ``TaggerOne-0.2.1/``, ``GNormPlusJava/``
        units: section units from ``runner_sections.load_sections``
        out_dir: output directory (created)
        java_bin: java executable
        timeout: per-tool wall clock in seconds
        run_tag: suffix for intermediate filenames
        models: subset of model keys to run (default: all five available tools)

    Returns:
        dict summary suitable for ``json.dump``.
    """
    # Every java invocation runs with cwd=tool_dir, so ANY relative path handed
    # to the JVM (the java binary itself, the batch file, -cp entries, the Ab3P
    # folder) silently resolves against the tool directory instead of ours.
    # Resolve once, up front, and pass only absolute paths downstream.
    tools_root = Path(tools_root).resolve()
    out_dir = Path(out_dir).resolve()
    java_bin = _abs_java(java_bin)
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "_work"
    work.mkdir(exist_ok=True)

    records, batch_map = build_batch(units)
    unit_index = {(u["cid"], u["section_id"]): u for u in units}
    batch_path = write_pubtator_batch(work / ("batch_%s.txt" % run_tag), records)
    n_chars = sum(len(r[5]) for r in records)
    n_empty = sum(1 for u in units if not (u["text"] or "").strip())
    print("[java] batch: %d articles, %d tool chars -> %s" % (len(records), n_chars, batch_path))
    print("[java] papers: %d | sections: %d | empty placeholders skipped: %d" % (
        len({u["cid"] for u in units}), len(units), n_empty))

    summary = {"papers": len({u["cid"] for u in units}), "units": len(units),
               "batch_articles": len(records), "batch_chars": n_chars,
               "empty_units_skipped": n_empty,
               "java": java_bin, "run_tag": run_tag, "models": {}}

    ab3p = _ab3p_dir(tools_root)
    summary["ab3p"] = {"status": "OK" if ab3p else "UNAVAILABLE", "dir": ab3p,
                       "effect": ("abbreviation expansion active"
                                  if ab3p else
                                  "DNorm/tmChem normalize without abbreviation expansion")}

    plan = [
        # key, model label, tool dir, args builder, output filename (relative to tool dir), log name
        ("DNorm", "DNorm", tools_root / "DNorm-0.0.7", "dnorm", "output_dnorm_%s.txt"),
        ("TaggerOne-Disease", "TaggerOne-Disease", tools_root / "TaggerOne-0.2.1",
         "taggerone_d", "output_disease_%s.txt"),
        ("TaggerOne-Chemical", "TaggerOne-Chemical", tools_root / "TaggerOne-0.2.1",
         "taggerone_c", "output_chem_%s.txt"),
        ("tmChem", "tmChem", tools_root / TMCHEM_DIR, "tmchem", "output_tmchem_%s.txt"),
        ("GNormPlus", "GNormPlus", tools_root / "GNormPlusJava", "gnormplus", None),
    ]
    if models:
        plan = [p for p in plan if p[0] in models]

    in_name = "input_%s.txt" % run_tag
    tmp_name = "temp_%s" % run_tag

    for key, model, tdir, kind, out_tmpl in plan:
        t0 = time.time()
        if not tdir.exists():
            summary["models"][key] = {"status": "MISSING_TOOL_DIR", "dir": str(tdir)}
            print("[%s] SKIP: %s missing" % (key, tdir))
            continue
        shutil.copy(batch_path, tdir / in_name)

        if kind == "dnorm":
            # DNorm reads a temp dir and the Ab3P folder. The folder must contain
            # identify_abbr (see _ab3p_dir); passing "" degrades gracefully.
            (tdir / tmp_name).mkdir(exist_ok=True)
            out_name = out_tmpl % run_tag
            args = [java_bin, "-Xmx16G", "-Xms8G", "-cp", _dnorm_classpath(tdir),
                    "dnorm.ApplyDNorm",
                    "config/banner_BC5CDR_UMLS2013AA.xml", "data/CTD_diseases.tsv",
                    "output/simmatrix_BC5CDR_e4.bin",
                    ab3p,
                    tmp_name, in_name, out_name]
            out_path = tdir / out_name
            log = work / "dnorm.log"
        elif kind == "tmchem":
            # ncbi.Run <config> <dictionary> <ab3p_dir> <tmpdir> <in> <out>.
            # Run.sh hardcodes -Xms10G; the corpus run uses 2G initial so the JVM
            # does not reserve 10 GB up front for a 6-minute tool.
            (tdir / tmp_name).mkdir(exist_ok=True)
            out_name = out_tmpl % run_tag
            args = [java_bin, "-Xmx10G", "-Xms2G", "-cp", "libs/*", "ncbi.Run",
                    "config/banner_JOINT.xml", "data/dict.txt", ab3p,
                    tmp_name, in_name, out_name]
            out_path = tdir / out_name
            log = work / "tmchem.log"
        elif kind in ("taggerone_d", "taggerone_c"):
            mfile = "model_BC5CDRD.bin" if kind == "taggerone_d" else "model_BC5CDRC.bin"
            out_name = out_tmpl % run_tag
            args = [java_bin, "-Xmx24G", "-cp", "libs/*", "ncbi.taggerOne.ProcessText",
                    "--fileFormat", "Pubtator", "--inputFilename", in_name,
                    "--outputFilename", out_name,
                    "--modelInputFilename", "output/%s" % mfile,
                    "--useSentenceBreaker", "true"]
            out_path = tdir / out_name
            log = work / ("taggerone_%s.log" % ("d" if kind == "taggerone_d" else "c"))
        else:  # gnormplus — folder API
            g_in = work / ("gnorm_in_%s" % run_tag)
            g_out = work / ("gnorm_out_%s" % run_tag)
            for d in (g_in, g_out):
                if d.exists():
                    shutil.rmtree(d)
            g_in.mkdir(parents=True)
            # GNormPlus does not create its output folder
            g_out.mkdir(parents=True)
            shutil.copy(batch_path, g_in / "batch.txt")
            args = [java_bin, "-Xmx30G", "-Xms8G", "-jar", "GNormPlus.jar",
                    str(g_in), str(g_out), "setup.txt"]
            out_path = g_out
            log = work / "gnormplus.log"

        if isinstance(out_path, Path) and out_path.is_file():
            out_path.unlink()

        ok, elapsed, detail = _run_java(args, tdir, log, timeout)
        entry = {"status": "OK" if ok else "FAILED", "detail": detail,
                 "elapsed_seconds": round(elapsed, 1), "log": str(log)}

        if ok:
            if out_path.is_dir():
                # GNormPlus writes one file per input file inside the output folder
                produced = sorted(p for p in out_path.iterdir() if p.is_file())
                recs = []
                for p in produced:
                    recs.extend(parse_pubtator_output(p))
                entry["output_files"] = [p.name for p in produced]
            else:
                if not out_path.exists():
                    entry["status"] = "FAILED"
                    entry["detail"] = "output missing: %s" % out_path
                    recs = []
                else:
                    recs = parse_pubtator_output(out_path)
            skip = None
            if kind == "gnormplus":
                # Species 9606 (human) rows are dropped, as in the notebook
                skip = lambda r: r["label"] == "Species" and r["norm"] == "9606"
            rows, stats = pubtator_to_rows(recs, model, batch_map, unit_index, skip=skip)
            csv_path = out_dir / ("%s_ner.csv" % key.lower().replace("-", "_"))
            with open(csv_path, "w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=TOOL_FIELDS, extrasaction="ignore")
                w.writeheader()
                w.writerows(rows)
            entry.update(stats)
            entry["rows"] = len(rows)
            entry["csv"] = str(csv_path)
            entry["papers_with_entities"] = len({r["paper"] for r in rows})
            labels = {}
            for r in rows:
                labels[r["labels"]] = labels.get(r["labels"], 0) + 1
            entry["labels"] = dict(sorted(labels.items(), key=lambda kv: -kv[1]))
            print("[%s] %s in %.0fs -> %d rows (%d papers), slice_fails=%d out_of_text=%d" % (
                key, entry["status"], elapsed, len(rows),
                entry["papers_with_entities"], stats["slice_fails"], stats["out_of_text"]))
        else:
            print("[%s] %s (%s) after %.0fs — see %s" % (key, entry["status"], detail, elapsed, log))

        summary["models"][key] = entry

    total = sum(v.get("rows", 0) for v in summary["models"].values())
    summary["total_rows"] = total
    write_json(out_dir / ("_java_tools_summary_%s.json" % run_tag), summary)
    return summary


def write_json(path, obj):
    """Write JSON atomically so a killed job never leaves a truncated summary."""
    path = Path(path)
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


# Where each tool leaves its raw PubTator output, relative to the tools root.
# GNormPlus writes a folder into the run's _work dir instead of a single file.
RAW_OUTPUTS = {
    "DNorm": ("DNorm-0.0.7", "output_dnorm_%s.txt"),
    "TaggerOne-Disease": ("TaggerOne-0.2.1", "output_disease_%s.txt"),
    "TaggerOne-Chemical": ("TaggerOne-0.2.1", "output_chem_%s.txt"),
    "tmChem": (TMCHEM_DIR, "output_tmchem_%s.txt"),
}


def remap_outputs(tools_root, units, out_dir, run_tag="v1", models=None):
    """Rebuild CSVs from raw tool output already on disk, without re-running any JVM.

    The offset-mapping step is pure Python and the tools' raw PubTator output is
    kept, so a mapping fix is replayable. Per-model ``status`` and
    ``elapsed_seconds`` are carried over from the existing summary; only the
    mapping-derived fields are recomputed.

    Returns the updated summary dict.
    """
    tools_root = Path(tools_root).resolve()
    out_dir = Path(out_dir).resolve()
    work = out_dir / "_work"
    summary_path = out_dir / ("_java_tools_summary_%s.json" % run_tag)
    if summary_path.is_file():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    else:
        summary = {"models": {}, "run_tag": run_tag}
    summary.setdefault("models", {})
    summary["remapped"] = True

    records, batch_map = build_batch(units)
    unit_index = {(u["cid"], u["section_id"]): u for u in units}

    targets = list(RAW_OUTPUTS) + ["GNormPlus"]
    if models:
        targets = [t for t in targets if t in models]

    for key in targets:
        entry = summary["models"].setdefault(key, {"status": "OK"})
        if key == "GNormPlus":
            src = work / ("gnorm_out_%s" % run_tag)
            if not src.is_dir():
                print("[remap] %s: no raw output at %s — left untouched" % (key, src))
                continue
            recs = []
            for p in sorted(x for x in src.iterdir() if x.is_file()):
                recs.extend(parse_pubtator_output(p))
            skip = lambda r: r["label"] == "Species" and r["norm"] == "9606"
        else:
            sub, tmpl = RAW_OUTPUTS[key]
            src = tools_root / sub / (tmpl % run_tag)
            if not src.is_file():
                print("[remap] %s: no raw output at %s — left untouched" % (key, src))
                continue
            recs = parse_pubtator_output(src)
            skip = None

        model = key
        rows, stats = pubtator_to_rows(recs, model, batch_map, unit_index, skip=skip)
        csv_path = out_dir / ("%s_ner.csv" % key.lower().replace("-", "_"))
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=TOOL_FIELDS, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)

        entry.update(stats)
        entry["rows"] = len(rows)
        entry["csv"] = str(csv_path)
        entry["papers_with_entities"] = len({r["paper"] for r in rows})
        labels = {}
        for r in rows:
            labels[r["labels"]] = labels.get(r["labels"], 0) + 1
        entry["labels"] = dict(sorted(labels.items(), key=lambda kv: -kv[1]))
        print("[remap] %s -> %d rows, slice_fails=%d out_of_text=%d reanchored=%d" % (
            key, len(rows), stats["slice_fails"], stats["out_of_text"],
            stats["reanchored"]))

    summary["total_rows"] = sum(v.get("rows", 0) for v in summary["models"].values())
    write_json(summary_path, summary)
    return summary


def main(argv=None):
    """CLI: run the staged Java tools over the 452-paper segmented-section body universe."""
    import argparse

    ap = argparse.ArgumentParser(
        description="PubTator-format Java NER tools over segmented section bodies.")
    ap.add_argument("--tools_root", default=None,
                    help="directory holding DNorm-0.0.7/, TaggerOne-0.2.1/, GNormPlusJava/, "
                         "tmChemM1-0.0.2/ and Ab3P-v1.5/; defaults to <ner_tools>/tools "
                         "(see cdm_pipeline.paths.ner_tools_dir)")
    ap.add_argument("--seg_dir", default=None,
                    help="segmented markdown dir (default: data/segmented_sections_markdown)")
    ap.add_argument("--output_dir", required=True)
    ap.add_argument("--java", default=None,
                    help="java binary; defaults to <ner_tools>/java/jdk8u*/bin/java, then PATH")
    ap.add_argument("--models", default="all",
                    help="comma list of DNorm,TaggerOne-Disease,TaggerOne-Chemical,tmChem,GNormPlus")
    ap.add_argument("--exclude_papers", default="HMPAPER_000372",
                    help="comma list of paper ids to exclude (default: the HTML stub)")
    ap.add_argument("--max_files", type=int, default=0)
    ap.add_argument("--timeout", type=int, default=79200,
                    help="per-tool wall clock seconds (default 22h, inside intelsr_medium)")
    ap.add_argument("--run_tag", default="v1")
    ap.add_argument("--remap_from_raw", action="store_true",
                    help="rebuild CSVs from raw tool output already on disk; runs no JVM")
    args = ap.parse_args(argv)

    from cdm_pipeline.ner.runner_sections import load_sections
    from cdm_pipeline.paths import ner_tools_dir, segmented_markdown_dir

    if not args.seg_dir:
        args.seg_dir = str(segmented_markdown_dir())
    if not args.tools_root:
        args.tools_root = str(ner_tools_dir() / "tools")

    exclude = {p.strip() for p in (args.exclude_papers or "").split(",") if p.strip()}
    units, _ = load_sections(args.seg_dir, args.max_files or None, body_only=True)
    units = [u for u in units if u["cid"] not in exclude]

    models = None
    if args.models and args.models != "all":
        models = [m.strip() for m in args.models.split(",") if m.strip()]

    if args.remap_from_raw:
        print("[java-tools] remap-only: rebuilding CSVs from raw tool output, no JVM run")
        summary = remap_outputs(args.tools_root, units, args.output_dir,
                               run_tag=args.run_tag, models=models)
        print("[java-tools] total rows: %d" % summary["total_rows"])
        return 0

    java = args.java
    if not java:
        cands = sorted((ner_tools_dir() / "java").glob("jdk8*/bin/java"))
        java = str(cands[0]) if cands else "java"
    java = _abs_java(java)
    if not (Path(java).exists() or shutil.which(java)):
        print("ERROR: java not found: %s" % java)
        return 2

    print("[java-tools] java: %s" % java)
    print("[java-tools] excluded papers: %s" % (sorted(exclude) or "none"))
    summary = run_tools(args.tools_root, units, args.output_dir, java_bin=java,
                        timeout=args.timeout, run_tag=args.run_tag, models=models)
    print("[java-tools] total rows: %d" % summary["total_rows"])
    failed = [k for k, v in summary["models"].items() if v["status"] != "OK"]
    if failed:
        print("[java-tools] FAILED tools: %s" % failed)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
