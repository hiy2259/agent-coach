"""Unit tests for emit_draft.py — every gate invariant, no disk unless needed.

These tests are the machine form of the plan's HOW-#3 invariant list: if any of
them fails, the emitted draft could disarm agent-coach's delegated gate (the
whole point of the skill), so none of these is cosmetic.
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import emit_draft as ed  # noqa: E402


def _limitations(n=10):
    return "\n".join("{}. limitation item {}".format(i, i) for i in range(1, n + 1))


def _payload(output_dir, **over):
    p = {
        "output_dir": output_dir,
        "target": "./toy/summarizer.md",
        "case_language": "ko",
        "created": "2026-07-02",
        "train_cases": [
            {"id": "t1", "input": "회의록 A", "rubric": ["c1?", "c2?", "c3?", "c4?", "c5?"],
             "verified_failing": True, "notes": "hallucination probe"},
            {"id": "t2", "input": "회의록 B", "rubric": ["c1?", "c2?", "c3?", "c4?", "c5?"],
             "verified_failing": True},
            {"id": "t3", "input": "회의록 C", "rubric": ["c1?", "c2?", "c3?", "c4?", "c5?"]},
            {"id": "t4", "input": "회의록 D", "rubric": ["c1?", "c2?", "c3?", "c4?", "c5?"]},
            {"id": "t5", "input_file_content": "긴 회의록 원문 ...",
             "rubric": ["c1?", "c2?", "c3?", "c4?", "c5?"]},
        ],
        "heldout_cases": [
            {"id": "h1", "input": "실사용 메시지 1", "probe_dimension": "ambiguous-owner"},
            {"id": "h2", "input": "실사용 메시지 2", "probe_dimension": "conflicting-dates"},
            {"id": "h3", "input_file_content": "실사용 대형 입력 ...", "probe_dimension": "long-context"},
        ],
        "ruler": {"model": "claude-opus-4-8", "temperature_configured": 0.7},
        "council": {"rounds": 2, "objections_total": 4, "unresolved": [], "accepted_risks": []},
        "runbook": {
            "title": "골든셋 초안 안내",
            "intro": "이것은 초안입니다.",
            "next_steps": "held-out 채점표를 직접 작성하세요.",
            "limitations": _limitations(),
        },
    }
    p.update(over)
    return p


class BuildInvariants(unittest.TestCase):
    """build_draft-level checks (no IO)."""

    def _build(self, **over):
        return ed.build_draft(_payload("unused-dir", **over))

    def test_unfrozen_no_split_hash(self):
        gs, _, _, _, _ = self._build()
        self.assertNotIn("split_hash", gs)

    def test_heldout_rubrics_all_empty_and_split_pinned(self):
        gs, _, _, _, _ = self._build()
        heldout = [c for c in gs["cases"] if c["split"] == "heldout"]
        self.assertEqual(len(heldout), 3)
        for c in heldout:
            self.assertEqual(c["rubric"], [])
            self.assertEqual(c["split"], "heldout")
            self.assertTrue(c["realistic"])

    def test_heldout_with_rubric_rejected_s52(self):
        bad = _payload("d")
        bad["heldout_cases"][0]["rubric"] = ["sneaky criterion?"]
        with self.assertRaises(ValueError) as ctx:
            ed.build_draft(bad)
        self.assertIn("S5-2", str(ctx.exception))

    def test_heldout_empty_rubric_key_tolerated(self):
        ok = _payload("d")
        ok["heldout_cases"][0]["rubric"] = []
        gs, _, _, _, _ = ed.build_draft(ok)
        self.assertEqual([c for c in gs["cases"] if c["id"] == "h1"][0]["rubric"], [])

    def test_train_below_floor_rejected(self):
        bad = _payload("d")
        bad["train_cases"] = bad["train_cases"][:4]
        with self.assertRaises(ValueError):
            ed.build_draft(bad)

    def test_heldout_below_floor_rejected(self):
        bad = _payload("d")
        bad["heldout_cases"] = bad["heldout_cases"][:2]
        with self.assertRaises(ValueError):
            ed.build_draft(bad)

    def test_empty_train_rubric_rejected(self):
        bad = _payload("d")
        bad["train_cases"][2]["rubric"] = []
        with self.assertRaises(ValueError):
            ed.build_draft(bad)

    def test_rubric_size_guidance_warns_not_blocks(self):
        p = _payload("d")
        p["train_cases"][0]["rubric"] = ["only?", "four?", "criteria?", "here?"]
        gs, _, _, _, warnings = ed.build_draft(p)
        self.assertTrue(any("4 criteria" in w for w in warnings))
        self.assertEqual(len([c for c in gs["cases"] if c["id"] == "t1"][0]["rubric"]), 4)

    def test_provenance_bootstrap_and_origin_tags(self):
        gs, _, _, _, _ = self._build()
        for c in gs["cases"]:
            self.assertEqual(c["provenance"], "bootstrap")
            self.assertEqual(c["added_in_version"], "v1")
            if c["split"] == "train":
                self.assertIn("ai-input", c["tags"])
                self.assertIn("ai-rubric", c["tags"])
            else:
                self.assertIn("ai-input", c["tags"])
                self.assertIn("human-rubric", c["tags"])

    def test_input_xor_file_both_rejected(self):
        bad = _payload("d")
        bad["train_cases"][0]["input_file_content"] = "also a file"
        with self.assertRaises(ValueError):
            ed.build_draft(bad)

    def test_input_xor_file_neither_rejected(self):
        bad = _payload("d")
        del bad["train_cases"][0]["input"]
        with self.assertRaises(ValueError):
            ed.build_draft(bad)

    def test_duplicate_ids_rejected(self):
        bad = _payload("d")
        bad["heldout_cases"][0]["id"] = "t1"
        with self.assertRaises(ValueError):
            ed.build_draft(bad)

    def test_unsafe_id_rejected(self):
        bad = _payload("d")
        bad["train_cases"][0]["id"] = "../evil"
        with self.assertRaises(ValueError):
            ed.build_draft(bad)

    def test_topup_and_verified_failing_contradiction_rejected(self):
        bad = _payload("d")
        bad["train_cases"][0]["top_up"] = True  # t1 is verified_failing
        with self.assertRaises(ValueError):
            ed.build_draft(bad)

    def test_topup_warning_and_tag(self):
        p = _payload("d")
        p["train_cases"][2]["top_up"] = True
        gs, _, runlog, _, warnings = ed.build_draft(p)
        self.assertIn("t3", runlog["expose"]["top_up"])
        self.assertIn("top-up", [c for c in gs["cases"] if c["id"] == "t3"][0]["tags"])
        self.assertTrue(any("top-up" in w or "near ceiling" in w for w in warnings))

    def test_no_expose_evidence_warns(self):
        p = _payload("d")
        for c in p["train_cases"]:
            c.pop("verified_failing", None)
        _, _, _, _, warnings = ed.build_draft(p)
        self.assertTrue(any("verified_failing" in w for w in warnings))

    def test_limitations_fewer_than_10_rejected(self):
        bad = _payload("d")
        bad["runbook"]["limitations"] = _limitations(9)
        with self.assertRaises(ValueError) as ctx:
            ed.build_draft(bad)
        self.assertIn("limitations", str(ctx.exception))

    def test_ruler_model_required(self):
        bad = _payload("d")
        bad["ruler"] = {"temperature_configured": 0.7}
        with self.assertRaises(ValueError):
            ed.build_draft(bad)

    def test_runlog_ruler_disclosure_and_no_heldout_runs(self):
        _, _, runlog, _, _ = self._build()
        self.assertEqual(runlog["ruler"]["temperature_pinning"],
                         "prose-only (harness limitation, both sides)")
        self.assertEqual(runlog["expose"]["heldout_runs"], 0)

    def test_baseline_excluded_tagging(self):
        p = _payload("d", excluded_case_ids={"t4": "needs web access"})
        gs, _, runlog, _, _ = ed.build_draft(p)
        self.assertIn("baseline-excluded", [c for c in gs["cases"] if c["id"] == "t4"][0]["tags"])
        self.assertEqual(runlog["expose"]["baseline_excluded"], {"t4": "needs web access"})

    def test_runbook_contains_heldout_ids_and_split_cmd(self):
        _, _, _, runbook_md, _ = self._build()
        for hid in ("h1", "h2", "h3"):
            self.assertIn("`{}`".format(hid), runbook_md)
        self.assertIn('"op":"split"', runbook_md)
        self.assertIn("UNFROZEN", runbook_md)


class EmitIO(unittest.TestCase):
    """emit_draft-level checks (real files in a tempdir)."""

    def test_happy_path_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "golden-set")
            result = ed.emit_draft(_payload(out))
            self.assertTrue(result["ok"])
            gs_path = os.path.join(out, "golden-set.json")
            self.assertTrue(os.path.isfile(gs_path))
            self.assertTrue(os.path.isfile(os.path.join(out, "GOLDEN-SET-DRAFT-README.md")))
            self.assertTrue(os.path.isfile(os.path.join(out, "GOLDEN-SET-DRAFT-RUNLOG.json")))
            # input_file cases resolve relative to the golden-set dir
            self.assertTrue(os.path.isfile(os.path.join(out, "cases", "t5.input.txt")))
            self.assertTrue(os.path.isfile(os.path.join(out, "cases", "h3.input.txt")))
            with open(gs_path, encoding="utf-8") as fh:
                gs = json.load(fh)
            self.assertNotIn("split_hash", gs)
            self.assertEqual(result["counts"], {"train": 5, "heldout": 3})

    def test_no_require_rubric_key_in_emitted_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "gs")
            ed.emit_draft(_payload(out))
            for name in ("golden-set.json", "GOLDEN-SET-DRAFT-RUNLOG.json"):
                with open(os.path.join(out, name), encoding="utf-8") as fh:
                    self.assertNotIn('"require_rubric"', fh.read(),
                                     "{} must never carry the gate-disabling key".format(name))

    def test_cli_totality_on_bad_payload(self):
        # run_cli must convert invariant violations into {ok:false}, exit 1
        import io
        bad = _payload("x")
        bad["heldout_cases"][0]["rubric"] = ["sneaky?"]
        old_stdin, old_stdout = sys.stdin, sys.stdout
        sys.stdin = io.StringIO(json.dumps(bad))
        sys.stdout = io.StringIO()
        try:
            rc = ed.run_cli(["emit_draft.py"])
            out = sys.stdout.getvalue()
        finally:
            sys.stdin, sys.stdout = old_stdin, old_stdout
        self.assertEqual(rc, 1)
        parsed = json.loads(out)
        self.assertFalse(parsed["ok"])
        self.assertIn("S5-2", parsed["reason"])


if __name__ == "__main__":
    unittest.main()
