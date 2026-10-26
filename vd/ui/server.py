"""Local browser UI — zero extra dependencies (stdlib ``http.server``).

The UI is a thin client over the same engine the CLI uses:

``GET  /api/overview``            settings, subjects, session, disk
``POST /api/subjects``            register a pasted subject URL
``POST /api/catalog``             refresh one subject's catalog (background job)
``GET  /api/plan?key=..&kinds=..`` chapters + items + disk status
``POST /api/download``            download the selected item ids (background job)
``GET  /api/job``                 progress snapshot + log tail
``POST /api/job/stop``            ask the running job to stop
``POST /api/status``              write the "kya bacha hai" report for one subject
``POST /api/session``             save pasted cookies and verify them
``POST /api/settings``            output root, concurrency, quality
``POST /api/clean``               delete temp segment folders

One job runs at a time on purpose: two parallel writers on one SSD only slow both
down and make the site push back.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
import traceback
import webbrowser
from collections import deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .. import auth, links, names, plan as plan_mod, report, state
from ..catalog import build_catalog
from ..config import LOG_DIR, PROJECT_ROOT, Settings, ensure_dirs, free_space_gb
from ..downloader import DownloadRunner
from ..stream import check_session

STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_BODY = 4 * 1024 * 1024


class Job:
    """One background task (catalog or download) plus its progress snapshot."""

    def __init__(self, kind: str, title: str):
        self.id = f"{int(time.time() * 1000)}"
        self.kind = kind
        self.title = title
        self.status = "running"
        self.started_at = time.time()
        self.finished_at = 0.0
        self.error = ""
        self.progress: dict = {"phase": "start", "done": 0, "total": 0, "current": "", "message": ""}
        self.log: deque[str] = deque(maxlen=400)
        self.stop_flag = threading.Event()
        self.thread: threading.Thread | None = None

    # -- events from the engine ---------------------------------------------
    def on_event(self, event: dict) -> None:
        kind = event.get("type")
        if kind == "log":
            self.push_log(event.get("message", ""))
            return
        if kind == "start":
            self.progress.update(total=event.get("total", 0), phase="start")
            self.push_log(f"start: {event.get('total', 0)} items")
        elif kind == "item_start":
            item = event.get("item", {})
            self.progress.update(
                phase="item", current=item.get("name", ""), item_kind=item.get("kind", ""),
                done=event.get("index", 1) - 1, total=event.get("total", 0),
                segments_done=0, segments_total=0, message="",
            )
            self.push_log(f"[{event.get('index')}/{event.get('total')}] {item.get('kind')}: {item.get('name', '')[:70]}")
        elif kind == "progress":
            if event.get("phase") == "segments":
                self.progress.update(
                    phase="segments",
                    segments_done=event.get("segments_done", 0),
                    segments_total=event.get("segments_total", 0),
                    bytes=event.get("bytes", 0),
                )
            elif event.get("phase") == "mux":
                self.progress.update(phase="mux", message="ffmpeg mux + decrypt")
        elif kind == "item_done":
            self.progress.update(done=event.get("index", 0), phase="item",
                                 bytes=event.get("bytes", 0),
                                 speed_mbps=event.get("speed_mbps", 0))
            self.push_log(f"  ok  {event.get('item', {}).get('name', '')[:70]}")
        elif kind == "item_fail":
            self.progress["failed"] = self.progress.get("failed", 0) + 1
            self.push_log(f"  fail {event.get('item', {}).get('name', '')[:60]}: {event.get('error', '')}")
        elif kind == "skip":
            self.push_log(f"  skip {event.get('item', {}).get('name', '')[:60]} (already local)")
        elif kind == "finish":
            self.progress.update(phase="finish", done=event.get("total", 0),
                                 bytes=event.get("bytes", 0), elapsed_s=event.get("elapsed_s", 0))
            self.push_log(
                f"finish: done={event.get('done')} failed={event.get('failed')} "
                f"skipped={event.get('skipped')} in {event.get('elapsed_s')}s"
            )
        elif kind == "error":
            self.error = event.get("error", "unknown")
            self.push_log(f"ERROR: {self.error}")
        elif kind == "catalog_progress":
            self.progress.update(phase="catalog", **{k: v for k, v in event.items()
                                                     if k in {"done", "total", "message", "step"}})

    def push_log(self, message: str) -> None:
        if not message:
            return
        self.log.append(f"{time.strftime('%H:%M:%S')} {message}"[:400])

    def snapshot(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "status": self.status,
            "error": self.error,
            "progress": self.progress,
            "elapsed_s": round((self.finished_at or time.time()) - self.started_at, 1),
            "log": list(self.log)[-120:],
        }

    def stop(self) -> None:
        self.stop_flag.set()
        self.push_log("stop requested")


class JobManager:
    def __init__(self):
        self._lock = threading.Lock()
        self.current: Job | None = None

    def busy(self) -> bool:
        with self._lock:
            return bool(self.current and self.current.status == "running")

    def snapshot(self) -> dict | None:
        with self._lock:
            return self.current.snapshot() if self.current else None

    def start(self, job: Job, target) -> tuple[bool, str]:
        """``target`` is a coroutine function taking the job as its argument."""
        with self._lock:
            if self.current and self.current.status == "running":
                return False, "ek job pehle se chal raha hai"
            self.current = job

        def runner() -> None:
            try:
                asyncio.run(target(job))
                if job.stop_flag.is_set():
                    job.status = "stopped"
                elif job.error:
                    job.status = "error"
                else:
                    job.status = "done"
            except asyncio.CancelledError:
                job.status = "stopped"
                job.push_log("job cancel ho gaya")
            except Exception as exc:
                job.status = "error"
                job.error = f"{type(exc).__name__}: {exc}"
                job.push_log(traceback.format_exc(limit=3))
            finally:
                job.finished_at = time.time()

        job.thread = threading.Thread(target=runner, name=f"job-{job.kind}", daemon=True)
        job.thread.start()
        return True, job.id


JOBS = JobManager()


# -- job bodies --------------------------------------------------------------
async def run_catalog_job(job: Job, key: str, deep: bool = True) -> None:
    settings = Settings.load()
    record = links.find_subject(key)
    if not record:
        raise RuntimeError(f"subject '{key}' registered nahi hai")
    cookies = auth.load_cookies()

    def on_event(event: dict) -> None:
        job.on_event({**event, "type": "catalog_progress"})
        if job.stop_flag.is_set():
            raise asyncio.CancelledError()

    job.push_log(f"catalog: {record.get('subject_name')} (deep={deep})")
    catalog = await build_catalog(record, settings, cookies, deep=deep, progress=on_event)
    if job.stop_flag.is_set():
        job.push_log("catalog rok diya — jo mila save nahi kiya")
        return
    state.save_catalog(key, catalog)
    totals = catalog["totals"]
    job.push_log(
        f"catalog saved: {totals['chapters']} chapters, {totals['videos']} videos, "
        f"{totals['notes']} notes, {totals['dpp']} dpp, {totals['slides']} slides"
    )
    job.progress.update(phase="finish", message="catalog ready")


async def run_download_job(job: Job, key: str, ids: list[str]) -> None:
    settings = Settings.load()
    record = links.find_subject(key)
    if not record:
        raise RuntimeError(f"subject '{key}' registered nahi hai")
    cookies = auth.load_cookies()
    if not cookies:
        raise RuntimeError("cookies nahi mile — Session panel me paste karo")

    plan = plan_mod.plan_for_subject(record, settings)
    by_id = {item["id"]: item for item in plan["items"]}
    items = [by_id[item_id] for item_id in ids if item_id in by_id]
    if not items:
        raise RuntimeError("selected items catalog me nahi mile — catalog refresh karo")

    runner = DownloadRunner(settings, cookies, record, on_event=job.on_event,
                            should_stop=job.stop_flag.is_set)
    log_path = LOG_DIR / f"run-{time.strftime('%Y%m%d-%H%M%S')}-{key[:20]}.log"
    ensure_dirs()
    log_file = open(log_path, "a", encoding="utf-8")
    try:
        def tee(event: dict) -> None:
            if event.get("type") == "log":
                log_file.write(event.get("message", "") + "\n")
                log_file.flush()
            job.on_event(event)

        runner.on_event = tee
        await runner.run(items)
    finally:
        log_file.close()
    updated = plan_mod.plan_for_subject(record, settings)
    report.write_subject_report(record, updated, state.report_file(key))
    job.push_log(f"report: {state.report_file(key)}")


async def run_session_job(job: Job, cookies: dict) -> None:
    record = links.sorted_subjects()[0] if links.sorted_subjects() else None
    if record and cookies:
        result = await check_session(cookies, record["batch_id"], record["subject_id"])
    else:
        result = {"ok": False, "detail": "cookies ya subject link nahi hai", "status": 0}
    job.progress.update(phase="finish", ok=result.get("ok"), message=result.get("detail", ""))
    job.push_log(f"session: {'OK' if result.get('ok') else 'BROKEN'} — {result.get('detail')}")
    if not result.get("ok"):
        job.error = result.get("detail", "session broken")


# -- HTTP --------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "vd-ui/2.0"

    def log_message(self, fmt: str, *args) -> None:  # keep the console clean
        pass

    # helpers
    def _send(self, status: int, payload, content_type: str = "application/json; charset=utf-8") -> None:
        if isinstance(payload, (dict, list)):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        elif isinstance(payload, bytes):
            body = payload
        else:
            body = str(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_BODY:
            raise ValueError("body too large")
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"JSON parse fail: {exc}")
        if not isinstance(data, dict):
            raise ValueError("JSON object expected")
        return data

    def _static(self, name: str, content_type: str) -> None:
        path = STATIC_DIR / name
        if not path.is_file():
            self._send(HTTPStatus.NOT_FOUND, "not found", "text/plain; charset=utf-8")
            return
        self._send(HTTPStatus.OK, path.read_bytes(), content_type)

    # routing
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path
        query = parse_qs(parsed.query)
        try:
            if route in ("/", "/index.html"):
                self._static("index.html", "text/html; charset=utf-8")
            elif route == "/static/app.js":
                self._static("app.js", "application/javascript; charset=utf-8")
            elif route == "/static/styles.css":
                self._static("styles.css", "text/css; charset=utf-8")
            elif route == "/api/overview":
                self._send(HTTPStatus.OK, overview())
            elif route == "/api/plan":
                self._send(HTTPStatus.OK, api_plan(query))
            elif route == "/api/job":
                self._send(HTTPStatus.OK, {"job": JOBS.snapshot()})
            elif route == "/api/subjects":
                self._send(HTTPStatus.OK, {"subjects": state.subjects_with_catalog()})
            else:
                self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except FileNotFoundError as exc:
            self._send(HTTPStatus.CONFLICT, {"error": str(exc)})
        except Exception as exc:
            self._send(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"{type(exc).__name__}: {exc}"})

    def do_POST(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        try:
            body = self._json_body()
            if route == "/api/subjects":
                result = api_add_subject(body)
            elif route == "/api/catalog":
                result = api_start_catalog(body)
            elif route == "/api/download":
                result = api_start_download(body)
            elif route == "/api/job/stop":
                result = api_stop()
            elif route == "/api/status":
                result = api_status(body)
            elif route == "/api/session":
                result = api_session(body)
            elif route == "/api/settings":
                result = api_settings(body)
            elif route == "/api/clean":
                result = {"removed": state.clean_temp()["removed"]}
            else:
                self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
            status = HTTPStatus.CONFLICT if not result.get("ok", True) else HTTPStatus.OK
            self._send(status, result)
        except ValueError as exc:
            self._send(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception as exc:
            self._send(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"{type(exc).__name__}: {exc}"})

    def do_DELETE(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/subjects/"):
            key = parsed.path.rsplit("/", 1)[-1]
            ok = links.remove_subject(key)
            self._send(HTTPStatus.OK if ok else HTTPStatus.NOT_FOUND, {"ok": ok})
            return
        self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})


# -- API implementations -----------------------------------------------------
def overview() -> dict:
    settings = Settings.load()
    cookies = auth.load_cookies()
    return {
        "version": "2.0.0",
        "settings": {
            "output_root": settings.output_root,
            "concurrency": settings.concurrency,
            "quality": settings.quality,
            "ui_port": settings.ui_port,
        },
        "free_gb": free_space_gb(settings.output_path),
        "output_exists": settings.output_path.exists(),
        "subjects": state.subjects_with_catalog(),
        "session": {
            **auth.cookie_summary(cookies),
            "ok": bool(cookies),
        },
        "job": JOBS.snapshot(),
        "project_root": str(PROJECT_ROOT),
    }


def api_plan(query: dict) -> dict:
    key = (query.get("key") or [""])[0]
    if not key:
        raise ValueError("key chahiye")
    record = links.find_subject(key)
    if not record:
        raise FileNotFoundError("subject registered nahi hai")
    kinds = (query.get("kinds") or [""])[0]
    kinds_list = [k for k in kinds.split(",") if k] or None
    only_missing = (query.get("only_missing") or ["1"])[0] != "0"
    settings = Settings.load()
    plan = plan_mod.plan_for_subject(record, settings, kinds=kinds_list, only_missing=only_missing)
    plan.pop("items", None)  # chapters already carry every item; keeps the payload small
    selected = plan.pop("selected_items", [])
    plan["selected_ids"] = [item["id"] for item in selected]
    return plan


def api_add_subject(body: dict) -> dict:
    url = (body.get("url") or "").strip()
    if not links.is_subject_url(url):
        return {"ok": False, "error": "URL me batchId aur subjectId chahiye (content ya schedule-details link)."}
    record = links.add_subject(url, dir_name=(body.get("dir") or "").strip())
    return {"ok": True, "subject": record}


def api_start_catalog(body: dict) -> dict:
    key = (body.get("key") or "").strip()
    if not key:
        raise ValueError("key chahiye")
    job = Job("catalog", f"catalog: {key}")
    started, info = JOBS.start(job, lambda active: run_catalog_job(active, key, bool(body.get("deep", True))))
    return {"ok": started, "id": info, "error": "" if started else info}


def api_start_download(body: dict) -> dict:
    key = (body.get("key") or "").strip()
    ids = body.get("ids") or []
    if not key or not isinstance(ids, list) or not ids:
        raise ValueError("key aur ids chahiye")
    job = Job("download", f"download: {key} ({len(ids)} items)")
    started, info = JOBS.start(job, lambda active: run_download_job(active, key, ids))
    return {"ok": started, "id": info, "error": "" if started else info}


def api_stop() -> dict:
    current = JOBS.snapshot()
    if not current or current["status"] != "running":
        return {"ok": False, "error": "koi job nahi chal raha"}
    with JOBS._lock:  # noqa: SLF001 - single owner
        if JOBS.current:
            JOBS.current.stop()
    return {"ok": True}


def api_status(body: dict) -> dict:
    """Write the per-subject markdown report the founder can open anywhere."""
    key = (body.get("key") or "").strip()
    if not key:
        raise ValueError("key chahiye")
    record = links.find_subject(key)
    if not record:
        raise FileNotFoundError("subject registered nahi hai")
    settings = Settings.load()
    plan_obj = plan_mod.plan_for_subject(record, settings)
    path = report.write_subject_report(record, plan_obj, state.report_file(key))
    summary = plan_obj["summary"]
    missing = {kind: summary["by_kind"][kind]["missing"] for kind in plan_mod.ALL_KINDS
               if summary["by_kind"][kind]["total"]}
    return {"ok": True, "path": str(path), "missing": missing,
            "est_gb": summary["selected_est_gb"], "free_gb": plan_obj.get("free_gb")}


def api_session(body: dict) -> dict:
    cookies = body.get("cookies")
    if isinstance(cookies, str):
        try:
            cookies = json.loads(cookies)
        except json.JSONDecodeError:
            return {"ok": False, "error": "cookies JSON parse nahi hua"}
    if not isinstance(cookies, dict) or not cookies:
        return {"ok": False, "error": "cookies object chahiye"}
    cleaned = {str(k): str(v) for k, v in cookies.items() if v}
    path = auth.save_cookies(cleaned)
    records = links.sorted_subjects()
    result = {"ok": True, "path": str(path), "detail": "saved (verify ke liye subject link chahiye)"}
    if records:
        probe = asyncio.run(check_session(cleaned, records[0]["batch_id"], records[0]["subject_id"]))
        result.update({"detail": probe["detail"], "session_ok": probe["ok"]})
        result["ok"] = True  # saved either way; session_ok tells the truth
    return result


def api_settings(body: dict) -> dict:
    settings = Settings.load()
    if "output_root" in body and str(body["output_root"]).strip():
        candidate = Path(str(body["output_root"]).strip())
        settings.output_root = str(candidate)
    if "concurrency" in body:
        try:
            settings.concurrency = max(1, min(8, int(body["concurrency"])))
        except (TypeError, ValueError):
            pass
    if "quality" in body and str(body["quality"]).strip():
        settings.quality = str(body["quality"]).strip()
    settings.save()
    return {"ok": True, "settings": {
        "output_root": settings.output_root,
        "concurrency": settings.concurrency,
        "quality": settings.quality,
    }}


# -- server ------------------------------------------------------------------
def serve(port: int = 0, open_browser: bool = True) -> int:
    ensure_dirs()
    settings = Settings.load()
    wanted = port or settings.ui_port
    httpd = None
    for candidate in range(wanted, wanted + 20):
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", candidate), Handler)
            break
        except OSError:
            continue
    if httpd is None:
        print(f"Port {wanted}-{wanted + 19} sab busy hain")
        return 1
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    print("Video-Downloader UI:", url)
    print("Band karne ke liye Ctrl+C")
    if open_browser:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
    finally:
        httpd.server_close()
    return 0
