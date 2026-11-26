"""Emplacement des réglages et du dictionnaire de l'utilisateur."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def app_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        return base / "NobodyDoc"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "nobodydoc"


def dictionary_path() -> Path:
    return app_dir() / "dictionnaire.csv"


def _prefs_path() -> Path:
    return app_dir() / "preferences.json"


def load_prefs() -> dict:
    try:
        return json.loads(_prefs_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_prefs(prefs: dict) -> None:
    try:
        _prefs_path().parent.mkdir(parents=True, exist_ok=True)
        _prefs_path().write_text(json.dumps(prefs, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
