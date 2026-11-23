import json
import urllib.request

BASE = "https://agentdock.link"
req = urllib.request.Request(BASE + "/api/v1/auth/token",
    data=json.dumps({"email": "mayintake351@gmail.com", "password": "Stevohh@2024"}).encode(),
    headers={"Content-Type": "application/json"}, method="POST")
token = json.load(urllib.request.urlopen(req, timeout=20))["access_token"]
headers = {"Authorization": "Bearer " + token}
items = []
for offset in range(0, 200, 50):
    data = json.load(urllib.request.urlopen(urllib.request.Request(
        BASE + f"/api/v1/skills/search?limit=50&offset={offset}", headers=headers), timeout=30))
    items.extend(data["items"])
    if len(items) >= data["total"]:
        break
for item in items:
    try:
        pkg = json.load(urllib.request.urlopen(urllib.request.Request(
            BASE + f"/api/v1/skills/{item['slug']}/package", headers=headers), timeout=30))
        scripts = pkg["groups"]["scripts"]
        js = [s for s in scripts if s.endswith((".js", ".mjs", ".cjs"))]
        sh = [s for s in scripts if s.endswith((".sh", ".bash"))]
        if js or sh:
            print(item["slug"], "JS:", js[:3], "SH:", sh[:3], "deps:", pkg["statistics_bundle_coverage"]["executable"])
    except Exception:
        pass
