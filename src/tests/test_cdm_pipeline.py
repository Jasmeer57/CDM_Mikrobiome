"""Test suite for cdm_pipeline package.

Run from repo root:
    python -m unittest discover tests -v

Covers:
  - config: CDM type count, vocab priority, preferred/noisy sets
  - utils: is_junk, norm, load_csv_safe
  - dedup: fix_label, model priority resolution, ENTITY fallback
  - mapping.confidence: _confidence scoring, resolve_canonical ranking
  - evaluation.intra_nlp: jaccard, unique contribution, ensemble stats
"""
import csv
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())))

from cdm_pipeline.config import (
    CDM_TYPES,
    VOCAB_PRIORITY,
    PREFERRED,
    NOISY,
    EXACT_MATCH_FLOOR,
)
from cdm_pipeline.utils import is_junk, norm, load_csv_safe
from cdm_pipeline.dedup import (
    fix_label,
    MODEL_PRIORITY,
    SOURCE_NAME,
    VALID_TYPES,
)
from cdm_pipeline.mapping.confidence import _confidence, resolve_canonical
from cdm_pipeline.evaluation.intra_nlp import (
    jaccard,
    compute_unique_contribution,
    compute_ensemble_stats,
    _model_key,
)
from cdm_pipeline.quality.study_type_annotator import classify_paper, build_paper_study_types
from cdm_pipeline.quality.confidence_scoring import recover_evidence_direction


class TestConfig(unittest.TestCase):
    def test_cdm_types_count(self):
        self.assertEqual(len(CDM_TYPES), 14)

    def test_cdm_types_unique(self):
        self.assertEqual(len(CDM_TYPES), len(set(CDM_TYPES)))

    def test_cdm_types_known_members(self):
        for t in ["ORGANISM", "CHEMICAL", "DISEASE", "PROTEIN", "DNA_RNA",
                  "CELL_TYPE", "GENOMICS", "PATHWAY", "LAB_METHOD",
                  "DATA_ANALYSIS", "SAMPLE_METHOD", "CLINICAL",
                  "EXPERIMENTAL_METHOD", "STUDY_DESIGN"]:
            self.assertIn(t, CDM_TYPES)

    def test_vocab_priority_all_types_covered(self):
        for t in CDM_TYPES:
            self.assertIn(t, VOCAB_PRIORITY)
            self.assertIsInstance(VOCAB_PRIORITY[t], list)
            self.assertGreater(len(VOCAB_PRIORITY[t]), 0)

    def test_preferred_subset_of_priority(self):
        for t in CDM_TYPES:
            preferred = PREFERRED.get(t, set())
            priority = set(VOCAB_PRIORITY.get(t, []))
            self.assertTrue(preferred.issubset(priority),
                            f"{t}: preferred has vocab not in priority")

    def test_noisy_known_members(self):
        for v in ["MEDDRA", "ICD9CM", "RCD", "CPT", "LNC"]:
            self.assertIn(v, NOISY)

    def test_exact_match_floor(self):
        self.assertGreater(EXACT_MATCH_FLOOR, 0.8)
        self.assertLess(EXACT_MATCH_FLOOR, 1.0)


class TestUtils(unittest.TestCase):
    def test_is_junk_short(self):
        self.assertTrue(is_junk(""))
        self.assertTrue(is_junk("a"))
        self.assertTrue(is_junk("1"))

    def test_is_junk_punctuation(self):
        self.assertTrue(is_junk(","))
        self.assertTrue(is_junk("."))
        self.assertTrue(is_junk("()"))
        self.assertTrue(is_junk("[1]"))

    def test_is_junk_valid_terms(self):
        self.assertFalse(is_junk("Bacteroides"))
        self.assertFalse(is_junk("Faecalibacterium prausnitzii"))
        self.assertFalse(is_junk("16S rRNA"))

    def test_is_junk_newlines(self):
        self.assertTrue(is_junk("hello\nworld"))

    def test_norm_lowercase(self):
        self.assertEqual(norm("Bacteroides"), "bacteroides")

    def test_norm_collapse_whitespace(self):
        self.assertEqual(norm("  Bacteroides   fragilis  "),
                         "bacteroides fragilis")

    def test_norm_idempotent(self):
        n = norm("Bacteroides fragilis")
        self.assertEqual(norm(n), n)

    def test_load_csv_safe_with_nullbytes(self, ):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv",
                                          delete=False, encoding="utf-8") as f:
            f.write("term,labels,model,paper\n")
            f.write("Bacteroides,ORGANISM,test,p1.txt\n")
            f.write("Firmicutes\x00,ORGANISM,test,p2.txt\n")
            path = f.name
        try:
            rows = load_csv_safe(Path(path))
            self.assertEqual(len(rows), 2)
            self.assertNotIn("\x00", rows[1]["term"])
        finally:
            os.unlink(path)


