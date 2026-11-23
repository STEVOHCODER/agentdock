import json
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://agentdock.link"
KEY = Path("tmp_final_key.txt").read_text(encoding="utf-8").strip()
H = {"Authorization": "Bearer " + KEY, "Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
SKILL = "qa-agentdock-execution-probes"

result = {"key_prefix": KEY[:12] + "...", "tests": {}}


def mcp(name, args, rid):
    body = {"jsonrpc": "2.0", "id": rid, "method": "tools/call", "params": {"name": name, "arguments": args}}
    with urllib.request.urlopen(urllib.request.Request(BASE + "/mcp", data=json.dumps(body).encode(), headers=H, method="POST"), timeout=45) as response:
        payload = json.load(response)
    if "error" in payload:
        return {"error": payload["error"]}
    return payload["result"]["structuredContent"]


def wait(job_id, base):
    for index in range(90):
        job = mcp("get_execution_status", {"job_id": job_id}, base + index)
        if job.get("status") in {"succeeded", "failed", "canceled"}:
            return mcp("retrieve_execution_result", {"job_id": job_id}, base + 200)
        time.sleep(0.5)
    return {"status": "timeout"}


def run(name, script, args, rid, **extra):
    payload = {"id": SKILL, "script": script, "command": "python3", "arguments": args}
    payload.update(extra)
    job = mcp("execute_skill_script", payload, rid)
    if isinstance(job.get("error"), dict):
        return {"error": job["error"]}
    out = wait(job["id"], rid + 20)
    return {"job_id": job["id"], "status": out.get("status"), "exit_code": out.get("exit_code"),
            "stdout": out.get("stdout", ""), "stderr": out.get("stderr", ""),
            "error": out.get("error", ""), "metrics": out.get("metrics"), "limits": job.get("limits")}


def main():
    pkg = mcp("resolve_skill_package", {"id": SKILL}, 1)
    result["package"] = {"version": pkg.get("version"), "files": len(pkg.get("manifest", [])),
                         "coverage": pkg.get("statistics_bundle_coverage")}
    deps = mcp("list_skill_files", {"id": SKILL}, 2)
    result["package"]["has_lock"] = "requirements.lock.txt" in [item["path"] for item in deps.get("files", [])]

    dep = run("dependency", "scripts/deps_probe.py", [], 10)
    result["tests"]["dependency_install"] = dep

    secrets = run("secrets", "scripts/probe_secrets.py", [], 100)
    result["tests"]["secret_isolation"] = secrets

    net_off = run("network_off", "scripts/probe_network.py", [], 200, network=False)
    result["tests"]["network_off"] = net_off
    net_on = run("network_on", "scripts/probe_network.py", [], 300, network=True)
    result["tests"]["network_on"] = net_on

    timeout = run("timeout", "scripts/sleep.py", ["30"], 400, timeout_seconds=3)
    result["tests"]["timeout"] = timeout

    sleep_job = mcp("execute_skill_script", {"id": SKILL, "script": "scripts/sleep.py",
        "command": "python3", "arguments": ["30"], "timeout_seconds": 60}, 500)
    time.sleep(2)
    cancel = mcp("cancel_execution", {"job_id": sleep_job["id"]}, 510)
    canceled_result = wait(sleep_job["id"], 520)
    result["tests"]["running_cancellation"] = {"job_id": sleep_job["id"],
                                               "cancel_status": cancel.get("status"),
                                               "final_status": canceled_result.get("status"),
                                               "error": canceled_result.get("error")}

    Path("tmp_final_validation.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    for name, value in result["tests"].items():
        if name == "running_cancellation":
            print(name, value)
        else:
            print(name, value.get("status"), value.get("exit_code"), value.get("stdout", "")[:160].replace("\n", " | "))


if __name__ == "__main__":
    main()
