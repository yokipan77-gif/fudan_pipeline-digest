"""Shared configuration loader.

Loads config.json (or config.example.json as fallback for sanity-only fields).
Resolves paths to absolute. Never logs API keys.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.json"
CONFIG_EXAMPLE_PATH = PROJECT_ROOT / "config.example.json"


class Config:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    @property
    def project_root(self) -> Path:
        return PROJECT_ROOT

    @property
    def output_dir(self) -> Path:
        return Path(self._data["output_dir"])

    @property
    def cache_dir(self) -> Path:
        return Path(self._data["cache_dir"])

    @property
    def cookies_dir(self) -> Path:
        return PROJECT_ROOT / "cookies"

    @property
    def ffmpeg_path(self) -> Path:
        return Path(self._data["ffmpeg_path"])


def load_config() -> Config:
    path = CONFIG_PATH if CONFIG_PATH.exists() else CONFIG_EXAMPLE_PATH
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    cfg = Config(data)
    cfg.cookies_dir.mkdir(parents=True, exist_ok=True)
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    cfg.cache_dir.mkdir(parents=True, exist_ok=True)
    return cfg
