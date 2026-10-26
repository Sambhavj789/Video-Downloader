import asyncio, json, re
from playwright.async_api import async_playwright

async def test():
    p = await async_playwright().start()
    b = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    ctx = b.contexts[0]
    
    # Use a worker page (separate from user's tabs)
    page = await ctx.new_page()
    
    url = "https://stream.testuk.org/content?batchId=68d63d619fb9929d48a19674&subjectId=68dcffcb485e6f500cd51e3f&scheduleId=6980a63931cbfcd747c58fc6"
    
    print(f"Navigating to: {url}")
    resp = await page.goto(url, wait_until="commit", timeout=30000)
    print(f"Response status: {resp.status}" if resp else "No response")
    print(f"Final URL: {page.url}")
    
    html = await page.content()
    if "keygenerate" in html.lower() or "keygenerate" in page.url.lower():
        print(f"BLOCKED: keygenerate. Title: {await page.title()}")
        print(f"HTML length: {len(html)}")
        # Check if there's a redirect happening
        print(f"First 300: {html[:300]}")
    else:
        mt = re.search(r'MEDIA_TOKEN\s*=\s*"([^"]+)"', html)
        if mt:
            print(f"SUCCESS! MEDIA_TOKEN: {mt.group(1)[:60]}...")
        else:
            print(f"Page loaded ({len(html)} chars), no MEDIA_TOKEN")
    
    await page.close()
    await b.close()
    await p.stop()

asyncio.run(test())
