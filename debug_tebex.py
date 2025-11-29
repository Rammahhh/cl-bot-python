import sys
import base64
import urllib.request
import json

# Credentials provided by user
PROJECT_ID = "1661236"
PRIVATE_KEY = "0a1NU1Exp9EGpMso1bt8xc7rfmLuOfW9"
PUBLIC_TOKEN = "zltg-8c50a30c5d0a7e6f72ff87d7fec5c26adc261043"

def debug_request(url, headers, method="GET", data=None):
    print(f"Requesting: {method} {url}")
    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, headers=headers, data=body, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            response_data = resp.read()
            return resp.status, json.loads(response_data.decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"HTTP Error: {e.code} {e.reason}")
        try:
            print(f"Error Body: {e.read().decode('utf-8')}")
        except:
            pass
        return e.code, None
    except Exception as e:
        print(f"Error: {e}")
        return 0, None

print("--- Tebex Key Debugger ---")

# 1. Test as Game Server Key (Plugin API)
print("\n[1] Testing as Game Server Key (https://plugin.tebex.io)...")
headers_plugin = {
    "X-Tebex-Secret": PRIVATE_KEY,
    "Content-Type": "application/json",
    "User-Agent": "TebexMigrateBot/1.0"
}
status, _ = debug_request("https://plugin.tebex.io/information", headers_plugin)
if status == 200:
    print("SUCCESS: It is a Game Server Key.")
else:
    print("FAILURE: Not a Game Server Key.")

# 2. Test as Headless API Key
print("\n[2] Testing as Headless API Key (https://headless.tebex.io)...")
# Headless requires no auth for public info, but let's try to fetch basket or something that proves the token works.
# Actually, let's just check the store info using the public token.
url_headless = f"https://headless.tebex.io/api/accounts/{PUBLIC_TOKEN}"
status, data = debug_request(url_headless, {"Content-Type": "application/json"})

if status == 200:
    print("SUCCESS: Public Token is valid for Headless API.")
    print(f"Store: {data.get('data', {}).get('name')}")
else:
    print("FAILURE: Public Token invalid.")

print("\n--- Conclusion ---")
print("If [1] failed, you cannot use this key to create Gift Cards via the Plugin API.")
print("You need to go to Tebex Panel > Game Servers > Connect Game Server and generate a SECRET KEY there.")
