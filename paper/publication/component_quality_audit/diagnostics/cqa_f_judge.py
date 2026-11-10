"""Component F evidence-judge scope reproducer (read-only).

Recomputes every agreement figure quoted in 06_CATALOGUE_QUALITY.md section 4.3
directly from the raw judge shards, and emits the scope table that shows which
number belongs to which denominator. No pipeline code is imported, no network
access, no write outside diagnostics/results/.

Why this exists: CQA-F-AMEND-2026-11-05-2 records that section 4.3 mixed two
scopes (text_value-only and all-fields) inside one sentence. Having the scopes
counted side by side, reproducibly, is what prevents the mistake recurring.

    python3 paper/publication/component_quality_audit/diagnostics/cqa_f_judge.py

Definitions copied verbatim from src/scripts/final_validation/judge_analysis.py
so the arithmetic is identical:

    NOT_TEXT = is_primary_finding, cites_other_work, finding_domain,
               intervention_category      (a passage cannot state a flag)
    LINKS    = cohort_id, assay_id, dataset_id
    VALID    = PASS, FAIL_NOT_SUPPORTED, FAIL_WRONG_FIELD, FAIL_CONTRADICTED,
               UNCERTAIN
    cls(v)   = INVALID for anything not in VALID (including a dict, a missing
               field, or a copied source value). INVALID is therefore a *computed
               class*, never a literal judge output.
"""

from __future__ import annotations

import glob
import json
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
JUDGE_DIR = REPO / "paper/publication/final_validation/evidence_judge"
SHIPPED = JUDGE_DIR / "judge_summary.json"

NOT_TEXT = {"is_primary_finding", "cites_other_work", "finding_domain", "intervention_category"}
LINKS = {"cohort_id", "assay_id", "dataset_id"}
VALID = {"PASS", "FAIL_NOT_SUPPORTED", "FAIL_WRONG_FIELD", "FAIL_CONTRADICTED", "UNCERTAIN"}
GROUP = ("text_value", "link", "flag_or_classification")


def cls(v):
    """Judge label -> 3-class verdict. Anything unrecognised becomes INVALID."""
    if not isinstance(v, str) or v not in VALID:
        return "INVALID"
    if v == "PASS":
        return "PASS"
    return "UNCERTAIN" if v == "UNCERTAIN" else "FAIL"


def link_verdict(v):
    """Per-id verdict dict: PASS only if every linked id is PASS."""
    if isinstance(v, dict) and v and all(isinstance(x, str) for x in v.values()):
        ks = {cls(x) for x in v.values()}
        if ks == {"PASS"}:
            return "PASS"
        return "FAIL_NOT_SUPPORTED" if "FAIL" in ks else "UNCERTAIN"
    return v


def load(model: str):
    rows = []
    for f in sorted(glob.glob(str(JUDGE_DIR / f"{model}.shard*.jsonl"))):
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    return rows


def kappa(tab: Counter) -> dict:
    """Cohen kappa over a (a, b) verdict-pair Counter, as in judge_analysis.py."""
    n = sum(tab.values())
    if not n:
        return {"pairs": 0}
    po = sum(v for (x, y), v in tab.items() if x == y) / n
    labels = {x for k in tab for x in k}
    pa = {l: sum(v for (x, _), v in tab.items() if x == l) / n for l in labels}
    pb = {l: sum(v for (_, y), v in tab.items() if y == l) / n for l in labels}
    pe = sum(pa[l] * pb[l] for l in labels)
    return {
        "pairs": n,
        "observed_agreement": round(po, 3),
        "cohen_kappa_between_models": round((po - pe) / (1 - pe), 3) if pe < 1 else None,
        "both_pass": tab[("PASS", "PASS")],
        "both_fail": tab[("FAIL", "FAIL")],
        "table": {f"{x}|{y}": v for (x, y), v in sorted(tab.items())},
    }


