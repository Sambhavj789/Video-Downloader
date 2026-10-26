"""
Check Chrome cookies for stream.testuk.org
Chrome must be closed, then run this script.
"""
import browser_cookie3, json, sys

# Need to run as admin for shadowcopy
cookies = list(browser_cookie3.chrome(domain_name="stream.testuk.org"))
if not cookies:
    cookies = list(browser_cookie3.chrome(domain_name="testuk.org"))

cookie_data = {}
has_session = False
for c in cookies:
    cookie_data[c.name] = c.value
    if c.name == "session":
        has_session = True
        print(f"✓ session: {c.value[:60]}...")
    else:
        print(f"  {c.name}: {c.value[:60]}...")

if has_session:
    json.dump(cookie_data, open("stream_cookies.json", "w"), indent=2)
    print(f"\nSession cookie found! Saved to stream_cookies.json")
    sys.exit(0)
elif cookie_data:
    json.dump(cookie_data, open("stream_cookies.json", "w"), indent=2)
    print(f"\n{len(cookie_data)} cookies saved but NO session cookie found")
    sys.exit(1)
else:
    print("No cookies found for testuk.org/stream.testuk.org")
    sys.exit(1)
