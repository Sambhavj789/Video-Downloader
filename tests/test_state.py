"""Catalog/progress stores + temp cleanup. All paths are redirected into tmp_path."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from vd import state


def namespace(mapping: dict) -> SimpleNamespace:
    return SimpleNamespace(**mapping)


@pytest.fixture()
def state_dirs(tmp_path: Path, monkeypatch):
    dirs = {
        "CATALOG_DIR": tmp_path / "catalogs",
        "PROGRESS_DIR": tmp_path / "progress",
        "REPORT_DIR": tmp_path / "reports",
        "TEMP_DIR": tmp_path / "work",
        "PROJECT_ROOT": tmp_path / "project",
    }
    for name, path in dirs.items():
        path.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(state, name, path)
    return namespace(dirs)


def test_catalog_roundtrip_and_age(state_dirs):
    assert state.load_catalog("k") is None
    state.save_catalog("k", {"chapters": [], "fetched_at": "2020-01-01T00:00:00+00:00"})
    loaded = state.load_catalog("k")
    assert loaded is not None and loaded["chapters"] == []
    assert state.catalog_age_days("k") > 365
    assert state.catalog_age_days("missing") is None


def test_catalog_without_chapters_is_ignored(state_dirs):
    path = state.catalog_file("bad")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"totals": {}}', encoding="utf-8")
    assert state.load_catalog("bad") is None


def test_progress_marks_done_and_clears_failures(state_dirs):
    state.mark_failed("k", "video:1", "boom")
    progress = state.load_progress("k")
    assert "video:1" in progress["failed"]

    state.mark_done("k", "video:1", path="C:/x.mp4")
    progress = state.load_progress("k")
    assert "video:1" in progress["done"]
    assert "video:1" not in progress["failed"]
    assert progress["files"]["video:1"] == "C:/x.mp4"
    assert progress["updated_at"]


def test_progress_file_is_json_on_disk(state_dirs):
    state.mark_done("k", "video:1")
    assert '"video:1"' in state.progress_file("k").read_text(encoding="utf-8")


def test_reports_are_written_into_report_dir(state_dirs):
    path = state.save_report("k", "# hi\n")
    assert path == state_dirs.REPORT_DIR / "k.md"
    assert path.read_text(encoding="utf-8") == "# hi\n"


def test_clean_temp_removes_work_and_legacy_dirs(state_dirs):
    nested = state_dirs.TEMP_DIR / "job1" / "seg.mp4"
    nested.parent.mkdir(parents=True)
    nested.write_bytes(b"x")
    legacy = state_dirs.PROJECT_ROOT / "_temp"
    (legacy / "sub").mkdir(parents=True)
    (legacy / "sub" / "part.mp4").write_bytes(b"x")
    keep = state_dirs.PROJECT_ROOT / "batch_download.py"
    keep.parent.mkdir(parents=True, exist_ok=True)
    keep.write_text("print('keep')", encoding="utf-8")

    removed = state.clean_temp()["removed"]
    assert job_removed(removed)
    assert not legacy.exists()
    assert keep.exists()


def job_removed(removed: list[str]) -> bool:
    return any(entry.endswith("job1") or entry.endswith("_temp") for entry in removed)


def test_subjects_with_catalog_is_decorated(state_dirs, monkeypatch):
    monkeypatch.setattr(state, "load_subjects", lambda: {
        "audit": {"key": "audit", "subject_name": "Auditing and Ethics"},
    })
    state.save_catalog("audit", {"chapters": [], "fetched_at": "2026-10-25T00:00:00+00:00",
                                 "totals": {"videos": 3}})
    rows = state.subjects_with_catalog()
    assert rows[0]["has_catalog"] is True
    assert rows[0]["totals"]["videos"] == 3
    assert rows[0]["catalog_age_days"] is not None


def test_legacy_progress_reads_old_trackers(state_dirs, tmp_path, monkeypatch):
    old = tmp_path / "old.json"
    old.write_text('{"videos_done": ["a", "b"], "url": "https://x"}', encoding="utf-8")
    monkeypatch.setattr(state, "LEGACY_TRACKERS", (old,))
    merged = state.legacy_progress()
    assert merged["videos_done"] == ["a", "b"]
    assert merged["urls"] == ["https://x"]


def test_broken_json_never_raises(state_dirs):
    path = state.progress_file("k")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert state.load_progress("k")["done"] == []
