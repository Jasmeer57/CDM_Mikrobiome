"""Tighter code-only checks on the unsigned-association results (deterministic; no model; reads the run outputs only).

    python src/scripts/triples/unsigned_regate.py

Input: outputs/results/unsigned_resolve_2026-11-10/all/unsigned_resolved.*.jsonl (genie + local parts, 1,708 rows).
Two loopholes found in the 2026-11-10 spot check of unsigned-resolve-v1.0 are closed here (regate v1.1):
  1. "risk" alone counted as sign wording ("associated with CRC risk" -> INCREASES_RISK_OF); now a signed label needs a
     sign word other than "risk" (increased / higher / lower / odds or hazard ratio / ...);
  2. a SECTION-step cue that mentions neither the subject nor the object (e.g. "beta = -0.726", or a sentence about a
     different taxon) cannot be traced to this triple -> demoted. A cue that mentions one endpoint is kept and flagged
     (cue_mentions_one_endpoint), because the other endpoint is often named elsewhere in that sentence.
Demoted rows become ASSOCIATION_UNSIGNED with the model proposal kept in proposed_relation and regate_reason set.
Output: final.jsonl and SUMMARY_FINAL.json in the same folder. Written with Claude Code (declare).
"""
from __future__ import annotations

import glob
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(ROOT / "src/scripts/triples"))
from retype_generic_triples import norm  # noqa: E402

D = ROOT / "outputs/results/unsigned_resolve_2026-11-10/all"
SIGN = re.compile(r"(increas|decreas|higher|lower|greater|less\b|fewer|more\b|positiv|negativ|invers|elevat|reduc|enrich|"
                  r"deplet|rais|odds ratio|hazard ratio|\bor\s*=|\bhr\b|protect|improv|impair|worsen|inhibit|promot|"
                  r"suppress|up-?regulat|down-?regulat|declin|rise|rose|gain|loss|drop|↑|↓|r\s*=\s*-?\d|rho|β|beta)")
SIGNED = {"POSITIVELY_ASSOCIATED_WITH", "NEGATIVELY_ASSOCIATED_WITH", "INCREASED_IN", "DECREASED_IN", "PROMOTES",
          "SUPPRESSES", "UPREGULATES", "DOWNREGULATES", "INCREASES_RISK_OF", "PROTECTIVE_AGAINST", "MORE_ABUNDANT_THAN",
          "LESS_ABUNDANT_THAN", "INCREASES_OVER_TIME", "DECREASES_OVER_TIME", "IMPROVES", "IMPAIRS", "ALLEVIATES",
          "EXACERBATES", "INHIBITS"}
STOP = {"with", "from", "between", "group", "groups", "patients", "subjects", "samples", "this", "that", "these", "those",
        "their", "which"}


def mentions(cue, x):
    """True if a content word of x (5-letter stem, >= 4 letters) occurs in the cue; True if x has no content word."""
    w = [t for t in norm(x).split() if len(t) >= 4 and t not in STOP]
    c = {t[:5] for t in norm(cue).split()}
    return (not w) or any(t[:5] in c for t in w)


def main():
    rows = [json.loads(l) for f in sorted(glob.glob(str(D / "unsigned_resolved.*.jsonl"))) for l in open(f, encoding="utf-8") if l.strip()]
    assert len(rows) == len({r["canonical_triple_id"] for r in rows}), "duplicate triple ids across parts"
    why = Counter()
    for r in rows:
        r["regate_version"] = "v1.1"
        if not r["specific_verified"]:
            continue
        reason = None
        if r["relation"] in SIGNED and not SIGN.search(r["cue"].lower()):
            reason = "SIGN_WORD_ONLY_RISK"
        elif r["step"] == "SECTION":
            ms, mo = mentions(r["cue"], r["subject"]), mentions(r["cue"], r["object"])
            if not (ms or mo):
                reason = "SECTION_CUE_MENTIONS_NEITHER_ENDPOINT"
            elif not (ms and mo):
                r["cue_mentions_one_endpoint"] = True
        if reason:
            why[reason] += 1
            r.update(proposed_relation=r["relation"], relation="ASSOCIATION_UNSIGNED", specific_verified=False, regate_reason=reason)
    with open(D / "final.jsonl", "w", encoding="utf-8") as f:
        for r in sorted(rows, key=lambda r: r["canonical_triple_id"]):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    s = json.load(open(D / "SUMMARY.json", encoding="utf-8"))
    sp = [r for r in rows if r["specific_verified"]]
    s.update({"regate": {"version": "v1.1", "demoted": dict(why),
                         "kept_flagged_cue_mentions_one_endpoint": sum(bool(r.get("cue_mentions_one_endpoint")) for r in sp)},
              "specific_verified": len(sp), "specific_verified_via_section": sum(r["step"] == "SECTION" for r in sp),
              "still_unsigned": sum(r["relation"] == "ASSOCIATION_UNSIGNED" for r in rows),
              "by_backend": {b: {**s["by_backend"][b], "specific_verified": sum(r["backend"] == b for r in sp)} for b in s["by_backend"]},
              "relations_specific": dict(Counter(r["relation"] for r in sp).most_common())})
    c = s["combined"]
    c["cdm_specific_cue_verified_after"] = c["cdm_specific_cue_verified_before"] + len(sp)
    c["cdm_specific_pct_after"] = round(100 * c["cdm_specific_cue_verified_after"] / c["cdm_triples"], 1)
    c["all_specific_cue_verified"] = c["cdm_specific_cue_verified_after"] + c["catalogue_derived_new_specific"]
    c["all_specific_pct"] = round(100 * c["all_specific_cue_verified"] / c["all_triples"], 1)
    (D / "SUMMARY_FINAL.json").write_text(json.dumps(s, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: s[k] for k in ("regate", "specific_verified", "specific_verified_via_section", "still_unsigned",
                                         "by_backend", "combined")}, indent=1))


if __name__ == "__main__":
    main()
