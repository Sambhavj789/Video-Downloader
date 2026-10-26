import requests, json, base64

license_url = 'https://api.penpencil.co/v1/videos/drm-license-manager'

def b64pad(s):
    return s + '=' * (4 - len(s) % 4)

lt = 'eyJkcm1fdHlwZSI6IldpZGV2aW5lIiwic2l0ZV9pZCI6IkZUVEsiLCJ1c2VyX2lkIjoiNjRjMGNhNzFmNDYxZTAwMTgwODE4MTgxMiIsImNpZCI6IjE0YTViODBmNmIyMDViODg0ZjMwZDRlNmY5NWE0MWY3IiwicG9saWN5IjoiNTEzRTQ1NnUvRU4vZ0pEekVBOWt4V0JOL3FLeHM5WlRIMHZjRHRielN6dVh5WmNLdGFVVXhsNXpZanlUK05uQU11S2FwaXZDaUE0bldRVjJGWmEzYU53c1RTcTVUWkJteVM0ZzgySUxoMDRrQURkWTNISWIvVEtoaHZld3NkekFlZXhnNmprU1FJOWpldEt2ZFV2VUlOVlZaUWpxTDBzOXZmNnpqTm1GSktqdW4vdnplK1FCbXBhNWc2UVg5ZCtvY0ltNkhaY1FoTDh3WUl3dHBJZDNYdndkSkVPb1pVbTd0TjJ2UlZUSEdJMHlSaHJQQ0RoeGMxWm1GbkY1SnRqL3Z2OEZtL3YwUjdVaW9pUHRuOHN5a1VQdFJoZDhsS3NDYkRzeUlCR1dXY2ZoNXRqTnRwTVJyeFJLNmhVaFhqQVMyNUxHWDhrZVQxQ2VBUmJScUhFN0VlVTNobVJlU2phNUJRbEt0SkhoVU55Q0U1VnJLcnhuSnp2VnBrZFBzWGFQRG5jYWM1ZTBCWHcwclJTS2dkNzE5R0pzRFlmSlFSdUxUQkd5RGJ4WjVqMTNyRVNuQnllRnM0TWxHdnkwV3pSTXdVZm9CdW1aY0lnN3V6Y1p5MmRwQU9UWHlid21qWkx2SGU0Q0NSeTZIa01aLzdUb3NLeXFQWnNJeDBDQnNMdyIsInRpbWVzdGFtcCI6IjIwMjYtMDYtMjBUMTc6Mjc6NTEuMzM3WiIsImhhc2giOiJvcEt3MXN0UnBnSENHRFpJbkhzajUvYVI4cVBhTTVjRm5SMjFON2habjdRPSIsInJlc3BvbnNlX2Zvcm1hdCI6Im9yaWdpbmFsIiwia2V5X3JvdGF0aW9uIjpmYWxzZX0'
pssh = 'AAAAZnBzc2gAAAAA7e+LqXnWSs6jyCfc1R0h7QAAAEYIARIQMxU8Km/ZRgCcJqah+jK+thoMRG92ZXJ1bm5lciIQMTE0YTViODBmNmIyMDViODg0ZjMwZDRlNmY5NWE0MWY3'
pssh_bytes = base64.b64decode(pssh)

jwt_token = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VyIjp7Il9pZCI6IjY0YWMwY2E3MWY0NjFlMDAxODA4MTgxMiIsImVtYWlsIjoic2hyaW5hdmFzaGlyLmNAcHdsaXZlLmNvbSIsIm1vYmlsZSI6Iis5MTk5OTk5OTk5OTkifSwiaWF0IjoxNzUwNDI2MDcwLCJleHAiOjE3NTA0Mjk2NzB9.XjH14BmJCP3E0I-Bok3l2MLvl7aNj7avwWMiwm34TKI'

headers = {
    'Authorization': f'Bearer {jwt_token}',
    'User-Agent': 'Mozilla/5.0',
    'Content-Type': 'application/json',
}

test_bodies = [
    {'pssh': pssh, 'token': lt},
    {'initData': pssh, 'token': lt},
    {'initDataBase64': pssh, 'token': lt},
    {'challenge': pssh, 'token': lt},
    {'contentId': '14a5b80f6b205b884f30d4e6f95a41f7', 'token': lt},
    {'drmType': 'Widevine', 'pssh': pssh, 'token': lt},
    {'pssh': pssh, 'licenseToken': lt},
    {'pssh': pssh, 'token': lt, 'userId': '64ac0ca71f461e0018081812'},
    {'widevineChallenge': pssh, 'token': lt},
    {'rawPssh': pssh, 'token': lt},
]

