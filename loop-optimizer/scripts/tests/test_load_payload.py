"""Tests for F: load_payload gives a clear hint when JSON is passed as an argv
string instead of via stdin / a file path (the opaque 'File name too long' trap)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from _common import load_payload  # noqa: E402


class TestLoadPayloadFriendlyError(unittest.TestCase):
    def test_inline_json_object_argv_hints_stdin(self):
        with self.assertRaises(ValueError) as cm:
            load_payload(['{"op": "split"}'])
        self.assertIn("STDIN", str(cm.exception))

    def test_inline_json_array_argv_hints_stdin(self):
        with self.assertRaises(ValueError) as cm:
            load_payload(['[1, 2, 3]'])
        self.assertIn("STDIN", str(cm.exception))

    def test_nonexistent_nonjson_path_still_raises_oserror(self):
        # A plain bad path that isn't JSON should propagate the real OSError, so
        # genuine file errors aren't masked by the friendly hint.
        with self.assertRaises(OSError):
            load_payload(["/no/such/file/here.json"])


if __name__ == "__main__":
    unittest.main()
