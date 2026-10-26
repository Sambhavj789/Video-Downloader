"""Session cookies for ``stream.testuk.org``.

The stream domain sits behind Cloudflare: plain HTTP clients are rejected, only
``curl_cffi`` (Chrome TLS fingerprint) with a browser-issued ``cf_clearance`` and
``session`` cookie gets through. Those two values are the whole "login".

Rules:
* cookies are never printed, logged or written into docs;
* they live in ``config/cookies.json`` (gitignored). The legacy
  ``stream_cookies.json`` in the project root is still read until it is moved.
"""

from __future__ import annotations

import json
from pathlib import Path

from .config import CONFIG_DIR, PROJECT_ROOT

COOKIE_FILE = CONFIG_DIR / "cookies.json"
LEGACY_COOKIE_FILE = PROJECT_ROOT / "stream_cookies.json"

REQUIRED_ANY = ("session", "cf_clearance")


def cookie_path() -> Path | None:
    for path in (COOKIE_FILE, LEGACY_COOKIE_FILE):
        if path.exists():
            return path
    return None


def load_cookies() -> dict:
    path = cookie_path()
    if not path:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    # accept both {"session": "..."} and a Playwright export [{"name": ...}]
    if isinstance(data.get("cookies"), dict):
        data = data["cookies"]
    return {str(k): str(v) for k, v in data.items() if v}


def save_cookies(cookies: dict) -> Path:
    if not cookies:
        raise ValueError("cookies khaali hain")
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = COOKIE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cookies, indent=2) + "\n", encoding="utf-8")
    tmp.replace(COOKIE_FILE)
    return COOKIE_FILE


def cookie_summary(cookies: dict) -> dict:
    """Names only — never values."""
    names = sorted(cookies)
    return {
        "count": len(names),
        "names": names,
        "has_session": "session" in cookies,
        "has_clearance": "cf_clearance" in cookies,
        "source": str(cookie_path()) if cookie_path() else "",
    }
