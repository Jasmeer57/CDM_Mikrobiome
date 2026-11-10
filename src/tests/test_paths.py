"""Tests for cdm_pipeline.paths — dataset path resolution.

Covers the two properties that matter for a future ``data/`` migration:
  1. Defaults resolve to exactly the current on-disk locations (no behavior change).
  2. Environment overrides redirect each dataset, and are read at call time.
"""
import importlib
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cdm_pipeline import paths  # noqa: E402


class TestDefaultResolution(unittest.TestCase):
    """Defaults must match the current repo layout exactly."""

    def test_repo_root_is_repo_root(self):
        self.assertEqual(paths.REPO_ROOT, REPO_ROOT)

    def test_papers_txt_default(self):
        self.assertEqual(paths.papers_txt(), REPO_ROOT / "data/papers_txt")

    def test_pdfs_default(self):
        self.assertEqual(paths.pdfs_dir(), REPO_ROOT / "data" / "pdfs")

    def test_corpus_fulltext_default(self):
        self.assertEqual(paths.corpus_fulltext_dir(), REPO_ROOT / "data" / "fulltext")

    def test_samples_paper_default(self):
        self.assertEqual(paths.samples_paper_dir(), REPO_ROOT / "data/168000-samples-paper")

    def test_samples_fulltext_default_is_nested(self):
        self.assertEqual(
            paths.samples_fulltext_dir(), REPO_ROOT / "data/168000-samples-paper" / "fulltext"
        )

    def test_bioproject_export_default(self):
        self.assertEqual(
            paths.bioproject_export(), REPO_ROOT / "data" / "bioproject_data_export.json"
        )

    def test_all_return_absolute_paths(self):
        for fn in (
            paths.papers_txt,
            paths.pdfs_dir,
            paths.corpus_fulltext_dir,
            paths.samples_paper_dir,
            paths.samples_fulltext_dir,
            paths.bioproject_export,
        ):
            with self.subTest(fn=fn.__name__):
                self.assertTrue(fn().is_absolute())

    def test_corpus_and_samples_fulltext_are_distinct(self):
        """Two different directories are both called 'fulltext'; they must not alias."""
        self.assertNotEqual(paths.corpus_fulltext_dir(), paths.samples_fulltext_dir())


class TestEnvOverrides(unittest.TestCase):
    """Each dataset honors its CDM_* environment variable."""

    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in (
            paths.ENV_PAPERS_TXT, paths.ENV_PDFS, paths.ENV_FULLTEXT,
            paths.ENV_SAMPLES_PAPER, paths.ENV_BIOPROJECT_EXPORT,
        )}

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_papers_txt_override(self):
        os.environ[paths.ENV_PAPERS_TXT] = "/tmp/custom_papers"
        self.assertEqual(paths.papers_txt(), Path("/tmp/custom_papers"))

    def test_pdfs_override(self):
        os.environ[paths.ENV_PDFS] = "/tmp/custom_pdfs"
        self.assertEqual(paths.pdfs_dir(), Path("/tmp/custom_pdfs"))

    def test_corpus_fulltext_override(self):
        os.environ[paths.ENV_FULLTEXT] = "/tmp/custom_ft"
        self.assertEqual(paths.corpus_fulltext_dir(), Path("/tmp/custom_ft"))

    def test_samples_paper_override_moves_nested_fulltext(self):
        os.environ[paths.ENV_SAMPLES_PAPER] = "/tmp/custom_samples"
        self.assertEqual(paths.samples_paper_dir(), Path("/tmp/custom_samples"))
        # nested fulltext must follow the parent override
        self.assertEqual(
            paths.samples_fulltext_dir(), Path("/tmp/custom_samples/fulltext")
        )

    def test_bioproject_export_override(self):
        os.environ[paths.ENV_BIOPROJECT_EXPORT] = "/tmp/bp.json"
        self.assertEqual(paths.bioproject_export(), Path("/tmp/bp.json"))

    def test_override_is_read_at_call_time_not_import_time(self):
        """Changing the env after import must take effect without re-importing."""
        os.environ[paths.ENV_PAPERS_TXT] = "/tmp/first"
        self.assertEqual(paths.papers_txt(), Path("/tmp/first"))
        os.environ[paths.ENV_PAPERS_TXT] = "/tmp/second"
        self.assertEqual(paths.papers_txt(), Path("/tmp/second"))

    def test_empty_value_falls_back_to_default(self):
        """CDM_PAPERS_TXT= must not silently resolve to the CWD."""
        os.environ[paths.ENV_PAPERS_TXT] = ""
        self.assertEqual(paths.papers_txt(), REPO_ROOT / "data/papers_txt")

    def test_relative_override_resolves_against_cwd(self):
        os.environ[paths.ENV_PAPERS_TXT] = "rel_papers"
        expected = (Path.cwd() / "rel_papers").resolve()
        self.assertEqual(paths.papers_txt(), expected)

    def test_config_module_reflects_same_defaults(self):
        """cdm_pipeline.config constants must agree with the resolver defaults."""
        from cdm_pipeline import config
        self.assertEqual(config.PAPERS_DIR, paths.papers_txt())
        self.assertEqual(config.BIOPROJECT_JSON, paths.bioproject_export())
        self.assertEqual(config.REPO_ROOT, paths.REPO_ROOT)


class TestModuleSurface(unittest.TestCase):
    def test_public_callables_exist(self):
        for name in (
            "papers_txt", "pdfs_dir", "corpus_fulltext_dir",
            "samples_paper_dir", "samples_fulltext_dir", "bioproject_export",
            "segmented_markdown_dir", "ner_tools_dir", "find_repo_root",
        ):
            self.assertTrue(callable(getattr(paths, name)), name)

    def test_reimport_is_idempotent(self):
        importlib.reload(paths)
        self.assertEqual(paths.REPO_ROOT, REPO_ROOT)


class TestRepoRootDiscovery(unittest.TestCase):
    def test_root_holds_the_marker(self):
        self.assertTrue((paths.REPO_ROOT / paths.ROOT_MARKER).is_file())

    def test_walks_up_from_a_nested_start(self):
        nested = paths.REPO_ROOT / "src" / "cdm_pipeline" / "ner"
        self.assertEqual(paths.find_repo_root(nested), paths.REPO_ROOT)

    def test_env_override_wins(self):
        os.environ[paths.ENV_REPO_ROOT] = "/tmp"
        try:
            self.assertEqual(paths.find_repo_root(), Path("/tmp").resolve())
        finally:
            del os.environ[paths.ENV_REPO_ROOT]

    def test_missing_marker_fails_loudly(self):
        os.environ.pop(paths.ENV_REPO_ROOT, None)
        with self.assertRaises(RuntimeError):
            paths.find_repo_root("/")

    def test_layout_groups_exist(self):
        for d in (paths.SRC_DIR, paths.PIPELINES_DIR, paths.DATA_DIR,
                  paths.OUTPUTS_DIR, paths.RELEASES_DIR, paths.PAPER_DIR,
                  paths.CORPUS_V2_DIR, paths.RESULTS_DIR, paths.FROZEN_OUTPUT_DIR):
            self.assertTrue(d.is_dir(), d)

    def test_segmented_markdown_default(self):
        self.assertEqual(paths.segmented_markdown_dir(),
                         REPO_ROOT / "data" / "segmented_sections_markdown")
        self.assertEqual(len(list(paths.segmented_markdown_dir().glob("HMPAPER_*.md"))), 453)


if __name__ == "__main__":
    unittest.main()