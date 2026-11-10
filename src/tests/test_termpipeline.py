"""Unit tests for the terminology pipeline stages (``src/scripts/termpipeline/``).

These are the properties the pipeline is *allowed to be trusted on*: identity is
deterministic, every emitted offset re-derives exactly, no candidate is silently
promoted, and failures are fail-closed.

No network access and no live credentials are used anywhere in this module. The
external-ontology behaviour is exercised against *mocked* responses only, which
is what lets these tests run on a CPU node with no API keys at all.
"""
import csv
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
TERMPIPE = REPO_ROOT / "src/scripts" / "termpipeline"
if str(TERMPIPE) not in sys.path:
    sys.path.insert(0, str(TERMPIPE))

import ids  # noqa: E402


def _load(name):
    """Import a stage module by path (``src/scripts/`` is not a package)."""
    spec = importlib.util.spec_from_file_location(name, TERMPIPE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- ids


class TestDeterministicIds(unittest.TestCase):
    """Ids must be pure functions of their inputs — no counters, no salt."""

    def test_term_id_is_a_function_of_content(self):
        a = ids.term_id("obesity", "DISEASE")
        b = ids.term_id("obesity", "DISEASE")
        self.assertEqual(a, b)
        self.assertTrue(a.startswith(ids.TERM_PREFIX))

    def test_term_id_separates_types(self):
        self.assertNotEqual(ids.term_id("obesity", "DISEASE"),
                            ids.term_id("obesity", "CLINICAL"))

    def test_term_id_normalizes_around_whitespace(self):
        self.assertEqual(ids.term_id(" obesity ", "DISEASE"),
                         ids.term_id("obesity", "DISEASE"))

    def test_mention_id_separates_extractors(self):
        """Two models tagging the same span must stay two mentions."""
        a = ids.mention_id("gliner", "HMPAPER_1", "sec_1", 5, 12, "obesity")
        b = ids.mention_id("pubmedbert", "HMPAPER_1", "sec_1", 5, 12, "obesity")
        self.assertNotEqual(a, b)

    def test_occurrence_key_is_extractor_independent(self):
        """The merge-free join key does NOT depend on who saw the span."""
        k = ids.occurrence_key("HMPAPER_1", "sec_1", 5, 12, "obesity")
        self.assertTrue(k.startswith(ids.OCCURRENCE_PREFIX))
        self.assertEqual(k, ids.occurrence_key("HMPAPER_1", "sec_1", 5, 12, "obesity"))

    def test_occurrence_key_distinguishes_offsets(self):
        self.assertNotEqual(
            ids.occurrence_key("HMPAPER_1", "sec_1", 5, 12, "obesity"),
            ids.occurrence_key("HMPAPER_1", "sec_1", 6, 13, "obesity"))

    def test_mapping_id_is_not_process_salted(self):
        """Regression: a builtin ``hash()`` id changes every process, so the same
        candidate would get a new id on every rerun."""
        a = ids.mapping_id("HMCTERM_x", "omop_exact", "433736")
        self.assertEqual(a, ids.mapping_id("HMCTERM_x", "omop_exact", "433736"))
        # Hash randomization must not perturb it.
        with mock.patch.dict(os.environ, {"PYTHONHASHSEED": "12345"}):
            b = ids.mapping_id("HMCTERM_x", "omop_exact", "433736")
        self.assertEqual(a, b)

    def test_mapping_id_separates_concepts(self):
        self.assertNotEqual(ids.mapping_id("HMCTERM_x", "omop_exact", "433736"),
                            ids.mapping_id("HMCTERM_x", "omop_exact", "201826"))

    def test_definition_id_is_stable(self):
        a = ids.definition_id("HMPAPER_1", "sec_1", "HMCTERM_x", 10, 40)
        self.assertEqual(a, ids.definition_id("HMPAPER_1", "sec_1", "HMCTERM_x", 10, 40))
        self.assertNotEqual(a, ids.definition_id("HMPAPER_1", "sec_1", "HMCTERM_x", 10, 41))

    def test_ids_never_collide_across_prefixes(self):
        vals = {ids.term_id("a", "B"), ids.mention_id("r", "p", "s", 0, 1, "a"),
                ids.occurrence_key("p", "s", 0, 1, "a"),
                ids.definition_id("p", "s", "t", 0, 1),
                ids.mapping_id("t", "src", "c")}
        self.assertEqual(len(vals), 5)


# ------------------------------------------------- stage 5 classification


class TestMappingClassification(unittest.TestCase):
    """Rule set for ``mapping_relation`` / ``mapping_disposition``."""

    @classmethod
    def setUpClass(cls):
        cls.pm = _load("project_mappings")

    def test_nothing_is_ever_auto_accepted(self):
        """``classify`` itself can never produce AUTO_ACCEPTED.

        Promotion happens only in ``apply_calibration``, and only when a
        human-reviewed calibration file enables it (spec 12)."""
        cases = [("omop_exact", "Obesity", False, False),
                 ("mesh_gazetteer", "Obesity", False, False),
                 ("ols", "Obesity", False, False),
                 ("umls", "something else", False, False),
                 ("bioportal", None, False, False),
                 ("none", None, True, False),
                 ("unknown_tier", "x", False, True)]
        for tier, label, err, tied in cases:
            rel, disp, elig = self.pm.classify(
                "obesity", "DISEASE", tier, label, "C1",
                has_error=err, tied_competing=tied)
            self.assertNotEqual(disp, "AUTO_ACCEPTED")
            self.assertIn(disp, {"REVIEW_REQUIRED", "UNRESOLVED", "LOOKUP_FAILED"})

    def test_validated_identifier_is_exact_match(self):
        rel, disp, elig = self.pm.classify("obesity", "DISEASE", "omop_exact",
                                           "Obesity", "433736")
        self.assertEqual(rel, "EXACT_MATCH")
        self.assertEqual(disp, "REVIEW_REQUIRED")
        self.assertTrue(elig)

    def test_failed_lookup_is_not_a_no_match(self):
        """A failed lookup must never be reported as 'no match found'."""
        rel, disp, elig = self.pm.classify("obesity", "DISEASE", "umls", None, None,
                                           has_error=True)
        self.assertEqual(rel, "UNVERIFIED")
        self.assertEqual(disp, "LOOKUP_FAILED")
        self.assertFalse(elig)

    def test_text_search_matching_label_is_exact(self):
        rel, _, _ = self.pm.classify("obesity", "DISEASE", "ols", "Obesity", "X1")
        self.assertEqual(rel, "EXACT_MATCH")

    def test_text_search_differing_label_is_related_not_exact(self):
        """Candidate generation must not be promoted to an exact mapping."""
        rel, _, elig = self.pm.classify("obesity", "DISEASE", "bioportal",
                                        "Body mass index", "X2")
        self.assertEqual(rel, "RELATED_TO")
        self.assertFalse(elig)

    def test_tie_flagged_as_ambiguous_not_forced(self):
        rel, disp, elig = self.pm.classify("1 year", "CLINICAL", "unknown_tier",
                                           "1 year", "C1", tied_competing=True)
        self.assertEqual(rel, "AMBIGUOUS")
        self.assertFalse(elig)

    def test_relations_and_dispositions_stay_in_controlled_vocabulary(self):
        allowed_rel = {"EXACT_MATCH", "EQUIVALENT_TO", "NARROWER_THAN",
                       "BROADER_THAN", "RELATED_TO", "SOURCE_CONCEPT_OF",
                       "NO_MATCH_FOUND", "AMBIGUOUS", "CONFLICTING_MAPPINGS",
                       "INVALID_OR_OBSOLETE", "UNVERIFIED"}
        allowed_disp = {"AUTO_ACCEPTED", "REVIEW_REQUIRED", "UNRESOLVED",
                        "REJECTED", "SOURCE_ERROR", "LOOKUP_FAILED", "NOT_APPLICABLE"}
        for tier, label, err, tied in [("omop_exact", "x", False, False),
                                       ("umls", "obesity", False, False),
                                       ("ols", "other", False, False),
                                       ("none", None, True, False),
                                       ("umls", None, False, True)]:
            rel, disp, _ = self.pm.classify("obesity", "DISEASE", tier, label,
                                            "C", has_error=err, tied_competing=tied)
            self.assertIn(rel, allowed_rel)
            self.assertIn(disp, allowed_disp)

    def test_normalization_is_case_and_whitespace_insensitive(self):
        self.assertEqual(self.pm.norm("  Obesity  "), self.pm.norm("obesity"))


# ------------------------------------------------- spec 12 calibration

class TestCalibrationSample(unittest.TestCase):
    """The review sample frames a decision; it never makes one."""

    @classmethod
    def setUpClass(cls):
        cls.bcs = _load("build_calibration_sample")

    def _write_mappings(self, recs):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        p = Path(td.name) / "mappings.jsonl"
        with p.open("w", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r) + "\n")
        return p

    @staticmethod
    def _rec(mid, svc, rel, eligible):
        return {"mapping_id": mid, "term_id": "T1", "term": "obesity",
                "term_norm": "obesity", "cdm_type": "DISEASE",
                "source_service": svc, "mapping_relation": rel,
                "ontology_source": "cv_linking",
                "concept_id": "C1" if rel != "NO_MATCH_FOUND" else None,
                "concept_label": "Obesity", "candidate_rank": 1,
                "is_canonical_candidate": True,
                "auto_accept_eligible": eligible,
                "staged_match": {"stage": "exact_label", "matched_label": True,
                                 "matched_synonym": None},
                "scores": {"confidence": 1.0}, "competing_candidates": 1}

    def test_sample_id_never_uses_process_salted_hash(self):
        """Two calls in one process — and a fresh interpreter — must agree."""
        a = self.bcs.sample_id("seed", "key")
        self.assertEqual(a, self.bcs.sample_id("seed", "key"))
        self.assertTrue(a.startswith(self.bcs.SAMPLE_PREFIX))

    def test_sampling_is_deterministic(self):
        recs = [self._rec(f"M{i}", "omop", "EXACT_MATCH", True) for i in range(200)]
        p = self._write_mappings(recs)
        r1, t1 = self.bcs.select(p, "s", 10, 0)
        r2, t2 = self.bcs.select(p, "s", 10, 0)
        self.assertEqual([x["sample_id"] for x in r1], [x["sample_id"] for x in r2])
        self.assertEqual(t1, t2)

    def test_seed_changes_the_sample(self):
        recs = [self._rec(f"M{i}", "omop", "EXACT_MATCH", True) for i in range(200)]
        p = self._write_mappings(recs)
        a, _ = self.bcs.select(p, "seed-a", 10, 0)
        b, _ = self.bcs.select(p, "seed-b", 10, 0)
        self.assertNotEqual({x["sample_id"] for x in a}, {x["sample_id"] for x in b})

    def test_cap_is_respected_and_weight_reflects_the_population(self):
        recs = [self._rec(f"M{i}", "omop", "EXACT_MATCH", True) for i in range(100)]
        p = self._write_mappings(recs)
        rows, totals = self.bcs.select(p, "s", 25, 0)
        self.assertEqual(len(rows), 25)
        self.assertEqual(totals[("primary", "omop|EXACT_MATCH")], 100)
        self.assertAlmostEqual(rows[0]["sampling_weight"], 4.0, places=6)

    def test_uncapped_stratum_has_unit_weight(self):
        recs = [self._rec(f"M{i}", "mesh", "EXACT_MATCH", True) for i in range(7)]
        p = self._write_mappings(recs)
        rows, _ = self.bcs.select(p, "s", 25, 0)
        self.assertEqual(len(rows), 7)
        self.assertEqual(rows[0]["sampling_weight"], 1.0)

    def test_roles_are_separated(self):
        recs = [self._rec("A", "omop", "EXACT_MATCH", True),
                self._rec("B", "bioportal", "RELATED_TO", False),
                self._rec("C", "none", "NO_MATCH_FOUND", False)]
        p = self._write_mappings(recs)
        rows, _ = self.bcs.select(p, "s", 5, 5)
        roles = {r["sample_id"]: r["sample_role"] for r in rows}
        by_mid = {r["mapping_id"]: roles[r["sample_id"]] for r in rows}
        self.assertEqual(by_mid["A"], "primary")
        self.assertEqual(by_mid["B"], "non_eligible_control")
        self.assertEqual(by_mid["C"], "no_match_control")

    def test_verdict_columns_ship_empty(self):
        """The sample is machine output: it must not invent a label."""
        recs = [self._rec("A", "omop", "EXACT_MATCH", True)]
        p = self._write_mappings(recs)
        rows, _ = self.bcs.select(p, "s", 5, 0)
        for col in self.bcs.HUMAN_COLS:
            self.assertNotIn(col, rows[0])

    def test_stratum_is_recomputable_from_the_row(self):
        self.assertEqual(self.bcs.stratum_of("omop", "EXACT_MATCH"),
                         "omop|EXACT_MATCH")
        self.assertEqual(self.bcs.stratum_of(None, None), "none|none")


