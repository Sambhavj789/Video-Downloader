"""Metadata proxy: pagination, durations, link parsing and catalog summarising."""

from __future__ import annotations

import asyncio

import pytest

from vd import links, names
from vd.catalog import apply_schedule, summarize
from vd.proxy import MetadataClient, ProxyError, duration_seconds
from vd.stream import Schedule


def test_duration_seconds_handles_every_shape():
    assert duration_seconds("02:03:40") == 7420
    assert duration_seconds("12:34") == 754
    assert duration_seconds(3600) == 3600
    assert duration_seconds("") == 0
    assert duration_seconds("junk") == 0


def test_paged_stops_when_a_page_is_short():
    pages = {1: [{"_id": str(i)} for i in range(20)], 2: [{"_id": "x"}]}
    client = MetadataClient()

    async def fake_get_json(path: str) -> dict:
        page = int(path.rsplit("=", 1)[1])
        return {"success": True, "data": pages.get(page, [])}

    client.get_json = fake_get_json  # type: ignore[method-assign]
    items = asyncio.run(client._paged("/batches/b/subject/s/topics", page_size=20))
    assert len(items) == 21


def test_paged_raises_on_success_false():
    client = MetadataClient()

    async def fake_get_json(path: str) -> dict:
        return {"success": False, "message": "nope"}

    client.get_json = fake_get_json  # type: ignore[method-assign]
    with pytest.raises(ProxyError):
        asyncio.run(client._paged("/x", page_size=20))


def test_link_url_roundtrip():
    url = links.build_subject_url("b1", "s1", "Batch Name", "Auditing and Ethics")
    fields = links.parse_subject_url(url)
    assert fields == {
        "batch_id": "b1",
        "subject_id": "s1",
        "batch_name": "Batch Name",
        "subject_name": "Auditing and Ethics",
    }
    assert links.is_subject_url(url)
    assert links.batch_id_from("b1") == "b1"
    assert links.batch_id_from(url) == "b1"
    assert not links.is_subject_url("https://stream.testuk.org/content")


def test_schedule_attach_copies_notes_dpp_slides():
    video = {"topic": "T", "notes": [], "dpp": [], "slides": [], "has_media": False,
             "attachments_scanned": False}
    schedule = Schedule(
        schedule_id="s",
        media_token="tok",
        notes=[{"name": "N", "url": "https://x/n.pdf"}],
        dpp=[{"name": "D", "url": "https://x/d.pdf"}],
        slides=[{"name": "S", "image": "https://x/s.jpg"}],
    )
    apply_schedule(video, schedule)
    assert [n["name"] for n in video["notes"]] == ["N"]
    assert video["dpp"][0]["ext"] == ".pdf"
    assert video["slides"][0]["ext"] == ".jpg"
    assert video["has_media"] is True
    assert video["attachments_scanned"] is True


def test_summarize_counts_every_kind():
    chapters = [
        {
            "videos": [
                {"duration_s": 60, "has_media": True,
                 "notes": [{"url": "a"}], "dpp": [{"url": "b"}], "slides": [{"url": "c"}]},
                {"duration_s": 0, "has_media": False, "notes": [], "dpp": [], "slides": []},
            ],
            "documents": [{"url": "d"}],
        }
    ]
    totals = summarize(chapters)
    assert totals == {
        "chapters": 1,
        "videos": 2,
        "documents": 1,
        "notes": 2,
        "dpp": 1,
        "slides": 1,
        "duration_s": 60,
        "missing_media": 1,
        "scan_failed": 0,
    }


def test_subject_key_is_deterministic():
    assert names.subject_key("Taxation (GST)", "68dcfffc43b13b466630b439") == (
        "taxation-gst-68dcff"
    )
