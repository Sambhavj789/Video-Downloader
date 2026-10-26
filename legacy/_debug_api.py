import asyncio, aiohttp, json
from urllib.parse import urlparse, parse_qs

async def test():
    pw_headers = json.loads(open("pw_headers.json", encoding="utf-8").read())
    batch_url = open("batch_link.txt", encoding="utf-8").read().strip()
    qs = parse_qs(urlparse(batch_url).query)
    batch_id = qs["batchId"][0]
    subject_id = qs["subjectId"][0]

    print("Starting...")
    async with aiohttp.ClientSession() as sess:
        print("Fetching chapters...")
        async with sess.get(f"https://api.penpencil.co/v2/batches/{batch_id}/subject/{subject_id}/topics?page=1", headers=pw_headers) as r:
            ch_data = await r.json()
        print(f"Got {len(ch_data.get('data', []))} chapters")

        for ch in ch_data.get("data", []):
            print(f"Chapter: {ch.get('name','?')}")
            if "Accounts" in ch.get("name", ""):
                ch_id = ch["_id"]
                print(f"  Fetching videos for chapter {ch_id}...")
                async with sess.get(f"https://api.penpencil.co/v2/batches/{batch_id}/subject/{subject_id}/contents?page=1&contentType=videos&tag={ch_id}", headers=pw_headers) as r:
                    vid_data = await r.json()
                print(f"  Got {len(vid_data.get('data', []))} videos")

                for vid in vid_data.get("data", [])[:3]:
                    print("  Video keys:", list(vid.keys()))
                    print("    _id:", vid.get("_id",""))
                    for vk in vid.keys():
                        vv = vid[vk]
                        if isinstance(vv, str) and len(vv) < 500:
                            print(f"    {vk}: {vv}")
                    vd = vid.get("videoDetails", {})
                    if vd:
                        print("    videoDetails keys:", list(vd.keys()))
                        for k, v in vd.items():
                            if isinstance(v, str):
                                print(f"      {k}: {v[:200]}")
                            else:
                                print(f"      {k}: {type(v).__name__} = {str(v)[:200]}")
                    print()

                    sched_id = vid["_id"]
                    sd_url = f"https://stream.testuk.org/schedule-details?batchId={batch_id}&subjectId={subject_id}&scheduleId={sched_id}&tap=video"
                    json_headers = dict(pw_headers)
                    json_headers["Accept"] = "application/json"
                    async with sess.get(sd_url, headers=json_headers, allow_redirects=False) as r:
                        print(f"    schedule-details: Status={r.status}, Location={r.headers.get('Location','')[:200]}")
                        body = await r.text()
                        print(f"    Body preview: {body[:300]}")
                    print()
                break

if __name__ == "__main__":
    asyncio.run(test())