print('=== Testing license server ===')
for i, body in enumerate(test_bodies):
    try:
        r = requests.post(license_url, json=body, headers=headers, timeout=15)
        try:
            resp = r.json()
            if resp.get('success'):
                print(f'\n{i+1}. SUCCESS! Fields: {list(body.keys())}')
                print(f'   Response: {json.dumps(resp, indent=2)[:300]}')
            else:
                msg = resp.get('message', '')
                print(f'{i+1}. Fields {list(body.keys())[:3]}: {resp.get("errorCode", "?")} - {str(msg)[:60]}')
        except:
            print(f'{i+1}. Fields {list(body.keys())[:3]}: HTTP {r.status}, {r.content[:150]}')
    except Exception as e:
        print(f'{i+1}. Error: {e}')

print('\n=== Without Content-Type (JSON auto-detect) ===')
try:
    h = {'Authorization': f'Bearer {jwt_token}', 'User-Agent': 'Mozilla/5.0'}
    r = requests.post(license_url, json={'pssh': pssh, 'token': lt}, headers=h, timeout=15)
    print(f'JSON auto-detect: HTTP {r.status}, {r.content[:200]}')
except Exception as e:
    print(f'Error: {e}')

print('\n=== Query params (GET) ===')
for params in [{'pssh': pssh, 'token': lt}, {'token': lt}, {'pssh': pssh}]:
    try:
        h = {'Authorization': f'Bearer {jwt_token}', 'User-Agent': 'Mozilla/5.0'}
        r = requests.get(license_url, params=params, headers=h, timeout=15)
        print(f'GET {list(params.keys())}: HTTP {r.status}, {len(r.content)} bytes, {str(r.content[:150])}')
    except Exception as e:
        print(f'Error: {e}')

print('\n=== Raw PSSH bytes ===')
for ct in ['application/octet-stream', 'application/x-protobuf', 'application/x-widevine']:
    try:
        h = {'Authorization': f'Bearer {jwt_token}', 'User-Agent': 'Mozilla/5.0', 'Content-Type': ct}
        r = requests.post(license_url, data=pssh_bytes, headers=h, timeout=15)
        print(f'POST binary ({ct}): HTTP {r.status}, {len(r.content)} bytes, {str(r.content[:150])}')
    except Exception as e:
        print(f'Error: {e}')

print('\n=== JWT payload as request body ===')
lt_parts = lt.split('.')
if len(lt_parts) >= 2:
    padded = lt_parts[1] + '=' * (4 - len(lt_parts[1]) % 4)
    lt_json = json.loads(base64.urlsafe_b64decode(padded))
    for fmt in ['json', 'text']:
        try:
            ct = 'application/json' if fmt == 'json' else 'text/plain'
            body = json.dumps(lt_json) if fmt == 'json' else str(lt_json)
            h = {'Authorization': f'Bearer {jwt_token}', 'User-Agent': 'Mozilla/5.0', 'Content-Type': ct}
            r = requests.post(license_url, data=body, headers=h, timeout=15)
            print(f'JWT payload ({fmt}): HTTP {r.status}, {len(r.content)} bytes, {str(r.content[:200])}')
        except Exception as e:
            print(f'Error: {e}')

# Try with the policy field sent separately
print('\n=== Policy field only ===')
if len(lt_parts) >= 2:
    padded = lt_parts[1] + '=' * (4 - len(lt_parts[1]) % 4)
    lt_json = json.loads(base64.urlsafe_b64decode(padded))
    data = {'policy': lt_json.get('policy', '')}
    try:
        r = requests.post(license_url, json=data, headers=headers, timeout=15)
        print(f'Policy only: HTTP {r.status}, {r.content[:200]}')
    except Exception as e:
        print(f'Error: {e}')

# Try multipart form data
print('\n=== Multipart form ===')
try:
    h = {'Authorization': f'Bearer {jwt_token}', 'User-Agent': 'Mozilla/5.0'}
    r = requests.post(license_url, files={'pssh': ('pssh.bin', pssh_bytes, 'application/octet-stream'), 'token': (None, lt)}, headers=h, timeout=15)
    print(f'Multipart: HTTP {r.status}, {r.content[:200]}')
except Exception as e:
    print(f'Error: {e}')