class TestDedup(unittest.TestCase):
    def test_fix_label_identity(self):
        self.assertEqual(fix_label("ORGANISM"), "ORGANISM")
        self.assertEqual(fix_label("ENTITY"), "ENTITY")

    def test_fix_label_go_to_pathway(self):
        self.assertEqual(fix_label("GO"), "PATHWAY")

    def test_fix_label_unknown_passthrough(self):
        self.assertEqual(fix_label("UNKNOWN"), "UNKNOWN")

    def test_model_priority_order(self):
        self.assertLess(MODEL_PRIORITY["gliner_medium"],
                        MODEL_PRIORITY["pubtator3"])
        self.assertLess(MODEL_PRIORITY["pubtator3"],
                        MODEL_PRIORITY["biobert_diseases"])
        self.assertLess(MODEL_PRIORITY["biobert_diseases"],
                        MODEL_PRIORITY["en_ner_bc5cdr_md"])
        self.assertGreater(MODEL_PRIORITY["en_core_sci_lg"],
                           MODEL_PRIORITY["en_ner_craft_md"])

    def test_source_name_spacy_models(self):
        for m in ["en_core_sci_lg", "en_ner_bc5cdr_md",
                   "en_ner_craft_md", "en_ner_jnlpba_md"]:
            self.assertEqual(SOURCE_NAME[m], "sciSpaCy")

    def test_valid_types_includes_cdm(self):
        for t in CDM_TYPES:
            self.assertIn(t, VALID_TYPES)
        self.assertIn("ENTITY", VALID_TYPES)


class TestVariantRegistration(unittest.TestCase):
    """The fifteen 2026-10-27/28 variant runs must stay registered.

    ``MODEL_PRIORITY.get(model, 9)`` means an unregistered model silently falls to
    priority 9 and can never win a type conflict — not even against
    ``en_core_sci_lg``'s generic ENTITY at tier 4.  These tests pin the contract so a
    new CSV cannot be added without a tier and a source label.
    """

    def test_every_variant_model_is_registered(self):
        from cdm_pipeline import dedup

        for rel_dir, filename in dedup.VARIANT_CSV_FILES:
            path = dedup._variant_dir_path(rel_dir, filename)
            # Artifacts live under outputs/results/, which is gitignored and absent in CI.
            if not path.exists():
                continue
            models = {(r.get("model") or "").strip()
                      for r in dedup.load_csv_safe(path)}
            models.discard("")
            self.assertTrue(models, f"{filename} declares no model string")
            for m in models:
                self.assertIn(m, MODEL_PRIORITY, f"{filename}: {m!r} has no tier")
                self.assertIn(m, SOURCE_NAME, f"{filename}: {m!r} has no source")

    def test_variant_filenames_are_unique(self):
        from cdm_pipeline import dedup

        names = [f"{d}/{f}" for d, f in dedup.VARIANT_CSV_FILES]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len(names), 15)

    def test_variant_tiers_are_within_known_bands(self):
        """Variants may tie with a baseline tier but must never outrank GLiNER."""
        from cdm_pipeline import dedup

        for rel_dir, filename in dedup.VARIANT_CSV_FILES:
            path = dedup._variant_dir_path(rel_dir, filename)
            if not path.exists():
                continue
            for r in dedup.load_csv_safe(path):
                m = (r.get("model") or "").strip()
                if not m:
                    continue
                self.assertGreaterEqual(MODEL_PRIORITY[m],
                                        MODEL_PRIORITY["gliner_medium"])
                self.assertLessEqual(MODEL_PRIORITY[m],
                                     MODEL_PRIORITY["en_core_sci_lg"])

    def test_resolve_inputs_opt_in(self):
        from cdm_pipeline import dedup

        self.assertEqual(len(dedup.resolve_inputs(include_variants=False)),
                         len(dedup.CSV_FILES))
        self.assertEqual(len(dedup.resolve_inputs(include_variants=True)),
                         len(dedup.CSV_FILES) + len(dedup.VARIANT_CSV_FILES))

    def test_baseline_tiers_unchanged(self):
        """Regression guard: the five baseline models keep their historical tiers."""
        self.assertEqual(MODEL_PRIORITY["gliner_medium"], 0)
        self.assertEqual(MODEL_PRIORITY["qwen3.5:9b"], 1)
        self.assertEqual(MODEL_PRIORITY["pubtator3"], 1)
        self.assertEqual(MODEL_PRIORITY["biobert_diseases"], 2)
        self.assertEqual(MODEL_PRIORITY["en_ner_bc5cdr_md"], 3)
        self.assertEqual(MODEL_PRIORITY["en_ner_craft_md"], 3)
        self.assertEqual(MODEL_PRIORITY["en_ner_jnlpba_md"], 3)
        self.assertEqual(MODEL_PRIORITY["en_core_sci_lg"], 4)

    def test_baseline_dir_override_is_honoured(self):
        """``--baseline_dir`` must actually move where the five CSVs are looked for.

        The default (``NER_OUTPUT_DIR``) is ``.../_multi_ner_runs/ner_output``,
        which does not exist in this tree, so without the override every baseline
        CSV is skipped.  That silently produced a variants-only registry and a
        wrong published combined total on 2026-10-28.
        """
        from cdm_pipeline import dedup

        alt = dedup.resolve_inputs(include_variants=False, baseline_dir="/tmp/somewhere")
        self.assertEqual([name for name, _ in alt], list(dedup.CSV_FILES))
        for _, path in alt:
            self.assertEqual(str(path).rsplit("/", 1)[0], "/tmp/somewhere")

    def test_default_baseline_dir_is_reported_when_empty(self):
        """The bad path is real in this tree: the default dir does not exist.

        Guards the diagnostic added for it — a merge must be able to *tell* that no
        baseline CSV was found, rather than looking like a complete run.
        """
        from cdm_pipeline import dedup

        base = dedup.NER_OUTPUT_DIR
        present = [n for n in dedup.CSV_FILES if (base / n).exists()]
        if base.exists() and present:
            self.skipTest(f"real baseline dir present at {base}")
        self.assertEqual(present, [],
                         "default baseline dir is unexpectedly populated; the "
                         "warning-below-empty behaviour is untested")


