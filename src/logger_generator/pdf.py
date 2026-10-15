"""Dependency-free one-page PDFs: the Fridge-tag history report, the EMS 60-day summary and
a text-only placeholder.

The PDFs use the standard Type 1 fonts (Helvetica, Helvetica-Bold) with WinAnsiEncoding, so
nothing is embedded and the files stay small and byte-for-byte reproducible. Parsers only
check that these files exist and how they are named; the drawing is for people looking at a
sample.
"""
import math

PRODUCER = "logger-generator"


def _pdf_text(text):
    """Escapes PDF string syntax; with WinAnsiEncoding the degree sign is octal 260."""
    return (text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            .replace("\u00b0", "\\260").replace("\u2264", "<="))


def build_pdf(content, fonts):
    """A one-page Letter PDF from a raw content stream and {resource name: base font}."""
    stream = content.encode("latin-1")
    font_refs = " ".join(f"/{name} {6 + i} 0 R" for i, name in enumerate(fonts))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R"
        b" /Resources << /Font << " + font_refs.encode() + b" >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Producer (%s) >>" % PRODUCER.encode(),
    ] + [b"<< /Type /Font /Subtype /Type1 /BaseFont /%s /Encoding /WinAnsiEncoding >>" % base.encode()
         for base in fonts.values()]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R /Info 5 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


def placeholder_pdf(path, lines):
    """A text-only page: `lines` are (font size, text) pairs from the top."""
    text, y = [], 760
    for size, line in lines:
        text.append(f"BT /F1 {size} Tf 72 {y} Td ({_pdf_text(line)}) Tj ET")
        y -= size + 14
    stream = "\n".join(text).encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R"
        b" /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    with open(path, "wb") as f:
        f.write(out)


