"""Tests for split_goldenset.py -- S5 split + size gate + freeze/verify."""

import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from split_goldenset import (  # noqa: E402
    split_goldenset,
    verify_split_hash,
    compute_split_hash,
    goldenset_state,
)


def _case(cid, realistic, status="active", split=None, input_text=None):
    c = {
        "id": cid,
        "realistic": realistic,
        "status": status,
        "input": input_text if input_text is not None else "input for {}".format(cid),
        "rubric": ["did it do {}?".format(cid)],
    }
    if split is not None:
        c["split"] = split
    return c


def _golden(cases, min_train=5, min_heldout=3):
    return {
        "target": "./t.md",
        "version": "v1",
        "min_size": {"train": min_train, "heldout": min_heldout},
        "cases": cases,
    }


class TestSplitAssignment(unittest.TestCase):
    def test_realistic_items_go_heldout_first(self):
        # 5 non-realistic + 3 realistic, no preassigned splits.
        cases = [_case("n{}".format(i), realistic=False) for i in range(5)]
        cases += [_case("r{}".format(i), realistic=True) for i in range(3)]
        res = split_goldenset(_golden(cases))
        self.assertTrue(res["ok"])
        # All realistic ones land in held-out (reality-first).
        for i in range(3):
            self.assertEqual(res["assignments"]["r{}".format(i)], "heldout")
        for i in range(5):
            self.assertEqual(res["assignments"]["n{}".format(i)], "train")
        self.assertEqual(res["counts"]["train"], 5)
        self.assertEqual(res["counts"]["heldout"], 3)

    def test_existing_splits_respected_without_reassign(self):
        cases = [_case("t{}".format(i), realistic=False, split="train") for i in range(5)]
        cases += [_case("h{}".format(i), realistic=True, split="heldout") for i in range(3)]
        res = split_goldenset(_golden(cases))
        self.assertEqual(res["counts"]["train"], 5)
        self.assertEqual(res["counts"]["heldout"], 3)


class TestSizeGate(unittest.TestCase):
    def test_train_too_small_errors(self):
        # 4 train + 3 heldout -> train < 5 -> error
        cases = [_case("n{}".format(i), realistic=False) for i in range(4)]
        cases += [_case("r{}".format(i), realistic=True) for i in range(3)]
        with self.assertRaises(ValueError) as ctx:
            split_goldenset(_golden(cases))
        self.assertIn("size gate", str(ctx.exception))

    def test_heldout_too_small_errors(self):
        # 6 train, only 2 realistic for heldout -> heldout < 3 -> error
        cases = [_case("n{}".format(i), realistic=False) for i in range(6)]
        cases += [_case("r{}".format(i), realistic=True) for i in range(2)]
        with self.assertRaises(ValueError):
            split_goldenset(_golden(cases))

    def test_retired_cases_excluded_from_counts(self):
        # 5 active train + 3 active heldout + 2 retired -> still passes; retired
        # are not counted and not hashed.
        cases = [_case("n{}".format(i), realistic=False) for i in range(5)]
        cases += [_case("r{}".format(i), realistic=True) for i in range(3)]
        cases += [_case("dead{}".format(i), realistic=False, status="retired") for i in range(2)]
        res = split_goldenset(_golden(cases))
        self.assertTrue(res["ok"])
        self.assertEqual(res["counts"]["retired"], 2)
        self.assertNotIn("dead0", res["assignments"])


