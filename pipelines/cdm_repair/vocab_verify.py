"""Deterministic, local verification of vocabulary identifiers (no network, no model).

Routes by identifier form:
  NCBITaxon:<id>                      -> NCBI Taxonomy names.dmp / merged.dmp / delnodes.dmp
  .../obo/MONDO_<n>, .../obo/HP_<n>   -> mondo.obo, hp.obo (obsolete flags respected)
  .../obo/NCIT_<code>                 -> OMOP index, vocabulary NCIt
  MeSH code (mesh service, or .../MESH/<code>) -> OMOP index, vocabulary MeSH
  .../SNOMEDCT/<code>                 -> OMOP index, vocabulary SNOMED
  numeric OMOP concept_id (omop service) -> OMOP index
  anything else (UMLS CUIs, DOID, other OLS/BioPortal ontologies) -> NOT_VERIFIABLE (no local copy)

Status: VERIFIED, OBSOLETE (merged/deleted/obsolete), NOT_FOUND, NOT_VERIFIABLE.
Label match of the stored concept label and of the term against the vocabulary's names (which include synonyms):
EXACT, NORMALISED, NONE (or NOT_CHECKED when the identifier is not verifiable).
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from collections import defaultdict

from common import rp, sha256_file


def norm(s: str | None) -> str:
    s = unicodedata.normalize("NFKC", s or "").casefold()
    s = re.sub(r"[\s_\-/,;:()\[\]'\"]+", " ", s)
    return " ".join(s.split())


def route(concept_id: str, service: str | None) -> tuple[str, str]:
    cid, svc = concept_id or "", (service or "").lower()
    if cid.startswith("NCBITaxon:"):
        return "ncbi_taxonomy", cid.split(":", 1)[1]
    m = re.search(r"/obo/NCBITaxon_(\d+)$", cid) or re.search(r"/ontology/NCBITAXON/(\d+)$", cid)
    if m:
        return "ncbi_taxonomy", m.group(1)
    m = re.search(r"snomed\.info/id/(\d+)$", cid)
    if m:
        return "omop:SNOMED", m.group(1)
    m = re.search(r"/ontology/LNC/((?:LA|LP|LG)?\d+-\d)$", cid)
    if m:
        return "omop:LOINC", m.group(1)
    m = re.search(r"/ontology/RXNORM/(\d+)$", cid)
    if m:
        return "omop:RxNorm", m.group(1)
    m = re.search(r"id\.nlm\.nih\.gov/mesh/([CDQ]\d+)$", cid)
    if m:
        return "omop:MeSH", m.group(1)
    m = re.search(r"Thesaurus\.owl#(C\d+)$", cid)
    if m:
        return "omop:NCIt", m.group(1)
    m = re.search(r"/obo/(MONDO|HP|NCIT)_(\w+)$", cid)
    if m:
        return {"MONDO": "mondo", "HP": "hpo", "NCIT": "omop:NCIt"}[m.group(1)], (
            f"{m.group(1)}:{m.group(2)}" if m.group(1) != "NCIT" else m.group(2))
    m = re.search(r"/ontology/MESH/(\w+)$", cid)
    if m:
        return "omop:MeSH", m.group(1)
    m = re.search(r"/ontology/SNOMEDCT/(\w+)$", cid)
    if m:
        return "omop:SNOMED", m.group(1)
    if svc == "mesh" and re.fullmatch(r"[CD]\d+", cid):
        return "omop:MeSH", cid
    if svc == "omop" and cid.isdigit():
        return "omop:concept_id", cid
    return "not_verifiable", cid


class Verifier:
    """Load only what the candidate set needs (lazy, per route)."""

    def __init__(self, cfg: dict, needed: dict[str, set[str]]):
        v = cfg["other_inputs"]["vocabularies"]
        self.versions, self.tax, self.obo = {}, {}, {}
        if needed.get("ncbi_taxonomy"):
            self._load_taxonomy(v, needed["ncbi_taxonomy"])
        for key, path in (("mondo", v["mondo"]), ("hpo", v["hpo"])):
            if needed.get(key):
                self.obo[key] = self._load_obo(rp(path), needed[key])
                self.versions[key] = self._obo_version(rp(path))
        self.omop = None
        if any(k.startswith("omop:") for k, ids in needed.items() if ids):
            p = rp(cfg["local_vocab"]["omop_index"])
            self.omop = self._load_omop(p, needed)
            self.versions["omop"] = f"omop_index.sqlite size {p.stat().st_size}"

    @staticmethod
    def _load_omop(path, needed):
        """One sequential pass over concept and term (the index has no (vocabulary_id, concept_code) or
        term(concept_id) index, so per-identifier queries would each scan ~10M rows)."""
        want_code = {(k.split(":", 1)[1], c) for k, ids in needed.items() if k.startswith("omop:")
                     and k != "omop:concept_id" for c in ids}
        want_id = {int(c) for c in needed.get("omop:concept_id", ()) if c.isdigit()}
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        con.execute("PRAGMA query_only = ON")
        by_code, by_id = defaultdict(set), {}
        for cid, name, vocab, code in con.execute("SELECT concept_id, name, vocabulary_id, concept_code FROM concept"):
            if (vocab, code) in want_code:
                by_code[(vocab, code)].add(cid)
            if cid in want_id or (vocab, code) in want_code:
                by_id.setdefault(cid, set()).add(name)
        for n, cid in con.execute("SELECT norm, concept_id FROM term"):
            if cid in by_id and len(by_id[cid]) < 60:
                by_id[cid].add(n)
        con.close()
        return {"by_code": by_code, "names": by_id}

    def _load_taxonomy(self, v, ids):
        names = defaultdict(set)
        with open(rp(v["ncbi_taxonomy_names"]), encoding="utf-8") as fh:
            for line in fh:
                tid, name = line.split("\t|\t", 2)[:2]
                if tid in ids:
                    names[tid].add(name)
        merged, deleted = {}, set()
        with open(rp(v["ncbi_taxonomy_merged"]), encoding="utf-8") as fh:
            for line in fh:
                a, b = line.split("\t|\t")[:2]
                if a in ids:
                    merged[a] = b.strip("\t|\n ")
        with open(rp(v["ncbi_taxonomy_deleted"]), encoding="utf-8") as fh:
            for line in fh:
                a = line.split("\t|")[0].strip()
                if a in ids:
                    deleted.add(a)
        self.tax = {"names": names, "merged": merged, "deleted": deleted}
        self.versions["ncbi_taxonomy"] = "names.dmp sha256 " + sha256_file(rp(v["ncbi_taxonomy_names"]))[:12]

    @staticmethod
    def _obo_version(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("data-version:"):
                    return line.split(":", 1)[1].strip()
                if line.startswith("[Term]"):
                    break
        return "unknown"

    @staticmethod
    def _load_obo(path, ids):
        out, cur = {}, None
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.rstrip("\n")
                if line == "[Term]":
                    cur = None
                elif line.startswith("id: "):
                    i = line[4:]
                    cur = out.setdefault(i, {"names": set(), "obsolete": False}) if i in ids else None
                elif cur is not None and line.startswith("name: "):
                    cur["names"].add(line[6:])
                elif cur is not None and line.startswith("synonym: "):
                    m = re.match(r'synonym: "(.*?)"', line)
                    if m:
                        cur["names"].add(m.group(1))
                elif cur is not None and line.startswith("is_obsolete: true"):
                    cur["obsolete"] = True
        return out

    def verify(self, concept_id: str, service: str | None, concept_label: str | None, term: str) -> dict:
        r, key = route(concept_id, service)
        res = {"route": r, "local_id": key, "id_status": "NOT_VERIFIABLE", "vocab_names": [],
               "label_match": "NOT_CHECKED", "term_match": "NOT_CHECKED",
               "vocab_version": self.versions.get(r.split(":")[0], "")}
        names = None
        if r == "ncbi_taxonomy":
            if key in self.tax["deleted"]:
                res["id_status"] = "OBSOLETE"
            elif key in self.tax["merged"]:
                res["id_status"], res["merged_into"] = "OBSOLETE", self.tax["merged"][key]
            elif key in self.tax["names"]:
                res["id_status"], names = "VERIFIED", self.tax["names"][key]
            else:
                res["id_status"] = "NOT_FOUND"
        elif r in ("mondo", "hpo"):
            e = self.obo.get(r, {}).get(key)
            if e is None:
                res["id_status"] = "NOT_FOUND"
            else:
                res["id_status"], names = ("OBSOLETE" if e["obsolete"] else "VERIFIED"), e["names"]
        elif r.startswith("omop:") and self.omop is not None:
            if r == "omop:concept_id":
                cids = {int(key)} & self.omop["names"].keys() if key.isdigit() else set()
            else:
                cids = self.omop["by_code"].get((r.split(":", 1)[1], key), set())
            if not cids and r == "omop:concept_id":
                res["id_status"] = "NOT_FOUND"
            elif not cids:
                # OMOP carries only a subset of NCIt / MeSH / SNOMED (e.g. no MeSH qualifiers Q*, newer NCIt codes),
                # so absence from the local copy does not show that the identifier is invalid.
                res["id_status"], res["note"] = "NOT_VERIFIABLE", "code not in local OMOP subset of this vocabulary"
            else:
                res["id_status"] = "VERIFIED"
                names = set().union(*(self.omop["names"][c] for c in cids))
        if names is not None:
            res["vocab_names"] = sorted(names)[:10]
            res["label_match"] = self._match(concept_label, names)
            res["term_match"] = self._match(term, names)
        return res

    @staticmethod
    def _match(s, names):
        if not s:
            return "NONE"
        if s in names:
            return "EXACT"
        if norm(s) in {norm(n) for n in names}:
            return "NORMALISED"
        return "NONE"
