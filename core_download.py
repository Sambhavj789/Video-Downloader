import re, json, os, sys, shutil, asyncio, aiohttp, base64, subprocess
import xml.etree.ElementTree as ET
from urllib.parse import urlparse, parse_qs, urlencode
from pathlib import Path

FFMPEG_CACHE = None

def get_ffmpeg():
    global FFMPEG_CACHE
    if FFMPEG_CACHE:
        return FFMPEG_CACHE
    try:
        import imageio_ffmpeg
        FFMPEG_CACHE = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        FFMPEG_CACHE = shutil.which("ffmpeg") or "ffmpeg"
    return FFMPEG_CACHE

def extract_key(video_data):
    """Extract decryption key from VIDEO_DATA.
    Tries key_strings first, then keys array/object.
    Returns key_hex string or None if no key found.
    """
    if "key_strings" in video_data:
        ks = video_data["key_strings"]
        if "--key " in ks:
            parts = ks.replace("--key ", "").split(":")
            if len(parts) >= 2:
                return parts[1]

    if "keys" in video_data and video_data["keys"]:
        keys = video_data["keys"]
        if isinstance(keys, list) and len(keys) > 0:
            first = str(keys[0]) if not isinstance(keys[0], str) else keys[0]
            parts = first.split(":")
            if len(parts) >= 2:
                return parts[1]
        elif isinstance(keys, dict):
            for k, v in keys.items():
                return str(v)

    return None

async def try_widevine_license(video_data, session):
    """Try to get decryption key from Widevine license server.
    Returns key_hex or None.
    """
    license_url = video_data.get("licenseUrl", "")
    license_token = video_data.get("licenseToken", "")
    pssh_b64 = video_data.get("pssh", "")
    cert_url = video_data.get("certificateUrl", "")
    if not license_url or not pssh_b64:
        return None
    try:
        pssh_bytes = base64.b64decode(pssh_b64)
        headers = {"Content-Type": "application/octet-stream"}
        if license_token:
            headers["Authorization"] = f"Bearer {license_token}"
        print(f"      [LICENSE] POST to {license_url}")
        async with session.post(license_url, data=pssh_bytes, headers=headers,
                                timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status == 200:
                data = await resp.read()
                print(f"      [LICENSE] Response: {len(data)} bytes, first 200 hex: {data[:200].hex()}")
                print(f"      [LICENSE] Response as text: {data[:500]}")
                try:
                    js = json.loads(data)
                    print(f"      [LICENSE] JSON response: {json.dumps(js, indent=2)[:1000]}")
                except:
                    pass
            else:
                text = await resp.text()
                print(f"      [LICENSE] HTTP {resp.status}: {text[:300]}")
        return None
    except Exception as e:
        print(f"      [LICENSE] Error: {e}")
        return None

def get_base_and_auth(mpd_url):
    parsed = urlparse(mpd_url)
    qs = parse_qs(parsed.query)
    raw = qs.get("URLPrefix", [""])[0]
    raw += "=" * (4 - len(raw) % 4)
    base = base64.b64decode(raw).decode("utf-8").rstrip("/") + "/"
    auth_only = {k: v[0] for k, v in qs.items() if k != "URLPrefix"}
    return base, auth_only

def count_segments(seg_tl):
    if seg_tl is None:
        return 0
    ns = {"mpd": "urn:mpeg:dash:schema:mpd:2011"}
    return sum(int(s.get("r", 0)) + 1 for s in seg_tl.findall("mpd:S", ns))

async def fetch_text(url, headers=None, session=None):
    if session:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=60)) as resp:
            return await resp.text()
    async with aiohttp.ClientSession() as s:
        async with s.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=60)) as resp:
            return await resp.text()

