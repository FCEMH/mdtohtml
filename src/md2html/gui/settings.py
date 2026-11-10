from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SETTINGS_DIR = Path.home() / ".config" / "md2html"
SETTINGS_FILE = SETTINGS_DIR / "gui_settings.json"


def load_gui_settings() -> dict[str, Any]:
    defaults = {
        "window_width": 1280,
        "window_height": 900,
        "last_folder": str(Path.home()),
        "last_file": "",
        "last_output_dir": str(Path.home()),
        "theme": "auto",
        "toc_depth": 3,
        "search": True,
    }
    if not SETTINGS_FILE.exists():
        return defaults
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            defaults.update(data)
    except Exception:
        pass
    return defaults


def save_gui_settings(settings: dict[str, Any]) -> None:
    try:
        SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
        current = load_gui_settings()
        current.update(settings)
        SETTINGS_FILE.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
