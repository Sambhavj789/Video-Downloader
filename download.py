import asyncio, json, re, sys
from pathlib import Path
from curl_cffi.requests import AsyncSession
from core_download import download_video

WORK_DIR = Path(__file__).parent
TEMP_DIR = WORK_DIR / "_temp"
COOKIES_FILE = WORK_DIR / "stream_cookies.json"

STREAM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://stream.testuk.org/",
}

async def main():
    print("Video-Downloader (single video)")
    print("=" * 50)

    link_path = WORK_DIR / "link.txt"
    page_url = link_path.read_text(encoding="utf-8").strip()
    if not page_url:
        print("ERROR: link.txt is empty"); sys.exit(1)

    if not COOKIES_FILE.exists():
        print(f"ERROR: {COOKIES_FILE.name} not found!")
        print("Open Chrome -> DevTools -> Application -> Cookies -> stream.testuk.org")
        print("Copy cf_clearance and session values into stream_cookies.json")
        sys.exit(1)
    cookies = json.loads(COOKIES_FILE.read_text("utf-8"))

    print(f"\nDownloading: {page_url[:80]}...")

    async with AsyncSession(impersonate="chrome124") as cf_session:
        resp = await cf_session.get(page_url, headers=STREAM_HEADERS, cookies=cookies)
        if resp.status_code != 200:
            print(f"ERROR: page returned {resp.status_code}")
            sys.exit(1)
        html = resp.text

        mt = re.search(r'MEDIA_TOKEN\s*=\s*"([^"]+)"', html)
        if not mt:
            print("ERROR: No MEDIA_TOKEN found on page")
            sys.exit(1)
        media_token = mt.group(1)
        print(f"  MEDIA_TOKEN found, resolving video URL...")

        api_headers = {**STREAM_HEADERS, "Accept": "application/json, text/plain, */*"}
        api_url = f"https://stream.testuk.org/v1/videos/video-url-details?mediaToken={media_token}&videoContainerType=DASH"
        api_resp = await cf_session.get(api_url, headers=api_headers, cookies=cookies)
        api_data = api_resp.json()

        if not api_data.get("success") or not api_data.get("data"):
            print(f"ERROR: API returned no data: {json.dumps(api_data)[:200]}")
            sys.exit(1)

        r = api_data["data"]
        video_data = {"drmType": r.get("drmType", "ClearKey"), "url": r["url"]}
        for k in ["keys", "key_strings", "pssh", "licenseUrl", "licenseToken", "certificateUrl"]:
            if r.get(k):
                video_data[k] = r[k]

        print(f"  Video URL resolved, drmType={video_data.get('drmType', '?')}")
        ok = await download_video(None, WORK_DIR / "video.mp4", TEMP_DIR, video_data_override=video_data)
        if ok:
            print(f"\n  SUCCESS: video.mp4")
        else:
            print(f"\n  FAILED")
            sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