class TestConfidence(unittest.TestCase):
    def test_exact_match(self):
        self.assertAlmostEqual(_confidence("Bacteroides", "Bacteroides",
                                            "ORGANISM", "NCBITAXON"), 1.0)

    def test_empty_label(self):
        self.assertEqual(_confidence("Bacteroides", "", "ORGANISM", ""), 0.5)

    def test_partial_match(self):
        score = _confidence("Bacteroides fragilis", "Bacteroides thetaiotaomicron",
                           "ORGANISM", "NCBITAXON")
        self.assertGreater(score, 0.3)
        self.assertLess(score, 1.0)

    def test_preferred_vocab_bonus(self):
        score_pref = _confidence("Bacteroides", "Bacteroides fragilis",
                                 "ORGANISM", "NCBITAXON")
        score_none = _confidence("Bacteroides", "Bacteroides fragilis",
                                "ORGANISM", "")
        self.assertGreater(score_pref, score_none)

    def test_noisy_vocab_penalty(self):
        score_noisy = _confidence("aspirin", "aspirin",
                                  "CHEMICAL", "MEDDRA")
        score_normal = _confidence("aspirin", "aspirin",
                                   "CHEMICAL", "")
        self.assertLessEqual(score_noisy, score_normal)

    def test_bounded(self):
        for a, b, t, o in [("a", "b", "ORGANISM", "NCBITAXON"),
                           ("", "", "DISEASE", ""),
                           ("longterm" * 10, "x", "PROTEIN", "PR")]:
            s = _confidence(a, b, t, o)
            self.assertGreaterEqual(s, 0.0)
            self.assertLessEqual(s, 1.0)

    def test_resolve_canonical_empty(self):
        c, others = resolve_canonical([], "ORGANISM")
        self.assertIsNone(c)
        self.assertEqual(others, [])

    def test_resolve_canonical_priority(self):
        candidates = [
            {"ontology_name": "MESH", "confidence": 0.9, "label": "a"},
            {"ontology_name": "NCBITAXON", "confidence": 0.7, "label": "b"},
            {"ontology_name": "SNOMEDCT", "confidence": 0.95, "label": "c"},
        ]
        c, others = resolve_canonical(candidates, "ORGANISM")
        self.assertEqual(c["ontology_name"], "NCBITAXON")
        self.assertEqual(len(others), 2)

    def test_resolve_canonical_fallback_unlisted(self):
        candidates = [
            {"ontology_name": "UNKNOWN_ONTO", "confidence": 0.5, "label": "a"},
            {"ontology_name": "ALSO_UNKNOWN", "confidence": 0.9, "label": "b"},
        ]
        c, others = resolve_canonical(candidates, "ORGANISM")
        self.assertEqual(c["confidence"], 0.9)


