import asyncio, aiohttp, json, re

async def test():
    # Extract MEDIA_TOKEN from saved HTML
    html = open("video_html_code.html", encoding="utf-8").read()
    mt = re.search(r'MEDIA_TOKEN\s*=\s*"([^"]+)"', html)
    if not mt:
        print("No MEDIA_TOKEN found")
        return
    media_token = mt.group(1)
    print(f"MEDIA_TOKEN: {media_token[:60]}...")
    
    pw_headers = json.loads(open("pw_headers.json", encoding="utf-8").read())
    
    api_url = f"https://stream.testuk.org/v1/videos/video-url-details?mediaToken={media_token}&videoContainerType=DASH"
    print(f"\n=== Calling API ===")
    print(f"URL: {api_url[:120]}...")
    
    async with aiohttp.ClientSession() as sess:
        async with sess.get(api_url, headers=pw_headers) as r:
            print(f"Status: {r.status}")
            data = await r.json()
            print(f"Response: {json.dumps(data, indent=2)[:2000]}")
            
            if data.get("success") and data.get("data"):
                d = data["data"]
                print(f"\nVideo URL: {d.get('url', 'N/A')[:120]}...")
                print(f"DRM Type: {d.get('drmType', 'N/A')}")
                print(f"Has keys: {'keys' in d or 'key_strings' in d}")
                print(f"All keys: {list(d.keys())}")

asyncio.run(test())
