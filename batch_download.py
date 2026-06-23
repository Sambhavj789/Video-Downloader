import asyncio, json, re, sys, os, shutil, aiohttp, base64
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode
from curl_cffi.requests import AsyncSession

WORK_DIR = Path(__file__).parent
OUTPUT_DIR = WORK_DIR / "output"
TEMP_BASE = WORK_DIR / "_batch_temp"
TRACKER_FILE = WORK_DIR / "batch_progress.json"
TOKEN_FILE = WORK_DIR / "token.txt"
COOKIES_FILE = WORK_DIR / "stream_cookies.json"

# Fallback schedule ID to bootstrap PW_HEADERS refresh when token expires
SEED_SCHEDULE_ID = "6980a63931cbfcd747c58fc6"

def fmt_bytes(b):
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

async def call_video_api(cf_session, cookies, media_token):
    url = f"https://stream.testuk.org/v1/videos/video-url-details?mediaToken={media_token}&videoContainerType=DASH"
    api_headers = {**STREAM_HEADERS, "Accept": "application/json, text/plain, */*"}
    resp = await cf_session.get(url, headers=api_headers, cookies=cookies)
    return resp.status_code, resp.json()

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
    print("  Batch Downloader (curl_cffi + Cookies)")
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
        print("Usage: python batch_download.py <batch-page-url>")
        sys.exit(1)

    (WORK_DIR / "batch_link.txt").write_text(page_url, "utf-8")
    params = parse_batch_url(page_url)
    if not params["batchId"] or not params["subjectId"]:
        print("ERROR: URL must contain batchId and subjectId")
        sys.exit(1)

    if not COOKIES_FILE.exists():
        print(f"\n  ERROR: {COOKIES_FILE.name} not found!")
        print("  Open Chrome -> DevTools -> Application -> Cookies -> stream.testuk.org")
        print("  Copy cf_clearance and session values into stream_cookies.json")
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
                      "device-meta": "{}", "randomid": "batch_dl"}
            print("  PW_HEADERS built from token.txt")

    subject_name = sanitize(params["subjectName"] or "Subject")
    print(f"\n  Subject: {subject_name}")

    connector = aiohttp.TCPConnector(limit=10)
    async with AsyncSession(impersonate="chrome124") as cf_session:
        # Try to refresh PW_HEADERS from stream.testuk.org (handles expired tokens)
        if cookies:
            fresh = await refresh_pw_headers(cf_session, cookies, params, SEED_SCHEDULE_ID)
            if fresh:
                pw_hdr = fresh
                print("  PW_HEADERS refreshed from stream.testuk.org")
            elif pw_hdr:
                print("  PW_HEADERS refresh skipped, using saved headers")
            else:
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
                # Retry with fresh PW_HEADERS (in case saved token was stale)
                print("  No chapters found, attempting token refresh...")
                fresh2 = await refresh_pw_headers(cf_session, cookies, params, SEED_SCHEDULE_ID)
                if fresh2:
                    pw_hdr = fresh2
                    print("  Retrying chapters API with fresh headers...")
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
            videos_done_global = set(tracker.get("videos_done", []))

            total_vids = total_dl = total_skip = total_fail = total_bytes = 0
            for ci, ch in enumerate(chapters, 1):
                ch_name = sanitize(ch.get("name", f"Chapter_{ci}"))
                ch_dir = OUTPUT_DIR / ch_name
                ch_dir.mkdir(parents=True, exist_ok=True)

                if ch_name in chapters_done:
                    existing = len(list(ch_dir.glob("*.mp4")))
                    total_skip += existing; total_vids += existing
                    print(f"  [{ci}/{len(chapters)}] {ch.get('name','?')}  ({existing} videos, done)")
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
                    print("    (no videos)\n"); continue

                ch_total = len(videos)
                ch_dl = ch_skip = ch_fail = ch_bytes = 0
                total_vids += ch_total
                print(f"    {ch_total} videos")

                for vi, vid in enumerate(videos, 1):
                    vname_raw = vid.get("topic") or vid.get("videoDetails", {}).get("name") or f"Video_{vi}"
                    vname_safe = sanitize(vname_raw)
                    out_file = ch_dir / f"{vname_safe}.mp4"
                    if out_file.exists() or vname_raw in videos_done_global:
                        sz = f"  ({fmt_bytes(out_file.stat().st_size)})" if out_file.exists() else ""
                        print(f"    [{vi}/{ch_total}] [ok] {vname_raw[:48]}{sz}")
                        ch_skip += 1; total_skip += 1; continue

                    print(f"    [{vi}/{ch_total}] [dl] {vname_raw[:50]}")
                    schedule_id = vid.get("_id")
                    if not schedule_id:
                        ch_skip += 1; total_skip += 1; continue

                    try:
                        status, html = await get_schedule_html(cf_session, cookies, params['batchId'], params['subjectId'], schedule_id)
                        if status != 200:
                            print(f"      schedule-details returned {status}")
                            ch_fail += 1; total_fail += 1; continue

                        if not pw_hdr:
                            pw_m = re.search(r'PW_HEADERS\s*=\s*({.*?});', html, re.DOTALL)
                            if pw_m:
                                try:
                                    pw_hdr = json.loads(pw_m.group(1))
                                    (WORK_DIR / "pw_headers.json").write_text(json.dumps(pw_hdr, indent=2), "utf-8")
                                    print(f"      PW_HEADERS extracted from page")
                                except:
                                    pass

                        mt = re.search(r'MEDIA_TOKEN\s*=\s*"([^"]+)"', html)
                        if not mt:
                            print(f"      No MEDIA_TOKEN in schedule-details")
                            ch_fail += 1; total_fail += 1; continue

                        api_status, api_data = await call_video_api(cf_session, cookies, mt.group(1))
                        if api_status != 200 or not api_data.get("success") or not api_data.get("data"):
                            print(f"      API error: {json.dumps(api_data)[:200]}")
                            ch_fail += 1; total_fail += 1; continue

                        r = api_data["data"]
                        video_url = r.get("url", "")
                        if not video_url:
                            print(f"      No video URL in API response")
                            ch_fail += 1; total_fail += 1; continue

                        vd = {"drmType": r.get("drmType", "ClearKey"), "url": video_url}
                        for k in ["keys","key_strings","pssh","licenseUrl","licenseToken","certificateUrl"]:
                            if r.get(k): vd[k] = r[k]
                    except Exception as e:
                        print(f"      Error: {e}")
                        ch_fail += 1; total_fail += 1; continue

                    temp_dir = TEMP_BASE / f"{ch_name}_{vname_safe}"
                    from core_download import download_video
                    ok = await download_video(None, out_file, temp_dir, pw_headers=pw_hdr, progress_prefix="    ", video_data_override=vd)

                    if ok:
                        ch_dl += 1; total_dl += 1
                        if out_file.exists(): ch_bytes += out_file.stat().st_size
                        videos_done_global.add(vname_raw)
                        tracker["videos_done"] = sorted(videos_done_global)
                        save_tracker(tracker)
                    else:
                        ch_fail += 1; total_fail += 1
                    await asyncio.sleep(1)

                ch_size_str = f" ({fmt_bytes(ch_bytes)})" if ch_bytes else ""
                if ch_fail == 0 and ch_dl + ch_skip == ch_total:
                    chapters_done.add(ch_name)
                    tracker["chapters_done"] = sorted(chapters_done)
                    save_tracker(tracker)
                    print(f"    [ok] Chapter done: {ch_dl} new, {ch_skip} existing{ch_size_str}\n")
                else:
                    print(f"    Chapter: {ch_dl} done, {ch_skip} skip, {ch_fail} fail / {ch_total}{ch_size_str}\n")
                total_bytes += ch_bytes

        print("=" * 60)
        print("  FINAL SUMMARY")
        print(f"    Videos found: {total_vids}")
        print(f"    Downloaded:   {total_dl}")
        print(f"    Skipped:      {total_skip}")
        print(f"    Failed:       {total_fail}")
        if total_bytes: print(f"    Total size:   {fmt_bytes(total_bytes)}")
        print(f"    Output:       {OUTPUT_DIR}")
        print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
