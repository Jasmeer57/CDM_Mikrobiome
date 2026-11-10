"""Component N probe: rights-layer mechanics of the shipped public release.

Audit-only, read-only. Produces diagnostics/results/cqa_n_rights.json with the quantities
quoted in 14_RIGHTS_READINESS_QUALITY.md that are not already in d12_rights_readiness.json:

  * over-redaction on TEXT_INCLUDED papers (source CDM cell non-null -> public DB cell null)
  * identifier / non-text value losses source -> public, attributed to withheld vs included
  * withheld section text is NULL in public but keeps its source sha256
  * gap_evidence serialization split (python repr kept for KEEP, re-serialized JSON for non-KEEP)
  * surviving text cells by quote policy in the shipped catalogue

Reads:  releases/cdm_v3/3.0.3/microbiome_cdm_v3.db  (mode=ro)
        /tmp/cqa_zn/public.db                        (extracted public bundle DB)
        releases/data_catalogue_v3/3.1.1/tables/*.csv
        releases/zenodo_frozen/catalogue/*.csv
"""
import collections
import csv
import io
import ast
import json
import os
import re
import sqlite3

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
SRC_DB = "file:%s/releases/cdm_v3/3.0.3/microbiome_cdm_v3.db?mode=ro" % REPO
PUB_DB = "file:/tmp/cqa_zn/public.db?mode=ro"
SRC_CAT = os.path.join(REPO, "releases/data_catalogue_v3/3.1.1/tables")
SHIP_CAT = os.path.join(REPO, "releases/zenodo_frozen/catalogue")
LIC = os.path.join(REPO, "releases/data_catalogue_v3/3.1.1/provenance/paper_licences.csv")
OUT = os.path.join(os.path.dirname(__file__), "results", "cqa_n_rights.json")

# tables that exist in the public bundle but not in the frozen source CDM
PUBLIC_ONLY = {"release_rights", "release_redaction"}
# tables deliberately excluded from the value diff (derived/compendium layers)
EXCLUDED = {"compendium_project", "compendium_sample", "compendium_sample_tag", "concept"}


def rows(path):
    raw = open(path, encoding="utf-8", errors="replace").read().replace("\0", "")
    return list(csv.DictReader(io.StringIO(raw)))


def ws(s):
    """Whitespace-normalise exactly as build/verify_zenodo_frozen do."""
    return re.sub(r"\s+", " ", s or "").strip()