async def download_video(media_page_url, output_path, temp_dir, pw_headers=None, progress_prefix="", video_data_override=None, pw_fetcher=None):
    """Download a single video from its media page URL to output_path.
    Uses temp_dir for intermediate files.
    Returns True on success, False on failure.
    """
    indent = progress_prefix + "  " if progress_prefix else ""
    try:
        if video_data_override:
            video_data = video_data_override
            print(f"{indent}[OVERRIDE] Using provided video_data")
            print(f"{indent}[DEBUG] drmType: {video_data.get('drmType', 'N/A')}")
            print(f"{indent}[DEBUG] has keys: {'keys' in video_data or 'key_strings' in video_data}")
        else:
            if pw_fetcher:
                html = await pw_fetcher.fetch_html(media_page_url)
            else:
                if pw_headers:
                    page_headers = {k: v for k, v in pw_headers.items() if k.lower() != "content-type"}
                else:
                    page_headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                html = await fetch_text(media_page_url, page_headers)
            print(f"{indent}[DEBUG] Page fetched, length: {len(html)} chars")
            print(f"{indent}[DEBUG] First 500 chars: {html[:500]}")
            print(f"{indent}[DEBUG] Last 300 chars: {html[-300:]}")
            print(f"{indent}[DEBUG] Looking for VIDEO_DATA / RAW_URL / MEDIA_TOKEN...")

            video_data = None
            video_data_m = re.search(r'(?:const|var|let|window\.)\s+VIDEO_DATA\s*=\s*({.*?});', html, re.DOTALL)
            if not video_data_m:
                for st in re.findall(r'<script[^>]*>([\s\S]*?)</script>', html, re.IGNORECASE):
                    video_data_m = re.search(r'(?:const|var|let|window\.)\s+VIDEO_DATA\s*=\s*({.*?});', st, re.DOTALL)
                    if video_data_m:
                        break
            if video_data_m:
                video_data = json.loads(video_data_m.group(1))
                print(f"{indent}[DEBUG] Found VIDEO_DATA in page")

            if not video_data:
                raw_url_m = re.search(r'(?:const|var|let|window\.)\s+RAW_URL\s*=\s*"([^"]+)"', html)
                parent_id_m = re.search(r'(?:const|var|let|window\.)\s+PARENT_ID\s*=\s*"([^"]+)"', html)
                child_id_m = re.search(r'(?:const|var|let|window\.)\s+CHILD_ID\s*=\s*"([^"]+)"', html)
                url_type_m = re.search(r'(?:const|var|let|window\.)\s+RAW_URL_TYPE\s*=\s*"([^"]+)"', html)
                if raw_url_m and parent_id_m and child_id_m:
                    raw_url = raw_url_m.group(1)
                    parent_id = parent_id_m.group(1)
                    child_id = child_id_m.group(1)
                    url_type = url_type_m.group(1) if url_type_m else "penpencilvdo"
                    print(f"{indent}[DEBUG] Found RAW_URL (new format) — resolving via API...")
                    api_qs = urlencode({
                        "url": raw_url, "parentId": parent_id,
                        "childId": child_id, "urlType": url_type,
                        "videoContainerType": "DASH"
                    })
                    api_url = f"{urlparse(media_page_url).scheme}://{urlparse(media_page_url).hostname}/v1/videos/video-url-details?{api_qs}"
                    if pw_fetcher:
                        api_data = await pw_fetcher.fetch_api_json(api_url)
                    else:
                        api_headers = pw_headers if pw_headers else {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                        api_resp = await fetch_text(api_url, api_headers)
                        api_data = json.loads(api_resp)
                    if api_data.get("success") and api_data.get("data"):
                        r = api_data["data"]
                        video_data = {"drmType": r.get("drmType", "ClearKey"), "url": r["url"]}
                        for k in ["keys", "key_strings", "pssh", "licenseUrl", "licenseToken", "certificateUrl"]:
                            if r.get(k):
                                video_data[k] = r[k]
                        print(f"{indent}[DEBUG] Resolved via API: url={video_data['url'][:80]}... drmType={video_data.get('drmType','?')} has_keys={'keys' in video_data or 'key_strings' in video_data}")
                    else:
                        print(f"{indent}[DEBUG] API: {api_resp[:500]}")
                        print(f"{indent}FAIL: Video API returned no data")
                        return False
                else:
                    media_token_m = re.search(r'(?:const|var|let|window\.)\s+MEDIA_TOKEN\s*=\s*"([^"]+)"', html)
                    if media_token_m:
                        media_token = media_token_m.group(1)
                        print(f"{indent}[DEBUG] Found MEDIA_TOKEN — resolving via API...")
                        api_headers = pw_headers
                        if api_headers is None:
                            pw_hdr_m_local = re.search(r'(?:const|var|let|window\.)\s+PW_HEADERS\s*=\s*({.*?});', html, re.DOTALL)
                            if pw_hdr_m_local:
                                try:
                                    api_headers = json.loads(pw_hdr_m_local.group(1))
                                except:
                                    pass
                        if api_headers is None:
                            api_headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                        api_qs = urlencode({"mediaToken": media_token, "videoContainerType": "DASH"})
                        api_url = f"{urlparse(media_page_url).scheme}://{urlparse(media_page_url).hostname}/v1/videos/video-url-details?{api_qs}"
                        if pw_fetcher:
                            api_data = await pw_fetcher.fetch_api_json(api_url)
                        else:
                            api_resp = await fetch_text(api_url, api_headers)
                            api_data = json.loads(api_resp)
                        if api_data.get("success") and api_data.get("data"):
                            r = api_data["data"]
                            video_data = {"drmType": r.get("drmType", "ClearKey"), "url": r["url"]}
                            for k in ["keys", "key_strings", "pssh", "licenseUrl", "licenseToken", "certificateUrl"]:
                                if r.get(k):
                                    video_data[k] = r[k]
                            print(f"{indent}[DEBUG] Resolved via MEDIA_TOKEN API: url={video_data['url'][:80]}... drmType={video_data.get('drmType','?')} has_keys={'keys' in video_data or 'key_strings' in video_data}")
                        else:
                            print(f"{indent}[DEBUG] MEDIA_TOKEN API: {api_resp[:500]}")
                            print(f"{indent}FAIL: MEDIA_TOKEN API returned no data")
                            return False
                    if not video_data:
                        print(f"{indent}FAIL: No VIDEO_DATA, RAW_URL, or MEDIA_TOKEN found on page")
                        return False

            if pw_headers is None:
                pw_hdr_m = re.search(r'(?:const|var|let|window\.)\s+PW_HEADERS\s*=\s*({.*?});', html, re.DOTALL)
                if not pw_hdr_m:
                    for st in re.findall(r'<script[^>]*>([\s\S]*?)</script>', html, re.IGNORECASE):
                        pw_hdr_m = re.search(r'(?:const|var|let|window\.)\s+PW_HEADERS\s*=\s*({.*?});', st, re.DOTALL)
                        if pw_hdr_m:
                            break
                if pw_hdr_m:
                    pw_headers = json.loads(pw_hdr_m.group(1))
                else:
                    print(f"{indent}FAIL: No PW_HEADERS found on page and none provided")
                    return False

        mpd_url = video_data["url"]
        print(f"{indent}[DEBUG] drmType: {video_data.get('drmType', 'N/A')}")
        print(f"{indent}[DEBUG] has key_strings: {'key_strings' in video_data}")
        print(f"{indent}[DEBUG] has keys array: {'keys' in video_data}")
        if "keys" in video_data:
            print(f"{indent}[DEBUG] keys data: {json.dumps(video_data['keys'], indent=2)}")
        print(f"{indent}[DEBUG] all VIDEO_DATA keys: {list(video_data.keys())}")
        if video_data.get("drmType") == "Widevine":
            print(f"{indent}[DEBUG] licenseUrl: {video_data.get('licenseUrl', 'N/A')}")
            print(f"{indent}[DEBUG] licenseToken: {str(video_data.get('licenseToken', 'N/A'))[:80]}")
            print(f"{indent}[DEBUG] certificateUrl: {video_data.get('certificateUrl', 'N/A')}")
            print(f"{indent}[DEBUG] pssh (b64): {video_data.get('pssh', 'N/A')[:80]}")
        print(f"{indent}[DEBUG] mpd_url: {mpd_url[:120]}...")
        key_hex = extract_key(video_data)
        if not key_hex:
            drm = video_data.get("drmType", "unknown")
            if drm == "Widevine":
                print(f"{indent}  Widevine DRM — trying license server...")
                async with aiohttp.ClientSession() as sess:
                    key_hex = await try_widevine_license(video_data, sess)
                if not key_hex:
                    print(f"{indent}  License server failed, will try without key (might be unencrypted)...")
            else:
                print(f"{indent}  SKIP: DRM-protected ({drm}) — no decryption key found")
                return False
        base_url, _ = get_base_and_auth(mpd_url)
        auth_qs = urlencode(parse_qs(urlparse(mpd_url).query), doseq=True)

        mpd_xml = await fetch_text(mpd_url, pw_headers)
        root = ET.fromstring(mpd_xml)
        ns = {"mpd": "urn:mpeg:dash:schema:mpd:2011"}

        has_encryption = root.find(".//mpd:ContentProtection", ns) is not None
        print(f"{indent}[DEBUG] MPD has ContentProtection: {has_encryption}")
        if has_encryption:
            for cp in root.findall(".//mpd:ContentProtection", ns):
                scheme = cp.get("schemeIdUri", "N/A")
                print(f"{indent}[DEBUG]   ContentProtection scheme: {scheme}")
                for child in cp:
                    print(f"{indent}[DEBUG]     {child.tag}: {child.text[:80] if child.text else 'N/A'}")
        if not has_encryption and key_hex:
            print(f"{indent}  No ContentProtection in MPD, ignoring key")
            key_hex = None
        if has_encryption and not key_hex:
            drm = video_data.get("drmType", "unknown")
            print(f"{indent}  MPD has ContentProtection but no key — trying download without decryption anyway...")

        manifests = []
        for period in root.findall(".//mpd:Period", ns):
            for ads in period.findall("mpd:AdaptationSet", ns):
                ct = ads.get("contentType", "")
                for rep in ads.findall("mpd:Representation", ns):
                    tmpl = rep.find("mpd:SegmentTemplate", ns)
                    if tmpl is None:
                        continue
                    bw = int(rep.get("bandwidth", 0))
                    manifests.append({
                        "type": ct, "init": tmpl.get("initialization"),
                        "media": tmpl.get("media"),
                        "count": count_segments(tmpl.find("mpd:SegmentTimeline", ns)),
                        "bw": bw, "rep": rep,
                        "qual": f"{rep.get('height', '?')}p" if ct == "video" else "audio",
                    })

        videos = [m for m in manifests if m["type"] == "video"]
        audios = [m for m in manifests if m["type"] == "audio"]
        if not videos or not audios:
            print(f"{indent}FAIL: No video or audio tracks")
            return False
        best_video = max(videos, key=lambda x: x["bw"])
        best_audio = max(audios, key=lambda x: x["bw"])

        temp_dir = Path(temp_dir)
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
        temp_dir.mkdir(parents=True, exist_ok=True)

        dl_items = []
        for m in [best_video, best_audio]:
            prefix = m["qual"]
            init_local = temp_dir / f"{prefix}_init.mp4"
            dl_items.append((f"{base_url}{m['init']}?{auth_qs}", init_local))
            m["init_local"] = init_local.name
            for i in range(m["count"]):
                seg_path = m["media"].replace("$Number$", str(i + 1))
                seg_local = temp_dir / f"{prefix}_{i+1}.mp4"
                dl_items.append((f"{base_url}{seg_path}?{auth_qs}", seg_local))
            m["seg_pattern"] = f"{prefix}_$Number$.mp4"

        total = len(dl_items)
        connector = aiohttp.TCPConnector(limit=5)
        downloaded = 0
        failures = 0
        downloaded_bytes = 0

        async with aiohttp.ClientSession(connector=connector) as session:
            sem = asyncio.Semaphore(5)
            async def limited_dl(url, path):
                nonlocal downloaded_bytes
                async with sem:
                    for attempt in range(8):
                        try:
                            async with session.get(url, headers=pw_headers, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                                if resp.status != 200:
                                    if attempt < 7:
                                        await asyncio.sleep(1 * (2 ** attempt))
                                        continue
                                    return False
                                data = await resp.read()
                                path.write_bytes(data)
                                downloaded_bytes += len(data)
                                return True
                        except Exception:
                            if attempt < 7:
                                await asyncio.sleep(1 * (2 ** attempt))
                            continue
                    return False
            tasks = [asyncio.ensure_future(limited_dl(u, p)) for u, p in dl_items]
            for coro in asyncio.as_completed(tasks):
                ok = await coro
                if not ok:
                    failures += 1
                downloaded += 1
                if downloaded % 100 == 0 or downloaded == total:
                    mb = downloaded_bytes / (1024 * 1024)
                    print(f"{indent}  Segments: {downloaded}/{total} ({mb:.1f} MB, {failures} bad)".ljust(80), end="\r")
            mb = downloaded_bytes / (1024 * 1024)
            print(f"{indent}  Segments: {total}/{total} ({mb:.1f} MB, {failures} bad)".ljust(80))

        if failures > total * 0.5:
            print(f"{indent}  Too many failures ({failures}/{total}), skipping")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return False

        ET.register_namespace("", "urn:mpeg:dash:schema:mpd:2011")
        ET.register_namespace("cenc", "urn:mpeg:cenc:2013")

        local_root = ET.Element("{urn:mpeg:dash:schema:mpd:2011}MPD", {
            "profiles": "urn:mpeg:dash:profile:isoff-live:2011",
            "minBufferTime": "PT2S", "type": "static", "mediaPresentationDuration": "PT7680S",
        })
        period = ET.SubElement(local_root, "Period", {"id": "0"})

        for m in [best_audio, best_video]:
            ads = ET.SubElement(period, "AdaptationSet", {
                "contentType": m["type"], "segmentAlignment": "true", "startWithSAP": "1",
            })
            if m["type"] == "audio":
                ads.set("lang", "en")
            for orig_ads in root.findall(".//mpd:AdaptationSet", ns):
                if orig_ads.get("contentType") == m["type"]:
                    for cp in orig_ads.findall("mpd:ContentProtection", ns):
                        ce = ET.SubElement(ads, "ContentProtection", dict(cp.attrib))
                        for child in cp:
                            ce2 = ET.SubElement(ce, child.tag, dict(child.attrib))
                            if child.text:
                                ce2.text = child.text
                    break
            rep = ET.SubElement(ads, "Representation")
            ori = m["rep"]
            for attr in ["id", "bandwidth", "codecs", "mimeType", "width", "height", "audioSamplingRate", "frameRate"]:
                v = ori.get(attr)
                if v:
                    rep.set(attr, v)
            if m["type"] == "audio":
                for ac in ori.findall("mpd:AudioChannelConfiguration", ns):
                    ET.SubElement(rep, "AudioChannelConfiguration", dict(ac.attrib))
            ot = ori.find("mpd:SegmentTemplate", ns)
            st = ET.SubElement(rep, "SegmentTemplate", {
                "timescale": ot.get("timescale", "1"),
                "initialization": m["init_local"],
                "media": m["seg_pattern"],
                "startNumber": "1",
            })
            otl = ot.find("mpd:SegmentTimeline", ns)
            if otl is not None:
                tl = ET.SubElement(st, "SegmentTimeline")
                for s in otl.findall("mpd:S", ns):
                    ET.SubElement(tl, "S", dict(s.attrib))

        local_mpd = temp_dir / "local.mpd"
        local_mpd.write_bytes(ET.tostring(local_root, encoding="utf-8", xml_declaration=True))

        ffmpeg = get_ffmpeg()
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [ffmpeg]
        if key_hex:
            cmd += ["-cenc_decryption_key", key_hex]
        cmd += ["-i", str(local_mpd), "-c", "copy",
                "-movflags", "+faststart", "-y", str(output_path)]
        sys.stdout.flush()
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"{indent}  ffmpeg failed ({result.returncode})")
            if output_path.exists():
                output_path.unlink()
            shutil.rmtree(temp_dir, ignore_errors=True)
            return False

        if output_path.exists():
            size_mb = output_path.stat().st_size / (1024 * 1024)
            print(f"{indent}  Output: {output_path.name} ({size_mb:.1f} MB)")

        shutil.rmtree(temp_dir, ignore_errors=True)
        return True

    except Exception as e:
        print(f"{indent}  ERROR: {e}")
        shutil.rmtree(temp_dir, ignore_errors=True)
        return False
