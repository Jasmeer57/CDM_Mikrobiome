"""Markdown reports for Stage A. Every number is read from the inventory dict; nothing is typed in."""
from __future__ import annotations

from pathlib import Path


def _n(x):
    return f"{x:,}" if isinstance(x, int) else str(x)


def baseline_md(path: Path, inv: dict) -> None:
    L = []
    a = L.append
    a("# Baseline inventory: CDM 3.1 repair candidate (Stage A)\n")
    a(f"*Status: **{inv['status']}**. Run {inv['started']} to {inv['finished']}. API calls made: {inv['api_calls_made']}. "
      "Read-only: no frozen file, database or earlier output was modified.*\n")
    a("## 1. Frozen releases (manifest re-verification)\n")
    a("| Release | Files listed | Mismatched | Missing | Files on disk | Manifest SHA-256 | Recorded fingerprint |")
    a("|---|---:|---:|---:|---:|---|---|")
    for k, v in inv["frozen_release_verification"].items():
        a(f"| {inv['source_releases'][k]} | {v['listed']} | {len(v['mismatched'])} | {len(v['missing'])} | "
          f"{v['files_on_disk_excl_manifest']} | `{v['manifest_sha256'][:16]}…` | {v['recorded_fingerprint'] or '—'} "
          f"{'OK' if v['fingerprint_ok'] else 'DIFFERS'} |")
    a("\n## 2. Reconciliation with documented values\n")
    a("| Quantity | Documented | Recomputed | Source | Status |")
    a("|---|---:|---:|---|---|")
    for r in inv["reconciliation"]:
        a(f"| {r['quantity']} | {_n(r['expected'])} | {_n(r['recomputed'])} | {r['source']} | {r['status']} |")
    a("\n## 3. Identifier integrity (reported, not repaired)\n")
    for k, v in inv["identifier_integrity"].items():
        a(f"- `{k}`: {v if not isinstance(v, dict) else (v or 'none')}")
    a("\n## 4. Baseline populations\n")
    a("**CDM types of canonical terms:** " + ", ".join(f"{k} {_n(v)}" for k, v in inv["distributions"]["cdm_type"].items()))
    a("\n**Relation families of triples:** " + ", ".join(f"{k} {_n(v)}" for k, v in inv["distributions"]["relation_family"].items()))
    a("\n**Mapping rows by two-model disposition:** " + ", ".join(f"{k} {_n(v)}" for k, v in inv["distributions"]["mapping_disposition_reviewed"].items()))
    a("\n**Mapping rows by evidence status:** " + ", ".join(f"{k} {_n(v)}" for k, v in inv["distributions"]["mapping_evidence_status"].items()))
    a("\n**Triple evidence anchoring:** " + ", ".join(f"{k} {_n(v)}" for k, v in inv["distributions"]["evidence_anchor_status"].items()))
    ts = inv["triple_routes"]
    a(f"\nLocal re-check of the evidence of the {_n(inv['computed']['triples'])} triples against section text "
      f"({_n(ts.get('evidence_rows', 0))} rows): {_n(ts.get('evidence_sentence_matches_offsets', 0))} reproduce at their "
      f"offsets (exactly, up to whitespace, after Unicode/punctuation normalisation, or letters-and-digits only); "
      f"{_n(ts.get('evidence_sentence_found_in_section', 0))} occur somewhere in their section. "
      f"Triples without any evidence row: {_n(ts.get('triples_with_no_evidence', 0))}.\n")
    a("| Stored anchor status | Local re-check | Rows |")
    a("|---|---|---:|")
    for k, v in inv.get("evidence_anchor_crosstab_stored_vs_local", {}).items():
        s, l = k.split("|")
        a(f"| {s} | {l} | {_n(v)} |")
    a("\nThese populations are the starting point, not targets: the 8,071 typed and 17,717 generic triples are not "
      "assumptions about the correct final counts.\n")
    a("## 5. Records per proposed inference route\n")
    a("Routes describe what *could* be sent after the required checks; nothing has been sent.\n")
    a("| Terminology (Stage B) | Terms |")
    a("|---|---:|")
    for k in ("LABEL_ONLY_ELIGIBLE", "LABEL_LONG_STRING_CANDIDATE_PENDING_RIGHTS_VERIFICATION",
              "LABEL_BLOCKED_LONG_STRING_FROM_WITHHELD_PAPER", "CONTEXT_CANDIDATE_PENDING_RIGHTS_VERIFICATION", "NO_ELIGIBLE_CONTEXT"):
        a(f"| {k} | {_n(inv['terminology_routes'].get(k, 0))} |")
    a("\n| Triples (Stage C) | Triples |")
    a("|---|---:|")
    for k in sorted(k for k in ts if "|" in k):
        a(f"| {k.replace('|', ' / ')} | {_n(ts[k])} |")
    a(f"\nEvidence sentences eligible after rights verification: {_n(ts.get('evidence_eligible', 0))}.")
    a("\n## 6. Rights\n")
    a("| API transmission status | Papers |")
    a("|---|---:|")
    for k, v in inv["rights"]["routes"].items():
        a(f"| {k} | {v} |")
    a("\n**Cases needing attention (a paper can have several):**")
    for k, v in inv["rights"]["unresolved_case_counts"].items():
        a(f"- {k}: {v}")
    a("\nNo paper is authorised for sentence transmission: `licence_scope_verified` and "
      "`api_processing_conditions_verified` are `NOT_VERIFIED` for all 453 papers in `RIGHTS_ELIGIBILITY_REGISTER.csv`. "
      "This register is not a legal determination.")
    a("\n## 7. Local vocabularies\n")
    v = inv["vocabularies"]
    a(f"Checksums (`{v['checksums_file']}`): {v['ok']} of {v['checked']} files verify." + (f" Failed: {v['failed']}" if v["failed"] else ""))
    for k, s in v["configured"].items():
        a(f"- {k}: `{s['path']}` {'present' if s['exists'] else '**MISSING**'}")
    a("\n## 8. Limits of this inventory\n")
    a("- Counts and integrity only. Nothing here measures whether a term, mapping or triple is correct.")
    a("- Evidence records carry ids, offsets and SHA-256 hashes, not text, so no text from withheld papers is copied.")
    a("- The rights routes follow the proposed release policy in the rights matrix; they are not legal clearance.")
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


