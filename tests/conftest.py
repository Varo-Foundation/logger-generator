"""Shared fixtures: every curated story is generated once per test session."""
import pytest

from logger_generator import scenarios


@pytest.fixture(scope="session")
def stories(tmp_path_factory):
    """{story name: output folder} for every curated story."""
    root = tmp_path_factory.mktemp("stories")
    out = {}
    for name, function in scenarios.STORIES.items():
        folder = root / name
        function(str(folder))
        out[name] = folder
    return out


def files(folder):
    """Every file below `folder`, as sorted relative POSIX paths."""
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())
