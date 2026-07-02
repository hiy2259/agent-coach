"""Option B drift-guard: vendored Runner/Grader copies must not drift.

The skill prefers the co-located agent-coach originals at runtime; the
byte-copies under ``agents/vendored/`` exist so a standalone ``.skill``
install (no sibling agent-coach) still has the same-ruler actor prompts. A
copy is only safe while it is byte-identical to its original — silent drift
would mean the drafter's expose pass runs a DIFFERENT Runner/Grader than
agent-coach's cold start, quietly breaking the same-ruler contract. Wherever
both files exist (the repo, any packaging build), this test enforces
byte-equality; in a standalone install the originals are absent and the
vendored copies ARE the source — nothing to compare, so the test skips with
that exact statement.
"""

import os
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_SKILL_DIR = os.path.dirname(os.path.dirname(_TESTS_DIR))
_REPO_DIR = os.path.dirname(_SKILL_DIR)
_AC_AGENTS = os.path.join(_REPO_DIR, "agent-coach", "agents")
_VENDORED = os.path.join(_SKILL_DIR, "agents", "vendored")


def _read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


@unittest.skipUnless(os.path.isdir(_AC_AGENTS),
                     "agent-coach not co-located — standalone install: the vendored "
                     "copies are the active source, nothing to compare")
class VendoredDriftGuard(unittest.TestCase):

    def test_vendored_copies_exist(self):
        for name in ("runner.md", "grader.md"):
            self.assertTrue(os.path.isfile(os.path.join(_VENDORED, name)),
                            "missing vendored copy: " + name)

    def test_runner_byte_identical(self):
        self.assertEqual(_read_bytes(os.path.join(_VENDORED, "runner.md")),
                         _read_bytes(os.path.join(_AC_AGENTS, "runner.md")),
                         "vendored runner.md drifted from agent-coach original — "
                         "re-copy it (same-ruler contract breaks on drift)")

    def test_grader_byte_identical(self):
        self.assertEqual(_read_bytes(os.path.join(_VENDORED, "grader.md")),
                         _read_bytes(os.path.join(_AC_AGENTS, "grader.md")),
                         "vendored grader.md drifted from agent-coach original — "
                         "re-copy it (same-ruler contract breaks on drift)")


if __name__ == "__main__":
    unittest.main()