class TestIntraNLP(unittest.TestCase):
    def test_jaccard_identity(self):
        s = {"a", "b", "c"}
        self.assertEqual(jaccard(s, s), 1.0)

    def test_jaccard_disjoint(self):
        self.assertEqual(jaccard({"a"}, {"b"}), 0.0)

    def test_jaccard_partial(self):
        self.assertAlmostEqual(jaccard({"a", "b"}, {"b", "c"}), 1/3)

    def test_jaccard_empty_both(self):
        self.assertEqual(jaccard(set(), set()), 1.0)

    def test_jaccard_one_empty(self):
        self.assertEqual(jaccard({"a"}, set()), 0.0)

    def test_model_key_gliner(self):
        self.assertEqual(_model_key("GLiNER_medium"), "gliner")

    def test_model_key_pubmedbert(self):
        self.assertEqual(_model_key("biobert_diseases"), "pubmedbert")
        self.assertEqual(_model_key("PubMedBERT"), "pubmedbert")

    def test_model_key_pubtator(self):
        self.assertEqual(_model_key("pubtator3"), "pubtator")

    def test_model_key_qwen(self):
        self.assertEqual(_model_key("qwen3.5_9b"), "qwen")

    def test_model_key_scispacy(self):
        self.assertEqual(_model_key("en_ner_craft_md"), "scispacy")
        self.assertEqual(_model_key("en_core_sci_lg"), "scispacy")

    def test_compute_unique_contribution(self):
        models = {
            "a": {"entities": {"x", "y", "z"}},
            "b": {"entities": {"y", "w"}},
        }
        results, total = compute_unique_contribution(models)
        self.assertEqual(results["a"]["total_unique"], 2)
        self.assertEqual(results["b"]["total_unique"], 1)
        self.assertEqual(total, 3)

    def test_compute_ensemble_stats(self):
        models = {
            "a": {"entities": {"x", "y"}},
            "b": {"entities": {"y", "z"}},
        }
        es = compute_ensemble_stats(models)
        self.assertEqual(es["union_all"], 3)
        self.assertEqual(es["intersection_all"], 1)
        self.assertEqual(len(es["progressive_union"]), 2)
        self.assertEqual(es["progressive_union"][0]["new_entities"], 2)
        self.assertEqual(es["progressive_union"][1]["new_entities"], 1)


class TestDedupMain(unittest.TestCase):
    """Test the dedup.main() function end-to-end with synthetic CSVs."""

    def test_dedup_main(self):
        from cdm_pipeline import dedup

        tmp = Path(tempfile.mkdtemp())
        try:
            # Patch NER_OUTPUT_DIR
            orig = dedup.NER_OUTPUT_DIR
            orig_out = dedup.OUTPUT
            dedup.NER_OUTPUT_DIR = tmp
            dedup.OUTPUT = tmp / "deduplicated_entities.json"

            # Write test CSVs
            def write_csv(name, rows):
                with open(tmp / name, "w", newline="", encoding="utf-8") as f:
                    w = csv.DictWriter(f, fieldnames=["term", "labels", "model", "paper"])
                    w.writeheader()
                    w.writerows(rows)

            write_csv("gliner_ner.csv", [
                {"term": "Bacteroides", "labels": "ORGANISM", "model": "gliner_medium", "paper": "p1.txt"},
                {"term": "aspirin", "labels": "CHEMICAL", "model": "gliner_medium", "paper": "p1.txt"},
            ])
            write_csv("pubmedbert_ner.csv", [
                {"term": "Bacteroides", "labels": "DISEASE", "model": "biobert_diseases", "paper": "p1.txt"},
                {"term": "colitis", "labels": "DISEASE", "model": "biobert_diseases", "paper": "p2.txt"},
            ])
            write_csv("scispacy_ner.csv", [
                {"term": "Bacteroides", "labels": "ENTITY", "model": "en_core_sci_lg", "paper": "p1.txt"},
                {"term": "  junk,, ", "labels": "ENTITY", "model": "en_core_sci_lg", "paper": "p3.txt"},
            ])
            write_csv("pubtator3_ner.csv", [])

            dedup.main()

            with open(dedup.OUTPUT) as f:
                results = json.load(f)

            terms = {r["term"]: r for r in results}
            # Bacteroides: GLiNER (priority 0) wins over PubMedBERT (2) and spaCy (4)
            self.assertEqual(terms["Bacteroides"]["cdm_type"], "ORGANISM")
            self.assertIn("GLiNER", terms["Bacteroides"]["sources"])
            self.assertIn("sciSpaCy", terms["Bacteroides"]["sources"])
            # aspirin only in gliner
            self.assertEqual(terms["aspirin"]["cdm_type"], "CHEMICAL")
            # colitis only in pubmedbert
            self.assertEqual(terms["colitis"]["cdm_type"], "DISEASE")
            # junk filtered out
            self.assertNotIn("junk,, ", terms)
            self.assertNotIn("  junk,, ", terms)
        finally:
            dedup.NER_OUTPUT_DIR = orig
            dedup.OUTPUT = orig_out
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


