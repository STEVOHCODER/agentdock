import json
import urllib.parse
import urllib.request

BASE = "https://agentdock.link"
req = urllib.request.Request(BASE + "/api/v1/auth/token",
    data=json.dumps({"email": "mayintake351@gmail.com", "password": "Stevohh@2024"}).encode(),
    headers={"Content-Type": "application/json"}, method="POST")
token = json.load(urllib.request.urlopen(req, timeout=20))["access_token"]
headers = {"Authorization": "Bearer " + token}
for slug, path in [
    ("vercel-labs-agent-skills-skills-vercel-optimize", "scripts/budget-summary.mjs"),
    ("leonxlnx-taste-skill-skills-taste-skill", "scripts/copy-lint.mjs"),
    ("stevohcoder-igura-marketplace-agents-skills-idea-refine", "scripts/idea-refine.sh"),
]:
    url = BASE + f"/api/v1/skills/{slug}/resources/" + urllib.parse.quote(path)
    text = urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30).read().decode("utf-8", "replace")
    print("=====", slug, path, "len", len(text))
    print("\n".join(text.splitlines()[:25]))
