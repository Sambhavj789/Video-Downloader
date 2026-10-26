"""Catalog builder — one subject's full tree, cached in ``state/catalogs/<key>.json``.

A catalog is the *site* truth: chapters, videos (with duration and media URL) and
every attachment (notes/DPP/slides). Whether a file already exists on disk is a
different question, answered by :mod:`vd.plan` — that separation is what makes
"download only what is missing" reliable.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Callable

from . import names
from .proxy import MetadataClient, ProxyError, duration_seconds
from .stream import Schedule, SessionExpired, StreamClient, StreamError

ProgressFn = Callable[[dict], None]


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _video_topic(raw: dict) -> str:
    topic = (raw.get("topic") or "").strip()
    if topic:
        return topic
    details = raw.get("videoDetails") or {}
    return (details.get("name") or "").strip() or "Untitled lecture"


def _attachment_list(items: list[dict], kind: str) -> list[dict]:
    """Normalise NOTES/DPP_NOTES/SLIDES entries from the schedule page."""
    out = []
    for item in items or []:
        if kind == "slides":
            url = item.get("image") or item.get("url") or ""
        else:
            url = item.get("url") or ""
        if not url:
            continue
        out.append({
            "name": (item.get("name") or f"{kind} item").strip(),
            "url": url,
            "kind": kind,
            "timestamp": item.get("timestamp"),
            "ext": ".jpg" if kind == "slides" else ".pdf",
        })
    return out


class CatalogBuilder:
    """Fetch one subject tree with bounded concurrency."""

    def __init__(self, settings, cookies: dict, deep: bool = True, progress: ProgressFn | None = None):
        self.settings = settings
        self.cookies = cookies
        self.deep = deep
        self.progress = progress or (lambda event: None)
        self._semaphore = asyncio.Semaphore(max(1, settings.fetch_workers))

    def _emit(self, **event) -> None:
        try:
            self.progress(event)
        except Exception:
            pass

    async def build(self, record: dict) -> dict:
        batch_id = record["batch_id"]
        subject_id = record["subject_id"]
        self._emit(phase="catalog", step="topics", message="chapters load ho rahe hain")

        async with MetadataClient() as meta, StreamClient(self.cookies) as stream:
            topics = await meta.topics(batch_id, subject_id)
            if not topics:
                raise ProxyError("Is subject me koi chapter nahi mila (link galat ya course khaali).")
            self._emit(phase="catalog", step="chapters", done=0, total=len(topics),
                       message=f"{len(topics)} chapters")

            chapters = []
            for index, chapter in enumerate(topics, start=1):
                built = await self._build_chapter(meta, stream, batch_id, subject_id, chapter)
                chapters.append(built)
                self._emit(phase="catalog", step="chapters", done=index, total=len(topics),
                           message=built["name"])

        catalog = {
            "version": 2,
            "key": record["key"],
            "batch": {"id": batch_id, "name": record.get("batch_name", "")},
            "subject": {"id": subject_id, "name": record.get("subject_name", "")},
            "fetched_at": _now(),
            "deep": self.deep,
            "chapters": chapters,
            "totals": summarize(chapters),
        }
        return catalog

    # -- chapters ------------------------------------------------------------
    async def _build_chapter(self, meta: MetadataClient, stream: StreamClient,
                             batch_id: str, subject_id: str, chapter: dict) -> dict:
        chapter_id = chapter.get("_id", "")
        chapter_name = (chapter.get("name") or "Chapter").strip()
        raw_videos = await meta.videos(batch_id, subject_id, chapter_id)
        raw_notes = [] if raw_videos else await meta.notes(batch_id, subject_id, chapter_id)

        videos = [self._base_video(item, chapter_name) for item in raw_videos]
        documents: list[dict] = []

        if raw_videos:
            await self._enrich_videos(stream, batch_id, subject_id, videos)
        else:
            documents = await self._documents_from_schedules(stream, batch_id, subject_id,
                                                            raw_notes, chapter_name)

        pdf_only = names.chapter_is_pdf_only(chapter_name)
        return {
            "id": chapter_id,
            "name": chapter_name,
            "pdf_only": pdf_only or (not videos and bool(documents)),
            "videos": videos,
            "documents": documents,
        }

    def _base_video(self, raw: dict, chapter_name: str) -> dict:
        details = raw.get("videoDetails") or {}
        url = (raw.get("url") or details.get("videoUrl") or "").strip()
        return {
            "id": raw.get("_id", ""),
            "topic": _video_topic(raw),
            "chapter": chapter_name,
            "duration_s": duration_seconds(details.get("duration")),
            "date": (raw.get("date") or "")[:10],
            "status": raw.get("status", ""),
            "has_media": bool(url),
            "has_attachment": bool(raw.get("hasAttachment")),
            "dpp_notes": bool(raw.get("isDPPNotes")),
            "media_url": url,
            "notes": [],
            "dpp": [],
            "slides": [],
            "attachments_scanned": False,
            "scan_ok": None,
        }

    async def _enrich_videos(self, stream: StreamClient, batch_id: str, subject_id: str,
                             videos: list[dict]) -> None:
        """Fetch each schedule page to learn notes/DPP/slides (bounded parallel)."""
        if not self.deep:
            pending = [v for v in videos if v["has_attachment"] or v["dpp_notes"]]
        else:
            pending = videos

        async def worker(video: dict) -> None:
            async with self._semaphore:
                last: Exception | None = None
                for attempt in range(4):
                    try:
                        schedule = await stream.schedule(batch_id, subject_id, video["id"])
                    except SessionExpired:
                        raise
                    except StreamError as exc:
                        last = exc
                        if attempt == 3:
                            break
                        # 429 = rate limit: back off harder than a normal hiccup.
                        rate_limited = "429" in str(exc)
                        await asyncio.sleep((10 if rate_limited else 2) * (attempt + 1))
                        continue
                    apply_schedule(video, schedule)
                    return
                # A failed scan is "unknown", not "nothing there": keep it retryable.
                video["scan_ok"] = False
                if last is not None:
                    video["scan_error"] = str(last)[:160]

        tasks = [asyncio.create_task(worker(v)) for v in pending if v["id"]]
        if not tasks:
            return
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, SessionExpired):
                raise result
            if isinstance(result, Exception):
                continue

    async def _documents_from_schedules(self, stream: StreamClient, batch_id: str,
                                        subject_id: str, raw_notes: list[dict],
                                        chapter_name: str) -> list[dict]:
        """PDF-only shelves: one schedule per document, PDF link in ``NOTES``."""
        if not raw_notes:
            return []
        async def worker(item: dict) -> list[dict]:
            async with self._semaphore:
                try:
                    schedule = await stream.schedule(batch_id, subject_id, item.get("_id", ""))
                except Exception:
                    return []
                return _attachment_list(schedule.notes + schedule.dpp, "notes")

        results = await asyncio.gather(*(worker(item) for item in raw_notes))
        documents: list[dict] = []
        seen: set[str] = set()
        for group in results:
            for doc in group:
                if doc["url"] in seen:
                    continue
                seen.add(doc["url"])
                doc["chapter"] = chapter_name
                doc["kind"] = "ebook"
                documents.append(doc)
        return documents


def apply_schedule(video: dict, schedule: Schedule) -> None:
    """Copy attachments from a schedule page onto its catalog video entry."""
    video["notes"] = _attachment_list(schedule.notes, "notes")
    video["dpp"] = _attachment_list(schedule.dpp, "dpp")
    video["slides"] = _attachment_list(schedule.slides, "slides")
    video["attachments_scanned"] = True
    video["scan_ok"] = True
    video["has_media"] = video["has_media"] or schedule.has_video


def summarize(chapters: list[dict]) -> dict:
    videos = [v for c in chapters for v in c.get("videos", [])]
    documents = [d for c in chapters for d in c.get("documents", [])]
    return {
        "chapters": len(chapters),
        "videos": len(videos),
        "documents": len(documents),
        "notes": sum(len(v.get("notes", [])) for v in videos) + len(documents),
        "dpp": sum(len(v.get("dpp", [])) for v in videos),
        "slides": sum(len(v.get("slides", [])) for v in videos),
        "duration_s": sum(int(v.get("duration_s") or 0) for v in videos),
        "missing_media": sum(1 for v in videos if not v.get("has_media")),
        "scan_failed": sum(1 for v in videos if v.get("scan_ok") is False),
    }


async def build_catalog(record: dict, settings, cookies: dict, deep: bool = True,
                        progress: ProgressFn | None = None) -> dict:
    """Build (and return) the catalog for one registered subject."""
    builder = CatalogBuilder(settings, cookies, deep=deep, progress=progress)
    return await builder.build(record)
