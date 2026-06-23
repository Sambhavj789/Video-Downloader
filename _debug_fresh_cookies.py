import asyncio, aiohttp, json, re
from urllib.parse import urlparse, parse_qs

async def test():
    pw_headers = json.loads(open("pw_headers.json", encoding="utf-8").read())
    cookies = json.loads(open("stream_cookies.json", encoding="utf-8").read())
    batch_url = open("batch_link.txt", encoding="utf-8").read().strip()
    qs = parse_qs(urlparse(batch_url).query)
    batch_id = qs["batchId"][0]
    subject_id = qs["subjectId"][0]

    # Build Cookie header
    cookie_parts = [f"{k}={v}" for k, v in cookies.items()]
    cookie_str = "; ".join(cookie_parts)
    print(f"Cookie: {cookie_str[:120]}...")

    hdrs = dict(pw_headers)
    hdrs["Cookie"] = cookie_str
    hdrs.pop("content-type", None)
    hdrs["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"

    sched_id = "6984a04a9e230d92b27e4d82"
    content_url = f"https://stream.testuk.org/content?batchId={batch_id}&subjectId={subject_id}&scheduleId={sched_id}"
    print(f"\n=== Test with fresh cookies ===")
    
    async with aiohttp.ClientSession() as sess:
        async with sess.get(content_url, headers=hdrs, allow_redirects=True) as r:
            print(f"Status: {r.status}, Final URL: {r.url}")
            body = await r.text()
            if "keygenerate" in str(r.url).lower() or "keygenerate" in body.lower():
                print("Still hitting keygenerate")
                print(f"Body first 300: {body[:300]}")
            else:
                print(f"SUCCESS! Got content page ({len(body)} chars)")
                mt = re.search(r'MEDIA_TOKEN\s*=\s*"([^"]+)"', body)
                if mt:
                    print(f"MEDIA_TOKEN: {mt.group(1)[:80]}...")

asyncio.run(test())
