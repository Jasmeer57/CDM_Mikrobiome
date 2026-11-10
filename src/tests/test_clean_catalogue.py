#!/usr/bin/env python3
"""Unit tests for the Phase A catalogue cleanup
(src/scripts/vllm_termpop/clean_catalogue.py).

Run from repo root:
    python -m unittest discover -s src/tests -p test_clean_catalogue.py -v

No corpus, network or model needed: each rule is exercised on small inline
records, with a negative case where a rule must NOT fire.
"""
import sys
import unittest
from pathlib import Path

REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
sys.path.insert(0, str(REPO_ROOT / "src" / "scripts" / "vllm_termpop"))

import clean_catalogue as cc  # noqa: E402


def _rec(entity, rid, paper="HMPAPER_000001", verified=1, **fields):
    f = {cc.ID_FIELD[entity]: rid, "paper_id": paper, "evidence_text": "", "notes": ""}
    f.update(fields)
    f.setdefault("v3_status", "KEPT")
    f.setdefault("merged_from", "")
    return {"entity_type": entity, "paper_id": paper, "evidence_verified": verified, "fields": f}


class TestPlaceholders(unittest.TestCase):
    def test_integer_zero_blanked(self):
        self.assertEqual(cc.clean_value("participant_count", 0, "")[0], "")
        self.assertEqual(cc.clean_value("inclusion_criteria", 0, "")[0], "")

    def test_placeholder_strings_blanked(self):
        for v in ("N/A", "not stated", "NOT_SPECIFIED", "none", "Not reported."):
            self.assertEqual(cc.clean_value("country_or_region", v, "")[0], "", v)

    def test_vocabulary_tokens_kept(self):
        self.assertEqual(cc.clean_value("original_or_reused", "UNKNOWN", "")[0], "UNKNOWN")
        self.assertEqual(cc.clean_value("longitudinal", "NOT_APPLICABLE", "")[0], "NOT_APPLICABLE")

    def test_zero_effect_kept_only_when_stated(self):
        self.assertEqual(cc.clean_value("effect_estimate", 0, "a change of 0 was seen")[0], "0")
        self.assertEqual(cc.clean_value("effect_estimate", 0, "no numbers here")[0], "")
        self.assertEqual(cc.clean_value("p_value", 0, "p = 0")[0], "")

    def test_non_integer_count_blanked(self):
        self.assertEqual(cc.clean_value("participant_count", 23.2, "")[0], "")
        self.assertEqual(cc.clean_value("participant_count", 40.0, "")[0], 40)

    def test_dict_serialised(self):
        v, _ = cc.clean_value("p_value", {"male": 0.01}, "")
        self.assertEqual(v, '{"male": 0.01}')


class TestDirection(unittest.TestCase):
    def test_normalise(self):
        self.assertEqual(cc.normalise_direction("increase"), "INCREASE")
        self.assertEqual(cc.normalise_direction("decrease; increase"), "MIXED")
        self.assertEqual(cc.normalise_direction(""), "NOT_STATED")
        self.assertEqual(cc.normalise_direction("n/a"), "NOT_STATED")
        self.assertEqual(cc.normalise_direction("no change"), "NO_ASSOCIATION")

    def test_flags(self):
        self.assertEqual(cc.direction_flag("INCREASE", "SFB prevalence was not significantly different"),
                         "NONSIGNIFICANCE_WORDING")
        self.assertEqual(cc.direction_flag("INCREASE", "Shannon diversity was reduced in cases"),
                         "OPPOSITE_WORDING")
        self.assertEqual(cc.direction_flag("NOT_STATED", "Prevotella was enriched in cases"),
                         "DIRECTION_RECOVERABLE")
        self.assertEqual(cc.direction_flag("INCREASE", "Prevotella was enriched in cases"), "")


class TestFindingSource(unittest.TestCase):
    def test_sections(self):
        self.assertEqual(cc.finding_source("3. Results > Diversity"), "RESULT")
        self.assertEqual(cc.finding_source("Introduction"), "BACKGROUND")
        self.assertEqual(cc.finding_source("References"), "REFERENCES")
        self.assertEqual(cc.finding_source("Acknowledgments"), "BACKMATTER")
        self.assertEqual(cc.finding_source("1272"), "UNKNOWN")

    def test_citations(self):
        self.assertTrue(cc.CITATION.search("suffer from gut microbiota dysbiosis17- 20, which"))
        self.assertTrue(cc.CITATION.search("as shown before [12, 14]"))
        self.assertTrue(cc.CITATION.search("Cherbuy et al. (2019) found"))
        self.assertIsNone(cc.CITATION.search("the V3-V4 region of 16S rRNA in CD4 cells"))

    def test_primary_verdict(self):
        self.assertEqual(cc.primary_verdict("RESULT", False), "YES")
        self.assertEqual(cc.primary_verdict("RESULT", True), "NO")
        self.assertEqual(cc.primary_verdict("DISCUSSION", False), "REVIEW")
        self.assertEqual(cc.primary_verdict("BACKGROUND", False), "NO")


