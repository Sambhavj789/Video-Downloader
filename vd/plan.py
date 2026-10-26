"""Plan builder — catalog (site) x disk (what exists here) -> what to download.

"Bache hue lectures" is literally this module: every item carries a ``status`` of
``done`` / ``missing`` / ``unavailable``, and the UI only ticks the missing ones.
Nothing is downloaded here; this is a pure function over the filesystem.
"""

from __future__ import annotations

from pathlib import Path

from . import names, state
from .config import free_space_gb
from .layout import Layout

VIDEO = "videos"
NOTES = "notes"
DPP = "dpp"
SLIDES = "slides"
DOCUMENTS = "documents"
ALL_KINDS = (VIDEO, NOTES, DPP, SLIDES, DOCUMENTS)
# Slides are hundreds of images per subject, so they are opt-in: the everyday sync is
# "lectures + everything printable". `--kinds slides` or the UI chip adds them.
DEFAULT_KINDS = (VIDEO, NOTES, DPP, DOCUMENTS)

PDF_MB = 2.0
SLIDE_MB = 0.15


def resolve_subject_dir(settings, record: dict) -> Path:
    """Where this subject lives on disk (keeps the founder's existing folder name).

    ``dir_name`` on the link record wins verbatim: it is the escape hatch when a
    site name would fuzzy-match the wrong existing folder (e.g. ``Taxation (GST)``
    vs ``Taxation``). Without it we match the site name against the folders that
    are already there, so nothing has to be moved or renamed.
    """
    layout = Layout(settings.output_path)
    forced = (record.get("dir_name") or "").strip()
    if forced:
        return layout.root / names.sanitize(forced)
    existing = Layout.existing_children(settings.output_path)
    return layout.subject_dir(record.get("subject_name", ""), existing)


def find_existing_file(directory: Path, filename: str) -> Path | None:
    """Exact name, else the same normalised stem in the same folder."""
    exact = Path(directory) / filename
    if names.stat_size(exact) > 0:
        return exact
    stem, suffix = Path(filename).stem, Path(filename).suffix.lower()
    wanted = names.normalize(stem)
    if not wanted:
        return None
    try:
        candidates = list(Path(directory).iterdir())
    except OSError:
        return None
    for candidate in candidates:
        if candidate.suffix.lower() == suffix:
            if names.normalize(candidate.stem) == wanted and names.stat_size(candidate) > 0:
                return candidate
    return None


def _video_estimate_mb(duration_s: int, mb_per_hour: int) -> float:
    hours = (duration_s / 3600) if duration_s else 1.6
    return round(hours * mb_per_hour, 1)


def _item(base: dict) -> dict:
    base.setdefault("size", 0)
    return base


