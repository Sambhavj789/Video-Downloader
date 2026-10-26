"""Name rules must stay byte-compatible with the library the old scripts wrote."""

from __future__ import annotations

from pathlib import Path

from vd import names


def test_sanitize_keeps_spaces_and_swaps_illegal_chars():
    assert names.sanitize("Heads of Income (SALARY)") == "Heads of Income (SALARY)"
    assert names.sanitize("Audit: Strategy/Planning?") == "Audit_ Strategy_Planning_"
    assert names.sanitize("  Cash Flow.  ") == "Cash Flow"
    assert names.sanitize("") == "Unknown"


def test_sanitize_truncates_long_names():
    assert len(names.sanitize("x" * 400)) == names.MAX_NAME


def test_normalize_ignores_case_and_punctuation():
    assert names.normalize("Financial-Management-And-Stratigic-Management") == (
        "financialmanagementandstratigicmanagement"
    )


def test_subject_key_is_stable_and_short():
    key = names.subject_key("Auditing and Ethics", "68dcfa87f59b6e035c24582e")
    assert key == "auditing-and-ethics-68dcfa"
    assert names.subject_key("Auditing and Ethics") == "auditing-and-ethics"


def test_match_dir_rescues_legacy_typos():
    existing = ["Advance-Accounting", "Financial-Management-And-Stratigic-Management"]
    assert names.match_dir(existing, "Financial Management and Strategic Management") == (
        "Financial-Management-And-Stratigic-Management"
    )
    assert names.match_dir(existing, "Advance Accounting") == "Advance-Accounting"


def test_match_dir_refuses_unrelated_folders():
    """A loose fuzzy match would drop files into the wrong subject."""
    assert names.match_dir(["Taxation"], "Auditing and Ethics") is None
    assert names.match_dir([], "Taxation") is None


def test_match_dir_prefers_exact_case_then_other_case():
    assert names.match_dir(["Taxation", "Audit"], "Taxation") == "Taxation"
    assert names.match_dir(["taxation"], "Taxation") == "taxation"


def test_note_filename_prefixes_the_video_topic():
    assert names.note_filename("Audit Evidence: Lecture 1", "Notes 1") == (
        "Audit Evidence_ Lecture 1 - Notes 1.pdf"
    )
    assert names.note_filename("", "Notes 1") == "Notes 1.pdf"


def test_chapter_is_pdf_only():
    assert names.chapter_is_pdf_only("E-Books __ PDF Only")
    assert names.chapter_is_pdf_only("Annonated E-book __ PDF Only")
    assert names.chapter_is_pdf_only("Ebook shelf")
    assert not names.chapter_is_pdf_only("Audit Evidence")


def test_unique_path_never_overwrites(tmp_path: Path):
    first = tmp_path / "a.pdf"
    first.write_text("x")
    assert names.unique_path(tmp_path, "a.pdf").name == "a (2).pdf"
    assert names.unique_path(tmp_path, "b.pdf").name == "b.pdf"


def test_url_hash_is_stable():
    assert names.url_hash("https://cdn/a.pdf") == names.url_hash("https://cdn/a.pdf")
    assert len(names.url_hash("https://cdn/a.pdf")) == 10


def test_fs_path_keeps_short_paths_plain(tmp_path: Path):
    short = tmp_path / "a.pdf"
    assert names.fs_path(short) == str(short)


def test_fs_path_prefixes_paths_over_the_windows_limit():
    """Legacy note names push `Notes\\<name>.pdf` past 260 characters."""
    long_name = "V" * 140
    deep = Path("G:/Knowledge/CA-Inter/Advance-Accounting/AS 21 " + "C" * 90)
    target = deep / "Notes" / (long_name + ".pdf")
    got = names.fs_path(target)
    assert len(got) > 260 or len(str(target)) < 240
    if len(str(Path(target).absolute())) >= 240:
        assert got.startswith("\\\\?\\")
        assert got.endswith(long_name + ".pdf")


def test_stat_size_reads_a_long_named_file(tmp_path: Path):
    folder = tmp_path / ("d" * 120)
    folder.mkdir()
    name = "n" * 120
    target = folder / name
    with open(names.fs_path(target), "wb") as handle:
        handle.write(b"abcdef")
    assert names.stat_size(target) == 6
