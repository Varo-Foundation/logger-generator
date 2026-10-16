"""The test library: a curated set of logger drives, each with the outcome an app should show.

    logger-generator library --out DIR

Writes one folder per case, laid out like the logger's USB drive, and `manifest.json` at
the root describing every case: what it is, which folder a tester should pick and what an
app that reads these formats is expected to report (recognized or not, parse result, days,
alarm days, failing checks, notices). The set covers normal downloads and alarms for every
format, damaged files, and picks that aren't a logger drive at all.

Every case is seeded and read at the same fixed wall-clock time (`READ_AT`, recorded as
`readAt` on each case), and every file and folder gets that time as its modification time,
so the library and an archive of it are reproducible byte for byte. Apps should import
library cases the way they import their bundled sample: as test data read at `readAt`, so
the age of the data never triggers "old report" or "copy on this phone" warnings.

Expectations are only recorded where they are stable; `null` means "don't check". Their
values come from running the cases through the Varo iOS import path; see the README's
"Test library" section for the field meanings and how to add a case.
"""
import json
import os
import shutil
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from . import __version__, fridgetag, scenarios

MANIFEST_VERSION = 1
READ_AT = datetime(2026, 10, 15, 9, 20)
# File times: the read time taken as UTC, so the stamp doesn't depend on the build machine.
FILE_TIME = READ_AT.replace(tzinfo=timezone.utc).timestamp()

FRIDGE_TAG, EMS, HAIER, METAFRIDGE = "fridgeTag", "pqsEms", "haier", "metaFridge"


def expect(outcome="recognized", family=None, parse=None, days=None, alarm_days=None,
           failing_checks=None, notices=None):
    """An `expect` block; `None` (JSON null) skips a field."""
    return {"outcome": outcome, "family": family, "parse": parse, "days": days, "alarmDays": alarm_days,
            "failingChecks": failing_checks, "notices": notices}


@dataclass
class Case:
    id: str
    title: str
    family: str  # the logger in the case, even when the pick isn't recognized
    group: str
    description: str
    build: object  # build(folder) writes the case into its folder
    expect: dict
    pick: str = None  # subfolder a tester picks, relative to the case folder (default: the folder itself)
    read_at: datetime = READ_AT

    @property
    def path(self):
        return self.id

    def manifest(self):
        return {
            "id": self.id,
            "title": self.title,
            "family": self.family,
            "group": self.group,
            "description": self.description,
            "path": self.path,
            "pickPath": f"{self.path}/{self.pick}" if self.pick else self.path,
            "readAt": self.read_at.strftime("%Y-%m-%dT%H:%M:%S"),
            "expect": self.expect,
        }


# --- Builders -----------------------------------------------------------------------------

def _tag(model, serial, seed):
    return fridgetag.Story(model, serial, READ_AT, seed=seed)


def fridgetag_case(scenario, model, serial, seed):
    return lambda folder: scenarios._fridgetag(scenario, folder, _tag(model, serial, seed))


def ems_case(scenario):
    return lambda folder: scenarios._ems(scenario, folder)


def haier_case(scenario):
    return lambda folder: scenarios._haier(scenario, folder)


def metafridge_case(scenario):
    return lambda folder: scenarios._metafridge(scenario, folder)


def two_reports(folder):
    """Today's report plus the same tag's report from a month earlier, both with their PDFs."""
    fridgetag.write(_tag("2E", "160600000040", 40), folder)
    older = os.path.join(folder, "older")
    fridgetag.write(replace(_tag("2E", "160600000040", 40), created=datetime(2026, 9, 15, 9, 20)), older)
    for name in sorted(os.listdir(older)):
        os.rename(os.path.join(older, name), os.path.join(folder, name))
    os.rmdir(older)


def missing_pdf(folder):
    """A normal report whose PDF wasn't copied along with the `.txt`."""
    fridgetag.write(_tag("2E", "160600000041", 41), folder)
    for name in os.listdir(folder):
        if name.endswith(".pdf"):
            os.remove(os.path.join(folder, name))


