import asyncio, aiohttp, json, re, sys
from urllib.parse import urlparse, parse_qs

async def test():
    batch_url = open("batch_link.txt", encoding="utf-8").read().strip()
    async with aiohttp.ClientSession() as sess:
        async with sess.get(batch_url, headers={"User-Agent": "Mozilla/5.0"}) as r:
            html = await r.text()

        pw_hdr = json.loads(re.search(r"const\s+PW_HDR\s*=\s*({.*?});", html, re.DOTALL).group(1))
        qs = parse_qs(urlparse(batch_url).query)
        batch_id = qs["batchId"][0]
        subject_id = qs["subjectId"][0]
        print(f"Batch: {batch_id}, Subject: {subject_id}")
        print(f"PW_HDR keys: {list(pw_hdr.keys())}")

        async with sess.get(f"https://api.penpencil.co/v2/batches/{batch_id}/subject/{subject_id}/topics?page=1", headers=pw_hdr) as r:
            ch_data = await r.json()

        for ch in ch_data.get("data", []):
            if "Acceptance" in ch.get("name", ""):
                ch_id = ch["_id"]
                print(f'\nChapter: {ch["name"]} (id: {ch_id})')

                async with sess.get(f"https://api.penpencil.co/v2/batches/{batch_id}/subject/{subject_id}/contents?page=1&contentType=videos&tag={ch_id}", headers=pw_hdr) as r:
                    vid_data = await r.json()

                for vid in vid_data.get("data", []):
                    vid_name = vid.get("topic", "Unknown")
                    sched_id = vid.get("_id", "")
                    print(f'\n  Video: {vid_name[:60]}')
                    print(f"  Schedule ID: {sched_id}")

                    sd_url = f"https://stream.testuk.org/schedule-details?batchId={batch_id}&subjectId={subject_id}&scheduleId={sched_id}&tap=video"
                    async with sess.get(sd_url, headers=pw_hdr, allow_redirects=True) as r:
                        sd_body = await r.text()
                        print(f"  Status: {r.status}, Content-Type: {r.content_type}")
                        print(f"  Final URL: {r.url}")
                        print(f"  Body first 200: {sd_body[:200]}")

                        if sd_body.strip().startswith("{"):
                            try:
                                jd = json.loads(sd_body)
                                print(f"  JSON keys: {list(jd.keys())[:15]}")
                                print(f"  JSON: {json.dumps(jd, indent=2)[:2000]}")
                            except:
                                pass
                        elif r.content_type and "text/html" in r.content_type:
                            vm = re.search(r"const\s+VIDEO_DATA\s*=\s*({.*?});", sd_body, re.DOTALL)
                            if vm:
                                print("  VIDEO_DATA found!")
                                vd = json.loads(vm.group(1))
                                print(f'  mpd_url: {vd.get("url", "")[:80]}...')
                                print(f'  drmType: {vd.get("drmType", "?")}')
                            else:
                                print("  No VIDEO_DATA in page")
                                fname = f'_debug_{vid_name[:30].strip().replace(" ","_")}.html'
                                with open(fname, "w", encoding="utf-8") as f:
                                    f.write(sd_body[:100000])
                                print(f"  Saved page to {fname}")
                                scripts = re.findall(r"<script[^>]*>([\s\S]*?)</script>", sd_body, re.IGNORECASE)
                                for i, st in enumerate(scripts):
                                    if any(k in st.lower() for k in ["video", "mpd", "drm", "vod", "stream", "token", "manifest", "config", "data"]):
                                        print(f"  Relevant script[{i}]: {st[:600]}...")
                                        break
                                urls = re.findall(r"https?://[^\"'\s<>]+(?:\.mpd|master[^\"'\s]*)", sd_body)
                                if urls:
                                    print(f"  MPD URLs found: {urls[:3]}")
                                keys_found = re.findall(r"[a-f0-9]{32}", sd_body)
                                if keys_found:
                                    print(f"  Potential keys (32-char hex): {keys_found[:3]}")
                    break
                break

asyncio.run(test())
