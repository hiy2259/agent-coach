"""GAP-4 integration test: drive the REAL deterministic pipeline across multiple
scripts via their CLIs, the way the orchestrator does -- split -> calibrate ->
verify -> apply -> score_compare -> promote -> resume.

Every other test in this suite is a UNIT test (one function/script in isolation).
This is the only test that exercises the SEAMS between scripts, which is exactly
where the audit's pipeline-level defects lived:

  * F-01: confirm re-run was never code-enforced before promote.
  * F-04: a kept subtraction (SUB_KEEP) was never promoted to the live current
          prompt, so pruning was dead end-to-end.

Both are invisible to unit tests and only surface when the scripts run together.
The ONLY injected values are the train/held scores -- they stand in for the
Runner+Grader output, the one boundary an offline test must stub.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run(script, payload):
    """Run a script CLI with a JSON payload on stdin. Returns (rc, parsed, stderr)."""
    proc = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, script)],
        input=json.dumps(payload), capture_output=True, text=True,
    )
    out = json.loads(proc.stdout) if proc.stdout.strip() else None
    return proc.returncode, out, proc.stderr


def _sha(text):
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _write(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _golden_cases():
    cases = []
    for i in range(5):
        cases.append({"id": "t%d" % i, "realistic": False, "status": "active",
                      "input": "train input %d" % i, "rubric": ["ok t%d?" % i],
                      "split": "train"})
    for i in range(3):
        cases.append({"id": "h%d" % i, "realistic": True, "status": "active",
                      "input": "held input %d" % i, "rubric": ["ok h%d?" % i],
                      "split": "heldout"})
    return {"target": "./prompt.current.md", "version": "v1",
            "min_size": {"train": 5, "heldout": 3}, "cases": cases}


# Controlled noise margins. calibrate runs in the pipeline below to prove it
# works, but the GATE decisions use these fixed eps so the test is robust to
# calibrate's exact formula -- the injected deltas clear them by a wide margin.
EPS_T = 0.05
EPS_H = 0.05


class TestFullLoopIntegration(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.current = os.path.join(self.d, "prompt.current.md")
        self.candidate = os.path.join(self.d, "prompt.candidate.md")
        self.state = os.path.join(self.d, "state.json")
        self.gs_path = os.path.join(self.d, "golden-set.json")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _promote(self, confirmed):
        return _run("apply_change.py", {
            "op": "promote", "current_file": self.current,
            "candidate_file": self.candidate, "confirmed": confirmed,
        })

    def test_split_then_merge_then_subkeep_pipeline(self):
        # ---- 1) SPLIT + FREEZE (real) ----------------------------------------
        rc, out, err = _run("split_goldenset.py", {"op": "split", "golden_set": _golden_cases()})
        self.assertEqual(rc, 0, err)
        self.assertTrue(out["ok"])
        frozen = out["golden_set"]
        _write(self.gs_path, json.dumps(frozen))

        # ---- 2) VERIFY the freeze holds (real) -------------------------------
        rc, out, err = _run("split_goldenset.py", {"op": "verify", "golden_set": frozen})
        self.assertEqual(rc, 0, err)
        self.assertTrue(out["valid"], out)

        # ---- 3) CALIBRATE runs in the pipeline (real) ------------------------
        rc, out, err = _run("calibrate_noise.py", {"samples": {
            "train": [0.60, 0.61, 0.59, 0.60, 0.60],
            "heldout": [0.60, 0.60, 0.61, 0.59, 0.60],
        }})
        self.assertEqual(rc, 0, err)
        self.assertIn("eps_train", out)
        self.assertIn("eps_heldout", out)

        # ---- 4) MERGE turn ---------------------------------------------------
        _write(self.current, "Rule A. Rule B. Rule C.")

        # verify the proposed edit (real)
        rc, out, err = _run("verify_change.py", {
            "target_text": _read(self.current), "before": "Rule B.", "after": "Rule B refined.",
        })
        self.assertEqual(rc, 0, err)
        self.assertTrue(out["ok"])

        # apply to STAGING only (real; apply re-runs the full verify gate)
        rc, out, err = _run("apply_change.py", {
            "op": "apply", "current_file": self.current,
            "before": "Rule B.", "after": "Rule B refined.", "candidate_file": self.candidate,
        })
        self.assertEqual(rc, 0, err)
        self.assertTrue(out["ok"])
        # live current is still untouched at this point (S4 staging)
        self.assertEqual(_read(self.current), "Rule A. Rule B. Rule C.")

        # provisional gate: MERGE but confirm_required (real)
        rc, out, err = _run("score_compare.py", {
            "train_b": 0.60, "train_a": 0.76, "held_b": 0.60, "held_a": 0.64,
            "eps_train": EPS_T, "eps_heldout": EPS_H, "mode": "merge",
        })
        self.assertEqual(out["decision"], "MERGE")
        self.assertTrue(out["confirm_required"])

        # confirm gate: re-run reproduces the gain against a re-measured baseline
        # (train_b2/held_b2 -- the H4 fix re-runs the current prompt too) ->
        # confirmed MERGE (real)
        rc, out, err = _run("score_compare.py", {
            "train_b": 0.60, "train_a": 0.76, "held_b": 0.60, "held_a": 0.64,
            "eps_train": EPS_T, "eps_heldout": EPS_H, "mode": "merge",
            "train_a2": 0.75, "held_a2": 0.63, "train_b2": 0.60, "held_b2": 0.60,
        })
        self.assertEqual(out["decision"], "MERGE")
        self.assertTrue(out["confirmed"])

        # promote (confirmed) + record state (real)
        merged_text = _read(self.candidate)
        rc, out, err = self._promote(True)
        self.assertEqual(rc, 0, err)
        self.assertTrue(out["promoted"])
        _run("resume.py", {"op": "promote_done", "state_path": self.state,
                           "candidate_prompt_hash": _sha(merged_text)})
        rc, out, err = _run("resume.py", {"op": "record_decision", "state_path": self.state,
                                          "turn": 1, "decision": "MERGE"})
        self.assertEqual(rc, 0, err)
        self.assertEqual(out["state"]["turn"], 2)
        self.assertEqual(out["state"]["no_progress_count"], 0)

        # the live current prompt now carries the merged edit
        self.assertEqual(_read(self.current), "Rule A. Rule B refined. Rule C.")

        # ---- 5) SUB_KEEP turn -- the F-04 net --------------------------------
        # Remove a rule. apply (kind=subtraction) re-runs the full verify gate.
        rc, out, err = _run("apply_change.py", {
            "op": "apply", "current_file": self.current,
            "before": " Rule C.", "after": "", "candidate_file": self.candidate,
            "kind": "subtraction",
        })
        self.assertEqual(rc, 0, err)
        self.assertTrue(out["ok"])
        pruned_text = _read(self.candidate)
        self.assertEqual(pruned_text, "Rule A. Rule B refined.")

        # subtraction gate, provisional then confirmed (real)
        rc, out, err = _run("score_compare.py", {
            "train_b": 0.76, "train_a": 0.74, "held_b": 0.64, "held_a": 0.62,
            "eps_train": EPS_T, "eps_heldout": EPS_H, "mode": "subtraction",
        })
        self.assertEqual(out["decision"], "SUB_KEEP")
        self.assertTrue(out["confirm_required"])
        rc, out, err = _run("score_compare.py", {
            "train_b": 0.76, "train_a": 0.74, "held_b": 0.64, "held_a": 0.62,
            "eps_train": EPS_T, "eps_heldout": EPS_H, "mode": "subtraction",
            "train_a2": 0.75, "held_a2": 0.63, "train_b2": 0.76, "held_b2": 0.64,
        })
        self.assertEqual(out["decision"], "SUB_KEEP")
        self.assertTrue(out["confirmed"])

        # promote the kept removal (confirmed) -- this is the step the old
        # protocol omitted, which made pruning dead end-to-end (F-04).
        rc, out, err = self._promote(True)
        self.assertEqual(rc, 0, err)
        self.assertTrue(out["promoted"])
        _run("resume.py", {"op": "promote_done", "state_path": self.state,
                           "candidate_prompt_hash": _sha(pruned_text)})
        rc, out, err = _run("resume.py", {"op": "record_decision", "state_path": self.state,
                                          "turn": 2, "decision": "SUB_KEEP"})
        self.assertEqual(rc, 0, err)
        self.assertEqual(out["state"]["turn"], 3)
        self.assertEqual(out["state"]["no_progress_count"], 0)

        # THE assertion that would have caught F-04: the pruned prompt is LIVE.
        self.assertEqual(_read(self.current), "Rule A. Rule B refined.")

    def test_promote_refuses_without_confirm_end_to_end(self):
        # F-01 net through the CLI: a staged candidate cannot be promoted without
        # the confirm flag, and the live current is left untouched.
        _write(self.current, "alpha beta gamma")
        _run("apply_change.py", {
            "op": "apply", "current_file": self.current,
            "before": "beta", "after": "BETA", "candidate_file": self.candidate,
        })
        rc, out, err = self._promote(False)
        self.assertEqual(rc, 1)
        self.assertFalse(out["ok"])
        self.assertEqual(_read(self.current), "alpha beta gamma")  # untouched

    def test_missing_id_is_clean_error_not_crash(self):
        # F-03 net through the CLI: op=state flags it, op=split errors cleanly --
        # neither emits an empty body + traceback.
        gs = _golden_cases()
        del gs["cases"][0]["id"]

        rc, out, err = _run("split_goldenset.py", {"op": "state", "golden_set": gs})
        self.assertEqual(out["state"], "malformed", err)

        rc, out, err = _run("split_goldenset.py", {"op": "split", "golden_set": gs})
        self.assertEqual(rc, 1)
        self.assertFalse(out["ok"])           # structured error, not None
        self.assertIn("id", out["reason"])
        self.assertEqual(err, "")              # no traceback on stderr


if __name__ == "__main__":
    unittest.main()