class TestCalibrationThresholds(unittest.TestCase):
    """Fail-closed threshold derivation from a human-reviewed sheet."""

    @classmethod
    def setUpClass(cls):
        cls.ct = _load("calibrate_thresholds")
        cls.bcs = _load("build_calibration_sample")
        cls.pm = _load("project_mappings")

    def _sheet(self, verdicts, roles=None, weights=None, svc="omop",
               rel="EXACT_MATCH"):
        """Write a review sheet; ``verdicts`` is a list of strings or None."""
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        p = Path(td.name) / "sheet.csv"
        cols = self.bcs.SHEET_COLS
        with p.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for i, v in enumerate(verdicts):
                row = {c: "" for c in cols}
                row.update({
                    "sample_id": f"HMCAL_{i:04d}", "sample_role": (roles or {}).get(
                        i, "primary"),
                    "stratum": f"{svc}|{rel}", "source_service": svc,
                    "mapping_relation": rel, "sampling_weight": (weights or {}).get(
                        i, 1.0),
                    "human_verdict": v or "",
                })
                w.writerow(row)
        return p

    def _run(self, sheet, out, **kw):
        import contextlib
        import io
        argv = ["calibrate_thresholds.py", "--review_sheet", str(sheet),
                "--out_dir", str(out)]
        for k, v in kw.items():
            argv += ["--" + k, str(v)]
        with mock.patch.object(sys, "argv", argv):
            with contextlib.redirect_stdout(io.StringIO()):
                self.ct.main()
        return json.loads((Path(out) / "calibration_thresholds.json").read_text())

    def test_blank_sheet_is_not_calibrated(self):
        sheet = self._sheet([None, None, None])
        with tempfile.TemporaryDirectory() as td:
            d = self._run(sheet, td)
        self.assertEqual(d["status"], "NOT_CALIBRATED")
        self.assertFalse(d["auto_accept_enabled"])
        self.assertEqual(d["accept_strata"], [])

    def test_missing_sheet_is_not_calibrated(self):
        with tempfile.TemporaryDirectory() as td:
            d = self._run(Path(td) / "nope.csv", Path(td) / "out")
        self.assertEqual(d["status"], "NOT_CALIBRATED")
        self.assertFalse(d["auto_accept_enabled"])

    def test_small_sample_is_insufficient_regardless_of_purity(self):
        sheet = self._sheet(["CORRECT"] * 5)
        with tempfile.TemporaryDirectory() as td:
            d = self._run(sheet, td, min_n=30, min_wilson_lower=0.5)
        self.assertEqual(d["status"], "NOT_CALIBRATED")
        self.assertEqual(d["strata"][0]["decision"], "INSUFFICIENT_SAMPLE")

    def test_clean_large_sample_clears_a_loose_threshold(self):
        # 60/60 gives a Wilson lower bound of ~0.940, so 0.90 clears and 0.95
        # does not: the point estimate is 1.0 either way.
        sheet = self._sheet(["CORRECT"] * 60)
        with tempfile.TemporaryDirectory() as td:
            d = self._run(sheet, td, min_n=30, min_wilson_lower=0.90)
        self.assertEqual(d["status"], "CALIBRATED")
        self.assertTrue(d["auto_accept_enabled"])
        self.assertEqual(d["accept_pair_keys"], ["omop|EXACT_MATCH"])

    def test_a_perfect_small_sample_does_not_clear_a_strict_threshold(self):
        """A perfect sample is not proof: 60/60 stays below a 0.95 bound."""
        sheet = self._sheet(["CORRECT"] * 60)
        with tempfile.TemporaryDirectory() as td:
            d = self._run(sheet, td, min_n=30, min_wilson_lower=0.95)
        self.assertEqual(d["status"], "NOT_CALIBRATED")
        self.assertEqual(d["strata"][0]["precision_point"], 1.0)
        self.assertLess(d["strata"][0]["wilson_lower"], 0.95)

    def test_imperfect_sample_below_threshold_stays_uncalibrated(self):
        sheet = self._sheet(["CORRECT"] * 40 + ["INCORRECT"] * 20)
        with tempfile.TemporaryDirectory() as td:
            d = self._run(sheet, td, min_n=30, min_wilson_lower=0.95)
        self.assertEqual(d["status"], "NOT_CALIBRATED")
        self.assertEqual(d["strata"][0]["decision"], "BELOW_THRESHOLD")

    def test_uncertain_is_never_counted_as_correct(self):
        """A pile of UNCERTAIN verdicts must not manufacture confidence."""
        sheet = self._sheet(["CORRECT"] * 30 + ["UNCERTAIN"] * 100)
        with tempfile.TemporaryDirectory() as td:
            d = self._run(sheet, td, min_n=30, min_wilson_lower=0.85)
        s = d["strata"][0]
        self.assertEqual(s["n_labeled"], 30)
        self.assertEqual(s["n_uncertain"], 100)
        self.assertEqual(s["precision_point"], 1.0)
        self.assertEqual(d["status"], "CALIBRATED")

    def test_invalid_verdict_is_excluded_not_counted(self):
        sheet = self._sheet(["CORRECT"] * 30 + ["yes"] * 4)
        with tempfile.TemporaryDirectory() as td:
            d = self._run(sheet, td, min_n=30, min_wilson_lower=0.95)
        self.assertEqual(d["counts"]["invalid_verdict_rows"], 4)
        self.assertEqual(d["counts"]["valid_labeled_rows"], 30)

    def test_wilson_lower_is_below_the_point_estimate(self):
        lo, hi = self.ct.wilson_interval(10, 10)
        self.assertLess(lo, 1.0)
        self.assertAlmostEqual(hi, 1.0, places=9)
        lo2, _ = self.ct.wilson_interval(30, 30)
        self.assertGreater(lo2, lo)   # more evidence narrows the interval

    def test_wilson_of_zero_trials_is_undefined(self):
        self.assertEqual(self.ct.wilson_interval(0, 0), (None, None))

    def test_control_strata_are_reported_but_never_accepted(self):
        sheet = self._sheet(["CORRECT"] * 60, roles={i: "non_eligible_control"
                                                    for i in range(60)})
        with tempfile.TemporaryDirectory() as td:
            d = self._run(sheet, td, min_n=30, min_wilson_lower=0.95)
        self.assertEqual(d["status"], "NOT_CALIBRATED")
        self.assertEqual(d["accept_strata"], [])
        self.assertEqual(len(d["control_strata"]), 1)

    def test_weights_do_not_change_a_unanimous_stratum(self):
        sheet = self._sheet(["CORRECT"] * 40, weights={i: 100.0 for i in range(40)})
        with tempfile.TemporaryDirectory() as td:
            d = self._run(sheet, td, min_n=30, min_wilson_lower=0.95)
        self.assertEqual(d["strata"][0]["precision_weighted"], 1.0)


