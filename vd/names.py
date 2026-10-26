"""Name and path-safe string rules.

The single most important invariant of this project: **a name produced here must
equal the name already on disk**. The founder's library was written by the old
scripts, so :func:`sanitize` keeps their exact rule (one ``_`` per illegal char,
spaces kept). Do not "improve" it without migrating the library.
"""

from __future__ import annotations

import difflib
import hashlib
import re
from pathlib import Path

_ILLEGAL = re.compile(r'[<>:"/\\|?*]')
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_SPACES = re.compile(r"\s+")

MAX_NAME = 150


def sanitize(name: object, fallback: str = "Unknown") -> str:
    """Windows-safe file/folder name, byte-compatible with the legacy scripts."""
    text = _ILLEGAL.sub("_", str(name or "").strip())
    text = text.strip(" .")
    text = _SPACES.sub(" ", text)
    return text[:MAX_NAME] or fallback


def normalize(text: object) -> str:
    """Comparison key: case, spaces and punctuation removed."""
    return _NON_ALNUM.sub("", str(text or "").lower())


def slug(text: object, fallback: str = "subject") -> str:
    """Readable ASCII key for state files: ``Financial Management`` -> ``financial-management``."""
    raw = _NON_ALNUM.sub("-", str(text or "").lower()).strip("-")
    return (raw[:60] or fallback)


def subject_key(subject_name: str, subject_id: str = "") -> str:
    """Stable per-subject state key; falls back to the id when two names collide."""
    base = slug(subject_name)
    if not subject_id:
        return base
    return f"{base}-{subject_id[:6]}"


def url_hash(url: str) -> str:
    return hashlib.md5(url.encode("utf-8")).hexdigest()[:10]


def fs_path(path) -> str:
    """Absolute path Windows will accept even when it is longer than MAX_PATH.

    Legacy note names are ~300 characters long, so ``Notes\\<name>.pdf`` blows past the
    260-character limit. Prefixed with ``\\\\?\\`` the open works without registry changes.
    Callers that *display* or *record* a path should keep using ``str(path)``.
    """
    import os

    text = os.path.abspath(str(path))
    if os.name != "nt" or text.startswith("\\\\?\\"):
        return text
    if len(text) < 240:
        return text
    if text.startswith("\\\\"):
        return "\\\\?\\UNC\\" + text[2:]
    return "\\\\?\\" + text


def stat_size(path) -> int:
    """``st_size`` that also survives long paths; 0 when the file is unreadable."""
    import os

    try:
        return os.stat(fs_path(path)).st_size
    except OSError:
        return 0


def match_dir(existing: list[str], wanted: str, threshold: float = 0.86) -> str | None:
    """Find the on-disk folder that a catalog chapter/subject name refers to.

    Order: exact -> case-insensitive -> normalized -> fuzzy. The fuzzy step
    rescues legacy typos (``Stratigic``) and renamed chapters without a migration.
    """
    if not existing:
        return None
    if wanted in existing:
        return wanted
    low = wanted.lower()
    for name in existing:
        if name.lower() == low:
            return name
    norm = normalize(wanted)
    if norm:
        scored = sorted(
            ((difflib.SequenceMatcher(None, norm, normalize(n)).ratio(), n) for n in existing),
            reverse=True,
        )
        if scored and scored[0][0] >= threshold:
            return scored[0][1]
    return None


def video_filename(topic: str, fallback: str = "video") -> str:
    return sanitize(topic, fallback) + ".mp4"


def note_filename(video_topic: str, note_name: str) -> str:
    """Per-video PDF name, legacy-compatible: ``<video> - <note>.pdf``."""
    note = sanitize(note_name, "note")
    if not video_topic:
        return note + ".pdf"
    return f"{sanitize(video_topic, 'video')} - {note}.pdf"


def chapter_is_pdf_only(chapter_name: str) -> bool:
    """The site mixes real chapters with PDF-only shelves (``E-Book __ PDF Only``)."""
    text = (chapter_name or "").lower()
    return "pdf only" in text or text.strip().startswith("e-book") or text.strip().startswith("ebook")


def unique_path(directory: Path, filename: str) -> Path:
    """``name.pdf`` -> ``name (2).pdf`` when a *different* download owns the name."""
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    for index in range(2, 100):
        alt = directory / f"{stem} ({index}){suffix}"
        if not alt.exists():
            return alt
    return candidate
