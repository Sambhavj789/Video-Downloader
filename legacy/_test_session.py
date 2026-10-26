import asyncio, json, re
from curl_cffi.requests import AsyncSession

async def test():
    cookies = json.load(open("stream_cookies.json"))
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    url = "https://stream.testuk.org/content?batchId=68d63d619fb9929d48a19674&subjectId=68dcffcb485e6f500cd51e3f&scheduleId=6980a63931cbfcd747c58fc6"

    for imp in ["chrome124", "chrome120", "chrome110"]:
        print(f"\n--- {imp} ---")
        async with AsyncSession(impersonate=imp) as sess:
            resp = await sess.get(url, headers=headers, cookies=cookies)
            print(f"  Status: {resp.status_code}, URL: {resp.url}")
            if "keygenerate" not in resp.url.lower() and "keygenerate" not in resp.text.lower():
                mt = re.search(r'MEDIA_TOKEN\s*=\s*"([^"]+)"', resp.text)
                if mt:
                    print(f"  SUCCESS! MEDIA_TOKEN: {mt.group(1)[:60]}...")
                else:
                    print(f"  Page loaded, no MEDIA_TOKEN, len={len(resp.text)}")
                break
            else:
                print(f"  Still keygenerate")
    else:
        print("\nNone worked. Trying aiohttp with cookies...")
        import aiohttp
        cookie_str = "; ".join(f"{k}={v}" for k,v in cookies.items() 
                              if k in ("session", "cf_clearance"))
        hdrs = dict(headers)
        hdrs["Cookie"] = cookie_str
        async with aiohttp.ClientSession() as sess:
            async with sess.get(url, headers=hdrs, allow_redirects=True) as r:
                print(f"  aiohttp: {r.status}, URL: {r.url}")
                if "keygenerate" not in str(r.url):
                    print(f"  aiohttp SUCCESS!")
                else:
                    print(f"  aiohttp STILL keygenerate")

asyncio.run(test())
