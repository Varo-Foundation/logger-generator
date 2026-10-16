"""Same arguments and seed give byte-identical files; a different seed gives different ones."""
import pytest

from conftest import files
from logger_generator.cli import main

COMMANDS = {
    "fridgetag": ["fridgetag", "--scenario", "heat-excursion", "--model", "2L", "--days", "20"],
    "ems": ["ems", "--scenario", "power-outage", "--active-days", "62", "--compact"],
    "haier": ["haier", "--scenario", "freeze-event", "--days", "14"],
    "metafridge": ["metafridge", "--scenario", "cloudy-week", "--days", "30"],
}


def run(tmp_path, name, args):
    out = tmp_path / name
    main(args + ["--out", str(out)])
    return {rel: (out / rel).read_bytes() for rel in files(out)}


@pytest.mark.parametrize("command", COMMANDS)
def test_same_seed_same_bytes(tmp_path, command):
    args = COMMANDS[command] + ["--seed", "7"]
    assert run(tmp_path, "a", args) == run(tmp_path, "b", args)


@pytest.mark.parametrize("command", COMMANDS)
def test_other_seed_other_bytes(tmp_path, command):
    a = run(tmp_path, "a", COMMANDS[command] + ["--seed", "7"])
    b = run(tmp_path, "b", COMMANDS[command] + ["--seed", "8"])
    assert a.keys() == b.keys() and a != b


def test_rerun_replaces_previous_output(tmp_path):
    out = tmp_path / "ft"
    main(["fridgetag", "--serial", "160600000101", "--days", "5", "--out", str(out)])
    main(["fridgetag", "--serial", "160600000102", "--days", "5", "--out", str(out)])
    assert all(name.startswith("160600000102_") for name in files(out))
