"""H4 regression (the audit's Monte-Carlo, locked in as a test).

It drives the SHIPPING score_compare gate over many NEUTRAL (zero-true-effect)
changes and shows that confirming against a FRESHLY re-measured baseline
(train_b2/held_b2 -- what the fix mandates) lets through materially fewer false
MERGEs than reusing the first-call baseline (what the H4 bug did). Reusing the
baseline correlates the two gate checks: a baseline drawn LOW clears the first
gate AND, reused, the confirm gate -- so confirm filters only ~half the noise it
should. Re-measuring makes the second check independent.

If anyone reverts the orchestrator to reuse the baseline, the "correlated" arm
here is what they get; this test documents, in numbers, why that roughly doubles
the false-MERGE rate, and fails if the gap collapses.

Determinism: a fixed seed + CPython's stable Mersenne Twister make the counts
reproducible, so the assertions are on concrete numbers, not luck. The model:
|train|=5 cases x ~5 criteria (25 binary criteria), |held|=3 x ~5 (15), each
criterion an independent Bernoulli(p); a "neutral" change keeps p identical
before and after, so EVERY confirmed MERGE is false by construction.
"""

import os
import sys
import unittest
from random import Random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from score_compare import score_compare  # noqa: E402
from calibrate_noise import eps_for_split  # noqa: E402

SEED = 20260619
N_TRIALS = 30000
TRAIN_CRIT = 25   # 5 train cases x ~5 rubric criteria
HELD_CRIT = 15    # 3 held-out cases x ~5 rubric criteria
P = 0.6           # neutral per-criterion pass probability (same before & after)


def _measure(rng, n, p=P):
    """One noisy measurement of a split: Sigma Bernoulli(p) / n."""
    return sum(1 for _ in range(n) if rng.random() < p) / n


class TestH4ConfirmIndependenceMonteCarlo(unittest.TestCase):
    def test_remeasured_baseline_cuts_false_merges_vs_reused_baseline(self):
        rng = Random(SEED)

        # Calibrate eps the way the loop does (stddev2), from a stable sample so
        # the margin is the true run-to-run spread, not a 5-sample fluke.
        cal = Random(SEED + 1)
        eps_t, _ = eps_for_split([_measure(cal, TRAIN_CRIT) for _ in range(400)])
        eps_h, _ = eps_for_split([_measure(cal, HELD_CRIT) for _ in range(400)])

        provisional_merges = 0
        false_independent = 0   # confirmed MERGEs with a FRESH baseline (the fix)
        false_correlated = 0    # confirmed MERGEs reusing the first baseline (bug)

        for _ in range(N_TRIALS):
            train_b = _measure(rng, TRAIN_CRIT)
            held_b = _measure(rng, HELD_CRIT)
            train_a1 = _measure(rng, TRAIN_CRIT)
            held_a1 = _measure(rng, HELD_CRIT)

            prov = score_compare(train_b, train_a1, held_b, held_a1, eps_t, eps_h)
            if prov["decision"] != "MERGE":
                continue
            provisional_merges += 1

            # one confirm re-run of the candidate, shared by both arms
            train_a2 = _measure(rng, TRAIN_CRIT)
            held_a2 = _measure(rng, HELD_CRIT)
            # the fix: a fresh, independent re-measurement of the baseline
            train_b2 = _measure(rng, TRAIN_CRIT)
            held_b2 = _measure(rng, HELD_CRIT)

            indep = score_compare(train_b, train_a1, held_b, held_a1, eps_t, eps_h,
                                  train_a2=train_a2, held_a2=held_a2,
                                  train_b2=train_b2, held_b2=held_b2)
            if indep["decision"] == "MERGE" and indep["confirmed"]:
                false_independent += 1

            corr = score_compare(train_b, train_a1, held_b, held_a1, eps_t, eps_h,
                                 train_a2=train_a2, held_a2=held_a2,
                                 train_b2=train_b, held_b2=held_b)  # reuse 1st baseline
            if corr["decision"] == "MERGE" and corr["confirmed"]:
                false_correlated += 1

        # The sim must actually exercise the confirm path.
        self.assertGreater(provisional_merges, 200,
                           "too few provisional merges to be meaningful: %d" % provisional_merges)
        # Both arms confirm SOME false merges (confirm is not a brick wall)...
        self.assertGreater(false_correlated, 0)
        # ...but reusing the baseline (the bug) passes materially more than a fresh
        # baseline (the fix). The audit measured ~2x; we assert >= 1.5x with margin
        # for seed wobble. THIS is the H4 regression guard.
        self.assertGreaterEqual(false_correlated, false_independent * 1.5,
            "reused-baseline confirm (%d) should pass far more false merges than "
            "re-measured-baseline confirm (%d) -- H4 may have regressed"
            % (false_correlated, false_independent))


if __name__ == "__main__":
    unittest.main()
