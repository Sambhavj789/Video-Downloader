import asyncio, sys
from pathlib import Path
from core_download import download_video

WORK_DIR = Path(__file__).parent
TEMP_DIR = WORK_DIR / "_temp"

async def main():
    print("Video-Downloader (single video)")
    print("=" * 50)

    link_path = WORK_DIR / "link.txt"
    page_url = link_path.read_text(encoding="utf-8").strip()
    if not page_url:
        print("ERROR: link.txt is empty"); sys.exit(1)

    print(f"\nDownloading: {page_url[:80]}...")
    ok = await download_video(page_url, WORK_DIR / "video.mp4", TEMP_DIR)
    if ok:
        print(f"\n  SUCCESS: video.mp4")
    else:
        print(f"\n  FAILED")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
