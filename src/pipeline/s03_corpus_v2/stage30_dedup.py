#!/usr/bin/env python3
"""Stage 30: duplicate detection over titles / DOI / PMID (template §3D, §7).

Nothing is deleted. Every paper gets a duplicate_group_id, a canonical_paper_id and
an is_canonical flag; non-canonical records keep their full text and are marked
excluded from the release subset with an explicit reason.

Canonical choice (deterministic): COMPLETE full text > PARTIAL > FAILED, then more
source characters, then lowest paper_id.

Outputs: data/papers.jsonl (updated), validation/dedup_report.json
Resume: checkpoints/stage30_dedup.jsonl (per paper)
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pipeline.common as C

STAGE = "stage30_dedup"
PV = "2.0.0"

_TIE = {"COMPLETE": 0, "PARTIAL": 1, "REVIEW_REQUIRED": 2, "FAILED": 3, "PENDING": 4}


class DisjointSet:
    def __init__(self):
        self.parent = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra
            self.parent.setdefault(ra, ra)


def main():
    C.require_slurm(STAGE)
    cfg = C.load_config()
    ev = C.Events(cfg["corpus"]["corpus_id"], STAGE, PV)
    papers = C.read_jsonl(C.CORPUS_DIR / "data" / "papers.jsonl")
    if not papers:
        sys.exit("ERROR: data/papers.jsonl is empty; run stage 10 first")

    prog = C.Progress(STAGE, total=len(papers), unit="paper", desc="dedup")
    ckpt = C.Checkpoint(C.CORPUS_DIR / "checkpoints" / f"{STAGE}.jsonl", key="paper_id")
    started = C.now_utc()

    # ---- build identifier keys ----
    ds = DisjointSet()
    keys = defaultdict(list)
    for p in papers:
        pid = p["paper_id"]
        ds.find(pid)
        if p.get("DOI"):
            keys["doi:" + str(p["DOI"]).lower().strip()].append(pid)
        if p.get("PMID"):
            keys["pmid:" + str(p["PMID"]).strip()].append(pid)
        t = C.normalize_title(p.get("title") or "")
        if len(t) >= 20:  # avoid collapsing short/generic titles
            keys["title:" + t].append(pid)

    groups_merged = 0
    for key, pids in keys.items():
        if len(pids) > 1:
            groups_merged += 1
            for other in pids[1:]:
                ds.union(pids[0], other)

    clusters = defaultdict(list)
    for p in papers:
        clusters[ds.find(p["paper_id"])].append(p["paper_id"])
    by_id = {p["paper_id"]: p for p in papers}

    def rank(pid):
        p = by_id[pid]
        return (_TIE.get(p.get("full_text_completeness") or "PENDING", 4),
                -(p.get("source_characters") or 0), pid)

    canonical_of = {}
    group_ids = {}
    for gi, members in enumerate(sorted(clusters.values(), key=lambda m: sorted(m)[0]), start=1):
        members = sorted(members)
        if len(members) == 1:
            canonical_of[members[0]] = members[0]
            group_ids[members[0]] = None
            continue
        canon = sorted(members, key=rank)[0]
        gid = f"DUP_{gi:04d}"
        for m in members:
            canonical_of[m] = canon
            group_ids[m] = gid

    # ---- apply per paper (checkpointed) ----
    updated = []
    for p in papers:
        pid = p["paper_id"]
        fp = C.sha256_text("|".join(str(p.get(k)) for k in ("title", "DOI", "PMID")))
        if ckpt.has(pid, fp):
            updated.append(ckpt.done[pid]["paper"])
            prog.update(1, detail=f"{pid} resumed")
            continue
        canon = canonical_of[pid]
        gid = group_ids[pid]
        p = dict(p)
        p["duplicate_group_id"] = gid
        p["canonical_paper_id"] = canon
        p["is_canonical"] = (canon == pid)
        if gid and canon != pid:
            p["eligibility_status"] = "duplicate"
            p["inclusion_decision"] = "exclude"
            p["exclusion_reason"] = f"duplicate of {canon} (group {gid}); text retained for audit"
        else:
            p.setdefault("eligibility_status", "pending")
        p.setdefault("dedup", {})
        p["dedup"] = {
            "duplicate_group_id": gid,
            "canonical_paper_id": canon,
            "is_canonical": canon == pid,
            "match_keys": sorted(k for k, v in keys.items() if pid in v and len(v) > 1),
            "checked_at": C.now_utc(),
            "method": "normalized title (>=20 chars) + DOI + PMID union-find",
        }
        ckpt.add({"paper_id": pid, "paper": p}, fingerprint=fp)
        updated.append(p)
        ev.record(pipeline_stage=STAGE, paper_id=pid, run_status="success",
                  input_artifact_hash=C.sha256_text(json.dumps(
                      {k: p.get(k) for k in ("title", "DOI", "PMID")}, sort_keys=True)),
                  output_artifact_hash=(gid or "singleton"))
        prog.update(1, detail=f"{pid} " + (f"dup->{canon}" if gid else "unique"))

    ckpt.close()
    C.write_jsonl(C.CORPUS_DIR / "data" / "papers.jsonl", updated)
    C.write_tracking_table(updated)

    dup_groups = {gid: sorted(m for m, c in canonical_of.items() if group_ids.get(m) == gid)
                  for gid in {g for g in group_ids.values() if g}}
    summary = {
        "stage": STAGE, "pipeline_version": PV, "generated_at": C.now_utc(),
        "papers": len(updated),
        "unique_papers": sum(1 for p in updated if p.get("duplicate_group_id") is None),
        "duplicate_groups": len(dup_groups),
        "papers_in_duplicate_groups": sum(len(v) for v in dup_groups.values()),
        "non_canonical_records": sum(1 for p in updated if not p.get("is_canonical", True)),
        "match_key_collisions": groups_merged,
        "groups": dup_groups,
        "missing_doi": sum(1 for p in updated if not p.get("DOI")),
        "missing_pmid": sum(1 for p in updated if not p.get("PMID")),
        "missing_title": sum(1 for p in updated if not p.get("title")),
        "note": "records are never deleted; non-canonical records are excluded, not removed",
    }
    C.atomic_write_json(C.CORPUS_DIR / "validation" / "dedup_report.json", summary)
    ev.record(pipeline_stage=STAGE, run_status="success", started_at=started,
              completed_at=C.now_utc(),
              output_artifact_hash=C.sha256_text(str(summary)),
              note=f"groups={len(dup_groups)} non_canonical={summary['non_canonical_records']}")
    ev.close()
    prog.close(summary=f"groups={len(dup_groups)} non_canonical={summary['non_canonical_records']}")
    print(json.dumps({k: summary[k] for k in
                      ("papers", "unique_papers", "duplicate_groups", "non_canonical_records")}))


if __name__ == "__main__":
    main()
