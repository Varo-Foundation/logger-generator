"""Small helpers shared by the format modules."""
import os
import re

_RELT = re.compile(r"^P(\d+)DT(\d+)H(\d+)M(?:(\d+)S)?$")


def relt(seconds, with_seconds=True):
    """ISO 8601 duration since activation as the loggers write it: `P74DT22H30M` or `P74DT22H30M0S`."""
    d, rest = divmod(int(seconds), 86400)
    h, rest = divmod(rest, 3600)
    m, s = divmod(rest, 60)
    return f"P{d}DT{h}H{m}M{s}S" if with_seconds else f"P{d}DT{h}H{m}M"


def parse_relt(text):
    """Seconds since activation from a `relt()` string; raises ValueError for anything else."""
    match = _RELT.match(text)
    if not match:
        raise ValueError(f"not a relative timestamp: {text!r}")
    d, h, m, s = (int(g or 0) for g in match.groups())
    return ((d * 24 + h) * 60 + m) * 60 + s


def clear(folder, suffixes):
    """Creates `folder` and removes files there ending in `suffixes` (case-insensitive)."""
    os.makedirs(folder, exist_ok=True)
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        if os.path.isfile(path) and name.lower().endswith(suffixes):
            os.remove(path)


def hhmm(minute):
    return f"{minute // 60:02d}:{minute % 60:02d}"


def parse_event(spec):
    """`DAYS_AGO,HH:MM,MINUTES` -> (days_ago, "HH:MM", minutes)."""
    days_ago, start, minutes = spec.split(",")
    return int(days_ago), start, int(minutes)
