import urllib.request
import json
import os
import sys

# The key provided by the user (default)
DEFAULT_KEY = "0a1NU1Exp9EGpMso1bt8xc7rfmLuOfW9"
TEBEX_API_KEY = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_KEY
TEBEX_BASE_URL = "https://plugin.tebex.io"

def tebex_request(method, endpoint, data=None):
    url = f"{TEBEX_BASE_URL}{endpoint}"
    headers = {
        "X-Tebex-Secret": TEBEX_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "TebexMigrateBot/1.0"
    }
    
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
            err_body = e.read().decode("utf-8")
            print(f"Error Body: {err_body}")
        except:
            pass
        return e.code, None
    except Exception as e:
        print(f"Error: {e}")
        return 0, None

print("--- Tebex API Debugger ---")

# 1. Check Store Information (Basic Auth)
print("\n[1] Checking Store Information (GET /information)...")
status, data = tebex_request("GET", "/information")
if status == 200:
    print("SUCCESS: API Key is valid.")
    print(f"Store Name: {data.get('account', {}).get('name')}")
    print(f"Domain: {data.get('account', {}).get('domain')}")
    print(f"Currency: {data.get('account', {}).get('currency', {}).get('iso_4217')}")
else:
    print("FAILURE: Could not fetch store info. Key might be invalid or IP restricted.")

# 2. Check Gift Cards Permission (GET /gift-cards)
print("\n[2] Checking Gift Cards Access (GET /gift-cards)...")
status, data = tebex_request("GET", "/gift-cards")
if status == 200:
    print("SUCCESS: Can list gift cards.")
elif status == 403:
    print("FAILURE: 403 Forbidden. Key lacks permission for /gift-cards.")
else:
    print(f"FAILURE: Status {status}")

# 3. Attempt Gift Card Creation (POST /gift-cards)
# We will try to create a 0.01 card as a test if listing worked, or just report the previous failure.
if status == 200:
    print("\n[3] Attempting to create a test gift card (POST /gift-cards)...")
    payload = {
        "amount": 0.01,
        "note": "Debug Test Card"
    }
    status, data = tebex_request("POST", "/gift-cards", payload)
    if status == 200 or status == 201:
        print("SUCCESS: Gift card created.")
        print(f"Code: {data.get('data', {}).get('code')}")
    else:
        print(f"FAILURE: Could not create gift card. Status {status}")
else:
    print("\n[3] Skipping creation test due to previous failure.")

print("\n--- End Debug ---")
