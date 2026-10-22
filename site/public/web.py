"""Glue between the page and logger-generator, run in the browser by Pyodide (see worker.js).

Every download is made by the same command-line entry point a user would run, so the
command the page shows reproduces the files byte for byte.
"""
import contextlib
import io
import json
import os
import shutil
import tempfile
import zipfile

from logger_generator import __version__, ems, fridgetag, haier, library, metafridge
from logger_generator.cli import main

FORMATS = [
    ("fridgetag", "Berlinger Fridge-tag 2 / 2E / 2L", "History report .txt and its PDF", fridgetag),
    ("ems", "WHO PQS E006 EMS", "A full drive: CURRENT_DATA, SYNC, DATA_HISTORY and the 60-day summary PDF", ems),
    ("haier", "Haier HETL-01", "The 30-day recorder's CSV export", haier),
    ("metafridge", "Aucma MetaFridge CFD-50 SDD", "The 30 DTR daily report CSV and its PDF", metafridge),
]
SETS = [  # (story or "library", title, description); built once by site/build.sh, not in the browser
    ("format-tour", "Format tour", "One normal download from every logger and model."),
    ("alarm-tour", "Alarm tour", "A heat, freeze, power-cut or door alarm from each kind of logger."),
    ("parser-edge-cases", "Damaged and unusual files",
     "Cut-off reports, corrupted records, missing files and older layouts, for checking that software copes."),
    ("library", "Test library",
     "{cases} cases, each with the result an app should show, plus manifest.json for automated tests."),
]


def catalogue():
    """JSON for the page: the formats with their scenarios, the ready-made sets and the version."""
    return json.dumps({
        "version": __version__,
        "formats": [{"command": command, "name": name, "detail": detail,
                     "scenarios": [{"name": key, "description": text} for key, (text, _) in module.SCENARIOS.items()]}
                    for command, name, detail, module in FORMATS],
        "fridgetagModels": sorted(fridgetag.MODELS),
        "sets": [{"title": title, "description": text.format(cases=len(library.CASES)),
                  "file": f"sets/{_set_folder(name)}.zip", "argv": _set_argv(name), "folder": _set_folder(name)}
                 for name, title, text in SETS],
    })


def _set_argv(name):
    return ["library"] if name == "library" else ["scenario", name]


def _set_folder(name):
    return "test-library" if name == "library" else name


def build_sets(out):
    """Writes every ready-made set as `<out>/<folder>.zip` (run with CPython by site/build.sh)."""
    os.makedirs(out, exist_ok=True)
    for name, _, _ in SETS:
        data, _, zip_name = run(json.dumps(_set_argv(name) + [_set_folder(name)]))
        with open(os.path.join(out, zip_name), "wb") as f:
            f.write(data)
        print(f"{zip_name}: {len(data) // 1024} KB")


def _zip(folder, top):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for root, dirs, files in os.walk(folder):
            dirs.sort()
            for name in sorted(files):
                path = os.path.join(root, name)
                archive.write(path, os.path.join(top, os.path.relpath(path, folder)))
    return buffer.getvalue()


def run(argv_json):
    """Runs `logger-generator <argv> --out <name>`; returns (zip bytes, printed summary, zip name)."""
    argv = json.loads(argv_json)
    name = argv.pop()  # the folder name, also the zip name
    work = tempfile.mkdtemp()
    try:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main(argv + ["--out", os.path.join(work, name)])
        return _zip(os.path.join(work, name), name), out.getvalue().strip(), name + ".zip"
    finally:
        shutil.rmtree(work, ignore_errors=True)
