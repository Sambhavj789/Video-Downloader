import asyncio, aiohttp, json

async def test():
    pw_headers = json.loads(open("pw_headers.json", encoding="utf-8").read())
    video_id = "69846eb7d6891e078390c291"  # from videoDetails._id
    
    endpoints = [
        f"https://api.penpencil.co/v2/videos/{video_id}",
        f"https://api.penpencil.co/v3/contents/{video_id}",
        f"https://api.penpencil.co/v2/videos/{video_id}/details",
        f"https://api.penpencil.co/v1/videos/{video_id}/url",
        f"https://api.penpencil.co/v2/media/video/{video_id}",
        f"https://api.penpencil.co/v2/stream/{video_id}",
    ]
    
    async with aiohttp.ClientSession() as sess:
        for url in endpoints:
            try:
                async with sess.get(url, headers=pw_headers) as r:
                    text = await r.text()
                    print(f"GET {url}")
                    print(f"  Status: {r.status}, CT: {r.content_type}")
                    if text.strip().startswith("{"):
                        data = json.loads(text)
                        print(f"  Keys: {list(data.keys())[:20]}")
                        if data.get("data"):
                            d = data["data"]
                            if isinstance(d, dict):
                                print(f"  Data keys: {list(d.keys())[:20]}")
                                for k in d:
                                    v = d[k]
                                    if isinstance(v, str) and "http" in v:
                                        print(f"    {k}: {v[:150]}")
                    else:
                        print(f"  Text: {text[:200]}")
            except Exception as e:
                print(f"GET {url}")
                print(f"  ERROR: {e}")
            print()
            
        # Try post endpoints
        post_urls = [
            "https://api.penpencil.co/v2/videos/get-url",
            "https://api.penpencil.co/v1/stream/get-url",
        ]
        for url in post_urls:
            try:
                payload = {"videoId": video_id, "contentType": "DASH"}
                async with sess.post(url, json=payload, headers=pw_headers) as r:
                    text = await r.text()
                    print(f"POST {url}")
                    print(f"  Status: {r.status}")
                    if text.strip().startswith("{"):
                        data = json.loads(text)
                        print(f"  Response: {json.dumps(data, indent=2)[:1000]}")
                    else:
                        print(f"  Text: {text[:200]}")
            except Exception as e:
                print(f"POST {url} ERROR: {e}")
            print()

asyncio.run(test())
