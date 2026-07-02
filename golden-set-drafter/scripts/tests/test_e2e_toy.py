"""Plan Verification 3 (e2e, assertable core): toy target + stub run-config.

Covers what the implementation plan's e2e bullet demands deterministically:
  - RUNLOG ruler record shows the pinned model MATCHING the stub run-config's
    ``runner.model`` plus the temperature-pinning disclosure,
  - the <5-failing TOP-UP path (strong-target fixture): top_up recorded and
    >= 5 train still emitted,
  - sim-human fills all held-out rubrics -> freeze -> op=state "ready".

The council/expose stages are model work and are exercised by the skill's
eval prompts (evals/evals.json), not by python.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS_DIR = os.path.dirname(_TESTS_DIR)
_REPO_DIR = os.path.dirname(os.path.dirname(_SCRIPTS_DIR))
_SPLIT_SCRIPT = os.path.join(_REPO_DIR, "agent-coach", "scripts", "split_goldenset.py")

sys.path.insert(0, _SCRIPTS_DIR)
import emit_draft as ed  # noqa: E402


def _limitations():
    return "\n".join("{}. limitation {}".format(i, i) for i in range(1, 11))


@unittest.skipUnless(os.path.isfile(_SPLIT_SCRIPT),
                     "agent-coach must be co-located; expected " + _SPLIT_SCRIPT)
class E2EToyTarget(unittest.TestCase):

    def test_strong_target_topup_to_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            # stub run-config: the production ruler the skill must mirror
            run_config = {
                "runner": {"model": "claude-opus-4-8", "temperature": 1.0,
                           "max_output_tokens": 2000},
                "grader": {"model": "claude-sonnet-5", "temperature": 0,
                           "version_id": "2026-07-02"},
                "proposer": {"model": "claude-sonnet-5", "temperature": 0.3},
                "tools": {"mode": "none"},
            }
            rc_path = os.path.join(tmp, "run-config.json")
            with open(rc_path, "w", encoding="utf-8") as fh:
                json.dump(run_config, fh)

            # strong-target fixture: only 2 of 5 train candidates actually
            # failed the expose pass -> 3 top-ups keep the floor at 5
            out_dir = os.path.join(tmp, "golden-set")
            rubric = ["c1?", "c2?", "c3?", "c4?", "c5?"]
            payload = {
                "output_dir": out_dir,
                "target": "./toy/summarizer.md",
                "case_language": "ko",
                "created": "2026-07-02",
                "train_cases": [
                    {"id": "t1", "input": "in-1", "rubric": rubric, "verified_failing": True},
                    {"id": "t2", "input": "in-2", "rubric": rubric, "verified_failing": True},
                    {"id": "t3", "input": "in-3", "rubric": rubric, "top_up": True},
                    {"id": "t4", "input": "in-4", "rubric": rubric, "top_up": True},
                    {"id": "t5", "input": "in-5", "rubric": rubric, "top_up": True},
                ],
                "heldout_cases": [
                    {"id": "h1", "input": "real-1", "probe_dimension": "d1"},
                    {"id": "h2", "input": "real-2", "probe_dimension": "d2"},
                    {"id": "h3", "input": "real-3", "probe_dimension": "d3"},
                ],
                "ruler": {"model": run_config["runner"]["model"],
                           "temperature_configured": run_config["runner"]["temperature"]},
                "runbook": {"title": "골든셋 초안", "intro": "초안입니다.",
                             "next_steps": "held-out 채점표를 직접 작성하세요.",
                             "limitations": _limitations()},
            }
            result = ed.emit_draft(payload)
            self.assertTrue(result["ok"])
            self.assertEqual(result["counts"]["train"], 5,
                             "top-up must keep the floor at 5, never fewer")

            # RUNLOG ruler record matches the stub run-config + disclosure
            with open(os.path.join(out_dir, "GOLDEN-SET-DRAFT-RUNLOG.json"),
                      encoding="utf-8") as fh:
                runlog = json.load(fh)
            self.assertEqual(runlog["ruler"]["model"], run_config["runner"]["model"])
            self.assertEqual(runlog["ruler"]["temperature_configured"],
                             run_config["runner"]["temperature"])
            self.assertEqual(runlog["ruler"]["temperature_pinning"],
                             "prose-only (harness limitation, both sides)")
            self.assertEqual(sorted(runlog["expose"]["top_up"]), ["t3", "t4", "t5"])
            self.assertTrue(any("near ceiling" in w or "top-up" in w
                                for w in runlog["warnings"]),
                            "near-ceiling warning must be recorded for top-ups")

            # sim-human: fill all held-out rubrics -> freeze -> ready
            gs_path = os.path.join(out_dir, "golden-set.json")
            with open(gs_path, encoding="utf-8") as fh:
                gs = json.load(fh)
            for case in gs["cases"]:
                if case["split"] == "heldout":
                    case["rubric"] = ["human criterion {}?".format(i) for i in range(1, 6)]
            with open(gs_path, "w", encoding="utf-8") as fh:
                json.dump(gs, fh, ensure_ascii=False, indent=2)

            def cli(payload_):
                proc = subprocess.run([sys.executable, _SPLIT_SCRIPT],
                                      input=json.dumps(payload_), capture_output=True,
                                      text=True, timeout=60)
                return proc.returncode, json.loads(proc.stdout)

            rc, out = cli({"op": "split", "golden_set_path": gs_path, "write": True})
            self.assertEqual(rc, 0, out)
            rc, state = cli({"op": "state", "golden_set_path": gs_path})
            self.assertEqual(state.get("state"), "ready", state)
            self.assertTrue(state.get("ready_to_run"))


if __name__ == "__main__":
    unittest.main()