def over_redaction(src, out):
    """Cells owned by a TEXT_INCLUDED paper that lose their value in the public DB."""
    lay = {p: l for p, l in src.execute("SELECT paper_id, text_layer FROM pubdb.release_rights")}
    inc = sorted(p for p, l in lay.items() if l == "TEXT_INCLUDED")
    q = ",".join("?" * len(inc))
    pairs = collections.Counter()
    papers = collections.Counter()
    detail = []
    tabs = [r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    for t in tabs:
        if t in EXCLUDED or t in PUBLIC_ONLY:
            continue
        cols = [r[1] for r in src.execute('PRAGMA table_info("%s")' % t)]
        if "paper_id" not in cols:
            continue
        for c in cols:
            if c == "paper_id":
                continue
            a = src.execute('SELECT COUNT("%s") FROM "%s"' % (c, t)).fetchone()[0]
            try:
                b = src.execute('SELECT COUNT("%s") FROM pubdb."%s"' % (c, t)).fetchone()[0]
            except sqlite3.Error:
                continue
            if a == b:
                continue
            # per-layer counts; paper_id is present so the layer join is valid
            qs = 'SELECT COUNT("%s") FROM "%s" WHERE paper_id IN (SELECT paper_id FROM pubdb.release_rights WHERE text_layer=?)' % (c, t)
            qp = 'SELECT COUNT("%s") FROM pubdb."%s" WHERE paper_id IN (SELECT paper_id FROM pubdb.release_rights WHERE text_layer=?)' % (c, t)
            x_inc = src.execute(qs, ("TEXT_INCLUDED",)).fetchone()[0]
            y_inc = src.execute(qp, ("TEXT_INCLUDED",)).fetchone()[0]
            x_wh = src.execute(qs, ("TEXT_WITHHELD_PENDING_RIGHTS_REVIEW",)).fetchone()[0]
            y_wh = src.execute(qp, ("TEXT_WITHHELD_PENDING_RIGHTS_REVIEW",)).fetchone()[0]
            lost_inc = x_inc - y_inc
            if lost_inc:
                pairs[(t, c)] = lost_inc
                ids = [r[0] for r in src.execute(
                    'SELECT DISTINCT paper_id FROM "%s" WHERE paper_id IN (%s)' % (t, q), inc)]
                for p in ids:
                    x1 = src.execute('SELECT COUNT("%s") FROM "%s" WHERE paper_id=?' % (c, t), (p,)).fetchone()[0]
                    y1 = src.execute('SELECT COUNT("%s") FROM pubdb."%s" WHERE paper_id=?' % (c, t), (p,)).fetchone()[0]
                    if x1 != y1:
                        papers[p] += x1 - y1
                        detail.append({"table": t, "column": c, "paper_id": p, "lost": x1 - y1})
            if x_wh - y_wh:
                pairs[("__withheld__" + t, c)] = x_wh - y_wh
    out["over_redaction"] = {
        "included_paper_cells_lost": sum(pairs[k] for k in pairs if not k[0].startswith("__withheld__")),
        "by_table_column": {"%s.%s" % k: v for k, v in pairs.items() if not k[0].startswith("__withheld__")},
        "by_paper": dict(papers.most_common()),
        "papers_affected": len(papers),
        "detail": detail,
        "withheld_cells_lost_by_table_column": {
            "%s.%s" % (k[0].replace("__withheld__", ""), k[1]): v
            for k, v in pairs.items() if k[0].startswith("__withheld__")},
    }


def caption_losses(src, out):
    """Non-text value losses source -> public, with the layer the lost value belonged to."""
    lay = {p: l for p, l in src.execute("SELECT paper_id, text_layer FROM pubdb.release_rights")}
    targets = [
        ("dataset", "repository_accession"), ("dataset", "repository_accession_original"),
        ("dataset", "dataset_url"), ("dataset", "license_or_terms"), ("dataset", "dataset_title"),
        ("data_asset", "accession_original"), ("data_asset", "repository_url"),
        ("data_asset", "license_or_terms"), ("paper", "full_text_url"),
        ("relation", "subject_display_label"), ("relation", "object_display_label"),
        ("canonical_term", "term"), ("canonical_term", "term_norm"),
    ]
    res = {}
    for t, c in targets:
        a = src.execute('SELECT COUNT("%s") FROM "%s"' % (c, t)).fetchone()[0]
        try:
            b = src.execute('SELECT COUNT("%s") FROM pubdb."%s"' % (c, t)).fetchone()[0]
        except sqlite3.Error:
            res["%s.%s" % (t, c)] = {"source": a, "public": None, "note": "table missing in public"}
            continue
        if a == b:
            res["%s.%s" % (t, c)] = {"source": a, "public": b, "lost": 0}
            continue
        entry = {"source": a, "public": b, "lost": a - b}
        cols = [r[1] for r in src.execute('PRAGMA table_info("%s")' % t)]
        if "paper_id" in cols:
            own = collections.Counter()
            for p, l in lay.items():
                x = src.execute('SELECT COUNT("%s") FROM "%s" WHERE paper_id=?' % (c, t), (p,)).fetchone()[0]
                y = src.execute('SELECT COUNT("%s") FROM pubdb."%s" WHERE paper_id=?' % (c, t), (p,)).fetchone()[0]
                if x != y:
                    own[l] += x - y
            entry["lost_by_layer"] = dict(own)
        else:
            entry["lost_by_layer"] = {"UNATTRIBUTED_no_paper_id": a - b}
        res["%s.%s" % (t, c)] = entry
    out["value_losses"] = res


def section_hashes(src, out):
    q = """SELECT s.paper_id, s.section_id_original, s.text_hash_sha256,
                  LENGTH(s.section_text_original)
             FROM section s"""
    src_rows = {}
    for pid, sid, h, n in src.execute(q):
        src_rows[(pid, sid)] = (h, n)
    pub = {}
    pq = """SELECT s.paper_id, s.section_id_original, s.text_hash_sha256,
                   LENGTH(s.section_text_original)
              FROM section s"""
    for pid, sid, h, n in src.execute(pq.replace("FROM section s", "FROM pubdb.section s")):
        pub[(pid, sid)] = (h, n)
    lay = {p: l for p, l in src.execute("SELECT paper_id, text_layer FROM pubdb.release_rights")}
    inc_txt_diff = 0
    inc_checked = 0
    wh_null = 0
    wh_hash_kept = 0
    wh_hash_lost = 0
    end = 0
    for (pid, sid), (h, n) in src_rows.items():
        ph, pn = pub.get((pid, sid), (None, None))
        if lay[pid] == "TEXT_INCLUDED":
            inc_checked += 1
            if pn is None or pn != n:
                inc_txt_diff += 1
            if ph != h:
                end += 1
            if pn == 0 and (n or 0) == 0:
                end = end  # zero-char placeholder, both null-equivalent
        else:
            if pn is None:
                wh_null += 1
                if ph == h:
                    wh_hash_kept += 1
                else:
                    wh_hash_lost += 1
    out["sections"] = {
        "source_pairs": len(src_rows),
        "public_pairs": len(pub),
        "included_checked": inc_checked,
        "included_text_length_mismatches": inc_txt_diff,
        "included_hash_mismatches": end,
        "withheld_pairs": sum(1 for p, l in lay.items() if l != "TEXT_INCLUDED"),
        "withheld_text_null": wh_null,
        "withheld_hash_retained": wh_hash_kept,
        "withheld_hash_missing": wh_hash_lost,
    }


def gap_evidence_serialization(src, out):
    """source stores gap_evidence as python repr; shipped non-KEEP rows are re-serialized JSON."""
    pol = {r["paper_id"]: r["quote_policy"] for r in rows(LIC)}

    def scan(base):
        res = collections.Counter()
        for fn in ("cohorts.csv", "samples.csv", "assays.csv", "datasets.csv",
                   "data_assets.csv", "findings.csv"):
            p = os.path.join(base, fn)
            if not os.path.exists(p):
                continue
            for r in rows(p):
                v = r.get("gap_evidence") or ""
                if not v.strip():
                    continue
                q = pol.get(r.get("paper_id"), "?")
                kind = "other"
                if v.lstrip().startswith("[{") or v.lstrip().startswith("{"):
                    try:
                        json.loads(v)
                        kind = "json"
                    except Exception:
                        kind = "json_invalid"
                if kind == "other" and v.lstrip().startswith("["):
                    kind = "pyrepr"
                res[(q, kind)] += 1
                res[(q, "has_quote")] += 1 if '"quote"' in v or "'quote'" in v else 0
                res[(q, "rows")] += 1
        return {"%s|%s" % k: v for k, v in res.items()}

    out["gap_evidence_serialization"] = {"source": scan(SRC_CAT), "shipped": scan(SHIP_CAT)}


def shipped_text_cells(src, out):
    pol = {r["paper_id"]: r["quote_policy"] for r in rows(LIC)}
    cols = ["abstract", "evidence_text", "finding_text", "gap_evidence", "evidence_span",
            "source_sentence", "supporting_sentence", "definition_text"]
    res = {}
    for label, base in (("source", SRC_CAT), ("shipped", SHIP_CAT)):
        per = collections.Counter()
        for fn in sorted(os.listdir(base)):
            if not fn.endswith(".csv"):
                continue
            for r in rows(os.path.join(base, fn)):
                q = pol.get(r.get("paper_id"), "?")
                for c in cols:
                    if c in r and (r[c] or "").strip():
                        per["%s|%s" % (q, c)] += 1
        res[label] = dict(per)
    out["text_cells_by_policy"] = res


def flag_semantics(out):
    """Does evidence_redacted mark every non-KEEP row, or only the REDACT subset?

    Reported twice - over the six record tables and over every CSV including
    papers.csv - because papers.csv carries no evidence_redacted values at all and
    would otherwise hide the 164-row difference between the two denominators.
    """
    pol = {r["paper_id"]: r["quote_policy"] for r in rows(LIC)}
    res = {}
    for label, base in (("source", SRC_CAT), ("shipped", SHIP_CAT)):
        for scope in ("all_csv", "record_tables_only"):
            n = collections.Counter()
            for fn in sorted(os.listdir(base)):
                if not fn.endswith(".csv"):
                    continue
                if scope == "record_tables_only" and fn == "papers.csv":
                    continue
                for r in rows(os.path.join(base, fn)):
                    q = pol.get(r.get("paper_id"), "?")
                    f = (r.get("evidence_redacted") or "") == "LICENCE"
                    n["%s|%s" % (q, "flagged" if f else "unflagged")] += 1
            res["%s/%s" % (label, scope)] = dict(n)
    out["flag_semantics"] = res


def redaction_log_reconciliation(src, out):
    """Does every logged (table,column) loss equal the observed source->public delta?

    Three buckets are needed, not two: a column can lose values on INCLUDED papers
    (over-redaction), on WITHHELD papers (policy), or belong to a table that has no
    paper_id at all (unattributable by layer).
    """
    log = collections.defaultdict(int)
    for t, c, n in src.execute(
            "SELECT table_or_file, column_name, values_emptied FROM pubdb.release_redaction"):
        if "/" in t:
            continue
        log[(t, c)] += n
    obs = {}
    for t in sorted({k[0] for k in log}):
        cols = [r[1] for r in src.execute('PRAGMA table_info("%s")' % t)]
        for c in [k[1] for k in log if k[0] == t]:
            if c not in cols:
                obs[(t, c)] = None
                continue
            a = src.execute('SELECT COUNT("%s") FROM "%s"' % (c, t)).fetchone()[0]
            b = src.execute('SELECT COUNT("%s") FROM pubdb."%s"' % (c, t)).fetchone()[0]
            obs[(t, c)] = a - b
    inc = {tuple(k.split(".")): v for k, v in out["over_redaction"]["by_table_column"].items()}
    wh = {tuple(k.split(".")): v
          for k, v in out["over_redaction"]["withheld_cells_lost_by_table_column"].items()}
    mismatched, unattributed = [], []
    for k in sorted(log):
        if obs.get(k) != log[k]:
            mismatched.append({"table": k[0], "column": k[1],
                               "logged": log[k], "observed": obs.get(k)})
        if k not in inc and k not in wh:
            unattributed.append({"table": k[0], "column": k[1], "logged": log[k]})
    out["redaction_log_reconciliation"] = {
        "logged_pairs": len(log),
        "logged_total_cells": sum(log.values()),
        "logged_targets": len({k[0] for k in log}),
        "columns_absent_in_source_schema": [
            {"table": k[0], "column": k[1]} for k, v in obs.items() if v is None],
        "pairs_where_log_equals_observed_delta": len(log) - len(mismatched),
        "mismatched_pairs": mismatched,
        "attributable_to_included_papers": sum(inc.values()),
        "attributable_to_withheld_papers": sum(wh.values()),
        "unattributed_pairs": unattributed,
        "unattributed_cells": sum(u["logged"] for u in unattributed),
        "reconciles": not mismatched
        and sum(inc.values()) + sum(wh.values()) + sum(u["logged"] for u in unattributed)
        == sum(log.values()),
    }


def shipped_catalogue_reconciliation(src, out):
    """The catalogue side of the log does NOT reconcile 1:1; account for the residual.

    Observed shipped-CSV non-empty deltas are smaller than the logged values for two
    reasons: quote removal empties the quoted span but leaves surrounding prose, and
    the shipped CSVs populate an evidence_redacted column the log never mentions.
    Decompose every logged pair into exact / partly-surviving, and list observed-only
    pairs separately.
    """
    log = collections.defaultdict(int)
    for t, c, n in src.execute(
            "SELECT table_or_file, column_name, values_emptied FROM pubdb.release_redaction"):
        if not t.startswith("catalogue/"):
            continue
        log[(os.path.basename(t)[:-4], c)] += n
    files = ("cohorts", "samples", "assays", "datasets", "data_assets", "findings",
             "papers")
    src_rows = {f: rows(os.path.join(SRC_CAT, f + ".csv")) for f in files}
    ship_rows = {f: rows(os.path.join(SHIP_CAT, f + ".csv")) for f in files}
    rowcount_problems = [{"file": f, "source": len(src_rows[f]), "shipped": len(ship_rows[f])}
                         for f in files if len(src_rows[f]) != len(ship_rows[f])]
    exact, partial, observed_only, observed_cells = [], [], [], 0
    flag_delta = {}
    for f in files:
        a, b = src_rows[f], ship_rows[f]
        for c in a[0]:
            x = sum(1 for r in a if (r.get(c) or "").strip())
            y = sum(1 for r in b if (r.get(c) or "").strip())
            d = x - y
            if c != "evidence_redacted":
                observed_cells += d
            if (f, c) in log:
                if log[(f, c)] == d:
                    exact.append({"file": f, "column": c, "cells": d})
                else:
                    partial.append({"file": f, "column": c, "logged": log[(f, c)],
                                    "observed_delta": d, "still_non_empty": y})
            elif d and c != "evidence_redacted":
                observed_only.append({"file": f, "column": c, "delta": d,
                                      "shipped_non_empty": y})
            elif c == "evidence_redacted":
                flag_delta[os.path.splitext(f)[0]] = {"source": x, "shipped": y,
                                                      "newly_flagged": y - x}
    resid = sum(p["still_non_empty"] for p in partial)
    out["shipped_catalogue_reconciliation"] = {
        "rowcount_problems": rowcount_problems,
        "logged_pairs": len(log),
        "logged_cells": sum(log.values()),
        "pairs_exact": len(exact),
        "pairs_partial": partial,
        "exact_cells": sum(e["cells"] for e in exact),
        "partial_cells_logged": sum(p["logged"] for p in partial),
        "partial_cells_still_non_empty": resid,
        "observed_only_pairs": observed_only,
        "observed_only_cells": sum(o["delta"] for o in observed_only),
        "evidence_redacted_newly_populated": flag_delta,
        "evidence_redacted_newly_populated_cells": sum(
            v["newly_flagged"] for v in flag_delta.values()),
        "observed_total_nonempty_delta_excl_flag": observed_cells,
        "reconciles": not rowcount_problems
        and sum(e["cells"] for e in exact)
        + sum(p["logged"] for p in partial)
        + sum(o["delta"] for o in observed_only)
        == sum(log.values()),
        "note": "non-empty cell deltas, not row counts; quote removal can leave a "
                "shortened value in place, so logged > observed for those pairs",
    }


def gap_changes_values(src, out):
    """Extracted field values surviving inside non-KEEP `gap_changes` change logs.

    gap_changes is {'<field>': {'original':..., 'new':..., 'source':...}} and is not in
    TEXT_COLS, so only the W=50 window rule touches it. `new` holds the extracted value,
    which for short values is an exact excerpt of the paper. Counted per table because the
    report has to say which tables were enumerated.
    """
    pol = {r["paper_id"]: r["quote_policy"] for r in rows(LIC)}
    nonkeep = {p for p, q in pol.items() if q != "KEEP"}
    text = collections.defaultdict(list)
    for pid, t in src.execute("SELECT paper_id, section_text_original FROM section"):
        text[pid].append(t or "")
    T = {p: ws(" ".join(v)) for p, v in text.items()}
    included_text = " ".join(t for p, t in T.items() if p not in nonkeep)

    per_file = collections.defaultdict(collections.Counter)
    cells = []
    for fn in sorted(os.listdir(SHIP_CAT)):
        if not fn.endswith(".csv"):
            continue
        rd = rows(os.path.join(SHIP_CAT, fn))
        if not rd or "gap_changes" not in (rd[0].keys() if rd else ()):
            continue
        for r in rd:
            pid = r.get("paper_id")
            if pid not in nonkeep:
                continue
            v = (r.get("gap_changes") or "").strip()
            if not v:
                continue
            try:
                d = ast.literal_eval(v)
            except (ValueError, SyntaxError):
                continue
            if not isinstance(d, dict):
                continue
            for field, change in d.items():
                if not isinstance(change, dict):
                    continue
                new = change.get("new")
                if not isinstance(new, str) or len(new) < 30:
                    continue
                cells.append((fn, pid, field, new))
                per_file[fn]["cells_ge30"] += 1
                per_file[fn]["max_len"] = max(per_file[fn]["max_len"], len(new))
                if len(new) >= 50:
                    per_file[fn]["cells_ge50"] += 1
                    if ws(new) in T.get(pid, ""):
                        per_file[fn]["verbatim_own_paper"] += 1

    verbatim = [c for c in cells if len(c[3]) >= 50 and ws(c[3]) in T.get(c[1], "")]
    out["gap_changes_values"] = {
        "note": "non-KEEP papers only; value must be a string >= 30 chars in the 'new' slot",
        "files_enumerated": sorted(per_file),
        "cells_ge30": len(cells),
        "cells_ge50": sum(1 for c in cells if len(c[3]) >= 50),
        "verbatim_own_paper": len(verbatim),
        "verbatim_also_in_included_paper": sum(1 for c in verbatim if ws(c[3]) in included_text),
        "verbatim_max_len": max((len(ws(c[3])) for c in verbatim), default=0),
        "verbatim_all_under_60": all(len(ws(c[3])) < 60 for c in verbatim),
        "max_len_any": max((len(c[3]) for c in cells), default=0),
        "len_buckets_cells_ge30": dict(sorted(
            collections.Counter(
                "30-39" if 30 <= len(c[3]) < 40 else
                "40-49" if len(c[3]) < 50 else
                "50-59" if len(c[3]) < 60 else "60+"
                for c in cells).items())),
        "per_file": {k: dict(v) for k, v in sorted(per_file.items())},
        "verbatim_examples": [
            {"paper_id": c[1], "file": c[0], "field": c[2], "len": len(ws(c[3])),
             "value": ws(c[3])} for c in sorted(verbatim, key=lambda x: -len(x[3]))[:12]],
    }


TEXT_COLS = {"section_text_original", "abstract", "evidence_text", "evidence_span",
             "supporting_sentence", "supporting_sentence_clipped", "source_sentence",
             "definition_text"}
EXEMPT_COLS = {"title", "authors", "journal", "doi", "concept_label",
               "standard_concept_label", "paper_id", "evidence_redacted"}


def window_guarantee(src, out):
    """The shipped README promises removal of any run of >=50 verbatim characters.

    build_zenodo_frozen.Rules.leaks() probes every STRIDE=10 characters, so it can
    only see a run that starts on the probe grid. A run of 50-58 characters that
    falls between probes is invisible to both the builder and verify_zenodo_frozen
    (which uses the same W, STRIDE). Measure what actually survives.

    Two scopes, because the guarantee is about the shipped bundle as a whole:
      catalogue - the shipped CSVs (what a reader downloads)
      public_db - the extracted public DB, non-KEEP papers, non-TEXT columns
    """
    pol = {r["paper_id"]: r["quote_policy"] for r in rows(LIC)}
    withheld = sorted(p for p, q in pol.items() if q != "KEEP")
    text = {}
    for pid, t in src.execute("SELECT paper_id, section_text_original FROM section"):
        text[pid] = text.get(pid, "") + " " + ws(t)
    inc_text = " ".join(t for p, t in text.items() if p not in set(withheld))
    win = {p: {text.get(p, "")[i:i + 50]
               for i in range(0, max(0, len(text.get(p, "")) - 50 + 1))} for p in withheld}

    def longest(v, pid):
        """Longest contiguous substring of v that occurs verbatim in pid's own text."""
        s, t = win.get(pid) or set(), text.get(pid, "")
        if not s:
            return 0, ""
        best, best_s = 0, ""
        for i in range(0, len(v) - 50 + 1):
            if v[i:i + 50] in s:
                n = 50
                while i + n < len(v) and v[i:i + n + 1] in t:
                    n += 1
                if n > best:
                    best, best_s = n, v[i:i + n]
        return best, best_s

    def scan_catalogue():
        lens, per, papers, uniq, ex = [], collections.Counter(), collections.Counter(), [], []
        for fn in ("papers.csv", "findings.csv", "cohorts.csv", "assays.csv",
                   "datasets.csv", "data_assets.csv", "samples.csv"):
            p = os.path.join(SHIP_CAT, fn)
            if not os.path.exists(p):
                continue
            for r in rows(p):
                pid = r.get("paper_id")
                if pol.get(pid) == "KEEP":
                    continue
                for c, v in r.items():
                    if c in TEXT_COLS or c in EXEMPT_COLS or not v:
                        continue
                    v2 = ws(v)
                    if len(v2) < 50:
                        continue
                    n, s = longest(v2, pid)
                    if n < 50:
                        continue
                    lens.append(n)
                    per[(fn[:-4], c)] += 1
                    papers[pid] += 1
                    if s and s in inc_text:
                        continue                       # shared wording, allowed
                    uniq.append({"file": fn[:-4], "column": c, "paper_id": pid,
                                 "run": n, "text": s[:90]})
                    if len(ex) < 12:
                        ex.append(uniq[-1])
        lens.sort()
        return {
            "cells_with_run_ge_50": len(lens),
            "run_min": lens[0] if lens else 0,
            "run_median": lens[len(lens) // 2] if lens else 0,
            "run_max": lens[-1] if lens else 0,
            "cells_with_run_ge_59": sum(1 for x in lens if x >= 59),
            "cells_shared_wording_with_included": len(lens) - len(uniq),
            "cells_unique_to_withheld": len(uniq),
            "papers_affected": len(papers),
            "pairs_affected": len(per),
            "by_file_column": {"%s.%s" % k: v for k, v in per.most_common()},
            "top_papers": dict(papers.most_common(10)),
            "examples": ex,
        }

    def scan_public_db():
        lay = {p: l for p, l in src.execute("SELECT paper_id, text_layer FROM pubdb.release_rights")}
        wh = sorted(p for p, l in lay.items() if l != "TEXT_INCLUDED")
        idx = set()
        for p in wh:
            idx.update(hash(h) for h in win.get(p) or ())
        per, papers = collections.Counter(), collections.Counter()
        uniq = collections.Counter()
        ex = []
        qm = ",".join("?" * len(wh))
        for t in [r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")]:
            if t in PUBLIC_ONLY or t in EXCLUDED:
                continue
            cols = [r[1] for r in src.execute('PRAGMA table_info("%s")' % t)]
            if "paper_id" not in cols:
                continue
            use = [c for c in cols
                   if c != "paper_id" and c not in EXEMPT_COLS and c not in TEXT_COLS]
            if not use:
                continue
            sel = ", ".join('"%s"' % c for c in use)
            for row in src.execute(
                    'SELECT paper_id, %s FROM pubdb."%s" WHERE paper_id IN (%s)' % (sel, t, qm), wh):
                pid = row[0]
                for c, v in zip(use, row[1:]):
                    if not isinstance(v, str) or len(v) < 50:
                        continue
                    v2 = ws(v)
                    if len(v2) < 50:
                        continue
                    found = [v2[i:i + 50] for i in range(0, len(v2) - 50 + 1)
                             if hash(v2[i:i + 50]) in idx]
                    if not found:
                        continue
                    per[(t, c)] += 1
                    papers[pid] += 1
                    if all(h in inc_text for h in found):
                        continue                       # shared wording, allowed
                    uniq[(t, c)] += 1
                    if len(ex) < 8:
                        ex.append({"table": t, "column": c, "paper_id": pid,
                                   "window": found[0]})
        return {
            "cells_with_withheld_window": sum(per.values()),
            "cells_unique_to_withheld": sum(uniq.values()),
            "pairs_affected": len(per),
            "papers_affected": len(papers),
            "by_table_column": {"%s.%s" % k: v for k, v in per.most_common(15)},
            "unique_by_table_column": {"%s.%s" % k: v for k, v in uniq.most_common(10)},
            "examples": ex,
        }

    out["window_guarantee"] = {
        "documented_guarantee_chars": 50,
        "builder_window": 50,
        "builder_stride": 10,
        "effective_guarantee_chars": 59,
        "note": "a 50-character run is detected only if one of its starts falls on the "
                "stride-10 probe grid, so contiguous runs of 50-58 characters survive; "
                "both build_zenodo_frozen and verify_zenodo_frozen use the same W=50/"
                "STRIDE=10 pair, so the 'independent' scan reproduces the same blind spot",
        "catalogue": scan_catalogue(),
        "public_db": scan_public_db(),
    }


def main():
    src = sqlite3.connect(SRC_DB, uri=True)
    src.execute("ATTACH DATABASE '%s' AS pubdb" % PUB_DB)
    out = {}
    over_redaction(src, out)
    caption_losses(src, out)
    section_hashes(src, out)
    gap_evidence_serialization(src, out)
    gap_changes_values(src, out)
    shipped_text_cells(src, out)
    flag_semantics(out)
    redaction_log_reconciliation(src, out)
    shipped_catalogue_reconciliation(src, out)
    window_guarantee(src, out)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w"), indent=1, sort_keys=True)
    print("wrote", OUT)
    print("over_redaction included cells:", out["over_redaction"]["included_paper_cells_lost"],
          "papers:", out["over_redaction"]["papers_affected"])
    print("sections:", json.dumps(out["sections"]))
    print("flag semantics:", json.dumps(out["flag_semantics"]))


if __name__ == "__main__":
    main()
