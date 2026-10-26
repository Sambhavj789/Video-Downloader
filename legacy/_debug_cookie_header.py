import asyncio, aiohttp, json, re
from urllib.parse import urlparse, parse_qs

async def test():
    pw_headers = json.loads(open("pw_headers.json", encoding="utf-8").read())
    batch_url = open("batch_link.txt", encoding="utf-8").read().strip()
    qs = parse_qs(urlparse(batch_url).query)
    batch_id = qs["batchId"][0]
    subject_id = qs["subjectId"][0]

    # Pass session cookie as Cookie header with aiohttp
    cookies_str = "cf_clearance=4W_Or26AJUudRPKhwreL4Td2.ytPf7Xu0fZAKdCzgVM-1782207588-1.2.1.1-pFmDdNIEBEZsafy0U2Ii9lI_zODdHMrV9_cBtO3sk24zKxV7o2U2UbOc4MmJigQf841Waa6BFTEj54YPCT5HIN4pM302F.16cFdLyN9jyXrK4QmoHzvCJYc7funClsfC_ivNIXe52ojG2AdzUt6GV8MQ00fDMJOPlzjSVdfQsNEo3_6xFNlxVfAIvYT6GKpVuuRWJIBO1y7lDCccVjK0Irlr2LmUGjqc30_8yw9LPLsasUi8fIQxGFgd0n6DhJ.apmUSW4zvePHHKKHsWdmdzHe5418RXBcRd.eDg81fjyO1vydtRrC1YTk2IgEYjg2xk5cYXSwyRpbu9nIQn2zGDA; session=.eJyt1EeupGYABOC7vC0eNTmM5AW5adJPDpsnMjQ5NmD57n5zBx-hVPXVP1_fU7H0yVAM29fvbdmLv76SLCvW9Xsb22L4-v21qb5gmjxfFDSXTNyau2gMXewdr2bkmJcFKSzJPt1CQuJa9xQfGpIYZFxYX1sUqKaWCSQOVoKF1UGHnufZdTbgK6dIvSoj1tQ44F1W3mwVwgqbo59MPrllV90PjNbSgPFHo808ZHafq0kQKHViPagpncucNj9cditF74gDUi_9kqHVofFI-WL9IQ6jOaR460Cd4U4bgVcacmLDwss-FpNjYt1o_vvqxTuhXm9Pdk2NgFmB8tvOchb7wRvIxeEPYmpcMXXOehNtcWx34wQZGCxoc4iQrKWZwyd80hmxxCvITmxdi4t95ip6otXkMhztQjWVH1NO3LCqmPcOOvbSF6-YJzWvXhJqd3wC-0gACbytSlrsxbruBjc70lwVM_haMkbOFQaDUK9BXNsfYm19BdvnFCo8QRPvwl1yUX52Z15Oa2kpmJCSmoRQD6V6UWK_yzNzRbu8ujmiwg4HPB8ZCtEgd0cC8MRMvRCKamLcw5zETUHCjpzaHldX60PFXS9y_bdCbmknLV27QA98vSZyHmxfM2lH1EYBhJTKIzzYMd6ZMem6kzfCCLuySM6LVGw5QrYiLVOVwcnFe5bdra3q4TwBIrOnWfufUKrhZNrFT9bmvnVmxgO3GbHZFeIO4fmMFMnRFFqmSe8heA-KDB29nKW24Q9arTuY60FbcvGH7OE6Ftu9JU5R9jN9OnS0Wus6_kR7CEiXyfMCZA4JDA5FK14BGB_AP6nZzY10TaqlDc9mNYl19u-vv76mz_f_DGANnZqL9miGkoenTonTU9gUZ02Nu-1jRrjgfIv-G8H0xKom04oX4yHTaJ3wsXY-n_QyMmHndqvXV0mkyp0p5DI8oTo1gCtglFeAsUSVtYpKBiq9r1NPULy9i2BpaBUckAe1T1lB8V6rvNaB30M4-dOPB_QFVsAalzovilwhtsUXiqPzZn2t84tPZKX18bvXhU8jFkZiZISdxZOI-Kk_nUZL-gFCqzCsTlbvAQJ_lM8tNQKDMFdJ2ciig8M8RG536ebibBmcitLEtj98rBhuX4jUbkhVE1vyftGpJFHZdLOYNuhtt0NTbpEtWSWU6q2XaM7lPvcugy6j7zQ_TVzAYGaPO6NVeKee0MeHte5XfgO3FwiFUd860ez7XXmwsu3YC0Nt08VmDcxSlGagps8rb5LReNmkIaX9pLunYO9osiivqreNR-0TczZ-xD5MOsGFw6XsW6VxRCNPpQxvX1PlkUdRqWcKK_C5nXbgVFkECftgBbvYy8cabF4h-rDtmCR79fvPzJpVM6ilz3_Cif52SXhcU5etRNbSp3X4fsWdEEA36vl7EQ9DLmmUP8auyjSh9eDl2xiDDmKOz_OAXexPo_1bLIU0byCjeIdUaqCPerFLRL1m2OklqQf6E4aJ4z0rasSXs7hyUdOyZemT8MhNxRmC4jEE9M3ZMIDJB8UqL2ocNzOW--BQKx-rnS7IOv69AEVqPj8olvV7_SHRjH88HPrhikDE5XuWHDwbnX0cIw9-HYRfIViJPZ9XwJJrVI-c7Ghz12sCUzYZMU2vOIicsu5hk26-Cwwk86Zq00z-3C2TUAiLCwGdiMFiP5tw4LSQV0ajMnX97B0tAuRyR5SFvrkrS76Z6RfFLyZy0tMF4JmKPpb1C9HegGH6RlSr208UhGaoFyWjYaCZci6PR0wl4PS__v0PfK1VGw.ajpUig.TJ0w0coKDzBH320mGD6erufsxjo; favourite_batches=[%2268d63d619fb9929d48a19674%22,%2268d642a49dfdb652ac3fcc23%22]"

    hdrs = dict(pw_headers)
    hdrs["Cookie"] = cookies_str
    # Remove content-type for GET
    hdrs.pop("content-type", None)

    sched_id = "6984a04a9e230d92b27e4d82"
    content_url = f"https://stream.testuk.org/content?batchId={batch_id}&subjectId={subject_id}&scheduleId={sched_id}"
    print(f"=== Fetching content page with Cookie header ===")
    
    async with aiohttp.ClientSession() as sess:
        async with sess.get(content_url, headers=hdrs, allow_redirects=True) as r:
            print(f"Status: {r.status}, Final URL: {r.url}")
            body = await r.text()
            if "keygenerate" in str(r.url).lower() or "keygenerate" in body.lower():
                print("Still hitting keygenerate")
                print(f"Body first 300: {body[:300]}")
            else:
                print(f"SUCCESS! Content page ({len(body)} chars)")
                mt = re.search(r'MEDIA_TOKEN\s*=\s*"([^"]+)"', body)
                if mt:
                    print(f"MEDIA_TOKEN: {mt.group(1)[:80]}...")

asyncio.run(test())
