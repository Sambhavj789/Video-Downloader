import asyncio, json
from playwright.async_api import async_playwright

async def debug():
    p = await async_playwright().start()
    b = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    ctx = b.contexts[0]
    
    # Check cookies in context
    cookies = await ctx.cookies()
    print(f"Cookies in context ({len(cookies)}):")
    for c in cookies:
        print(f"  {c['name']}: {c['value'][:60]}... domain={c['domain']}")
    
    # Check user's current page URL
    if ctx.pages:
        print(f"\nUser's current page: {ctx.pages[0].url}")
    
    # Create a new page and navigate to video page
    page = await ctx.new_page()
    url = "https://stream.testuk.org/content?batchId=68d63d619fb9929d48a19674&subjectId=68dcffcb485e6f500cd51e3f&scheduleId=6981c2872e67f8559a57660d"
    print(f"\nNavigating to: {url}")
    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    print(f"After navigation URL: {page.url}")
    html = await page.content()
    if "keygenerate" in html.lower() or "keygenerate" in page.url.lower():
        print(f"BLOCKED: Still on keygenerate page")
        print(f"Title: {await page.title()}")
    else:
        print(f"SUCCESS! Page loaded, {len(html)} chars")
    
    await page.close()
    await b.close()
    await p.stop()

asyncio.run(debug())
