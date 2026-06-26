"""Tests for aggregate_scores.py -- F-24: per-case Scores -> per-split scalars."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aggregate_scores import aggregate_scores, _passed_total  # noqa: E402


class TestAggregate(unittest.TestCase):
    def test_basic_two_splits(self):
        res = aggregate_scores([
            {"case_id": "t1", "split": "train", "passed": 4, "total": 5},
            {"case_id": "t2", "split": "train", "passed": 3, "total": 5},
            {"case_id": "h1", "split": "heldout", "passed": 2, "total": 3},
        ])
        self.assertTrue(res["ok"])
        # train: (4+3)/(5+5) = 0.7 ; heldout: 2/3
        self.assertEqual(res["train_score"], 0.7)
        self.assertAlmostEqual(res["heldout_score"], 0.666667, places=6)
        self.assertEqual(res["per_split"]["train"]["n_cases"], 2)

    def test_sum_over_total_not_mean_of_rates(self):
        # A 10-criterion case must weigh more than a 1-criterion case. Mean-of-rates
        # would give (1.0 + 0.0)/2 = 0.5; Σpassed/Σtotal gives 10/11 ≈ 0.909.
        res = aggregate_scores([
            {"case_id": "big", "split": "train", "passed": 10, "total": 10},
            {"case_id": "small", "split": "train", "passed": 0, "total": 1},
        ])
        self.assertAlmostEqual(res["train_score"], 10 / 11, places=6)
        self.assertNotAlmostEqual(res["train_score"], 0.5, places=3)

    def test_derives_from_results_array(self):
        res = aggregate_scores([
            {"case_id": "c", "split": "train", "results": [
                {"criterion_index": 0, "passed": True},
                {"criterion_index": 1, "passed": False},
                {"criterion_index": 2, "passed": True},
            ]},
        ])
        self.assertEqual(res["per_case"][0]["passed"], 2)
        self.assertEqual(res["per_case"][0]["total"], 3)

    def test_per_case_vector_echoed_for_persistence(self):
        res = aggregate_scores([{"case_id": "c1", "split": "train", "passed": 1, "total": 2}])
        self.assertEqual(res["per_case"], [
            {"case_id": "c1", "split": "train", "passed": 1, "total": 2, "score": 0.5}
        ])


class TestAggregateErrors(unittest.TestCase):
    def test_zero_total_errors(self):
        with self.assertRaises(ValueError):
            aggregate_scores([{"case_id": "c", "split": "train", "passed": 0, "total": 0}])

    def test_passed_exceeds_total_errors(self):
        with self.assertRaises(ValueError):
            aggregate_scores([{"case_id": "c", "split": "train", "passed": 6, "total": 5}])

    def test_missing_split_errors(self):
        with self.assertRaises(ValueError):
            aggregate_scores([{"case_id": "c", "passed": 1, "total": 2}])

    def test_duplicate_case_id_in_split_errors(self):
        with self.assertRaises(ValueError):
            aggregate_scores([
                {"case_id": "dup", "split": "train", "passed": 1, "total": 2},
                {"case_id": "dup", "split": "train", "passed": 2, "total": 2},
            ])

    def test_results_passed_mismatch_errors(self):
        with self.assertRaises(ValueError):
            _passed_total({"case_id": "c", "passed": 3,
                           "results": [{"criterion_index": 0, "passed": True}]})

    def test_empty_scores_errors(self):
        with self.assertRaises(ValueError):
            aggregate_scores([])


if __name__ == "__main__":
    unittest.main()
