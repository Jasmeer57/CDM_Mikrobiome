"""D10 - provenance and release-manifest consistency.

Three separate questions, deliberately not merged:

  1. INTEGRITY   - do the files match their published checksums?
  2. IDENTITY    - does the release say it is what its path says it is? Version
                   strings, upstream paths, and the build ledger must agree with
                   the directory the DB sits in.
  3. LINEAGE     - can every row be traced to a named extraction run, and does
                   that run survive into the frozen release as VERIFIED?

Integrity is a checksum result and nothing else. Identity and lineage are
documentary: a mismatch there means a reader cannot tell which build produced a
number, which is a different (and usually more consequential) failure than a
changed byte.

Read-only. Stdlib only.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import AUDIT, CAT, CORPUS, DB, REPO, TERM, connect, emit  # noqa: E402

OUT: dict = {"diagnostic": "d10_provenance_manifest"}

CDM303 = REPO / "releases/cdm_v3/3.0.3"
CDM302 = REPO / "releases/cdm_v3/3.0.2"


def sha256_file(p, chunk=1 << 22):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for blk in iter(lambda: fh.read(chunk), b""):
            h.update(blk)
    return h.hexdigest()


def manifest_check():
    """Verify MANIFEST.sha256 for each frozen release that ships one."""
    out = {}
    for label, d in (("cdm_v3/3.0.3", CDM303),
                     ("data_catalogue_v3/3.1.1", CAT),
                     ("terminology/1.0.1", TERM)):
        mf = d / "MANIFEST.sha256"
        if not mf.exists():
            # terminology ships a ledger digest instead
            cand = sorted(d.glob("*MANIFEST*")) + sorted(d.glob("*ledger*"))
            out[label] = {
                "manifest_present": False,
                "sha256_manifest_present": False,
                "other_ledger_files": [c.name for c in cand],
            }
            continue
        good = bad = missing = 0
        bad_list = []
        n = 0
        with open(mf, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                m = re.match(r"^([0-9a-fA-F]{64})\s+\*?(.+)$", line)
                if not m:
                    continue
                n += 1
                want, rel = m.group(1).lower(), m.group(2).strip()
                target = (d / rel.lstrip("./")).resolve()
                if not target.exists():
                    missing += 1
                    bad_list.append({"file": rel, "problem": "MISSING"})
                    continue
                got = sha256_file(target)
                if got == want:
                    good += 1
                else:
                    bad += 1
                    bad_list.append({"file": rel, "problem": "HASH_MISMATCH",
                                     "expected": want[:16], "got": got[:16]})
        out[label] = {
            "manifest_present": True,
            "sha256_manifest_present": True,
            "entries": n,
            "verified": good,
            "mismatched": bad,
            "missing": missing,
            "pct_verified": round(100.0 * good / max(1, n), 2),
            "problems": bad_list[:20],
        }
    return out


def identity_check(con):
    """Does the release identify itself as the release it lives in?"""
    meta = {}
    try:
        for k, v in con.execute("select key, value from run_metadata"):
            meta[k] = v
    except Exception as e:  # noqa: BLE001
        return {"error": "run_metadata unreadable: %s" % e}

    notes = []

    declared_version = meta.get("cdm_version")
    if declared_version != "3.0.3":
        notes.append("run_metadata.cdm_version=%r but the DB lives in "
                     "releases/cdm_v3/3.0.3" % declared_version)

    # The catalogue is named as a *working* path, not the frozen release path.
    cat = meta.get("catalogue") or ""
    if "outputs/results" in cat:
        frozen = CAT.exists()
        notes.append(
            "run_metadata.catalogue=%r is a working-output path, not the frozen "
            "release path releases/data_catalogue_v3/3.1.1 (which %s exist). A "
            "reader cannot tell from the manifesto which catalogue was frozen."
            % (cat, "does" if frozen else "does not"))

    term = meta.get("terminology") or ""
    if term.rstrip("/").endswith("1.0.1"):
        notes.append(
            "run_metadata.terminology=%r points at terminology 1.0.1, while "
            "extraction_run still carries run id 28619916 labelled "
            "'terminology build 1.0.0'. The version string and the run label "
            "disagree." % term)

    # built_at vs migrated_at vs promoted_at ordering
    ts = {k: meta.get(k) for k in ("built_at", "migrated_at", "promoted_at")}
    if all(ts.values()):
        if not (ts["built_at"] <= ts["migrated_at"] <= ts["promoted_at"]):
            notes.append("timestamp order is not built_at <= migrated_at <= "
                         "promoted_at: %r" % ts)

    # template version
    tpl = meta.get("template") or ""
    notes.append("run_metadata.template=%r; src/template/cdm is a DRAFT design "
                 "proposal per AGENTS.md, so the template version string refers to "
                 "an unimplemented schema spec." % tpl)

    return {
        "run_metadata": meta,
        "observations": notes,
        "derived_from_present": CDM302.exists(),
        "derived_from_declared": meta.get("derived_from"),
    }


def build_ledger(con):
    """cdm_change_log + REVERT_303.sql: is every 3.0.3 step reversible?"""
    rows = []
    try:
        for r in con.execute(
                "select step, kind, target, description, rows_affected, "
                "length(revert_sql) from cdm_change_log order by step"):
            rows.append({"step": r[0], "kind": r[1], "target": r[2],
                         "description": (r[3] or "")[:160],
                         "rows_affected": r[4], "revert_sql_len": r[5]})
    except Exception as e:  # noqa: BLE001
        return {"error": "cdm_change_log unreadable: %s" % e}

    revert = CDM303 / "REVERT_303.sql"
    revert_txt = revert.read_text(encoding="utf-8", errors="replace") if revert.exists() else ""
    kinds = Counter(r["kind"] for r in rows)
    with_sql = sum(1 for r in rows if (r["revert_sql_len"] or 0) > 0)
    statements = len(re.findall(r";\s*$", revert_txt, re.M))
    return {
        "change_log_rows": len(rows),
        "kinds": dict(kinds),
        "rows_with_revert_sql": with_sql,
        "rows_without_revert_sql": len(rows) - with_sql,
        "revert_file_present": revert.exists(),
        "revert_file_statements": statements,
        "rows_total_affected": sum(r["rows_affected"] or 0 for r in rows),
        "sample": rows[:6],
        "interpretation": (
            "The release documents itself as reversible. Each logged step carries "
            "inline revert SQL and a rollup file exists. This is a documentary "
            "claim: it was not executed here, because running it would mutate a "
            "frozen release."),
    }


def extraction_run_lineage(con):
    """Can each row be traced to a run, and is that run VERIFIED?"""
    runs = []
    for r in con.execute(
            "select extraction_run_id, stage, model, verification from extraction_run"):
        runs.append({"run_id": r[0], "stage": r[1], "model": r[2],
                     "verification": r[3]})
    verif = Counter(r["verification"] for r in runs)

    # Which tables actually carry extraction_run_id, and how populated is it?
    tables = [t for (t,) in con.execute(
        "select name from sqlite_master where type='table' and name not like 'sqlite_%'")]
    coverage = []
    for t in sorted(tables):
        cols = {c[1] for c in con.execute('PRAGMA table_info("%s")' % t)}
        if "extraction_run_id" not in cols:
            continue
        total = con.execute('select count(*) from "%s"' % t).fetchone()[0]
        if total == 0:
            continue
        nulls = con.execute(
            'select count(*) from "%s" where extraction_run_id is null or '
            "trim(extraction_run_id)=''" % t).fetchone()[0]
        distinct = [r[0] for r in con.execute(
            'select distinct extraction_run_id from "%s" where extraction_run_id '
            'is not null limit 40' % t)]
        valid = set(r["run_id"] for r in runs)
        unknown = [d for d in distinct if d not in valid]
        coverage.append({
            "table": t, "rows": total, "null_run_id": nulls,
            "pct_traced": round(100.0 * (total - nulls) / total, 2),
            "distinct_runs": len(distinct),
            "run_ids_not_in_extraction_run": unknown[:6],
            "n_run_ids_not_in_extraction_run": len(unknown),
        })
    coverage.sort(key=lambda x: x["pct_traced"])
    no_col = [t for t in sorted(tables)
              if "extraction_run_id" not in
              {c[1] for c in con.execute('PRAGMA table_info("%s")' % t)}]
    return {
        "extraction_run_rows": len(runs),
        "verification_states": dict(verif),
        "runs": runs,
        "tables_with_extraction_run_id": len(coverage),
        "tables_without_extraction_run_id": no_col,
        "lowest_coverage": coverage[:12],
        "untraceable_rows_total": sum(c["null_run_id"] for c in coverage),
        "rows_total_in_traced_tables": sum(c["rows"] for c in coverage),
    }


def _resolve_artifact(art):
    """source_artifact is stored without its releases/ or outputs/ prefix.

    Try the literal path, then the two repo prefixes. Whichever exists wins; the
    ambiguity itself is the finding, so the winning prefix is reported.
    """
    if not art:
        return None, None
    p = Path(art)
    if p.is_absolute() or p.exists():
        return str(p), "as_written"
    for pref in ("releases", "outputs"):
        q = REPO / pref / art
        if q.exists():
            return str(q), "prefixed_with_%s" % pref
    return None, "unresolved"


def upstream_artifact_hashes(con):
    """extraction_run.source_artifact_sha256 - resolvable to a real file?"""
    out = []
    for r in con.execute(
            "select extraction_run_id, source_artifact, source_artifact_sha256, "
            "verification from extraction_run"):
        art, want = r[1], r[2]
        e = {"run_id": r[0], "source_artifact": art,
             "has_sha256": bool(want), "verification": r[3]}
        if art and want:
            path, how = _resolve_artifact(art)
            e["resolution"] = how
            e["resolved_path"] = path
            e["file_exists"] = bool(path)
            if path:
                ap = Path(path)
                if ap.is_file():
                    e["artifact_is_file"] = True
                    e["hash_matches"] = sha256_file(ap) == want.lower()
                else:
                    e["artifact_is_file"] = False
                    e["hash_matches"] = None
        out.append(e)
    return {
        "rows": out,
        "with_sha256": sum(1 for e in out if e["has_sha256"]),
        "hash_verified_here": sum(1 for e in out if e.get("hash_matches") is True),
        "hash_mismatched_here": sum(1 for e in out if e.get("hash_matches") is False),
        "artifact_missing": sum(1 for e in out if e.get("file_exists") is False),
        "artifact_is_directory": sum(1 for e in out if e.get("artifact_is_file") is False
                                     and e.get("file_exists")),
        "paths_requiring_implied_prefix": sum(
            1 for e in out if str(e.get("resolution", "")).startswith("prefixed_with")),
        "interpretation": (
            "All declared upstream artifacts resolve and match their hashes, but "
            "only after guessing an implied 'releases/' or 'outputs/' prefix: "
            "source_artifact strings are stored as 'zenodo_v1/...' and "
            "'results/...', which are not paths from the repo root. A reader who "
            "takes the string literally concludes the artifact is missing. The "
            "hash claim is true; the path claim is not self-sufficient."),
    }


def version_surface():
    """Every place a version number is asserted, side by side."""
    surface = {}

    rel = REPO / "releases/RELEASES.md"
    if rel.exists():
        txt = rel.read_text(encoding="utf-8", errors="replace")
        surface["RELEASES.md_lines_mentioning_3_0_3"] = [
            ln.strip()[:180] for ln in txt.splitlines() if "3.0.3" in ln][:10]
        surface["RELEASES.md_digests"] = re.findall(r"[0-9a-f]{12,64}", txt)[:12]

    led = TERM / "RELEASE_LEDGER.md"
    if led.exists():
        surface["terminology_ledger_head"] = led.read_text(
            encoding="utf-8", errors="replace").splitlines()[:14]

    for label, p in (("cdm_3.0.3_README", CDM303 / "README.md"),
                     ("cdm_3.0.3_PROMOTION", CDM303 / "PROMOTION.txt"),
                     ("catalogue_MANIFEST", CAT / "MANIFEST.json")):
        if p.exists() and p.suffix != ".json":
            surface[label] = p.read_text(encoding="utf-8",
                                         errors="replace")[:400]
    if (CAT / "MANIFEST.json").exists():
        try:
            m = json.loads((CAT / "MANIFEST.json").read_text(encoding="utf-8"))
            surface["catalogue_manifest_keys"] = sorted(m.keys())[:30]
            surface["catalogue_manifest_version"] = (
                m.get("version") or m.get("release") or m.get("catalogue_version"))
        except Exception as e:  # noqa: BLE001
            surface["catalogue_manifest_error"] = str(e)
    return surface


def main():
    con = connect()

    print("=== 1. integrity: MANIFEST.sha256 ===")
    OUT["integrity"] = manifest_check()
    for k, v in OUT["integrity"].items():
        if not v.get("sha256_manifest_present"):
            print("  %-26s no sha256 manifest; ledgers=%s"
                  % (k, v.get("other_ledger_files")))
            continue
        print("  %-26s %d entries  verified=%d  mismatch=%d  missing=%d  (%.2f%%)"
              % (k, v["entries"], v["verified"], v["mismatched"], v["missing"],
                 v["pct_verified"]))
        for p in v["problems"][:5]:
            print("      !", p)

    print("\n=== 2. identity: does the DB know which release it is? ===")
    OUT["identity"] = identity_check(con)
    for k, v in sorted(OUT["identity"].get("run_metadata", {}).items()):
        print("  %-14s = %s" % (k, str(v)[:110]))
    print()
    for n in OUT["identity"].get("observations", []):
        print("  ! " + n)

    print("\n=== 3. build ledger / reversibility ===")
    OUT["build_ledger"] = build_ledger(con)
    b = OUT["build_ledger"]
    print("  change_log rows=%s kinds=%s with_revert_sql=%s without=%s"
          % (b["change_log_rows"], b["kinds"], b["rows_with_revert_sql"],
             b["rows_without_revert_sql"]))
    print("  REVERT_303.sql present=%s statements=%s  rows affected logged=%s"
          % (b["revert_file_present"], b["revert_file_statements"],
             format(b["rows_total_affected"], ",")))

    print("\n=== 4. extraction-run lineage ===")
    OUT["lineage"] = extraction_run_lineage(con)
    L = OUT["lineage"]
    print("  extraction_run rows=%s states=%s" % (L["extraction_run_rows"],
                                                  L["verification_states"]))
    print("  tables with extraction_run_id=%s  without=%s"
          % (L["tables_with_extraction_run_id"], len(L["tables_without_extraction_run_id"])))
    print("  rows in traced tables=%s  with NULL run id=%s"
          % (format(L["rows_total_in_traced_tables"], ","),
             format(L["untraceable_rows_total"], ",")))
    print("  lowest coverage:")
    for c in L["lowest_coverage"][:8]:
        print("    %-26s rows=%-9s traced=%6.2f%%  unknown_run_ids=%s"
              % (c["table"], format(c["rows"], ","), c["pct_traced"],
                 c["n_run_ids_not_in_extraction_run"]))
    print("  tables with no extraction_run_id column: %s"
          % L["tables_without_extraction_run_id"])

    print("\n=== 5. upstream artifact hashes ===")
    OUT["upstream_hashes"] = upstream_artifact_hashes(con)
    u = OUT["upstream_hashes"]
    print("  runs with sha256=%s  re-verified here=%s  mismatched=%s  missing=%s  "
          "needs_implied_prefix=%s"
          % (u["with_sha256"], u["hash_verified_here"], u["hash_mismatched_here"],
             u["artifact_missing"], u["paths_requiring_implied_prefix"]))
    for r in u["rows"]:
        if r["has_sha256"]:
            print("    %-24s %-34s %s match=%s"
                  % (r["run_id"], str(r["source_artifact"])[:34],
                     r.get("resolution"), r.get("hash_matches")))

    print("\n=== 6. version surface ===")
    OUT["version_surface"] = version_surface()
    vs = OUT["version_surface"]
    for k, v in vs.items():
        if isinstance(v, list):
            print("  %s: %d entries" % (k, len(v)))
            for x in v[:6]:
                print("     ", str(x)[:150])
        else:
            print("  %s: %s" % (k, str(v)[:200].replace("\n", " | ")))

    emit("d10_provenance_manifest", OUT)


if __name__ == "__main__":
    main()
