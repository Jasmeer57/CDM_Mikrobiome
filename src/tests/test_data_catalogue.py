#!/usr/bin/env python3
"""Test suite for the human-microbiome data catalogue build + validation.

Run from repo root:
    python -m unittest tests.test_data_catalogue -v

Design (see temp.md acceptance criteria):
- Positive tests: a synthetic but realistic mini catalogue (2 papers, 3 findings)
  passes all validators, proving the checks accept valid data.
- Negative fixtures: deliberately broken mutants of that catalogue, each
  engineered to trip exactly one validator — proving the validators actually
  FAIL when they should (a validator that never fails proves nothing).
- No network, no corpus, no schema-file dependency beyond the tracked template.

Heavy/optional deps follow the repo convention (try/except ImportError with
*_AVAILABLE flag) so the suite skips schema tests gracefully if jsonschema
isn't installed.
"""
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())))
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file()) / "src"))
sys.path.insert(
    0, str(next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file()) / "src" / "corpus_builder"))

from corpus_builder import catalogue_validation as cv

JSONSCHEMA_AVAILABLE = cv.JSONSCHEMA_AVAILABLE

SCHEMA_PATH = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file()) / (
    "src/template/data_catalogue/human_microbiome_data_catalogue.schema.json")


# ---------------------------------------------------------------- fixtures


def valid_catalogue():
    """Hand-built minimal catalogue that must pass every validator.

    Mirrors the real builder's output shape (all required + key optional fields,
    correct ID patterns, one PRJ accession per paper, verbatim-evidenced findings).
    """
    return {
        "schema_version": "1.0.0",
        "papers": [
            {"paper_id": "HMPAPER_000001", "doi": "10.1/x", "title": "Gut microbiota in health",
             "human_microbiome_relevance": "DIRECT", "inclusion_decision": "INCLUDE"},
            {"paper_id": "HMPAPER_000002", "doi": "10.1/y", "title": "Skin microbiome study",
             "human_microbiome_relevance": "DIRECT", "inclusion_decision": "INCLUDE"},
        ],
        "datasets": [
            {"dataset_id": "HMDATA_000001", "paper_id": "HMPAPER_000001",
             "repository_accession": ["PRJNA111111"], "data_availability_status": "PUBLIC",
             "verification_status": "VERIFIED_IMPORT"},
            {"dataset_id": "HMDATA_000002", "paper_id": "HMPAPER_000002",
             "repository_accession": ["PRJEB222222"], "data_availability_status": "PUBLIC",
             "verification_status": "VERIFIED_IMPORT"},
        ],
        "data_assets": [
            {"asset_id": "HMASSET_000001", "dataset_id": "HMDATA_000001"},
            {"asset_id": "HMASSET_000002", "dataset_id": "HMDATA_000002"},
        ],
        "cohorts": [
            {"cohort_id": "HMCOHORT_000001", "paper_id": "HMPAPER_000001",
             "dataset_id": "HMDATA_000001", "participant_count": 10},
        ],
        "samples": [
            {"sample_group_id": "HMSAMPLE_000001", "paper_id": "HMPAPER_000001",
             "dataset_id": "HMDATA_000001"},
            {"sample_group_id": "HMSAMPLE_000002", "paper_id": "HMPAPER_000002",
             "dataset_id": "HMDATA_000002"},
        ],
        "assays": [
            {"assay_id": "HMASSAY_000001", "paper_id": "HMPAPER_000001",
             "dataset_id": "HMDATA_000001"},
            {"assay_id": "HMASSAY_000002", "paper_id": "HMPAPER_000002",
             "dataset_id": "HMDATA_000002"},
        ],
        "findings": [
            {"finding_id": "HMFINDING_000001", "paper_id": "HMPAPER_000001",
             "verification_status": "VERIFIED_INLINE",
             "finding_text": "Bifidobacterium increased after intervention.",
             "evidence_text": "the abundance of Bifidobacterium increased significantly after the intervention"},
            {"finding_id": "HMFINDING_000002", "paper_id": "HMPAPER_000002",
             "verification_status": "VERIFIED_INLINE",
             "finding_text": "Staphylococcus dominates skin sites.",
             "evidence_text": "Staphylococcus dominated all sampled skin sites"},
            {"finding_id": "HMFINDING_000003", "paper_id": "HMPAPER_000001",
             "verification_status": "PENDING",
             "finding_text": "unverified draft finding", "evidence_text": None},
        ],
    }