class TestStudyTypeAnnotator(unittest.TestCase):
    """Tests for study_type_annotator.classify_paper and build_paper_study_types."""

    def test_classify_rct_from_pub_type(self):
        result = classify_paper(
            pub_types=["Journal Article", "Randomized Controlled Trial"],
            mesh_terms=[],
        )
        self.assertEqual(result, "randomized_controlled_trial")

    def test_classify_cohort_from_mesh(self):
        result = classify_paper(
            pub_types=["Journal Article"],
            mesh_terms=["Cohort Studies", "Prospective Studies"],
        )
        self.assertEqual(result, "prospective_cohort")

    def test_classify_case_control_from_mesh(self):
        result = classify_paper(
            pub_types=["Journal Article"],
            mesh_terms=["Case-Control Studies"],
        )
        self.assertEqual(result, "case_control")

    def test_classify_rct_beats_cohort(self):
        """When both RCT and cohort are detected, RCT wins (higher rank)."""
        result = classify_paper(
            pub_types=["Journal Article", "Randomized Controlled Trial"],
            mesh_terms=["Cohort Studies"],
        )
        self.assertEqual(result, "randomized_controlled_trial")

    def test_classify_animal_from_mesh(self):
        result = classify_paper(
            pub_types=["Journal Article"],
            mesh_terms=["Animals", "Mice"],
        )
        self.assertEqual(result, "in_vivo_animal")

    def test_classify_unknown(self):
        result = classify_paper(pub_types=["Journal Article"], mesh_terms=[])
        self.assertEqual(result, "unknown")

    def test_classify_meta_analysis(self):
        result = classify_paper(
            pub_types=["Meta-Analysis"],
            mesh_terms=[],
        )
        self.assertEqual(result, "systematic_review_meta_analysis")

    def test_build_paper_study_types(self):
        meta = {
            "PRJ001": {"publication_types": ["Randomized Controlled Trial"], "mesh_terms": []},
            "PRJ002": {"publication_types": ["Journal Article"], "mesh_terms": ["Cohort Studies"]},
            "PRJ003": {"publication_types": ["Journal Article"], "mesh_terms": []},
        }
        result = build_paper_study_types(meta)
        self.assertEqual(len(result), 3)
        self.assertEqual(result["PRJ001"], "randomized_controlled_trial")
        self.assertEqual(result["PRJ002"], "cohort")
        self.assertEqual(result["PRJ003"], "unknown")


