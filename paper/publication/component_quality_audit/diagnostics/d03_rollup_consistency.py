"""D03 - Denormalized rollup / summary column consistency.

Several CDM tables carry precomputed rollups (mention_count, definition_count,
paper.n_findings, dataset child counts, ...). This diagnostic recomputes each
rollup from the child table and reports how many parent rows disagree.

A stale rollup is a correctness defect even when the underlying records are
fine, because downstream consumers and the manuscript quote these columns.

Read-only. Writes no release artifact.
"""

from __future__ import annotations

import sys

sys.path.insert(0, str(__file__.rsplit("/", 1)[0]))
from common import connect, emit


ROLLUPS = [
    # (label, expectation sql -> (computed, stored), population sql)
    (
        "canonical_term.mention_count vs term_mention",
        """select count(*) from canonical_term t
           where t.mention_count is not null
             and t.mention_count <> (select count(*) from term_mention m
                                     where m.canonical_term_id = t.term_id)""",
        "select count(*) from canonical_term where mention_count is not null",
    ),
    (
        "canonical_term.definition_count vs term_definition",
        """select count(*) from canonical_term t
           where coalesce(t.definition_count,0) <> (select count(*) from term_definition d
                                     where d.term_id = t.term_id)""",
        "select count(*) from canonical_term",
    ),
    (
        "canonical_term.paper_count vs distinct mention papers",
        """select count(*) from canonical_term t
           where t.paper_count is not null
             and t.paper_count <> (select count(distinct m.paper_id) from term_mention m
                                   where m.canonical_term_id = t.term_id)""",
        "select count(*) from canonical_term where paper_count is not null",
    ),
    (
        "paper.n_findings vs claim",
        """select count(*) from paper p
           where coalesce(p.n_findings,0) <> (select count(*) from claim c
                                              where c.paper_id=p.paper_id and c.v3_status='KEPT')""",
        "select count(*) from paper",
    ),
    (
        "paper.n_datasets vs dataset",
        """select count(*) from paper p
           where coalesce(p.n_datasets,0) <> (select count(*) from dataset d where d.paper_id=p.paper_id)""",
        "select count(*) from paper",
    ),
    (
        "paper.n_cohorts vs cohort",
        """select count(*) from paper p
           where coalesce(p.n_cohorts,0) <> (select count(*) from cohort c where c.paper_id=p.paper_id)""",
        "select count(*) from paper",
    ),
    (
        "paper.n_samples vs sample",
        """select count(*) from paper p
           where coalesce(p.n_samples,0) <> (select count(*) from sample s where s.paper_id=p.paper_id)""",
        "select count(*) from paper",
    ),
    (
        "paper.n_assays vs assay",
        """select count(*) from paper p
           where coalesce(p.n_assays,0) <> (select count(*) from assay a where a.paper_id=p.paper_id)""",
        "select count(*) from paper",
    ),
    (
        "paper.n_records_total vs sum of child tables",
        """select count(*) from paper p
           where coalesce(p.n_records_total,0) <>
             (select count(*) from claim c where c.paper_id=p.paper_id and c.v3_status='KEPT')
           + (select count(*) from dataset d where d.paper_id=p.paper_id)
           + (select count(*) from cohort c where c.paper_id=p.paper_id)
           + (select count(*) from sample s where s.paper_id=p.paper_id)
           + (select count(*) from assay a where a.paper_id=p.paper_id)
           + (select count(*) from data_asset a where a.paper_id=p.paper_id)""",
        "select count(*) from paper",
    ),
    (
        "paper.sections_total vs section",
        """select count(*) from paper p
           where coalesce(p.sections_total,0) <> (select count(*) from section s where s.paper_id=p.paper_id)""",
        "select count(*) from paper",
    ),
    (
        "relation.mention_count vs triple_mention_ids length",
        """select count(*) from relation
           where mention_count is not null
             and triple_mention_ids is not null
             and mention_count <> (length(triple_mention_ids) - length(replace(triple_mention_ids,'HMPAPER','')))/7""",
        "select count(*) from relation where mention_count is not null and triple_mention_ids is not null",
    ),
    (
        "relation.paper_count vs paper_ids length",
        """select count(*) from relation
           where paper_count is not null and paper_ids is not null
             and paper_count <> (length(paper_ids) - length(replace(paper_ids,'HMPAPER','')))/7""",
        "select count(*) from relation where paper_count is not null and paper_ids is not null",
    ),
    (
        "relation.evidence_verified_count vs relation_evidence anchor_status",
        """select count(*) from relation r
           where r.evidence_verified_count is not null
             and r.evidence_verified_count <> (select count(*) from relation_evidence e
                 where e.canonical_triple_id=r.canonical_triple_id
                   and e.relation_table='relation'
                   and e.anchor_status in ('EXACT','WHITESPACE','NORMALISED'))""",
        "select count(*) from relation where evidence_verified_count is not null",
    ),
    (
        "relation.mention_count vs relation_evidence rows",
        """select count(*) from relation r
           where r.mention_count is not null
             and r.mention_count <> (select count(*) from relation_evidence e
                 where e.canonical_triple_id=r.canonical_triple_id
                   and e.relation_table='relation')""",
        "select count(*) from relation where mention_count is not null",
    ),
]


def main():
    con = connect()
    results = []
    for label, sql, pop_sql in ROLLUPS:
        try:
            bad = con.execute(sql).fetchone()[0]
            pop = con.execute(pop_sql).fetchone()[0]
            results.append(
                {
                    "rollup": label,
                    "population": pop,
                    "disagreeing_rows": bad,
                    "pct_disagreeing": round(100.0 * bad / pop, 4) if pop else None,
                    "status": "CONSISTENT" if bad == 0 else "STALE",
                }
            )
        except Exception as e:  # noqa: BLE001 - report, never crash the audit
            results.append({"rollup": label, "error": f"{type(e).__name__}: {e}"})

    stale = [r for r in results if r.get("status") == "STALE"]
    payload = {
        "status": "OK",
        "rollups_checked": len(results),
        "rollups_stale": len(stale),
        "results": results,
    }
    emit("d03_rollup_consistency", payload)
    for r in results:
        if "error" in r:
            print(f"  ERROR {r['rollup']}: {r['error']}")
        else:
            print(f"  {r['status']:10s} {r['rollup']:58s} {r['disagreeing_rows']:>9,}/{r['population']:>9,} "
                  f"({r['pct_disagreeing']}%)")


if __name__ == "__main__":
    main()
