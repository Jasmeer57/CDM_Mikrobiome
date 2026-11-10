"""Tests for scripts.release_gates.

Fixtures are built in temporary directories; no production artifact is read
or written.  Both passing and failing cases are exercised.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from scripts.release_gates import gates
from scripts.release_gates.core import Ctx, sha256_file


def _write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def _refresh_manifest(root):
    lines = []
    for base, _dirs, files in os.walk(root):
        for name in files:
            if name == "MANIFEST.sha256":
                continue
            p = Path(base) / name
            rel = p.relative_to(root)
            lines.append(f"{sha256_file(p)}  ./{rel}")
    (Path(root) / "MANIFEST.sha256").write_text("\n".join(sorted(lines)) + "\n", encoding="utf-8")


def make_release(tmp, *, mentions=3, declared_mentions=3, coverage_mentions=3,
                 auto_accepted=0, calibration="NOT_CALIBRATED", secret=False,
                 extra_file=False, mention_type="ORGANISM", mention_norm="x"):
    root = Path(tmp) / "terminology" / "9.9.9"
    root.mkdir(parents=True)
    (root / "term_mentions.jsonl").write_text(
        "".join(json.dumps({"mention_id": f"M{i}", "normalized_mention": mention_norm,
                            "entity_type": mention_type, "canonical_term_id": None,
                            "extraction_run_id": "cpu_ensemble_v1",
                            "paper_id": "P", "section_id": "s",
                            "start_offset": 0, "end_offset": 1,
                            "surface_form": "x"}) + "\n" for i in range(mentions)),
        encoding="utf-8")
    _write_jsonl(root / "canonical_terms.jsonl",
                 [{"term_id": "T1", "term_norm": "x", "cdm_type": "ORGANISM"}])
    _write_jsonl(root / "term_definitions.jsonl", [{"definition_id": "D1"}])
    _write_jsonl(root / "term_ontology_mappings.jsonl",
                 [{"mapping_id": "M1", "mapping_relation": "RELATED_TO",
                   "mapping_disposition": "REVIEW_REQUIRED", "auto_accept_eligible": False}])

    arts = []
    for name, rec in (("term_mentions.jsonl", declared_mentions),
                      ("canonical_terms.jsonl", 1),
                      ("term_definitions.jsonl", 1),
                      ("term_ontology_mappings.jsonl", 1)):
        p = root / name
        arts.append({"name": name, "sha256": sha256_file(p), "bytes": p.stat().st_size,
                     "records": rec})
    (root / "terminology_extraction_manifest.json").write_text(json.dumps({
        "manifest_version": "1.0.0", "pipeline_version": "v1",
        "generated_at": "2026-10-25T17:45:38",
        "coverage": {"mention_records": coverage_mentions},
        "artifacts": arts,
    }), encoding="utf-8")

    (root / "mapping_projection_summary.json").write_text(json.dumps({
        "counts": {"rows": 1, "auto_accepted": auto_accepted},
        "calibration": {"status": calibration},
    }), encoding="utf-8")

    (root / "PROVENANCE.json").write_text(json.dumps({
        "job_id": "28619916", "generated_at": "2026-10-25T17:45:38",
        "artifacts": {"term_mentions.jsonl": arts[0]["sha256"]},
        "sources": {"sections": {"path": "segmented_sections_markdown"}},
        "non_claims": ["no human verification"],
        "corpus_release": "2.2.0",
    }), encoding="utf-8")

    repo = Path(tmp)
    (repo / ".gitignore").write_text(
        "secrets.env\n**/secrets.env\n*.key\n*.pem\n", encoding="utf-8")
    _refresh_manifest(root)

    # Ledger row must reference the manifest digest (G6).
    digest = sha256_file(root / "MANIFEST.sha256")
    (repo / "releases").mkdir(parents=True, exist_ok=True)
    (repo / "releases" / "RELEASES.md").write_text(
        "# Release ledger\n\n| date_utc | product | version | build_id | manifest_sha256 | actor | notes |\n"
        "|---|---|---|---|---|---|---|\n"
        f"| 2026-10-26 | terminology | 9.9.9 | 28619916 | {digest} | test | fixture |\n",
        encoding="utf-8")

    # Added after the manifest so G1 reports them as unlisted.
    if secret:
        (root / "secrets.env").write_text("not-a-real-secret", encoding="utf-8")
    if extra_file:
        (root / "UNLISTED.txt").write_text("x", encoding="utf-8")

    return repo, root


class TestGates(unittest.TestCase):
    def ctx(self, repo, root):
        return Ctx(root=root, repo_root=repo)

    # ---- G1 -------------------------------------------------------------
    def test_g1_passes_clean_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, root = make_release(tmp)
            self.assertEqual(gates.g1_manifest(self.ctx(repo, root)).status, "PASS")

    def test_g1_detects_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, root = make_release(tmp)
            (root / "canonical_terms.jsonl").write_text('{"tampered":true}\n', encoding="utf-8")
            r = gates.g1_manifest(self.ctx(repo, root))
            self.assertEqual(r.status, "FAIL")
            self.assertTrue(any("DIGEST" in f for f in r.metrics["failures"]))

    def test_g1_flags_unlisted_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, root = make_release(tmp, extra_file=True)
            r = gates.g1_manifest(self.ctx(repo, root))
            self.assertEqual(r.status, "FAIL")
            self.assertIn("UNLISTED.txt", r.metrics["unlisted"])

    def test_g1_missing_manifest_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "empty"
            root.mkdir()
            r = gates.g1_manifest(Ctx(root=root, repo_root=Path(tmp)))
            self.assertEqual(r.status, "MISSING")

    # ---- G2 -------------------------------------------------------------
    def test_g2_catches_off_by_one(self):
        """The 2,505,736 vs 2,505,735 class of bug."""
        with tempfile.TemporaryDirectory() as tmp:
            repo, root = make_release(tmp, mentions=3, declared_mentions=3,
                                      coverage_mentions=4)
            r = gates.g2_counts(self.ctx(repo, root))
            self.assertEqual(r.status, "FAIL")
            self.assertTrue(r.metrics["known_off_by_one_detected"])

    def test_g2_catches_declared_vs_physical(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, root = make_release(tmp, mentions=3, declared_mentions=5,
                                      coverage_mentions=5)
            r = gates.g2_counts(self.ctx(repo, root))
            self.assertEqual(r.status, "FAIL")
            self.assertIn("term_mentions.jsonl", r.detail)

    def test_g2_passes_reconciled(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, root = make_release(tmp)
            self.assertEqual(gates.g2_counts(self.ctx(repo, root)).status, "PASS")

    # ---- G3 -------------------------------------------------------------
    def test_g3_pair_resolves(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, root = make_release(tmp)
            r = gates.g3_referential(self.ctx(repo, root))
            self.assertEqual(r.status, "PASS")
            self.assertEqual(r.metrics["pair_resolved"], 3)
            self.assertEqual(r.metrics["type_conflict"], 0)

    def test_g3_reports_type_conflict_without_failing(self):
        """A term that exists with a divergent observed type is a preserved
        type conflict, not a broken reference."""
        with tempfile.TemporaryDirectory() as tmp:
            repo, root = make_release(tmp, mention_type="DISEASE")
            r = gates.g3_referential(self.ctx(repo, root))
            self.assertEqual(r.status, "PASS")
            self.assertEqual(r.metrics["type_conflict"], 3)
            self.assertEqual(r.metrics["pair_resolved"], 0)
            self.assertEqual(r.metrics["term_coverage"], 1.0)

    def test_g3_fails_when_terms_are_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, root = make_release(tmp, mention_norm="not-in-canonical")
            r = gates.g3_referential(self.ctx(repo, root))
            self.assertEqual(r.status, "FAIL")
            self.assertEqual(r.metrics["term_missing"], 3)
            self.assertEqual(r.metrics["term_coverage"], 0.0)

    # ---- G4 -------------------------------------------------------------
    def _g4_fixture(self, tmp, mentions, checked_declared=None):
        repo, root = make_release(tmp, mentions=0)
        (root / "term_mentions.jsonl").write_text(
            "".join(json.dumps(m) + "\n" for m in mentions), encoding="utf-8")
        corpus = Path(tmp) / "corpusdata"
        corpus.mkdir(exist_ok=True)
        (corpus / "sections.jsonl").write_text(json.dumps({
            "paper_id": "P", "section_id_original": "s",
            "section_text_original": "abcdef",
        }) + "\n", encoding="utf-8")
        if checked_declared is not None:
            (root / "validation_summary.json").write_text(json.dumps({
                "mention_offset_verification": {"mentions_checked": checked_declared}}),
                encoding="utf-8")
        return Ctx(root=root, repo_root=repo, corpus_data=corpus)

    @staticmethod
    def _mention(i, start, end, surface):
        return {"mention_id": f"M{i}", "paper_id": "P", "section_id": "s",
                "start_offset": start, "end_offset": end, "surface_form": surface}

    def test_g4_exact_offsets_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = self._g4_fixture(tmp, [self._mention(0, 1, 3, "bc")])
            r = gates.g4_offsets(ctx)
            self.assertEqual(r.status, "PASS")
            self.assertEqual(r.metrics["exact"], 1)

    def test_g4_bounded_shift_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = self._g4_fixture(tmp, [self._mention(0, 2, 4, "bc")])  # needs -1
            r = gates.g4_offsets(ctx)
            self.assertEqual(r.status, "PASS")
            self.assertEqual(r.metrics["shift_histogram"].get("-1"), 1)

    def test_g4_out_of_range_without_declaration_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = self._g4_fixture(tmp, [self._mention(0, 99, 100, "zz")])
            self.assertEqual(gates.g4_offsets(ctx).status, "FAIL")

    def test_g4_out_of_range_declared_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = self._g4_fixture(tmp, [self._mention(0, 1, 3, "bc"),
                                         self._mention(1, 99, 100, "zz")],
                                   checked_declared=1)
            r = gates.g4_offsets(ctx)
            self.assertEqual(r.status, "PASS")
            self.assertEqual(r.metrics["excluded_unaccounted"], 0)

    # ---- G5 -------------------------------------------------------------
    def test_g5_fails_auto_accept_without_calibration(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, root = make_release(tmp, auto_accepted=1, calibration="NOT_CALIBRATED")
            r = gates.g5_calibration(self.ctx(repo, root))
            self.assertEqual(r.status, "FAIL")

    def test_g5_passes_zero_auto_accept(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, root = make_release(tmp, auto_accepted=0)
            r = gates.g5_calibration(self.ctx(repo, root))
            self.assertEqual(r.status, "PASS")
            self.assertEqual(r.metrics["auto_accepted_declared"], 0)

    # ---- G8 -------------------------------------------------------------
    def test_g8_detects_secret_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, root = make_release(tmp, secret=True)
            r = gates.g8_secrets(self.ctx(repo, root))
            self.assertEqual(r.status, "FAIL")
            self.assertTrue(any("secrets.env" in h for h in r.metrics["hits"]))

    def test_g8_detects_missing_gitignore_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, root = make_release(tmp)
            (repo / ".gitignore").write_text("*.pyc\n", encoding="utf-8")
            r = gates.g8_secrets(self.ctx(repo, root))
            self.assertEqual(r.status, "FAIL")
            self.assertIn("secrets.env", r.metrics["gitignore_missing_rules"])

    # ---- G10 ------------------------------------------------------------
    def test_g10_missing_provenance_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, root = make_release(tmp)
            (root / "PROVENANCE.json").unlink()
            self.assertEqual(gates.g10_provenance(self.ctx(repo, root)).status, "MISSING")

    # ---- non-terminology ------------------------------------------------
    def test_g5_not_applicable_for_corpus(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "corpus"
            root.mkdir()
            (root / "corpus_manifest.json").write_text("{}", encoding="utf-8")
            self.assertEqual(gates.g5_calibration(Ctx(root=root, repo_root=Path(tmp))).status,
                             "NOT_APPLICABLE")

    def test_g6_not_applicable_outside_releases_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "corpus_v2" / "releases" / "2.2.0"
            root.mkdir(parents=True)
            (root / "corpus_manifest.json").write_text("{}", encoding="utf-8")
            self.assertEqual(gates.g6_ledger(Ctx(root=root, repo_root=Path(tmp))).status,
                             "NOT_APPLICABLE")

    # ---- G7 -------------------------------------------------------------
    def test_g7_flags_bare_retired_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "README.md"
            doc.write_text("| rows | 2,505,736 |\n", encoding="utf-8")
            r = gates.g7_docs(Ctx(root=Path(tmp), repo_root=Path(tmp)), files=[doc])
            self.assertEqual(r.status, "FAIL")

    def test_g7_exempts_documented_retirement(self):
        """Documenting that a value is the known off-by-one is not a stale claim."""
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "README.md"
            doc.write_text(
                "the single failure is G2, the off-by-one 2,505,736 vs 2,505,735\n"
                "the pre-fix 334,275-row table is quarantined\n"
                "166,012 canonical terms (a separate chain run, not production)\n",
                encoding="utf-8")
            r = gates.g7_docs(Ctx(root=Path(tmp), repo_root=Path(tmp)), files=[doc])
            self.assertEqual(r.status, "PASS", r.metrics)

    # ---- CLI ------------------------------------------------------------
    @staticmethod
    def _p03_ready(repo, root):
        """Give a fixture release what the P0.3 CLI gates (G2/G5/G8) read.

        G2 needs a coverage count for all four artifacts; G5 needs the
        calibration summary and review sheet under the repo's
        outputs/results/terminology_v1/calibration/.
        """
        manifest_path = root / "terminology_extraction_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["coverage"].update({"canonical_terms_records": 1,
                                     "definition_records": 1, "mapping_records": 1})
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        _refresh_manifest(root)
        calib = repo / "outputs" / "results" / "terminology_v1" / "calibration"
        calib.mkdir(parents=True)
        (calib / "_calibration_sample_summary.json").write_text(
            json.dumps({"status": "NOT_CALIBRATED", "sample_size": 0}), encoding="utf-8")
        (calib / "calibration_sample.csv").write_text("mapping_id,verdict\n", encoding="utf-8")

    def test_cli_exit_codes(self):
        from scripts.release_gates.check_all import main
        with tempfile.TemporaryDirectory() as tmp:
            repo, root = make_release(Path(tmp) / "good")
            self._p03_ready(repo, root)
            report = Path(tmp) / "report.json"
            self.assertEqual(main(["--release", str(root), "--repo-root", str(repo),
                                   "--report", str(report)]), 0)
            self.assertTrue(report.is_file())
            self.assertEqual(json.loads(report.read_text())["summary"]["FAIL"], 0)
            self.assertTrue((repo / "outputs" / "logs" / "p0_3_summary.md").is_file())

            repo2, root2 = make_release(Path(tmp) / "bad", coverage_mentions=99)
            self._p03_ready(repo2, root2)
            report2 = Path(tmp) / "r2.json"
            self.assertEqual(main(["--release", str(root2), "--repo-root", str(repo2),
                                   "--report", str(report2)]), 1)
            gates_out = json.loads(report2.read_text())["gates"]
            self.assertEqual(gates_out["G2"]["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