class TestRecoverEvidenceDirection(unittest.TestCase):
    """Tests for confidence_scoring.recover_evidence_direction."""

    def test_increased_risk_positive(self):
        ev = "Patients had an increased risk of colorectal cancer."
        self.assertEqual(recover_evidence_direction(ev, "colorectal cancer"), "positive")

    def test_decreased_risk_negative(self):
        ev = "The treatment showed a decreased risk of infection."
        self.assertEqual(recover_evidence_direction(ev, "infection"), "negative")

    def test_inversely_associated_negative(self):
        ev = "Bacteroides was inversely associated with the disease severity."
        self.assertEqual(recover_evidence_direction(ev, "disease severity"), "negative")

    def test_positively_associated_positive(self):
        ev = "Firmicutes was positively associated with the outcome."
        self.assertEqual(recover_evidence_direction(ev, "outcome"), "positive")

    def test_enriched_in_positive(self):
        ev = "The taxa was enriched in the gut microbiome of patients."
        self.assertEqual(recover_evidence_direction(ev, "gut microbiome"), "positive")

    def test_depleted_in_negative(self):
        ev = "The taxa was depleted in the gut microbiome of patients."
        self.assertEqual(recover_evidence_direction(ev, "gut microbiome"), "negative")

    def test_abundance_up_positive(self):
        ev = "There was an increased abundance of Bifidobacterium after treatment."
        self.assertEqual(recover_evidence_direction(ev, "Bifidobacterium"), "positive")

    def test_abundance_down_negative(self):
        ev = "We observed a decreased abundance of Clostridium in the cohort."
        self.assertEqual(recover_evidence_direction(ev, "Clostridium"), "negative")

    def test_no_direction_returns_none(self):
        ev = "The microbiome was studied in the cohort."
        self.assertIsNone(recover_evidence_direction(ev, "microbiome"))

    def test_empty_evidence_returns_none(self):
        self.assertIsNone(recover_evidence_direction("", "test"))
        self.assertIsNone(recover_evidence_direction("some evidence", ""))

    def test_object_anchored_up(self):
        ev = "We found elevated levels of Bacteroides in the treatment group."
        self.assertEqual(recover_evidence_direction(ev, "Bacteroides"), "positive")

    def test_object_anchored_down(self):
        ev = "Reduced levels of Faecalibacterium were observed in patients."
        self.assertEqual(recover_evidence_direction(ev, "Faecalibacterium"), "negative")