def build_plan(catalog: dict, settings, *, kinds: list[str] | tuple[str, ...] | None = None,
               chapters: list[str] | None = None, only_missing: bool = True,
               include_ids: list[str] | None = None) -> dict:
    """Turn a catalog into downloadable items, annotated with disk status."""
    kinds = list(kinds) if kinds else list(DEFAULT_KINDS)
    wanted_chapters = {c for c in (chapters or []) if c}
    explicit = set(include_ids or [])
    layout = Layout(settings.output_path)
    record = catalog.get("subject_record") or {}
    if not record:
        subject = catalog.get("subject") or {}
        record = {"subject_name": subject.get("name", "") if isinstance(subject, dict) else ""}
    subject_dir = resolve_subject_dir(settings, record)
    existing_chapters = Layout.existing_children(subject_dir)

    chapters_out: list[dict] = []
    all_items: list[dict] = []

    for chapter in catalog.get("chapters", []):
        chapter_name = chapter["name"]
        if wanted_chapters and chapter_name not in wanted_chapters:
            continue
        chapter_dir = layout.chapter_dir(subject_dir, chapter_name, existing_chapters)
        pdf_only = bool(chapter.get("pdf_only"))
        chapter_existing = Layout.existing_children(chapter_dir)

        items: list[dict] = []
        for video in chapter.get("videos", []):
            topic = video.get("topic", "")
            # -- the lecture video
            target = layout.video_path(chapter_dir, topic)
            found = find_existing_file(chapter_dir, target.name)
            scan_failed = video.get("scan_ok") is False
            downloadable = bool(video.get("has_media")) or scan_failed
            status = "done" if found else ("missing" if downloadable else "unavailable")
            items.append(_item({
                "id": f"video:{video.get('id')}",
                "kind": VIDEO,
                "chapter": chapter_name,
                "name": topic,
                "target": str(found or target),
                "status": status,
                "size": Layout.file_size(found) if found else 0,
                "size_est_mb": _video_estimate_mb(int(video.get("duration_s") or 0), settings.mb_per_hour),
                "duration_s": int(video.get("duration_s") or 0),
                "schedule_id": video.get("id", ""),
                "video_id": (video.get("videoDetails") or {}).get("id", "") if isinstance(video.get("videoDetails"), dict) else "",
                "unavailable_reason": "" if downloadable else "site par video ready nahi",
            }))
            # -- its attachments
            for kind, key in ((NOTES, "notes"), (DPP, "dpp"), (SLIDES, "slides")):
                for attachment in video.get(key, []):
                    folder = chapter_dir if pdf_only else chapter_dir / {"notes": "Notes", "dpp": "DPP", "slides": "Slides"}[kind]
                    target = layout.attachment_path(chapter_dir, attachment, kind, pdf_only, topic)
                    found = find_existing_file(folder, target.name)
                    size_est = SLIDE_MB if kind == SLIDES else PDF_MB
                    items.append(_item({
                        "id": f"{kind}:{names.url_hash(attachment['url'])}",
                        "kind": kind,
                        "chapter": chapter_name,
                        "name": attachment.get("name", ""),
                        "video": topic,
                        "target": str(found or target),
                        "status": "done" if found else "missing",
                        "size": Layout.file_size(found) if found else 0,
                        "size_est_mb": size_est,
                        "url": attachment["url"],
                        "ext": attachment.get("ext", ".pdf"),
                    }))

        for document in chapter.get("documents", []):
            target = layout.attachment_path(chapter_dir, document, DOCUMENTS, True, "")
            found = find_existing_file(chapter_dir, target.name)
            items.append(_item({
                "id": f"doc:{names.url_hash(document['url'])}",
                "kind": DOCUMENTS,
                "chapter": chapter_name,
                "name": document.get("name", ""),
                "target": str(found or target),
                "status": "done" if found else "missing",
                "size": Layout.file_size(found) if found else 0,
                "size_est_mb": PDF_MB,
                "url": document["url"],
                "ext": ".pdf",
            }))

        counts = _count(items)
        selected = [i for i in items if _is_selected(i, kinds, only_missing, explicit)]
        for item in items:
            item["selected"] = item in selected
        chapters_out.append({
            "name": chapter_name,
            "dir": str(chapter_dir),
            "pdf_only": pdf_only,
            "counts": counts,
            "items": items,
            "selected_count": len(selected),
        })
        all_items.extend(items)

    selected_items = [i for c in chapters_out for i in c["items"] if i["selected"]]
    summary = _count(all_items)
    summary.update({
        "selected": len(selected_items),
        "selected_est_mb": round(sum(float(i.get("size_est_mb") or 0) for i in selected_items), 1),
        "selected_est_gb": round(sum(float(i.get("size_est_mb") or 0) for i in selected_items) / 1024, 2),
        "by_kind": {kind: _count([i for i in all_items if i["kind"] == kind]) for kind in ALL_KINDS},
    })

    return {
        "subject": catalog.get("subject", {}),
        "subject_key": catalog.get("key", ""),
        "root": str(subject_dir),
        "free_gb": free_space_gb(subject_dir),
        "catalog_at": catalog.get("fetched_at", ""),
        "kinds": kinds,
        "chapters": chapters_out,
        "items": all_items,
        "selected_items": selected_items,
        "summary": summary,
    }


def _is_selected(item: dict, kinds: list[str], only_missing: bool, explicit: set[str]) -> bool:
    if item["status"] == "unavailable":
        return False
    if explicit:
        return item["id"] in explicit
    if item["kind"] not in kinds:
        return False
    if only_missing and item["status"] != "missing":
        return False
    return True


def _count(items: list[dict]) -> dict:
    counts = {"total": len(items), "done": 0, "missing": 0, "unavailable": 0}
    for item in items:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    return counts


def plan_for_subject(record: dict, settings, **filters) -> dict:
    """Load the cached catalog for a registered subject and build its plan."""
    catalog = state.load_catalog(record["key"])
    if not catalog:
        raise FileNotFoundError(f"{record.get('subject_name')} ka catalog nahi hai — pehle 'Catalog refresh' chalao.")
    catalog["subject_record"] = record
    return build_plan(catalog, settings, **filters)
