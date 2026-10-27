"""Project paths and persisted settings.

One fact in one place: every module asks this file for a directory instead of
building its own ``Path(__file__).parent / ".."``.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
STATE_DIR = PROJECT_ROOT / "state"
LOG_DIR = PROJECT_ROOT / "logs"
TEMP_DIR = PROJECT_ROOT / ".work"

SETTINGS_FILE = CONFIG_DIR / "settings.json"
SUBJECTS_FILE = CONFIG_DIR / "subjects.json"
LINKS_DIR = CONFIG_DIR / "links"

CATALOG_DIR = STATE_DIR / "catalogs"
PROGRESS_DIR = STATE_DIR / "progress"
REPORT_DIR = STATE_DIR / "reports"

# The founder's library. Auto-detected so a fresh clone still works.
LIBRARY_HINT = Path(r"G:\Knowledge\CA-Inter")
LIBRARY_PARENT_HINT = Path(r"G:\Knowledge")


def _default_output_root() -> str:
    if LIBRARY_HINT.is_dir():
        return str(LIBRARY_HINT)
    if LIBRARY_PARENT_HINT.is_dir():
        return str(LIBRARY_PARENT_HINT / "CA-Inter")
    return str(PROJECT_ROOT / "output")


@dataclass
class Settings:
    """User-facing knobs. Persisted in ``config/settings.json``."""

    output_root: str = ""
    concurrency: int = 12         # parallel segment downloads per video (16+ nahi tez)
    videos_per_hour: int = 18     # API allows 20 video-url-details/hour; stay under it
    videos_per_day: int = 45      # API allows 50 video-url-details/24h; stay under it
    video_workers: int = 1        # videos downloaded at the same time
    retries: int = 4              # attempts per segment / per file
    fetch_workers: int = 2        # parallel schedule-page requests (higher = HTTP 429)
    mb_per_hour: int = 450        # size estimate when a duration is unknown
    ui_port: int = 7878
    quality: str = "best"         # "best" or a height such as "720"

    def __post_init__(self) -> None:
        if not self.output_root:
            self.output_root = _default_output_root()

    @property
    def output_path(self) -> Path:
        return Path(self.output_root)

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")
        tmp.replace(SETTINGS_FILE)

    @classmethod
    def load(cls) -> "Settings":
        if not SETTINGS_FILE.exists():
            settings = cls()
            settings.save()
            return settings
        try:
            raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in raw.items() if k in known})


def ensure_dirs() -> None:
    for path in (CONFIG_DIR, LINKS_DIR, STATE_DIR, CATALOG_DIR, PROGRESS_DIR,
                 REPORT_DIR, LOG_DIR, TEMP_DIR):
        path.mkdir(parents=True, exist_ok=True)


def free_space_gb(path: Path) -> float | None:
    """Free space of the drive holding ``path`` (walks up to an existing parent)."""
    probe = path
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    try:
        return round(shutil.disk_usage(probe).free / (1024 ** 3), 1)
    except OSError:
        return None


def which_curl() -> str | None:
    return shutil.which("curl.exe") or shutil.which("curl")


def env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
