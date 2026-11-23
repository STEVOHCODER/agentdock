import http.cookiejar
import json
import urllib.request
from collections import Counter

BASE = "https://agentdock.link"
EMAIL = "mayintake351@gmail.com"
PASSWORD = "Stevohh@2024"


def main():
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    login = urllib.request.Request(BASE + "/api/v1/auth/login",
        data=json.dumps({"email": EMAIL, "password": PASSWORD}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    opener.open(login, timeout=20)
    owners = Counter()
    for status in ["pending_review", "qualified", "quarantined"]:
        data = json.load(opener.open(BASE + f"/api/v1/admin/skills?status={status}", timeout=30))
        for item in data.get("items", []):
            slug = item.get("slug", "")
            owner = slug.split("-")[0] if slug else "unknown"
            owners[(status, owner)] += 1
    for (status, owner), count in sorted(owners.items()):
        print(status, owner, count)


if __name__ == "__main__":
    main()