def history_folder(folder):
    """A whole EMS drive; the tester is meant to (wrongly) pick its DATA_HISTORY folder."""
    scenarios._ems("normal", folder)


def empty_folder(folder):
    os.makedirs(folder, exist_ok=True)


def unrelated_files(folder):
    """A folder of everyday files that aren't from a logger (placeholders, not real documents)."""
    os.makedirs(folder, exist_ok=True)
    for name in ("IMG_2041.jpg", "IMG_2042.jpg", "Stock count October.docx"):
        with open(os.path.join(folder, name), "w") as f:
            f.write(f"Placeholder for {name}: not a logger file.\n")


def one_folder_down(folder):
    """A folder holding a Fridge-tag drive copied into a subfolder."""
    fridgetag.write(_tag("2E", "160600000042", 42), os.path.join(folder, "Fridge-tag 160600000042"))


# --- The catalogue ------------------------------------------------------------------------

CASES = [
    # Fridge-tag
    Case("fridgetag-2e-normal", "Fridge-tag 2E, normal", FRIDGE_TAG, "Fridge-tag",
         "Sixty days in a 2-8 °C fridge with no excursions.",
         fridgetag_case("normal", "2E", "160600000031", 31),
         expect(family=FRIDGE_TAG, parse="ok", days=60, alarm_days=0, failing_checks=[], notices=[])),
    Case("fridgetag-2e-heat-excursion", "Fridge-tag 2E, heat alarm", FRIDGE_TAG, "Fridge-tag",
         "A 17-hour warm spell five days back peaking at +12 °C raises a high alarm that day.",
         fridgetag_case("heat-excursion", "2E", "160600000032", 32),
         expect(family=FRIDGE_TAG, parse="ok", days=60, alarm_days=1, failing_checks=[], notices=[])),
    Case("fridgetag-2e-heat-no-alarm", "Fridge-tag 2E, warm spell without alarm", FRIDGE_TAG, "Fridge-tag",
         "A 6-hour warm spell records minutes above 8 °C but is shorter than the alarm delay.",
         fridgetag_case("heat-no-alarm", "2E", "160600000033", 33),
         expect(family=FRIDGE_TAG, parse="ok", days=60, alarm_days=0, failing_checks=[], notices=[])),
    Case("fridgetag-2e-heat-across-midnight", "Fridge-tag 2E, excursion across midnight", FRIDGE_TAG, "Fridge-tag",
         "One 19-hour excursion runs past midnight, so the alarm lands on the second day.",
         fridgetag_case("heat-across-midnight", "2E", "160600000034", 34),
         expect(family=FRIDGE_TAG, parse="ok", days=60, alarm_days=1, failing_checks=[], notices=[])),
    Case("fridgetag-2l-freeze", "Fridge-tag 2L, freeze alarm", FRIDGE_TAG, "Fridge-tag",
         "A cold dawn twelve days back drops to -1.6 °C and raises a low alarm.",
         fridgetag_case("freeze-event", "2L", "160600000035", 35),
         expect(family=FRIDGE_TAG, parse="ok", days=60, alarm_days=1, failing_checks=[], notices=[])),
    Case("fridgetag-2-unset-clock", "Fridge-tag 2, clock never set", FRIDGE_TAG, "Fridge-tag",
         "The tag's clock was never set, so its dates start in 2000.",
         fridgetag_case("unset-clock", "2", "130400000036", 36),
         expect(family=FRIDGE_TAG, parse="ok", days=60, alarm_days=0, failing_checks=[], notices=["clockUnset"])),
    Case("fridgetag-2e-fahrenheit", "Fridge-tag 2E, Fahrenheit", FRIDGE_TAG, "Fridge-tag",
         "A tag configured for Fahrenheit writes every temperature and limit in °F.",
         fridgetag_case("fahrenheit", "2E", "160600000037", 37),
         expect(family=FRIDGE_TAG, parse="ok", days=60, alarm_days=0, failing_checks=[], notices=[])),
    Case("fridgetag-2e-freezer", "Fridge-tag 2E, freezer limits", FRIDGE_TAG, "Fridge-tag",
         "A freezer tag around -20 °C with limits of -40 °C and -15 °C.",
         fridgetag_case("freezer", "2E", "160600000038", 38),
         expect(family=FRIDGE_TAG, parse="ok", days=60, alarm_days=0, failing_checks=[], notices=[])),
    Case("fridgetag-2e-two-reports", "Fridge-tag 2E, two reports on the drive", FRIDGE_TAG, "Fridge-tag",
         "The drive holds today's report and one from a month ago; the newest should be used.",
         two_reports,
         expect(family=FRIDGE_TAG, parse="ok", days=60, alarm_days=0, failing_checks=[], notices=["multipleReports"])),
    Case("fridgetag-2e-missing-pdf", "Fridge-tag 2E, report without its PDF", FRIDGE_TAG, "Fridge-tag",
         "Only the .txt report is there; the PDF that belongs with it is missing.",
         missing_pdf,
         expect(family=FRIDGE_TAG, parse="ok", days=60, alarm_days=0, failing_checks=[], notices=["missingCompanion"])),

    # EMS
    Case("ems-normal", "EMS, normal", EMS, "EMS",
         "A mains fridge with ordinary door openings and compressor cycling, no alarms.",
         ems_case("normal"),
         expect(family=EMS, parse="ok", days=61, alarm_days=0, failing_checks=[], notices=[])),
    Case("ems-long-history", "EMS, long history", EMS, "EMS",
         "Read 150 days after activation, with two 60-day files in DATA_HISTORY.",
         ems_case("long-history"),
         expect(family=EMS, parse="ok", days=61, alarm_days=0, failing_checks=[], notices=[])),
    Case("ems-power-outage", "EMS, 30-hour power outage", EMS, "EMS",
         "A 30-hour grid outage two days before the read; the chamber warms past +8 °C.",
         ems_case("power-outage"),
         expect(family=EMS, parse="ok", days=61, alarm_days=2, failing_checks=[], notices=[])),
    Case("ems-short-outages", "EMS, short outages", EMS, "EMS",
         "Three short power cuts that the ice lining rides out without an excursion.",
         ems_case("short-outages"),
         expect(family=EMS, parse="ok", days=61, alarm_days=0, failing_checks=[], notices=[])),
    Case("ems-door-left-open", "EMS, door left open", EMS, "EMS",
         "The lid is left ajar for four hours three days before the read.",
         ems_case("door-left-open"),
         expect(family=EMS, parse="ok", days=61, alarm_days=0, failing_checks=[], notices=[])),
    Case("ems-heat-excursion", "EMS, compressor failure", EMS, "EMS",
         "The compressor fails for 36 hours with mains on, raising a heat alarm.",
         ems_case("heat-excursion"),
         expect(family=EMS, parse="ok", days=61, alarm_days=2, failing_checks=[], notices=[])),
    Case("ems-freeze", "EMS, thermostat fault (freeze)", EMS, "EMS",
         "A stuck thermostat runs the compressor for 10 hours and raises a freeze alarm.",
         ems_case("freeze-event"),
         expect(family=EMS, parse="ok", days=61, alarm_days=1, failing_checks=[], notices=[])),
    Case("ems-refrigerant-leak", "EMS, refrigerant leak", EMS, "EMS",
         "Cooling fades over 20 days and the chamber creeps up to a heat alarm.",
         ems_case("refrigerant-leak"),
         expect(family=EMS, parse="ok", days=61, alarm_days=15, failing_checks=[], notices=[])),
    Case("ems-no-history-yet", "EMS, no history yet", EMS, "EMS",
         "Read 50 days after activation, so DATA_HISTORY is still empty.",
         ems_case("no-history-yet"),
         expect(family=EMS, parse="ok", days=51, alarm_days=0, failing_checks=[], notices=[])),

    # Haier
    Case("haier-normal", "Haier HETL-01, normal", HAIER, "Haier",
         "Thirty days in a 2-8 °C fridge with no excursions.",
         haier_case("normal"),
         expect(family=HAIER, parse="ok", days=31, alarm_days=0, failing_checks=[], notices=[])),
    Case("haier-heat-excursion", "Haier HETL-01, heat alarm", HAIER, "Haier",
         "A 17-hour warm spell five days back peaking at +12 °C.",
         haier_case("heat-excursion"),
         expect(family=HAIER, parse="ok", days=31, alarm_days=1, failing_checks=[], notices=[])),
    Case("haier-room-temperature", "Haier HETL-01, left at room temperature", HAIER, "Haier",
         "A logger left out of the fridge at about 22 °C for its whole recording.",
         haier_case("room-temperature"),
         expect(family=HAIER, parse="ok", days=31, alarm_days=31, failing_checks=[], notices=[])),

    # MetaFridge
    Case("metafridge-normal", "MetaFridge CFD-50, normal", METAFRIDGE, "MetaFridge",
         "Sixty days on a solar fridge with no excursions.",
         metafridge_case("normal"),
         expect(family=METAFRIDGE, parse="ok", days=60, alarm_days=0, failing_checks=[], notices=[])),
    Case("metafridge-heat-excursion", "MetaFridge CFD-50, heat alarm", METAFRIDGE, "MetaFridge",
         "A 17-hour warm spell five days back peaking at +12 °C.",
         metafridge_case("heat-excursion"),
         expect(family=METAFRIDGE, parse="ok", days=60, alarm_days=1, failing_checks=[], notices=[])),
    Case("metafridge-legacy-layout", "MetaFridge CFD-50, older firmware", METAFRIDGE, "MetaFridge",
         "The older firmware's 10-column layout with different date and duration formats.",
         metafridge_case("legacy-layout"),
         expect(family=METAFRIDGE, parse="ok", days=60, alarm_days=0, failing_checks=[], notices=[])),

    # Broken files
    Case("fridgetag-2e-truncated", "Fridge-tag 2E, report cut off", FRIDGE_TAG, "Broken files",
         "The .txt report stops part-way through the history, as when the USB is pulled while copying.",
         fridgetag_case("damaged-truncated", "2E", "160600000039", 39),
         expect(family=FRIDGE_TAG, parse="partial", days=33, alarm_days=0, failing_checks=[], notices=["incomplete"])),
    Case("ems-missing-sync", "EMS, SYNC file missing", EMS, "Broken files",
         "The drive has no SYNC file.",
         ems_case("damaged-missing-sync"),
         expect(family=EMS, parse="ok", days=61, alarm_days=0, failing_checks=["files.sync"], notices=[])),
    Case("ems-truncated-json", "EMS, CURRENT_DATA cut off", EMS, "Broken files",
         "CURRENT_DATA stops part-way through a record, so it isn't valid JSON.",
         ems_case("damaged-truncated-json"),
         expect(family=EMS, parse="partial", days=47, alarm_days=0,
                failing_checks=["parsing.BE0H26A1T00LM4K70216EMS_CURRENT_DATA_P75DT2H13M37S.json"],
                notices=["incomplete"])),
    Case("ems-invalid-relt", "EMS, unreadable record times", EMS, "Broken files",
         "Some records carry malformed, impossible or missing relative timestamps.",
         ems_case("damaged-invalid-relt"),
         expect(family=EMS, parse="partial", days=61, alarm_days=0, failing_checks=["records.relt"], notices=[])),
    Case("ems-duplicate-records", "EMS, repeated records", EMS, "Broken files",
         "A run of records appears twice in CURRENT_DATA.",
         ems_case("damaged-duplicate-records"),
         expect(family=EMS, parse="ok", days=61, alarm_days=0, failing_checks=[], notices=[])),
    Case("ems-history-case", "EMS, lower-case history folder", EMS, "Broken files",
         "The history folder is named data_history instead of DATA_HISTORY.",
         ems_case("damaged-history-case"),
         expect(family=EMS, parse="ok", days=61, alarm_days=0, failing_checks=["files.historyFolder"], notices=[])),
    Case("haier-damaged-lines", "Haier HETL-01, damaged lines", HAIER, "Broken files",
         "A few reading lines are corrupted: a wrong year, garbled digits and a cut-off line.",
         haier_case("damaged-lines"),
         expect(family=HAIER, parse="partial", days=31, alarm_days=0, failing_checks=[], notices=[])),
    Case("metafridge-truncated", "MetaFridge CFD-50, report cut off", METAFRIDGE, "Broken files",
         "The CSV stops part-way through the day rows; the PDF is intact.",
         metafridge_case("damaged-truncated"),
         expect(family=METAFRIDGE, parse="partial", days=30, alarm_days=0, failing_checks=[], notices=["incomplete"])),

    # Wrong picks
    Case("wrong-pick-history-folder", "EMS drive's DATA_HISTORY folder", EMS, "Wrong picks",
         "A tester opens the DATA_HISTORY folder instead of choosing the EMS drive itself.",
         history_folder,
         expect(outcome="insideLoggerFolder", failing_checks=["pick.family"]), pick="DATA_HISTORY"),
    Case("wrong-pick-empty-folder", "Empty folder", FRIDGE_TAG, "Wrong picks",
         "A folder with nothing in it, as when the logger isn't plugged in.",
         empty_folder,
         expect(outcome="empty", failing_checks=["pick.family"])),
    Case("wrong-pick-unrelated-files", "Folder of unrelated files", FRIDGE_TAG, "Wrong picks",
         "Photos and a document, but no logger files.",
         unrelated_files,
         expect(outcome="noLoggerFiles", failing_checks=["pick.family"])),
    Case("wrong-pick-one-folder-down", "Logger one folder down", FRIDGE_TAG, "Wrong picks",
         "The Fridge-tag files are inside a subfolder of the folder picked; they should still be found.",
         one_folder_down,
         expect(family=FRIDGE_TAG, parse="ok", days=60, alarm_days=0, failing_checks=[], notices=["foundInSubfolder"])),
]


