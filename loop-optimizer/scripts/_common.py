"""Shared deterministic helpers for the loop-optimizer scripts.

Standard library only. No model calls, no network, no hidden state.

These helpers are intentionally small and side-effect free (except the
explicit I/O helpers at the bottom) so the safety-critical scripts that
import them stay easy to reason about and test.
"""

import hashlib
import json
import re
import sys


# ---------------------------------------------------------------------------
# Tokenization (used for locality caps in verify_change.py)
# ---------------------------------------------------------------------------

# A "token" here is a deliberately simple whitespace-or-word unit. We do NOT
# try to match any model tokenizer (that would be non-deterministic across
# model versions). The locality cap only needs a stable, monotonic proxy for
# "how big is this span" so a reviewer can reason about it. Words + standalone
# punctuation runs are counted.
_TOKEN_RE = re.compile(r"\w+|[^\w\s]+")


def tokenize(text):
    """Return the deterministic token LIST for ``text`` (words + standalone
    punctuation runs). Empty list for falsy/whitespace-only text. The single
    source of truth for both count_tokens and the pure-deletion subset check."""
    if not text:
        return []
    return _TOKEN_RE.findall(text)


def count_tokens(text):
    """Return a deterministic token count for ``text``.

    Empty / whitespace-only text counts as 0 tokens.
    """
    return len(tokenize(text))


# ---------------------------------------------------------------------------
# Hashing (split_hash, current_prompt_hash)
# ---------------------------------------------------------------------------

def sha256_hex(text):
    """sha256 of ``text`` (str or bytes) as ``sha256:<hexdigest>``."""
    if isinstance(text, str):
        data = text.encode("utf-8")
    else:
        data = text
    return "sha256:" + hashlib.sha256(data).hexdigest()


def canonical_json(obj):
    """Deterministic JSON serialization for hashing.

    Sorted keys, compact separators, ``ensure_ascii=False`` so the same
    logical content always hashes identically regardless of insertion order
    or incidental whitespace.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


# ---------------------------------------------------------------------------
# Substring matching (unique-`before` check in verify_change.py)
# ---------------------------------------------------------------------------

def count_occurrences(haystack, needle):
    """Count NON-overlapping occurrences of ``needle`` in ``haystack``.

    Returns 0 for an empty needle (an empty ``before`` is never a valid,
    uniquely-locatable anchor).
    """
    if not needle:
        return 0
    count = 0
    start = 0
    while True:
        idx = haystack.find(needle, start)
        if idx == -1:
            break
        count += 1
        start = idx + len(needle)
    return count


# ---------------------------------------------------------------------------
# CLI plumbing: read a JSON payload from a file-path arg or from stdin
# ---------------------------------------------------------------------------

def load_payload(argv):
    """Load a JSON object for a CLI entrypoint.

    Resolution order:
      1. If ``argv`` has a positional arg that is not ``-``, read that file.
      2. Otherwise read JSON from stdin.

    Returns the parsed object. Raises ValueError on malformed JSON so the
    caller can convert it into a structured error result.
    """
    path = None
    for arg in argv:
        if arg in ("-", "--stdin"):
            path = None
            break
        if not arg.startswith("-"):
            path = arg
            break

    if path is not None:
        # A very common mistake is passing the JSON payload as an argv STRING
        # (`python3 tool.py '{"op":...}'`) instead of via stdin/a file. open()
        # then fails with an opaque OSError ("File name too long" for big JSON).
        # Detect the inline-JSON shape and explain the right invocation.
        looks_like_json = path.lstrip()[:1] in ("{", "[")
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = fh.read()
        except OSError:
            if looks_like_json:
                raise ValueError(
                    "the argument looks like inline JSON, not a file path. These scripts read "
                    "their JSON payload from STDIN (or a file path), not as an argv string. "
                    "Pipe it instead, e.g.:  printf '%s' '<json>' | python3 scripts/<tool>.py"
                )
            raise
    else:
        raw = sys.stdin.read()

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid JSON input: {}".format(exc))


def emit(result, stream=None):
    """Print a result object as pretty JSON to stdout (or ``stream``)."""
    out = stream if stream is not None else sys.stdout
    out.write(json.dumps(result, ensure_ascii=False, indent=2))
    out.write("\n")
    out.flush()
