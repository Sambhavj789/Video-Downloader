"""Markdown reports: the founder reads these instead of opening the UI."""

from __future__ import annotations

from pathlib import Path

from vd import plan as plan_mod, report


def _plan(tmp_path: Path, catalog: dict, record: dict, settings) -> dict:
    catalog["subject_record"] = record
    return plan_mod.build_plan(catalog, settings)


def test_subject_report_has_summary_and_chapters(tmp_path, settings, record, catalog):
    plan = _plan(tmp_path, catalog, record, settings)
    text = report.render_subject(record, plan)
    assert text.startswith("# Auditing and Ethics")
    assert "Folder: `" in text and "Audit" in text
    assert "| Videos | 2 | 0 | 1 |" in text
    assert "## Missing (first 40)" in text
    assert "Sab kuch local me hai" not in text


def test_subject_report_escapes_pipes_in_chapter_names(tmp_path, settings, record, catalog):
    catalog["chapters"][0]["name"] = "MCQ || Video Only"
    text = report.render_subject(record, _plan(tmp_path, catalog, record, settings))
    assert "MCQ \\|\\| Video Only" in text


def test_subject_report_celebrates_a_finished_subject(tmp_path, settings, record, catalog):
    plan = _plan(tmp_path, catalog, record, settings)
    for item in plan["items"]:
        if item["status"] != "missing":
            continue
        target = Path(item["target"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x")

    finished = plan_mod.build_plan(catalog, settings)
    text = report.render_subject(record, finished)
    assert "Sab kuch local me hai" in text


def test_library_report_lists_one_row_per_subject(tmp_path, settings, record, catalog):
    plan = _plan(tmp_path, catalog, record, settings)
    text = report.render_library([(record, plan)], settings.output_path)
    assert "# CA Inter — offline sync status" in text
    assert "Auditing and Ethics" in text
    assert "| `Audit` |" in text
    assert "Legend" in text


def test_reports_are_written_to_disk(tmp_path, settings, record, catalog):
    plan = _plan(tmp_path, catalog, record, settings)
    path = report.write_subject_report(record, plan, tmp_path / "reports" / "k.md")
    assert path.exists() and path.read_text(encoding="utf-8").startswith("# Auditing and Ethics")

    settings.output_path.mkdir(parents=True, exist_ok=True)
    library = report.write_library_status([(record, plan)], settings.output_path)
    assert library.name == "_SYNC-STATUS.md"