class TestFreezeAndVerify(unittest.TestCase):
    def setUp(self):
        cases = [_case("n{}".format(i), realistic=False) for i in range(5)]
        cases += [_case("r{}".format(i), realistic=True) for i in range(3)]
        self.frozen = split_goldenset(_golden(cases))["golden_set"]

    def test_verify_passes_on_unchanged(self):
        res = verify_split_hash(self.frozen)
        self.assertTrue(res["valid"], res)

    def test_verify_detects_input_mutation(self):
        mutated = copy.deepcopy(self.frozen)
        # change an active case's input text mid-run -> hash must flip
        mutated["cases"][0]["input"] = "TAMPERED input"
        res = verify_split_hash(mutated)
        self.assertFalse(res["valid"])
        self.assertIn("mutated", res["reason"])

    def test_verify_detects_split_mutation(self):
        mutated = copy.deepcopy(self.frozen)
        # flip a case's split -> hash must flip
        first_id = mutated["cases"][0]["id"]
        mutated["cases"][0]["split"] = "heldout" if mutated["cases"][0]["split"] == "train" else "train"
        res = verify_split_hash(mutated)
        self.assertFalse(res["valid"], "mutating split of {} should break hash".format(first_id))

    def test_verify_detects_rubric_mutation(self):
        mutated = copy.deepcopy(self.frozen)
        mutated["cases"][0]["rubric"].append("sneaky new criterion")
        res = verify_split_hash(mutated)
        self.assertFalse(res["valid"])

    def test_retiring_a_case_does_not_break_hash_of_actives(self):
        # Hash is over ACTIVE cases only; the hash value naturally differs if the
        # set of active cases changes, but verify against a freshly frozen set
        # with the same actives must still match. Here we confirm that adding a
        # brand-new RETIRED case to the frozen set does NOT change the stored hash
        # comparison (retired cases are excluded from the computed hash).
        mutated = copy.deepcopy(self.frozen)
        mutated["cases"].append(_case("dead-new", realistic=False, status="retired"))
        res = verify_split_hash(mutated)
        self.assertTrue(res["valid"], "adding a retired case must not break the freeze")

    def test_hash_is_order_independent(self):
        reordered = copy.deepcopy(self.frozen)
        reordered["cases"].reverse()
        self.assertEqual(
            compute_split_hash(self.frozen),
            compute_split_hash(reordered),
        )

    def test_missing_stored_hash_is_invalid(self):
        no_hash = copy.deepcopy(self.frozen)
        del no_hash["split_hash"]
        res = verify_split_hash(no_hash)
        self.assertFalse(res["valid"])
        self.assertIn("no stored split_hash", res["reason"])


class TestRubricGate(unittest.TestCase):
    """S5 moat guard: a frozen rubric-less active case neuters the eval."""

    def _set(self):
        cases = [_case("n{}".format(i), realistic=False) for i in range(5)]
        cases += [_case("r{}".format(i), realistic=True) for i in range(3)]
        return cases

    def test_empty_rubric_active_case_errors_by_default(self):
        cases = self._set()
        cases[0]["rubric"] = []
        with self.assertRaises(ValueError) as ctx:
            split_goldenset(_golden(cases))
        self.assertIn("empty rubric", str(ctx.exception))

    def test_missing_rubric_active_case_errors(self):
        cases = self._set()
        del cases[1]["rubric"]
        with self.assertRaises(ValueError):
            split_goldenset(_golden(cases))

    def test_retired_empty_rubric_is_exempt(self):
        cases = self._set()
        dead = _case("dead", realistic=False, status="retired")
        dead["rubric"] = []
        cases.append(dead)
        res = split_goldenset(_golden(cases))  # must NOT raise
        self.assertTrue(res["ok"])

    def test_require_rubric_false_allows_empty(self):
        cases = self._set()
        cases[0]["rubric"] = []
        res = split_goldenset(_golden(cases), require_rubric=False)
        self.assertTrue(res["ok"])


class TestIdValidation(unittest.TestCase):
    """F-03: a missing/blank id must become a clean error, never a KeyError
    traceback -- and op=state must flag it as 'malformed', not route to split."""

    def _set(self):
        cases = [_case("n{}".format(i), realistic=False) for i in range(5)]
        cases += [_case("r{}".format(i), realistic=True) for i in range(3)]
        return cases

    def test_split_raises_on_missing_id(self):
        cases = self._set()
        del cases[0]["id"]
        with self.assertRaises(ValueError) as ctx:
            split_goldenset(_golden(cases))
        self.assertIn("id", str(ctx.exception))

    def test_split_raises_on_blank_id(self):
        cases = self._set()
        cases[2]["id"] = "   "
        with self.assertRaises(ValueError):
            split_goldenset(_golden(cases))

    def test_split_raises_on_non_string_id(self):
        cases = self._set()
        cases[1]["id"] = 123
        with self.assertRaises(ValueError):
            split_goldenset(_golden(cases))

    def test_retired_case_without_id_is_exempt(self):
        cases = self._set()
        dead = _case("dead", realistic=False, status="retired")
        del dead["id"]
        cases.append(dead)
        res = split_goldenset(_golden(cases))  # must NOT raise
        self.assertTrue(res["ok"])

    def test_state_malformed_on_missing_id(self):
        cases = self._set()
        del cases[0]["id"]
        res = goldenset_state({"golden_set": _golden(cases)})
        self.assertEqual(res["state"], "malformed")
        self.assertFalse(res["ready_to_run"])

    def test_split_raises_on_duplicate_id(self):
        # F-05: two active cases sharing an id collapse in the assignment map, so
        # the size gate undercounts. Reject up front.
        cases = self._set()
        cases[1]["id"] = cases[0]["id"]  # duplicate active id
        with self.assertRaises(ValueError) as ctx:
            split_goldenset(_golden(cases))
        self.assertIn("duplicate", str(ctx.exception).lower())

    def test_state_malformed_on_duplicate_id(self):
        cases = self._set()
        cases[1]["id"] = cases[0]["id"]
        res = goldenset_state({"golden_set": _golden(cases)})
        self.assertEqual(res["state"], "malformed")

    def test_duplicate_id_on_retired_case_is_exempt(self):
        # A retired case may reuse an id (it's excluded from split + hash).
        cases = self._set()
        dead = _case(cases[0]["id"], realistic=False, status="retired")
        cases.append(dead)
        res = split_goldenset(_golden(cases))  # must NOT raise
        self.assertTrue(res["ok"])