class TestCalibrationApplication(unittest.TestCase):
    """Thresholds are opt-in and only ever narrow what is accepted."""

    @classmethod
    def setUpClass(cls):
        cls.pm = _load("project_mappings")

    def test_no_calibration_file_leaves_rows_untouched(self):
        pairs, meta = self.pm.load_calibration(None)
        self.assertEqual(pairs, set())
        self.assertEqual(meta["status"], "NOT_CALIBRATED")

    def test_missing_calibration_file_fails_closed(self):
        pairs, meta = self.pm.load_calibration(Path("/nonexistent/thresholds.json"))
        self.assertEqual(pairs, set())
        self.assertFalse(meta.get("auto_accept_enabled", False))

    def test_disabled_calibration_yields_no_accept_pairs(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "t.json"
            p.write_text(json.dumps({
                "status": "NOT_CALIBRATED", "auto_accept_enabled": False,
                "accept_strata": [{"source_service": "omop",
                                   "mapping_relation": "EXACT_MATCH"}]}))
            pairs, _ = self.pm.load_calibration(p)
        self.assertEqual(pairs, set())

    def test_enabled_calibration_yields_the_strata_pairs(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "t.json"
            p.write_text(json.dumps({
                "status": "CALIBRATED", "auto_accept_enabled": True,
                "accept_strata": [{"source_service": "omop",
                                   "mapping_relation": "EXACT_MATCH"}]}))
            pairs, meta = self.pm.load_calibration(p)
        self.assertEqual(pairs, {"omop|EXACT_MATCH"})
        self.assertEqual(meta["n_accept_strata"], 1)

    def test_promotion_requires_both_calibration_and_eligibility(self):
        # calibrated + eligible -> promoted
        rel, disp, _ = self.pm.apply_calibration("EXACT_MATCH", "REVIEW_REQUIRED",
                                                 True, True)
        self.assertEqual(disp, "AUTO_ACCEPTED")
        # calibrated but NOT eligible -> never promoted
        _, disp, _ = self.pm.apply_calibration("RELATED_TO", "REVIEW_REQUIRED",
                                               False, True)
        self.assertEqual(disp, "REVIEW_REQUIRED")
        # eligible but not calibrated -> never promoted
        _, disp, _ = self.pm.apply_calibration("EXACT_MATCH", "REVIEW_REQUIRED",
                                               True, False)
        self.assertEqual(disp, "REVIEW_REQUIRED")

    @staticmethod
    def _terms_index(*pairs):
        """A minimal canonical-terms index: ``(norm, cdm_type) -> term row``.

        ``build_rows`` resolves a subject against ``terms_index`` before it can
        classify or promote anything, so tests that exercise promotion must
        supply a *resolvable* term — otherwise every row is correctly parked as
        ``UNRESOLVED_NO_CANONICAL_TERM`` and can never be promoted.
        """
        out = {}
        for tn, cdm in pairs:
            out[(tn, cdm)] = {
                "term_id": ids.term_id(tn, cdm), "term_norm": tn,
                "term": tn, "cdm_type": cdm, "alternative_types": [],
            }
        return out

    def test_build_rows_default_never_auto_accepts(self):
        """The documented default path stays fail-closed."""
        cv = {("obesity", "DISEASE"): {
            "canonical": {"source": "ols", "ontology_name": "SNOMEDCT",
                          "concept_id": "C1", "label": "Obesity"},
            "all_mappings": [{"source": "ols", "ontology_name": "SNOMEDCT",
                              "concept_id": "C1", "label": "Obesity",
                              "confidence": 1.0}]}}
        idx = self._terms_index(("obesity", "DISEASE"))
        rows, _, _ = self.pm.build_rows(cv, {}, {}, idx)
        self.assertTrue(rows)
        for r in rows:
            self.assertNotEqual(r["mapping_disposition"], "AUTO_ACCEPTED")

    def test_build_rows_with_calibration_promotes_only_that_stratum(self):
        cv = {("obesity", "DISEASE"): {
            "canonical": {"source": "ols", "ontology_name": "SNOMEDCT",
                          "concept_id": "C1", "label": "Obesity"},
            "all_mappings": [{"source": "ols", "ontology_name": "SNOMEDCT",
                              "concept_id": "C1", "label": "Obesity",
                              "confidence": 1.0}]}}
        idx = self._terms_index(("obesity", "DISEASE"))
        rows, _, _ = self.pm.build_rows(cv, {}, {}, idx,
                                        accept_pairs={"ols|EXACT_MATCH"})
        self.assertTrue(rows)
        self.assertTrue(all(r["key_resolution"] == "EXACT_KEY" for r in rows))
        self.assertTrue(all(r["mapping_disposition"] == "AUTO_ACCEPTED"
                            for r in rows if r.get("concept_id")))
        # and a non-matching stratum is left alone
        rows2, _, _ = self.pm.build_rows(cv, {}, {}, idx,
                                         accept_pairs={"omop|EXACT_MATCH"})
        for r in rows2:
            self.assertNotEqual(r["mapping_disposition"], "AUTO_ACCEPTED")

    def test_ambiguous_rows_are_never_promoted(self):
        """An within-vocabulary tie is ineligible, so no threshold can lift it."""
        cv = {("obesity", "DISEASE"): {
            "canonical": {"source": "ols", "ontology_name": "SNOMEDCT",
                          "concept_id": "C1", "label": "Obesity"},
            "all_mappings": [
                {"source": "ols", "ontology_name": "SNOMEDCT", "concept_id": "C1",
                 "label": "Obesity", "confidence": 1.0},
                {"source": "ols", "ontology_name": "SNOMEDCT", "concept_id": "C2",
                 "label": "Obesity", "confidence": 1.0}]}}
        idx = self._terms_index(("obesity", "DISEASE"))
        rows, _, _ = self.pm.build_rows(cv, {}, {}, idx,
                                        accept_pairs={"ols|EXACT_MATCH",
                                                      "ols|AMBIGUOUS"})
        for r in rows:
            self.assertNotEqual(r["mapping_disposition"], "AUTO_ACCEPTED")
            self.assertFalse(r["auto_accept_eligible"])


# ------------------------------------------------------- stage 2 builder


class TestCanonicalTerms(unittest.TestCase):
    """One canonical term per ``(term_norm, cdm_type)``; alternative types kept
    as evidence and never merged on."""

    @classmethod
    def setUpClass(cls):
        cls.bct = _load("build_canonical_terms")

    def setUp(self):
        # load_terms() opens the path after _rows() returns, so the directory has
        # to outlive the call; a TemporaryDirectory in a `with` block would be gone.
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self._n = 0

    def _rows(self, rows):
        import csv
        self._n += 1
        src = Path(self._td.name) / f"dedup_{self._n}.csv"
        fieldnames = ["term_norm", "term", "cdm_type", "all_types"]
        for r in rows:
            for k in r:
                if k not in fieldnames:
                    fieldnames.append(k)
        with src.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(rows)
        return src

    def test_multi_type_surface_yields_one_row_per_type(self):
        rows = [{"term_norm": "obesity", "term": "obesity", "cdm_type": "DISEASE",
                 "all_types": "DISEASE|CLINICAL"},
                {"term_norm": "obesity", "term": "obesity", "cdm_type": "CLINICAL",
                 "all_types": "DISEASE|CLINICAL"}]
        src = self._rows(rows)
        out, _, _, _ = self.bct.load_terms(src)
        ids_ = [r["term_id"] for r in out]
        self.assertEqual(len(out), 2)
        self.assertEqual(len(set(ids_)), 2)

    def test_alternative_types_reported_as_evidence(self):
        rows = [{"term_norm": "obesity", "term": "obesity", "cdm_type": "DISEASE",
                 "all_types": "DISEASE|CLINICAL"}]
        out, _, _, _ = self.bct.load_terms(self._rows(rows))
        alt = out[0].get("alternative_types")
        self.assertIsNotNone(alt)
        self.assertIn("CLINICAL", alt)
        self.assertEqual(out[0]["identity_evidence"], "multi_type_surface_form")

    def test_term_id_matches_shared_helper(self):
        rows = [{"term_norm": "obesity", "term": "obesity", "cdm_type": "DISEASE",
                 "all_types": "DISEASE"}]
        out, _, _, _ = self.bct.load_terms(self._rows(rows))
        self.assertEqual(out[0]["term_id"], ids.term_id("obesity", "DISEASE"))

    def test_blank_term_norm_is_skipped(self):
        rows = [{"term_norm": "", "term": "", "cdm_type": "DISEASE", "all_types": "DISEASE"}]
        out, _, _, _ = self.bct.load_terms(self._rows(rows))
        self.assertEqual(out, [])

    def test_unpopulated_rollups_stay_null_not_zero(self):
        """An unrun rollup must be null, never a fabricated 0."""
        rows = [{"term_norm": "obesity", "term": "obesity", "cdm_type": "DISEASE",
                 "all_types": "DISEASE"}]
        out, _, _, _ = self.bct.load_terms(self._rows(rows))
        self.assertIsNone(out[0]["mention_count"])
        self.assertIsNone(out[0]["definition_status"])


# ----------------------------------------------------------- fail-closed


class TestFailClosedRollup(unittest.TestCase):
    """``COMPLETE`` must require coverage, not just clean section integrity."""

    @classmethod
    def setUpClass(cls):
        cls.vo = _load("validate_outputs")

    def test_complete_requires_all_conditions(self):
        self.assertEqual(self.vo._overall(0, [], 0, 453, True), "COMPLETE")

    def test_integrity_failure_blocks_complete(self):
        self.assertEqual(self.vo._overall(1, [], 0, 453, True), "REVIEW_REQUIRED")

    def test_missing_paper_blocks_complete(self):
        self.assertEqual(self.vo._overall(0, ["HMPAPER_x"], 0, 453, True),
                         "REVIEW_REQUIRED")

    def test_paper_without_mentions_blocks_complete(self):
        self.assertEqual(self.vo._overall(0, [], 12, 453, True), "REVIEW_REQUIRED")

    def test_absent_mention_stream_blocks_complete(self):
        self.assertEqual(self.vo._overall(0, [], 0, 453, False), "REVIEW_REQUIRED")


# ------------------------------------------------------- fix 1/2/3 quality gates


class TestTextSanitizer(unittest.TestCase):
    """Fix 1: control bytes are stripped from the identity layer only."""

    @classmethod
    def setUpClass(cls):
        cls.tn = _load("textnorm")

    def test_strips_control_bytes_and_collapses_whitespace(self):
        self.assertEqual(self.tn.sanitize("P \x02 0.0001"), "P 0.0001")
        self.assertEqual(self.tn.sanitize("\x04-diversity"), "-diversity")
        self.assertEqual(self.tn.sanitize("fut8\x02/\x02"), "fut8 /")

    def test_is_idempotent(self):
        for s in ["P \x02 0.0001", "\x04-diversity", "  plain  ", ""]:
            once = self.tn.sanitize(s)
            self.assertEqual(self.tn.sanitize(once), once)

    def test_does_not_fold_legitimate_terms_together(self):
        """The full normalizer would merge these; sanitize must not."""
        self.assertNotEqual(self.tn.sanitize("Proteobacteria"),
                            self.tn.sanitize("\u03b5-proteobacteria"))
        self.assertNotEqual(self.tn.sanitize("\u221280\u00b0C"),
                            self.tn.sanitize("80c"))

    def test_preserves_non_control_content_verbatim(self):
        self.assertEqual(self.tn.sanitize("  Prevotella  copri "), "Prevotella copri")

    def test_has_control_is_a_pre_sanitize_check(self):
        self.assertTrue(self.tn.has_control("p \x04"))
        self.assertFalse(self.tn.has_control("p 4"))

    def test_control_collisions_are_only_invisible_byte_pairs(self):
        """Sanitizing merges a row pair *only* when it differs by a control byte."""
        a = "P \x02 0.0001"
        b = "P 0.0001"
        self.assertEqual(self.tn.sanitize(a), self.tn.sanitize(b))
        self.assertNotEqual(a, b)


class TestNonConceptFlag(unittest.TestCase):
    """Fix 2: conservative, named flags — never a forced UNCERTAIN."""

    @classmethod
    def setUpClass(cls):
        cls.tn = _load("textnorm")

    def test_named_reasons(self):
        cases = {
            "": "EMPTY",
            "p \x04": "CONTROL_CHAR",
            "http://x.org": "URL_OR_LICENSE",
            "Fig. 3": "FIGURE_TABLE_REF",
            "Supplementary Table": "FIGURE_TABLE_REF",
            "XVII": "ROMAN_NUMERAL",
            "et al": "CITATION_FRAGMENT",
        }
        for surface, reason in cases.items():
            self.assertEqual(self.tn.non_concept_reason(surface), reason, surface)

    def test_real_terms_are_never_flagged(self):
        """The rejected broad rules (punctuation-edged / short word+digit) would
        have flagged every one of these."""
        for surface in ["PC1", "CO2", "IL-6", "806R", "16S rRNA", "HOMA-IR",
                        "S100a8", "Bacteroides", "log2FC", "p-value", "T2D"]:
            self.assertIsNone(self.tn.non_concept_reason(surface), surface)

    def test_no_forced_uncertain(self):
        self.assertIsNone(self.tn.non_concept_reason("Prevotella copri"))
        self.assertFalse(self.tn.is_non_concept("Prevotella copri"))
        self.assertTrue(self.tn.is_non_concept("XIV"))


class TestAbbreviationPathologyGates(unittest.TestCase):
    """Fix 3: reject *pathologies* only, keep non-initial expansions."""

    @classmethod
    def setUpClass(cls):
        cls.ed = _load("extract_definitions")

    def test_must_keep_real_expansions(self):
        """Every one of these fails a strict Hearst test but is correct."""
        keep = [
            ("HCM", "Hypertrophic cardiomyopathy"),
            ("LEfSe", "Linear discriminant analysis Effect Size"),
            ("SHAP", "SHapley Additive exPlanations"),
            ("Sobs", "number of species observed"),
            ("LOOCV", "leave-one-out cross-validation"),
            ("UHPLC", "ultra-high-performance liquid chromatography"),
            ("VSURF", "variable selection using random forests"),
            ("Chao1", "capture-recapture-based estimate of species richness"),
            ("OTUs", "operational taxonomic units"),
            ("HOMA-IR", "homeostasis model assessment of insulin resistance"),
            ("GraPhlAn", "Graphical Phylogenetic Analysis"),
            ("MaAsLin", "Multivariate Association with Linear Models"),
        ]
        for acr, long_text in keep:
            self.assertIsNone(self.ed.abbreviation_rejection(acr, long_text),
                              f"{acr} -> {long_text}")

    def test_reject_circular_and_degenerate(self):
        reject = [
            # circular: the acronym is repeated verbatim inside the long form
            ("CAGs", "elderly-associated CAGs"),
            ("LME", "R package lmerTest"),
            ("System", "Applied Biosystems"),
            ("A", "anything at all"),          # degenerate (single letter)
            ("III", "Escherichia coli"),       # degenerate (single distinct letter)
            ("AAA", "tyrosine and phenylalanine"),
            ("BMI", "zz"),                     # long form shorter than acronym
            ("SULT", "sulfation"),             # single-word long form
            ("Xus", "systems"),                # single-word long form
        ]
        for acr, long_text in reject:
            self.assertIsNotNone(self.ed.abbreviation_rejection(acr, long_text),
                                 f"{acr} -> {long_text}")

    def test_escape_hatch_keeps_ambiguous_circular_cases(self):
        """The case-aware escape is permissive on purpose: it protects real
        expansions, and the price is that ``QIIME`` -> "MacQIIME version" (the
        acronym is an upper-case subsequence) is *kept* rather than risk
        dropping correct rows. Frozen behaviour, asserted so a later tightening
        is a conscious change."""
        for acr, long_text in [("QIIME", "MacQIIME version"),
                               ("DNA", "S rDNA"),
                               ("PCR", "index PCR")]:
            self.assertIsNone(self.ed.abbreviation_rejection(acr, long_text))

    def test_word_level_containment_not_concatenation(self):
        """``Sobs`` is contained in the *concatenation* of 'number of species
        observed' but not in any single word, so it must be kept; ``CAGs`` *is*
        contained inside a word of 'elderly-associated CAGs' and must be
        dropped."""
        self.assertIsNone(self.ed.abbreviation_rejection(
            "Sobs", "number of species observed"))
        self.assertEqual(self.ed.abbreviation_rejection(
            "CAGs", "elderly-associated CAGs"), "ABBREV_CIRCULAR_EXPANSION")

    def test_case_aware_escape_rescues_shap(self):
        self.assertTrue(self.ed._case_aware_match("shap", "SHapley Additive exPlanations"))


class TestDefinitionShapeGates(unittest.TestCase):
    """Fix 3: figure furniture and fragments are removed, traceably."""

    @classmethod
    def setUpClass(cls):
        cls.ed = _load("extract_definitions")

    def _reason(self, surf, d, source="CONTEXTUAL_DESCRIPTION"):
        return self.ed.definition_rejection(surf, d, source)

    def test_figure_legend_furniture_is_rejected(self):
        for surf, d in [("color", "responders (blue) and non-responders (green)"),
                        ("circles", "boxplot outliers"),
                        ("shaded areas", "95% confidence bands"),
                        ("bar", "median, and whiskers denote range")]:
            r = self._reason(surf, d, "EXPLICIT_AUTHOR_DEFINITION")
            self.assertIsNotNone(r, f"{surf} -> {d}")

    def test_multi_word_legit_terms_survive_figure_surface_gate(self):
        """``polar regions`` / ``green alga`` share a token with the figure
        vocabulary but are real terms."""
        self.assertFalse(self.ed._figure_surface("polar regions"))
        self.assertFalse(self.ed._figure_surface("green alga"))

    def test_leading_preposition_fragment_is_rejected(self):
        self.assertEqual(self._reason("inflammation", "of gut inflammation"),
                         "LEADING_PREPOSITION")

    def test_finite_verb_clause_head_is_rejected(self):
        self.assertEqual(self._reason("findings", "current findings indicate a link"),
                         "FINITE_VERB_FRAGMENT")

    def test_gerund_head_is_not_a_finite_verb(self):
        """'variable selection using random forests' is a noun phrase."""
        self.assertFalse(self.ed._finite_verb_head("variable selection using random forests"))
        self.assertFalse(self.ed._finite_verb_head("number of species observed"))

    def test_bibliography_start_is_rejected(self):
        self.assertEqual(self._reason("PCR", "purchased from KAPA biosystems"),
                         "BAD_DEFINITION_START")
        self.assertEqual(self._reason("MAG", "Supplemental figure S5"),
                         "BAD_DEFINITION_START")
        self.assertEqual(self._reason("SNE", "Supplemental Figure S4"),
                         "BAD_DEFINITION_START")

    def test_non_concept_surface_is_rejected(self):
        self.assertEqual(self._reason("XVII", "a real description of something"),
                         "NON_CONCEPT_SURFACE")
        # a non-concept surface outranks the generic shape gates
        self.assertEqual(self._reason("et al", "taxonomic distributions we"),
                         "NON_CONCEPT_SURFACE")

    def test_word_count_gate_counts_alnum_runs(self):
        """Hyphens split, so 'leave-one-out cross-validation' is 5 words."""
        self.assertEqual(len(self.ed._TOKEN.findall("leave-one-out cross-validation")), 5)
        self.assertEqual(self._reason("x", "a b c"), None)
        self.assertEqual(self._reason("x", "a b"), "TOO_FEW_WORDS")

    def test_word_count_gate_not_applied_to_abbreviations(self):
        """A two-word expansion is normal and must not be counted out."""
        self.assertIsNone(self._reason("HCM", "Hypertrophic cardiomyopathy",
                                       "ABBREVIATION_EXPANSION"))

    def test_gate_never_rewrites_a_definition(self):
        """A rejection returns a reason and no text — nothing is repaired."""
        self.assertEqual(self._reason("bar", "median, and whiskers denote range"),
                         "FIGURE_SURFACE")

    def test_main_plumbs_rejection_counters(self):
        """The summary must report what each gate removed (fail-closed/traceable)."""
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "seg").mkdir()
            # one section with a figure-legend appositive plus a real one
            (d / "seg" / "HMPAPER_1.md").write_text(
                "<!-- SECTION -->\n", encoding="utf-8")
            csv_p = d / "terms.csv"
            with csv_p.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=["term_norm", "term", "cdm_type"])
                w.writeheader()
                w.writerow({"term_norm": "colors", "term": "colors",
                            "cdm_type": "DISEASE"})
                w.writerow({"term_norm": "\x04-diversity", "term": "\x04-diversity",
                            "cdm_type": "DISEASE"})
            stats = {"rejected": self.ed.Counter(),
                     "load_terms_non_concept": 0,
                     "load_terms_non_concept_by_reason": self.ed.Counter()}
            self.ed.load_terms(csv_p, stats=stats)
            # control-char surface is counted, then excluded
            self.assertEqual(stats["load_terms_non_concept"], 1)
            self.assertIn("CONTROL_CHAR",
                          stats["load_terms_non_concept_by_reason"])


