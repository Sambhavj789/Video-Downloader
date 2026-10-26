"""DASH manifest parsing, track choice and local-MPD rewriting."""

from __future__ import annotations

import base64
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

import pytest

from vd import dash

MPD_URL = (
    "https://cdn.example/drm/abc/master.mpd"
    "?URLPrefix=" + quote(base64.b64encode(b"https://cdn.example/drm/abc").decode())
    + "&Policy=eyJ4IjoxfQ=="
    + "&Signature=abc"
    + "&Key-Pair-Id=K123"
)

MANIFEST = """<?xml version="1.0" encoding="utf-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" mediaPresentationDuration="PT600S">
  <Period id="0">
    <AdaptationSet contentType="video" mimeType="video/mp4">
      <ContentProtection schemeIdUri="urn:mpeg:dash:mp4protection:2011" value="cenc"/>
      <Representation id="v1" bandwidth="800000" width="1280" height="720" codecs="avc1.4d401f">
        <SegmentTemplate timescale="1000" initialization="v_init.mp4" media="v_$Number$.mp4">
          <SegmentTimeline><S t="0" d="4000" r="149"/></SegmentTimeline>
        </SegmentTemplate>
      </Representation>
      <Representation id="v2" bandwidth="400000" width="640" height="360" codecs="avc1.4d401e">
        <SegmentTemplate timescale="1000" initialization="v_init.mp4" media="v_$Number$.mp4">
          <SegmentTimeline><S t="0" d="4000" r="149"/></SegmentTimeline>
        </SegmentTemplate>
      </Representation>
    </AdaptationSet>
    <AdaptationSet contentType="audio" lang="en">
      <Representation id="a1" bandwidth="128000" codecs="mp4a.40.2">
        <SegmentTemplate timescale="1000" initialization="a_init.mp4" media="a_$Number$.mp4">
          <SegmentTimeline><S t="0" d="4000" r="149"/></SegmentTimeline>
        </SegmentTemplate>
      </Representation>
    </AdaptationSet>
  </Period>
</MPD>
"""


def test_split_mpd_url_decodes_the_base_and_keeps_auth():
    base, auth = dash.split_mpd_url(MPD_URL)
    assert base == "https://cdn.example/drm/abc/"
    assert "URLPrefix" not in auth
    assert parse_qs(auth)["Policy"] == ["eyJ4IjoxfQ=="]


def test_split_mpd_url_without_prefix_uses_the_mpd_folder():
    """New CDN sends relative segment paths and no URLPrefix."""
    base, auth = dash.split_mpd_url("https://cdn.example/stream/abc123/master.mpd")
    assert base == "https://cdn.example/stream/abc123/"
    assert auth == ""

    base, auth = dash.split_mpd_url("https://cdn.example/x.mpd?Policy=p")
    assert base == "https://cdn.example/"
    assert parse_qs(auth) == {"Policy": ["p"]}


def test_parse_manifest_reads_tracks_and_encryption():
    manifest = dash.parse_manifest(MANIFEST, MPD_URL)
    assert manifest.encrypted is True
    assert manifest.duration == "PT600S"
    kinds = sorted(t.kind for t in manifest.tracks)
    assert kinds == ["audio", "video", "video"]
    video = next(t for t in manifest.tracks if t.kind == "video")
    assert video.count == 150
    assert video.height == 720


def test_parse_manifest_rejects_garbage():
    with pytest.raises(dash.DashError):
        dash.parse_manifest("<not-xml", MPD_URL)


def test_parse_manifest_requires_a_video_track():
    audio_only = MANIFEST.replace('contentType="video"', 'contentType="audio"')
    with pytest.raises(dash.DashError):
        dash.parse_manifest(audio_only, MPD_URL)


def test_choose_tracks_prefers_highest_by_default_and_honours_quality():
    manifest = dash.parse_manifest(MANIFEST, MPD_URL)
    video, audio = dash.choose_tracks(manifest)
    assert (video.height, audio.kind) == (720, "audio")
    small, _ = dash.choose_tracks(manifest, "360")
    assert small.height == 360


def test_choose_tracks_errors_when_audio_missing():
    no_audio = MANIFEST.split('<AdaptationSet contentType="audio"')[0] + "</Period></MPD>"
    manifest = dash.parse_manifest(no_audio, MPD_URL)
    with pytest.raises(dash.DashError):
        dash.choose_tracks(manifest)


def test_segment_urls_carry_auth_and_are_numbered():
    manifest = dash.parse_manifest(MANIFEST, MPD_URL)
    video, _ = dash.choose_tracks(manifest)
    items = dash.segment_urls(manifest, video)
    assert items[0][1] == "720p_init.mp4"
    assert items[0][0].startswith("https://cdn.example/drm/abc/v_init.mp4?")
    assert "Policy=" in items[0][0]
    assert items[1] == (items[1][0], "720p_1.mp4")
    assert len(items) == 151