def summary_report_pdf(path, title, subtitle, info, days, serial, footnote):
    """One page: title, label/value pairs, a daily min/mean/max chart over the 2-8 C band and a
    table of every day. `days` are dicts with date, min, max, mean, low/high (minutes, alarm)."""
    ops = []

    def text(x, y, value, size=8, font="F1", gray=0.0):
        ops.append(f"{gray:.2f} g BT /{font} {size} Tf {x:.1f} {y:.1f} Td ({_pdf_text(value)}) Tj ET")

    def line(x1, y1, x2, y2, width=0.5, rgb=(0, 0, 0), dash=""):
        ops.append(f"{rgb[0]:.2f} {rgb[1]:.2f} {rgb[2]:.2f} RG {width} w [{dash}] 0 d {x1:.1f} {y1:.1f} m {x2:.1f} {y2:.1f} l S")

    text(50, 750, title, 16, "F2")
    text(50, 734, subtitle, 9, gray=0.35)
    for i, (label, value) in enumerate(info):
        x, y = 50 + (i % 2) * 260, 712 - (i // 2) * 14
        text(x, y, label, 8, gray=0.35)
        text(x + 84, y, value, 8, "F2")
    alarm_days = [d for d in days if d["low"][1] or d["high"][1]]
    lowest, highest = min(d["min"] for d in days), max(d["max"] for d in days)
    summary = (f"{len(days)} days recorded, {len(alarm_days)} with an alarm. "
               f"Lowest {lowest:+.1f} \u00b0C, highest {highest:+.1f} \u00b0C.")
    text(50, 664, summary, 9, "F2" if alarm_days else "F1")
    line(50, 654, 562, 654, 0.6, (0.6, 0.6, 0.6))

    # Chart of daily min/mean/max.
    left, right, bottom, top = 78, 562, 430, 630
    lo = min(-2, math.floor(lowest) - 1)
    hi = max(12, math.ceil(highest) + 1)

    def ty(v):
        return bottom + (v - lo) / (hi - lo) * (top - bottom)

    def tx(i):
        return left + (i + 0.5) / len(days) * (right - left)

    ops.append(f"0.92 0.97 0.92 rg {left} {ty(2):.1f} {right - left} {ty(8) - ty(2):.1f} re f")
    step = 2 if hi - lo <= 16 else 5
    for v in range(lo, hi + 1):
        if v % step == 0:
            line(left, ty(v), right, ty(v), 0.25, (0.82, 0.82, 0.82))
            text(left - 22, ty(v) - 2.5, f"{v:+d}" if v else "0", 7, gray=0.35)
    line(left, ty(8), right, ty(8), 0.8, (0.85, 0.2, 0.15), "3 2")
    line(left, ty(2), right, ty(2), 0.8, (0.15, 0.35, 0.85), "3 2")
    text(right - 34, ty(8) + 3, "+8.0 \u00b0C", 6.5, gray=0.3)
    text(right - 34, ty(2) - 9, "+2.0 \u00b0C", 6.5, gray=0.3)
    for key, rgb, width in (("max", (0.85, 0.2, 0.15), 1.0), ("mean", (0.1, 0.1, 0.1), 1.2),
                            ("min", (0.15, 0.35, 0.85), 1.0)):
        points = " ".join(f"{tx(i):.1f} {ty(d[key]):.1f} {'m' if i == 0 else 'l'}" for i, d in enumerate(days))
        ops.append(f"{rgb[0]} {rgb[1]} {rgb[2]} RG {width} w [] 0 d 1 j {points} S")
    for i, d in enumerate(days):
        if d["high"][1] or d["low"][1]:
            v = d["max"] if d["high"][1] else d["min"]
            x, y = tx(i), ty(v) + (6 if d["high"][1] else -6)
            ops.append(f"0.85 0.2 0.15 rg {x - 3:.1f} {y - 2.5:.1f} m {x + 3:.1f} {y - 2.5:.1f} l {x:.1f} {y + 3:.1f} l f")
        if i % 10 == 0 or i == len(days) - 1:
            line(tx(i), bottom, tx(i), bottom - 3, 0.5, (0.4, 0.4, 0.4))
            text(tx(i) - 14, bottom - 12, d["date"].strftime("%d %b"), 6.5, gray=0.35)
    ops.append(f"0.4 0.4 0.4 RG 0.6 w [] 0 d {left} {bottom} {right - left} {top - bottom} re S")
    text(left - 22, top + 8, "\u00b0C", 7, gray=0.35)
    for i, (label, rgb) in enumerate((("Maximum", (0.85, 0.2, 0.15)), ("Mean", (0.1, 0.1, 0.1)),
                                      ("Minimum", (0.15, 0.35, 0.85)))):
        x = left + i * 80
        line(x, 404, x + 16, 404, 1.2, rgb)
        text(x + 20, 401.5, label, 7)

    # Table of every day, newest first, in three columns.
    headers = ["Date", "Min", "Max", "Mean", "Low", "High"]
    offsets = [0, 46, 72, 98, 124, 146]
    rows = list(reversed(days))
    per_column = math.ceil(len(rows) / 3)
    for column in range(3):
        x0 = 50 + column * 172
        for h, o in zip(headers, offsets):
            text(x0 + o, 380, h, 6.5, "F2")
        line(x0, 376, x0 + 166, 376, 0.4, (0.5, 0.5, 0.5))
        for r, d in enumerate(rows[column * per_column:(column + 1) * per_column]):
            y = 367 - r * 10.6
            alarm = d["high"][1] or d["low"][1]
            if alarm:
                ops.append(f"0.99 0.88 0.86 rg {x0 - 2} {y - 2.6:.1f} 170 9.6 re f")
            cells = [d["date"].strftime("%Y-%m-%d"), f"{d['min']:+.1f}", f"{d['max']:+.1f}", f"{d['mean']:+.1f}",
                     str(d["low"][0]), str(d["high"][0])]
            for c, o in zip(cells, offsets):
                text(x0 + o, y, c, 6.5, "F2" if alarm else "F1")
    text(50, 40, footnote, 6.5, gray=0.4)
    text(452, 40, f"{serial}  page 1/1", 6.5, gray=0.4)

    with open(path, "wb") as f:
        f.write(build_pdf("\n".join(ops), {"F1": "Helvetica", "F2": "Helvetica-Bold"}))
