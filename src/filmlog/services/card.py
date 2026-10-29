"""HTML for the printable "darkroom card" of a roll (rendered to PDF by the UI)."""

from __future__ import annotations

from html import escape

from filmlog.db.models import Chemical, Roll
from filmlog.services.prints import contrast_summary, total_exposure
from filmlog.services.pushpull import badge_text
from filmlog.services.timefmt import format_duration, format_seconds
from filmlog.services.units import format_temp, to_display_length

CSS = """
body { font-family: sans-serif; font-size: 10pt; color: #111; }
h1 { font-size: 18pt; margin: 0 0 2pt 0; }
h2 { font-size: 12pt; margin: 14pt 0 4pt 0; border-bottom: 1px solid #888; }
h3 { font-size: 10.5pt; margin: 10pt 0 2pt 0; }
table.kv td { padding: 1pt 10pt 1pt 0; vertical-align: top; }
table.kv td.k { color: #555; white-space: nowrap; }
table.grid { border-collapse: collapse; margin-top: 2pt; }
table.grid th, table.grid td { border: 1px solid #999; padding: 2pt 5pt; text-align: left; }
table.grid th { background: #eee; }
.sub { color: #555; }
.notes { white-space: pre-wrap; }
"""


def _kv(rows: list[tuple[str, str]]) -> str:
    body = "".join(
        f"<tr><td class='k'>{escape(k)}</td><td>{escape(v)}</td></tr>" for k, v in rows if v
    )
    return f"<table class='kv'>{body}</table>"


def _chem(c: Chemical | None, dilution: str = "") -> str:
    if c is None:
        return ""
    return f"{c.display_name} {dilution}".strip()


def _with_time(text: str, seconds: int | None) -> str:
    t = format_duration(seconds)
    if text and t:
        return f"{text}, {t}"
    return text or t


def roll_card_html(roll: Roll, temp_unit: str = "C", length_unit: str = "cm") -> str:
    """Self-contained HTML (QTextDocument subset) describing roll, development and prints."""
    title = escape(roll.code) + (f" — {escape(roll.title)}" if roll.title else "")
    camera = roll.camera.display_name if roll.camera else ""
    parts = [f"<html><head><style>{CSS}</style></head><body>", f"<h1>{title}</h1>"]
    parts.append(
        f"<div class='sub'>{escape(roll.film_stock.display_name)} · EI {roll.shot_iso} "
        f"({escape(badge_text(roll.push_pull_stops))})"
        + (f" · {escape(camera)}" if camera else "")
        + "</div>"
    )
    parts.append("<h2>Roll</h2>")
    parts.append(
        _kv(
            [
                ("Format", roll.format.value),
                ("Exposures", str(roll.exposures or "")),
                ("Lens", roll.lens),
                ("Loaded", str(roll.date_loaded or "")),
                ("Finished", str(roll.date_finished or "")),
                ("Subject / location", roll.subject_location),
                ("Film expiry", str(roll.film_expiry or "")),
                ("Tags", ", ".join(t.name for t in roll.tags)),
                ("Status", roll.status.value),
            ]
        )
    )
    if roll.notes:
        parts.append(f"<p class='notes'>{escape(roll.notes)}</p>")

    dev = roll.development
    if dev is not None:
        parts.append("<h2>Development</h2>")
        parts.append(
            _kv(
                [
                    ("Date", str(dev.date_developed or "")),
                    ("Developer", _chem(dev.developer, dev.dilution)),
                    ("Time / temperature", f"{format_duration(dev.dev_time_s)} at "
                     f"{format_temp(dev.temperature_c, temp_unit)}"),
                    ("Agitation", dev.agitation),
                    ("Pre-soak", format_duration(dev.presoak_s)),
                    ("Stop", _with_time(_chem(dev.stop_chemical), dev.stop_time_s)),
                    ("Rinse", format_duration(dev.rinse_time_s)),
                    ("Fixer", _with_time(_chem(dev.fixer, dev.fixer_dilution), dev.fix_time_s)),
                    ("Wash", _with_time(dev.wash_method, dev.wash_time_s)),
                    ("Wetting agent", _with_time(_chem(dev.wetting_agent), dev.wetting_time_s)),
                    ("Tank", dev.tank),
                    ("Developed with", ", ".join(r.code for r in dev.developed_with_rolls)),
                    ("Negatives", "★" * (dev.result_rating or 0)),
                ]
            )
        )  # fmt: skip
        if dev.notes:
            parts.append(f"<p class='notes'>{escape(dev.notes)}</p>")

    if roll.prints:
        parts.append(f"<h2>Prints ({len(roll.prints)})</h2>")
    for p in roll.prints:
        head = f"Frame {escape(p.frame or '?')}" + (f" — {escape(p.title)}" if p.title else "")
        head += " · final" if p.is_final else " · work print"
        parts.append(f"<h3>{head}</h3>")
        head_h = to_display_length(p.head_height_cm, length_unit)
        parts.append(
            _kv(
                [
                    ("Date", str(p.date_printed or "")),
                    ("Paper", (p.paper.display_name if p.paper else "")
                     + (f", {p.paper_size}" if p.paper_size else "")),
                    ("Enlarger", " / ".join(x for x in (p.enlarger, p.enlarging_lens) if x)),
                    ("Aperture", p.aperture),
                    ("Head height", f"{head_h:g} {length_unit}" if head_h else ""),
                    ("Contrast", contrast_summary(p.contrast_method, p.exposures)),
                    ("Developer", _with_time(_chem(p.developer, p.dev_dilution), p.dev_time_s)
                     + (f" at {format_temp(p.dev_temperature_c, temp_unit)}"
                        if p.dev_temperature_c else "")),
                    ("Stop", _with_time(_chem(p.stop_chemical), p.stop_time_s)),
                    ("Fixer", _with_time(_chem(p.fixer, p.fixer_dilution), p.fix_time_s)),
                    ("Wash", format_duration(p.wash_time_s)),
                    ("Toning", p.toning),
                    ("Rating", "★" * (p.rating or 0)),
                ]
            )
        )  # fmt: skip
        if p.exposures:
            rows = "".join(
                f"<tr><td>{i + 1}</td><td>{escape(e.purpose.value)}</td>"
                f"<td>{escape(e.filter_grade)}</td><td>{format_seconds(e.seconds)}</td>"
                f"<td>{escape(e.aperture or '')}</td><td>{escape(e.note or '')}</td></tr>"
                for i, e in enumerate(p.exposures)
            )
            parts.append(
                "<table class='grid'><tr><th>#</th><th>Purpose</th><th>Filter</th>"
                "<th>Time</th><th>Aperture</th><th>Note</th></tr>"
                f"{rows}<tr><td></td><td colspan='2'><b>Total</b></td>"
                f"<td><b>{format_seconds(total_exposure(p.exposures))}</b></td>"
                "<td colspan='2'></td></tr></table>"
            )
        if p.notes:
            parts.append(f"<p class='notes'>{escape(p.notes)}</p>")
    parts.append("</body></html>")
    return "".join(parts)
