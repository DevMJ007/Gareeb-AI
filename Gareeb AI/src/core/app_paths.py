"""Stable paths for MJ AI's bundled files and per-user runtime data."""

from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    """Return the source checkout root, independent of the current directory."""
    return Path(__file__).resolve().parents[2]


def app_data_dir() -> Path:
    """Return MJ AI's local, per-user data directory.

    ``MJAI_HOME`` can point to a custom or portable data folder. By default,
    Windows uses ``%LOCALAPPDATA%\\Gareeb AI``. Other platforms follow the
    XDG data directory convention.
    """
    override = os.environ.get("MJAI_HOME")
    if override:
        override_path = Path(override).expanduser()
        if not override_path.is_absolute():
            override_path = project_root() / override_path
        return override_path.resolve()

    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return (Path(local_app_data) / "Gareeb AI").resolve()
        return (Path.home() / "AppData" / "Local" / "Gareeb AI").resolve()

    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        return (Path(xdg_data_home).expanduser() / "gareeb-ai").resolve()
    return (Path.home() / ".local" / "share" / "gareeb-ai").resolve()


def data_path(path: str | Path) -> Path:
    """Resolve a configured relative runtime path below MJ AI's data folder."""
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate
    return app_data_dir() / candidate