class FakeV1Dir:
    """Builds a temp 'v1 records' dir whose source_txt files contain the evidence
    text for the fixture catalogue. Used for traceability tests."""

    def __init__(self, contents_by_acc):
        self.dir = None
        self._contents = contents_by_acc
        self._mk()

    def _mk(self):
        import os
        self.dir = tempfile.mkdtemp(prefix="hmp_v1_test_")
        self.src_texts = {}
        for acc, text in sorted(self._contents.items()):
            sub = os.path.join(self.dir, acc[-2:])
            os.makedirs(sub, exist_ok=True)
            src = os.path.join(self.dir, f"{acc}.txt")
            with open(src, "w") as fh:
                fh.write(text)
            rec = {"source": {"source_txt": src}, "corpus_classification": {"llm_status": "completed"}}
            with open(os.path.join(sub, f"HMP_{acc}.json"), "w") as fh:
                json.dump(rec, fh)
        return self.dir

    def destroy(self):
        import shutil
        if self.dir:
            shutil.rmtree(self.dir, ignore_errors=True)


def make_v1_dir():
    return FakeV1Dir({
        "PRJNA111111": "We observed that the abundance of Bifidobacterium increased "
                       "significantly after the intervention (p = 0.01).",
        "PRJEB222222": "Across cohorts, Staphylococcus dominated all sampled skin sites.",
    })


# ------------------------------------------------------ positive validators


