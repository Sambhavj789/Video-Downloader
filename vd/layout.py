"""Where a catalog item lives on disk.

Layout (matches the founder's existing library, nothing has to be moved)::

    <output_root>/
      <Subject>/                       e.g. Financial-Management-.../
        <Chapter>/                     e.g. Cost of Capital/
          <Topic>.mp4
          Notes/<video> - <note>.pdf
          DPP/<video> - <dpp>.pdf
          Slides/<video> - <slide>.jpg   (optional)
        <Chapter> __ PDF Only/          PDFs sit directly here
          <document>.pdf
        _SYNC-STATUS.md                generated summary
"""

from __future__ import annotations

from pathlib import Path

from . import names

ATTACHMENT_DIRS = {"notes": "Notes", "dpp": "DPP", "slides": "Slides"}


class Layout:
    """Pure path builder. Never creates folders unless ``ensure`` is used."""

    def __init__(self, root: Path):
        self.root = Path(root)

    # -- subjects / chapters -------------------------------------------------
    def subject_dir_name(self, subject_name: str, existing: list[str] | None = None) -> str:
        wanted = names.sanitize(subject_name, "Subject")
        return names.match_dir(existing or [], wanted) or wanted

    def subject_dir(self, subject_name: str, existing: list[str] | None = None) -> Path:
        return self.root / self.subject_dir_name(subject_name, existing)

    def chapter_dir(self, subject_dir: Path, chapter_name: str,
                    existing: list[str] | None = None) -> Path:
        wanted = names.sanitize(chapter_name, "Chapter")
        folder = names.match_dir(existing or [], wanted) or wanted
        return Path(subject_dir) / folder

    @staticmethod
    def chapter_dir_name(chapter_name: str, existing: list[str] | None = None) -> str:
        wanted = names.sanitize(chapter_name, "Chapter")
        return names.match_dir(existing or [], wanted) or wanted

    # -- files ---------------------------------------------------------------
    def video_path(self, chapter_dir: Path, topic: str) -> Path:
        return Path(chapter_dir) / names.video_filename(topic)

    def attachment_path(self, chapter_dir: Path, attachment: dict, kind: str,
                        chapter_pdf_only: bool = False, video_topic: str = "") -> Path:
        """Target for a PDF/image attachment.

        PDF-only shelves keep files at the top level; real chapters get a
        ``Notes``/``DPP``/``Slides`` subfolder so videos stay easy to find.
        """
        directory = Path(chapter_dir)
        if not chapter_pdf_only:
            directory = directory / ATTACHMENT_DIRS.get(kind, kind.title())
        name = attachment.get("name") or attachment.get("file") or kind
        if chapter_pdf_only or not video_topic:
            filename = names.sanitize(name, kind) + ".pdf"
        else:
            filename = names.note_filename(video_topic, name)
        return directory / filename

    # -- helpers -------------------------------------------------------------
    @staticmethod
    def ensure(path: Path) -> Path:
        Path(names.fs_path(path)).mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def existing_children(path: Path) -> list[str]:
        try:
            return sorted(p.name for p in Path(path).iterdir() if p.is_dir())
        except OSError:
            return []

    @staticmethod
    def file_size(path: Path) -> int:
        return names.stat_size(path)
