"""UI server: pure handlers + one real HTTP round-trip on an ephemeral port.

Nothing here opens the real library or the real catalog: every store the handlers
touch is patched to a tmp path, so the tests also document what each endpoint owns.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from vd.config import Settings
from vd.ui import server


@pytest.fixture()
def fake_env(tmp_path, monkeypatch, settings, record, catalog):
    """Point the server at a tmp library and one registered subject."""
    from vd import state

    monkeypatch.setattr(Settings, "load", classmethod(lambda cls: settings))
    monkeypatch.setattr(Settings, "save", lambda self: None)
    monkeypatch.setattr(server.links, "find_subject", lambda key: record if key == record["key"] else None)
    monkeypatch.setattr(server.links, "sorted_subjects", lambda: [record])
    monkeypatch.setattr(server.links, "remove_subject", lambda key: key == record["key"])
    monkeypatch.setattr(server.auth, "load_cookies", lambda: {"session": "s", "cf_clearance": "c"})
    monkeypatch.setattr(server.auth, "cookie_summary", lambda cookies: {
        "count": len(cookies), "names": sorted(cookies),
        "has_session": True, "has_clearance": True, "source": "test",
    })
    monkeypatch.setattr(server.state, "subjects_with_catalog", lambda: [{**record, "has_catalog": True,
                                                                       "catalog_age_days": 1.0,
                                                                       "totals": {"videos": 2}}])
    monkeypatch.setattr(server.state, "report_file", lambda key: tmp_path / "reports" / f"{key}.md")
    monkeypatch.setattr(state, "load_catalog", lambda key: catalog if key == record["key"] else None)
    return settings


def test_overview_shape(fake_env):
    data = server.overview()
    assert data["version"] == "2.0.0"
    assert data["settings"]["concurrency"] == fake_env.concurrency
    assert data["subjects"][0]["has_catalog"] is True
    assert data["session"]["has_session"] is True
    assert "job" in data


def test_api_plan_needs_a_key(fake_env):
    with pytest.raises(ValueError):
        server.api_plan({})


def test_api_plan_unknown_subject(fake_env):
    with pytest.raises(FileNotFoundError):
        server.api_plan({"key": ["nope"]})


def test_api_plan_returns_chapters_without_inline_items(fake_env):
    plan = server.api_plan({"key": ["auditing-and-ethics"]})
    assert plan["subject_key"] == "auditing-and-ethics"
    assert "items" not in plan and "selected_items" not in plan
    assert plan["chapters"][0]["name"] == "Audit Evidence"
    assert {item["kind"] for item in plan["chapters"][0]["items"]} == {"videos", "notes"}
    assert all(isinstance(item_id, str) for item_id in plan["selected_ids"])


def test_api_plan_kind_filter(fake_env):
    plan = server.api_plan({"key": ["auditing-and-ethics"], "kinds": ["documents"]})
    kinds = {item["kind"] for chapter in plan["chapters"] for item in chapter["items"]
             if item["selected"]}
    assert kinds == {"documents"}


def test_api_add_subject_rejects_a_link_without_ids():
    result = server.api_add_subject({"url": "https://stream.testuk.org/content"})
    assert result["ok"] is False
    assert "batchId" in result["error"]


def test_api_add_subject_checks_the_url(monkeypatch):
    captured = {}

    def fake_add(url, dir_name=""):
        captured["url"] = url
        captured["dir"] = dir_name
        return {"key": "k", "subject_name": "S"}

    monkeypatch.setattr(server.links, "add_subject", fake_add)
    result = server.api_add_subject({
        "url": "https://stream.testuk.org/content?batchId=b&subjectId=s&subjectName=S",
        "dir": "Audit",
    })
    assert result["ok"] is True
    assert captured["dir"] == "Audit"


def test_api_download_validates_input(fake_env):
    with pytest.raises(ValueError):
        server.api_start_download({"key": "auditing-and-ethics", "ids": []})


def test_api_status_writes_the_report(fake_env, tmp_path, monkeypatch):
    written = {}

    def fake_write(record, plan, path):
        written["path"] = path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# report", encoding="utf-8")
        return path

    monkeypatch.setattr(server.report, "write_subject_report", fake_write)
    result = server.api_status({"key": "auditing-and-ethics"})
    assert result["ok"] is True
    assert written["path"].exists()
    assert result["missing"]["videos"] == 1


def test_api_settings_clamps_concurrency(fake_env, monkeypatch):
    monkeypatch.setattr(server.Settings, "load", classmethod(lambda cls: fake_env))
    result = server.api_settings({"concurrency": 99})
    assert result["settings"]["concurrency"] <= 8


def test_job_snapshot_tracks_events():
    job = server.Job("download", "download: k (2 items)")
    job.on_event({"type": "start", "total": 2})
    job.on_event({"type": "item_start", "index": 1, "total": 2, "item": {"name": "A", "kind": "videos"}})
    job.on_event({"type": "progress", "phase": "segments", "segments_done": 5,
                  "segments_total": 10, "bytes": 1024})
    snapshot = job.snapshot()
    assert snapshot["progress"]["current"] == "A"
    assert snapshot["progress"]["segments_done"] == 5
    assert snapshot["status"] == "running"
    assert any("A" in line for line in snapshot["log"])

    job.on_event({"type": "error", "error": "boom"})
    assert job.snapshot()["error"] == "boom"

    job.stop()
    assert job.stop_flag.is_set()


def test_job_manager_refuses_a_second_running_job(monkeypatch):
    manager = server.JobManager()
    started = []

    async def slow(job):
        started.append(job.id)

    first = server.Job("catalog", "one")
    assert manager.start(first, slow)[0] is True
    first.thread.join(5)
    second = server.Job("catalog", "two")
    ok, _ = manager.start(second, slow)
    assert ok is True          # first already finished
    second.thread.join(5)
    assert len(started) == 2


def test_job_manager_marks_a_cancelled_job_stopped():
    manager = server.JobManager()

    async def cancelled(job):
        raise server.asyncio.CancelledError()

    job = server.Job("catalog", "cancel me")
    assert manager.start(job, cancelled)[0] is True
    job.thread.join(5)
    assert job.snapshot()["status"] == "stopped"


@pytest.fixture()
def live_server(fake_env, monkeypatch):
    monkeypatch.setattr(server, "JOBS", server.JobManager())
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        yield base
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(5)


def _call(base: str, path: str, method: str = "GET", body: dict | None = None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def test_http_overview_and_job(live_server):
    status, body = _call(live_server, "/api/overview")
    assert status == 200
    assert json.loads(body)["version"] == "2.0.0"

    status, body = _call(live_server, "/api/job")
    assert status == 200
    assert json.loads(body) == {"job": None}


def test_http_index_and_static(live_server):
    status, body = _call(live_server, "/")
    assert status == 200 and "Offline Downloader" in body

    status, body = _call(live_server, "/static/app.js")
    assert status == 200 and "api(" in body


def test_http_unknown_route(live_server):
    status, _ = _call(live_server, "/api/nope")
    assert status == 404


def test_http_bad_json_body(live_server):
    request = urllib.request.Request(live_server + "/api/settings", data=b"{oops",
                                     method="POST", headers={"Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as info:
        urllib.request.urlopen(request, timeout=10)
    assert info.value.code == 400


def test_http_status_endpoint(live_server, monkeypatch, tmp_path):
    monkeypatch.setattr(server.report, "write_subject_report",
                        lambda record, plan, path: path)
    status, body = _call(live_server, "/api/status", "POST", {"key": "auditing-and-ethics"})
    assert status == 200
    assert json.loads(body)["ok"] is True