def _stamp(root):
    """Sets every file and folder below `root` (and `root`) to the fixed library time."""
    for folder, dirs, files in os.walk(root, topdown=False):
        for name in files + dirs:
            os.utime(os.path.join(folder, name), (FILE_TIME, FILE_TIME))
    os.utime(root, (FILE_TIME, FILE_TIME))


def manifest(cases=CASES):
    return {"version": MANIFEST_VERSION, "generator": __version__, "cases": [case.manifest() for case in cases]}


def write(out, cases=CASES):
    """Writes every case into `out` (each case folder is replaced) plus `manifest.json`; returns the manifest."""
    os.makedirs(out, exist_ok=True)
    for case in cases:
        folder = os.path.join(out, case.path)
        if os.path.isdir(folder):
            shutil.rmtree(folder)
        case.build(folder)
        os.makedirs(folder, exist_ok=True)
    data = manifest(cases)
    with open(os.path.join(out, "manifest.json"), "w") as f:
        f.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    _stamp(out)
    return data


def describe(data):
    groups = {}
    for case in data["cases"]:
        groups[case["group"]] = groups.get(case["group"], 0) + 1
    return f"{len(data['cases'])} cases: " + ", ".join(f"{group} {count}" for group, count in groups.items())


def add_arguments(parser):
    parser.add_argument("--out", required=True, help="folder to write the library into (case folders are replaced)")


def run(args):
    print(describe(write(args.out)))