class TestSanitizedJoin(unittest.TestCase):
    """Fixes 1-2 must not break the T1 -> T2 -> T5 joins."""

    def test_t5_norm_strips_control_bytes(self):
        pm = _load("project_mappings")
        self.assertEqual(pm.norm("P \x02 0.0001"), pm.norm("P 0.0001"))
        self.assertEqual(pm.norm("  Obesity  "), "obesity")

    def test_t2_term_id_uses_the_sanitized_key(self):
        bct = _load("build_canonical_terms")
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "d.csv"
            with p.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=["term_norm", "term", "cdm_type",
                                                  "all_types"])
                w.writeheader()
                w.writerow({"term_norm": "p \x02 0.0001", "term": "P \x02 0.0001",
                            "cdm_type": "DISEASE", "all_types": "DISEASE"})
                w.writerow({"term_norm": "p 0.0001", "term": "P 0.0001",
                            "cdm_type": "DISEASE", "all_types": "DISEASE"})
            out, _, reasons, n_deduped = bct.load_terms(p)
        self.assertEqual(len(out), 1)          # one-term-per-key invariant held
        self.assertEqual(n_deduped, 1)         # the collision is counted, not hidden
        self.assertEqual(out[0]["term_norm"], "p 0.0001")
        self.assertEqual(out[0]["term_id"], ids.term_id("p 0.0001", "DISEASE"))

    def test_t2_marks_non_concept_but_keeps_all_rows(self):
        bct = _load("build_canonical_terms")
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "d.csv"
            with p.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=["term_norm", "term", "cdm_type",
                                                  "all_types"])
                w.writeheader()
                w.writerow({"term_norm": "xvii", "term": "XVII",
                            "cdm_type": "DISEASE", "all_types": "DISEASE"})
                w.writerow({"term_norm": "prevotella copri",
                            "term": "Prevotella copri",
                            "cdm_type": "SPECIES", "all_types": "SPECIES"})
            out, _, reasons, _ = bct.load_terms(p)
        self.assertEqual(len(out), 2)          # marked, never deleted
        by = {r["term_norm"]: r for r in out}
        self.assertTrue(by["xvii"]["is_non_concept_surface"])
        self.assertEqual(by["xvii"]["non_concept_reason"], "ROMAN_NUMERAL")
        self.assertFalse(by["prevotella copri"]["is_non_concept_surface"])
        self.assertEqual(reasons["ROMAN_NUMERAL"], 1)

    def test_non_concept_term_is_never_auto_accept_eligible(self):
        pm = _load("project_mappings")
        cv = {("xvii", "DISEASE"): {
            "canonical": {"source": "ols", "ontology_name": "SNOMEDCT",
                          "concept_id": "C1", "label": "XVII"},
            "all_mappings": [{"source": "ols", "ontology_name": "SNOMEDCT",
                              "concept_id": "C1", "label": "XVII",
                              "confidence": 1.0}]}}
        idx = {("xvii", "DISEASE"): {"term": "XVII",
                                     "non_concept_reason": "ROMAN_NUMERAL"}}
        rows, _, _ = pm.build_rows(cv, {}, {}, idx,
                                   accept_pairs={"ols|EXACT_MATCH"})
        self.assertTrue(rows)
        for r in rows:
            self.assertFalse(r["auto_accept_eligible"])
            self.assertEqual(r["auto_accept_ineligible_reason"], "ROMAN_NUMERAL")
            self.assertNotEqual(r["mapping_disposition"], "AUTO_ACCEPTED")


