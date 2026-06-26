"""Tests for check_cross_validation.py -- ADVISORY cross-family drift WARN.

The check is record-only and NON-BLOCKING. These tests pin:
  - never_run / match / drift verdicts (incl. which fields drifted)
  - a null current provenance field counts as drift (can't certify an unseen match)
  - last ledger entry wins; blank lines skipped; a corrupt line raises
  - run_cli is advisory: exit 0 even when it WARNs; only bad input/ledger -> 1
"""

import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from check_cross_validation import (  # noqa: E402
    check_cross_validation,
    read_last_ledger_entry,
    run_cli,
    PROVENANCE_FIELDS,
)


SEED = {
    "date": "2026-06-23",
    "grader_version_id": "claude-opus-4-8",
    "golden_set_version": "v2",
    "split_hash": "sha256:b25a9ada4ff2eb5751945befd08c1f42384a34b71d6998941e86d6b52439117c",
    "verdict": "hold",
}


def _matching_current():
    return {f: SEED[f] for f in PROVENANCE_FIELDS}


class TestCheckLogic(unittest.TestCase):
    def test_never_run_warns(self):
        r = check_cross_validation(_matching_current(), None)
        self.assertTrue(r["ok"])
        self.assertTrue(r["warn"])
        self.assertEqual(r["reason"], "never_run")
        self.assertEqual(set(r["changed"]), set(PROVENANCE_FIELDS))
        self.assertIsNone(r["last_check"])

    def test_full_match_no_warn(self):
        r = check_cross_validation(_matching_current(), SEED)
        self.assertTrue(r["ok"])
        self.assertFalse(r["warn"])
        self.assertEqual(r["reason"], "match")
        self.assertEqual(r["changed"], [])
        self.assertEqual(r["last_check"], SEED)

    def test_grader_drift_warns_with_field(self):
        cur = _matching_current()
        cur["grader_version_id"] = "claude-sonnet-4-6"
        r = check_cross_validation(cur, SEED)
        self.assertTrue(r["warn"])
        self.assertEqual(r["reason"], "drift")
        self.assertEqual(r["changed"], ["grader_version_id"])

    def test_goldenset_drift_warns(self):
        cur = _matching_current()
        cur["golden_set_version"] = "v3"
        r = check_cross_validation(cur, SEED)
        self.assertTrue(r["warn"])
        self.assertEqual(r["changed"], ["golden_set_version"])

    def test_split_drift_warns(self):
        cur = _matching_current()
        cur["split_hash"] = "sha256:different"
        r = check_cross_validation(cur, SEED)
        self.assertTrue(r["warn"])
        self.assertEqual(r["changed"], ["split_hash"])

    def test_multiple_fields_drift_reported_in_order(self):
        cur = {"grader_version_id": "x", "golden_set_version": "y", "split_hash": "z"}
        r = check_cross_validation(cur, SEED)
        self.assertTrue(r["warn"])
        # Reported in PROVENANCE_FIELDS order.
        self.assertEqual(r["changed"], list(PROVENANCE_FIELDS))

    def test_missing_current_field_counts_as_drift(self):
        # A None/absent current field can never equal a recorded value -> drift,
        # never a silent match. (fail-loud-but-soft)
        cur = _matching_current()
        del cur["grader_version_id"]
        r = check_cross_validation(cur, SEED)
        self.assertTrue(r["warn"])
        self.assertIn("grader_version_id", r["changed"])
        # current view shows the unseen field as None.
        self.assertIsNone(r["current"]["grader_version_id"])

    def test_null_current_drifts_even_when_ledger_field_also_null(self):
        # L1 fail-safe edge: a null current field must count as drift EVEN when
        # the ledger's same field is also null. Plain `!=` would let None == None
        # resolve to a silent match; "I cannot read this field" must always warn.
        ledger = dict(SEED, grader_version_id=None)
        cur = _matching_current()
        cur["grader_version_id"] = None
        r = check_cross_validation(cur, ledger)
        self.assertTrue(r["warn"])
        self.assertEqual(r["reason"], "drift")
        self.assertIn("grader_version_id", r["changed"])


