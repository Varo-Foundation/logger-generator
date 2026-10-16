"""Every generated file is recognised by the apps' file-name patterns as the right family."""
import pytest

from conftest import files
from patterns import ANDROID_DATA_FILE, HISTORY_FOLDER, IOS_DATA_FILE, android_families, ios_families

EXPECTED = {  # file kind -> (iOS family, Android pattern)
    "fridgetag-txt": ({"fridgeTag"}, {"BERLINGER_DATA_PATTERN"}),
    "summary-pdf": (set(), set()),
    "ems-current": ({"pqsCurrent"}, {"CURRENT_DATA_FILE_PATTERN"}),
    "ems-history": ({"pqsHistory"}, {"HISTORY_DATA_FILE_PATTERN"}),
    "ems-sync": ({"pqsSync"}, {"SYNC_DATA_FILE_PATTERN"}),
    "ems-pdf": ({"pqsSummaryPdf"}, {"PDF_DATA_FILE_PATTERN"}),
    "haier": ({"haier"}, {"HAIER_DATA_PATTERN"}),
    "metafridge": ({"metaFridge"}, {"AUCMA_DATA_PATTERN"}),
}


def kind(rel):
    name = rel.rsplit("/", 1)[-1]
    if name.endswith(".txt"):
        return "fridgetag-txt"
    if name.endswith(".CSV"):
        return "haier"
    if name.endswith(".csv"):
        return "metafridge"
    if "_CURRENT_DATA_" in name:
        return "ems-current"
    if "_SYNC_" in name:
        return "ems-sync"
    if "_60DTR_SUMMARY_" in name:
        return "ems-pdf"
    if "_DATA_" in name:
        return "ems-history"
    return "summary-pdf"


def all_files(stories):
    return [(story, rel) for story, folder in stories.items() for rel in files(folder)]


def test_every_file_matches_exactly_its_family(stories):
    checked = 0
    for story, rel in all_files(stories):
        name = rel.rsplit("/", 1)[-1]
        ios, android = EXPECTED[kind(rel)]
        assert ios_families(name) == ios, (story, rel)
        assert android_families(name) == android, (story, rel)
        assert IOS_DATA_FILE.search(name) and ANDROID_DATA_FILE.fullmatch(name), (story, rel)
        checked += 1
    assert checked > 50


def test_history_files_live_in_data_history(stories):
    for story, rel in all_files(stories):
        if kind(rel) == "ems-history":
            folder = rel.rsplit("/", 2)[-2]
            if story == "parser-edge-cases" and rel.startswith("ems-history-case/"):
                assert folder == "data_history" and folder.upper() == HISTORY_FOLDER
            else:
                assert folder == HISTORY_FOLDER, rel


@pytest.mark.parametrize("folder", ["screenshot-story/EMS", "demo-ems", "demo-ems-alarm", "format-tour/ems"])
def test_pqs_drive_layout(stories, folder):
    """At most 10 root items, exactly one CURRENT_DATA, SYNC and summary PDF, one serial throughout."""
    story, _, sub = folder.partition("/")
    root = stories[story] / sub if sub else stories[story]
    items = sorted(p.name for p in root.iterdir())
    assert len(items) <= 10 and HISTORY_FOLDER in items
    kinds = [kind(name) for name in items if name != HISTORY_FOLDER]
    assert sorted(kinds) == ["ems-current", "ems-pdf", "ems-sync"]
    serials = {name.rsplit("/", 1)[-1].split("_")[0] for name in files(root)}
    assert len(serials) == 1


def test_fridgetag_name_is_serial_and_creation_stamp(stories):
    for story, rel in all_files(stories):
        if kind(rel) == "fridgetag-txt":
            serial, stamp = rel.rsplit("/", 1)[-1][:-4].split("_")
            assert len(serial) == 12 and serial.isdigit() and len(stamp) == 12 and stamp.isdigit()


def test_metafridge_name_is_serial_and_date_range(stories):
    for story, rel in all_files(stories):
        if kind(rel) == "metafridge":
            serial, start, end = rel.rsplit("/", 1)[-1][:-4].split("_")
            assert serial and len(start) == len(end) == 8 and start.isdigit() and end.isdigit() and start <= end
