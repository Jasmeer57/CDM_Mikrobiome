#!/usr/bin/env python3
"""Unit tests for catalogue Phase C (normalize_catalogue_vocab.py) and Phase B
(link_catalogue.py).

Run from repo root:
    python -m unittest discover -s src/tests -p test_catalogue_vocab_link.py -v

No network, GPU or corpus: the vocabulary is the tracked
src/configs/catalogue_vocab/vocab.yaml, NCBI runs offline against a temporary
cache, and the model is replaced by a stub returning canned answers.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(REPO_ROOT / "src" / "scripts" / "vllm_termpop"))

try:
    import yaml  # noqa: F401
    YAML_AVAILABLE = True
except ImportError:  # pragma: no cover
    YAML_AVAILABLE = False

import link_catalogue as lc  # noqa: E402

if YAML_AVAILABLE:
    import normalize_catalogue_vocab as nv  # noqa: E402


@unittest.skipUnless(YAML_AVAILABLE, "pyyaml not installed")
class TestVocab(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v = nv.Vocab(nv.VOCAB_DIR / "vocab.yaml")

    def test_body_site(self):
        self.assertEqual(self.v.body_site("fecal samples")[:2], ("feces", "UBERON:0001988"))
        self.assertEqual(self.v.body_site("Rectal swabs")[0], "rectum")
        self.assertEqual(self.v.body_site("caecum")[0], "caecum")
        self.assertEqual(self.v.body_site("gastric mucosa")[0], "stomach")
        self.assertEqual(self.v.body_site("gut microbiota")[0], "digestive tract")
        self.assertEqual(self.v.body_site("mice feces")[2], "NON_HUMAN")
        self.assertEqual(self.v.body_site("general")[2], "UNMAPPED")
        self.assertEqual(self.v.body_site("")[2], "EMPTY")

    def test_assay(self):
        self.assertEqual(self.v.assay("16S rRNA gene sequencing"), ("16S rRNA amplicon sequencing", "WET_LAB"))
        self.assertEqual(self.v.assay("shotgun metagenomic sequencing")[0], "shotgun metagenomic sequencing")
        self.assertEqual(self.v.assay("metatranscriptomics")[0], "metatranscriptomics")
        self.assertEqual(self.v.assay("RT-qPCR")[0], "quantitative PCR")
        self.assertEqual(self.v.assay("LEfSe analysis")[1], "COMPUTATIONAL")

    def test_repository(self):
        self.assertEqual(self.v.repository("NCBI Sequence Read Archive (SRA)", ""), "NCBI SRA")
        self.assertEqual(self.v.repository("NCBI", "BioProject"), "NCBI BioProject")
        self.assertEqual(self.v.repository("", "GEO"), "GEO")
        self.assertEqual(self.v.repository("corresponding author", ""), "available on request")

    def test_domain_and_rank(self):
        self.assertEqual(self.v.simple("finding_domain", "alpha_diversity"), "alpha diversity")
        self.assertEqual(self.v.simple("finding_domain", "microbiota_composition"),
                         "taxonomic composition and abundance")
        self.assertEqual(self.v.simple("taxonomic_rank", "Genus"), "genus")
        self.assertEqual(self.v.simple("taxonomic_rank", "metabolite"), "not a taxon")

    def test_taxon_candidates(self):
        self.assertEqual(nv.taxon_candidates("Peptostreptococcus, Streptococcus and Fusobacterium"),
                         ["Peptostreptococcus", "Streptococcus", "Fusobacterium"])
        self.assertEqual(nv.taxon_candidates("g__Prevotella"), ["Prevotella"])
        self.assertEqual(nv.taxon_candidates("F. prausnitzii"), [])  # abbreviations not guessed
        self.assertEqual(nv.taxon_candidates("unclassified Lachnospiraceae"), ["Lachnospiraceae"])

    def test_link_taxa_offline(self):
        with tempfile.TemporaryDirectory() as d:
            cache = Path(d) / "c.json"
            cache.write_text(json.dumps({
                "Prevotella": {"status": "SCIENTIFIC_NAME", "taxid": "838", "name": "Prevotella"},
                "Firmicutes": {"status": "SYNONYM", "taxid": "1239", "name": "Bacillota"}}))
            ncbi = nv.NCBITaxonomy(cache, offline=True)
            self.assertEqual(nv.link_taxa({"taxon_or_feature": "Prevotella, Firmicutes"}, ncbi),
                             ("NCBITaxon:838; NCBITaxon:1239", "Prevotella; Bacillota", "LINKED"))
            self.assertEqual(nv.link_taxa({"taxon_or_feature": "Prevotella, Blautia"}, ncbi)[2], "PARTIAL")

    def test_homonym_prefers_microbe(self):
        rothia = {"status": "AMBIGUOUS", "candidates": [
            {"taxid": "1380124", "name": "Rothia", "rank": "genus", "division": "moths & butterflies"},
            {"taxid": "508215", "name": "Rothia", "rank": "genus", "division": "eudicots"},
            {"taxid": "32207", "name": "Rothia", "rank": "genus", "division": "high G+C Gram-positive bacteria"}]}
        self.assertEqual(nv.NCBITaxonomy._resolve(rothia, "genus")["taxid"], "32207")
        firm = {"status": "AMBIGUOUS", "candidates": [
            {"taxid": "1783272", "rank": "kingdom", "division": "bacteria"},
            {"taxid": "1239", "rank": "phylum", "division": "firmicutes"}]}
        self.assertEqual(nv.NCBITaxonomy._resolve(firm, "phylum")["taxid"], "1239")
        self.assertEqual(nv.NCBITaxonomy._resolve(firm, "genus")["status"], "AMBIGUOUS")


class TestLicencePolicy(unittest.TestCase):
    def test_policy(self):
        import fetch_paper_licences as fl
        self.assertEqual(fl.quote_policy("cc by"), "KEEP")
        self.assertEqual(fl.quote_policy("cc0"), "KEEP")
        self.assertEqual(fl.quote_policy("cc by-nc"), "KEEP_NC")
        self.assertEqual(fl.quote_policy("cc by-nc-sa"), "KEEP_NC")
        self.assertEqual(fl.quote_policy("cc by-nc-nd"), "REDACT")
        self.assertEqual(fl.quote_policy(""), "REDACT")
        self.assertEqual(fl.license_url("cc by-nc-nd"), "https://creativecommons.org/licenses/by-nc-nd/")


def _rec(entity, rid, paper="HMPAPER_000001", **fields):
    f = {lc.ID_FIELD[entity]: rid, "paper_id": paper, "evidence_text": "ev " + rid}
    f.update(fields)
    return {"entity_type": entity, "paper_id": paper, "fields": f}


class TestLinking(unittest.TestCase):
    def _paper(self):
        return [
            _rec("datasets", "HMDATA_1", dataset_title="BioProject PRJNA1"),
            _rec("cohorts", "HMCOHORT_1", cohort_label="HIV+"),
            _rec("cohorts", "HMCOHORT_2", cohort_label="HIV-"),
            _rec("assays", "HMASSAY_1", assay_type="16S"),
            _rec("findings", "HMFINDING_1", taxon_or_feature="Prevotella",
                 is_primary_finding="REVIEW", direction="INCREASE", direction_flag="OPPOSITE_WORDING"),
            _rec("findings", "HMFINDING_2", taxon_or_feature="Blautia", is_primary_finding="YES",
                 direction="DECREASE", direction_flag=""),
        ]

    def test_batches_only_use_own_paper(self):
        recs = self._paper()
        batches = lc.build_batches(recs)
        ents = {b["entity"] for b in batches}
        self.assertEqual(ents, {"cohorts", "assays", "findings"})
        fb = next(b for b in batches if b["entity"] == "findings")
        payload = json.loads(fb["user"])
        self.assertEqual({c["id"] for c in payload["CANDIDATES"]["cohorts"]}, {"HMCOHORT_1", "HMCOHORT_2"})
        asks = {i["id"]: i["answer_fields"] for i in payload["ITEMS"]}
        self.assertIn("primary", asks["HMFINDING_1"])
        self.assertIn("direction", asks["HMFINDING_1"])
        self.assertNotIn("primary", asks["HMFINDING_2"])

    def test_invalid_and_foreign_ids_dropped(self):
        recs = self._paper() + [_rec("cohorts", "HMCOHORT_9", paper="HMPAPER_000002")]
        by_id = {r["fields"][lc.ID_FIELD[r["entity_type"]]]: r for r in recs}
        batch = next(b for b in lc.build_batches(recs[:6]) if b["entity"] == "findings")
        answers = [
            {"id": "HMFINDING_1", "cohort_id": ["HMCOHORT_1", "HMCOHORT_9", "HMCOHORT_77"],
             "assay_id": "HMASSAY_1", "dataset_id": "NONE", "primary": "yes", "direction": "decrease"},
            {"id": "HMFINDING_2", "cohort_id": "NONE", "assay_id": "NONE", "dataset_id": "NONE",
             "primary": "NO"},
        ]
        stats = lc.Counter()
        lc.apply_answers(batch, lc.normalise_answers({"links": answers}), by_id,
                         lc.paper_ids(recs), "RUN", stats)
        f1, f2 = by_id["HMFINDING_1"]["fields"], by_id["HMFINDING_2"]["fields"]
        self.assertEqual(f1["cohort_id"], "HMCOHORT_1")  # other paper's + invented id dropped
        self.assertEqual(f1["assay_id"], "HMASSAY_1")
        self.assertEqual(f1["dataset_id"], "")
        self.assertEqual(stats["invalid_ids_dropped"], 2)
        self.assertEqual((f1["is_primary_finding"], f1["is_primary_finding_source"]), ("YES", "LLM"))
        self.assertEqual(f1["direction_llm"], "DECREASE")
        self.assertEqual(f1["direction"], "INCREASE")  # never overwritten
        self.assertEqual(f2["link_status"], "NONE_CLEAR")
        self.assertEqual(f2["is_primary_finding"], "YES")  # rule verdict not REVIEW: untouched

    def test_end_to_end_with_stub_model(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            in_dir, out_dir = d / "in", d / "out"
            in_dir.mkdir()
            recs = self._paper()
            with open(in_dir / "catalogue_records.jsonl", "w") as fh:
                for r in recs:
                    fh.write(json.dumps(r) + "\n")
            for e in lc.ENTITIES:
                cols = sorted({k for r in recs if r["entity_type"] == e for k in r["fields"]}) or ["paper_id"]
                (in_dir / f"catalogue_{e}.csv").write_text(",".join(cols) + "\n")

            def stub(host, model, user, timeout):
                items = json.loads(user)["ITEMS"]
                return {"links": [{"id": i["id"], "cohort_id": "HMCOHORT_2", "dataset_id": "HMDATA_1",
                                   "assay_id": "HMASSAY_1", "primary": "NO"} for i in items]}

            with mock.patch.object(lc, "chat", stub):
                rc = lc.main(["--input_dir", str(in_dir), "--output_dir", str(out_dir),
                              "--expected_papers", "1", "--parallel", "2"])
            self.assertEqual(rc, 0)
            out = [json.loads(line) for line in open(out_dir / "catalogue_records.jsonl")]
            f1 = next(r["fields"] for r in out if r["fields"].get("finding_id") == "HMFINDING_1")
            self.assertEqual((f1["cohort_id"], f1["assay_id"], f1["dataset_id"]),
                             ("HMCOHORT_2", "HMASSAY_1", "HMDATA_1"))
            self.assertEqual(f1["is_primary_finding"], "NO")
            c1 = next(r["fields"] for r in out if r["fields"].get("cohort_id") == "HMCOHORT_1"
                      and r["entity_type"] == "cohorts")
            self.assertEqual(c1["dataset_id"], "HMDATA_1")
            report = json.loads((out_dir / "_link_report.json").read_text())
            self.assertEqual(report["link_fill_pct"]["findings"]["cohort_id"], 100.0)

    def test_answer_shapes(self):
        want = {"HMSAMPLE_1": "HMCOHORT_1", "HMSAMPLE_2": "HMCOHORT_2"}
        shapes = [
            {"links": [{"id": "HMSAMPLE_1", "cohort_id": ["HMCOHORT_1"]},
                       {"id": "HMSAMPLE_2", "cohort_id": "HMCOHORT_2"}]},
            {"links": [{"HMSAMPLE_1": {"cohort_id": "HMCOHORT_1"},
                        "HMSAMPLE_2": {"cohort_id": "HMCOHORT_2"}}]},
            {"HMSAMPLE_1": {"cohort_id": "HMCOHORT_1"}, "HMSAMPLE_2": {"cohort_id": "HMCOHORT_2"}},
            {"links": ["HMSAMPLE_1", {"id": "HMSAMPLE_1", "cohort_id": "HMCOHORT_1"},
                       {"id": "HMSAMPLE_2", "cohort_id": "HMCOHORT_2"}]},
        ]
        for obj in shapes:
            got = lc.normalise_answers(obj)
            self.assertEqual({k: (v["cohort_id"][0] if isinstance(v["cohort_id"], list) else v["cohort_id"])
                              for k, v in got.items()}, want, obj)

    def test_truncated_batch_is_split(self):
        recs = self._paper()
        b = next(b for b in lc.build_batches(recs) if b["entity"] == "cohorts")
        halves = lc.split_batch(b)
        self.assertEqual([len(h["items"]) for h in halves], [1, 1])
        self.assertEqual(sum((h["items"] for h in halves), []), b["items"])
        self.assertEqual(json.loads(halves[0]["user"])["CANDIDATES"], json.loads(b["user"])["CANDIDATES"])

    def test_wrong_corpus_size_aborts(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "catalogue_records.jsonl").write_text(json.dumps(self._paper()[0]) + "\n")
            with self.assertRaises(SystemExit):
                lc.main(["--input_dir", str(d), "--output_dir", str(d / "o"), "--dry_run"])


if __name__ == "__main__":
    unittest.main()
