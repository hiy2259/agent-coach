"""Tests for calibrate_noise.py -- S7 noise-margin estimation (per split)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from calibrate_noise import calibrate, eps_for_split, _percentile  # noqa: E402


class TestStddev2Estimator(unittest.TestCase):
    def test_per_split_eps_computed(self):
        res = calibrate({
            "train": [0.70, 0.72, 0.68, 0.71, 0.69],
            "heldout": [0.65, 0.67, 0.64],
        })
        self.assertTrue(res["ok"])
        self.assertIn("eps_train", res)
        self.assertIn("eps_heldout", res)
        # eps must be positive given non-identical samples
        self.assertGreater(res["eps_train"], 0.0)
        self.assertGreater(res["eps_heldout"], 0.0)
        # train and heldout are estimated independently (per-split)
        self.assertNotEqual(res["per_split"]["train"]["n"], res["per_split"]["heldout"]["n"])

    def test_eps_is_two_stddev(self):
        # Known sample: [0.0, 0.2] -> mean 0.1, pop stddev 0.1 -> eps = 0.2
        eps, detail = eps_for_split([0.0, 0.2], estimator="stddev2")
        self.assertAlmostEqual(eps, 0.2, places=9)
        self.assertAlmostEqual(detail["stddev"], 0.1, places=9)

    def test_identical_samples_zero_raw_eps(self):
        # stddev of identical samples is 0; with the floor disabled, eps is 0.
        eps, _ = eps_for_split([0.7, 0.7, 0.7], estimator="stddev2", min_eps=0.0)
        self.assertEqual(eps, 0.0)

    def test_default_min_eps_floor_keeps_eps_positive(self):
        # The default floor (0.02) keeps eps strictly positive even at stddev 0,
        # so a +0.0 tie can never look like progress to the merge gate (B).
        eps, _ = eps_for_split([0.7, 0.7, 0.7], estimator="stddev2")
        self.assertEqual(eps, 0.02)

    def test_min_eps_floor_applied(self):
        eps, _ = eps_for_split([0.7, 0.7], estimator="stddev2", min_eps=0.01)
        self.assertEqual(eps, 0.01)

    def test_single_sample_stddev_zero(self):
        eps, _ = eps_for_split([0.7], estimator="stddev2", min_eps=0.0)
        self.assertEqual(eps, 0.0)


class TestPairwiseEstimator(unittest.TestCase):
    def test_pairwise_p95(self):
        res = calibrate(
            {"train": [0.60, 0.70, 0.80], "heldout": [0.60, 0.62, 0.64]},
            estimator="pairwise_p95",
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["estimator"], "pairwise_p95")
        self.assertGreaterEqual(res["eps_train"], 0.0)
        # pairwise abs diffs of [0.6,0.7,0.8] are {0.1,0.2,0.1}; p95 ~ near max 0.2
        self.assertLessEqual(res["eps_train"], 0.2 + 1e-9)

    def test_pairwise_single_sample_zero(self):
        eps, detail = eps_for_split([0.7], estimator="pairwise_p95", min_eps=0.0)
        self.assertEqual(eps, 0.0)
        self.assertEqual(detail["n_pairs"], 0)


class TestPercentileHelper(unittest.TestCase):
    def test_percentile_interpolation(self):
        # p50 of [0,1,2,3,4] is 2.0
        self.assertAlmostEqual(_percentile([0, 1, 2, 3, 4], 50), 2.0, places=9)
        # p100 is the max
        self.assertAlmostEqual(_percentile([0, 1, 2, 3, 4], 100), 4.0, places=9)
        # p0 is the min
        self.assertAlmostEqual(_percentile([0, 1, 2, 3, 4], 0), 0.0, places=9)


class TestGateSatisfiability(unittest.TestCase):
    """A: calibration-time detection that the merge gate can never be cleared."""

    def test_satisfiable_when_headroom_exceeds_eps(self):
        res = calibrate(
            {"train": [0.70, 0.74, 0.72], "heldout": [0.60, 0.62, 0.64]},
            baseline={"train": 0.72, "heldout": 0.63},
        )
        self.assertTrue(res["gate_satisfiable"])
        self.assertNotIn("warnings", res)
        self.assertIn("headroom", res["per_split"]["train"])

    def test_unsatisfiable_warns_when_eps_exceeds_headroom(self):
        # Big run-to-run swing (eps ~ 0.25) against a near-top baseline (headroom 0.16).
        res = calibrate({"train": [0.70, 1.00, 0.84]}, baseline={"train": 0.84})
        self.assertFalse(res["gate_satisfiable"])
        self.assertTrue(any("UNSATISFIABLE" in w for w in res["warnings"]))

    def test_saturated_baseline_warns(self):
        res = calibrate({"train": [1.0, 1.0, 1.0]}, baseline={"train": 1.0})
        self.assertFalse(res["gate_satisfiable"])
        self.assertTrue(any("SATURATED" in w for w in res["warnings"]))

    def test_no_baseline_means_no_gate_field(self):
        res = calibrate({"train": [0.70, 0.72, 0.68]})
        self.assertNotIn("gate_satisfiable", res)
        self.assertNotIn("warnings", res)

    def test_invalid_baseline_out_of_range_raises(self):
        # A baseline outside [0,1] is malformed input -> raise, not a misleading
        # "SATURATED" message.
        with self.assertRaises(ValueError):
            calibrate({"train": [0.8, 0.8, 0.8]}, baseline={"train": 1.5})


class TestErrors(unittest.TestCase):
    def test_empty_samples_object_errors(self):
        with self.assertRaises(ValueError):
            calibrate({})

    def test_empty_split_list_errors(self):
        with self.assertRaises(ValueError):
            calibrate({"train": []})

    def test_unknown_estimator_errors(self):
        with self.assertRaises(ValueError):
            eps_for_split([0.1, 0.2], estimator="bogus")


class TestInputValidation(unittest.TestCase):
    """F-09: calibrate() rejects a non-positive floor and an out-of-range
    percentile up front, instead of silently dropping the floor to 0 or letting
    the pairwise estimator index past the sample list."""

    def test_nonpositive_min_eps_raises(self):
        with self.assertRaises(ValueError):
            calibrate({"train": [0.7, 0.72]}, min_eps=0.0)
        with self.assertRaises(ValueError):
            calibrate({"train": [0.7, 0.72]}, min_eps=-0.1)

    def test_out_of_range_percentile_raises_for_pairwise(self):
        with self.assertRaises(ValueError):
            calibrate({"train": [0.6, 0.7, 0.8]}, estimator="pairwise_p95", percentile=150)
        with self.assertRaises(ValueError):
            calibrate({"train": [0.6, 0.7, 0.8]}, estimator="pairwise_p95", percentile=-5)

    def test_bogus_percentile_ignored_for_stddev2(self):
        # percentile is unused by stddev2, so a bogus value there must NOT error.
        res = calibrate({"train": [0.7, 0.72, 0.68]}, estimator="stddev2", percentile=150)
        self.assertTrue(res["ok"])


if __name__ == "__main__":
    unittest.main()