class TestLedgerReading(unittest.TestCase):
    def _write_ledger(self, text):
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        self.addCleanup(os.remove, path)
        return path

    def test_missing_file_returns_none(self):
        self.assertIsNone(read_last_ledger_entry("/nonexistent/ledger.jsonl"))

    def test_last_entry_wins(self):
        e1 = dict(SEED, date="2026-06-23", grader_version_id="claude-opus-4-8")
        e2 = dict(SEED, date="2026-07-01", grader_version_id="claude-opus-9-9")
        path = self._write_ledger(json.dumps(e1) + "\n" + json.dumps(e2) + "\n")
        last = read_last_ledger_entry(path)
        self.assertEqual(last["grader_version_id"], "claude-opus-9-9")

    def test_blank_lines_skipped(self):
        path = self._write_ledger("\n" + json.dumps(SEED) + "\n\n")
        last = read_last_ledger_entry(path)
        self.assertEqual(last["date"], "2026-06-23")

    def test_corrupt_line_raises(self):
        path = self._write_ledger(json.dumps(SEED) + "\nnot json\n")
        with self.assertRaises(ValueError):
            read_last_ledger_entry(path)

    def test_empty_file_returns_none(self):
        path = self._write_ledger("\n   \n")
        self.assertIsNone(read_last_ledger_entry(path))


class TestRunCliAdvisory(unittest.TestCase):
    """run_cli MUST be non-blocking: exit 0 even when warning. The only non-zero
    paths are a malformed request or a corrupt ledger (operator error)."""

    def _run(self, payload):
        """Drive run_cli with a JSON payload via stdin, capturing stdout + code."""
        old_stdin, old_stdout = sys.stdin, sys.stdout
        sys.stdin = io.StringIO(json.dumps(payload))
        sys.stdout = io.StringIO()
        try:
            code = run_cli([])  # no argv -> reads stdin
            out = sys.stdout.getvalue()
        finally:
            sys.stdin, sys.stdout = old_stdin, old_stdout
        return code, json.loads(out)

    def _write_ledger(self, text):
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        self.addCleanup(os.remove, path)
        return path

    def test_warn_still_exits_zero(self):
        # never_run is a WARN; the process must still succeed (advisory).
        code, result = self._run({
            "grader_version_id": "x", "golden_set_version": "v2",
            "split_hash": "sha256:zzz",
            "ledger_path": "/nonexistent/ledger.jsonl",
        })
        self.assertEqual(code, 0)
        self.assertTrue(result["warn"])
        self.assertEqual(result["reason"], "never_run")

    def test_match_exits_zero_no_warn(self):
        path = self._write_ledger(json.dumps(SEED) + "\n")
        cur = _matching_current()
        cur["ledger_path"] = path
        code, result = self._run(cur)
        self.assertEqual(code, 0)
        self.assertFalse(result["warn"])

    def test_corrupt_ledger_exits_one(self):
        # A corrupt ledger is an operator error the human should see -> ok:false,
        # exit 1 (this is NOT a verdict about the run, it's a bad-input signal).
        path = self._write_ledger(json.dumps(SEED) + "\ngarbage\n")
        cur = _matching_current()
        cur["ledger_path"] = path
        code, result = self._run(cur)
        self.assertEqual(code, 1)
        self.assertFalse(result["ok"])

    def test_non_object_payload_exits_one(self):
        old_stdin, old_stdout = sys.stdin, sys.stdout
        sys.stdin = io.StringIO("[1, 2, 3]")
        sys.stdout = io.StringIO()
        try:
            code = run_cli([])
            out = sys.stdout.getvalue()
        finally:
            sys.stdin, sys.stdout = old_stdin, old_stdout
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(out)["ok"])


if __name__ == "__main__":
    unittest.main()
