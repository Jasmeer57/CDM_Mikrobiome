"""Controlled vocabularies for the cleaned catalogue (Phase C of
docs/catalogue_cleanup_plan.md). Deterministic rules, plus a cached exact-name
lookup of taxa in NCBI Taxonomy.

Reads the Phase B (linked) output and writes a new directory; the input is not modified.
Original values are never overwritten — every normalised value goes into a new
column next to the original:

  samples   body_site_normalized / _ontology_id / _status
            sample_type_normalized / _normalization_status / _normalization_reason
            (the frozen release's own normaliser, imported read-only)
  findings  body_site_normalized / _ontology_id / _status,
            finding_domain_normalized, taxonomic_rank_normalized,
            taxon_ncbi_ids, taxon_ncbi_names, taxon_link_status
  assays    assay_type_normalized, assay_class
  datasets  repository_normalized

Rules live in src/configs/catalogue_vocab/vocab.yaml (ordered; first match
wins). Values no rule matches stay blank and go to review_vocab_unmapped.csv.

Taxa: each name in `taxon_or_feature` (for taxonomic ranks only) is looked up
by exact scientific name, then by exact synonym, in NCBI Taxonomy (E-utilities).
Only a single unambiguous hit is accepted. Results are cached in
src/configs/catalogue_vocab/ncbi_taxon_cache.json, so reruns are offline;
`--offline` uses the cache only. NCBI_API_KEY is used if set.

Usage:
    python src/scripts/vllm_termpop/normalize_catalogue_vocab.py \
        [--input_dir outputs/results/catalogue_v3_linked] \
        [--output_dir outputs/results/catalogue_v3_vocab] [--offline] [--verify_ids]
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

import yaml

csv.field_size_limit(sys.maxsize)

REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
VOCAB_DIR = REPO_ROOT / "src/configs/catalogue_vocab"
SAMPLE_TYPE_NORMALIZER = REPO_ROOT / "releases/data_catalogue/scripts/normalize_sample_types.py"
ENTITIES = ("datasets", "data_assets", "cohorts", "samples", "assays", "findings")

NEW_COLUMNS = {
    "samples": ["body_site_normalized", "body_site_ontology_id", "body_site_status",
                "sample_type_normalized", "sample_type_normalization_status",
                "sample_type_normalization_reason"],
    "findings": ["body_site_normalized", "body_site_ontology_id", "body_site_status",
                 "finding_domain_normalized", "taxonomic_rank_normalized",
                 "taxon_ncbi_ids", "taxon_ncbi_names", "taxon_link_status"],
    "assays": ["assay_type_normalized", "assay_class"],
    "datasets": ["repository_normalized"],
}
TAXON_RANKS = {"superkingdom", "phylum", "class", "order", "family", "genus", "species", "strain"}


# ── rule tables ──────────────────────────────────────────────────────────────
class Vocab:
    def __init__(self, path):
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        self.raw = raw
        self.rules = {field: [dict(r, rx=re.compile(r["re"], re.I)) for r in spec["rules"]]
                      for field, spec in raw.items() if isinstance(spec, dict) and "rules" in spec}
        bs = raw["body_site"]
        self.bs_strip = re.compile(bs["strip"], re.I)
        self.bs_non_human = re.compile(bs["non_human"], re.I)
        self.repo_from_acc = raw["repository_name"]["from_accession_type"]

    def first(self, field, value):
        for r in self.rules[field]:
            if r["rx"].search(value):
                return r
        return None

    def body_site(self, value):
        """-> (label, ontology id, status)"""
        v = str(value or "").strip().lower()
        if not v:
            return "", "", "EMPTY"
        if self.bs_non_human.search(v):
            return "", "", "NON_HUMAN"
        stripped = re.sub(r"\s+", " ", self.bs_strip.sub(" ", v)).strip()
        r = self.first("body_site", stripped or v)
        return (r["label"], r["id"], "NORMALIZED") if r else ("", "", "UNMAPPED")

    def assay(self, value):
        v = str(value or "").strip().lower().replace("_", " ")
        if not v:
            return "", ""
        r = self.first("assay_type", v)
        return (r["label"], r["class"]) if r else ("", "")

    def repository(self, name, accession_type):
        v = str(name or "").strip().lower()
        r = self.first("repository_name", v) if v else None
        if r and r["label"] != "NCBI (unspecified database)":
            return r["label"]
        for t in str(accession_type or "").split("; "):
            if t in self.repo_from_acc:
                return self.repo_from_acc[t]
        return r["label"] if r else ""

    def simple(self, field, value):
        v = str(value or "").strip().lower().replace("_", " ")
        if not v:
            return ""
        r = self.first(field, v)
        return r["label"] if r else ""


def load_sample_type_normalizer():
    """The frozen release's normalize() — imported read-only, never run as main."""
    spec = importlib.util.spec_from_file_location("normalize_sample_types", SAMPLE_TYPE_NORMALIZER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.normalize


# ── taxa ─────────────────────────────────────────────────────────────────────
_TAX_JUNK = re.compile(
    r"\b(unclassified|uncultured|unidentified|unknown|norank|incertae sedis|members? of|"
    r"the|genus|genera|family|families|phylum|phyla|order|class|species|spp?|"
    r"relative abundance of|abundance of|levels? of|bacteria|bacterium)\b\.?", re.I)
_PREFIX = re.compile(r"\b[kpcofgs]__", re.I)
_LEAD = re.compile(r"^(?:(?:a|an|as well as|from|especially|including|in|of|e\.?g\.?|such as|"
                   r"both|all|other|several|some|most|many|certain|only|also|whereas|while|"
                   r"with|by|to)\s+)+", re.I)
_TRAIL = re.compile(r"(?:\s+(?:taxa|strains?|members|isolates?|lineages?|phylotypes?|"
                    r"otus?|asvs?|reads|abundance|levels?))+$", re.I)
# Microbial NCBI esummary divisions: a homonym in one of these wins over a
# plant/animal one (Rothia the bacterium vs the moth and the legume). NCBI
# animal divisions are too varied ("walking sticks", "salamanders") to exclude.
_MICROBE_DIVISIONS = ("bacteria", "proteobacteria", "firmicutes", "archaea", "virus", "phage",
                      "fung", "ascomycete", "basidiomycete", "yeast", "spirochete", "chlamydia",
                      "mycoplasma", "enterobacteria", "cfb group", "gram-", "fusobacteria",
                      "verrucomicrobia", "cyanobacteria", "tenericutes")
_SKIP = re.compile(r"^(otus?|asvs?|taxa|microbiota|microbiome|community|total|others?|"
                   r"genera|species|bacteria)$", re.I)


def taxon_candidates(text):
    """Split a taxon_or_feature cell into clean candidate scientific names."""
    out = []
    for part in re.split(r",|;|/|\band\b|&|\bvs\.?\b", str(text or "")):
        p = _PREFIX.sub("", part)
        p = re.sub(r"\(.*?\)|\[|\]", " ", p)
        p = _TAX_JUNK.sub(" ", p)
        p = re.sub(r"[^A-Za-z0-9 .-]", " ", p)
        p = re.sub(r"\s+", " ", p).strip(" .-")
        p = _TRAIL.sub("", _LEAD.sub("", p)).strip(" .-")
        if (len(p) < 3 or _SKIP.match(p) or re.match(r"^[A-Za-z]\.\s", p)
                or not p[0].isalpha() or len(p.split()) > 4 or any(c.isdigit() for c in p[:3])):
            continue
        out.append(p[0].upper() + p[1:].lower() if len(p.split()) > 1 else p.capitalize())
    return list(dict.fromkeys(out))


class NCBITaxonomy:
    EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"

    def __init__(self, cache_path, offline=False, renamed=None):
        self.cache_path = Path(cache_path)
        self.cache = (json.loads(self.cache_path.read_text(encoding="utf-8"))
                      if self.cache_path.exists() else {})
        # entries from before candidates were stored cannot be resolved by rank
        self.cache = {k: v for k, v in self.cache.items()
                      if not (v.get("status") == "AMBIGUOUS" and "candidates" not in v)}
        self.renamed = {k.lower(): v for k, v in (renamed or {}).items()}
        self.offline = offline
        self.key = os.environ.get("NCBI_API_KEY") or os.environ.get("ENTREZ_API_KEY")
        self.delay = 0.11 if self.key else 0.35
        self._last = 0.0
        self.new = 0

    def _get(self, endpoint, params):
        params = dict(params, tool="cdm_catalogue_vocab", retmode="json")
        if self.key:
            params["api_key"] = self.key
        url = self.EUTILS + endpoint + "?" + urllib.parse.urlencode(params)
        for attempt in range(4):
            wait = self.delay - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
            try:
                with urllib.request.urlopen(url, timeout=30) as resp:
                    return json.loads(resp.read())
            except Exception:  # noqa: BLE001 — retry, then report failure
                time.sleep(2 ** attempt)
        return None

    def lookup(self, name, rank=""):
        """-> {"status", "taxid", "name", "rank"} for one name.

        Renamed species are mapped to their current name first (curated table);
        a name with several hits is resolved by the finding's stated rank, then
        by preferring microbes over plants/animals; a strain-level name that is
        not found falls back to its first two words (the species).
        """
        current = self.renamed.get(name.lower())
        if current:
            res = dict(self._raw(current))
            if res.get("taxid"):
                res["status"] = "CURATED_RENAME"
            return self._resolve(res, rank)
        res = self._resolve(self._raw(name), rank)
        words = name.split()
        if res["status"] == "NOT_FOUND" and len(words) >= 3:
            sp = self._resolve(self._raw(" ".join(words[:2])), "species")
            if sp.get("taxid"):
                return dict(sp, status="SPECIES_OF_STRAIN")
        return res

    @staticmethod
    def _resolve(res, rank):
        if res.get("status") != "AMBIGUOUS":
            return res
        cands = res.get("candidates") or []
        pick = [c for c in cands if rank and c.get("rank") == rank] or cands
        micro = [c for c in pick if any(m in (c.get("division") or "").lower()
                                        for m in _MICROBE_DIVISIONS)]
        pick = micro or pick
        if len(pick) == 1:
            return dict(pick[0], status="DISAMBIGUATED")
        return res

    def _raw(self, name):
        """Exact scientific name, then exact any-name; cached per name."""
        if name in self.cache:
            return self.cache[name]
        if self.offline:
            return {"status": "NOT_LOOKED_UP"}
        res = None
        for field, how in (("Scientific Name", "SCIENTIFIC_NAME"), ("All Names", "SYNONYM")):
            data = self._get("esearch.fcgi", {"db": "taxonomy", "term": f'"{name}"[{field}]'})
            if data is None or "esearchresult" not in data:
                return {"status": "LOOKUP_FAILED"}  # not cached: retried next run
            ids = data["esearchresult"].get("idlist", [])
            if len(ids) == 1:
                res = {"status": how, "taxid": ids[0]}
                break
            if len(ids) > 1:
                res = {"status": "AMBIGUOUS", "candidates": [{"taxid": i} for i in ids[:10]]}
                break
        if res is None:
            res = {"status": "NOT_FOUND"}
        ids = [res["taxid"]] if "taxid" in res else [c["taxid"] for c in res.get("candidates", [])]
        if ids:
            summ = self._get("esummary.fcgi", {"db": "taxonomy", "id": ",".join(ids)})
            docs = (summ or {}).get("result", {})
            if summ is None:
                return {"status": "LOOKUP_FAILED"}
            meta = {i: {"taxid": i, "name": docs.get(i, {}).get("scientificname", ""),
                        "rank": docs.get(i, {}).get("rank", ""),
                        "division": docs.get(i, {}).get("division", "")} for i in ids}
            if "taxid" in res:
                res.update(meta[res["taxid"]])
            else:
                res["candidates"] = list(meta.values())
        self.cache[name] = res
        self.new += 1
        if self.new % 100 == 0:
            self.save()
        return res

    def save(self):
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.cache_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.cache, indent=0, sort_keys=True), encoding="utf-8")
        tmp.replace(self.cache_path)