class TestLLMEntityCleanup(unittest.TestCase):
    """Tests for cdm_pipeline.quality.llm_entity_cleanup (no Ollama required)."""

    def setUp(self):
        from cdm_pipeline.quality import llm_entity_cleanup as mod

        self.mod = mod

    def test_ensure_ollama_host_adds_http(self):
        os.environ["OLLAMA_HOST"] = "127.0.0.1:11434"
        host = self.mod._ensure_ollama_host()
        self.assertTrue(host.startswith("http://"))

    def test_ensure_ollama_host_preserves_http(self):
        os.environ["OLLAMA_HOST"] = "http://localhost:11434"
        host = self.mod._ensure_ollama_host()
        self.assertEqual(host, "http://localhost:11434")

    def test_parse_json_array_valid(self):
        raw = '[{"index": 1, "type": "DISEASE", "confidence": 0.9}]'
        result = self.mod._parse_json_array(raw)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["type"], "DISEASE")

    def test_parse_json_array_markdown_fenced(self):
        raw = '```json\n[{"index": 1, "type": "CHEMICAL", "confidence": 0.85}]\n```'
        result = self.mod._parse_json_array(raw)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["type"], "CHEMICAL")

    def test_parse_json_array_empty(self):
        self.assertEqual(self.mod._parse_json_array(""), [])
        self.assertEqual(self.mod._parse_json_array("no json here"), [])

    def test_cosine_sim_identical(self):
        import numpy as np

        v = np.array([1.0, 2.0, 3.0])
        self.assertAlmostEqual(self.mod._cosine_sim(v, v), 1.0, places=5)

    def test_cosine_sim_orthogonal(self):
        import numpy as np

        a = np.array([1.0, 0.0])
        b = np.array([0.0, 1.0])
        self.assertAlmostEqual(self.mod._cosine_sim(a, b), 0.0, places=5)

    def test_cosine_sim_zero_vector(self):
        import numpy as np

        a = np.array([0.0, 0.0])
        b = np.array([1.0, 2.0])
        self.assertEqual(self.mod._cosine_sim(a, b), 0.0)

    def test_is_likely_noise_short(self):
        self.assertTrue(self.mod._is_likely_noise("ab"))
        self.assertTrue(self.mod._is_likely_noise("x"))

    def test_is_likely_noise_generic_words(self):
        self.assertTrue(self.mod._is_likely_noise("taxa"))
        self.assertTrue(self.mod._is_likely_noise("species"))
        self.assertTrue(self.mod._is_likely_noise("reads"))
        self.assertTrue(self.mod._is_likely_noise("negative"))

    def test_is_likely_noise_real_terms(self):
        self.assertFalse(self.mod._is_likely_noise("Faecalibacterium prausnitzii"))
        self.assertFalse(self.mod._is_likely_noise("butyrate"))
        self.assertFalse(self.mod._is_likely_noise("Crohn's disease"))

    def test_find_type_correction_candidates_prefix_mismatch(self):
        entities = [
            {"id": 1, "name": "some bacterium", "type": "DISEASE",
             "ontology_id": "NCBITaxon:123", "ontology_prefix": "NCBITAXON"},
            {"id": 2, "name": "aspirin", "type": "CHEMICAL",
             "ontology_id": "CHEBI:22730", "ontology_prefix": "CHEBI"},
        ]
        candidates = self.mod._find_type_correction_candidates(entities)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["id"], 1)

    def test_find_type_correction_candidates_mesh_is_not_flagged(self):
        """MESH prefixes are valid across types — should not be flagged."""
        entities = [
            {"id": 1, "name": "obesity", "type": "DISEASE",
             "ontology_id": "MESH:D009765", "ontology_prefix": "MESH"},
        ]
        candidates = self.mod._find_type_correction_candidates(entities)
        self.assertEqual(len(candidates), 0)

    def test_find_type_correction_candidates_invalid_type(self):
        entities = [
            {"id": 1, "name": "test", "type": "UNKNOWN",
             "ontology_id": "", "ontology_prefix": ""},
        ]
        candidates = self.mod._find_type_correction_candidates(entities)
        self.assertEqual(len(candidates), 1)

    def test_pass1_applies_correction_from_checkpoint(self):
        """Pass 1 should apply corrections loaded from checkpoint without calling LLM."""
        import tempfile

        entities = [
            {"id": 10, "name": "taxonomic", "type": "DISEASE",
             "ontology_id": "", "ontology_prefix": "", "paper_count": 5,
             "frequency": 10, "umls": "", "ols": "", "bioportal": "", "ncbitaxon": ""},
            {"id": 11, "name": "Bifidobacterium", "type": "ORGANISM",
             "ontology_id": "NCBITaxon:1649", "ontology_prefix": "NCBITAXON",
             "paper_count": 20, "frequency": 50, "umls": "", "ols": "", "bioportal": "", "ncbitaxon": ""},
        ]
        ckpt_data = {str(10): {"old_type": "DISEASE", "new_type": "GENOMICS", "confidence": 0.9, "name": "taxonomic"}}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(ckpt_data, f)
            ckpt_path = Path(f.name)

        try:
            result_entities, corrections = self.mod.pass1_type_correction(
                entities, ckpt_path, apply=False, conn=None
            )
            self.assertEqual(corrections["10"]["new_type"], "GENOMICS")
            updated = [e for e in result_entities if e["id"] == 10][0]
            self.assertEqual(updated["type"], "GENOMICS")
        finally:
            ckpt_path.unlink(missing_ok=True)

    def test_pass2_dedup_from_checkpoint(self):
        """Pass 2 should apply remappings from checkpoint without calling embed."""
        import tempfile

        entities = [
            {"id": 1, "name": "B. fragilis", "type": "ORGANISM",
             "ontology_id": "NCBITaxon:1649", "ontology_prefix": "NCBITAXON",
             "paper_count": 10, "frequency": 20, "umls": "", "ols": "", "bioportal": "", "ncbitaxon": ""},
            {"id": 2, "name": "Bacteroides fragilis", "type": "ORGANISM",
             "ontology_id": "", "ontology_prefix": "", "paper_count": 5,
             "frequency": 8, "umls": "", "ols": "", "bioportal": "", "ncbitaxon": ""},
        ]
        ckpt_data = {"remap": {"2": "1"}}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(ckpt_data, f)
            ckpt_path = Path(f.name)

        try:
            result_entities, remap = self.mod.pass2_semantic_dedup(
                entities, ckpt_path, apply=False, conn=None
            )
            self.assertEqual(remap["2"], "1")
            # Duplicate should be removed from the list
            ids = [e["id"] for e in result_entities]
            self.assertNotIn(2, ids)
            self.assertIn(1, ids)
        finally:
            ckpt_path.unlink(missing_ok=True)

    def test_pass3_noise_from_checkpoint(self):
        """Pass 3 should load noise flags from checkpoint without calling LLM."""
        import tempfile

        entities = [
            {"id": 5, "name": "taxa", "type": "GENOMICS",
             "ontology_id": "", "ontology_prefix": "", "paper_count": 3,
             "frequency": 5, "umls": "", "ols": "", "bioportal": "", "ncbitaxon": ""},
        ]
        ckpt_data = {"5": {"name": "taxa", "type": "GENOMICS", "is_noise": True, "is_real_term": False, "reason": "generic word"}}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(ckpt_data, f)
            ckpt_path = Path(f.name)

        try:
            _, noise = self.mod.pass3_noise_detection(
                entities, ckpt_path, apply=False, conn=None
            )
            self.assertIn("5", noise)
            self.assertTrue(noise["5"]["is_noise"])
        finally:
            ckpt_path.unlink(missing_ok=True)

    def test_cdm_types_complete(self):
        self.assertEqual(len(self.mod.CDM_TYPES), 14)
        for t in self.mod.CDM_TYPES:
            self.assertIn(t, self.mod.TYPE_PREFIX_MAP)

    def test_type_prototypes_complete(self):
        """Every CDM type should have a prototype description."""
        for t in self.mod.CDM_TYPES:
            self.assertIn(t, self.mod.TYPE_PROTOTYPES)
            self.assertTrue(len(self.mod.TYPE_PROTOTYPES[t]) > 20)


