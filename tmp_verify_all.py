import concurrent.futures
import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://agentdock.link"
EMAIL = "mayintake351@gmail.com"
PASSWORD = "Stevohh@2024"


def call(method, path, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(BASE + path, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=40) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()[:200]


def main():
    skills = []
    request = urllib.request.Request(BASE + "/api/v1/auth/token",
        data=json.dumps({"email": EMAIL, "password": PASSWORD}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    token = json.load(urllib.request.urlopen(request, timeout=20))["access_token"]

    skills = []
    for offset in range(0, 200, 50):
        status, data = call("GET", f"/api/v1/skills/search?limit=50&offset={offset}", token)
        if status != 200:
            print("list failed", status, data)
            return
        skills.extend(data["items"])
        if len(skills) >= data["total"]:
            break

    def verify(skill):
        slug = skill["slug"]
        status, package = call("GET", f"/api/v1/skills/{urllib.parse.quote(slug)}/package", token)
        if status != 200:
            return {"slug": slug, "error": f"package {status}: {package}"}
        manifest = package["manifest"]
        groups = package["groups"]
        mismatches = []
        for entry in manifest:
            path_url = urllib.parse.quote(entry["path"])
            req = urllib.request.Request(
                BASE + f"/api/v1/skills/{urllib.parse.quote(slug)}/resources/{path_url}",
                headers={"Authorization": "Bearer " + token})
            try:
                content = urllib.request.urlopen(req, timeout=40).read()
                if hashlib.sha256(content).hexdigest() != entry["sha256"]:
                    mismatches.append(entry["path"])
            except Exception as exc:
                mismatches.append(f"{entry['path']}: {exc}")
        return {"slug": slug, "files": len(manifest), "scripts": len(groups["scripts"]),
                "datasets": len(groups["data"]), "complete": package["statistics_bundle_coverage"]["complete"],
                "mismatches": mismatches}

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
        for result in executor.map(verify, skills):
            results.append(result)

    ok = [r for r in results if not r.get("error") and not r.get("mismatches")]
    with_scripts = [r for r in ok if r["scripts"] > 0]
    docs_only = [r for r in ok if r["scripts"] == 0]
    total_files = sum(r.get("files", 0) for r in ok)
    total_scripts = sum(r.get("scripts", 0) for r in ok)
    print("skills:", len(skills))
    print("packages OK:", len(ok))
    print("packages with errors:", len(results) - len(ok))
    print("total files verified:", total_files)
    print("total Python scripts:", total_scripts)
    print("skills with scripts:", len(with_scripts))
    print("docs-only skills:", len(docs_only))
    print("hash mismatches:", sum(len(r.get("mismatches", [])) for r in results))
    print("sample executable skills:")
    for r in with_scripts[:10]:
        print("  ", r["slug"], r["scripts"], "scripts", r["datasets"], "datasets")
    with open("tmp_all_packages.json", "w", encoding="utf-8") as handle:
        json.dump(results, handle, indent=2)


if __name__ == "__main__":
    main()
