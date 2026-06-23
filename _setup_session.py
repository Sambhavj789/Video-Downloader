"""
Step 1: Navigate to a video URL in your Chrome, let you complete the keygenerate flow,
and save cookies + verify they work.

After this succeeds, run batch_download.py
"""
import asyncio, json, re, sys
from pathlib import Path
from playwright.async_api import async_playwright

COOKIE_FILE = Path(__file__).parent / "stream_cookies.json"

async def main():
    print("=" * 60)
    print("  Connecting to your Chrome to set up access...")
    print()
    print("  Make sure Chrome is running with: --remote-debugging-port=9222")
    print("=" * 60)

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        ctx = browser.contexts[0]

        # Check existing cookies
        cookies = await ctx.cookies()
        has_session = any(c["name"] == "session" and "testuk.org" in c.get("domain","") for c in cookies)
        
        if has_session:
            print("\n  Session cookie found! You already have access.")
        else:
            print("\n  No session cookie found. Need to complete keygenerate flow.")
            print("  Opening a video page in a new tab...")
            page = await ctx.new_page()
            # Use a known video URL from the batch
            test_url = "https://stream.testuk.org/content?batchId=68d63d619fb9929d48a19674&subjectId=68dcffcb485e6f500cd51e3f&scheduleId=6980a63931cbfcd747c58fc6"
            await page.goto(test_url, wait_until="domcontentloaded", timeout=30000)
            
            print(f"\n  Current page: {page.url}")
            print("\n  If you see the 'Generate Access Key' page or tipsguru.in:")
            print("    -> Click through the buttons/ads in the Chrome window")
            print("    -> Keep going until the REAL video page appears")
            print("\n  Waiting for you to complete the flow (max 5 min)...")
            
            for i in range(300):
                await asyncio.sleep(1)
                url = page.url
                if "stream.testuk.org" in url and "keygenerate" not in url:
                    print(f"\n  SUCCESS! Reached content page: {url[:100]}")
                    break
                if i % 15 == 0:
                    print(f"  [{i}s] Current: {url[:80]}...")
            else:
                print("\n  Timeout. Did you complete the flow?")
                await page.close()
                await browser.close()
                return False

            await page.close()

        # Save cookies after flow
        cookies = await ctx.cookies()
        print(f"\n  Cookies found ({len(cookies)}):")
        cookie_data = {}
        for c in cookies:
            cookie_data[c["name"]] = c["value"]
            print(f"    {c['name']}: {c['value'][:60]}...")
        
        COOKIE_FILE.write_text(json.dumps(cookie_data, indent=2), "utf-8")
        print(f"\n  Cookies saved to {COOKIE_FILE}")

        # Verify by fetching a content page
        print("\n  Verifying access...")
        page2 = await ctx.new_page()
        test_urls = [
            "https://stream.testuk.org/content?batchId=68d63d619fb9929d48a19674&subjectId=68dcffcb485e6f500cd51e3f&scheduleId=6980a63931cbfcd747c58fc6",
            "https://stream.testuk.org/schedule-details?batchId=68d63d619fb9929d48a19674&subjectId=68dcffcb485e6f500cd51e3f&scheduleId=6980a63931cbfcd747c58fc6&tap=video",
        ]
        for url in test_urls:
            await page2.goto(url, wait_until="domcontentloaded", timeout=30000)
            html = await page2.content()
            if "keygenerate" not in html.lower() and "keygenerate" not in page2.url.lower():
                mt = re.search(r'MEDIA_TOKEN\s*=\s*"([^"]+)"', html)
                print(f"  [OK] {url[:80]}... -> {'MEDIA_TOKEN found' if mt else 'page loaded'}")
            else:
                print(f"  [FAIL] {url[:80]}... -> still blocked")
        await page2.close()
        
        await browser.close()
        print("\n  Done! Now run: python batch_download.py")
        return True

if __name__ == "__main__":
    success = asyncio.run(main())
    if not success:
        sys.exit(1)
