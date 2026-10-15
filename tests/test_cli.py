"""The command line: help for every command, the scenario listing and errors."""
import pytest

from logger_generator import __version__, scenarios
from logger_generator.cli import main


@pytest.mark.parametrize("command", ["fridgetag", "ems", "haier", "scenario"])
def test_help(capsys, command):
    with pytest.raises(SystemExit) as exit:
        main([command, "--help"])
    assert exit.value.code == 0
    assert "usage: logger-generator " + command in capsys.readouterr().out


def test_list_scenarios_names_everything(capsys):
    assert main(["--list-scenarios"]) == 0
    out = capsys.readouterr().out
    for name in list(scenarios.STORIES) + ["heat-excursion", "power-outage", "damaged-lines", "unset-clock"]:
        assert name in out


def test_version(capsys):
    with pytest.raises(SystemExit):
        main(["--version"])
    assert __version__ in capsys.readouterr().out


def test_scenario_needs_out():
    with pytest.raises(SystemExit):
        main(["scenario", "demo-ems"])


def test_unknown_scenario_is_rejected():
    with pytest.raises(SystemExit):
        main(["ems", "--scenario", "no-such-thing", "--out", "x"])
