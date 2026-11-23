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
    with opener.open(login, timeout=20) as response:
        print("admin login:", response.status)

    analytics = json.load(opener.open(BASE + "/api/v1/admin/analytics", timeout=30))
    print("catalogue by_status:", analytics["catalogue"]["by_status"])
    print("approved:", analytics["catalogue"]["approved"], "pending:", analytics["catalogue"]["pending"],
          "quarantined:", analytics["catalogue"]["quarantined"])

    skills = []
    for offset in range(0, 200, 50):
        data = json.load(opener.open(BASE + f"/api/v1/skills/search?limit=50&offset={offset}", timeout=30))
        skills.extend(data["items"])
        if len(skills) >= data["total"]:
            break
    statuses = {}
    security = {}
    for skill in skills:
        statuses[skill.get("status")] = statuses.get(skill.get("status"), 0) + 1
        security[skill.get("security_status")] = security.get(skill.get("security_status"), 0) + 1
    print("public listing statuses:", statuses)
    print("public listing security:", security)
    print("skills:", len(skills))


if __name__ == "__main__":
    main()
