"""
SettingsStore – persists MeshTreeSupportPlugin settings to a JSON file
in Cura's global preferences folder (independent of project/workspace).

File location:  <cura_user_data>/MeshTreeSupportPlugin.json
"""
from __future__ import annotations
import json
import os
from typing import Any, Dict

from UM.Logger import Logger
from UM.Resources import Resources

FILENAME = "MeshTreeSupportPlugin.json"


class SettingsStore:

    @staticmethod
    def _path() -> str:
        folder = Resources.getStoragePath(Resources.Preferences)
        return os.path.join(folder, FILENAME)

    @classmethod
    def save(cls, settings: Dict[str, Any]) -> str:
        path = cls._path()
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(settings, f, indent=2)
            Logger.log("d", "[SettingsStore] Saved to %s", path)
            return f"Settings saved to:\n{path}"
        except Exception as e:
            Logger.log("e", "[SettingsStore] Save failed: %s", e)
            return f"Save failed: {e}"

    @classmethod
    def load(cls) -> Dict[str, Any] | None:
        path = cls._path()
        if not os.path.isfile(path):
            Logger.log("d", "[SettingsStore] No settings file at %s", path)
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            Logger.log("d", "[SettingsStore] Loaded from %s", path)
            return data
        except Exception as e:
            Logger.log("e", "[SettingsStore] Load failed: %s", e)
            return None
