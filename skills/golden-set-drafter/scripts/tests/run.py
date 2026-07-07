#!/usr/bin/env python3
"""Run the golden-set-drafter test suite (mirrors agent-coach's convention)."""

import os
import sys
import unittest


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    suite = unittest.defaultTestLoader.discover(here, pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