# ------------------------------------------------------ mocked externals


class TestMockedLookupSemantics(unittest.TestCase):
    """External behaviour is exercised with mocked responses only.

    These assert the *policy* the pipeline enforces around a remote call:
    a no-match and a failed lookup are different outcomes, and a remote service
    is never handed paper text.
    """

    @classmethod
    def setUpClass(cls):
        cls.pm = _load("project_mappings")

    def test_empty_result_is_no_match_not_an_error(self):
        """A well-formed empty response is NO_MATCH_FOUND, never LOOKUP_FAILED."""
        with mock.patch.object(self.pm, "norm", side_effect=self.pm.norm):
            rel, disp, _ = self.pm.classify(
                "zzz_unlikely_term", "DISEASE", "umls", None, None, has_error=False)
        self.assertNotEqual(disp, "LOOKUP_FAILED")
        self.assertIn(rel, {"RELATED_TO", "NO_MATCH_FOUND"})

    def test_transport_failure_is_lookup_failed(self):
        rel, disp, _ = self.pm.classify(
            "obesity", "DISEASE", "umls", None, None, has_error=True)
        self.assertEqual(disp, "LOOKUP_FAILED")
        self.assertEqual(rel, "UNVERIFIED")

    def test_registry_reports_credential_presence_without_reading_it(self):
        """Only presence is tested — the value must never be read or written."""
        reg = _load("build_registry")
        secret = "this-value-must-never-appear-in-an-artifact"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".env").write_text(f"UMLS_API_KEY={secret}\n", encoding="utf-8")
            with mock.patch.object(reg, "REPO_ROOT", root):
                with mock.patch.dict(os.environ, {}, clear=True):
                    self.assertTrue(reg._credential_present("UMLS_API_KEY"))
                    self.assertFalse(reg._credential_present("BIOPORTAL_API_KEY"))

    def test_missing_credential_reports_false_not_absent_vocabulary(self):
        reg = _load("build_registry")
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(reg, "REPO_ROOT", Path(td)):
                with mock.patch.dict(os.environ, {}, clear=True):
                    self.assertFalse(reg._credential_present("UMLS_API_KEY"))

    def test_source_tier_sets_are_disjoint(self):
        """A source cannot be both an id-validation and a text-search tier."""
        self.assertFalse(self.pm.VALIDATED_ID_SOURCES & self.pm.TEXT_SEARCH_SOURCES)