def link_taxa(f, ncbi):
    names = taxon_candidates(f.get("taxon_or_feature"))
    if not names:
        return "", "", "NO_TAXON_NAME"
    ids, labels, statuses = [], [], Counter()
    rank = f.get("taxonomic_rank_normalized", "")
    for n in names:
        res = ncbi.lookup(n, "" if rank == "strain" else rank)
        statuses[res["status"]] += 1
        if res.get("taxid"):
            ids.append("NCBITaxon:" + res["taxid"])
            labels.append(res.get("name") or n)
    if ids and len(ids) == len(names):
        status = "LINKED"
    elif ids:
        status = "PARTIAL"
    else:
        status = statuses.most_common(1)[0][0]
    return "; ".join(dict.fromkeys(ids)), "; ".join(dict.fromkeys(labels)), status


# ── ontology id check ────────────────────────────────────────────────────────
def verify_ids(vocab, out_path):
    """Check every body-site CURIE against EBI OLS: label or synonym must match."""
    results, bad = [], 0
    for r in vocab.raw["body_site"]["rules"]:
        curie, label = r["id"], r["label"]
        onto = curie.split(":")[0].lower()
        url = ("https://www.ebi.ac.uk/ols4/api/ontologies/%s/terms?obo_id=%s"
               % (onto, urllib.parse.quote(curie)))
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                term = json.loads(resp.read())["_embedded"]["terms"][0]
            names = {term["label"].lower()} | {s.lower() for s in term.get("synonyms") or []}
            ok = label.lower() in names
            results.append({"id": curie, "our_label": label, "ols_label": term["label"], "ok": ok})
        except Exception as ex:  # noqa: BLE001
            ok = False
            results.append({"id": curie, "our_label": label, "error": repr(ex), "ok": False})
        bad += not ok
    Path(out_path).write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    return bad, results


