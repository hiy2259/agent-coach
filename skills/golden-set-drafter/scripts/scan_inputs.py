#!/usr/bin/env python3
"""Collect case-language SIGNALS for the drafter. Hints only — never a decision.

The case language must come from the target's real production inputs/logs, not
from the language the target file happens to be written in (counterexample in
this very repo: agent-coach's instructions are English, its real usage is
Korean). This script only gathers evidence in the plan's priority order:

  1. failure-log.jsonl        (real production failures — strongest signal)
  2. user-provided log files  (payload "extra_logs")
  3. run-config.json          (weak context: paths/notes may hint locale)
  4. golden-set.json          (INCIDENTAL only — rare in v1 create-new; its
                               presence must NOT trigger update-mode handling)

The model + user make the call; when no signal is found the skill must ASK.

Usage::

    printf '%s' '{"target": "path/to/target.md", "roots": ["loop"], "extra_logs": []}' \
        | python3 scripts/scan_inputs.py
"""

import json
import os
import sys

SAMPLE_CHARS = 2000
MAX_DEPTH = 4
PRIORITY = {"failure-log.jsonl": 1, "extra-log": 2, "run-config.json": 3, "golden-set.json": 4}


def _script_ratios(text):
    """Rough per-script character ratios — a hint, not linguistics."""
    counts = {"hangul": 0, "latin": 0, "cjk": 0, "kana": 0, "other_letters": 0}
    letters = 0
    for ch in text:
        code = ord(ch)
        if 0xAC00 <= code <= 0xD7A3 or 0x1100 <= code <= 0x11FF:
            counts["hangul"] += 1
        elif ch.isalpha() and code < 0x0250:
            counts["latin"] += 1
        elif 0x4E00 <= code <= 0x9FFF:
            counts["cjk"] += 1
        elif 0x3040 <= code <= 0x30FF:
            counts["kana"] += 1
        elif ch.isalpha():
            counts["other_letters"] += 1
        else:
            continue
        letters += 1
    if letters == 0:
        return {k: 0.0 for k in counts}
    return {k: round(v / letters, 3) for k, v in counts.items()}


def _sample(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read(SAMPLE_CHARS)
    except OSError as exc:
        return "<unreadable: {}>".format(exc)


def _walk(root):
    root = os.path.abspath(root)
    base_depth = root.rstrip(os.sep).count(os.sep)
    for dirpath, dirnames, filenames in os.walk(root):
        if dirpath.count(os.sep) - base_depth >= MAX_DEPTH:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(".") and d not in ("node_modules", "__pycache__", "dist")]
        for name in filenames:
            if name in ("failure-log.jsonl", "run-config.json", "golden-set.json"):
                yield os.path.join(dirpath, name), name


def scan(payload):
    target = payload.get("target") or ""
    roots = payload.get("roots") or []
    if target:
        tdir = os.path.dirname(os.path.abspath(target))
        if tdir not in roots:
            roots.insert(0, tdir)
    if os.path.isdir("loop") and "loop" not in roots:
        roots.append("loop")
    if not roots:
        roots = ["."]

    signals = []
    seen = set()
    for root in roots:
        if not os.path.isdir(root):
            continue
        for path, name in _walk(root):
            if path in seen:
                continue
            seen.add(path)
            text = _sample(path)
            signals.append({
                "path": path,
                "kind": name,
                "priority": PRIORITY[name],
                "incidental": name == "golden-set.json",
                "sample_chars": len(text),
                "script_ratios": _script_ratios(text),
            })

    for path in payload.get("extra_logs") or []:
        if os.path.isfile(path) and path not in seen:
            text = _sample(path)
            signals.append({
                "path": path,
                "kind": "extra-log",
                "priority": PRIORITY["extra-log"],
                "incidental": False,
                "sample_chars": len(text),
                "script_ratios": _script_ratios(text),
            })

    signals.sort(key=lambda s: (s["priority"], s["path"]))
    return {
        "ok": True,
        "signals": signals,
        "note": ("hints only — the language decision stays with the model+user; "
                 "no signal => ASK the user, never infer from the target file's "
                 "own prose. golden-set.json entries are INCIDENTAL language "
                 "signals and must not trigger update-mode handling."),
    }


def run_cli(argv):
    try:
        data = sys.stdin.read() if len(argv) < 2 else open(argv[1], encoding="utf-8").read()
        payload = json.loads(data) if data.strip() else {}
        result = scan(payload)
    except (ValueError, OSError) as exc:
        print(json.dumps({"ok": False, "reason": "error: {}".format(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(run_cli(sys.argv))
