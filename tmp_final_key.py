import http.cookiejar
import json
import urllib.request
from pathlib import Path

BASE = "https://agentdock.link"
EMAIL = "mayintake351@gmail.com"
PASSWORD = "Stevohh@2024"
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
opener.open(urllib.request.Request(BASE + "/api/v1/auth/login",
    data=json.dumps({"email": EMAIL, "password": PASSWORD}).encode(),
    headers={"Content-Type": "application/json"}, method="POST"), timeout=20)
key = json.load(opener.open(urllib.request.Request(BASE + "/api/v1/auth/api-keys",
    data=json.dumps({"name": "Final QA Key", "scopes": ["skills:read", "execution:run", "account:read"]}).encode(),
    headers={"Content-Type": "application/json"}, method="POST"), timeout=20))["api_key"]
Path("tmp_final_key.txt").write_text(key, encoding="utf-8")
quota = json.load(opener.open(BASE + "/api/v1/account/entitlements", timeout=20))["execution_quota"]
print("key:", key[:12] + "...")
print("quota:", quota)
