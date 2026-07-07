"""Smoke tests for the CLI surface: each script must be runnable, reading JSON
from a file path AND from stdin, emitting JSON, with an exit code mirroring the
decision. This is what SKILL.md shells out to."""

import json
import os
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run(script, payload, via="stdin"):
    """Run a script with ``payload`` (dict) via stdin or a temp file.
    Returns (returncode, parsed_json_stdout)."""
    path = os.path.join(SCRIPTS, script)
    if via == "stdin":
        proc = subprocess.run(
            [sys.executable, path],
            input=json.dumps(payload),
            capture_output=True, text=True,
        )
    else:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(payload, fh)
            tmp = fh.name
        try:
            proc = subprocess.run(
                [sys.executable, path, tmp],
                capture_output=True, text=True,
            )
        finally:
            os.unlink(tmp)
    out = json.loads(proc.stdout) if proc.stdout.strip() else None
    return proc.returncode, out, proc.stderr


class TestVerifyChangeCLI(unittest.TestCase):
    def test_stdin_pass(self):
        rc, out, err = _run("verify_change.py", {
            "target_text": "alpha beta gamma", "before": "beta", "after": "BETA",
        }, via="stdin")
        self.assertEqual(rc, 0, err)
        self.assertTrue(out["ok"])

    def test_file_reject_multi(self):
        rc, out, err = _run("verify_change.py", {
            "target_text": "foo bar foo", "before": "foo", "after": "X",
        }, via="file")
        self.assertEqual(rc, 1)
        self.assertFalse(out["ok"])


class TestScoreCompareCLI(unittest.TestCase):
    def test_merge_decision(self):
        rc, out, err = _run("score_compare.py", {
            "train_b": 0.70, "train_a": 0.78, "held_b": 0.65, "held_a": 0.70,
            "eps_train": 0.03, "eps_heldout": 0.04, "mode": "merge",
        }, via="stdin")
        self.assertEqual(rc, 0, err)
        self.assertEqual(out["decision"], "MERGE")

    def test_halt_decision(self):
        rc, out, err = _run("score_compare.py", {
            "train_b": 0.78, "train_a": 0.85, "held_b": 0.70, "held_a": 0.58,
            "eps_train": 0.03, "eps_heldout": 0.04,
        }, via="file")
        self.assertEqual(rc, 0)
        self.assertEqual(out["decision"], "HALT")

    def test_missing_field_errors(self):
        rc, out, err = _run("score_compare.py", {"train_b": 0.7}, via="stdin")
        self.assertEqual(rc, 1)
        self.assertFalse(out["ok"])


class TestCalibrateCLI(unittest.TestCase):
    def test_calibrate_stdin(self):
        rc, out, err = _run("calibrate_noise.py", {
            "samples": {"train": [0.70, 0.72, 0.68], "heldout": [0.65, 0.66, 0.64]},
        }, via="stdin")
        self.assertEqual(rc, 0, err)
        self.assertIn("eps_train", out)
        self.assertIn("eps_heldout", out)


class TestResumeCLI(unittest.TestCase):
    def test_read_init_when_absent(self):
        rc, out, err = _run("resume.py", {"op": "read", "state_path": "/nonexistent/state.json"}, via="stdin")
        self.assertEqual(rc, 0, err)
        self.assertTrue(out["ok"])
        self.assertEqual(out["state"]["turn"], 1)

    def test_record_decision_roundtrip(self):
        d = tempfile.mkdtemp()
        sp = os.path.join(d, "state.json")
        rc, out, err = _run("resume.py", {
            "op": "record_decision", "state_path": sp, "turn": 1, "decision": "DISCARD",
        }, via="file")
        self.assertEqual(rc, 0, err)
        self.assertEqual(out["state"]["no_progress_count"], 1)
        self.assertEqual(out["state"]["turn"], 2)
        self.assertTrue(os.path.exists(sp))
        import shutil
        shutil.rmtree(d, ignore_errors=True)

    def test_record_scores_roundtrip(self):
        d = tempfile.mkdtemp()
        sp = os.path.join(d, "state.json")
        rc, out, err = _run("resume.py", {
            "op": "record_scores", "state_path": sp,
            "prompt_hash": "sha256:abc", "train": 0.78, "heldout": 0.70,
        }, via="file")
        self.assertEqual(rc, 0, err)
        self.assertEqual(out["state"]["last_train"], 0.78)
        self.assertEqual(out["state"]["last_scored_prompt_hash"], "sha256:abc")
        import shutil
        shutil.rmtree(d, ignore_errors=True)


class TestApplyChangeCLI(unittest.TestCase):
    def test_apply_then_promote(self):
        d = tempfile.mkdtemp()
        cur = os.path.join(d, "prompt.current.md")
        cand = os.path.join(d, "prompt.candidate.md")
        with open(cur, "w") as fh:
            fh.write("alpha beta gamma")
        rc, out, err = _run("apply_change.py", {
            "op": "apply", "current_file": cur, "before": "beta", "after": "BETA",
            "candidate_file": cand,
        }, via="file")
        self.assertEqual(rc, 0, err)
        self.assertTrue(out["ok"])
        rc2, out2, err2 = _run("apply_change.py", {
            "op": "promote", "current_file": cur, "candidate_file": cand,
            "confirmed": True,
        }, via="file")
        self.assertEqual(rc2, 0, err2)
        self.assertTrue(out2["promoted"])
        # And promote REFUSES without the confirm flag (S7 wall).
        rc3, out3, err3 = _run("apply_change.py", {
            "op": "promote", "current_file": cur, "candidate_file": cand,
        }, via="file")
        self.assertEqual(rc3, 1)
        self.assertFalse(out3["ok"])
        import shutil
        shutil.rmtree(d, ignore_errors=True)


class TestAggregateScoresCLI(unittest.TestCase):
    def test_aggregate_stdin(self):
        rc, out, err = _run("aggregate_scores.py", {"scores": [
            {"case_id": "t1", "split": "train", "passed": 4, "total": 5},
            {"case_id": "h1", "split": "heldout", "passed": 2, "total": 3},
        ]}, via="stdin")
        self.assertEqual(rc, 0, err)
        self.assertEqual(out["train_score"], 0.8)
        self.assertIn("heldout_score", out)

    def test_aggregate_bad_input_errors(self):
        rc, out, err = _run("aggregate_scores.py", {"scores": [
            {"case_id": "c", "split": "train", "passed": 9, "total": 5},
        ]}, via="stdin")
        self.assertEqual(rc, 1)
        self.assertFalse(out["ok"])


class TestSplitGoldensetCLI(unittest.TestCase):
    def test_split_inline(self):
        cases = []
        for i in range(5):
            cases.append({"id": "n%d" % i, "realistic": False, "status": "active",
                          "input": "in%d" % i, "rubric": ["ok?"]})
        for i in range(3):
            cases.append({"id": "r%d" % i, "realistic": True, "status": "active",
                          "input": "rin%d" % i, "rubric": ["ok?"]})
        gs = {"target": "./t.md", "version": "v1",
              "min_size": {"train": 5, "heldout": 3}, "cases": cases}
        rc, out, err = _run("split_goldenset.py", {"op": "split", "golden_set": gs}, via="stdin")
        self.assertEqual(rc, 0, err)
        self.assertTrue(out["ok"])
        self.assertIn("split_hash", out)
        self.assertEqual(out["counts"]["heldout"], 3)


if __name__ == "__main__":
    unittest.main()
