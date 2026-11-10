"""Regression tests for the retry accounting in `repair_catalogue_cache.py`.

Why this exists: passes 1-5 of the catalogue repair recorded only a `modes`
tally, so the sentence "retrying was not the lever" could not be checked
against a produced artifact for split-mode trees -- `attempts` is written into
the per-node info dict only in `direct` mode. The pass-4 negative (4 attempts
per leaf, 0 repaired) is real evidence, but it is one run, not a per-node
histogram.

`Repairer` now keeps four running totals so the next run reports the numbers
instead of the assertion. Their invariants are the point of this file:

  * ``attempts_total == api_calls`` -- every HTTP request belongs to exactly
    one node, so the totals must add up to the call count. If they do not,
    some call path is not being accounted for.
  * ``nodes_asked == nodes_ok + nodes_failed`` -- a node that exhausted its
    retries and failed is still a node the tree asked about. Omitting those
    would make the totals look cheaper than the run actually was.
  * ``retried_ok`` counts only nodes that needed more than one attempt.

Run with:  PYTHONPATH=src python -m unittest tests.test_repair_accounting -v
"""

import importlib.util
import unittest
from pathlib import Path

REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".cdm_root").is_file())


def _load(name, relpath):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / relpath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


repair = _load("repair_catalogue_cache", "src/scripts/vllm_termpop/repair_catalogue_cache.py")
catalogue = _load("catalogue_ner", "src/scripts/vllm_termpop/catalogue_ner.py")

TRUNCATED = ValueError("response truncated by max_tokens (finish_reason=length)")


class FakeClient:
    """Scripted client: each call pops the next scripted outcome.

    ``None`` means "fits, return one record". A ``ValueError`` instance means
    "raise it" (truncation). A plain ``RuntimeError`` means "raise it" (transport
    error, which must not be retried).
    """

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def chat(self, text, group):
        self.calls += 1
        if not self.script:
            raise AssertionError("FakeClient called more times than scripted")
        outcome = self.script.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return {"findings": [{"outcome": "x"}]}

    def _merge(self, parts, group):
        out = {"findings": []}
        for p in parts:
            out["findings"].extend(p.get("findings") or [])
        return out


def make_repairer(client, depth=8, min_chars=10, call_budget=100, leaf_retries=0):
    return repair.Repairer(catalogue, client, depth, min_chars, call_budget, leaf_retries)


class InvariantTests(unittest.TestCase):
    def assertInvariants(self, rp, client):
        self.assertEqual(
            rp.attempts_total,
            client.calls,
            "attempts_total must equal the number of requests actually issued",
        )
        self.assertEqual(rp.attempts_total, rp.calls)
        # Every node the tree asked about cost at least one request, and only
        # some of them eventually fit — so the two bounds below must hold for
        # any non-buggy run.
        self.assertGreaterEqual(rp.attempts_total, rp.nodes_asked)
        self.assertLessEqual(rp.nodes_ok, rp.nodes_asked)
        self.assertLessEqual(rp.max_attempts_used, max(1, rp.attempts_total))

    def test_single_direct_success(self):
        client = FakeClient([None])
        rp = make_repairer(client)
        recs, info = rp.repair("a short passage that fits", ["findings"])
        self.assertEqual(info["mode"], "direct")
        self.assertEqual(info["attempts"], 1)
        self.assertEqual(rp.nodes_asked, 1)
        self.assertEqual(rp.nodes_ok, 1)
        self.assertEqual(rp.retried_ok, 0)
        self.assertEqual(rp.max_attempts_used, 1)
        self.assertInvariants(rp, client)

    def test_retry_then_success_is_counted_as_retried_ok(self):
        client = FakeClient([TRUNCATED, None])
        rp = make_repairer(client, leaf_retries=1)
        recs, info = rp.repair("a short passage that fits", ["findings"])
        self.assertEqual(info["mode"], "direct")
        self.assertEqual(info["attempts"], 2)
        self.assertEqual(rp.nodes_ok, 1)
        self.assertEqual(rp.retried_ok, 1)
        self.assertEqual(rp.max_attempts_used, 2)
        self.assertInvariants(rp, client)

    def test_failed_node_is_counted_even_though_it_produced_nothing(self):
        """The whole point: a node that never fits must still appear in the totals."""
        # depth=0 forbids splitting, so two truncations mean a failed target.
        client = FakeClient([TRUNCATED, TRUNCATED])
        rp = make_repairer(client, depth=0, leaf_retries=1)
        with self.assertRaises(RuntimeError):
            rp.repair("a passage too long to fit", ["findings"])
        self.assertEqual(rp.nodes_asked, 1)
        self.assertEqual(rp.nodes_ok, 0)
        self.assertEqual(rp.attempts_total, 2)
        self.assertEqual(rp.max_attempts_used, 2)
        self.assertEqual(rp.retried_ok, 0, "a failure is not a retried success")
        self.assertInvariants(rp, client)

    def test_split_totals_cover_both_halves(self):
        # Root truncates (twice, exhausting retries), then both halves fit.
        text = "x" * 40 + " " + "y" * 40
        client = FakeClient([TRUNCATED, TRUNCATED, None, None])
        rp = make_repairer(client, depth=2, min_chars=10, leaf_retries=1)
        recs, info = rp.repair(text, ["findings"])
        self.assertEqual(info["mode"], "split")
        self.assertEqual(rp.nodes_asked, 3, "one failed root + two successful leaves")
        self.assertEqual(rp.nodes_ok, 2)
        self.assertEqual(rp.attempts_total, 4)
        self.assertEqual(rp.max_attempts_used, 2)
        self.assertInvariants(rp, client)

    def test_transport_error_is_not_retried_and_not_double_counted(self):
        client = FakeClient([RuntimeError("connection reset")])
        rp = make_repairer(client, leaf_retries=3)
        with self.assertRaises(RuntimeError):
            rp.repair("a passage", ["findings"])
        self.assertEqual(client.calls, 1, "a transport error must not be multiplied")
        self.assertEqual(rp.attempts_total, 1, "the one issued request is still counted")
        self.assertEqual(rp.nodes_asked, 1)
        self.assertEqual(rp.nodes_ok, 0)
        self.assertInvariants(rp, client)

    def test_budget_exhaustion_issues_no_request_and_counts_none(self):
        client = FakeClient([])
        rp = make_repairer(client, call_budget=0)
        with self.assertRaises(RuntimeError) as ctx:
            rp.repair("a passage", ["findings"])
        self.assertIn("budget", str(ctx.exception))
        self.assertEqual(client.calls, 0)
        self.assertEqual(rp.attempts_total, 0, "no request was issued, so none is counted")
        self.assertEqual(rp.nodes_asked, 0)
        self.assertInvariants(rp, client)

    def test_direct_attempts_field_matches_recorded_tries(self):
        """The per-node `attempts` must agree with the aggregate for that node."""
        client = FakeClient([TRUNCATED, TRUNCATED, None])
        rp = make_repairer(client, leaf_retries=2)
        recs, info = rp.repair("a passage", ["findings"])
        self.assertEqual(info["attempts"], 3)
        self.assertEqual(rp.attempts_total, info["attempts"])
        self.assertEqual(rp.retried_ok, 1)
        self.assertInvariants(rp, client)


if __name__ == "__main__":
    unittest.main()
