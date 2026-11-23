import http.cookiejar
import json
import urllib.request
from pathlib import Path

BASE = "https://agentdock.link"
EMAIL = "mayintake351@gmail.com"
PASSWORD = "Stevohh@2024"
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
login = urllib.request.Request(BASE + "/api/v1/auth/login",
    data=json.dumps({"email": EMAIL, "password": PASSWORD}).encode(),
    headers={"Content-Type": "application/json"}, method="POST")
opener.open(login, timeout=20)
key_req = urllib.request.Request(BASE + "/api/v1/auth/api-keys",
    data=json.dumps({"name": "Priority Validation", "scopes": ["skills:read", "execution:run", "account:read"]}).encode(),
    headers={"Content-Type": "application/json"}, method="POST")
key = json.load(opener.open(key_req, timeout=20))["api_key"]
Path("tmp_key2.txt").write_text(key, encoding="utf-8")
print("key:", key[:12] + "...")
