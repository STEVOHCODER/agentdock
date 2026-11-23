import http.cookiejar
import json
import time
import urllib.request
from pathlib import Path

BASE = "https://agentdock.link"
KEY = Path("tmp_key2.txt").read_text(encoding="utf-8").strip()
HEADERS = {"Authorization": "Bearer " + KEY, "Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
EMAIL = "mayintake351@gmail.com"
PASSWORD = "Stevohh@2024"

UIUX = "nextlevelbuilder-ui-ux-pro-max-skill-claude-skills-ui-ux-pro-max"
BRAIN = "obra-superpowers-skills-brainstorming"
IDEA = "stevohcoder-igura-marketplace-agents-skills-idea-refine"


def mcp(method, params=None, rid=1):
    body = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None:
        body["params"] = params
    req = urllib.request.Request(BASE + "/mcp", data=json.dumps(body).encode(), headers=HEADERS, method="POST")
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.load(response)


def call_tool(name, args, rid):
    response = mcp("tools/call", {"name": name, "arguments": args}, rid)
    if "error" in response:
        return {"error": response["error"]}
    return response["result"]["structuredContent"]


def wait_job(job_id, base_rid):
    for index in range(60):
        job = call_tool("get_execution_status", {"job_id": job_id}, base_rid + index)
        if job.get("status") in {"succeeded", "failed", "canceled"}:
            return call_tool("retrieve_execution_result", {"job_id": job_id}, base_rid + 100)
        time.sleep(1)
    return {"status": "timeout"}


def main():
    tools = mcp("tools/list", None, 1)["result"]["tools"]
    exec_tool = next(item for item in tools if item["name"] == "execute_skill_script")
    props = exec_tool["inputSchema"]["properties"]
    print("MCP exec properties:", sorted(props.keys()))

    # Team for team-aware execution
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.open(urllib.request.Request(BASE + "/api/v1/auth/login",
        data=json.dumps({"email": EMAIL, "password": PASSWORD}).encode(),
        headers={"Content-Type": "application/json"}, method="POST"), timeout=20)
    team = json.load(opener.open(urllib.request.Request(BASE + "/api/v1/teams",
        data=json.dumps({"name": "Execution QA Team"}).encode(),
        headers={"Content-Type": "application/json"}, method="POST"), timeout=20))
    team_id = team["id"]
    print("team:", team_id)

    # Python with custom limits
    py = call_tool("execute_skill_script", {
        "id": UIUX, "script": "scripts/search.py", "command": "python3",
        "arguments": ["SaaS technology landing page", "--design-system"],
        "timeout_seconds": 30, "max_memory_mb": 512, "max_cpu_millicores": 500,
        "network": False,
    }, 10)
    py_result = wait_job(py["id"], 20)
    print("PYTHON:", py_result["status"], "exit", py_result["exit_code"],
          "runtime", py["command"], "limits", py["limits"],
          "deps", py["dependencies"].get("detected"),
          "metrics", py_result["metrics"]["duration_ms"], py_result["metrics"]["peak_memory_bytes"])

    # Node runtime
    node = call_tool("execute_skill_script", {
        "id": BRAIN, "script": "scripts/helper.js", "command": "node", "arguments": [],
    }, 200)
    node_result = wait_job(node["id"], 210)
    print("NODE:", node_result["status"], "exit", node_result["exit_code"], "runtime", node["command"])

    # Bash runtime + team scope
    sh = call_tool("execute_skill_script", {
        "id": IDEA, "script": "scripts/idea-refine.sh", "command": "bash",
        "arguments": [], "team_id": team_id,
    }, 400)
    sh_result = wait_job(sh["id"], 410)
    print("BASH:", sh_result["status"], "exit", sh_result["exit_code"],
          "runtime", sh["command"], "team", sh["team_id"])

    history = json.load(opener.open(BASE + "/api/v1/executions?limit=10&status=succeeded", timeout=30))
    print("HISTORY:", history["total"], "records; first metrics:", history["items"][0]["metrics"])

    quota = json.load(opener.open(BASE + "/api/v1/account/entitlements", timeout=30))["execution_quota"]
    print("QUOTA:", quota)

    with open("tmp_priority_validation.json", "w", encoding="utf-8") as handle:
        json.dump({"python": py_result, "node": node_result, "bash": sh_result,
                   "history_total": history["total"], "quota": quota, "team_id": team_id},
                  handle, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
