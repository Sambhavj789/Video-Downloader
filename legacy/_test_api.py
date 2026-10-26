import asyncio, json
from curl_cffi.requests import AsyncSession

async def test():
    headers = json.load(open("pw_headers.json"))
    token = "8Sbf0Y2UObtsy34z3TA4p1T3sRpXqNVMULMMrc2zr0E5ZGv-2NHp1cplKWGbvE2VrqG6MSXKbHKQYGuXbbhUAVaX3BipBPPDQkfgRocEm3J_LjVO3X6xWq6spj9e6EgSqXLS-Lv9muvwPHx8WaMgA2X5s9eObJ3oKeWr7cNSOAJEgK__eCnVzUAMkIMYRhKtflVw1ifLLWgdG_kxrRKcpH54P5TlD6S5XEQKrcmGdyuu5g7tAi0ECOl5VDBqRXfMyqMh2kzRCSqHg3yrNvXUJrb_34GEbiLaq1rKmhI0wFbe8BBYp0lI5AA6jwKsVbu1rll9TZkbjsopIeNuefaWufYhjLH-9cd_Zbh6JRMik_YdEkfCxkpvpHXuUlAEFnq1N6vNMq5hwvEvN7aXG2ILoW97SP2GzrKjY7SVHOkxPUXZN16zXplbYqIgJ1xVnQf-5whMUm6FGv7WkUmGVl3ZG9G9W2bhMqApnbXVtQhbDA4u8WVwFIWyzb0xmk8QuBAYSyMxtkIL5ouJdYfutp-2dOpq6qLhM8RwOJyv472eCNg"
    url = f"https://stream.testuk.org/v1/videos/video-url-details?mediaToken={token}&videoContainerType=DASH"

    for imp in ["chrome124", "chrome120"]:
        print(f"\n--- {imp} ---")
        async with AsyncSession(impersonate=imp) as sess:
            resp = await sess.get(url, headers=headers)
            print(f"  Status: {resp.status_code}, URL: {resp.url}")
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success") and data.get("data"):
                    print(f"  SUCCESS!")
                    print(f"  URL: {data['data']['url'][:80]}...")
                    print(f"  DRM: {data['data'].get('drmType','?')}")
                    k = data["data"].get("keys")
                    print(f"  Keys: {json.dumps(k, indent=2)[:200]}" if k else "  Keys: none")
                else:
                    print(f"  API: {json.dumps(data, indent=2)[:400]}")
                break
            else:
                print(f"  Body: {resp.text[:200]}")

asyncio.run(test())
