import urllib.request
import json
import os

TEBEX_API_KEY = "0a1NU1Exp9EGpMso1bt8xc7rfmLuOfW9"
TEBEX_BASE_URL = "https://plugin.tebex.io"

def tebex_request(method, endpoint, data=None):
    url = f"{TEBEX_BASE_URL}{endpoint}"
    headers = {
        "X-Tebex-Secret": TEBEX_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    
    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, headers=headers, data=body, method=method)
    
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            response_data = resp.read()
            return json.loads(response_data.decode("utf-8"))
    except Exception as e:
        print(f"Error: {e}")
        return None

print("Testing Tebex API Connection....")
# Try to list gift cards to verify auth
response = tebex_request("GET", "/gift-cards")
if response:
    print("Success! Response:")
    print(json.dumps(response, indent=2))
else:
    print("Failed to connect.")
