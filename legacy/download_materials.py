import asyncio, json, re, sys, os, aiohttp
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from curl_cffi.requests import AsyncSession

WORK_DIR = Path(__file__).parent
OUTPUT_DIR = WORK_DIR / "output"
TRACKER_FILE = WORK_DIR / "materials_progress.json"
COOKIES_FILE = WORK_DIR / "stream_cookies.json"
TOKEN_FILE = WORK_DIR / "token.txt"
SEED_SCHEDULE_ID = "6980a63931cbfcd747c58fc6"

def fmt_size(b):
    if b < 1024 * 1024:
        return f"{b/1024:.1f} KB"
    return f"{b/(1024*1024):.1f} MB"

def parse_batch_url(url):
    qs = parse_qs(urlparse(url).query)
    return {"batchId": qs.get("batchId", [""])[0], "subjectId": qs.get("subjectId", [""])[0],
            "batchName": qs.get("batchName", [""])[0], "subjectName": qs.get("subjectName", [""])[0]}

def sanitize(name):
    s = re.sub(r'[<>:"/\\|?*]', '_', name or "Unknown")
    return s.strip() or "Unknown"

def load_tracker():
    if TRACKER_FILE.exists():
        try: return json.loads(TRACKER_FILE.read_text("utf-8"))
        except: pass
    return {"url": "", "chapters_done": [], "videos_done": []}

def save_tracker(t):
    TRACKER_FILE.write_text(json.dumps(t, indent=2, ensure_ascii=False), "utf-8")

STREAM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://stream.testuk.org/",
}

async def get_schedule_html(cf_session, cookies, batch_id, subject_id, schedule_id):
    url = f"https://stream.testuk.org/schedule-details?batchId={batch_id}&subjectId={subject_id}&scheduleId={schedule_id}&tap=video"
    resp = await cf_session.get(url, headers=STREAM_HEADERS, cookies=cookies)
    return resp.status_code, resp.text

def extract_materials(html, vname):
    notes = []
    dpp = []
    m = re.search(r'const\s+NOTES\s*=\s*(\[[\s\S]*?\])\s*;', html)
    if m:
        try:
            items = json.loads(m.group(1))
            for item in items:
                item["video"] = vname
            notes = items
        except: pass
    m = re.search(r'const\s+DPP_NOTES\s*=\s*(\[[\s\S]*?\])\s*;', html)
    if m:
        try:
            items = json.loads(m.group(1))
            for item in items:
                item["video"] = vname
            dpp = items
        except: pass
    return notes, dpp

async def download_file(session, url, path):
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=120)) as resp:
            if resp.status == 200:
                path.parent.mkdir(parents=True, exist_ok=True)
                data = await resp.read()
                path.write_bytes(data)
                return len(data)
    except: pass
    return 0

async def refresh_pw_headers(cf_session, cookies, params, seed_id):
    url = f"https://stream.testuk.org/schedule-details?batchId={params['batchId']}&subjectId={params['subjectId']}&scheduleId={seed_id}&tap=video"
    resp = await cf_session.get(url, headers=STREAM_HEADERS, cookies=cookies)
    if resp.status_code != 200:
        return None
    m = re.search(r'PW_HEADERS\s*=\s*({.*?});', resp.text, re.DOTALL)
    if not m:
        return None
    try:
        pw = json.loads(m.group(1))
        (WORK_DIR / "pw_headers.json").write_text(json.dumps(pw, indent=2), "utf-8")
        return pw
    except:
        return None