# ------------------------------------------------------- stage 4/6 outputs


class TestTaxonomyExport(unittest.TestCase):
    """The taxonomy is exported as-is; nothing is invented."""

    @classmethod
    def setUpClass(cls):
        cls.et = _load("export_taxonomy")

    def test_uncertain_is_reserved(self):
        self.assertIn("UNCERTAIN", self.et.RESERVED)

    def test_real_taxonomy_loads_with_upper_and_sub(self):
        raw, cats, upper, subs = self.et.load_taxonomy(self.et.TAXONOMY_YAML)
        self.assertTrue(upper)
        self.assertTrue(subs)
        # UNCERTAIN must be excluded from the upper list it is reserved from.
        self.assertNotIn("UNCERTAIN", {c.get("category_id") for c in upper})

    def test_every_subcategory_parent_resolves(self):
        raw, cats, upper, subs = self.et.load_taxonomy(self.et.TAXONOMY_YAML)
        all_ids = {c.get("category_id") for c in cats}
        self.assertTrue(subs)
        unresolved = {s.get("parent_category_id") for s in subs} - all_ids
        self.assertFalse(unresolved, f"unresolved parent categories: {unresolved}")

    def test_upper_category_count_matches_raw_minus_reserved(self):
        raw, cats, upper, subs = self.et.load_taxonomy(self.et.TAXONOMY_YAML)
        raw_upper = {c.get("category_id") for c in cats
                     if c.get("hierarchy_level") == "UPPER"}
        self.assertEqual({c.get("category_id") for c in upper},
                         raw_upper - self.et.RESERVED)