class TestValidatorsAcceptValidData(unittest.TestCase):
    """Positive controls: the valid fixture passes every check."""

    @classmethod
    def setUpClass(cls):
        cls.v1 = make_v1_dir()

    @classmethod
    def tearDownClass(cls):
        cls.v1.destroy()

    def cat(self):
        return valid_catalogue()

    def test_schema_conformance_pass(self):
        if not JSONSCHEMA_AVAILABLE:
            self.skipTest("jsonschema not installed")
        res = cv.check_schema(self.cat(), SCHEMA_PATH)
        self.assertTrue(res["pass"], msg=json.dumps(res))
        self.assertEqual(res["n_errors"], 0)

    def test_fk_pass(self):
        res = cv.check_fk(self.cat())
        self.assertTrue(res["pass"])
        self.assertEqual(res["n_violations"], 0)

    def test_id_uniqueness_pass(self):
        res = cv.check_id_uniqueness(self.cat())
        self.assertTrue(res["pass"])

    def test_required_fields_pass(self):
        res = cv.check_required_fields(self.cat())
        self.assertTrue(res["pass"])

    def test_accession_integrity_pass(self):
        res = cv.check_accession_integrity(self.cat())
        self.assertTrue(res["pass"])

    def test_evidence_traceability_pass(self):
        res = cv.check_evidence_traceability(self.cat(), v1_dir=self.v1.dir)
        self.assertTrue(res["pass"], msg=json.dumps(res))
        self.assertEqual(res["n_checked"], 2)
        self.assertEqual(res["n_mismatch"], 0)

    def test_mapping_conflicts_resolved_when_export_matches(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump({"bioprojects": [
                {"bioproject_id": "PRJNA111111", "title": "Gut microbiota in health"},
                {"bioproject_id": "PRJEB222222", "title": "Skin microbiome study"},
            ]}, fh)
            bpe = fh.name
        try:
            res = cv.check_accession_mapping_conflicts(self.cat(), bpe)
            self.assertEqual(res["n_resolved"], 2)
            self.assertEqual(res["n_unverified"], 0)
            self.assertTrue(res["pass"])
        finally:
            import os
            os.unlink(bpe)

    def test_run_all_checks_pass(self):
        res = cv.run_all_checks(self.cat(), v1_dir=self.v1.dir)
        self.assertTrue(res["overall_pass"], msg=json.dumps(res["blocking_failures"]))
        self.assertEqual(res["blocking_failures"], [])

    def test_unverified_finding_skipped_in_traceability(self):
        """PENDING findings without evidence must not be counted as traceable
        (denominator = VERIFIED_INLINE only) — and must not fail the check."""
        res = cv.check_evidence_traceability(self.cat(), v1_dir=self.v1.dir)
        self.assertEqual(res["n_checked"], 2)  # 3 findings, 2 VERIFIED_INLINE


# ------------------------------------------------------ negative fixtures


class ValidatorFailsWhenItShould(unittest.TestCase):
    """Negative controls: each mutant breaks exactly one thing; the right
    validator must fail."""

    @classmethod
    def setUpClass(cls):
        cls.v1 = make_v1_dir()

    @classmethod
    def tearDownClass(cls):
        cls.v1.destroy()

    def mutate(self, fn):
        cat = valid_catalogue()
        fn(cat)
        return cat

    # --- schema
    def test_schema_catches_bad_id_pattern(self):
        if not JSONSCHEMA_AVAILABLE:
            self.skipTest("jsonschema not installed")
        def m(cat):
            cat["papers"][0]["paper_id"] = "paper-1"  # violates ^HMPAPER_[0-9]{6}$
        res = cv.check_schema(self.mutate(m), SCHEMA_PATH)
        self.assertFalse(res["pass"])
        self.assertGreater(res["n_errors"], 0)

    def test_schema_catches_bad_enum(self):
        if not JSONSCHEMA_AVAILABLE:
            self.skipTest("jsonschema not installed")
        def m(cat):
            cat["papers"][0]["inclusion_decision"] = "MAYBE"
        res = cv.check_schema(self.mutate(m), SCHEMA_PATH)
        self.assertFalse(res["pass"])

    def test_schema_catches_missing_top_table(self):
        if not JSONSCHEMA_AVAILABLE:
            self.skipTest("jsonschema not installed")
        def m(cat):
            del cat["findings"]
        res = cv.check_schema(self.mutate(m), SCHEMA_PATH)
        self.assertFalse(res["pass"])

    # --- FK
    def test_fk_catches_dangling_paper_ref(self):
        def m(cat):
            cat["findings"][0]["paper_id"] = "HMPAPER_999999"
        res = cv.check_fk(self.mutate(m))
        self.assertFalse(res["pass"])
        self.assertEqual(res["n_violations"], 1)

    def test_fk_catches_dangling_dataset_ref(self):
        def m(cat):
            cat["data_assets"][0]["dataset_id"] = "HMDATA_999999"
        res = cv.check_fk(self.mutate(m))
        self.assertFalse(res["pass"])

    def test_fk_cohorts_dataset_may_be_null(self):
        def m(cat):
            cat["cohorts"][0]["dataset_id"] = None
        res = cv.check_fk(self.mutate(m))
        self.assertTrue(res["pass"])

    # --- uniqueness
    def test_uniqueness_catches_duplicate(self):
        def m(cat):
            cat["samples"][1]["sample_group_id"] = cat["samples"][0]["sample_group_id"]
        res = cv.check_id_uniqueness(self.mutate(m))
        self.assertFalse(res["pass"])

    def test_uniqueness_catches_bad_pattern(self):
        def m(cat):
            cat["assays"][0]["assay_id"] = "ASSAY_1"
        res = cv.check_id_uniqueness(self.mutate(m))
        self.assertFalse(res["pass"])

    # --- required
    def test_required_catches_missing_key(self):
        def m(cat):
            del cat["datasets"][0]["paper_id"]
        res = cv.check_required_fields(self.mutate(m))
        self.assertFalse(res["pass"])

    # --- accession integrity
    def test_accession_catches_cross_paper_duplicate(self):
        def m(cat):
            cat["datasets"][1]["repository_accession"] = ["PRJNA111111"]
        res = cv.check_accession_integrity(self.mutate(m))
        self.assertFalse(res["pass"])

    def test_accession_catches_non_prj(self):
        def m(cat):
            cat["datasets"][0]["repository_accession"] = ["GSE12345"]
        res = cv.check_accession_integrity(self.mutate(m))
        self.assertFalse(res["pass"])

    def test_accession_catches_empty(self):
        def m(cat):
            cat["datasets"][0]["repository_accession"] = []
        res = cv.check_accession_integrity(self.mutate(m))
        self.assertFalse(res["pass"])

    # --- traceability
    def test_traceability_catches_fabricated_evidence(self):
        def m(cat):
            cat["findings"][0]["evidence_text"] = "this sentence is nowhere in the source text at all"
        res = cv.check_evidence_traceability(self.mutate(m), v1_dir=self.v1.dir)
        self.assertFalse(res["pass"])
        self.assertEqual(res["n_mismatch"], 1)
        self.assertEqual(res["n_checked"], 2)

    def test_traceability_catches_empty_evidence_on_verified(self):
        def m(cat):
            cat["findings"][1]["evidence_text"] = ""
        res = cv.check_evidence_traceability(self.mutate(m), v1_dir=self.v1.dir)
        self.assertFalse(res["pass"])

    def test_traceability_reports_missing_source_file(self):
        def m(cat):
            cat["findings"][0]["paper_id"] = "HMPAPER_000003"  # no such record dir
            cat["findings"][0]["finding_id"] = "HMFINDING_000003"
            cat["findings"][2]["finding_id"] = "HMFINDING_000004"
        res = cv.check_evidence_traceability(self.mutate(m), v1_dir=self.v1.dir)
        self.assertGreaterEqual(res["n_source_missing"], 1)
        self.assertEqual(res["n_checked"], 1)

    def test_traceability_is_case_and_ws_insensitive(self):
        def m(cat):
            cat["findings"][0]["evidence_text"] = "  THE ABUNDANCE of\n\tBifidobacterium INCREASED significantly after the intervention  "
        res = cv.check_evidence_traceability(self.mutate(m), v1_dir=self.v1.dir)
        self.assertEqual(res["n_mismatch"], 0)
        self.assertTrue(res["pass"])

    # --- mapping conflicts
    def test_mapping_flags_unverified_absent_accession(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump({"bioprojects": [
                {"bioproject_id": "PRJNA111111", "title": "Gut microbiota in health"},
            ]}, fh)  # PRJEB222222 absent -> one UNVERIFIED
            bpe = fh.name
        try:
            res = cv.check_accession_mapping_conflicts(self.mutate(lambda c: c), bpe)
            self.assertEqual(res["n_unverified"], 1)
            self.assertTrue(res["pass"], "UNVERIFIED alone must not block (documented uncertainty)")
        finally:
            import os
            os.unlink(bpe)

    def test_mapping_zero_agreement_goes_to_review_not_conflict(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump({"bioprojects": [
                {"bioproject_id": "PRJNA111111", "title": "Completely unrelated boring title here"},
                {"bioproject_id": "PRJEB222222", "title": "Skin microbiome study"},
            ]}, fh)
            bpe = fh.name
        try:
            res = cv.check_accession_mapping_conflicts(self.mutate(lambda c: c), bpe)
            self.assertEqual(res["n_review"], 1)
            self.assertEqual(res["n_conflicting"], 0)
            self.assertTrue(res["pass"])
        finally:
            import os
            os.unlink(bpe)

    # --- aggregate gate
    def test_run_all_reports_blocking_failure(self):
        def m(cat):
            cat["data_assets"][0]["dataset_id"] = "HMDATA_999999"
        res = cv.run_all_checks(self.mutate(m), v1_dir=self.v1.dir)
        self.assertTrue([c for c in res["checks"] if c["check"] == "schema_conformance"][0]["pass"]
                        or not JSONSCHEMA_AVAILABLE)
        self.assertIn("fk_integrity", res["blocking_failures"])
        self.assertFalse(res["overall_pass"])


# ------------------------------------------------------- reproducibility


class TestReproducibility(unittest.TestCase):
    """input_manifest hashing: same content -> same hash; changed content ->
    different hash (the stale-mix detector)."""

    def test_hash_stable_and_sensitive(self):
        v1 = make_v1_dir()
        try:
            h1 = cv.hash_record_dir(v1.dir)
            h2 = cv.hash_record_dir(v1.dir)
            self.assertEqual(h1["content_sha256"], h2["content_sha256"])
            self.assertEqual(h1["n_record_files"], 2)
            p = next(iter(Path(v1.dir).glob("*/*.json")))
            p.with_suffix(".json").write_text(p.read_text() + " ")
            h3 = cv.hash_record_dir(v1.dir)
            self.assertNotEqual(h1["content_sha256"], h3["content_sha256"])
        finally:
            v1.destroy()

    def test_hash_file_matches_sha256sum(self):
        import hashlib
        with tempfile.NamedTemporaryFile("wb", delete=False) as fh:
            fh.write(b"hello catalogue")
            p = fh.name
        try:
            self.assertEqual(cv.hash_file(p), hashlib.sha256(b"hello catalogue").hexdigest())
        finally:
            import os
            os.unlink(p)


class TestLLMCatalogueOverlay(unittest.TestCase):
    """Offline test of the LLM-catalogue overlay merge in build_data_catalogue.

    Exercises _fill/_avail, each overlay_* function (fill-if-empty enrichment,
    append-only new rows, ID collisions, dedup, raw-source re-verification),
    and re-runs the blocking validators over the merged result — no GPU, no
    network, synthetic inputs only.
    """

    @classmethod
    def setUpClass(cls):
        import build_data_catalogue as bdc
        cls.bdc = bdc

    def _cat(self):
        """Synthetic overlay checkpoint shaped like catalogue_llm_extract output."""
        return {
            "datasets": [
                {"accession": None, "title": "16S profiles of gut samples",
                 "description": "Amplicon survey", "availability_status": "upon request",
                 "role": "primary", "evidence_text": "Data are available upon request.",
                 "evidence_verified": True},
                {"accession": "PRJNA999999", "title": "Shotgun data",
                 "description": None, "availability_status": "public",
                 "role": None, "evidence_text": "Shotgun reads deposited in PRJNA999999.",
                 "evidence_verified": True},
            ],
            "cohorts": [
                {"cohort_label": "IBD cohort", "cohort_role": "disease_group",
                 "population_description": "Adults with Crohn's disease",
                 "participant_count": "85", "sample_count": None,
                 "country_or_region": ["Spain"], "evidence_text": "85 Spanish CD patients",
                 "evidence_verified": True},
            ],
            "samples": [
                {"body_site": "gut", "sample_type": "stool",
                 "collection_method": "home kit", "sample_count": "85",
                 "evidence_verified": True},
                {"body_site": "Gut", "sample_type": "Stool",
                 "collection_method": None, "sample_count": None,
                 "evidence_verified": False},  # dup by (upper site, type) -> skipped
            ],
            "assays": [
                {"assay_type": "16S rRNA sequencing", "target_gene_or_region": "V4",
                 "sequencing_platform": "Illumina MiSeq", "evidence_verified": True},
            ],
            "findings": [
                {"finding_text": "Faecalibacterium reduced", "taxon_or_feature":
                 "Faecalibacterium prausnitzii", "direction": "decrease",
                 "outcome": "Crohn's disease", "evidence_text":
                 "Faecalibacterium prausnitzii was reduced in CD patients.",
                 "evidence_verified": True},
                {"finding_text": "untraceable", "taxon_or_feature": "Bogus taxon",
                 "direction": "increase", "outcome": None,
                 "evidence_text": "THIS SENTENCE IS NOT IN THE RAW SOURCE TEXT AT ALL.",
                 "evidence_verified": True},  # passes extractor check, fails raw re-check
            ],
        }

    def test_fill_avail_and_evhash(self):
        bdc = self.bdc
        self.assertEqual(bdc._avail("upon request"), "UPON_REQUEST")
        self.assertEqual(bdc._avail("Public"), "PUBLIC")
        self.assertEqual(bdc._avail("weird value"), "UNKNOWN")
        self.assertIsNone(bdc._avail(""))
        notes = []
        tgt = {"setting": None}
        bdc._fill(tgt, {"setting": "  tertiary hospital "}, "setting", notes)
        self.assertEqual(tgt["setting"], "tertiary hospital")
        self.assertEqual(notes, ["setting<-llm_catalogue_overlay"])
        tgt2 = {"setting": "existing"}
        bdc._fill(tgt2, {"setting": "new"}, "setting", notes)
        self.assertEqual(tgt2["setting"], "existing")  # fill-if-empty, never overwrite
        self.assertEqual(bdc._evhash("a"), bdc._evhash("a"))
        self.assertNotEqual(bdc._evhash("a"), bdc._evhash("b"))

    def test_overlay_datasets_enrich_and_append(self):
        bdc = self.bdc
        cat = self._cat()
        import itertools as _it
        ds_counter = _it.count(1000)
        asset_counter = _it.count(1000)
        # deterministic row: same PRJ as overlay[1] but new PRJ differs
        det_row = {
            "dataset_id": "HMDATA_000001", "paper_id": "HMPAPER_000001",
            "repository_accession": ["PRJNA999999"], "accession_type": "bioproject",
            "dataset_title": None, "dataset_description": None,
            "data_availability_status": None, "access_conditions": None,
            "original_or_reused": None, "verification_status": "UNVERIFIED",
            "notes": [],
        }
        datasets = [det_row]
        assets = []
        bpe = {}
        n_enriched, n_new = bdc.overlay_datasets(cat, "HMPAPER_000001",
                                                 ds_counter, datasets, assets,
                                                 asset_counter, bpe)
        # overlay[0]: no accession + verified evidence -> appended via the
        # unlinked-paper path ONLY when the paper has no datasets; here it has
        # one, so overlay[0] must NOT create a second dataset (one-PRJ invariant
        # notes extra accessions instead). overlay[1] matches det_row's PRJ ->
        # enrich fill-if-empty.
        self.assertEqual(n_new, 0)
        self.assertEqual(n_enriched, 1)
        self.assertEqual(len(datasets), 1)
        self.assertEqual(det_row["dataset_title"], "Shotgun data")
        self.assertEqual(det_row["data_availability_status"], "PUBLIC")
        self.assertIn("dataset_title<-llm_catalogue_overlay", det_row["catalogue_notes"])

    def test_overlay_datasets_links_unlinked_paper(self):
        bdc = self.bdc
        cat = {"datasets": [{"accession": "PRJNA999999", "title": "Metagenomes",
                             "availability_status": "public",
                             "evidence_text": "Data in PRJNA999999.",
                             "evidence_verified": True}]}
        import itertools as _it
        datasets, assets = [], []
        n_enriched, n_new = bdc.overlay_datasets(cat, "HMPAPER_000002",
                                                 _it.count(1000), datasets, assets,
                                                 _it.count(1000), {})
        self.assertEqual((n_enriched, n_new), (0, 1))
        self.assertEqual(len(datasets), 1)
        self.assertEqual(datasets[0]["repository_accession"], ["PRJNA999999"])
        self.assertEqual(datasets[0]["data_availability_status"], "PUBLIC")
        self.assertEqual(len(assets), 1)  # asset row auto-built

    def test_overlay_cohorts_and_samples(self):
        bdc = self.bdc
        cat = self._cat()
        import itertools as _it
        # paper HAS a deterministic cohort -> first overlay cohort enriches it
        det_cohort = {"cohort_id": "HMCOHORT_000001", "paper_id": "HMPAPER_000001",
                      "population_description": None, "participant_count": None,
                      "notes": []}
        cohorts = [det_cohort]
        n_enriched, n_new = bdc.overlay_cohorts(cat, "HMPAPER_000001",
                                                "HMDATA_000001", cohorts, _it.count(100000))
        self.assertEqual((n_enriched, n_new), (1, 0))
        self.assertEqual(det_cohort["participant_count"], 85)  # str "85" coerced to int
        self.assertEqual(det_cohort["population_description"],
                         "Adults with Crohn's disease")

        # paper WITHOUT deterministic cohort -> first overlay cohort takes the
        # tail ID so sample/finding cohort refs resolve; second gets counter ID
        cohorts2 = []
        cat2 = {"cohorts": [dict(c) for c in cat["cohorts"]] * 2}
        n_enriched, n_new = bdc.overlay_cohorts(cat2, "HMPAPER_000007",
                                                "HMDATA_000001", cohorts2, _it.count(100000))
        ids = [c["cohort_id"] for c in cohorts2]
        self.assertEqual(ids[0], "HMCOHORT_000007")  # tail ID
        self.assertEqual(ids[1], "HMCOHORT_100000")  # counter seeded above tail range
        self.assertTrue(all(re.fullmatch(r"HMCOHORT_[0-9]{6}", i) for i in ids))

        # samples: dup (gut, stool)/(GUT, STOOL) collapses to exactly one new row
        samples = []
        n_new = bdc.overlay_samples(cat, "HMPAPER_000001", "HMDATA_000001",
                                    samples, _it.count(1))
        self.assertEqual(n_new, 1)
        self.assertEqual(samples[0]["cohort_id"], "HMCOHORT_000001")
        self.assertEqual(samples[0]["sample_count"], 85)
        self.assertEqual(samples[0]["body_site"], "GUT")

    def test_overlay_assays_and_findings(self):
        bdc = self.bdc
        cat = self._cat()
        import itertools as _it
        det_assay = {"assay_id": "HMASSAY_000001", "paper_id": "HMPAPER_000001",
                     "assay_type": "16S rRNA sequencing", "target_gene_or_region": None,
                     "notes": []}
        assays = [det_assay]
        n_enriched, n_new = bdc.overlay_assays(cat, "HMPAPER_000001",
                                               "HMDATA_000001", assays, _it.count(100000))
        # overlay assay_type matches existing -> enrich only, no append
        self.assertEqual((n_enriched, n_new), (1, 0))
        self.assertEqual(det_assay["target_gene_or_region"], "V4")
        self.assertEqual(det_assay["sequencing_platform"], "Illumina MiSeq")

        # findings: verified one appended, untraceable-in-raw one dropped
        raw = ("background faecalibacterium prausnitzii was reduced in cd patients. "
               "data are available upon request. shotgun reads deposited in prjna999999.")
        hashes = set()
        findings = []
        n_new, n_reject = bdc.overlay_findings(cat, "HMPAPER_000001", findings,
                                              _it.count(1), hashes, raw_norm=raw)
        self.assertEqual((n_new, n_reject), (1, 1))
        self.assertEqual(findings[0]["verification_status"], "VERIFIED_INLINE")
        self.assertEqual(findings[0]["direction"], "DECREASE")
        self.assertIn("Faecalibacterium prausnitzii", findings[0]["taxon_or_feature"])
        # dedup: same paper overlay twice -> no new finding
        n_new2, _ = bdc.overlay_findings(cat, "HMPAPER_000001", findings,
                                        _it.count(1), hashes, raw_norm=raw)
        self.assertEqual(n_new2, 0)

    def test_merged_catalogue_passes_blocking_validators(self):
        """End-to-end: synthetic det + overlay merge -> all blocking checks green."""
        bdc = self.bdc
        cat = self._cat()
        import itertools as _it
        # fake v1 dir: paper 1's source txt must contain the overlay evidence
        v1 = FakeV1Dir({"PRJNA999999": (
            "BACKGROUND: We enrolled 85 Spanish CD patients. "
            "Faecalibacterium prausnitzii was reduced in CD patients. "
            "Data are available upon request. Shotgun reads deposited in PRJNA999999.")})
        try:
            raw = ("background: we enrolled 85 spanish cd patients. "
                   "faecalibacterium prausnitzii was reduced in cd patients. "
                   "data are available upon request. shotgun reads deposited in prjna999999.")
            papers = [{"paper_id": "HMPAPER_000001", "doi": "10.1/x",
                       "title": "Gut study", "human_microbiome_relevance": "DIRECT",
                       "inclusion_decision": "INCLUDE"}]
            det_row = {"dataset_id": "HMDATA_000001", "paper_id": "HMPAPER_000001",
                       "repository_accession": ["PRJNA999999"], "accession_type": "bioproject",
                       "dataset_title": None, "dataset_description": None,
                       "data_availability_status": None, "access_conditions": None,
                       "original_or_reused": None, "verification_status": "UNVERIFIED",
                       "notes": []}
            datasets = [det_row]
            assets = []
            bdc.overlay_datasets(cat, "HMPAPER_000001", _it.count(2), datasets, assets,
                                 _it.count(2), {})
            cohorts = [{"cohort_id": "HMCOHORT_000001", "paper_id": "HMPAPER_000001",
                        "population_description": None, "participant_count": None, "notes": []}]
            bdc.overlay_cohorts(cat, "HMPAPER_000001", "HMDATA_000001", cohorts, _it.count(100000))
            samples = []
            bdc.overlay_samples(cat, "HMPAPER_000001", "HMDATA_000001", samples, _it.count(1))
            assays = [{"assay_id": "HMASSAY_000001", "paper_id": "HMPAPER_000001",
                       "assay_type": "16S rRNA sequencing", "target_gene_or_region": None,
                       "notes": []}]
            bdc.overlay_assays(cat, "HMPAPER_000001", "HMDATA_000001", assays, _it.count(100000))
            findings = []
            bdc.overlay_findings(cat, "HMPAPER_000001", findings, _it.count(1), set(),
                                 raw_norm=raw)
            self.assertEqual(len(findings), 1)  # untraceable one dropped
            catalogue = {"schema_version": "1.0.0", "papers": papers, "datasets": datasets,
                         "data_assets": assets, "cohorts": cohorts, "samples": samples,
                         "assays": assays, "findings": findings}
            report = cv.run_all_checks(catalogue, v1_dir=v1.dir)
            self.assertTrue(report["overall_pass"], "\n".join(
                str(r) for r in report["checks"] if r.get("pass") is False))
            trace = next(r for r in report["checks"]
                         if r["check"] == "evidence_traceability")
            self.assertEqual((trace["n_checked"], trace["n_mismatch"],
                             trace["n_source_missing"]), (1, 0, 0))
        finally:
            v1.destroy()


class TestCatalogueLLMExtract(unittest.TestCase):
    """Offline tests for catalogue_llm_extract: prompt construction + gates."""

    @classmethod
    def setUpClass(cls):
        import catalogue_llm_extract as cle
        cls.cle = cle

    def test_prompt_contains_title_doi_excerpt(self):
        rec = {"publication": {"title": "  Gut   study ", "doi": "10.1/x"},
               "full_text": {"clean_text_path": None}, }
        prompt = self.cle.make_prompt(rec, context_chars=500)
        self.assertIn("Gut study", prompt)
        self.assertIn("10.1/x", prompt)
        self.assertGreater(len(prompt), 500)

    def test_clean_item_coercions(self):
        cle = self.cle
        d = cle.clean_item({"participant_count": "1,234", "sample_count": "about 90 frogs",
                            "title": "  spaced  title ", "body_site": None,
                            "country_or_region": [" Spain ", "", None]})
        self.assertEqual(d["participant_count"], 1234)
        self.assertEqual(d["sample_count"], 90)  # regex fallback picks first number
        self.assertEqual(d["title"], "spaced title")
        self.assertIsNone(d["body_site"])
        self.assertEqual(d["country_or_region"], ["Spain"])

    def test_postprocess_hallucination_gates(self):
        cle = self.cle
        text = ("we enrolled 85 spanish cd patients and sequenced stool samples. "
                "faecalibacterium prausnitzii was reduced in cd patients. "
                "data are available upon request.")
        norm = text.lower()
        ex = {
            "datasets": [
                {"accession": None, "evidence_text": "Data are available upon request.",
                 "availability_status": "upon request"},  # verified -> kept
                {"accession": None, "evidence_text": "totally fabricated sentence here.",
                 "availability_status": "public"},  # unverified, no accession -> dropped
            ],
            "findings": [
                {"finding_text": "F reduced", "taxon_or_feature": "F. prausnitzii",
                 "evidence_text": "Faecalibacterium prausnitzii was reduced in cd patients."},
                # short/untraceable evidence -> refused outright
                {"finding_text": "junk", "evidence_text": "not in text"},
            ],
            "cohorts": [{"cohort_label": "IBD", "evidence_text": "we enrolled 85 spanish cd patients"}],
            "samples": [], "assays": [],
        }
        out = cle.postprocess(ex, norm)
        self.assertEqual(len(out["datasets"]), 1)
        self.assertTrue(out["datasets"][0]["evidence_verified"])
        self.assertEqual(out["datasets"][0]["availability_status"], "upon request")
        self.assertEqual(len(out["findings"]), 1)
        self.assertEqual(len(out["cohorts"]), 1)
        # non-dict / junk-tolerant input
        empty = cle.postprocess("not a dict", norm)
        self.assertEqual(empty, {"datasets": [], "cohorts": [], "samples": [],
                                 "assays": [], "findings": []})


if __name__ == "__main__":
    unittest.main()
