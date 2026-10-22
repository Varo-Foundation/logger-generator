# logger-generator

Realistic, synthetic cold chain logger downloads for tests, demos and screenshots.

`logger-generator` writes the files a vaccine-refrigerator temperature logger puts on its
USB drive (same file names, folder layout, field order, number formatting and line
endings) from a seeded simulation of a fridge, its door, its power supply and its faults.
It is the shared source of logger fixtures for the Varo apps (iOS and Android) and the
Pogo LT report pipeline, and it is useful to anyone building or testing software that
reads these formats.

- **Deterministic:** the same arguments and seed always give byte-identical files.
- **Self-consistent:** every daily minimum, maximum, mean, alarm minute and alarm flag is
  computed from one underlying simulated series, so the numbers agree with each other the
  way a real device's do.
- **No dependencies:** Python 3.11+ standard library only, PDFs included.
- **Everything is made up.** No real device, facility or person is in this repository; see
  [the public-only rule](#supported-devices-and-the-public-only-rule).

| Command | Writes |
| --- | --- |
| `fridgetag` | Berlinger Fridge-tag 2 / 2E / 2L history report: `<serial>_<yyyyMMddHHmm>.txt` + `.pdf` |
| `ems` | WHO PQS E006 EMS drive: `CURRENT_DATA`, `SYNC`, `DATA_HISTORY/`, `60DTR_SUMMARY` PDF |
| `haier` | Haier HETL-01 30-day temperature recorder export: `HE<serial>.CSV` |
| `metafridge` | Aucma MetaFridge CFD-50 SDD 30 DTR report: `<serial>_<yyyyMMdd>_<yyyyMMdd>.csv` + `.pdf` |
| `scenario` | Curated multi-drive stories (app screenshots, demo drives, parser edge cases, tours) |
| `library` | The [test library](#test-library): 37 cases with the outcome an app should show, plus `manifest.json` |

## Supported devices and the public-only rule

This repository is public, so it only models **publicly available devices**: devices
that are commercially sold and whose download format is public, either documented in a
public specification or visible to anyone who buys the device.

| Format | Why it qualifies |
| --- | --- |
| WHO PQS E006 EMS (generic) | The file layout and fields come from the public WHO PQS E006 specification |
| Berlinger Fridge-tag 2 / 2E / 2L | Commercially sold 30-day recorders; the report is written to the tag's own USB drive |
| Haier HETL-01 and Haier integrated EMS | Commercially sold with PQS-prequalified Haier Biomedical refrigerators |
| Aucma MetaFridge CFD-50 SDD | Commercially sold solar direct-drive refrigerator; its public user manual (section 5.5) describes the USB download, and the CSV is visible to anyone with the fridge |

Not included, and not to be added: prototypes, unreleased hardware and anything under
NDA. Their names, manufacturer strings and model strings must not appear anywhere here,
including in EMS header fields (`AMFR`, `AMOD`, `LMFR`, `LMOD`, `EMFR`, ...); use the
generic or publicly sold makes and models already in the code. A format whose public
status is unclear stays out until it is confirmed.

**Never commit real device data.** No real downloads, serial numbers, facility names,
locations tied to a facility, or people's names, in code, fixtures, docs or commit
messages, not even "anonymised" ones. Calibrate against real downloads on your own machine
and carry over only structure and typical value ranges (see [Calibration](#calibration)).

## Install and run

With [uv](https://docs.astral.sh/uv/), nothing needs installing:

```sh
# Latest main
uvx --from git+https://github.com/Varo-Foundation/logger-generator logger-generator --help

# Pinned to a release (what other projects should do, so their fixtures stay reproducible)
uvx --from git+https://github.com/Varo-Foundation/logger-generator@v0.3.1 \
    logger-generator ems --scenario power-outage --out /tmp/ems
```

From a clone:

```sh
uv run logger-generator --list-scenarios
uv run pytest
```

Or install it as a tool: `uv tool install git+https://github.com/Varo-Foundation/logger-generator@v0.3.1`.
Each module also works as a library (`from logger_generator import fridgetag, ems, haier, metafridge`);
see the module docstrings.

## Commands

Every command takes `--out DIR` (created if needed; files of that format already there
are replaced, other files are left alone), prints a short summary of what it simulated,
and documents its format in `--help`. `logger-generator --list-scenarios` lists every
scenario with a one-line description.

### `fridgetag`

```sh
logger-generator fridgetag --model 2E --days 60 --seed 7 --scenario heat-excursion --out DIR
logger-generator fridgetag --excursion 21,07:30,23:50,11.8 --drift 22:1.3 --out DIR
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--scenario NAME` | `normal` | Preset story (below); the other options adjust it, list options add to it |
| `--model 2\|2E\|2L` | `2E` | Header, firmware and config block of that model |
| `--serial` | `160600000002` | 12-digit serial; also the file name prefix |
| `--created yyyy-mm-ddTHH:MM` | `2026-10-15T09:20` | Report creation; the newest history day |
| `--activated yyyy-mm-ddTHH:MM` | from the seed | `TS Actv` (default 40-200 days before the history) |
| `--days N` | `60` | History length (real tags keep 60) |
| `--seed N` | `1` | Daily wander, door openings, PCB number, check presses, signatures |
| `--base C`, `--swing C` | `4.6`, `0.8` | Typical daily mean and half the normal daily range |
| `--excursion DAYS_AGO,HH:MM,HH:MM,PEAK` | | Push the reading towards `PEAK` °C between two times (an end past `24:00`, e.g. `34:00`, runs into the next day). Repeatable |
| `--drift DAYS_AGO:OFFSET` | | Shift a whole day's baseline (e.g. a cloudy spell on a solar fridge). Repeatable |
| `--low-limit C`, `--low-minutes N` | `-0.5`, `60` | Low alarm: at or below the limit for N minutes in a row |
| `--high-limit C`, `--high-minutes N` | `8.0`, `600` | High alarm: above the limit for N minutes in a row |
| `--unit C\|F` | `C` | Every temperature and limit in that unit (`Temp unit: F`) |
| `--unset-clock` | off | The clock was never set: dates count from 2000-01-01 at activation |
| `--error CODE,COUNT,YYYY-MM-DD HH:MM` | | An entry in the `Errors:` block. Repeatable |

### `ems`

```sh
logger-generator ems --scenario power-outage --seed 3 --out DIR
logger-generator ems --outage 4,15:10,960 --lid-ajar 23,11:05,40 --door busy --out DIR
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--scenario NAME` | `normal` | Preset story (below); event options add to it |
| `--seed N` | `26` | Ambient noise, weather, door openings, mains voltage |
| `--appliance-serial` | `BE0H26A1T00LM4K70216` | `ASER`/`ESER`; the logger serial `LSER` appends `EMS` |
| `--read-at yyyy-mm-ddTHH:MM` | `2026-10-15T09:20` | Wall clock of the read, for the day/night and clinic-hours cycle only |
| `--active-days N` | `75` | Days since activation; each completed 60 days becomes a `DATA_HISTORY` file |
| `--door PATTERN` | `normal` | `best-practice`, `normal`, `frequent-short`, `busy`, `few-but-long` |
| `--ambient C` | `21.5` | Mean indoor ambient |
| `--outage DAYS_AGO,HH:MM,MINUTES` | | Grid power cut. Repeatable |
| `--lid-ajar DAYS_AGO,HH:MM,MINUTES` | | Lid or door left open. Repeatable |
| `--compressor-failure DAYS_AGO,HH:MM,MINUTES` | | Compressor can't run while mains stays on. Repeatable |
| `--thermostat-fault DAYS_AGO,HH:MM,MINUTES` | | Compressor stuck on with a subcooled lining. Repeatable |
| `--leak DAYS_AGO[,RATE]` | | Refrigerant leak: cooling capacity × exp(−RATE × hours), default 0.01/h |
| `--header KEY=VALUE` | | Override a header field (e.g. `LSV=v01.03.000`). Repeatable |
| `--compact` | off | Minified JSON instead of the logger's cJSON print layout |

### `haier`

```sh
logger-generator haier --scenario heat-excursion --seed 4 --out DIR
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--scenario NAME` | `normal` | Preset story (below) |
| `--serial` | `HE09900000001` | `HE` + digits; also the file name |
| `--read-at yyyy-mm-ddTHH:MM:SS` | `2026-10-15T09:20:00` | Time of the read (the last reading is at or before it) |
| `--days N` | `30` | Days of readings (the logger holds 8192, about 34 days at 6 minutes) |
| `--seed N` | `1` | Series and the start time's seconds |
| `--base C`, `--swing C`, `--excursion` | `4.6`, `0.8` | As for `fridgetag` |
| `--interval MIN` | `6` | Record interval |

### `metafridge`

```sh
logger-generator metafridge --scenario heat-excursion --seed 4 --out DIR
logger-generator metafridge --active-days 28 --drift 8:1.5 --out DIR
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--scenario NAME` | `normal` | Preset story (below) |
| `--serial` | `99S-0001` | Fridge serial (the last 7 characters); also the file name prefix |
| `--created yyyy-mm-ddTHH:MM:SS` | `2026-10-15T09:20:00` | Report creation; row `01` is that day up to this time |
| `--days N` | `60` | Day rows in the report window |
| `--active-days N` | all | Days with readings; earlier rows keep their number and date with blank cells |
| `--seed N` | `1` | Series, door seconds, holdover and power figures |
| `--base C`, `--swing C`, `--excursion`, `--drift` | `4.6`, `0.8` | As for `fridgetag` |
| `--legacy` | off | The older firmware's 10-column layout |

### `scenario`

```sh
logger-generator scenario screenshot-story --out DIR
logger-generator scenario --list          # same as logger-generator --list-scenarios
```

Curated stories take only `--out`; stories with several drives write one subfolder each.

## Scenario catalogue

### Fridge-tag (`fridgetag --scenario`)

| Name | What it shows |
| --- | --- |
| `normal` | A 2-8 °C vaccine fridge, no excursions |
| `heat-excursion` | A 17 h warm spell 5 days back peaking at +12 °C: high alarm (`TS A`) that day |
| `heat-no-alarm` | A 6 h warm spell: `t Acc` minutes but shorter than the alarm delay, so no `TS A` |
| `heat-across-midnight` | One 19 h excursion from 15:00 to 10:00 the next day: the first day gets `t Acc` only; the alarm triggers early on the second day from the run that began the day before |
| `freeze-event` | A cold dawn down to −1.6 °C: low alarm after 60 min at or below −0.5 °C |
| `cloudy-week` | A solar fridge's cloudy spell: baselines drift up to +1.5 °C for three days, no alarm |
| `unset-clock` | The clock was never set: every date, and the file name, counts from 2000-01-01 at activation |
| `freezer` | A freezer tag around −20 °C with limits −40 °C (60 min) and −15 °C (600 min) |
| `fahrenheit` | Configured for Fahrenheit: every temperature and limit in °F |
| `damaged-truncated` | The `.txt` cut off part-way through the history (USB pulled while copying) |

### EMS (`ems --scenario`)

| Name | What it shows |
| --- | --- |
| `normal` | Ordinary door openings and compressor cycling, no alarms |
| `power-outage` | A 30 h grid outage 2 days before the read: `POWR` throughout, `HEAT` after 10 h above +8 °C |
| `short-outages` | Cuts of 80, 40 and 25 minutes: `POWR` records, the ice lining keeps the chamber in range |
| `door-left-open` | The lid left ajar for 4 hours: `DOOR` while open, the chamber warms |
| `heat-excursion` | The compressor fails for 36 h with mains on (no `POWR`): `HEAT` |
| `freeze-event` | A thermostat fault runs the compressor for 10 h on a subcooled lining: `FRZE` |
| `refrigerant-leak` | Cooling capacity decays from 20 days back; duty rises until the chamber reaches `HEAT` |
| `busy-clinic` | 16+ door openings a day over long hours |
| `few-but-long` | Doors left open for minutes at a time: `DOOR` alarms and warm spikes |
| `no-history-yet` | Read 50 days after activation: `DATA_HISTORY` exists but is empty |
| `long-history` | Read 150 days after activation: two `DATA_HISTORY` files |
| `damaged-truncated-json` | `CURRENT_DATA` cut off mid-record (invalid JSON) |
| `damaged-invalid-relt` | Records with `P74DT25H0M` (hour 25), `PXDT1H`, an empty and a missing `RELT` |
| `damaged-duplicate-records` | Four records repeated in a row in `CURRENT_DATA` (same `RELT` twice) |
| `damaged-missing-sync` | No `SYNC` file |
| `damaged-history-case` | The history folder is `data_history` instead of `DATA_HISTORY` |

### Haier (`haier --scenario`)

| Name | What it shows |
| --- | --- |
| `normal` | In a 2-8 °C fridge: `Alarm State: Normal` |
| `heat-excursion` | A 17 h warm spell peaking at +12 °C: `High Alarm` |
| `freeze-event` | A cold dawn down to −1.6 °C: `Low Alarm` |
| `room-temperature` | A logger left out of the fridge (about 22 °C): `High Alarm` |
| `damaged-lines` | Three corrupted reading lines (year 2225, a garbled `2..9`, a cut-off line) among good ones |

### MetaFridge (`metafridge --scenario`)

| Name | What it shows |
| --- | --- |
| `normal` | A 2-8 °C solar fridge, no excursions |
| `heat-excursion` | A 17 h warm spell 5 days back peaking at +12 °C: `ALARM` with time above limit that day |
| `freeze-event` | A cold dawn 12 days back down to −1.6 °C: `ALARM` with time below limit that day |
| `cloudy-week` | A cloudy spell: baselines drift up to +1.5 °C for three days, lower Power Good and holdover, no alarm |
| `recently-installed` | Installed 28 days before the report: rows 29-60 have a date and blank cells |
| `not-cooling` | Switched off at room temperature (about 22 °C): `ALARM` all day every day, Power Good `0.0`, no holdover |
| `legacy-layout` | The older firmware layout: no BOM, LF, 10 comma-padded columns, blank serial, `M/d/yyyy` dates, `h:mm` and `24:00:00` durations |
| `damaged-truncated` | The CSV cut off part-way through the rows; the PDF is intact |

### Curated stories (`scenario NAME`)

| Name | Writes |
| --- | --- |
| `screenshot-story` | `FridgeTag/` (a Fridge-tag 2E with a heat alarm in a cloudy spell, a warm day without alarm and a freeze alarm), `FridgeTagPast/` (an older, clean Fridge-tag 2), `EMS/` (a Haier HBC-260 drive with three outages, one raising `HEAT`, and a lid ajar). The Varo App Store screenshots use it |
| `demo-ems` | One drive (`SAMPLE-EMS-0001`) from a simpler first-order model: 60 days, one short cut, placeholder summary PDF |
| `demo-ems-alarm` | The same fridge (`SAMPLE-EMS-0002`) with `HEAT`, `FRZE`, `DOOR` and `POWR` |
| `parser-edge-cases` | Every damaged variant above, plus an unset-clock and a Fahrenheit Fridge-tag and a legacy-layout and a recently installed MetaFridge, one folder each |
| `format-tour` | One normal download of every format: Fridge-tag 2, 2E, 2L, EMS, Haier, MetaFridge |
| `alarm-tour` | Fridge-tag heat and freeze, EMS power outage, door and freeze, Haier heat, MetaFridge heat and freeze |

## Test library

```sh
logger-generator library --out DIR
```

A curated set of test cases for apps that read these formats, one folder per case laid out
like the logger's drive, and `manifest.json` at the root describing each case and the
outcome an app should show for it. It covers normal downloads and alarms for every format,
damaged files, and picks that aren't a logger drive. The Varo iOS app bundles it (debug
console, "Test data library") and runs every case through its import path as a regression
test; other projects can use it the same way, or copy the folders onto a thumb drive.

| Group | Cases |
| --- | --- |
| Fridge-tag | 2E normal, heat alarm, warm spell without alarm, excursion across midnight; 2L freeze; 2 with an unset clock; 2E in Fahrenheit, with freezer limits, with two reports on the drive, and without its PDF |
| EMS | Normal, long history (two `DATA_HISTORY` files), 30-hour power outage, short outages, door left open, compressor failure (heat), thermostat fault (freeze), refrigerant leak, no history yet |
| Haier | Normal, heat alarm, left at room temperature |
| MetaFridge | Normal, heat alarm, older firmware layout |
| Broken files | Fridge-tag and MetaFridge reports cut off; EMS without SYNC, with CURRENT_DATA cut off, with unreadable record times, with repeated records, with a lower-case `data_history`; Haier with damaged lines |
| Wrong picks | An EMS drive's `DATA_HISTORY` folder, an empty folder, a folder of unrelated files, and a logger one folder down (which should still be found) |

`manifest.json`:

```json
{
  "version": 1,
  "generator": "0.3.0",
  "cases": [
    {
      "id": "fridgetag-2e-two-reports",
      "title": "Fridge-tag 2E, two reports on the drive",
      "family": "fridgeTag",
      "group": "Fridge-tag",
      "description": "The drive holds today's report and one from a month ago; the newest should be used.",
      "path": "fridgetag-2e-two-reports",
      "pickPath": "fridgetag-2e-two-reports",
      "readAt": "2026-10-15T09:20:00",
      "expect": {
        "outcome": "recognized", "family": "fridgeTag", "parse": "ok", "days": 60, "alarmDays": 0,
        "failingChecks": [], "notices": ["multipleReports"]
      }
    }
  ]
}
```

| Field | Meaning |
| --- | --- |
| `family` | The logger in the case: `fridgeTag`, `pqsEms`, `haier` or `metaFridge` (also set for wrong picks, where it names the drive the folder came from) |
| `path`, `pickPath` | The case folder, and the folder a tester should pick (relative to the library root). They differ only for picks of a folder inside a drive, e.g. `wrong-pick-history-folder/DATA_HISTORY` |
| `readAt` | Local wall-clock time the case was read. Every case uses 2026-10-15 09:20, and every file and folder carries that modification time |
| `expect.outcome` | `recognized`, `insideLoggerFolder` (a folder inside a logger drive), `noLoggerFiles` or `empty` |
| `expect.parse` | `ok`; `partial` (read, but part of it was unusable: a report that ends early, a data file that didn't parse, damaged lines or records); `failed` |
| `expect.days`, `expect.alarmDays` | Days recorded and days with a temperature alarm, as the import summary shows them, for a read at `readAt` in the device's time zone |
| `expect.failingChecks` | Ids of the import checks that fail (Varo's `ImportChecks` and, for EMS drives, the PQS E006 rules in `EmsValidator`). Checks about the drive itself (file system, removable or not) and the data's age are left out |
| `expect.notices` | Notices on the import summary, by Varo's `ImportNotice.Kind`: `unreadableData`, `incomplete`, `duplicate`, `foundInSubfolder`, `missingCompanion`, `multipleReports`, `clockUnset` |

Any `expect` field can be `null`, meaning "don't check"; wrong picks leave the fields that
only apply to a recognized logger null. Expectations are only recorded for stable results.

**Import library cases like a bundled sample.** Read each case as test data at its
`readAt` rather than at the current time: EMS records carry only times relative to the
read, so their day and alarm counts depend on it, and a case's age or its place on the
phone's storage should never raise "old report" or "copy on this phone" notices (those are
not in any `expect`).

**Adding a case:** add a `Case` to `CASES` in `src/logger_generator/library.py` (an id, title,
family, group, one-sentence description, a builder that writes the folder, and `expect`;
`pick=` for a subfolder pick). Generate the library, run it through the Varo iOS import
path to get the values (`VARO_CORPUS_NOW=2026-10-15T09:20:00 scripts/check-device-corpus.sh
DIR` prints family, parse result, days, alarm days and failing checks per folder; its
library self-test reports notices too), fill in `expect`, then refresh the golden hashes
with `UPDATE_GOLDEN=1 uv run pytest tests/test_library.py`.

## Format reference

### Berlinger Fridge-tag 2 / 2E / 2L

Files: `<serial>_<yyyyMMddHHmm>.txt` (the tag's clock at report creation) beside a PDF with
the same base name, in the root of the tag's drive.

- ASCII, **CRLF** line endings, a key/value outline indented with single spaces. Several
  `key: value` pairs can share a line, separated by `, ` (`Min T: +3.1, TS Min T: 03:52`).
- Temperatures carry an explicit sign and one decimal (`+4.6`, `-0.5`); times inside a day
  are `HH:MM`, dates `yyyy-mm-dd`, timestamps `yyyy-mm-dd HH:MM`, all zoneless local time.
- Order: `Device`, `Vers`, `Fw Vers`, `Sensor` (2L adds `Ext Sensor: 1`), then `Conf:`
  (`Serial`, `PCB`, `CID`, `Lot`, `Zone`, `Measurement delay`, `Moving Avrg`, `User Alarm
  Config`, `User Clock Config` on 2E/2L, `Alarm Indication`, `Temp unit`, `Alarm:` with `0:`
  low and `1:` high limits as `T AL` / `t AL` (minutes), the 2L's `Ext Sensor:` block, `Int
  Sensor:` timeout and offset, `Report history length`, `Det Report`, `Use ext devices`,
  `Test Res` / `Test TS`), optional `Errors:` (code, `Err Count`, `Err TS`), `Hist:` (`TS
  Actv`, `TS Report Creation`, then one block per day, `1:` being the newest), and finally
  `Cert:`, `Sig Cert`, `Sig`.
- Each day: `Date`, `Min T` / `TS Min T`, `Max T` / `TS Max T`, `Avrg T`, `Alarm:` with
  `0:` and `1:`, `Int Sensor timeout:` (2L also `Ext Sensor timeout:`), `Events` and, after
  a check-button press, `Checked:` with `TS AM` or `TS PM`.
- **Alarm semantics.** `t Acc` is the minutes that day beyond the limit, counting every
  excursion. `TS A` (when the alarm triggered) and `C A` appear only on a day the alarm
  triggered, i.e. when one continuous excursion reached the configured duration, even if
  it started the day before. A day that begins inside an already-triggered excursion shows
  `TS A: 00:00`. A shorter excursion gets `t Acc` but no `TS A`. High means above the
  limit, low means at or below it.
- Models: 2 (`Fw Vers: 3.2p0o`, no `User Clock Config`, short CID), 2E (`3.4p0o`, `User
  Clock Config: 1`, 8-digit CID), 2L (a 2E with the external-probe fields).
- A tag whose clock was never set writes 2000-era dates, file name included.
- The PDF is a one-page summary (chart and table of every day). Apps only check that it is
  present; it is not a copy of the manufacturer's layout.

### WHO PQS E006 EMS

Drive root: `<LSER>_CURRENT_DATA_<RELT>.json`, `<LSER>_SYNC_<RELT>.json` and
`<LSER>_60DTR_SUMMARY_<RELT>.pdf`, all with the read's relative time including seconds
(`P75DT2H13M37S`), plus `DATA_HISTORY/<LSER>_DATA_<RELT>.json` per completed 60-day block,
named with the block's end (`P60DT0H0M`). Apps expect at most 10 root items, exactly one of
each root file, and that folder name.

- Each file is one JSON object: header fields, then `records`. Header: appliance (`ACAT`
  category, `ADOP` date of placement, `AMFR`, `AMOD`, `APQS` PQS code, `ASER` serial),
  compressor (`CNAM`, `CSER`), logger (`LDOP`, `LMFR`, `LMOD`, `LPQS`, `LSER`, `LSV`
  software version) and EMS (`EDOP`, `EMFR`, `EMOD`, `EPQS`, `ESER`, `EMSV`).
- The default output is printed the way the logger's cJSON library does: tab indents,
  `"key":<TAB>value`, `},{` between records, LF line endings, no trailing newline. The
  demo drives (and `--compact`) are minified. Parsers must accept both.
- Records every 15 minutes on the activation grid. `RELT` is the ISO 8601 duration since
  activation (`P74DT22H30M`); apps date records from the moment the drive is read, so the
  data always looks current.
- Record fields: `TVC` vaccine chamber °C, `TAMB` ambient °C, `SVA` seconds with mains
  power in the interval, `ACSV` mains voltage (0 without power), `ACCD` current, `CMPR`
  compressor run seconds, `DORV` door-open seconds, `DRCV` door openings, `BLOG` / `BEMD`
  logger and EMS battery voltages, `RTCW` clock drift, `ALRM` (space-separated alarms or
  `null`). The demo drives also write `HOLD` (holdover days) and `LERR` (error text).
- **Alarm rules:** `HEAT` once `TVC` has been above +8 °C for 10 hours, `FRZE` once at or
  below −0.5 °C for 60 minutes, `DOOR` when the door stayed open 5 minutes in a row, `POWR`
  for any interval with mains missing. Alarms stay set on every record while the condition
  lasts.
- `SYNC` holds two records: a reading at the read time (`IDRV`, `RELT` with seconds,
  `RTCW`, `TVC`) and a copy of the newest record.
- The summary PDF shows the last 60 days (daily min, mean and max and the alarm days).

### Haier HETL-01

One file, `HE<serial>.CSV` (upper-case extension), CRLF line endings:

```text
Note: All temperature are in degree ceslsius        (sic)

Device Information
****************************************
Device:HETL-01
Version: V1.0
Serial Number:HE09900000001
Record Interval:  6 min
Start Delay: 30 min
Alarm Temperature High: +8  Delay 10 h
Alarm Temperature Low: -0.5 Delay 1 h
Alarm State: Normal

Recorded Temperature
****************************************
MM.DD.YYYY  HH:MM:SS   T
09.15.2026  09:50:13  4.8
```

- Readings oldest first, one per record interval from the start (after the start delay)
  to the read, `MM.DD.YYYY  HH:MM:SS  T` with T in °C to one decimal.
- `Alarm State` is `High Alarm` once a run above the high limit lasted its delay, `Low Alarm`
  for a run at or below the low limit, otherwise `Normal`.

### Aucma MetaFridge CFD-50 SDD

The fridge's drive holds the newest 30 DTR report as CSV and PDF in its top level, named
`<serial>_<yyyyMMdd>_<yyyyMMdd>.csv` (the last 7 characters of the fridge serial, then the
first and last day of the report window); older reports sit in subfolders (not modelled).

```text
CFD50 30 DTR REPORT                                 (UTF-8 BOM, CRLF)
Fridge Serial Number:, ,99S-0001
Report Creation Date:, ,2026-10-15
Report Creation Time:, ,09:20:00
DayNum,Date,Average Temperature (°C),Status,Minimum Temperature (°C),Total Time Below Limit (hh:mm),Total Low Alarm Time (hh:mm),Maximum Temperature (°C),Total Time Above Limit (hh:mm),Total High Alarm Time (hh:mm),Door Open Time (seconds),Min Holdover (days),Power Good (%),Faults
01,2026-10-15,4.8,OK,4.1,00:00,00:00,5.6,00:00,00:00,74,4.4,46.5,0
...
60,2026-08-17, , , , , , , , , , , ,
```

- One row per day of the window, newest first; `01` is the report day up to the creation
  time. Days before installation keep their number and date with every other cell blank.
- Temperatures in °C to one decimal; durations `hh:mm`, a whole day `24:00`.
- Time below/above limit counts minutes below +2 °C and above +8 °C; the alarm time equals
  it, and `Status` is `ALARM` on a day with any alarm time. Door, holdover and power figures
  are illustrative, and fault codes are always `0`.
- Older firmware: no BOM, LF line endings, every line padded with commas to 10 columns, a
  blank serial, unpadded day numbers, `M/d/yyyy` dates, `h:mm` durations, `24:00:00` for a
  whole day, and only the first ten columns.
- The PDF is a one-page summary (chart and table of every day with readings). Apps only
  check that it is present; it is not a copy of the manufacturer's layout.

## How it simulates

- **Fridge-tag, Haier and MetaFridge:** one reading per minute: a daily cosine around the base
  temperature, a slow day-to-day wander, short warm bumps for door openings in clinic hours,
  then the excursions (a smooth warm-up, a broad top and a pull-down) and baseline drifts.
  Days and alarms are summarized from that series.
- **EMS:** a two-node chamber (the air the probe reads and the bulk contents) with an ice
  bank at 0 °C, integrated in 10-second steps. The compressor cycles on the ice bank's
  charge; the air-to-ice coupling weakens as the lining melts. Ambient is a daily cosine
  with noise and weather drift. Door openings are a Poisson process in clinic hours, with
  presets tuned to span what deployed fleets show, from well-run clinics to doors left open.
  Faults are injected on top: outages, a lid ajar, compressor failure, a stuck thermostat
  and a refrigerant leak.
- Constants are on the `Thermal` class in `ems.py` and the `Story` dataclasses.

## Using it from other projects

Pin a release tag and regenerate fixtures with a script committed next to them, so anyone
can reproduce them and a format change is one tag bump away.

- **Varo iOS** regenerates every bundled sample with `scripts/generate-samples.sh`, which
  calls `uvx --from git+https://github.com/Varo-Foundation/logger-generator@v0.3.1
  logger-generator scenario ...` for the demo drives and the screenshot story, and bundles
  the test library (`logger-generator library`) as its regression suite.
- **Varo Android** tests: generate into the test resources, e.g.
  `logger-generator scenario parser-edge-cases --out app/src/test/resources/generated`,
  and commit the files with the command that made them.
- **Pogo LT silver harness:** generate the logger files for a fixture folder (`ems`,
  `fridgetag`, `haier`, `metafridge`), add the Varo metadata JSON and `expected.json` the harness needs,
  and record the generator command and tag in the fixture's notes.
- **Anything else:** `uvx --from git+https://github.com/Varo-Foundation/logger-generator@v0.3.1
  logger-generator format-or-scenario ... --out your/fixtures`. Loop over seeds for variety.

Output only changes in a release that says so; the golden tests guard this.

## Calibration

Formats and value ranges were checked against real downloads (Fridge-tag 2E reports with
and without alarms, and E006 EMS drives from several loggers including Haier's integrated
EMS). The MetaFridge layouts follow the CSV files the Varo apps' parsers were built and
tested against, in both firmware layouts; its door, holdover and power values are less
well calibrated than the temperatures. Those downloads stayed on a local machine and nothing from them is here. What was
carried over is structural: field order and spelling, number formatting, line endings,
file naming, alarm bookkeeping, record cadence, header field sets, and typical
temperature, ambient, voltage and duty-cycle ranges.

## Adding a format or scenario

- **A scenario for an existing format:** add an entry to that module's `SCENARIOS` (a
  description and the story fields it sets; a `damage` step for broken variants), a test
  that checks what the scenario promises, and a row in the catalogue above.
- **A curated story:** a function in `scenarios.py` whose docstring's first paragraph is its
  summary, registered in `STORIES`.
- **A new format:** confirm it qualifies under the public-only rule first. Then add a
  module with a docstring describing the format, a `Story` dataclass, `write(story,
  folder)`, `describe(...)`, `SCENARIOS`, `add_arguments(parser)` and `run(args)`; register
  it in `cli.py`; add format-invariant tests (including the apps' file-name patterns in
  `tests/patterns.py`), a format reference section here, and golden hashes.
- **Changed output:** run `UPDATE_GOLDEN=1 uv run pytest tests/test_golden.py`, and say in
  the commit and release notes which output changed and why.

## Website

[sample-loggers.varofoundation.org](https://sample-loggers.varofoundation.org) offers the same
generator to people who don't use the command line: pick a logger and a scenario and download a
zip, freshly seeded each time, with the command that reproduces it. It is a static site in
`site/` that runs this package in the browser with [Pyodide](https://pyodide.org), so the page
and the command line can't drift apart; the ready-made sets are built once per release.

```sh
site/build.sh                     # the wheel and the ready-made sets, into site/public
# serve site/public with any static file server to preview
(cd site && npm install --no-save pyodide@314.0.7 && node check.mjs)   # site == CLI, byte for byte
```

The `Site` workflow deploys it to Cloudflare from release tags (`site/wrangler.jsonc`).

## Contributing

- Commit straight to `main` in small, logical commits; keep `uv run pytest` green (CI runs
  it on every push).
- Keep the package dependency-free and output deterministic: seed every random draw, never
  use the current time, and sum floats with `math.fsum` (plain `sum()` rounds differently
  from Python 3.12 on).
- Follow the public-only rule and never commit real device data.
- Releases are tagged `vX.Y.Z` with notes listing any changed output.

## License

MIT, see [LICENSE](LICENSE).
