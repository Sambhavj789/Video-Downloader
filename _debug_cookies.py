import asyncio, json
from playwright.async_api import async_playwright

async def main():
    p = await async_playwright().start()
    b = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    ctx = b.contexts[0]
    
    cookies = await ctx.cookies()
    for c in cookies:
        if c["name"] in ("session", "cf_clearance"):
            print(f"{c['name']}:")
            print(f"  domain: {c.get('domain')}")
            print(f"  path: {c.get('path')}")
            print(f"  httponly: {c.get('httpOnly')}")
            print(f"  secure: {c.get('secure')}")
            print(f"  samesite: {c.get('sameSite')}")
            print(f"  expires: {c.get('expires')}")
            print(f"  value: {c['value'][:60]}...")
            print()
    
    # Also check: can we navigate to ANY page on stream.testuk.org?
    print("Testing navigation to stream.testuk.org homepage...")
    page = await ctx.new_page()
    try:
        await page.goto("https://stream.testuk.org", wait_until="domcontentloaded", timeout=15000)
        print(f"  URL: {page.url}")
        html = await page.content()
        if "keygenerate" not in html.lower() and "keygenerate" not in page.url.lower():
            print("  HOMEPAGE LOADS WITHOUT KEYGENERATE!")
        else:
            print(f"  Homepage: {await page.title()}")
    except Exception as e:
        print(f"  Error: {e}")
    await page.close()
    await b.close()
    await p.stop()

asyncio.run(main())