class TestStatusValidation(unittest.TestCase):
    """GAP-5: status is parsed case-insensitively; an unrecognized value is flagged
    rather than silently treated as active (and frozen + scored)."""

    def _set(self):
        cases = [_case("n{}".format(i), realistic=False) for i in range(5)]
        cases += [_case("r{}".format(i), realistic=True) for i in range(3)]
        return cases

    def test_capitalized_retired_is_excluded(self):
        cases = self._set()
        cases.append(_case("dead", realistic=False, status="Retired"))  # capital typo
        res = split_goldenset(_golden(cases))
        self.assertTrue(res["ok"])
        self.assertNotIn("dead", res["assignments"])   # actually retired, not active
        self.assertEqual(res["counts"]["retired"], 1)

    def test_unknown_status_raises_in_split(self):
        cases = self._set()
        cases[0]["status"] = "inactive"  # not a known status
        with self.assertRaises(ValueError) as ctx:
            split_goldenset(_golden(cases))
        self.assertIn("status", str(ctx.exception).lower())

    def test_state_malformed_on_unknown_status(self):
        cases = self._set()
        cases[0]["status"] = "archived"
        res = goldenset_state({"golden_set": _golden(cases)})
        self.assertEqual(res["state"], "malformed")


class TestInputFileResolution(unittest.TestCase):
    def test_resolves_input_file_relative_to_base_dir(self):
        import tempfile
        d = tempfile.mkdtemp()
        cases_dir = os.path.join(d, "cases")
        os.makedirs(cases_dir)
        with open(os.path.join(cases_dir, "c1.input.txt"), "w", encoding="utf-8") as fh:
            fh.write("file-backed input content")
        cases = [_case("n{}".format(i), realistic=False) for i in range(5)]
        cases += [_case("r{}".format(i), realistic=True) for i in range(2)]
        # one file-backed realistic case
        fc = {
            "id": "rfile", "realistic": True, "status": "active",
            "input_file": "./cases/c1.input.txt", "rubric": ["ok?"],
        }
        cases.append(fc)
        res = split_goldenset(_golden(cases), base_dir=d)
        self.assertTrue(res["ok"])
        # the file content participates in the hash (mutating the file flips it)
        h1 = res["split_hash"]
        with open(os.path.join(cases_dir, "c1.input.txt"), "w", encoding="utf-8") as fh:
            fh.write("DIFFERENT content")
        h2 = compute_split_hash(res["golden_set"], base_dir=d)
        self.assertNotEqual(h1, h2)
        import shutil
        shutil.rmtree(d, ignore_errors=True)