def test_relative_segment_paths_resolve_against_the_mpd_folder():
    """streamvideo.co.in manifest: no URLPrefix, segments like ``dash/720/1.mp4``."""
    relative = MANIFEST.replace('initialization="v_init.mp4"', 'initialization="dash/720/init.mp4"') \
                       .replace('media="v_$Number$.mp4"', 'media="dash/720/$Number$.mp4"') \
                       .replace('initialization="a_init.mp4"', 'initialization="dash/audio/init.mp4"') \
                       .replace('media="a_$Number$.mp4"', 'media="dash/audio/$Number$.mp4"')
    url = "https://cdn.example/stream/abc123/master.mpd"
    manifest = dash.parse_manifest(relative, url)
    video, _ = dash.choose_tracks(manifest)
    items = dash.segment_urls(manifest, video)
    assert manifest.base_url == "https://cdn.example/stream/abc123/"
    assert items[0][0] == "https://cdn.example/stream/abc123/dash/720/init.mp4"
    assert items[1][0] == "https://cdn.example/stream/abc123/dash/720/1.mp4"


def test_build_local_mpd_points_at_local_files(tmp_path: Path):
    manifest = dash.parse_manifest(MANIFEST, MPD_URL)
    video, audio = dash.choose_tracks(manifest)
    path = dash.build_local_mpd(manifest, video, audio, tmp_path)
    text = path.read_text(encoding="utf-8")
    assert path.name == "local.mpd"
    assert "720p_init.mp4" in text and "720p_$Number$.mp4" in text
    assert "audio_init.mp4" in text
    assert "urn:mpeg:dash:mp4protection:2011" in text
    assert "URLPrefix" not in text


def test_ffmpeg_binary_exists():
    assert Path(dash.ffmpeg_exe()).name.lower().startswith("ffmpeg")


def test_cdn_headers_look_like_a_browser():
    """Cloudflare 403s library user agents on the manifest and every segment."""
    assert dash.CDN_HEADERS["User-Agent"].startswith("Mozilla/5.0")
    assert dash.CDN_HEADERS["Referer"].startswith("https://stream.testuk.org")
    assert dash.CDN_HEADERS["Origin"] == "https://stream.testuk.org"
    assert all(isinstance(v, str) and v for v in dash.CDN_HEADERS.values())


def test_curl_segment_fetch_sends_browser_headers(monkeypatch, tmp_path: Path):
    import asyncio

    captured: dict = {}

    class FakeProc:
        returncode = 0

        async def communicate(self):
            return (b"200", b"")

    async def fake_exec(*args, **kwargs):
        captured["argv"] = list(args)
        return FakeProc()

    monkeypatch.setattr(dash, "which_curl", lambda: "curl")
    monkeypatch.setattr(dash.asyncio, "create_subprocess_exec", fake_exec)

    ok = asyncio.run(dash._fetch_with_curl("https://cdn.example/s1.mp4", tmp_path / "s1.mp4", 10))

    assert ok is True
    argv = captured["argv"]
    assert "-H" in argv
    joined = " ".join(argv)
    assert "Mozilla/5.0" in joined
    assert "Referer: https://stream.testuk.org/" in joined


def test_urlparse_roundtrip_of_auth_query_keeps_signature():
    _, auth = dash.split_mpd_url(MPD_URL)
    parsed = urlparse("https://cdn/x.mpd?" + auth)
    assert parsed.query

def test_mux_uses_a_part_file_then_renames(tmp_path, monkeypatch):
    """A dropped drive must never leave a half written .mp4 (that would count as done)."""
    import os

    target = tmp_path / "lecture.mp4"
    seen = {}

    def fake_ffmpeg(mpd, out_fs, key):
        seen["path"] = out_fs
        with open(out_fs, "wb") as handle:
            handle.write(b"x" * 2048)
        return 0, ""

    monkeypatch.setattr(dash, "_run_ffmpeg", fake_ffmpeg)
    ok, error, size = dash._mux_to_target(tmp_path / "local.mpd", target, None)

    assert ok is True and error == "" and size == 2048
    assert seen["path"].endswith("lecture.mp4.part")
    assert target.read_bytes()[:1] == b"x"
    assert not (tmp_path / "lecture.mp4.part").exists()


def test_failed_mux_removes_the_part_file(tmp_path, monkeypatch):
    target = tmp_path / "lecture.mp4"

    def broken_ffmpeg(mpd, out_fs, key):
        with open(out_fs, "wb") as handle:
            handle.write(b"partial")
        return 1, "conversion failed"

    monkeypatch.setattr(dash, "_run_ffmpeg", broken_ffmpeg)
    ok, error, size = dash._mux_to_target(tmp_path / "local.mpd", target, None)

    assert ok is False and "ffmpeg fail" in error and size == 0
    assert not target.exists()
    assert not (tmp_path / "lecture.mp4.part").exists()
