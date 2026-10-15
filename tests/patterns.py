"""File-name patterns the apps use to recognise logger files.

Copied verbatim from Varo iOS (`Packages/VaroCore/Sources/VaroCore/Import/LoggerFamily.swift`,
matched with NSRegularExpression `firstMatch`, case-insensitive) and Varo Android
(`data/entities/usb/EmsDevice.kt`, Kotlin `Regex.matches`, i.e. a full match, case-insensitive).
Keep them in sync when the apps change.
"""
import re

I = re.IGNORECASE

IOS = {
    "fridgeTag": re.compile(r"^([A-Z0-9-]+)_(\d+)\.txt$", I),
    "metaFridge": re.compile(r"^([A-Z0-9-]+)_\d+_\d+.*\.csv$", I),
    "haier": re.compile(r"^(HE[0-9]+)\.csv$", I),
    "pqsCurrent": re.compile(r"^([^._]*)_CURRENT_DATA_(P[A-Z0-9]+.*)\.json$", I),
    "pqsHistory": re.compile(r"^([^._](?!_CURRENT)[^_]*)_DATA_(P[A-Z0-9]+.*)\.json$", I),
    "pqsSync": re.compile(r"^([^._]*)_SYNC_P[A-Z0-9]+.*\.json$", I),
    "pqsSummaryPdf": re.compile(r"^([^._]*)_60DTR_SUMMARY_P[A-Z0-9]+.*\.pdf$", I),
}
IOS_DATA_FILE = re.compile(r".*\.(csv|pdf|txt|json)$", I)

ANDROID = {
    "BERLINGER_DATA_PATTERN": re.compile(r"([A-Z0-9-]+)_\d+\.txt$", I),
    "AUCMA_DATA_PATTERN": re.compile(r"([A-Z0-9-]+)_\d+_\d+.*\.csv$", I),
    "HAIER_DATA_PATTERN": re.compile(r"^(HE[0-9]+)\.csv$", I),
    "CURRENT_DATA_FILE_PATTERN": re.compile(r"^([^._]*)_CURRENT_DATA_(P[A-Z0-9]+.*)\.json$", I),
    "HISTORY_DATA_FILE_PATTERN": re.compile(r"^([^._](?!_CURRENT)[^_]*)_DATA_(P[A-Z0-9]+.*)\.json$", I),
    "SYNC_DATA_FILE_PATTERN": re.compile(r"^([^._]*)_SYNC_P[A-Z0-9]+.*\.json$", I),
    "PDF_DATA_FILE_PATTERN": re.compile(r"^([^._]*)_60DTR_SUMMARY_P[A-Z0-9]+.*\.pdf$", I),
}
ANDROID_DATA_FILE = re.compile(r".*\.(csv|pdf|txt|json)", I)
HISTORY_FOLDER = "DATA_HISTORY"


def ios_families(name):
    return {family for family, pattern in IOS.items() if pattern.search(name)}


def android_families(name):
    return {family for family, pattern in ANDROID.items() if pattern.fullmatch(name)}
