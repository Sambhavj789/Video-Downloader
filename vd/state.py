"""Small JSON stores: catalog cache per subject + run progress.

Everything here is disposable (``state/`` is gitignored). Disk is the real source of
truth for "is this file downloaded"; progress files only remember the last run and
the failures worth retrying.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .config import CATALOG_DIR, PROGRESS_DIR, PROJECT_ROOT, REPORT_DIR, STATE_DIR, TEMP_DIR
from .links import load_subjects

LEGACY_TRACKERS = (
    PROJECT_ROOT / "batch_progress.json",
    PROJECT_ROOT / "materials_progress.json",
)


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


# -- catalog -----------------------------------------------------------------
def catalog_file(key: str) -> Path:
    return CATALOG_DIR / f"{key}.json"


def load_catalog(key: str) -> dict | None:
    data = _read_json(catalog_file(key), None)
    if not isinstance(data, dict) or "chapters" not in data:
        return None
    return data


def save_catalog(key: str, catalog: dict) -> Path:
    path = catalog_file(key)
    _write_json(path, catalog)
    return path


def catalog_age_days(key: str) -> float | None:
    path = catalog_file(key)
    if not path.exists():
        return None
    stamp = _read_json(path, {}).get("fetched_at")
    if not stamp:
        return None
    try:
        when = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    return round((datetime.now(when.tzinfo) - when).total_seconds() / 86400, 1)


# -- progress ----------------------------------------------------------------
def progress_file(key: str) -> Path:
    return PROGRESS_DIR / f"{key}.json"


def load_progress(key: str) -> dict:
    data = _read_json(progress_file(key), {})
    if not isinstance(data, dict):
        return {}
    data.setdefault("done", [])
    data.setdefault("failed", {})
    return data


def save_progress(key: str, progress: dict) -> Path:
    progress["updated_at"] = _now()
    path = progress_file(key)
    _write_json(path, progress)
    return path


def mark_done(key: str, item_id: str, path: str = "") -> None:
    progress = load_progress(key)
    if item_id not in progress["done"]:
        progress["done"].append(item_id)
    progress["failed"].pop(item_id, None)
    if path:
        progress.setdefault("files", {})[item_id] = path
    save_progress(key, progress)


def mark_failed(key: str, item_id: str, error: str) -> None:
    progress = load_progress(key)
    progress["failed"][item_id] = {"error": str(error)[:400], "at": _now()}
    save_progress(key, progress)


# -- reports -----------------------------------------------------------------
def report_file(key: str) -> Path:
    return REPORT_DIR / f"{key}.md"


def save_report(key: str, text: str) -> Path:
    path = report_file(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# -- migration / housekeeping ------------------------------------------------
def legacy_progress() -> dict:
    """Old ``batch_progress.json`` / ``materials_progress.json`` names, read-only.

    Used only as a hint in the report (``videos_done`` names). Download state is
    recomputed from disk so a moved library still counts as done.
    """
    merged = {"videos_done": [], "chapters_done": [], "urls": []}
    for path in LEGACY_TRACKERS:
        data = _read_json(path, {})
        if not isinstance(data, dict):
            continue
        merged["videos_done"].extend(data.get("videos_done") or [])
        merged["chapters_done"].extend(data.get("chapters_done") or [])
        if data.get("url"):
            merged["urls"].append(data["url"])
    merged["videos_done"] = sorted({v for v in merged["videos_done"] if v})
    return merged


def clean_temp(keep_root: bool = True) -> dict:
    """Delete stale segment folders / caches. Returns what was removed."""
    removed = []
    if TEMP_DIR.exists():
        for child in TEMP_DIR.iterdir():
            if child.is_dir():
                for nested in sorted(child.rglob("*"), reverse=True):
                    try:
                        nested.unlink() if nested.is_file() else nested.rmdir()
                    except OSError:
                        pass
                try:
                    child.rmdir()
                except OSError:
                    pass
                removed.append(str(child))
    legacy_dirs = ["_temp", "_segments", "_batch_temp", "_debug_segments", "__pycache__"]
    for name in legacy_dirs:
        path = PROJECT_ROOT / name
        if path.is_dir():
            for nested in sorted(path.rglob("*"), reverse=True):
                try:
                    nested.unlink() if nested.is_file() else nested.rmdir()
                except OSError:
                    pass
            try:
                path.rmdir()
                removed.append(name)
            except OSError:
                pass
    return {"removed": removed, "temp_root": str(TEMP_DIR) if keep_root else ""}


def state_root() -> Path:
    return STATE_DIR


def subjects_with_catalog() -> list[dict]:
    """Registered subjects decorated with catalog presence/age."""
    out = []
    for record in load_subjects().values():
        key = record.get("key", "")
        catalog = load_catalog(key)
        out.append({
            **record,
            "has_catalog": catalog is not None,
            "catalog_age_days": catalog_age_days(key),
            "totals": (catalog or {}).get("totals", {}),
        })
    return out
