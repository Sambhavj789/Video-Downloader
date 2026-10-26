"""Shared fixtures. Nothing here touches the real library or the real config files."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vd.config import Settings  # noqa: E402


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    """Settings pointed at a throwaway output root (no ``config/`` writes)."""
    return Settings(output_root=str(tmp_path / "library"), video_workers=1, concurrency=2)


@pytest.fixture()
def record() -> dict:
    return {
        "key": "auditing-and-ethics",
        "batch_id": "68d63fcee9931e9b04787991",
        "subject_id": "68dcfa87f59b6e035c24582e",
        "batch_name": "CA Inter Pro Udesh Regular Sep 2026 Group 2",
        "subject_name": "Auditing and Ethics",
        "dir_name": "Audit",
    }


@pytest.fixture()
def catalog() -> dict:
    """Two chapters: one normal (video + notes) and one PDF-only shelf."""
    return {
        "version": 2,
        "key": "auditing-and-ethics",
        "fetched_at": "2026-10-25T10:00:00+05:30",
        "subject": {"id": "68dcfa87f59b6e035c24582e", "name": "Auditing and Ethics"},
        "chapters": [
            {
                "id": "ch1",
                "name": "Audit Evidence",
                "pdf_only": False,
                "videos": [
                    {
                        "id": "sched1",
                        "topic": "Audit Evidence: Lecture 1",
                        "duration_s": 3600,
                        "has_media": True,
                        "notes": [{"name": "Notes 1", "url": "https://cdn/notes1.pdf", "ext": ".pdf"}],
                        "dpp": [],
                        "slides": [],
                    },
                    {
                        "id": "sched2",
                        "topic": "Audit Evidence: Lecture 2",
                        "duration_s": 0,
                        "has_media": False,
                        "notes": [],
                        "dpp": [],
                        "slides": [],
                    },
                ],
                "documents": [],
            },
            {
                "id": "ch2",
                "name": "E-Books __ PDF Only",
                "pdf_only": True,
                "videos": [],
                "documents": [
                    {"name": "Audit Book", "url": "https://cdn/book.pdf", "ext": ".pdf"},
                ],
            },
        ],
    }
