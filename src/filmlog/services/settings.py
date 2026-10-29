"""User settings persisted as JSON in the config directory."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from filmlog import paths

THEMES = ("system", "light", "dark", "darkroom")
TEMP_UNITS = ("C", "F")
LENGTH_UNITS = ("cm", "in")


@dataclass
class Settings:
    theme: str = "system"
    temperature_unit: str = "C"
    length_unit: str = "cm"
    window_geometry: str = ""  # base64-encoded Qt geometry
    window_state: str = ""
    # Per-table header state (base64), keyed by table name.
    table_states: dict[str, str] = field(default_factory=dict)
    last_view: int = 0

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        path = path or paths.config_file()
        try:
            raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        known = {f.name for f in fields(cls)}
        s = cls(**{k: v for k, v in raw.items() if k in known})
        if s.theme not in THEMES:
            s.theme = "system"
        if s.temperature_unit not in TEMP_UNITS:
            s.temperature_unit = "C"
        if s.length_unit not in LENGTH_UNITS:
            s.length_unit = "cm"
        return s

    def save(self, path: Path | None = None) -> None:
        path = path or paths.config_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        tmp.replace(path)
