import http.cookiejar
import json
import time
import urllib.request

BASE = "https://agentdock.link"
EMAIL = "mayintake351@gmail.com"
PASSWORD = "Stevohh@2024"
REPOS = [
    "4e781364-5d4e-436d-a122-8fb2fd0d6c16",  # earthtojake/text-to-cad
    "480479e0-0d5d-483c-98fb-c522db69c794",  # stevohcoder/igura-marketplace
]

jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
login = urllib.request.Request(BASE + "/api/v1/auth/login",
    data=json.dumps({"email": EMAIL, "password": PASSWORD}).encode(),
    headers={"Content-Type": "application/json"}, method="POST")
opener.open(login, timeout=20)
for repo_id in REPOS:
    req = urllib.request.Request(BASE + f"/api/v1/admin/repositories/{repo_id}/sync",
        data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
    with opener.open(req, timeout=30) as response:
        print("sync", repo_id, response.status, json.load(response))

for index in range(30):
    analytics = json.load(opener.open(BASE + "/api/v1/admin/analytics", timeout=30))
    statuses = analytics["catalogue"]["by_status"]
    print("poll", index, statuses)
    if statuses.get("pending_review", 0) <= 3 and statuses.get("qualified", 0) <= 24:
        break
    time.sleep(3)