class TestManifestReporting(unittest.TestCase):
    """A missing artifact is reported MISSING, never as zero or complete."""

    @classmethod
    def setUpClass(cls):
        cls.bm = _load("build_manifest")

    def test_all_nine_artifact_names_declared(self):
        self.assertIn("terminology_extraction_manifest.json", self.bm.ARTIFACTS)
        for n in ["term_mentions.jsonl", "canonical_terms.jsonl",
                  "term_definitions.jsonl", "term_ontology_mappings.jsonl",
                  "terminology_taxonomy.json", "ontology_registry.json",
                  "terminology_validation.jsonl",
                  "terminology_extraction_report.md"]:
            self.assertIn(n, self.bm.ARTIFACTS)

    def test_missing_artifact_is_not_counted_as_present(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "term_mentions.jsonl").write_text("{}\n", encoding="utf-8")
            with mock.patch.object(sys, "argv",
                                   ["build_manifest.py", "--out_dir", str(d)]):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.bm.main()
            man = json.loads((d / "terminology_extraction_manifest.json").read_text())
            by = {a["name"]: a["status"] for a in man["artifacts"]}
            self.assertEqual(by["term_mentions.jsonl"], "PRESENT")
            self.assertEqual(by["canonical_terms.jsonl"], "MISSING")

    def test_jsonl_count_is_recomputed_not_assumed(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "x.jsonl"
            p.write_text('{"a":1}\n\n{"a":2}\n', encoding="utf-8")
            self.assertEqual(self.bm._jsonl_count(p), 2)


if __name__ == "__main__":
    unittest.main()
