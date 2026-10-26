"""Metadata client — chapter/video lists through the site's JSON proxy.

``api.penpencil.co`` now rejects the old Bearer token (401) and the site itself no
longer embeds ``PW_HEADERS``. What works (verified 2026-10-25) is the proxy the new
site calls from the browser::

    https://proxy.streamvideo.co.in/fetch/api.penpencil.co/v2/...

Cloudflare blocks ``curl_cffi``/``aiohttp`` on that host, but a real Chromium request
context gets ``200`` even without a session. So metadata goes through Playwright;
media (CDN segments) and PDFs stay on fast HTTP clients.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

PROXY_ROOT = "https://proxy.streamvideo.co.in/fetch/api.penpencil.co"
PROXY_BASE = f"{PROXY_ROOT}/v2"
BROWSER_HEADERS = {
    "origin": "https://stream.testuk.org",
    "referer": "https://stream.testuk.org/",
}


class ProxyError(RuntimeError):
    """Metadata could not be fetched (Playwright missing, blocked, bad payload)."""


class MetadataClient:
    """Async wrapper around one headless Chromium request context."""

    def __init__(self, timeout_ms: int = 45_000, retries: int = 3):
        self.timeout_ms = timeout_ms
        self.retries = retries
        self._pw = None
        self._browser = None
        self._context = None

    async def __aenter__(self) -> "MetadataClient":
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:  # pragma: no cover - environment problem
            raise ProxyError(
                "playwright install nahi hai. Chalao: pip install playwright && python -m playwright install chromium"
            ) from exc
        self._pw = await async_playwright().start()
        try:
            self._browser = await self._pw.chromium.launch(headless=True)
        except Exception as exc:  # pragma: no cover - browser not downloaded
            await self._pw.stop()
            raise ProxyError(f"Chromium launch fail: {exc}") from exc
        self._context = await self._browser.new_context()
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.close()

    async def close(self) -> None:
        for closer in (self._context, self._browser):
            if closer is not None:
                try:
                    await closer.close()
                except Exception:
                    pass
        self._context = self._browser = None
        if self._pw is not None:
            try:
                await self._pw.stop()
            except Exception:
                pass
            self._pw = None

    async def get_json(self, path: str) -> dict:
        """GET ``PROXY_BASE + path`` and parse JSON, with retries."""
        return await self._get(f"{PROXY_BASE}{path}")

    async def get_json_version(self, path: str, version: str = "v2") -> dict:
        """Some endpoints only exist under another version (``v3/batches/<id>/details``)."""
        return await self._get(f"{PROXY_ROOT}/{version}{path}")

    async def _get(self, url: str) -> dict:
        if self._context is None:
            raise ProxyError("MetadataClient start nahi hua (use 'async with').")
        last = "unknown"
        for attempt in range(1, self.retries + 1):
            try:
                response = await self._context.request.get(
                    url, headers=BROWSER_HEADERS, timeout=self.timeout_ms
                )
                body = await response.text()
                if response.status != 200:
                    last = f"HTTP {response.status}: {body[:160]}"
                else:
                    try:
                        return json.loads(body)
                    except json.JSONDecodeError:
                        last = f"non-JSON response: {body[:160]}"
            except Exception as exc:  # network hiccup inside the browser
                last = f"{type(exc).__name__}: {exc}"
            if attempt < self.retries:
                await asyncio.sleep(1.5 * attempt)
        raise ProxyError(f"{url} -> {last}")

    async def _paged(self, path: str, page_size: int, page_param: str = "page",
                     max_pages: int = 60) -> list[dict]:
        items: list[dict] = []
        page = 1
        while page <= max_pages:
            joiner = "&" if "?" in path else "?"
            payload = await self.get_json(f"{path}{joiner}{page_param}={page}")
            if not payload.get("success"):
                raise ProxyError(f"{path} page {page}: {payload.get('message') or 'success=false'}")
            data = payload.get("data") or []
            items.extend(data)
            if len(data) < page_size:
                break
            page += 1
        return items

    # -- endpoints -----------------------------------------------------------
    async def subjects(self, batch_id: str) -> list[dict]:
        """Every subject of a batch — lets the UI offer a picker instead of URLs."""
        payload = await self.get_json_version(f"/batches/{batch_id}/details", version="v3")
        if not payload.get("success"):
            raise ProxyError(f"batch {batch_id}: {payload.get('message') or 'success=false'}")
        data = payload.get("data") or {}
        return [item for item in data.get("subjects") or [] if isinstance(item, dict)]

    async def topics(self, batch_id: str, subject_id: str) -> list[dict]:
        """Chapters of one subject."""
        return await self._paged(
            f"/batches/{batch_id}/subject/{subject_id}/topics", page_size=10
        )

    async def videos(self, batch_id: str, subject_id: str, chapter_id: str) -> list[dict]:
        """Video schedules in one chapter."""
        return await self._paged(
            f"/batches/{batch_id}/subject/{subject_id}/contents"
            f"?contentType=videos&tag={chapter_id}", page_size=20
        )

    async def notes(self, batch_id: str, subject_id: str, chapter_id: str) -> list[dict]:
        """Note/PDF schedules in one chapter (used by PDF-only shelves)."""
        return await self._paged(
            f"/batches/{batch_id}/subject/{subject_id}/contents"
            f"?contentType=notes&tag={chapter_id}", page_size=20
        )


def duration_seconds(text: Any) -> int:
    """``"02:03:40"`` -> 7420; ``"12:34"`` -> 754; junk -> 0."""
    if isinstance(text, (int, float)):
        return int(text)
    parts = str(text or "").strip().split(":")
    try:
        values = [int(float(p)) for p in parts if p != ""]
    except ValueError:
        return 0
    seconds = 0
    for value in values[-3:]:
        seconds = seconds * 60 + value
    return seconds
