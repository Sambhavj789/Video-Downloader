import asyncio, json
from playwright.async_api import async_playwright

async def main():
    p = await async_playwright().start()
    b = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    ctx = b.contexts[0]
    
    cookies = await ctx.cookies()
    print(f"Cookies found: {len(cookies)}")
    cookie_data = {}
    has_session = False
    for c in cookies:
        cookie_data[c["name"]] = c["value"]
        if c["name"] == "session":
            has_session = True
            print(f"  [SESSION] {c['value'][:60]}...")
        elif c["name"] == "cf_clearance":
            print(f"  [CF] {c['value'][:60]}...")
    
    if cookie_data:
        json.dump(cookie_data, open("stream_cookies.json", "w"), indent=2)
        print(f"\nSaved {len(cookie_data)} cookies to stream_cookies.json")
    else:
        print("No cookies found!")
    
    # Check current page URL
    if ctx.pages:
        for pg in ctx.pages:
            print(f"\nTab: {pg.url[:100]}")
    
    await b.close()
    await p.stop()
    
    if has_session:
        print("\n[OK] Session cookie present!")
    else:
        print("\n[FAIL] No session cookie.")

asyncio.run(main())
