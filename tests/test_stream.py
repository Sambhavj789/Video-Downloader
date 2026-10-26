"""Stream-domain parsing: the page is the only source of notes/DPP/slides/keys."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

from vd import stream
from vd.stream import Schedule, SessionExpired, StreamClient

PAGE = """
<script>
const NOTES = [{"name": "Notes 1", "url": "https://static/notes1.pdf", "timestamp": "2026-01-01"}];
const DPP_NOTES = [{"name": "DPP 1", "url": "https://static/dpp1.pdf"}];
const SLIDES = [{"name": "Slide 1", "image": "https://static/slide1.jpg"}];
MEDIA_TOKEN = "tok_abc123";
</script>
"""


def test_parse_js_arrays_reads_each_list():
    notes = stream.parse_js_array(PAGE, "NOTES")
    dpp = stream.parse_js_array(PAGE, "DPP_NOTES")
    slides = stream.parse_js_array(PAGE, "SLIDES")
    assert notes[0]["name"] == "Notes 1"
    assert dpp[0]["url"] == "https://static/dpp1.pdf"
    assert slides[0]["image"] == "https://static/slide1.jpg"


def test_parse_js_array_is_forgiving():
    assert stream.parse_js_array("", "NOTES") == []
    assert stream.parse_js_array("const NOTES = not-json;", "NOTES") == []
    assert stream.parse_js_array("const NOTES = [1, 2];", "NOTES") == []


def test_parse_media_token():
    assert stream.parse_media_token(PAGE) == "tok_abc123"
    assert stream.parse_media_token("nothing here") == ""


def test_parse_video_data_block():
    html = 'window.VIDEO_DATA = {"url": "https://cdn/x.mpd", "keys": ["kid:key"]};'
    data = stream.parse_video_data_block(html)
    assert data["url"] == "https://cdn/x.mpd"


def test_extract_key_supports_all_shapes():
    assert stream.extract_key({"key_strings": "--key kid:abc123"}) == "abc123"
    assert stream.extract_key({"keys": ["kid:def456"]}) == "def456"
    assert stream.extract_key({"keys": {"1": "ghi789"}}) == "ghi789"
    assert stream.extract_key({}) is None


def test_schedule_has_video_only_with_a_token():
    assert Schedule(schedule_id="s", media_token="t").has_video is True
    assert Schedule(schedule_id="s").has_video is False


def test_schedule_to_dict_hides_the_token():
    data = Schedule(schedule_id="s", media_token="secret", topic="T").to_dict()
    assert "media_token" not in data
    assert data["has_video"] is True


def test_schedule_url_encodes_every_param():
    client = StreamClient({})
    url = client.schedule_url("b id", "s id", "sched id")
    query = parse_qs(urlparse(url).query)
    assert query["batchId"] == ["b id"]
    assert query["tap"] == ["video"]
    assert url.startswith("https://stream.testuk.org/schedule-details?")


def test_blocked_detection_covers_cloudflare_and_keygenerate():
    assert StreamClient._looks_blocked(403, "")
    assert StreamClient._looks_blocked(401, "")
    assert StreamClient._looks_blocked(200, "<title>Just a moment...</title>")
    assert StreamClient._looks_blocked(200, 'location.href="/keygenerate"')
    assert not StreamClient._looks_blocked(200, PAGE)


def test_session_expired_is_a_stream_error():
    assert isinstance(SessionExpired("x", 403), stream.StreamError)


def test_check_session_without_cookies_is_not_an_exception():
    import asyncio

    result = asyncio.run(stream.check_session({}, "b", "s"))
    assert result["ok"] is False
    assert result["detail"] == "cookies nahi mile"


def test_schedule_parse_of_real_page_shape():
    """The schedule object must expose notes + dpp + slides without touching cookies."""
    schedule = Schedule(
        schedule_id="s",
        media_token=stream.parse_media_token(PAGE),
        notes=stream.parse_js_array(PAGE, "NOTES"),
        dpp=stream.parse_js_array(PAGE, "DPP_NOTES"),
        slides=stream.parse_js_array(PAGE, "SLIDES"),
    )
    assert schedule.has_video
    assert json.dumps(schedule.to_dict())  # serialisable for logs/catalog
