"""Tests for verify_change.py -- S3 mechanical single-change verification."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from verify_change import verify_change  # noqa: E402


class TestUniqueness(unittest.TestCase):
    def test_unique_match_passes(self):
        target = "alpha beta gamma"
        res = verify_change(target, before="beta", after="BETA")
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["occurrences"], 1)

    def test_multi_match_rejected(self):
        # "foo" appears twice -> ambiguous anchor -> reject (mandated case).
        target = "foo bar foo baz"
        res = verify_change(target, before="foo", after="FOO")
        self.assertFalse(res["ok"])
        self.assertEqual(res["occurrences"], 2)
        self.assertIn("ambiguous", res["reason"])

    def test_zero_match_rejected(self):
        target = "alpha beta gamma"
        res = verify_change(target, before="delta", after="DELTA")
        self.assertFalse(res["ok"])
        self.assertEqual(res["occurrences"], 0)
        self.assertIn("not found", res["reason"])

    def test_empty_before_rejected(self):
        target = "alpha beta"
        res = verify_change(target, before="", after="x")
        self.assertFalse(res["ok"])
        self.assertEqual(res["occurrences"], 0)


class TestLocality(unittest.TestCase):
    def test_before_span_cap_enforced(self):
        # 201 word tokens in `before` exceeds the default 200 cap -> reject.
        big = " ".join("w{}".format(i) for i in range(201))
        target = "head " + big + " tail"
        res = verify_change(target, before=big, after="small")
        self.assertFalse(res["ok"])
        self.assertIn("locality cap", res["reason"])
        self.assertEqual(res["checks"]["before_tokens"], 201)

    def test_before_span_at_cap_ok(self):
        # Exactly 200 tokens is allowed (<=).
        words = " ".join("w{}".format(i) for i in range(200))
        target = "head " + words + " tail"
        res = verify_change(target, before=words, after=words + " x")
        # after-delta is tiny, span is exactly at cap -> passes
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["checks"]["before_tokens"], 200)

    def test_after_delta_cap_enforced(self):
        # Must exceed BOTH the ratio cap AND the absolute floor to be rejected.
        # before 10 chars; after adds 150 chars (ratio 15.0; abs 150 > 100).
        target = "prefix 0123456789 suffix"
        res = verify_change(target, before="0123456789", after="0123456789" + "Z" * 150)
        self.assertFalse(res["ok"])
        self.assertIn("not local", res["reason"])

    def test_after_delta_within_cap_ok(self):
        # before 10 chars, after 14 chars -> ratio 0.4 <= 0.5 -> ok.
        target = "prefix 0123456789 suffix"
        res = verify_change(target, before="0123456789", after="0123456789ABCD")
        self.assertTrue(res["ok"], res)

    def test_subtraction_to_empty_within_cap(self):
        # Removing a short rule: before non-trivial, after "" -> delta ratio 1.0.
        # Default cap 0.5 would reject a full deletion; callers raise the cap for
        # subtraction. Verify the override path works.
        target = "rule-A. rule-B. rule-C."
        res = verify_change(
            target, before="rule-B. ", after="", kind="subtraction",
            max_after_delta_ratio=1.0,
        )
        self.assertTrue(res["ok"], res)

    def test_custom_token_cap_override(self):
        target = "one two three four five"
        res = verify_change(target, before="two three four", after="X", max_before_tokens=2)
        self.assertFalse(res["ok"])
        self.assertEqual(res["checks"]["max_before_tokens"], 2)


class TestAbsoluteFloor(unittest.TestCase):
    """E: the absolute char floor rescues short targets but can't admit bundles."""

    def test_short_target_one_clause_passes_via_abs_floor(self):
        # A short scoped addition (<=60 chars, <=10 tokens) on a tiny anchor
        # passes via the absolute floor even though it blows the ratio.
        target = "Keep it to five sentences or fewer."
        before = "five sentences or fewer."
        after = "five sentences or fewer. Name each owner."
        res = verify_change(target, before=before, after=after)
        self.assertTrue(res["ok"], res)
        self.assertGreater(res["checks"]["after_delta_ratio"], 0.5)
        self.assertLessEqual(res["checks"]["after_added_tokens"], 10)

    def test_bundle_exceeding_abs_floor_rejected(self):
        # A multi-rule bundle (> 100 chars added) fails BOTH caps -> rejected, so
        # the absolute floor cannot become a back-door for bundling edits (S3).
        target = "Output only the JSON."
        before = "Output only the JSON."
        bundle = (" Rule1: always include a title. Rule2: never fabricate a salary."
                  " Rule3: prefer null over guessing. Rule4: keep all keys sorted.")
        res = verify_change(target, before=before, after=before + bundle)
        self.assertFalse(res["ok"], res)
        self.assertGreater(res["checks"]["after_abs_delta"], 100)

    def test_abs_floor_override_tightens(self):
        target = "prefix 0123456789 suffix"
        res = verify_change(
            target, before="0123456789", after="0123456789ABCDEFGHIJ",
            max_after_abs_delta=5,
        )
        self.assertFalse(res["ok"])

    def test_shrink_rewrite_rejected(self):
        # A shrink (after shorter) that blows the ratio must NOT pass via the abs
        # floor: the abs path is growth-only, so it can't relax a span rewrite.
        target = "head " + "A" * 60 + "B" * 60 + " tail"
        before = "A" * 60 + "B" * 60       # 120 chars, unique
        res = verify_change(target, before=before, after="C" * 30)  # ratio 0.75, shrink
        self.assertFalse(res["ok"], res)

    def test_enumeration_bundle_rejected(self):
        # Capital-led micro-rule pile: rejected by the TOKEN cap (not formatting).
        target = "Return JSON."
        res = verify_change(target, before="Return JSON.",
                            after="Return JSON. Sort keys. Omit nulls. No comments. Trim it.")
        self.assertFalse(res["ok"], res)
        self.assertGreater(res["checks"]["after_added_tokens"], 10)

    def test_lowercase_comma_pile_rejected(self):
        # The dodge that beat a punctuation heuristic: lowercase + commas, zero
        # capital sentence-starts. The token cap rejects it anyway (style-agnostic).
        target = "Be brief."
        res = verify_change(
            target, before="Be brief.",
            after="Be brief, also cite sources, never guess, omit nulls, sort keys, trim text",
        )
        self.assertFalse(res["ok"], res)

    def test_subtraction_swap_rejected(self):
        # A "subtraction" that REPLACES a rule with new shorter rules (net shrink)
        # is NOT a pure deletion -> it does not get the relaxed ratio -> rejected.
        target = "head " + "R" * 100 + " tail"
        res = verify_change(target, before="R" * 100,
                            after="Add a title. Skip nulls. Sort keys.", kind="subtraction")
        self.assertFalse(res["ok"], res)
        self.assertFalse(res["checks"]["is_removal"])

    def test_subtraction_partial_removal_passes(self):
        # A genuine excision (after's tokens are a subset of before's) gets the
        # relaxed ratio and passes.
        target = "rule-A. rule-B. rule-C."
        res = verify_change(target, before="rule-A. rule-B. rule-C.",
                            after="rule-A. rule-C.", kind="subtraction")
        self.assertTrue(res["ok"], res)
        self.assertTrue(res["checks"]["is_removal"])

    def test_subtraction_shrink_duplicate_dodge_rejected(self):
        # F-10: a "subtraction" that shrinks but DUPLICATES a surviving token is not
        # a genuine in-order excision (subsequence false), so it must NOT get the
        # relaxed ratio cap. The old set-subset check wrongly accepted this.
        target = "head alpha beta gamma delta epsilon zeta tail"
        before = "alpha beta gamma delta epsilon zeta"
        res = verify_change(target, before=before, after="alpha alpha", kind="subtraction")
        self.assertFalse(res["ok"], res)
        self.assertFalse(res["checks"]["is_removal"])

    def test_subtraction_reorder_is_not_a_removal(self):
        # A same-token REORDER labelled subtraction is not an excision: is_removal
        # must be False (it passes locality only because a reorder is zero-delta).
        target = "head prefer X over Y tail"
        res = verify_change(target, before="prefer X over Y",
                            after="prefer Y over X", kind="subtraction")
        self.assertFalse(res["checks"]["is_removal"])

    def test_compound_clause_via_wide_anchor_passes(self):
        # Faithful "anchor wide, add little": a compound clause too big for the
        # absolute floor passes the RATIO path on a wide unique anchor.
        before = ("You are a meeting-minutes summarizer. Given notes, write a short "
                  "summary so a teammate who missed it can catch up.")
        after = before + " If no decision was reached, say so; do not invent one."
        res = verify_change(before, before=before, after=after)
        self.assertTrue(res["ok"], res)
        self.assertLessEqual(res["checks"]["after_delta_ratio"], 0.5)

    def test_subtraction_long_removal_passes_with_defaults(self):
        # A >60-char rule removed via kind="subtraction" passes with DEFAULT caps
        # (no manual override) -- so verify and apply agree on subtraction turns.
        rule = "X" * 130
        target = "KEEP. " + rule + " END."
        res = verify_change(target, before=rule, after="", kind="subtraction")
        self.assertTrue(res["ok"], res)


class TestTargetResolution(unittest.TestCase):
    def test_reads_from_target_file(self):
        # Exercises the CLI-level file resolution via the module helper.
        import tempfile
        from verify_change import _resolve_target_text
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as fh:
            fh.write("hello unique world")
            path = fh.name
        try:
            text = _resolve_target_text({"target_file": path})
            self.assertEqual(text, "hello unique world")
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
