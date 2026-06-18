#!/usr/bin/env python3
"""Run all loop-optimizer deterministic-core unit tests (stdlib unittest only).

Usage:
    python3 scripts/tests/run.py          # run everything, verbose
    python3 scripts/tests/run.py -q       # quiet

Exit code 0 iff all tests pass (suitable for CI / pre-run gating).
No pytest dependency.
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)

# Make both the scripts/ modules and the tests/ importable.
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)


def build_suite():
    loader = unittest.TestLoader()
    return loader.discover(start_dir=HERE, pattern="test_*.py", top_level_dir=HERE)


def main(argv):
    verbosity = 1 if ("-q" in argv or "--quiet" in argv) else 2
    suite = build_suite()
    runner = unittest.TextTestRunner(verbosity=verbosity)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