class TestAccessions(unittest.TestCase):
    def test_find(self):
        ids = cc.find_accessions("Data are in SRA (PRJNA644520; SRR1234567) and Qiita study 10317")
        self.assertEqual([a for _, a in ids], ["PRJNA644520", "SRR1234567", "qiita:10317"])

    def test_non_id_moved(self):
        f = {"repository_accession": "Table S1 in the supplemental material",
             "dataset_url": "", "accession_type": "supplementary_material"}
        cc.clean_accession(f, "datasets")
        self.assertEqual(f["repository_accession"], "")
        self.assertEqual(f["accession_valid"], "NO")
        self.assertEqual(f["repository_accession_original"], "Table S1 in the supplemental material")
        self.assertEqual(f["accession_type"], "")

    def test_url_moved_to_url_field(self):
        f = {"repository_accession": "https://github.com/x/y", "dataset_url": ""}
        cc.clean_accession(f, "datasets")
        self.assertEqual(f["dataset_url"], "https://github.com/x/y")

    def test_type_without_accession_cleared(self):
        f = {"repository_accession": "", "accession_type": "github"}
        cc.clean_accession(f, "datasets")
        self.assertEqual(f["accession_type"], "")


class TestCounts(unittest.TestCase):
    def test_digit_concatenation_blanked(self):
        f = {"participant_count": 120150, "sample_count": "", "evidence_text": ""}
        cc.check_counts(f, "cohorts", "between 120-150 participants were enrolled")
        self.assertEqual(f["participant_count"], "")
        self.assertIn("NOT_IN_SOURCE_TEXT", f["count_flag"])

    def test_stated_count_kept(self):
        f = {"participant_count": 1070, "sample_count": 24, "evidence_text": ""}
        cc.check_counts(f, "cohorts", "a total of 1,070 participants and twenty-four samples")
        self.assertEqual((f["participant_count"], f["sample_count"]), (1070, 24))
        self.assertEqual(f["count_flag"], "")

    def test_huge_count_blanked_and_flagged(self):
        f = {"sample_count": 14434301, "evidence_text": ""}
        cc.check_counts(f, "samples", "we obtained 14434301 reads")
        self.assertEqual(f["sample_count"], "")
        self.assertIn("IMPLAUSIBLY_LARGE", f["count_flag"])


class TestRelocate(unittest.TestCase):
    SECTION = "Intro text.\nAlpha diversity was signifi-\ncantly reduced in HIV+ subjects\n(Fig. 2). More."

    def test_normalised_match(self):
        norm, idx = cc._norm_map(self.SECTION)
        hit = cc.relocate("Alpha diversity was significantly reduced in HIV+ subjects", norm, idx)
        self.assertIsNotNone(hit)
        self.assertEqual(hit[2], "NORMALIZED")
        self.assertTrue(self.SECTION[hit[0]:hit[1]].startswith("Alpha"))

    def test_fuzzy_match(self):
        norm, idx = cc._norm_map(self.SECTION)
        hit = cc.relocate("Alpha diversity was significantly reduced in the HIV+ subjects (Fig 2)", norm, idx)
        self.assertIsNotNone(hit)
        self.assertTrue(hit[2].startswith("FUZZY"))

    def test_invented_quote_not_found(self):
        norm, idx = cc._norm_map(self.SECTION)
        self.assertIsNone(cc.relocate("Bacteroides were enriched in all controls at baseline", norm, idx))


class TestMerge(unittest.TestCase):
    def test_exact_duplicate_folded(self):
        a = _rec("findings", "F1", taxon_or_feature="Prevotella", evidence_text="x")
        b = _rec("findings", "F2", taxon_or_feature="Prevotella", evidence_text="x")
        kept, folded = cc.merge_records([a, b], "findings")
        self.assertEqual(len(kept), 1)
        self.assertEqual(folded[0]["fields"]["v3_status"], "DUPLICATE_OF:F1")

    def test_same_key_merged_and_union(self):
        a = _rec("cohorts", "C1", cohort_label="HIV+ adults", participant_count=40, evidence_text="a")
        b = _rec("cohorts", "C2", cohort_label="HIV+ adults", country_or_region="Ghana", evidence_text="b")
        kept, folded = cc.merge_records([a, b], "cohorts")
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["fields"]["country_or_region"], "Ghana")
        self.assertEqual(kept[0]["fields"]["merged_from"], "C2")

    def test_conflict_not_merged(self):
        a = _rec("cohorts", "C1", cohort_label="cases", participant_count=40, evidence_text="a")
        b = _rec("cohorts", "C2", cohort_label="cases", participant_count=52, evidence_text="b")
        kept, _ = cc.merge_records([a, b], "cohorts")
        self.assertEqual(len(kept), 2)

    def test_other_paper_not_merged(self):
        a = _rec("cohorts", "C1", cohort_label="cases", evidence_text="a")
        b = _rec("cohorts", "C2", paper="HMPAPER_000002", cohort_label="cases", evidence_text="b")
        kept, _ = cc.merge_records([a, b], "cohorts")
        self.assertEqual(len(kept), 2)

    def test_samples_never_key_merged(self):
        a = _rec("samples", "S1", body_site="gut", sample_type="fecal", sample_count=4, evidence_text="CD Flare (4)")
        b = _rec("samples", "S2", body_site="gut", sample_type="fecal", sample_count=4, evidence_text="CD Remission (4)")
        kept, _ = cc.merge_records([a, b], "samples")
        self.assertEqual(len(kept), 2)


if __name__ == "__main__":
    unittest.main()
