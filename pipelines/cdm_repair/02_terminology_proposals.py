"""Stage B: terminology repair (validity, type, relevance, display label) for all CDM 3.0.3 canonical terms.

1. Deterministic rules flag obvious non-terms first (URLs, e-mails, DOIs, accessions, citations, figure/table labels,
   numbers and statistics, person names with initials, non-Latin script, one-character strings). Each flag carries
   its rule id. These terms are not sent to the model.
2. A local Qwen3.5-9B (vLLM on a cluster GPU; nothing leaves the cluster) judges the remaining terms in batches,
   each with one sentence from a paper that uses it: valid?, type (14 CDM types, ENTITY or UNRESOLVED), relevant to
   human microbiome research (broad scope), cleaned display label.
3. Deterministic validation decides. Vocabulary support (exact name in NCBI Taxonomy, Mondo, HPO or the OMOP index)
   is recorded as evidence and used to confirm or reject type changes and invalid flags:
     FLAG_NOT_A_TERM     rule hit, or model invalid without contrary vocabulary evidence
     KEEP_TYPE / CHANGE_TYPE   with evidence_level VOCAB_CONFIRMED or MODEL_ONLY
     UNRESOLVED          model UNRESOLVED, conflict between model and vocabulary, or no answer
   A display label is accepted only if it uses the term's own letters and digits (it may drop stray characters).
Nothing in the CDM changes; originals stay beside every proposal.

    python 02_terminology_proposals.py build
    python 02_terminology_proposals.py run --shard 0 --nshards 8 [--limit 20]    # gated: stage B (limit = batches)
    python 02_terminology_proposals.py validate
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict

import jsonschema

from common import HERE, connect_ro, load_config, now_iso, require_stage, rp, verify_frozen, write_json
from local_llm import LocalLLM
from repair_runner import fill, load_prompt, provenance, run_items, shard_items
from vocab_verify import norm

PROMPT = "term_repair_v1.md"
TYPES = {"ORGANISM", "CHEMICAL", "DISEASE", "PROTEIN", "DNA_RNA", "CELL_TYPE", "GENOMICS", "PATHWAY", "LAB_METHOD",
         "DATA_ANALYSIS", "SAMPLE_METHOD", "CLINICAL", "EXPERIMENTAL_METHOD", "STUDY_DESIGN", "ENTITY", "UNRESOLVED"}

RULES = [  # (rule id, invalid_reason, compiled pattern) -- conservative: only unambiguous non-terms
    ("url_email_doi", "CITATION_OR_REFERENCE", re.compile(r"https?://|www\.|\S@\S|\bdoi\b|\b10\.\d{4,}/", re.I)),
    ("accession", "CITATION_OR_REFERENCE", re.compile(r"^(PRJ[EDN][A-Z]?\d+|[SED]R[RXSP]\d+|GS[EM]\d+|PMC\d+|[A-Z]{1,2}_?\d{6,}(\.\d)?)$")),
    ("citation", "CITATION_OR_REFERENCE", re.compile(r"\bet al\b|^[A-Z][\w\-]+,? (19|20)\d\d[a-z]?$|\((19|20)\d\d\)")),
    ("figure_table", "CITATION_OR_REFERENCE", re.compile(r"^(supplementa\w*|fig(ure)?s?\.?|tables?|data fig\.?)\s*[\w.\-]*$|^S\d{1,2}[A-Z]?$", re.I)),
    ("number_statistic", "NUMBER_OR_STATISTIC", re.compile(r"^(?=.*\d)[\d\s.,;:%±<>=()+\-−×x/^*~eE]+$|\bp\s*[<=>]\s*0?\.\d|^n\s*=\s*\d", re.I)),
    ("person_initials", "PERSON_OR_ORG", re.compile(r"^[A-Z][a-zà-ÿ]+(?:[-‐][A-Z][a-zà-ÿ]+)? (?![IVXL]+$)[A-Z]{2,3}$|^(?:[A-Z]\.\s?){1,3}[A-Z][a-z]+$")),
    ("non_latin", "GARBLED", re.compile(r"[ᄀ-ᇿ぀-ヿ㄰-㆏一-鿿가-힯]")),
]


def rule_hit(term: str):
    t = (term or "").strip()
    if len(t) <= 1:
        return "too_short", "GARBLED"
    for rid, reason, pat in RULES:
        if pat.search(t):
            return rid, reason
    return None, None


def stage_dir(cfg):
    return rp(cfg["pipeline"]["workspace"]) / "stage_b_terms_qwen"


def db(cfg):
    fi = cfg["frozen_inputs"]["cdm"]
    return connect_ro(rp(fi["dir"]) / fi["database"])


def squash(s):
    return re.sub(r"[^0-9a-z]", "", norm(s))


# --------------------------------------------------------------------------------------------- build
def cmd_build(cfg, args):
    if not verify_frozen(cfg, ("cdm",))["cdm"]["ok"]:
        sys.exit("CDM 3.0.3 manifest does not verify; stopping")
    con = db(cfg)
    ctx = dict(con.execute(
        "SELECT canonical_term_id, mention_row_id FROM (SELECT canonical_term_id, mention_row_id, ROW_NUMBER() OVER "
        "(PARTITION BY canonical_term_id ORDER BY mention_row_id) rn FROM term_mention WHERE canonical_term_id IS NOT NULL "
        "AND supporting_sentence IS NOT NULL AND supporting_sentence <> '') WHERE rn = 1"))
    terms, rule_rows, rules = [], [], Counter()
    for tid, term, ctype in con.execute("SELECT term_id, term, cdm_type FROM canonical_term ORDER BY term_id"):
        rid, reason = rule_hit(term)
        if rid:
            rules[rid] += 1
            rule_rows.append({"term_id": tid, "rule": rid, "invalid_reason": reason})
        else:
            terms.append({"term_id": tid, "term": term, "cdm_type": ctype, "mention_row_id": ctx.get(tid)})
    bs = cfg["stage_b"]["terms_per_request"]
    batches = [{"item_id": f"TB{i // bs:06d}", "terms": terms[i:i + bs]} for i in range(0, len(terms), bs)]
    out = stage_dir(cfg) / "inputs"
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "term_batches.jsonl", "w", encoding="utf-8") as fh:
        for b in batches:
            fh.write(json.dumps(b, ensure_ascii=False) + "\n")
    with open(out / "rule_flags.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["term_id", "rule", "invalid_reason"])
        w.writeheader()
        w.writerows(rule_rows)
    summ = {"built": now_iso(), "terms_total": len(terms) + len(rule_rows), "flagged_by_rules": len(rule_rows),
            "rules": dict(rules), "terms_for_model": len(terms), "batches": len(batches), "terms_per_request": bs,
            "terms_without_sentence": sum(1 for t in terms if not t["mention_row_id"])}
    write_json(out / "build_summary.json", summ)
    print(json.dumps(summ, indent=1))


def load_batches(cfg):
    with open(stage_dir(cfg) / "inputs" / "term_batches.jsonl", encoding="utf-8") as fh:
        return [json.loads(l) for l in fh]


# --------------------------------------------------------------------------------------------- run
def cmd_run(cfg, args):
    require_stage(cfg, "B")
    batches = shard_items(load_batches(cfg), args.shard, args.nshards)
    if args.limit:
        batches = batches[: args.limit]
    system, user_t, psha = load_prompt(PROMPT)
    llm = LocalLLM(cfg, max_tokens=cfg["stage_b"].get("max_tokens"))
    served = llm.served_model()
    con = db(cfg)

    def sentence(mid):
        if mid is None:
            return "(no sentence available)"
        r = con.execute("SELECT supporting_sentence FROM term_mention WHERE mention_row_id = ?", (mid,)).fetchone()
        s = " ".join((r[0] if r else "").split())
        return s[:400] or "(no sentence available)"

    def render(b):
        lines = [f'{i}. TERM: "{t["term"]}" | TYPE: {t["cdm_type"]} | SENTENCE: {sentence(t["mention_row_id"])}'
                 for i, t in enumerate(b["terms"], 1)]
        return system, fill(user_t, items="\n".join(lines))

    out = stage_dir(cfg) / "runs" / f"shard_{args.shard:03d}_of_{args.nshards:03d}.jsonl"
    res = run_items(batches, "item_id", render, llm, out, cfg["local_llm"]["parallel"], {"prompt_sha256": psha, "model": served})
    write_json(out.with_suffix(".provenance.json"), provenance(cfg, "B", psha, served, {"result": res, "shard": args.shard,
                                                                                         "nshards": args.nshards, "limit": args.limit}))
    print(json.dumps(res))


# --------------------------------------------------------------------------------------------- validate
class VocabNames:
    """Exact (normalised) name lookup used as evidence for types: NCBI Taxonomy, Mondo, HPO, OMOP index."""

    def __init__(self, cfg, wanted: set[str]):
        v = cfg["other_inputs"]["vocabularies"]
        self.hit = defaultdict(set)
        with open(rp(v["ncbi_taxonomy_names"]), encoding="utf-8") as fh:
            for line in fh:
                p = line.split("\t|\t")
                n = norm(p[1])
                if n in wanted:
                    self.hit[n].add("NCBITaxon")
        for key, path in (("MONDO", v["mondo"]), ("HPO", v["hpo"])):
            with open(rp(path), encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("name: "):
                        n = norm(line[6:].strip())
                    elif line.startswith("synonym: "):
                        m = re.match(r'synonym: "(.*?)" EXACT', line)
                        n = norm(m.group(1)) if m else None
                    else:
                        continue
                    if n in wanted:
                        self.hit[n].add(key)
        om = sqlite3.connect(f"file:{rp(cfg['local_vocab']['omop_index'])}?mode=ro", uri=True)
        for n in wanted:
            for (dom,) in om.execute("SELECT DISTINCT c.domain_id FROM term t JOIN concept c ON c.concept_id = t.concept_id "
                                     "WHERE t.norm = ? LIMIT 5", (n,)):
                self.hit[n].add("OMOP:" + (dom or ""))

    TYPE_SUPPORT = {"ORGANISM": {"NCBITaxon"}, "DISEASE": {"MONDO", "HPO", "OMOP:Condition"},
                    "CHEMICAL": {"OMOP:Drug"}, "CLINICAL": {"OMOP:Measurement", "OMOP:Observation", "OMOP:Procedure", "HPO"},
                    "LAB_METHOD": {"OMOP:Procedure", "OMOP:Measurement"}, "EXPERIMENTAL_METHOD": {"OMOP:Procedure"}}

    def support(self, term):
        return self.hit.get(norm(term), set())

    def types_supported(self, term):
        s = self.support(term)
        return {t for t, srcs in self.TYPE_SUPPORT.items() if s & srcs}


def cmd_validate(cfg, args):
    sd = stage_dir(cfg)
    batches = load_batches(cfg)
    schema = json.load(open(HERE / "schemas" / "term_judgement.schema.json"))
    val = jsonschema.Draft202012Validator({k: v for k, v in schema.items() if k != "properties"} | {"properties": {"items": {"type": "array"}}})
    item_val = jsonschema.Draft202012Validator(schema["properties"]["items"]["items"])   # each answer checked on its own
    resp = {}
    for f in sorted((sd / "runs").glob("shard_*.jsonl")):
        for line in open(f, encoding="utf-8"):
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("response") is not None or r["item_id"] not in resp:
                resp[r["item_id"]] = r
    con = db(cfg)
    all_terms = {t: (term, ct) for t, term, ct in con.execute("SELECT term_id, term, cdm_type FROM canonical_term")}
    vocab = VocabNames(cfg, {norm(t) for t, _ in all_terms.values()})
    rows, dec = [], Counter()
    with open(sd / "inputs" / "rule_flags.csv", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            term, ct = all_terms[r["term_id"]]
            sup = vocab.support(term)
            d = ("UNRESOLVED", "rule_flag_but_vocab_name") if sup else ("FLAG_NOT_A_TERM", "rule:" + r["rule"])
            rows.append(dict(term_id=r["term_id"], term=term, type_original=ct, valid=False, invalid_reason=r["invalid_reason"],
                             type_proposed=None, relevant=None, display_label=None, vocab_support=";".join(sorted(sup)),
                             evidence_level="RULE", decision=d[0], reason=d[1], model=None))
    for b in batches:
        r = resp.get(b["item_id"])
        ans = {}
        if r and r.get("response") is not None and not list(val.iter_errors(r["response"])):
            ans = {a["n"]: a for a in r["response"]["items"]
                   if isinstance(a, dict) and isinstance(a.get("n"), int) and not list(item_val.iter_errors(a))}
        for i, t in enumerate(b["terms"], 1):
            a, sup = ans.get(i), vocab.support(t["term"])
            row = dict(term_id=t["term_id"], term=t["term"], type_original=t["cdm_type"], valid=None, invalid_reason=None,
                       type_proposed=None, relevant=None, display_label=None, vocab_support=";".join(sorted(sup)),
                       evidence_level=None, decision=None, reason=None, model=r.get("model") if r else None)
            if r is None:
                row.update(decision="NOT_PROCESSED", reason="no_model_answer_yet")
            elif a is None:
                row.update(decision="UNRESOLVED", reason="no_valid_answer_for_item")
            else:
                row.update(valid=a["valid"], invalid_reason=a.get("invalid_reason"), type_proposed=a["type"],
                           relevant=a["relevant"])
                lab = a.get("display_label")
                if lab:
                    q, tq = squash(lab), squash(t["term"])
                    row["display_label"] = lab if (q and q in tq and len(q) >= 0.6 * len(tq)) else None
                if not a["valid"]:
                    row.update(decision="UNRESOLVED" if sup else "FLAG_NOT_A_TERM",
                               reason="model_invalid_but_vocab_name" if sup else "model_invalid", evidence_level="MODEL")
                elif a["type"] == "UNRESOLVED":
                    row.update(decision="UNRESOLVED", reason="type_unresolved", evidence_level="MODEL")
                else:
                    supported = vocab.types_supported(t["term"])
                    new, old = a["type"], t["cdm_type"]
                    level = "VOCAB_CONFIRMED" if new in supported else "MODEL_ONLY"
                    if new == old:
                        row.update(decision="KEEP_TYPE", reason="model_keeps_type", evidence_level=level)
                    elif old in supported and new not in supported:
                        row.update(decision="UNRESOLVED", reason="vocab_supports_original_type", evidence_level="CONFLICT")
                    else:
                        row.update(decision="CHANGE_TYPE", reason=f"{old}->{new}", evidence_level=level)
            rows.append(row)
    for r_ in rows:
        dec[(r_["decision"], r_["evidence_level"])] += 1
    out = sd / "validation"
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "TERM_DECISIONS.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    answered = [r_ for r_ in rows if r_["decision"] not in ("NOT_PROCESSED",)]
    summ = {"validated": now_iso(), "terms": len(rows), "answered_or_rule": len(answered),
            "decisions": {f"{a}|{b}": n for (a, b), n in sorted(dec.items(), key=lambda x: -x[1])},
            "valid_true": sum(1 for r_ in rows if r_["valid"] is True),
            "relevant_true": sum(1 for r_ in rows if r_["relevant"] is True),
            "type_changes": dict(Counter(r_["reason"] for r_ in rows if r_["decision"] == "CHANGE_TYPE").most_common(30)),
            "display_labels_accepted": sum(1 for r_ in rows if r_["display_label"]),
            "note": "Decisions pass implemented checks; MODEL_ONLY type changes have no vocabulary confirmation."}
    write_json(out / "summary.json", summ)
    print(json.dumps(summ, indent=1))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    r = sub.add_parser("run")
    r.add_argument("--shard", type=int, default=0)
    r.add_argument("--nshards", type=int, default=1)
    r.add_argument("--limit", type=int, default=0)
    r.add_argument("--array-task", type=int, default=None)
    sub.add_parser("validate")
    args = ap.parse_args()
    if getattr(args, "array_task", None) is not None:
        args.shard = args.array_task
    cfg = load_config()
    {"build": cmd_build, "run": cmd_run, "validate": cmd_validate}[args.cmd](cfg, args)


if __name__ == "__main__":
    main()
