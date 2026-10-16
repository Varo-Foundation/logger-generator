"""The test library: manifest schema, folder layout, fixed times and a golden hash.

If a generator change alters the library's bytes on purpose, regenerate the hashes with
`UPDATE_GOLDEN=1 uv run pytest tests/test_library.py` and check that every case's `expect`
block still holds (consumers compare their app's results against it).
"""
import hashlib
import json
import os
from pathlib import Path

import pytest

from conftest import files
from logger_generator import __version__, library
from logger_generator.cli import main

GOLDEN = Path(__file__).with_name("golden_library.json")
FAMILIES = {"fridgeTag", "pqsEms", "haier", "metaFridge"}
OUTCOMES = {"recognized", "insideLoggerFolder", "noLoggerFiles", "empty"}
NOTICES = {"unreadableData", "incomplete", "duplicate", "phoneCopy", "stale", "foundInSubfolder",
           "missingCompanion", "multipleReports", "clockUnset"}
CASE_KEYS = {"id", "title", "family", "group", "description", "path", "pickPath", "readAt", "expect"}
EXPECT_KEYS = {"outcome", "family", "parse", "days", "alarmDays", "failingChecks", "notices"}


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("library")
    main(["library", "--out", str(out)])
    return out, json.loads((out / "manifest.json").read_text())


def test_manifest_header(built):
    _, manifest = built
    assert manifest["version"] == library.MANIFEST_VERSION == 1
    assert manifest["generator"] == __version__
    assert set(manifest) == {"version", "generator", "cases"}


def test_every_case_follows_the_schema(built):
    _, manifest = built
    ids = [case["id"] for case in manifest["cases"]]
    assert len(ids) == len(set(ids))
    for case in manifest["cases"]:
        assert set(case) == CASE_KEYS, case["id"]
        assert case["family"] in FAMILIES
        assert case["title"] and case["group"]
        assert case["description"].endswith(".") and "\n" not in case["description"]
        assert case["pickPath"] == case["path"] or case["pickPath"].startswith(case["path"] + "/")
        assert case["readAt"] == "2026-10-15T09:20:00"
        expect = case["expect"]
        assert set(expect) == EXPECT_KEYS, case["id"]
        assert expect["outcome"] in OUTCOMES
        if expect["outcome"] == "recognized":
            assert expect["family"] == case["family"]
            assert expect["parse"] in {"ok", "partial", "failed"}
            assert all(isinstance(expect[k], int) for k in ("days", "alarmDays")), case["id"]
            assert set(expect["notices"]) <= NOTICES
            assert "phoneCopy" not in expect["notices"] and "stale" not in expect["notices"]
        else:
            assert expect["family"] is expect["parse"] is expect["notices"] is None
            assert expect["failingChecks"] == ["pick.family"]
        assert expect["failingChecks"] is None or all(isinstance(c, str) for c in expect["failingChecks"])


def test_groups_cover_every_kind_of_case(built):
    _, manifest = built
    groups = {case["group"] for case in manifest["cases"]}
    assert groups == {"Fridge-tag", "EMS", "Haier", "MetaFridge", "Broken files", "Wrong picks"}
    outcomes = {case["expect"]["outcome"] for case in manifest["cases"]}
    assert outcomes == OUTCOMES


def test_every_path_exists(built):
    out, manifest = built
    for case in manifest["cases"]:
        assert (out / case["path"]).is_dir(), case["id"]
        assert (out / case["pickPath"]).is_dir(), case["id"]
    folders = {p.name for p in out.iterdir() if p.is_dir()}
    assert folders == {case["path"] for case in manifest["cases"]}


def test_pick_shapes(built):
    out, manifest = built
    cases = {case["id"]: case for case in manifest["cases"]}
    assert not any((out / cases["wrong-pick-empty-folder"]["path"]).iterdir())
    assert cases["wrong-pick-history-folder"]["pickPath"].endswith("/DATA_HISTORY")
    unrelated = files(out / cases["wrong-pick-unrelated-files"]["path"])
    assert unrelated and not any(name.lower().endswith((".txt", ".csv", ".json", ".pdf")) for name in unrelated)
    nested = out / cases["wrong-pick-one-folder-down"]["path"]
    assert not [p for p in nested.iterdir() if p.is_file()]
    two = files(out / cases["fridgetag-2e-two-reports"]["path"])
    assert sum(name.endswith(".txt") for name in two) == 2 and sum(name.endswith(".pdf") for name in two) == 2
    assert not [n for n in files(out / cases["fridgetag-2e-missing-pdf"]["path"]) if n.endswith(".pdf")]


def test_files_carry_the_fixed_time(built):
    out, _ = built
    for path in [out, *out.rglob("*")]:
        assert os.stat(path).st_mtime == library.FILE_TIME, path


def test_library_matches_golden_hashes(built):
    out, _ = built
    actual = {rel: hashlib.sha256((out / rel).read_bytes()).hexdigest() for rel in files(out)}
    if os.environ.get("UPDATE_GOLDEN"):
        GOLDEN.write_text(json.dumps(actual, indent=1, sort_keys=True) + "\n")
    expected = json.loads(GOLDEN.read_text())
    assert sorted(actual) == sorted(expected)
    changed = [rel for rel in expected if actual[rel] != expected[rel]]
    assert not changed, f"library files changed: {changed[:5]}"


def test_rerun_gives_identical_bytes(built, tmp_path):
    out, _ = built
    main(["library", "--out", str(tmp_path)])
    assert files(tmp_path) == files(out)
    for rel in files(out):
        assert (tmp_path / rel).read_bytes() == (out / rel).read_bytes(), rel
