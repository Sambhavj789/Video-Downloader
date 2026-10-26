"""Subject links: every batch-subject the tool tracks.

A "link" is the URL the site uses for one subject:

    https://stream.testuk.org/content?batchId=..&subjectId=..&batchName=..&subjectName=..

Registered links live in ``config/subjects.json``; the raw URLs are also written to
``config/links/<key>.txt`` so a human can re-paste or share them.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from . import names
from .config import LINKS_DIR, SUBJECTS_FILE


def parse_subject_url(url: str) -> dict:
    """Pull the four fields we need out of any site URL that carries them."""
    query = parse_qs(urlparse(url).query)
    fields = {
        "batch_id": (query.get("batchId") or [""])[0],
        "subject_id": (query.get("subjectId") or [""])[0],
        "batch_name": (query.get("batchName") or [""])[0],
        "subject_name": (query.get("subjectName") or [""])[0],
    }
    return fields


def is_subject_url(url: str) -> bool:
    fields = parse_subject_url(url)
    return bool(fields["batch_id"] and fields["subject_id"])


def build_subject_url(batch_id: str, subject_id: str, batch_name: str = "",
                      subject_name: str = "") -> str:
    """The same URL shape the site itself links to (so it can be pasted back)."""
    query = {
        "batchId": batch_id,
        "subjectId": subject_id,
        "batchName": batch_name,
        "subjectName": subject_name,
    }
    return f"https://stream.testuk.org/content?{urlencode({k: v for k, v in query.items() if v})}"


def batch_id_from(url_or_id: str) -> str:
    """Accept a full link or a bare 24-char batch id."""
    text = (url_or_id or "").strip()
    fields = parse_subject_url(text)
    return fields["batch_id"] or text


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_subjects() -> dict:
    if not SUBJECTS_FILE.exists():
        return {}
    try:
        return json.loads(SUBJECTS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_subjects(subjects: dict) -> None:
    from .config import CONFIG_DIR

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SUBJECTS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(subjects, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(SUBJECTS_FILE)


def add_subject(url: str, dir_name: str = "") -> dict:
    """Register (or refresh) a subject link and return its record."""
    fields = parse_subject_url(url)
    if not (fields["batch_id"] and fields["subject_id"]):
        raise ValueError("URL me batchId aur subjectId dono chahiye (content ya schedule-details link do).")

    key = names.subject_key(fields["subject_name"] or fields["subject_id"], fields["subject_id"])
    subjects = load_subjects()
    record = subjects.get(key, {})
    record.update({
        "key": key,
        "url": url,
        "batch_id": fields["batch_id"],
        "subject_id": fields["subject_id"],
        "batch_name": fields["batch_name"] or record.get("batch_name", ""),
        "subject_name": fields["subject_name"] or record.get("subject_name", key),
        "dir_name": dir_name or record.get("dir_name", ""),
        "updated_at": now_iso(),
    })
    record.setdefault("added_at", now_iso())
    subjects[key] = record
    save_subjects(subjects)

    LINKS_DIR.mkdir(parents=True, exist_ok=True)
    (LINKS_DIR / f"{key}.txt").write_text(url + "\n", encoding="utf-8")
    return record


def remove_subject(key: str) -> bool:
    subjects = load_subjects()
    if key not in subjects:
        return False
    subjects.pop(key)
    save_subjects(subjects)
    link_file = LINKS_DIR / f"{key}.txt"
    if link_file.exists():
        link_file.unlink()
    return True


def find_subject(key: str) -> dict | None:
    return load_subjects().get(key)


def sorted_subjects() -> list[dict]:
    items = list(load_subjects().values())
    items.sort(key=lambda r: (r.get("subject_name", "").lower(), r.get("key", "")))
    return items