class TestStateClassification(unittest.TestCase):
    """op=state: PURE-READ signpost for deterministic cold-start entry (B3b)."""

    def _actives(self):
        cases = [_case("n{}".format(i), realistic=False) for i in range(5)]
        cases += [_case("r{}".format(i), realistic=True) for i in range(3)]
        return cases

    def test_missing_when_path_absent(self):
        res = goldenset_state({"golden_set_path": "/no/such/dir/golden-set.json"})
        self.assertTrue(res["ok"])
        self.assertEqual(res["state"], "missing")
        self.assertFalse(res["ready_to_run"])

    def test_malformed_when_no_cases_array(self):
        res = goldenset_state({"golden_set": {"target": "./t.md"}})
        self.assertEqual(res["state"], "malformed")
        self.assertFalse(res["ready_to_run"])

    def test_empty_when_no_active_cases(self):
        dead = [_case("dead{}".format(i), realistic=False, status="retired") for i in range(3)]
        res = goldenset_state({"golden_set": _golden(dead)})
        self.assertEqual(res["state"], "empty")
        self.assertEqual(res["counts"]["active"], 0)
        self.assertEqual(res["counts"]["retired"], 3)

    def test_unfrozen_when_no_stored_hash(self):
        res = goldenset_state({"golden_set": _golden(self._actives())})
        self.assertEqual(res["state"], "unfrozen")
        self.assertFalse(res["ready_to_run"])
        self.assertEqual(res["counts"]["active"], 8)

    def test_ready_on_frozen_set(self):
        frozen = split_goldenset(_golden(self._actives()))["golden_set"]
        res = goldenset_state({"golden_set": frozen})
        self.assertEqual(res["state"], "ready")
        self.assertTrue(res["ready_to_run"])

    def test_mutated_after_freeze(self):
        frozen = split_goldenset(_golden(self._actives()))["golden_set"]
        mutated = copy.deepcopy(frozen)
        mutated["cases"][0]["input"] = "TAMPERED input"
        res = goldenset_state({"golden_set": mutated})
        self.assertEqual(res["state"], "mutated")
        self.assertIn("expected", res)
        self.assertIn("actual", res)

    def test_malformed_on_broken_input_file(self):
        frozen = split_goldenset(_golden(self._actives()))["golden_set"]
        broken = copy.deepcopy(frozen)
        broken["cases"][0].pop("input", None)
        broken["cases"][0]["input_file"] = "./does-not-exist.txt"
        res = goldenset_state({"golden_set": broken, "base_dir": "/tmp"})
        self.assertEqual(res["state"], "malformed")

    def test_state_is_pure_read_no_mutation(self):
        gs = _golden(self._actives())
        snapshot = copy.deepcopy(gs)
        goldenset_state({"golden_set": gs})
        self.assertEqual(gs, snapshot, "op=state must not mutate the golden set")
        self.assertNotIn("split_hash", gs)

    def test_unknown_when_path_not_a_string(self):
        # Totality: a bad payload TYPE is a structured ok:False, never a crash.
        res = goldenset_state({"golden_set_path": 123})
        self.assertFalse(res["ok"])
        self.assertEqual(res["state"], "unknown")

    def test_unknown_when_base_dir_not_a_string(self):
        res = goldenset_state({"golden_set": _golden(self._actives()), "base_dir": 5})
        self.assertFalse(res["ok"])
        self.assertEqual(res["state"], "unknown")

    def test_malformed_when_case_not_an_object(self):
        res = goldenset_state({"golden_set": {"cases": ["not-a-dict", {"id": "x"}]}})
        self.assertEqual(res["state"], "malformed")

    def test_unassigned_counted_on_degenerate_frozen_set(self):
        # Freeze-consistent but with a bogus split label: still "ready", yet
        # counts.unassigned exposes the degeneracy without changing the verdict.
        frozen = split_goldenset(_golden(self._actives()))["golden_set"]
        bogus = copy.deepcopy(frozen)
        bogus["cases"][0]["split"] = "BOGUS"
        bogus["split_hash"] = compute_split_hash(bogus)
        res = goldenset_state({"golden_set": bogus})
        self.assertEqual(res["state"], "ready")
        self.assertGreaterEqual(res["counts"]["unassigned"], 1)

    def test_malformed_on_non_string_input_file(self):
        # Totality: a non-string input_file on a frozen set makes compute_split_hash
        # raise TypeError, which is caught -> malformed (a structured state, no crash).
        frozen = split_goldenset(_golden(self._actives()))["golden_set"]
        broken = copy.deepcopy(frozen)
        broken["cases"][0].pop("input", None)
        broken["cases"][0]["input_file"] = 123
        res = goldenset_state({"golden_set": broken})
        self.assertEqual(res["state"], "malformed")


if __name__ == "__main__":
    unittest.main()