# ── main ─────────────────────────────────────────────────────────────────────
def main(argv=None):
    ap = argparse.ArgumentParser(description="Phase C controlled vocabularies")
    ap.add_argument("--input_dir", default=str(REPO_ROOT / "outputs/results/catalogue_v3_linked"))
    ap.add_argument("--output_dir", default=str(REPO_ROOT / "outputs/results/catalogue_v3_vocab"))
    ap.add_argument("--vocab", default=str(VOCAB_DIR / "vocab.yaml"))
    ap.add_argument("--taxon_cache", default=str(VOCAB_DIR / "ncbi_taxon_cache.json"))
    ap.add_argument("--offline", action="store_true", help="NCBI cache only, no network")
    ap.add_argument("--verify_ids", action="store_true",
                    help="check body-site ontology ids against EBI OLS and stop")
    args = ap.parse_args(argv)

    vocab = Vocab(args.vocab)
    if args.verify_ids:
        bad, results = verify_ids(vocab, VOCAB_DIR / "ontology_id_check.json")
        for r in results:
            print(("OK  " if r["ok"] else "BAD ") + f"{r['id']:16s} {r['our_label']:36s} {r.get('ols_label', r.get('error'))}")
        return 1 if bad else 0

    t0 = time.time()
    in_dir, out_dir = Path(args.input_dir), Path(args.output_dir)
    if out_dir.resolve() == in_dir.resolve():
        sys.exit("refusing to write into the input directory")
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(in_dir / "catalogue_records.jsonl", encoding="utf-8") as fh:
        records = [json.loads(line) for line in fh if line.strip()]
    headers = {}
    for e in ENTITIES:
        with open(in_dir / f"catalogue_{e}.csv", newline="", encoding="utf-8") as fh:
            headers[e] = next(csv.reader(fh))
    print(f"loaded {len(records)} records from {in_dir}")

    normalize_sample_type = load_sample_type_normalizer()
    ncbi = NCBITaxonomy(args.taxon_cache, offline=args.offline,
                        renamed=vocab.raw.get("renamed_taxa", {}))
    unmapped = Counter()
    stats = defaultdict(Counter)

    todo_taxa = sum(1 for r in records if r["entity_type"] == "findings")
    for i, r in enumerate(records):
        e, f = r["entity_type"], r["fields"]
        if e in ("samples", "findings"):
            label, oid, status = vocab.body_site(f.get("body_site"))
            f.update(body_site_normalized=label, body_site_ontology_id=oid, body_site_status=status)
            stats[f"{e}.body_site"][status] += 1
            if status == "UNMAPPED":
                unmapped[(f"{e}.body_site", str(f["body_site"]).strip().lower())] += 1
        if e == "samples":
            norm, status, reason = normalize_sample_type(str(f.get("sample_type") or ""))
            f.update(sample_type_normalized=norm, sample_type_normalization_status=status,
                     sample_type_normalization_reason=reason)
            stats["samples.sample_type"][status] += 1
        elif e == "assays":
            label, klass = vocab.assay(f.get("assay_type"))
            f.update(assay_type_normalized=label, assay_class=klass)
            stats["assays.assay_class"][klass or ("UNMAPPED" if str(f.get("assay_type", "")).strip() else "EMPTY")] += 1
            if not label and str(f.get("assay_type", "")).strip():
                unmapped[("assays.assay_type", str(f["assay_type"]).strip().lower())] += 1
        elif e == "datasets":
            f["repository_normalized"] = vocab.repository(f.get("repository_name"), f.get("accession_type"))
            stats["datasets.repository"]["NORMALIZED" if f["repository_normalized"] else
                                         ("UNMAPPED" if str(f.get("repository_name", "")).strip() else "EMPTY")] += 1
            if not f["repository_normalized"] and str(f.get("repository_name", "")).strip():
                unmapped[("datasets.repository_name", str(f["repository_name"]).strip().lower())] += 1
        elif e == "findings":
            f["finding_domain_normalized"] = vocab.simple("finding_domain", f.get("finding_domain"))
            f["taxonomic_rank_normalized"] = vocab.simple("taxonomic_rank", f.get("taxonomic_rank"))
            for fld in ("finding_domain", "taxonomic_rank"):
                if not f[f"{fld}_normalized"] and str(f.get(fld, "")).strip():
                    unmapped[(f"findings.{fld}", str(f[fld]).strip().lower())] += 1
            stats["findings.finding_domain"][f["finding_domain_normalized"] or "(blank)"] += 1
            if f["taxonomic_rank_normalized"] in TAXON_RANKS:
                ids, names, status = link_taxa(f, ncbi)
            else:
                ids, names, status = "", "", "NOT_A_TAXON_RANK"
            f.update(taxon_ncbi_ids=ids, taxon_ncbi_names=names, taxon_link_status=status)
            stats["findings.taxon_link"][status] += 1
        if (i + 1) % 5000 == 0:
            print(f"  {i + 1}/{len(records)} records; NCBI new lookups {ncbi.new}", flush=True)
    ncbi.save()

    for r in records:
        r["vocab_file"] = Path(args.vocab).name
    with open(out_dir / "catalogue_records.jsonl", "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    for e in ENTITIES:
        cols = headers[e] + [c for c in NEW_COLUMNS.get(e, []) if c not in headers[e]]
        with open(out_dir / f"catalogue_{e}.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(r["fields"] for r in records if r["entity_type"] == e)
    # carry the Phase A side files forward unchanged
    for name in ("catalogue_papers.csv", "_removed.jsonl", "_v2_to_v3_map.csv", "_link_report.json"):
        src = in_dir / name
        if src.exists():
            (out_dir / name).write_bytes(src.read_bytes())
    with open(out_dir / "review_vocab_unmapped.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["field", "value", "rows"])
        for (fld, val), n in sorted(unmapped.items(), key=lambda kv: (kv[0][0], -kv[1])):
            w.writerow([fld, val, n])

    report = {"input_dir": str(in_dir), "output_dir": str(out_dir), "records": len(records),
              "papers": len({r["paper_id"] for r in records}),
              "vocab": str(Path(args.vocab).relative_to(REPO_ROOT)),
              "ncbi_cache_entries": len(ncbi.cache), "ncbi_new_lookups": ncbi.new,
              "stats": {k: dict(v.most_common()) for k, v in sorted(stats.items())},
              "unmapped_distinct_values": len(unmapped),
              "elapsed_s": round(time.time() - t0, 1)}
    (out_dir / "_vocab_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_markdown(report, out_dir / "VOCAB_REPORT.md")
    print(json.dumps(report["stats"], indent=1))
    print(f"wrote {out_dir} in {report['elapsed_s']}s")
    return 0


def write_markdown(rep, path):
    L = [f"# Catalogue vocabularies — Phase C", "",
         f"Input `{rep['input_dir']}` → output `{rep['output_dir']}`. "
         f"{rep['records']:,} records over {rep['papers']} papers. Rules: `{rep['vocab']}`. "
         "Original values are untouched; normalised values are in new columns.", ""]
    for field, counts in rep["stats"].items():
        total = sum(counts.values())
        L += [f"## {field}", "", "| value | rows | % |", "|---|---:|---:|"]
        L += [f"| {k} | {v:,} | {100 * v / total:.1f}% |" for k, v in counts.items()]
        L.append("")
    L += ["## Notes", "",
          "- Body-site ids are UBERON/CL CURIEs checked against EBI OLS "
          "(`src/configs/catalogue_vocab/ontology_id_check.json`).",
          "- Taxa: exact scientific-name or exact-synonym match in NCBI Taxonomy; only "
          "a single unambiguous hit is accepted. Abbreviated names (`F. prausnitzii`) are "
          "not expanded and stay unlinked.",
          "- Assay types, repositories and finding domains get controlled labels only "
          "(no ontology ids).",
          f"- {rep['unmapped_distinct_values']:,} distinct values matched no rule: "
          "`review_vocab_unmapped.csv`.", ""]
    path.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
