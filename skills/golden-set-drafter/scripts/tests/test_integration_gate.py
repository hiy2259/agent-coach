"""Integration proof of the delegated gate — against the REAL agent-coach code.

This is the load-bearing test of the whole skill: it round-trips an emitted
draft through agent-coach's actual ``split_goldenset.py`` and proves the
handoff story end to end:

    emit (unfrozen, empty held-out rubrics)
      -> op=state  == "unfrozen"                      (routing works)
      -> op=split  raises / {ok:false} on the ids     (the gate is armed)
      -> human fills ALL held-out rubrics
      -> op=split  freezes successfully               (input_file resolves,
                                                       pinned splits survive)
      -> op=state  == "ready"
      -> retiring held-out below the floor is blocked (no retirement dodge)

The ``input_file`` case matters specifically because agent-coach resolves file
inputs only inside ``compute_split_hash`` — i.e. at FREEZE time, after the
human has already invested rubric work. A draft with a bad relative path would
pass every schema check and fail at the worst possible moment; driving one
file-backed case to a successful freeze is the only proof the paths are right.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS_DIR = os.path.dirname(_TESTS_DIR)
_SKILL_DIR = os.path.dirname(_SCRIPTS_DIR)
_REPO_DIR = os.path.dirname(_SKILL_DIR)
_AGENT_COACH_SCRIPTS = os.path.join(_REPO_DIR, "agent-coach", "scripts")
_SPLIT_SCRIPT = os.path.join(_AGENT_COACH_SCRIPTS, "split_goldenset.py")

sys.path.insert(0, _SCRIPTS_DIR)
import emit_draft as ed  # noqa: E402


def _limitations():
    return "\n".join("{}. limitation {}".format(i, i) for i in range(1, 11))


def _payload(out_dir):
    return {
        "output_dir": out_dir,
        "target": "./toy/summarizer.md",
        "case_language": "ko",
        "created": "2026-07-02",
        "train_cases": [
            {"id": "t1", "input": "회의록 A 요약", "rubric": ["c1?", "c2?", "c3?", "c4?", "c5?"],
             "verified_failing": True},
            {"id": "t2", "input": "회의록 B 요약", "rubric": ["c1?", "c2?", "c3?", "c4?", "c5?"],
             "verified_failing": True},
            {"id": "t3", "input": "회의록 C 요약", "rubric": ["c1?", "c2?", "c3?", "c4?", "c5?"]},
            {"id": "t4", "input": "회의록 D 요약", "rubric": ["c1?", "c2?", "c3?", "c4?", "c5?"]},
            {"id": "t5-file", "input_file_content": "아주 긴 회의록 원문 (train)…",
             "rubric": ["c1?", "c2?", "c3?", "c4?", "c5?"]},
        ],
        "heldout_cases": [
            {"id": "h1", "input": "실사용 메시지 1", "probe_dimension": "ambiguous-owner"},
            {"id": "h2", "input": "실사용 메시지 2", "probe_dimension": "conflicting-dates"},
            {"id": "h3-file", "input_file_content": "실사용 대형 입력 (heldout)…",
             "probe_dimension": "long-context"},
        ],
        "ruler": {"model": "claude-opus-4-8", "temperature_configured": 0.7},
        "runbook": {
            "title": "골든셋 초안",
            "intro": "이것은 초안입니다.",
            "next_steps": "held-out 채점표를 직접 작성하세요.",
            "limitations": _limitations(),
        },
    }


def _cli(payload):
    """Run agent-coach's split_goldenset.py exactly as documented:
    printf '%s' '<json>' | python3 scripts/split_goldenset.py"""
    proc = subprocess.run(
        [sys.executable, _SPLIT_SCRIPT],
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True, text=True, timeout=60,
    )
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise AssertionError("split_goldenset.py emitted non-JSON stdout: {!r} (stderr: {!r})".format(
            proc.stdout, proc.stderr))
    return proc.returncode, out


@unittest.skipUnless(os.path.isfile(_SPLIT_SCRIPT),
                     "agent-coach must be co-located (declared compatibility dependency); "
                     "expected " + _SPLIT_SCRIPT)
class DelegatedGateRoundTrip(unittest.TestCase):

    def test_full_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = os.path.join(tmp, "golden-set")
            result = ed.emit_draft(_payload(out_dir))
            self.assertTrue(result["ok"])
            gs_path = os.path.join(out_dir, "golden-set.json")

            # (a) op=state routes the cold start to op=split — "unfrozen"
            rc, state = _cli({"op": "state", "golden_set_path": gs_path})
            self.assertEqual(state.get("state"), "unfrozen", state)
            self.assertFalse(state.get("ready_to_run"), state)
            self.assertEqual(rc, 0, "unfrozen is a routed state, not an error")
            self.assertIn("op=split", state.get("next", ""))

            # (b1) function level: the require_rubric raise names the held-out ids
            sys.path.insert(0, _AGENT_COACH_SCRIPTS)
            try:
                import split_goldenset as sg
                with open(gs_path, encoding="utf-8") as fh:
                    gs = json.load(fh)
                with self.assertRaises(ValueError) as ctx:
                    sg.split_goldenset(gs, base_dir=out_dir)
                msg = str(ctx.exception)
                for hid in ("h1", "h2", "h3-file"):
                    self.assertIn(hid, msg, "raise must name the empty-rubric held-out ids")
                self.assertIn("empty rubric", msg)
            finally:
                sys.path.remove(_AGENT_COACH_SCRIPTS)

            # (b2) CLI level: same wall as the orchestrator/human sees it
            rc, out = _cli({"op": "split", "golden_set_path": gs_path, "write": True})
            self.assertEqual(rc, 1)
            self.assertFalse(out.get("ok"), out)
            self.assertIn("empty rubric", out.get("reason", ""))

            # the failed split must not have frozen anything
            with open(gs_path, encoding="utf-8") as fh:
                self.assertNotIn("split_hash", json.load(fh))

            # (c) the human authors ALL held-out rubrics -> freeze succeeds
            with open(gs_path, encoding="utf-8") as fh:
                gs = json.load(fh)
            for case in gs["cases"]:
                if case["split"] == "heldout":
                    case["rubric"] = [
                        "Did it satisfy human criterion {} for {}?".format(i, case["id"])
                        for i in range(1, 6)
                    ]
            with open(gs_path, "w", encoding="utf-8") as fh:
                json.dump(gs, fh, ensure_ascii=False, indent=2)

            rc, out = _cli({"op": "split", "golden_set_path": gs_path, "write": True})
            self.assertEqual(rc, 0, out)
            self.assertTrue(out.get("ok"), out)

            with open(gs_path, encoding="utf-8") as fh:
                frozen = json.load(fh)
            # freeze succeeded => split_hash present AND every input_file
            # (train t5-file, heldout h3-file) resolved relative to the set dir
            self.assertTrue(frozen.get("split_hash"), "freeze must store split_hash")
            # pinned splits survived the freeze (split respected, not reassigned)
            for case in frozen["cases"]:
                if case["id"].startswith("h"):
                    self.assertEqual(case["split"], "heldout",
                                     "pinned heldout split must survive freeze")
                else:
                    self.assertEqual(case["split"], "train")

            # (d) op=state now reports ready
            rc, state = _cli({"op": "state", "golden_set_path": gs_path})
            self.assertEqual(state.get("state"), "ready", state)
            self.assertTrue(state.get("ready_to_run"), state)

            # (e) retirement dodge is blocked by the size gate
            frozen["cases"] = [
                dict(c, status="retired") if c["id"] == "h1" else c
                for c in frozen["cases"]
            ]
            with open(gs_path, "w", encoding="utf-8") as fh:
                json.dump(frozen, fh, ensure_ascii=False, indent=2)
            rc, out = _cli({"op": "split", "golden_set_path": gs_path, "write": False})
            self.assertEqual(rc, 1)
            self.assertFalse(out.get("ok"), out)
            reason = out.get("reason", "").lower()
            self.assertTrue("held" in reason or "heldout" in reason,
                            "size gate must name the held-out floor: " + reason)


class ShippedFilesS52Tripwire(unittest.TestCase):
    """Verification 4: no shipped artifact OFFERS to ghostwrite held-out rubrics.

    A grep can only catch known offer phrasings, not every possible one — this
    is a tripwire, not a proof (the structural proof is emit_draft's S5-2
    rejection, tested in test_emit_draft.py). Ban text ("never write held-out
    rubrics") is legitimate and must NOT trip this.
    """

    FORBIDDEN = [
        "shall i write the held-out",
        "i can write the held-out",
        "want me to write the held-out",
        "let me draft the held-out rubric",
        "i'll draft the held-out rubric",
        "write the held-out rubrics for you",
        "starting point for the held-out rubric",
        "채점표를 대신 작성",
        "채점표를 써드릴",
        "루브릭을 대신 작성",
    ]

    def test_no_offer_phrasing_in_shipped_files(self):
        offenders = []
        checker = os.path.abspath(__file__)
        for root, dirs, files in os.walk(_SKILL_DIR):
            dirs[:] = [d for d in dirs if d not in ("__pycache__", ".pytest_cache")]
            for name in files:
                if not name.endswith((".md", ".py", ".json")):
                    continue
                path = os.path.join(root, name)
                # The pattern registry has to live somewhere: the checker
                # excludes exactly itself (its FORBIDDEN list would self-match),
                # and nothing else.
                if os.path.abspath(path) == checker:
                    continue
                with open(path, encoding="utf-8", errors="replace") as fh:
                    text = fh.read().lower()
                for pat in self.FORBIDDEN:
                    if pat in text:
                        offenders.append((os.path.relpath(path, _SKILL_DIR), pat))
        self.assertEqual(offenders, [],
                         "S5-2 tripwire: shipped files must never offer rubric "
                         "ghostwriting: {}".format(offenders))


if __name__ == "__main__":
    unittest.main()
