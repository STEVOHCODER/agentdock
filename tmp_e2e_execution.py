import base64
import http.cookiejar
import json
import time
import urllib.request

BASE = "https://agentdock.link"
EMAIL = "mayintake351@gmail.com"
PASSWORD = "Stevohh@2024"
SKILL = "nextlevelbuilder-ui-ux-pro-max-skill-claude-skills-ui-ux-pro-max"


def main():
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    login = urllib.request.Request(
        BASE + "/api/v1/auth/login",
        data=json.dumps({"email": EMAIL, "password": PASSWORD}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with opener.open(login, timeout=20):
        pass
    created = urllib.request.Request(
        BASE + "/api/v1/auth/api-keys",
        data=json.dumps({"name": "E2E Execution Bridge", "scopes": ["skills:read", "execution:run"]}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with opener.open(created, timeout=20) as response:
        key = json.load(response)["api_key"]
    headers = {"Authorization": "Bearer " + key, "Accept": "application/json, text/event-stream",
               "Content-Type": "application/json"}

    def mcp(name, args, rid):
        body = {"jsonrpc": "2.0", "id": rid, "method": "tools/call",
                "params": {"name": name, "arguments": args}}
        req = urllib.request.Request(BASE + "/mcp", data=json.dumps(body).encode(), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=60) as response:
            return json.load(response)

    package = mcp("resolve_skill_package", {"id": SKILL}, 1)["result"]["structuredContent"]
    print("PACKAGE version:", package["version"], "hash:", package["version_hash"][:12])
    print("COVERAGE:", package["statistics_bundle_coverage"])
    print("WORKSPACE:", package["workspace_path"])

    files = mcp("list_skill_files", {"id": SKILL}, 2)["result"]["structuredContent"]
    print("FILES:", len(files["files"]), "scripts:", len(files["groups"]["scripts"]), "datasets:", len(files["groups"]["data"]))

    script = "skills/ui-ux-pro-max/scripts/search.py"
    file_response = mcp("retrieve_skill_file", {"id": SKILL, "path": script}, 3)
    if "error" in file_response:
        print("FILE ERROR:", file_response["error"])
        return
    one = file_response["result"]["structuredContent"]
    print("RETRIEVED FILE:", one["path"], "sha256:", one["sha256"][:12], "bytes:", len(base64.b64decode(one["content"])))

    job = mcp("execute_skill_script", {
        "id": SKILL,
        "script": script,
        "arguments": ["SaaS technology landing page", "--design-system"],
    }, 4)["result"]["structuredContent"]
    print("JOB:", job["id"], job["status"], job["sandbox"])
    job_id = job["id"]

    for index in range(60):
        result = mcp("get_execution_status", {"job_id": job_id}, 10 + index)["result"]["structuredContent"]
        if result["status"] in {"succeeded", "failed", "canceled"}:
            break
        time.sleep(1)
    print("FINAL STATUS:", result["status"], "exit:", result["exit_code"])
    print("STDERR:", result["stderr"][:500])
    print("STDOUT LENGTH:", len(result["stdout"]))
    print("STDOUT HEAD:\n", result["stdout"][:1200])
    print("STDOUT TAIL:\n", result["stdout"][-600:])


if __name__ == "__main__":
    main()
