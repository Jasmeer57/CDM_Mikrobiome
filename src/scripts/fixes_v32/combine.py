"""Step 4 of the 3.2.0-candidate fix: combine gazetteer hits and verified LLM spans into per-paper and per-assay-record
values for dna_extraction_method and sequencing_platform, with provenance. Rules (fixed before the evaluation runs):

Keys: (family, model). An LLM span is normalised by running the gazetteer on the span; if it has no gazetteer hit the
key is ("OTHER", verbatim span) and is kept only if it looks like a product/method name (a capital letter or digit, or
a method word such as phenol, bead, lysis, enzymatic, column, magnetic).
field_source per key: both_agree (a verified LLM span overlaps a gazetteer hit of the key), gazetteer_only, llm_only.
Subsumption: a family-level key ("Illumina", "QIAamp (kit not specified)", "MO BIO kit (not specified)") is dropped when
the same paper has a model-level key of the same vendor group.
field_confidence per key: high = both_agree; medium = gazetteer_only at model/kit level, or llm_only normalised to a
model/kit-level gazetteer entry; low = everything else (family-level only, OTHER, CITED_PROTOCOL). A gazetteer-only hit
is not "high" because the extractor saw every window containing it and did not return it.
Abstention: LLM spans that fail span verification are never used; with no gazetteer hit either, the value is
NOT_REPORTED. DNA extraction given only by citation -> CITED_PROTOCOL (cited text kept as evidence).
Records: every 3.0.3 assay record whose assay_type_normalized is a sequencing assay (platform) or a DNA-based assay
(extraction: sequencing, PCR, qPCR, genotyping), plus every record that had a non-missing old value. A record gets the
paper's keys; if the paper has several keys, those with evidence within +-1,500 characters of the record's own evidence
span in the same section are used when there are any (record_scope=record_section), else all (record_scope=paper).
Record field_source / confidence = the weakest of its keys (both_agree > gazetteer_only > llm_only; high > medium > low).

    python src/scripts/fixes_v32/combine.py [--llm-dir DIR]
Written with Claude Code (declare).
"""
from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(Path(__file__).resolve().parent))
import gazetteer as G  # noqa: E402

CDM = ROOT / "releases/cdm_v3/3.0.3/microbiome_cdm_v3.db"
OUT = G.OUT
LAYER = "3.2.0-candidate"
FIELDS = ("dna_extraction_method", "sequencing_platform")
LLMF = {"dna_extraction_method": "dna_extraction", "sequencing_platform": "sequencing_platform"}
MISSING = ("", "NOT_REPORTED", "NOT_APPLICABLE", "NOT_ACCESSIBLE", "CONFLICTING", None)
SEQ_ASSAY = re.compile(r"sequenc|transcriptom|amplicon|metagenom", re.I)
DNA_ASSAY = re.compile(r"sequenc|transcriptom|amplicon|metagenom|PCR|genotyp", re.I)
METHOD_WORD = re.compile(r"phenol|chloroform|bead|lys|enzym|column|magnetic|boil|salting|CTAB|protocol", re.I)
VGROUP = {"Qiagen/MO BIO": "Qiagen", "Qiagen": "Qiagen"}
SRC_ORDER = ["both_agree", "gazetteer_only", "llm_only"]
CONF_ORDER = ["high", "medium", "low"]
REC_WIN = 1500


def level(key):
    fam, model = key
    return "model" if model and "not specified" not in model and fam != "OTHER" else "family"


def display(field, key):
    return key[1] if key[0] == "OTHER" else G.canonical(field, *key)


