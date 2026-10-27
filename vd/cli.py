"""CLI — every feature of the UI exists here too (and is what tests use).

    python -m vd link "<subject-url>"
    python -m vd catalog --all
    python -m vd status --all
    python -m vd download --subject <key> --kinds videos,notes --yes
    python -m vd ui
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

from . import auth, links, names, plan as plan_mod, report, state
from .catalog import build_catalog
from .config import LOG_DIR, ensure_dirs, free_space_gb
from .downloader import DownloadRunner
from .stream import check_session

KIND_ALIASES = {
    "video": "videos", "videos": "videos",
    "note": "notes", "notes": "notes", "pdf": "notes",
    "dpp": "dpp",
    "slide": "slides", "slides": "slides",
    "doc": "documents", "documents": "documents", "ebook": "documents", "ebooks": "documents",
}


def parse_kinds(value: str | None) -> list[str] | None:
    if not value:
        return None
    out = []
    for piece in value.replace(" ", ",").split(","):
        piece = piece.strip().lower()
        if not piece:
            continue
        if piece not in KIND_ALIASES:
            raise SystemExit(f"unknown kind: {piece} (videos|notes|dpp|slides|documents)")
        out.append(KIND_ALIASES[piece])
    return out or None


def select_subjects(key: str | None, all_subjects: bool) -> list[dict]:
    records = links.sorted_subjects()
    if not records:
        raise SystemExit("Koi subject link registered nahi hai. Pehle: python -m vd link \"<subject-url>\"")
    if all_subjects or not key:
        return records
    match = [r for r in records if r.get("key") == key]
    if not match:
        match = [r for r in records if names.normalize(r.get("subject_name", "")) == names.normalize(key)]
    if not match:
        raise SystemExit(f"subject '{key}' nahi mila. Registered: {', '.join(r['key'] for r in records)}")
    return match


# -- commands ----------------------------------------------------------------
def cmd_link(args) -> int:
    if args.action == "list":
        records = links.sorted_subjects()
        if not records:
            print("(koi link nahi)")
            return 0
        for record in records:
            catalog = state.load_catalog(record["key"])
            stamp = catalog.get("fetched_at", "—") if catalog else "catalog nahi"
            print(f"{record['key']:<48} {record.get('subject_name', ''):<45} {stamp}")
        return 0
    if args.action == "remove":
        ok = links.remove_subject(args.target or "")
        print("hataya" if ok else "nahi mila")
        return 0 if ok else 1
    if not args.target:
        raise SystemExit("URL do: python -m vd link \"<subject-url>\"")
    record = links.add_subject(args.target, dir_name=args.dir or "")
    print(f"registered: {record['key']}  ({record.get('subject_name', '')})")
    return 0


def cmd_catalog(args) -> int:
    ensure_dirs()
    settings = _settings()
    cookies = auth.load_cookies()
    records = select_subjects(args.subject, args.all)
    if not cookies:
        print("WARNING: cookies nahi mile — PDF/notes list nahi aayegi. `python -m vd session save <file>` chalao.")
    for record in records:
        print(f"\n=== {record.get('subject_name', record['key'])} ===")
        try:
            catalog = asyncio.run(_catalog_async(record, settings, cookies, deep=not args.shallow))
        except Exception as exc:
            print(f"  FAIL: {type(exc).__name__}: {exc}")
            continue
        state.save_catalog(record["key"], catalog)
        totals = catalog["totals"]
        print(f"  saved: {totals['chapters']} chapters · {totals['videos']} videos · "
              f"{totals['notes']} notes · {totals['dpp']} dpp · {totals['slides']} slides")
        if totals.get("missing_media"):
            print(f"  note: {totals['missing_media']} videos ka media site par ready nahi")
        if totals.get("scan_failed"):
            print(f"  WARN: {totals['scan_failed']} videos ka schedule page nahi khula "
                  f"(notes/DPP adhoore) — catalog dobara chalao")
    return 0


async def _catalog_async(record: dict, settings, cookies: dict, deep: bool) -> dict:
    last = {"done": 0, "total": 0}

    def on_event(event: dict) -> None:
        if event.get("step") == "chapters":
            last["done"] = event.get("done", 0)
            last["total"] = event.get("total", 0)
            sys.stdout.write(f"\r  chapters {last['done']}/{last['total']}  {event.get('message', '')[:50]:<50}")
            sys.stdout.flush()

    catalog = await build_catalog(record, settings, cookies, deep=deep, progress=on_event)
    print()
    return catalog


def cmd_batch(args) -> int:
    """List the subjects of a batch (and optionally register them as links)."""
    batch_id = links.batch_id_from(args.target)
    if not batch_id:
        raise SystemExit("batch link ya batchId do")

    from .config import Settings
    from .proxy import MetadataClient

    async def fetch() -> tuple[str, list[dict]]:
        async with MetadataClient() as meta:
            payload = await meta.get_json_version(f"/batches/{batch_id}/details", version="v3")
            data = payload.get("data") or {}
            return (data.get("batchName") or data.get("name") or "", data.get("subjects") or [])

    batch_name, subjects = asyncio.run(fetch())
    if not subjects:
        print("is batch me koi subject nahi mila")
        return 1

    only = {names.normalize(piece) for piece in (args.only or "").split(",") if piece.strip()}
    print(f"{batch_name}  ({batch_id})")
    added = 0
    for subject in subjects:
        subject_name = (subject.get("subject") or subject.get("name") or "").strip()
        subject_id = subject.get("_id", "")
        if not subject_id or not subject_name:
            continue
        if names.normalize(subject_name) == "notices":
            continue
        picked = not only or names.normalize(subject_name) in only
        print(f"  {'*' if picked else ' '} {subject_id}  {subject_name}  "
              f"({subject.get('tagCount') or 0} chapters)")
        if picked and args.add:
            record = links.add_subject(
                links.build_subject_url(batch_id, subject_id, batch_name, subject_name),
                dir_name=args.dir or "",
            )
            added += 1
            print(f"      -> registered {record['key']}")
    if args.add:
        print(f"\n{added} link(s) registered")
    else:
        print("\n(add karne ke liye: --add)")
    return 0


def cmd_status(args) -> int:
    ensure_dirs()
    settings = _settings()
    rows: list[tuple[dict, dict]] = []
    for record in select_subjects(args.subject, args.all):
        try:
            plan = plan_mod.plan_for_subject(record, settings)
        except FileNotFoundError as exc:
            print(f"{record.get('subject_name', record['key'])}: {exc}")
            continue
        rows.append((record, plan))
        report.write_subject_report(record, plan, state.report_file(record["key"]))
        summary = plan["summary"]
        print(f"\n{record.get('subject_name', record['key'])}  ({plan['root']})")
        for kind in plan_mod.ALL_KINDS:
            counts = summary["by_kind"][kind]
            if counts["total"]:
                print(f"  {kind:<10} {counts['done']:>4}/{counts['total']:<4} done, {counts['missing']:>3} missing")
        print(f"  free space: {plan.get('free_gb')} GB · selected if you download all missing: "
              f"{summary['selected_est_gb']} GB")
    if rows:
        path = report.write_library_status(rows, settings.output_path)
        print(f"\nlibrary status: {path}")
        from .config import REPORT_DIR

        print(f"per-subject reports: {REPORT_DIR}")
    return 0


def _wait_for_output_root(output_root: str, *, interval: float = 60.0, exists=None) -> None:
    """Never plan against a missing drive.

    Without ``G:`` every file looks missing, so a run would announce 161 "missing" AA
    videos and start re-downloading the whole library. Wait for the drive instead.
    """
    try:
        anchor = Path(output_root).anchor
    except (OSError, ValueError):  # pragma: no cover - defensive
        return
    if not anchor:
        return
    root = Path(anchor)
    check = exists or (lambda path: path.exists())
    while not check(root):
        print(f"[drive] {anchor} nahi mil raha — drive lagao, main {interval:.0f}s par check karta "
              f"rahunga (Ctrl+C se rukega).", flush=True)
        time.sleep(interval)


def cmd_download(args) -> int:
    ensure_dirs()
    settings = _settings()
    _wait_for_output_root(settings.output_root)
    cookies = auth.load_cookies()
    if not cookies:
        raise SystemExit("cookies nahi mile — download ke liye session chahiye (python -m vd session save <file>).")
    kinds = parse_kinds(args.kinds)
    total_selected = 0
    for record in select_subjects(args.subject, args.all):
        try:
            plan = plan_mod.plan_for_subject(
                record, settings, kinds=kinds, only_missing=not args.include_done,
                chapters=args.chapters.split(",") if args.chapters else None,
            )
        except FileNotFoundError as exc:
            print(f"{record.get('subject_name', record['key'])}: {exc}")
            continue
        items = plan["selected_items"]
        if args.limit:
            items = items[: args.limit]
        if not items:
            print(f"{record.get('subject_name', record['key'])}: kuch download karne ko nahi (sab local hai).")
            continue
        total_selected += len(items)
        size_gb = round(sum(float(i.get("size_est_mb") or 0) for i in items) / 1024, 2)
        print(f"\n{record.get('subject_name', record['key'])}: {len(items)} items (~{size_gb} GB), "
              f"free {plan.get('free_gb')} GB")
        if args.dry_run or not args.yes:
            for item in items[:15]:
                print(f"  - [{item['kind']}] {item['chapter']} / {item['name'][:60]}")
            if len(items) > 15:
                print(f"  … aur {len(items) - 15}")
            print("  (dry run — asli download ke liye --yes lagao)")
            continue
        summary = asyncio.run(_download_async(settings, cookies, record, items))
        print(f"  done={summary['done']} failed={summary['failed']} skipped={summary['skipped']} "
              f"bytes={summary['bytes'] / (1024 ** 2):.0f} MB in {summary['elapsed_s']}s")
        plan2 = plan_mod.plan_for_subject(record, settings)
        report.write_subject_report(record, plan2, state.report_file(record["key"]))
    if not total_selected:
        return 0
    return 0


async def _download_async(settings, cookies: dict, record: dict, items: list[dict]) -> dict:
    def on_event(event: dict) -> None:
        kind = event.get("type")
        if kind == "item_start":
            item = event["item"]
            print(f"[{event['index']}/{event['total']}] {item['kind']}: {item['name'][:60]}")
        elif kind == "progress" and event.get("phase") == "segments":
            sys.stdout.write(
                f"\r    segments {event.get('segments_done', 0)}/{event.get('segments_total', 0)}"
            )
            sys.stdout.flush()
        elif kind == "item_done":
            speed = event.get("speed_mbps", 0)
            print(f"\r    ok ({speed} MB/s)                          ")
        elif kind == "item_fail":
            print(f"\r    fail: {event.get('error', '')[:80]}          ")
        elif kind == "skip":
            pass
        elif kind == "log":
            print(f"  {event.get('message', '')}")

    runner = DownloadRunner(settings, cookies, record, on_event=on_event)
    return await runner.run(items)


def cmd_session(args) -> int:
    if args.action == "save":
        source = Path(args.target or "")
        if not source.exists():
            raise SystemExit(f"file nahi mili: {source}")
        import json

        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"JSON parse fail: {exc}")
        path = auth.save_cookies(data)
        print(f"saved: {path} ({len(data)} cookies)")
        return 0
    records = links.sorted_subjects()
    if not records:
        raise SystemExit("koi subject link nahi hai")
    record = records[0]
    result = asyncio.run(check_session(auth.load_cookies(), record["batch_id"], record["subject_id"]))
    print(f"session: {'OK' if result['ok'] else 'BROKEN'} — {result['detail']} (HTTP {result['status']})")
    return 0 if result["ok"] else 1


def cmd_doctor(args) -> int:
    ensure_dirs()
    settings = _settings()
    ok = True
    print("python:", sys.version.split()[0])

    for module in ("aiohttp", "curl_cffi", "playwright", "imageio_ffmpeg"):
        try:
            __import__(module)
            print(f"  dep {module}: ok")
        except ImportError:
            print(f"  dep {module}: MISSING")
            ok = False

    try:
        from .dash import ffmpeg_exe

        binary = ffmpeg_exe()
        print(f"  ffmpeg: {binary}")
    except Exception as exc:
        print(f"  ffmpeg: MISSING ({exc})")
        ok = False

    try:
        from playwright.async_api import async_playwright  # noqa: F401
        print("  playwright module: ok (browser check: python -m vd catalog --all)")
    except ImportError:
        ok = False

    print(f"  output root: {settings.output_root} "
          f"(exists={settings.output_path.exists()}, free={free_space_gb(settings.output_path)} GB)")
    cookies = auth.load_cookies()
    print(f"  cookies: {auth.cookie_summary(cookies)}")

    records = links.sorted_subjects()
    print(f"  registered subjects: {len(records)}")
    for record in records:
        catalog = state.load_catalog(record["key"])
        stamp = catalog.get("fetched_at", "—") if catalog else "catalog nahi"
        print(f"    - {record['key']}: {record.get('subject_name', '')} ({stamp})")
    if records and cookies:
        record = records[0]
        result = asyncio.run(check_session(cookies, record["batch_id"], record["subject_id"]))
        print(f"  session probe: {'OK' if result['ok'] else 'BROKEN'} — {result['detail']}")
        ok = ok and bool(result["ok"])
    print(f"  logs: {LOG_DIR}")
    return 0 if ok else 1


def cmd_clean(args) -> int:
    result = state.clean_temp()
    print(f"removed: {len(result['removed'])} item(s)")
    for entry in result["removed"]:
        print(f"  - {entry}")
    return 0


def cmd_ui(args) -> int:
    from .ui.server import serve

    return serve(port=args.port, open_browser=not args.no_browser)


# -- wiring ------------------------------------------------------------------
def _settings():
    from .config import Settings

    return Settings.load()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m vd", description="CA lecture offline downloader")
    sub = parser.add_subparsers(dest="command", required=True)

    link = sub.add_parser("link", help="register / list / remove subject links")
    link.add_argument("action", nargs="?", default="add", choices=["add", "list", "remove"])
    link.add_argument("target", nargs="?")
    link.add_argument("--dir", help="existing folder name to use for this subject")
    link.set_defaults(func=cmd_link)

    batch = sub.add_parser("batch", help="list a batch's subjects (and register them)")
    batch.add_argument("target", help="batch link or batchId")
    batch.add_argument("--add", action="store_true", help="register every subject as a link")
    batch.add_argument("--only", help="comma separated subject names to keep")
    batch.add_argument("--dir", help="existing folder name (only for a single subject)")
    batch.set_defaults(func=cmd_batch)

    catalog = sub.add_parser("catalog", help="fetch chapters/videos/notes for a subject")
    catalog.add_argument("--subject")
    catalog.add_argument("--all", action="store_true")
    catalog.add_argument("--shallow", action="store_true", help="skip per-video note/DPP scan")
    catalog.set_defaults(func=cmd_catalog)

    status = sub.add_parser("status", help="what is done and what is missing")
    status.add_argument("--subject")
    status.add_argument("--all", action="store_true")
    status.set_defaults(func=cmd_status)

    download = sub.add_parser("download", help="download missing items")
    download.add_argument("--subject")
    download.add_argument("--all", action="store_true")
    download.add_argument("--kinds", help="videos,notes,dpp,slides,documents")
    download.add_argument("--chapters", help="comma separated chapter names")
    download.add_argument("--limit", type=int, default=0)
    download.add_argument("--include-done", action="store_true")
    download.add_argument("--dry-run", action="store_true")
    download.add_argument("--yes", action="store_true", help="actually download")
    download.set_defaults(func=cmd_download)

    session = sub.add_parser("session", help="check or save stream cookies")
    session.add_argument("action", nargs="?", default="check", choices=["check", "save"])
    session.add_argument("target", nargs="?", help="cookies JSON file")
    session.set_defaults(func=cmd_session)

    doctor = sub.add_parser("doctor", help="environment + session check")
    doctor.set_defaults(func=cmd_doctor)

    clean = sub.add_parser("clean", help="delete temporary segment folders")
    clean.set_defaults(func=cmd_clean)

    ui = sub.add_parser("ui", help="open the browser UI")
    ui.add_argument("--port", type=int, default=0)
    ui.add_argument("--no-browser", action="store_true")
    ui.set_defaults(func=cmd_ui)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
