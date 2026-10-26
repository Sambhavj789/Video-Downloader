import asyncio, json, sys, re
from pathlib import Path
from playwright.async_api import async_playwright

COOKIE_FILE = Path(__file__).parent / "stream_cookies.json"

async def main():
    print("=" * 60)
    print("  Get cookies from your existing Chrome browser")
    print()
    print("  STEP 1: Close all Chrome windows completely")
    print("  STEP 2: Open Chrome with remote debugging enabled:")
    print()
    print('    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --remote-debugging-port=9222')
    print()
    print("  STEP 3: In that Chrome, go to stream.testuk.org")
    print("          and open any video page (it should load normally)")
    print("  STEP 4: Come back here and press ENTER")
    print()
    print("  The script will then connect to your Chrome and extract")
    print("  the cookies that work with stream.testuk.org.")
    print("=" * 60)
    input("\n  Press ENTER after Chrome is open on stream.testuk.org... ")

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else await context.new_page()

        cookies = await context.cookies()
        print(f"\n  Cookies found: {len(cookies)}")
        cookie_data = {}
        for c in cookies:
            cookie_data[c["name"]] = c["value"]
            print(f"    {c['name']}: {c['value'][:60]}...")

        COOKIE_FILE.write_text(json.dumps(cookie_data, indent=2), "utf-8")
        print(f"\n  Cookies saved to {COOKIE_FILE}")

        # Check current page
        if "stream.testuk.org" in page.url.lower() and "keygenerate" not in page.url.lower():
            html = await page.content()
            pw = re.search(r'PW_HEADERS\s*=\s*({.*?});', html, re.DOTALL)
            if pw:
                try:
                    pw_hdrs = json.loads(pw.group(1))
                    hdr_file = Path(__file__).parent / "pw_headers.json"
                    hdr_file.write_text(json.dumps(pw_hdrs, indent=2), "utf-8")
                    print(f"  PW_HEADERS updated in pw_headers.json")
                except Exception as e:
                    print(f"  PW_HEADERS parse failed: {e}")
            mt = re.search(r'MEDIA_TOKEN\s*=\s*"([^"]+)"', html)
            if mt:
                print(f"  MEDIA_TOKEN found: {mt.group(1)[:60]}...")

        await browser.close()
        print("\n  Done! Cookies saved. Now run batch_download.py")
        return True

if __name__ == "__main__":
    success = asyncio.run(main())
    if not success:
        sys.exit(1)
