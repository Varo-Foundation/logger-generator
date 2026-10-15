"""Golden tests: every curated story's files hash to the recorded values.

A change to any generator that alters output fails here. If the change is intended,
regenerate the hashes with `UPDATE_GOLDEN=1 uv run pytest tests/test_golden.py` and say in
the commit why the output changed (consumers pin release tags, so they keep the old bytes
until they upgrade).
"""
import hashlib
import json
import os
from pathlib import Path

from conftest import files

GOLDEN = Path(__file__).with_name("golden.json")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_stories_match_golden_hashes(stories):
    actual = {name: {rel: digest(folder / rel) for rel in files(folder)} for name, folder in stories.items()}
    if os.environ.get("UPDATE_GOLDEN"):
        GOLDEN.write_text(json.dumps(actual, indent=1, sort_keys=True) + "\n")
    expected = json.loads(GOLDEN.read_text())
    assert sorted(actual) == sorted(expected)
    for name in expected:
        assert actual[name] == expected[name], f"story {name} changed"
