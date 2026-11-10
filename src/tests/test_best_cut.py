"""Regression tests for the whitespace-aware halving cut.

`best_cut` is the split point used by catalogue-NER's recursive halving: both
the production runner (`src/scripts/vllm_termpop/catalogue_ner.py`) and the cache
repair tool (`src/scripts/vllm_termpop/repair_catalogue_cache.py`) must split a
passage at the *same* offset, otherwise a repaired span and a freshly extracted
span would be cut differently.

The bug these tests pin: the original rule was `text.rfind(" ", 0, len//2)` with
no fallback. Flattened statistical tables are newline/tab separated, so they can
contain no space before the midpoint at all; `rfind` then returned -1, the
split path raised, and no amount of retrying could make progress. Two repair
passes stalled on `HMPAPER_000024 sec_001` (3,983 chars of `137.9\n-\n4382476\n…`)
for exactly this reason.

Run with:  PYTHONPATH=src python -m unittest tests.test_best_cut -v
"""

import importlib.util
import unittest
from pathlib import Path

REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())


def _load(name, relpath):
    """Load a script by path — these live outside the installed package."""
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / relpath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class BestCutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ner = _load("catalogue_ner_under_test", "src/scripts/vllm_termpop/catalogue_ner.py")
        cls.rep = _load("repair_catalogue_under_test",
                        "src/scripts/vllm_termpop/repair_catalogue_cache.py")

    def test_midpoint_fallback_when_no_space_before_midpoint(self):
        """A digits-only run has no space at all; rfind would return -1."""
        text = "9" * 4000
        self.assertEqual(text.rfind(" ", 0, len(text) // 2), -1)  # the old bug
        self.assertEqual(self.ner.best_cut(text), 2000)

    def test_newline_separated_table(self):
        """Table rows separated by newlines only — the real failing shape."""
        text = "\n".join(str(i) for i in range(4000))
        cut = self.ner.best_cut(text)
        self.assertGreater(cut, 0)
        self.assertLess(cut, len(text))
        self.assertEqual(text[cut - 1], "\n")  # cut sits just past a newline

    def test_prefers_space_when_one_exists(self):
        text = "aaaa bbbb cccc dddd"
        cut = self.ner.best_cut(text)
        self.assertEqual(text[cut], " ")
        self.assertLessEqual(cut, len(text) // 2)

    def test_both_halves_strictly_smaller(self):
        """Recursion must terminate: a cut at 0 or len would loop forever."""
        for text in ("ab", "a" * 7, "x" * 1000, "\n".join(["12"] * 500)):
            cut = self.ner.best_cut(text)
            self.assertGreater(cut, 0, msg=repr(text[:20]))
            self.assertLess(cut, len(text), msg=repr(text[:20]))

    def test_degenerate_inputs_return_minus_one(self):
        for text in ("", "x"):
            self.assertEqual(self.ner.best_cut(text), -1)

    def test_runner_and_repairer_agree_on_real_sections(self):
        """The two copies must not drift — they cut real corpus text."""
        units, _ = self.ner.load_sections(str(self.ner.SEG_DIR_DEFAULT), None,
                                          body_only=False)
        compared = 0
        for unit in units:
            text = unit["text"] or ""
            if len(text) < 2:
                continue
            compared += 1
            self.assertEqual(self.ner.best_cut(text), self.rep.best_cut(text),
                             msg="%s %s" % (unit["cid"], unit["section_id"]))
        self.assertGreater(compared, 0, "no sections loaded — check SEG_DIR_DEFAULT")

    def test_regression_hmpaper_000024_table_slice(self):
        """The exact span that stalled repair passes 3 and 4, if corpus present."""
        units, _ = self.ner.load_sections(str(self.ner.SEG_DIR_DEFAULT), None,
                                          body_only=False)
        sect = {(u["cid"], u["section_id"]): (u["text"] or "") for u in units}
        text = sect.get(("HMPAPER_000024", "sec_001"))
        if text is None:
            self.skipTest("HMPAPER_000024 sec_001 not in this corpus checkout")
        slice_ = text[63519:67502]
        self.assertEqual(len(slice_), 3983)
        self.assertEqual(slice_.rfind(" ", 0, len(slice_) // 2), -1)  # old rule failed
        cut = self.ner.best_cut(slice_)
        self.assertEqual(cut, 1988)
        self.assertEqual((len(slice_[:cut]), len(slice_[cut:])), (1988, 1995))


if __name__ == "__main__":
    unittest.main()