def main() -> None:
    raw = {m: load(m) for m in ("llama", "mistral")}
    meta = {}
    for m, rs in raw.items():
        meta[m] = {
            "lines": len(rs),
            "errors": sum("error" in r for r in rs),
            "truncated": sum(r.get("finish") == "length" for r in rs),
            "records": sum("error" not in r for r in rs),
        }

    # index usable records per model, keyed (table, record_id)
    idx = {}
    for m, rs in raw.items():
        d = {}
        for r in rs:
            if "error" in r:
                continue
            d[(r["table"], r["record_id"])] = r
        idx[m] = d
    common = set(idx["llama"]) & set(idx["mistral"])

    # A field's group, taken from the union of both models' inventories so the scope
    # table can be read without knowing which model spoke first.
    field_group = {}
    for m in idx:
        for r in idx[m].values():
            for f in (r.get("fields") or {}):
                field_group[f] = (
                    "flag_or_classification"
                    if f in NOT_TEXT
                    else ("link" if f in LINKS else "text_value")
                )

    # Agreement is enumerated over *llama's* field inventory per record, exactly as
    # judge_analysis.py does (`for f, va in (a.get("fields") or {}).items()`), with a
    # field absent from mistral reading as None and therefore cls() -> INVALID. Using
    # the union instead inflates the denominator by ~3.5M cells; that difference is
    # itself the reason the two scopes must be reported separately.
    scopes = {
        "text_value": {f for f, g in field_group.items() if g == "text_value"},
        "all_fields": set(field_group),
    }

    out = {"judges": meta, "common_records": len(common), "field_inventory": len(field_group),
           "fields_by_group": {g: sum(1 for x in field_group.values() if x == g) for g in GROUP},
           "scopes": {}}

    for scope_name, keep in scopes.items():
        agree = Counter()
        inval = {"llama": 0, "mistral": 0}
        cell = Counter()
        for key in common:
            a, b = idx["llama"][key], idx["mistral"][key]
            fa = a.get("fields") or {}
            fb = b.get("fields") or {}
            for f in fa:  # llama's inventory, as judge_analysis.py
                if f not in keep:
                    continue
                va = fa.get(f)
                vb = fb.get(f)
                if f in LINKS:
                    va, vb = link_verdict(va), link_verdict(vb)
                ka, kb = cls(va), cls(vb)
                agree[(ka, kb)] += 1
                cell[f] += 1
                if ka == "INVALID":
                    inval["llama"] += 1
                if kb == "INVALID":
                    inval["mistral"] += 1
        both_valid = Counter({k: v for k, v in agree.items() if "INVALID" not in k})
        out["scopes"][scope_name] = {
            "fields_in_scope": len(keep),
            "cells": sum(agree.values()),
            "invalid_by_model": inval,
            "all_cells": kappa(agree),
            "both_valid": kappa(both_valid),
        }

    # the crosstab cells section 4.3 quotes, and where each actually comes from
    tv = out["scopes"]["text_value"]
    out["quoted_cell_provenance"] = {
        "159680": {"scope": "text_value", "key": "PASS|PASS",
                   "value": tv["all_cells"]["table"].get("PASS|PASS")},
        "132890": {"scope": "text_value", "key": "PASS|INVALID",
                   "value": tv["all_cells"]["table"].get("PASS|INVALID")},
    }

    # Provenance sweep for the two disputed figures. Section 4.3 quoted a mistral
    # INVALID count and a both-valid pair count that do not belong to the text_value
    # scope its own sentence names. Enumerate the small variant space that a
    # reimplementation without judge_analysis.py would plausibly have produced, and
    # report whether either figure is reproduced exactly.
    variant = []
    for rst in ("common", "union"):
        keys = common if rst == "common" else (set(idx["llama"]) | set(idx["mistral"]))
        for fi in ("llama", "mistral", "union"):
            for link in (True, False):
                for scope in ("text_value", "all_fields"):
                    tab = Counter()
                    inval = {"llama": 0, "mistral": 0}
                    for key in keys:
                        a = idx["llama"].get(key) or {}
                        b = idx["mistral"].get(key) or {}
                        fa = a.get("fields") or {}
                        fb = b.get("fields") or {}
                        flds = fa if fi == "llama" else (fb if fi == "mistral" else set(fa) | set(fb))
                        for f in flds:
                            if scope == "text_value" and (f in NOT_TEXT or f in LINKS):
                                continue
                            va, vb = fa.get(f), fb.get(f)
                            if link and f in LINKS:
                                va, vb = link_verdict(va), link_verdict(vb)
                            ka, kb = cls(va), cls(vb)
                            tab[(ka, kb)] += 1
                            if ka == "INVALID":
                                inval["llama"] += 1
                            if kb == "INVALID":
                                inval["mistral"] += 1
                    bv = Counter({k: v for k, v in tab.items() if "INVALID" not in k})
                    variant.append({
                        "record_set": rst,
                        "field_iteration": fi,
                        "link_verdict": link,
                        "scope": scope,
                        "cells": sum(tab.values()),
                        "invalid_llama": inval["llama"],
                        "invalid_mistral": inval["mistral"],
                        "both_valid": kappa(bv) if bv else {"pairs": 0},
                    })
    out["variant_sweep"] = variant

    def matches(field, target):
        return [v for v in variant if v.get(field) == target or
                (isinstance(v.get(field), dict) and v[field].get("pairs") == target)]

    out["disputed_figure_provenance"] = {
        "284325": {
            "exact_hits": matches("invalid_mistral", 284325),
            "nearest": min(variant, key=lambda v: abs(v["invalid_mistral"] - 284325))["invalid_mistral"],
        },
        "242158": {
            "exact_hits": matches("both_valid", 242158),
            "nearest": min(variant, key=lambda v: abs(v["both_valid"]["pairs"] - 242158))["both_valid"]["pairs"],
        },
    }

    # the shipped file must agree with this recomputation on the text_value scope
    check = {}
    if SHIPPED.is_file():
        shipped = json.loads(SHIPPED.read_text(encoding="utf-8"))
        for block, mine in (
            ("judge_agreement_text_values", tv["all_cells"]),
            ("judge_agreement_text_values_both_valid", tv["both_valid"]),
        ):
            s = shipped.get(block, {})
            check[block] = {
                "pairs": [s.get("pairs"), mine.get("pairs")],
                "observed_agreement": [s.get("observed_agreement"), mine.get("observed_agreement")],
                "cohen_kappa": [
                    s.get("cohen_kappa_between_models"),
                    mine.get("cohen_kappa_between_models"),
                ],
                "reproduces": (
                    s.get("pairs") == mine.get("pairs")
                    and s.get("observed_agreement") == mine.get("observed_agreement")
                    and s.get("cohen_kappa_between_models")
                    == mine.get("cohen_kappa_between_models")
                ),
            }
        out["shipped_file_reproduces"] = check

    dest = Path(__file__).resolve().parent / "results" / "cqa_f_judge.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=1, default=str) + "\n", encoding="utf-8")
    print(f"[wrote] {dest.relative_to(REPO)}")
    for name, s in out["scopes"].items():
        print(
            f"{name:12s} cells={s['cells']:>7d} invalid llama={s['invalid_by_model']['llama']:>6d} "
            f"mistral={s['invalid_by_model']['mistral']:>7d} | all: po={s['all_cells']['observed_agreement']} "
            f"k={s['all_cells']['cohen_kappa_between_models']} | both_valid: n={s['both_valid']['pairs']} "
            f"po={s['both_valid']['observed_agreement']} k={s['both_valid']['cohen_kappa_between_models']}"
        )
    if check:
        for b, v in check.items():
            print(f"reproduces {b}: {v['reproduces']}  pairs={v['pairs']}")


if __name__ == "__main__":
    main()
