import asyncio, json, re
from urllib.parse import urlparse, parse_qs
from curl_cffi.requests import AsyncSession

async def test():
    pw_headers = json.loads(open("pw_headers.json", encoding="utf-8").read())
    cookies = json.loads(open("stream_cookies.json", encoding="utf-8").read())
    batch_url = open("batch_link.txt", encoding="utf-8").read().strip()
    qs = parse_qs(urlparse(batch_url).query)
    batch_id = qs["batchId"][0]
    subject_id = qs["subjectId"][0]

    # Use browser-like headers (without content-type for GET)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Referer": "https://stream.testuk.org/keygenerate",
    }

    sched_id = "6984a04a9e230d92b27e4d82"
    content_url = f"https://stream.testuk.org/content?batchId={batch_id}&subjectId={subject_id}&scheduleId={sched_id}"
    print(f"=== Testing curl_cffi with fresh cookies ===")
    
    for imp in ["chrome124", "chrome120", "safari17_0"]:
        print(f"\n--- Impersonating {imp} ---")
        async with AsyncSession(impersonate=imp) as sess:
            resp = await sess.get(content_url, headers=headers, cookies=cookies)
            print(f"  Status: {resp.status_code}, URL: {resp.url}")
            if "keygenerate" in resp.url.lower():
                print(f"  Still keygenerate")
            else:
                body = resp.text
                print(f"  SUCCESS! ({len(body)} chars)")
                mt = re.search(r'MEDIA_TOKEN\s*=\s*"([^"]+)"', body)
                if mt:
                    print(f"  MEDIA_TOKEN: {mt.group(1)[:80]}...")
                pw = re.search(r'PW_HEADERS\s*=\s*({.*?});', body, re.DOTALL)
                if pw:
                    print(f"  PW_HEADERS found")
                break
    else:
        print("\nAll impersonations failed :(")
        
        # Last resort: try the actual browser flow from cookies
        # Maybe we need to also visit /keygenerate or /keyloginsuccess first
        print("\n=== Trying /keyloginsuccess flow ===")
        async with AsyncSession(impersonate="chrome124") as sess:
            # First visit the tipsguru redirect
            import base64
            tips_url = "https://tipsguru.in/prolink.php?id=aHR0cHM6Ly9zdHJlYW0udGVzdHVrLm9yZy9rZXlsb2dpbnN1Y2Nlc3M%3D"
            resp = await sess.get(tips_url, headers=headers, cookies=cookies)
            print(f"  Tipsguru: Status={resp.status_code}, URL={resp.url}")
            
            # Now visit keyloginsuccess
            resp = await sess.get("https://stream.testuk.org/keyloginsuccess?key=test", headers=headers, cookies=cookies)
            print(f"  keyloginsuccess: Status={resp.status_code}, URL={resp.url}")
            
            # Now try content page again
            resp = await sess.get(content_url, headers=headers, cookies=cookies)
            print(f"  Content: Status={resp.status_code}, URL={resp.url}")
            if "keygenerate" not in resp.url.lower():
                print(f"  SUCCESS after flow!")
                body = resp.text
                mt = re.search(r'MEDIA_TOKEN\s*=\s*"([^"]+)"', body)
                if mt:
                    print(f"  MEDIA_TOKEN: {mt.group(1)[:80]}...")

asyncio.run(test())