def load_llm(d):
    out = []
    for f in sorted(glob.glob(str(Path(d) / "llm_extract.shard*.jsonl"))):
        out += [json.loads(l) for l in open(f, encoding="utf-8")]
    ok = {j["window_id"]: j for j in out if "error" not in j}
    err = {j["window_id"] for j in out if "error" in j} - set(ok)
    return ok, err


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm-dir", default=str(OUT / "llm_extract"))
    a = ap.parse_args(argv)
    c = sqlite3.connect(f"file:{CDM}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    sec = {(r[0], r[1]): r[2] for r in c.execute("SELECT paper_id, section_id_original, section_text_original FROM section")}
    hits = [json.loads(l) for l in open(OUT / "gazetteer_hits.jsonl", encoding="utf-8")]
    wins = {w["window_id"]: w for w in map(json.loads, open(OUT / "windows.jsonl", encoding="utf-8"))}
    llm, llm_err = load_llm(a.llm_dir)
    stats = Counter()
    stats["windows"], stats["windows_llm_ok"], stats["windows_llm_error"] = len(wins), len(llm), len(llm_err)

    # ---- per paper, per field: evidence items -------------------------------------------------------------------------
    ev = defaultdict(lambda: defaultdict(list))        # (pid, field) -> key -> [evidence dicts]
    cited = defaultdict(list)
    for h in hits:
        ev[(h["paper_id"], h["field"])][(h["family"], h["model"])].append(
            {"source": "gazetteer", "section_id": h["section_id"], "start": h["start"], "end": h["end"], "surface": h["surface"]})
    for wid, j in llm.items():
        pid, sid = j["paper_id"], j["section_id"]
        txt = sec[(pid, sid)]
        for f in FIELDS:
            r = j.get(LLMF[f]) or {}
            for s in r.get("spans", []):
                stats[f"llm_spans_{f}"] += 1
                if not s["verified"]:
                    stats[f"llm_spans_unverified_{f}"] += 1
                    continue
                st, en = s["start"], s["end"]
                surface = txt[st:en]
                gh = G.match(f, surface, base=st)
                if gh:
                    keys = [(x["family"], x["model"]) for x in gh]
                elif re.search(r"[A-Z0-9]", surface) or METHOD_WORD.search(surface):
                    keys = [("OTHER", " ".join(surface.split()))]
                else:
                    stats[f"llm_spans_generic_dropped_{f}"] += 1
                    continue
                for k in keys:
                    ev[(pid, f)][k].append({"source": "llm", "section_id": sid, "start": st, "end": en, "surface": surface,
                                            "window_id": wid})
            if f == "dna_extraction_method" and r.get("status") == "CITED_PROTOCOL" and r.get("cited_verified"):
                cited[pid].append({"source": "llm", "section_id": sid, "start": r["cited_start"], "end": r["cited_end"],
                                   "surface": txt[r["cited_start"]:r["cited_end"]], "window_id": wid})

    paper_vals = {}
    for (pid, f), keys in ev.items():
        items = []
        for k, evs in keys.items():
            g = [e for e in evs if e["source"] == "gazetteer"]
            l_ = [e for e in evs if e["source"] == "llm"]
            agree = any(x["section_id"] == y["section_id"] and x["start"] < y["end"] and y["start"] < x["end"] for x in g for y in l_)
            src = "both_agree" if agree else ("gazetteer_only" if g else "llm_only")
            lv = level(k)
            conf = "high" if src == "both_agree" else ("medium" if lv == "model" else "low")
            items.append({"family": k[0], "model": k[1], "level": lv, "value": display(f, k), "field_source": src,
                          "field_confidence": conf, "evidence": sorted(evs, key=lambda e: (e["source"] != "gazetteer", e["start"]))[:6],
                          "first": min((e["section_id"], e["start"]) for e in evs), "n_gazetteer": len(g), "n_llm": len(l_)})
        # subsumption of family-level keys
        mgroups = {VGROUP.get(i["family"], i["family"]) for i in items if i["level"] == "model"}
        items = [i for i in items if i["level"] == "model" or VGROUP.get(i["family"], i["family"]) not in mgroups]
        items.sort(key=lambda i: i["first"])
        paper_vals[(pid, f)] = items

    # ---- records ----------------------------------------------------------------------------------------------------------
    rows = []
    for r in c.execute("SELECT * FROM assay ORDER BY rowid"):
        r = dict(r)
        pid, at = r["paper_id"], r.get("assay_type_normalized") or r.get("assay_type") or ""
        rs, re_ = r.get("evidence_span_start"), r.get("evidence_span_end")
        if rs is None:
            rs, re_ = r.get("char_start"), r.get("char_end")
        out = {"assay_id": r["assay_id"], "paper_id": pid, "assay_type_normalized": at, "layer": LAYER}
        any_elig = False
        for f in FIELDS:
            old = r.get(f)
            elig = bool((SEQ_ASSAY if f == "sequencing_platform" else DNA_ASSAY).search(at)) or old not in MISSING
            out[f"{f}_old"] = old or ""
            out[f"{f}_eligible"] = elig
            if not elig:
                continue
            any_elig = True
            items = paper_vals.get((pid, f), [])
            scope = "paper"
            if len(items) > 1 and rs is not None:
                near = [i for i in items if any(e["section_id"] == r.get("section_id") and abs(e["start"] - rs) <= REC_WIN + (re_ - rs)
                                                 for e in i["evidence"])]
                if near:
                    items, scope = near, "record_section"
            if items:
                out[f] = "; ".join(i["value"] for i in items)
                out[f"{f}_family"] = "; ".join(dict.fromkeys(i["family"] for i in items))
                out[f"{f}_model"] = "; ".join(i["model"] or "" for i in items)
                out[f"{f}_field_source"] = max((i["field_source"] for i in items), key=SRC_ORDER.index)
                out[f"{f}_field_confidence"] = max((i["field_confidence"] for i in items), key=CONF_ORDER.index)
                out[f"{f}_keys"] = [{k: i[k] for k in ("family", "model", "value", "level", "field_source", "field_confidence")} |
                                    {"evidence": [{k: e[k] for k in ("source", "section_id", "start", "end", "surface")} for e in i["evidence"]]}
                                    for i in items]
                out[f"{f}_record_scope"] = scope
            elif f == "dna_extraction_method" and cited.get(pid):
                e = cited[pid][0]
                out[f] = "CITED_PROTOCOL"
                out[f"{f}_family"] = out[f"{f}_model"] = ""
                out[f"{f}_field_source"] = "llm_only"
                out[f"{f}_field_confidence"] = "low"
                out[f"{f}_keys"] = [{"family": "CITED_PROTOCOL", "model": "", "value": "CITED_PROTOCOL", "level": "none",
                                     "field_source": "llm_only", "field_confidence": "low",
                                     "evidence": [{k: e[k] for k in ("source", "section_id", "start", "end", "surface")}]}]
                out[f"{f}_record_scope"] = "paper"
            else:
                out[f] = "NOT_REPORTED"
                out[f"{f}_family"] = out[f"{f}_model"] = ""
                out[f"{f}_field_source"] = "not_reported"
                out[f"{f}_field_confidence"] = ""
                out[f"{f}_keys"] = []
                out[f"{f}_record_scope"] = "paper"
        if any_elig:
            rows.append(out)

    with open(OUT / "records_v32.jsonl", "w", encoding="utf-8") as fh:
        for o in rows:
            fh.write(json.dumps(o, ensure_ascii=False) + "\n")
    with open(OUT / "paper_values_v32.jsonl", "w", encoding="utf-8") as fh:
        for (pid, f), items in sorted(paper_vals.items()):
            fh.write(json.dumps({"paper_id": pid, "field": f, "layer": LAYER, "values": [{k: v for k, v in i.items() if k != "first"} for i in items]},
                                ensure_ascii=False) + "\n")
        for pid, cs in sorted(cited.items()):
            fh.write(json.dumps({"paper_id": pid, "field": "dna_extraction_method_cited_protocol", "layer": LAYER, "evidence": cs},
                                ensure_ascii=False) + "\n")
    cols = ["assay_id", "paper_id", "assay_type_normalized"] + [f"{f}{s}" for f in FIELDS for s in
                                                                 ("_old", "", "_family", "_model", "_field_source", "_field_confidence", "_record_scope")]
    with open(OUT / "records_v32.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols + ["evidence"], extrasaction="ignore")
        w.writeheader()
        for o in rows:
            evs = []
            for f in FIELDS:
                for k in o.get(f"{f}_keys", []):
                    e = k["evidence"][0]
                    evs.append(f"{f}:{k['value']}@{e['section_id']}:{e['start']}-{e['end']}")
            w.writerow({**o, "evidence": " | ".join(evs)})

    summ = {"layer": LAYER, "gazetteer_version": G.VERSION, "cdm": str(CDM.relative_to(ROOT)), "llm_dir": a.llm_dir,
            "counts": dict(stats), "records_eligible": len(rows), "by_field": {}}
    for f in FIELDS:
        R = [o for o in rows if o[f"{f}_eligible"]]
        pv = [i for (p, ff), items in paper_vals.items() if ff == f for i in items]
        summ["by_field"][f] = {
            "records_eligible": len(R),
            "records_old_nonmissing": sum(o[f"{f}_old"] not in MISSING for o in R),
            "field_source": dict(Counter(o[f"{f}_field_source"] for o in R)),
            "field_confidence": dict(Counter(o[f"{f}_field_confidence"] or "n/a" for o in R)),
            "record_scope": dict(Counter(o[f"{f}_record_scope"] for o in R if o[f] not in ("NOT_REPORTED",))),
            "papers_with_value": len({p for (p, ff), items in paper_vals.items() if ff == f and items}),
            "paper_keys": len(pv), "paper_keys_by_source": dict(Counter(i["field_source"] for i in pv)),
            "paper_keys_by_confidence": dict(Counter(i["field_confidence"] for i in pv)),
            "paper_keys_by_level": dict(Counter(i["level"] for i in pv)),
            "top_values": Counter(i["value"] for i in pv).most_common(25)}
    summ["by_field"]["dna_extraction_method"]["papers_cited_protocol_only"] = sum(
        1 for p in cited if not paper_vals.get((p, "dna_extraction_method")))
    for p in ("records_v32.jsonl", "records_v32.csv", "paper_values_v32.jsonl"):
        summ.setdefault("sha256", {})[p] = hashlib.sha256((OUT / p).read_bytes()).hexdigest()
    (OUT / "combine_summary.json").write_text(json.dumps(summ, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summ.items()}, indent=1, ensure_ascii=False)[:5000])


if __name__ == "__main__":
    main()