class TestJavaToolReanchor(unittest.TestCase):
    """DNorm reports starts that drift from the true occurrence while echoing the
    input byte-identically. ``reanchor`` recovers only an unambiguous nearest hit."""

    def setUp(self):
        from cdm_pipeline.ner.java_tools import reanchor, MAX_REANCHOR_DRIFT
        self.reanchor = reanchor
        self.max_drift = MAX_REANCHOR_DRIFT

    def test_exact_occurrence_returned(self):
        self.assertEqual(self.reanchor("aa HIV bb", "HIV", 3), 3)

    def test_small_drift_either_direction(self):
        self.assertEqual(self.reanchor("aa HIV bb", "HIV", 2), 3)
        self.assertEqual(self.reanchor("aa HIV bb", "HIV", 4), 3)

    def test_absent_term_not_invented(self):
        self.assertIsNone(self.reanchor("aa HIV bb", "ZZZ", 3))

    def test_empty_term_not_matched(self):
        self.assertIsNone(self.reanchor("aa HIV bb", "", 0))

    def test_beyond_max_drift_rejected(self):
        text = "a" * 200 + "HIV"
        self.assertIsNone(self.reanchor(text, "HIV", 0))
        self.assertEqual(self.max_drift, 64)

    def test_exact_tie_rejected(self):
        # occurrences at 1 and 5; st0=3 is equidistant
        self.assertIsNone(self.reanchor("xHIVyHIVz", "HIV", 3))

    def test_unique_nearest_preferred(self):
        self.assertEqual(self.reanchor("HIV aaaaa HIV", "HIV", 9), 10)

    def test_recovery_must_still_slice_verify(self):
        """A drifted record is rewritten to the recovered span, never trusted blindly."""
        from cdm_pipeline.ner.java_tools import pubtator_to_rows
        text = "aa HIV bb"
        title = "sec_001"
        batch_map = {1: (1, "P1", title, "x", title, text)}
        units = [{"cid": "P1", "section_id": title, "path": "body", "text": text}]
        unit_index = {("P1", title): units[0]}
        base = len(title) + 1
        # tool reports start 2 (drifted by one) -> must be recovered to 3
        recs = [{"idx": 1, "start": base + 2, "end": base + 5,
                 "term": "HIV", "label": "Disease", "norm": "MESH:D006678"}]
        rows, stats = pubtator_to_rows(recs, "DNorm", batch_map, unit_index)
        self.assertEqual(stats["reanchored"], 1)
        self.assertEqual(stats["slice_fails"], 0)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["char_start"], rows[0]["char_end"]), (3, 6))
        self.assertEqual(text[rows[0]["char_start"]:rows[0]["char_end"]], "HIV")

    def test_unrecoverable_drift_counted_as_slice_fail(self):
        from cdm_pipeline.ner.java_tools import pubtator_to_rows
        text = "aa HIV bb"
        title = "sec_001"
        batch_map = {1: (1, "P1", title, "x", title, text)}
        units = [{"cid": "P1", "section_id": title, "path": "body", "text": text}]
        unit_index = {("P1", title): units[0]}
        # term is absent from the text -> nothing to re-anchor to
        base = len(title) + 1
        recs = [{"idx": 1, "start": base + 0, "end": base + 3,
                 "term": "ZZZ", "label": "Disease", "norm": ""}]
        rows, stats = pubtator_to_rows(recs, "DNorm", batch_map, unit_index)
        self.assertEqual(stats["slice_fails"], 1)
        self.assertEqual(stats["reanchored"], 0)
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
