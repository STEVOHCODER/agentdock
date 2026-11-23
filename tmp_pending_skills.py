import http.cookiejar
import json
import urllib.request

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
    for status in ["pending_review", "qualified", "quarantined"]:
        data = json.load(opener.open(BASE + f"/api/v1/admin/skills?status={status}", timeout=30))
        items = data.get("items", [])
        print("STATUS", status, "count", len(items))
        for item in items[:12]:
            print("  ", item.get("slug"), "| license:", item.get("license_id"), "| security:", item.get("security_status"), "| score:", item.get("score"))
        if len(items) > 12:
            print("   ...", len(items) - 12, "more")


if __name__ == "__main__":
    main()
