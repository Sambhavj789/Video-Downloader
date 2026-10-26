"""Layout + plan: the "kya bacha hai" logic, checked against a fake disk."""

from __future__ import annotations

from pathlib import Path

from vd import plan as plan_mod
from vd.layout import Layout


def _write(path: Path, size: int = 10) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


def test_resolve_subject_dir_uses_existing_folder(settings, record):
    _write(settings.output_path / "Audit" / "keep.txt")
    assert plan_mod.resolve_subject_dir(settings, record).name == "Audit"


def test_explicit_dir_name_wins_over_fuzzy_match(settings, record):
    """``Taxation (GST)`` must not be folded into the existing ``Taxation`` folder."""
    _write(settings.output_path / "Taxation" / "keep.txt")
    gst = {**record, "subject_name": "Taxation (GST)", "dir_name": "Taxation (GST)"}
    assert plan_mod.resolve_subject_dir(settings, gst).name == "Taxation (GST)"


def test_subject_name_matches_typo_folder(settings, record):
    _write(settings.output_path / "Coorporate-And-Other-Law" / "keep.txt")
    law = {**record, "subject_name": "Corporate and Other Law", "dir_name": ""}
    assert plan_mod.resolve_subject_dir(settings, law).name == "Coorporate-And-Other-Law"


def test_plan_marks_everything_missing_on_an_empty_disk(settings, catalog):
    plan = plan_mod.build_plan(catalog, settings)
    statuses = {item["id"]: item["status"] for item in plan["items"]}
    assert statuses["video:sched1"] == "missing"
    assert statuses["video:sched2"] == "unavailable"      # site has no media yet
    assert plan["summary"]["by_kind"]["videos"]["missing"] == 1
    assert plan["summary"]["by_kind"]["documents"]["missing"] == 1
    assert "video:sched2" not in [i["id"] for i in plan["selected_items"]]


def test_plan_sees_existing_files_as_done(settings, record, catalog):
    catalog["subject_record"] = record
    chapter = settings.output_path / "Audit" / "Audit Evidence"
    _write(chapter / "Audit Evidence_ Lecture 1.mp4", 2048)
    _write(chapter / "Notes" / "Audit Evidence_ Lecture 1 - Notes 1.pdf", 512)

    plan = plan_mod.build_plan(catalog, settings)
    videos = plan["summary"]["by_kind"]["videos"]
    notes = plan["summary"]["by_kind"]["notes"]
    assert (videos["done"], videos["missing"], videos["unavailable"]) == (1, 0, 1)
    assert (notes["done"], notes["missing"]) == (1, 0)


def test_plan_matches_renamed_file_by_normalised_stem(settings, record, catalog):
    catalog["subject_record"] = record
    chapter = settings.output_path / "Audit" / "Audit Evidence"
    _write(chapter / "audit evidence lecture 1.mp4", 100)
    plan = plan_mod.build_plan(catalog, settings)
    assert plan["summary"]["by_kind"]["videos"]["done"] == 1


def test_pdf_only_shelf_keeps_pdfs_at_chapter_root(settings, record, catalog):
    catalog["subject_record"] = record
    plan = plan_mod.build_plan(catalog, settings)
    document = next(i for i in plan["items"] if i["kind"] == "documents")
    target = Path(document["target"])
    assert target.name == "Audit Book.pdf"
    assert target.parent.name == "E-Books __ PDF Only"
    assert "Notes" not in target.parts


def test_notes_live_in_a_notes_subfolder(settings, catalog):
    plan = plan_mod.build_plan(catalog, settings)
    note = next(i for i in plan["items"] if i["kind"] == "notes")
    assert Path(note["target"]).parent.name == "Notes"


def test_kind_filter_and_only_missing(settings, catalog):
    notes_only = plan_mod.build_plan(catalog, settings, kinds=["notes"])
    assert {item["kind"] for item in notes_only["selected_items"]} == {"notes"}

    everything = plan_mod.build_plan(catalog, settings, only_missing=False)
    downloadable = [i for i in everything["items"] if i["status"] != "unavailable"]
    assert everything["summary"]["selected"] == len(downloadable)


def test_explicit_ids_win_over_filters(settings, catalog):
    chosen = plan_mod.build_plan(catalog, settings, kinds=["videos"], include_ids=["doc:whatever"])
    assert chosen["summary"]["selected"] == 0

    document_id = next(i["id"] for i in plan_mod.build_plan(catalog, settings)["items"]
                       if i["kind"] == "documents")
    picked = plan_mod.build_plan(catalog, settings, kinds=["videos"], include_ids=[document_id])
    assert [i["id"] for i in picked["selected_items"]] == [document_id]


def test_size_estimate_uses_duration(settings, catalog):
    plan = plan_mod.build_plan(catalog, settings)
    video = next(i for i in plan["items"] if i["id"] == "video:sched1")
    assert video["size_est_mb"] == round(1.0 * settings.mb_per_hour, 1)
    unknown = next(i for i in plan["items"] if i["id"] == "video:sched2")
    assert unknown["size_est_mb"] == round(1.6 * settings.mb_per_hour, 1)


def test_plan_for_subject_needs_a_catalog(settings, record):
    try:
        plan_mod.plan_for_subject(record, settings)
    except FileNotFoundError as exc:
        assert "catalog" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("missing catalog should raise")


def test_layout_chapter_dir_matches_existing_typo(settings):
    layout = Layout(settings.output_path)
    subject_dir = settings.output_path / "Audit"
    _write(subject_dir / "Special Features of Audit of Different Types of Entities" / "x.mp4")
    resolved = layout.chapter_dir(
        subject_dir,
        "Special Features of Audit of Different Types of Entities",
        Layout.existing_children(subject_dir),
    )
    assert resolved.name == "Special Features of Audit of Different Types of Entities"