async def main():
    print("=" * 60)
    print("  Materials Downloader (Notes + DPP)")
    print("=" * 60)

    page_url = ""
    if len(sys.argv) > 1:
        page_url = sys.argv[1]
    else:
        link_file = WORK_DIR / "batch_link.txt"
        if link_file.exists():
            page_url = link_file.read_text("utf-8").strip()
        if not page_url:
            t = load_tracker()
            page_url = t.get("url", "")
    if not page_url:
        print("Usage: python download_materials.py <batch-page-url>")
        sys.exit(1)

    params = parse_batch_url(page_url)
    if not params["batchId"] or not params["subjectId"]:
        print("ERROR: URL must contain batchId and subjectId")
        sys.exit(1)

    if not COOKIES_FILE.exists():
        print(f"\n  ERROR: {COOKIES_FILE.name} not found!")
        sys.exit(1)
    cookies = json.loads(COOKIES_FILE.read_text("utf-8"))

    pw_hdr = None
    hdr_file = WORK_DIR / "pw_headers.json"
    if hdr_file.exists():
        pw_hdr = json.loads(hdr_file.read_text("utf-8"))
        print(f"  PW_HEADERS loaded from {hdr_file.name}")
    elif TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text("utf-8").strip()
        if token:
            pw_hdr = {"authorization": f"Bearer {token}",
                      "referer": "https://android.pw.live",
                      "client-id": "ADMIN", "client-type": "MOBILE",
                      "device-meta": "{}", "randomid": "mat_dl"}

    subject_name = sanitize(params["subjectName"] or "Subject")
    print(f"  Subject: {subject_name}")

    connector = aiohttp.TCPConnector(limit=10)
    async with AsyncSession(impersonate="chrome124") as cf_session:
        if cookies:
            fresh = await refresh_pw_headers(cf_session, cookies, params, SEED_SCHEDULE_ID)
            if fresh:
                pw_hdr = fresh
                print("  PW_HEADERS refreshed")
            elif not pw_hdr:
                print("  ERROR: No valid PW_HEADERS available")
                sys.exit(1)

        async with aiohttp.ClientSession(connector=connector) as session:
            chapters = []
            p = 1
            while True:
                async with session.get(
                    f"https://api.penpencil.co/v2/batches/{params['batchId']}/subject/{params['subjectId']}/topics?page={p}",
                    headers=pw_hdr, timeout=aiohttp.ClientTimeout(total=30)
                ) as r:
                    data = await r.json()
                if not data.get("success") or not data.get("data"):
                    break
                chapters.extend(data["data"])
                if len(data["data"]) < 10:
                    break
                p += 1

            if not chapters:
                print("  Retrying with fresh PW_HEADERS...")
                fresh2 = await refresh_pw_headers(cf_session, cookies, params, SEED_SCHEDULE_ID)
                if fresh2:
                    pw_hdr = fresh2
                    p = 1
                    while True:
                        async with session.get(
                            f"https://api.penpencil.co/v2/batches/{params['batchId']}/subject/{params['subjectId']}/topics?page={p}",
                            headers=pw_hdr, timeout=aiohttp.ClientTimeout(total=30)
                        ) as r:
                            data = await r.json()
                        if not data.get("success") or not data.get("data"):
                            break
                        chapters.extend(data["data"])
                        if len(data["data"]) < 10:
                            break
                        p += 1

            if not chapters:
                print("  No chapters found")
                return

            print(f"\n  Found {len(chapters)} chapters")

            tracker = load_tracker()
            if tracker.get("url") != page_url:
                tracker = {"url": page_url, "chapters_done": [], "videos_done": []}
                save_tracker(tracker)

            chapters_done = set(tracker.get("chapters_done", []))
            videos_done = set(tracker.get("videos_done", []))

            total_notes = total_dpp = total_skip = total_dl = 0

            for ci, ch in enumerate(chapters, 1):
                ch_name = sanitize(ch.get("name", f"Chapter_{ci}"))
                ch_base = OUTPUT_DIR / ch_name
                notes_dir = ch_base / "Notes"
                dpp_dir = ch_base / "DPP"

                if ch_name in chapters_done:
                    existing_notes = len(list(notes_dir.glob("*.pdf"))) if notes_dir.exists() else 0
                    existing_dpp = len(list(dpp_dir.glob("*.pdf"))) if dpp_dir.exists() else 0
                    total_skip += existing_notes + existing_dpp
                    print(f"  [{ci}/{len(chapters)}] {ch.get('name','?')}  ({existing_notes} notes, {existing_dpp} dpp, done)")
                    continue

                print(f"  [{ci}/{len(chapters)}] {ch.get('name','?')}  loading videos...")

                videos = []
                p = 1
                while True:
                    async with session.get(
                        f"https://api.penpencil.co/v2/batches/{params['batchId']}/subject/{params['subjectId']}/contents?page={p}&contentType=videos&tag={ch['_id']}",
                        headers=pw_hdr, timeout=aiohttp.ClientTimeout(total=30)
                    ) as r:
                        data = await r.json()
                    if not data.get("success") or not data.get("data"):
                        break
                    videos.extend(data["data"])
                    if len(data["data"]) < 20:
                        break
                    p += 1

                if not videos:
                    print("    (no videos)\n")
                    continue

                ch_notes = ch_dpp = ch_skip = 0

                for vi, vid in enumerate(videos, 1):
                    vname_raw = vid.get("topic") or vid.get("videoDetails", {}).get("name") or f"Video_{vi}"
                    vname_safe = sanitize(vname_raw)

                    if vname_raw in videos_done:
                        print(f"    [{vi}/{len(videos)}] [ok] {vname_raw[:48]}")
                        ch_skip += 1
                        continue

                    schedule_id = vid.get("_id")
                    if not schedule_id:
                        continue

                    try:
                        status, html = await get_schedule_html(cf_session, cookies, params['batchId'], params['subjectId'], schedule_id)
                        if status != 200:
                            print(f"    [{vi}/{len(videos)}] [err] {vname_raw[:48]}  HTTP {status}")
                            continue
                    except Exception as e:
                        print(f"    [{vi}/{len(videos)}] [err] {vname_raw[:48]}  {e}")
                        continue

                    notes, dpp_items = extract_materials(html, vname_raw)

                    for n in notes:
                        fname = sanitize(f"{vname_safe} - {n.get('name', 'note')}") + ".pdf"
                        fpath = notes_dir / fname
                        if fpath.exists():
                            ch_skip += 1
                            continue
                        size = await download_file(session, n["url"], fpath)
                        if size:
                            ch_notes += 1
                            total_dl += 1
                            print(f"    [{vi}/{len(videos)}] [note] {n['name'][:40]}  ({fmt_size(size)})")
                        else:
                            print(f"    [{vi}/{len(videos)}] [fail] {n['name'][:40]}")

                    for d in dpp_items:
                        fname = sanitize(f"{vname_safe} - {d.get('name', 'dpp')}") + ".pdf"
                        fpath = dpp_dir / fname
                        if fpath.exists():
                            ch_skip += 1
                            continue
                        size = await download_file(session, d["url"], fpath)
                        if size:
                            ch_dpp += 1
                            total_dl += 1
                            print(f"    [{vi}/{len(videos)}] [dpp] {d['name'][:40]}  ({fmt_size(size)})")
                        else:
                            print(f"    [{vi}/{len(videos)}] [fail] {d['name'][:40]}")

                    videos_done.add(vname_raw)
                    tracker["videos_done"] = sorted(videos_done)
                    save_tracker(tracker)
                    await asyncio.sleep(0.5)

                total_notes += ch_notes
                total_dpp += ch_dpp

                if ch_notes + ch_dpp == 0 and videos:
                    print(f"    (no notes or dpp found)\n")
                else:
                    print(f"    [ok] Chapter done: {ch_notes} notes, {ch_dpp} dpp\n")

                chapters_done.add(ch_name)
                tracker["chapters_done"] = sorted(chapters_done)
                save_tracker(tracker)

        print("=" * 60)
        print("  MATERIALS SUMMARY")
        print(f"    Notes downloaded: {total_notes}")
        print(f"    DPP downloaded:   {total_dpp}")
        print(f"    Skipped:          {total_skip}")
        print(f"    Output:           {OUTPUT_DIR}")
        print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
