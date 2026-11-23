import http.cookiejar
import json
import urllib.request

BASE = "https://agentdock.link"
EMAIL = "mayintake351@gmail.com"
PASSWORD = "Stevohh@2024"

jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
login = urllib.request.Request(BASE + "/api/v1/auth/login",
    data=json.dumps({"email": EMAIL, "password": PASSWORD}).encode(),
    headers={"Content-Type": "application/json"}, method="POST")
opener.open(login, timeout=20)
repos = json.load(opener.open(BASE + "/api/v1/admin/repositories", timeout=30))["items"]
for repo in repos:
    owner = (repo.get("owner") or "").lower()
    if owner in {"stevohcoder", "earthtojake", "muratcankoylan", "garrytan"}:
        print(repo["id"], owner, repo["name"], "status:", repo["status"])