def config_md(path: Path, inv: dict, cfg: dict) -> None:
    api, e = cfg["api"], inv["request_estimates"]
    L = []
    a = L.append
    a("# Pipeline configuration report: CDM 3.1 repair (after Stage A)\n")
    a(f"*Generated {inv['finished']}. Authorised stages: {cfg['authorised_stages']}. API calls made so far: 0.*\n")
    a("## Model and endpoint\n")
    a(f"- Model: `{api['model']}` (as used for the 2026-11-03 judge and cleaned layer).")
    a(f"- Endpoint and key: read only by Stages 02/03 from `{api['secrets_file']}` (chmod 600); never logged, never in the repo.")
    a(f"- Settings: temperature {api['temperature']}, JSON mode {api['json_mode']}, thinking disabled via `extra_body`, "
      f"timeout {api['timeout_s']} s, up to {api['max_retries']} retries with backoff (honours `Retry-After`).")
    a("- Reachability: a compute node (`intelsr_short`) reached the endpoint on 2026-11-05 (HTTP 401 without a key).")
    a("\n## Rate limiting\n")
    a(f"- Endpoint limit 50 requests/min **per key, shared by every client using it** (OpenCode included). The pipeline uses "
      f"{api['max_rpm']}/min.")
    a(f"- One global limiter: inference arrays run with `%1` (one task at a time); inside a task a token bucket spaces "
      f"requests at {api['max_rpm']}/min with at most {api['max_concurrency']} in flight.")
    a(f"- Effective rate assumed: {e['effective_requests_per_minute']:.0f}/min (min of the limit and concurrency × 60 / "
      f"{api['observed_latency_s']} s latency).")
    a("- No other process may use the key during a run; this is a precondition checked by hand before submission.")
    a("\n## Expected requests and runtime (upper bound for the full arrays; pilot first)\n")
    a("| Stage | Items | Per request | Requests | Array tasks | Minutes at the rate limit |")
    a("|---|---:|---:|---:|---:|---:|")
    for k in ("stage_b_terms_label_only", "stage_b_terms_with_context_after_rights_verification",
              "stage_c_triples_with_sentence_after_rights_verification"):
        x = e[k]
        a(f"| {k} | {_n(x['items'])} | {x['items_per_request']} | {_n(x['requests'])} | {x['array_tasks']} | {x['minutes_at_rate_limit']} |")
    a(f"\nTriples not sent (no eligible sentence; remain generic or unresolved for sentence-dependent classification): "
      f"{_n(e['stage_c_triples_not_sent'])}.")
    a("Token use and cost are not estimated until the 100 + 100 pilot measures them.")
    a("\n## HPC\n")
    s = cfg["slurm"]
    a(f"- CPU partition `{s['partition_cpu']}` (8 h limit, verified with `sinfo`). Inference needs no GPU: the model runs on the endpoint.")
    a(f"- Environment: `module load {s['python_module']}` and venv `{s['venv']}`, as in the existing kg and judge jobs.")
    a(f"- Logs: `{s['log_dir']}/`. Outputs: `{cfg['pipeline']['workspace']}/<stage>/`.")
    a("\n## Stage gate and safety\n")
    a("- `config.yaml: authorised_stages` lists what may run; every script exits with code 3 otherwise.")
    a("- Outputs are written to `<dir>.partial` and renamed on success; a completed directory is never overwritten.")
    a("- Frozen manifests are re-verified at the start of every stage.")
    a("- Sentences go to the API only for papers whose two rights checks are recorded as VERIFIED in the register.")
    path.write_text("\n".join(L) + "\n", encoding="utf-8")
