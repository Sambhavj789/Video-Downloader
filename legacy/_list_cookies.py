import asyncio, json
from playwright.async_api import async_playwright

async def main():
    p = await async_playwright().start()
    b = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    ctx = b.contexts[0]
    
    cookies = await ctx.cookies()
    print("All cookies for testuk.org / stream.testuk.org:")
    for c in cookies:
        domain = c.get("domain", "")
        if "testuk" in domain or "pw.live" in domain or "penpencil" in domain:
            print(f"  {c['name']} ({domain}): {c['value'][:80]}...")
    
    print(f"\nTotal cookies: {len(cookies)}")
    
    await b.close()
    await p.stop()

asyncio.run(main())
