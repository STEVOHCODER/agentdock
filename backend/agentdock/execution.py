"""Complete skill package resolution and isolated execution.

Execution never happens in the web process. The worker claims an
``ExecutionJob`` from the database, materializes an immutable SkillVault
snapshot into a temporary workspace, verifies every file hash and runs the
approved command inside a bubblewrap sandbox with networking disabled.
"""
import ast
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import tomllib
from pathlib import Path, PurePosixPath
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import ExecutionJob, Skill, SkillVersion, utcnow
from .vault import read_resource, safe_relative_path

PAYTHON = sys.executable

RUNTIME_ALIASES = {
    "python": "python3", "python3": "python3",
    "node": "node", "nodejs": "node",
    "bash": "bash", "sh": "sh",
}
SCRIPT_RUNTIMES = {
    ".py": "python3", ".js": "node", ".mjs": "node", ".cjs": "node",
    ".sh": "bash", ".bash": "bash",
}


class ExecutionError(RuntimeError):
    pass


def _version(db: Session, skill: Skill, version: str | None) -> SkillVersion:
    statement = select(SkillVersion).where(SkillVersion.skill_id == skill.id)
    if version:
        statement = statement.where(SkillVersion.version == version)
    else:
        statement = statement.where(SkillVersion.version == skill.latest_version)
    item = db.scalar(statement.order_by(SkillVersion.created_at.desc()))
    if not item:
        raise ExecutionError("The requested immutable skill version was not found")
    return item


def assert_execution_allowed(skill: Skill) -> None:
    """Execution is limited to approved, security-reviewed, optionally allow-listed skills."""
    if skill.status != "approved" or skill.security_status != "clear":
        raise ExecutionError("Only approved, security-reviewed packages can be executed")
    settings = get_settings()
    allowed = settings.execution_allowed_skill_list
    if allowed and skill.slug.lower() not in allowed and skill.name.lower() not in allowed:
        raise ExecutionError("This skill is not in the execution allow-list")


def resolve_package(db: Session, identifier: str, version: str | None = None, user=None) -> dict:
    from .common import get_skill, premium_entitlement  # local import avoids a module cycle

    skill = get_skill(db, identifier)
    if skill.status != "approved" or skill.security_status != "clear":
        raise ExecutionError("Only approved, security-reviewed packages can be read")
    if user is not None and skill.is_premium and not premium_entitlement(db, user, skill):
        raise ExecutionError("Purchase this skill to retrieve its package")
    item = _version(db, skill, version)
    manifest = sorted(item.manifest or [], key=lambda entry: entry.get("path", ""))
    groups = {"entrypoints": [], "scripts": [], "data": [], "references": [], "assets": [], "other": []}
    for entry in manifest:
        path = entry.get("path", "")
        lower = path.lower()
        if lower == "skill.md" or lower.endswith("/skill.md"):
            groups["entrypoints"].append(path)
        elif lower.startswith("scripts/") or "/scripts/" in lower:
            groups["scripts"].append(path)
        elif lower.startswith("data/") or "/data/" in lower:
            groups["data"].append(path)
        elif lower.startswith("references/") or "/references/" in lower or lower.startswith("docs/") or "/docs/" in lower:
            groups["references"].append(path)
        elif any(lower.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp", ".pdf")):
            groups["assets"].append(path)
        else:
            groups["other"].append(path)
    return {
        "skill": skill,
        "version": item,
        "manifest": manifest,
        "groups": groups,
        "workspace_path": f"skills/{skill.name}",
        "version_pinned": True,
        "statistics_bundle_coverage": {
            "documents": len(groups["entrypoints"]) + len(groups["references"]) + len(groups["other"]),
            "scripts": len(groups["scripts"]),
            "datasets": len(groups["data"]),
            "complete": bool(manifest),
            "missing": [] if manifest else ["package files"],
            "has_scripts": bool(groups["scripts"]),
            "has_data": bool(groups["data"]),
            "executable": bool(groups["scripts"]),
        },
    }


def normalize_package_path(package: dict, path: str) -> str:
    prefix = package["workspace_path"].rstrip("/") + "/"
    if path.startswith(prefix):
        return path[len(prefix):]
    return path


def resolve_runtime(command: str, script: str) -> str:
    settings = get_settings()
    allowed = settings.execution_runtime_set
    runtime = RUNTIME_ALIASES.get((command or "").strip().lower())
    if not runtime or runtime not in allowed:
        raise ExecutionError(f"Runtime is not approved: {command}")
    extension = PurePosixPath(script).suffix.lower()
    expected = SCRIPT_RUNTIMES.get(extension)
    if expected and expected != runtime:
        raise ExecutionError(f"Script type {extension} requires {expected}, not {runtime}")
    return runtime


def detect_dependencies(manifest: list[dict], snapshot_path: str) -> dict:
    """Read lock/manifest files and build a reproducible dependency plan."""
    names = {PurePosixPath(entry.get("path", "")).name: entry["path"] for entry in manifest}
    found = {}
    for name in ["requirements.lock.txt", "requirements.txt", "pyproject.toml", "poetry.lock",
                 "Pipfile.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "package.json"]:
        if name in names:
            found[name] = names[name]

    packages: list[str] = []
    if "requirements.lock.txt" in found or "requirements.txt" in found:
        path = found.get("requirements.lock.txt") or found["requirements.txt"]
        for line in read_resource(snapshot_path, path).decode("utf-8", "replace").splitlines():
            line = line.strip()
            if line and not line.startswith(("#", "-")):
                packages.append(line)
    if "pyproject.toml" in found:
        try:
            data = tomllib.loads(read_resource(snapshot_path, found["pyproject.toml"]).decode("utf-8", "replace"))
            packages.extend(data.get("project", {}).get("dependencies", []) or [])
        except Exception:
            pass
    if "package.json" in found:
        try:
            data = json.loads(read_resource(snapshot_path, found["package.json"]).decode("utf-8", "replace"))
            for section in ("dependencies", "devDependencies"):
                packages.extend(f"{name}@{version}" for name, version in (data.get(section) or {}).items())
        except Exception:
            pass

    has_python = any(name.endswith((".txt", ".toml", ".lock")) for name in found)
    has_node = any(name in {"package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml"} for name in found)
    lock_names = {"requirements.lock.txt", "poetry.lock", "Pipfile.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml"}
    locked = bool(lock_names & set(found)) or not packages
    install_commands = []
    if has_python:
        req = found.get("requirements.lock.txt") or found.get("requirements.txt")
        if req:
            install_commands.append(f"pip install --no-cache-dir --target /workspace/.deps -r /workspace/{req}")
        elif "pyproject.toml" in found:
            install_commands.append("pip install --no-cache-dir --target /workspace/.deps /workspace")
    if has_node:
        if "package-lock.json" in found:
            install_commands.append("npm ci --ignore-scripts --no-audit --no-fund")
        elif "yarn.lock" in found:
            install_commands.append("yarn install --frozen-lockfile --ignore-scripts")
        elif "pnpm-lock.yaml" in found:
            install_commands.append("pnpm install --frozen-lockfile --ignore-scripts")
        else:
            install_commands.append("npm install --ignore-scripts --no-audit --no-fund")
    return {
        "detected": bool(packages or install_commands),
        "locked": locked,
        "runtimes": [name for name, enabled in (("python", has_python), ("node", has_node)) if enabled],
        "files": found,
        "packages": sorted(set(packages))[:200],
        "install_commands": install_commands,
        "notes": "Locked dependency plan" if locked else "Unlocked dependency plan; install requires explicit operator approval.",
    }


def verify_snapshot(snapshot_path: str, manifest: list[dict]) -> int:
    verified = 0
    for entry in manifest:
        path = safe_relative_path(entry["path"])
        expected = entry.get("sha256", "")
        data = read_resource(snapshot_path, path)
        actual = hashlib.sha256(data).hexdigest()
        if expected and actual != expected:
            raise ExecutionError(f"Snapshot hash mismatch for {path}")
        verified += 1
    return verified


def detect_requirements(manifest: list[dict], snapshot_path: str) -> dict:
    """Statically inspect Python files without importing or executing them."""
    imports: set[str] = set()
    scripts: list[str] = []
    datasets: list[str] = []
    stdlib = set(getattr(sys, "stdlib_module_names", ()))
    for entry in manifest:
        path = entry.get("path", "")
        if not path.endswith(".py"):
            if path.startswith("data/") or "/data/" in path:
                datasets.append(path)
            continue
        scripts.append(path)
        try:
            tree = ast.parse(read_resource(snapshot_path, path).decode("utf-8", "replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                imports.add(node.module.split(".")[0])
    external = sorted(name for name in imports if name not in stdlib and name not in {"scripts", "data", "core", "design_system", "search"})
    return {
        "scripts": sorted(scripts),
        "datasets": sorted(datasets),
        "python_imports": sorted(imports),
        "external_dependencies": external,
        "dependencies": detect_dependencies(manifest, snapshot_path),
        "notes": "Static analysis only. Missing runtime dependencies are reported at execution time." if external else "No external Python dependencies detected.",
    }


def chown_workspace(workspace: Path, uid: int | None = None, gid: int | None = None) -> None:
    if uid is None or gid is None:
        settings = get_settings()
        uid = uid if uid is not None else settings.execution_uid
        gid = gid if gid is not None else settings.execution_gid
    for root, dirs, files in os.walk(workspace):
        for name in dirs + files:
            try:
                os.chown(os.path.join(root, name), uid, gid)
            except (PermissionError, OSError):
                pass
    try:
        os.chown(workspace, uid, gid)
    except (PermissionError, OSError):
        pass


def materialize_workspace(package: dict, workspace: Path) -> int:
    root = workspace / package["workspace_path"]
    root.mkdir(parents=True, exist_ok=True)
    snapshot_path = package["version"].snapshot_path
    verified = verify_snapshot(snapshot_path, package["manifest"])
    for entry in package["manifest"]:
        path = safe_relative_path(entry["path"])
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(read_resource(snapshot_path, path))
    return verified


def _limits() -> tuple[int, int]:
    settings = get_settings()
    return settings.execution_timeout_seconds, settings.execution_max_memory_mb * 1024 * 1024


def build_sandbox_command(workspace: Path, argv: list[str]) -> list[str]:
    if len(argv) < 2:
        raise ExecutionError("An interpreter and a script path are required")
    runtime = resolve_runtime(argv[0], argv[1])
    script = argv[1]
    if not script or ".." in script or PurePosixPath(script).is_absolute():
        raise ExecutionError("A relative script path inside the package is required")
    script_path = workspace / script
    if not script_path.exists() or workspace not in script_path.resolve().parents:
        raise ExecutionError("Script is not part of the approved package")
    interpreter = "python3" if runtime == "python3" else runtime
    command = [interpreter, *argv[1:]]
    settings = get_settings()
    bwrap = shutil.which("bwrap")
    if settings.execution_require_bubblewrap and not bwrap:
        raise ExecutionError("Bubblewrap is required for isolated execution but is unavailable")
    if not bwrap:
        return command
    return [
        bwrap,
        "--unshare-all",
        "--die-with-parent",
        "--clearenv",
        "--setenv", "HOME", "/workspace",
        "--setenv", "LANG", "C.UTF-8",
        "--setenv", "PYTHONIOENCODING", "utf-8",
        "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
        "--setenv", "PATH", "/usr/local/bin:/usr/bin:/bin",
        "--ro-bind", "/usr", "/usr",
        "--ro-bind", "/lib", "/lib",
        "--ro-bind", "/lib64", "/lib64",
        "--ro-bind", "/etc", "/etc",
        "--dev", "/dev",
        "--proc", "/proc",
        "--tmpfs", "/tmp",
        "--bind", str(workspace), "/workspace",
        "--chdir", "/workspace",
        *command,
    ]


def _preexec(memory_bytes: int, cpu_seconds: int):
    def apply():
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
        except Exception:
            pass
    return apply


def _bootstrap_dependencies(client, settings, host_workspace: Path, deps: dict,
                           memory_bytes: int, cpu_millicores: int) -> dict:
    commands = deps.get("install_commands") or []
    if not commands:
        return {"installed": False, "locked": deps.get("locked", True), "commands": []}
    if not deps.get("locked") and not settings.execution_allow_unlocked_dependencies:
        raise ExecutionError("Dependency files are not locked; set AGENTDOCK_EXEC_ALLOW_UNLOCKED_DEPS=true to allow")
    if not settings.execution_allow_dependency_network:
        raise ExecutionError("Dependency installation requires network; AGENTDOCK_EXEC_ALLOW_DEPENDENCY_NETWORK=false")
    container = client.containers.run(
        settings.execution_image,
        command=["sh", "-c", " && ".join(commands)],
        volumes={str(host_workspace): {"bind": "/workspace", "mode": "rw"}},
        working_dir="/workspace",
        environment={"HOME": "/tmp", "LANG": "C.UTF-8", "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                     "NPM_CONFIG_CACHE": "/tmp/npm"},
        network_disabled=False,
        read_only=True,
        tmpfs={"/tmp": "rw,size=256m,nosuid,nodev"},
        mem_limit=memory_bytes,
        nano_cpus=cpu_millicores * 1_000_000,
        cap_drop=["ALL"],
        security_opt=["no-new-privileges:true"],
        pids_limit=128,
        detach=True,
        auto_remove=False,
        stdout=True,
        stderr=True,
    )
    try:
        result = container.wait(timeout=min(300, settings.execution_max_timeout_seconds))
        exit_code = int(result.get("StatusCode", -1))
        if exit_code != 0:
            stderr = container.logs(stdout=False, stderr=True).decode("utf-8", "replace")
            raise ExecutionError(f"Dependency installation failed: {stderr[-500:]}")
        return {"installed": True, "locked": bool(deps.get("locked")),
                "commands": commands, "packages": deps.get("packages", [])}
    finally:
        try:
            container.remove(force=True)
        except Exception:
            pass


def _run_in_docker(job: ExecutionJob, db: Session, workspace: Path, argv: list[str],
                   timeout: int, memory_bytes: int, cpu_millicores: int,
                   network_enabled: bool, deps: dict) -> dict:
    import docker

    settings = get_settings()
    client = docker.from_env()
    host_workspace = Path(settings.execution_host_workspace_root) / workspace.name
    runtime = resolve_runtime(argv[0], argv[1])
    script = argv[1]
    if not script or ".." in script or PurePosixPath(script).is_absolute():
        raise ExecutionError("A relative script path inside the package is required")
    script_path = workspace / script
    if not script_path.exists() or workspace not in script_path.resolve().parents:
        raise ExecutionError("Script is not part of the approved package")
    bootstrap = _bootstrap_dependencies(client, settings, host_workspace, deps, memory_bytes, cpu_millicores)
    interpreter = "python3" if runtime == "python3" else runtime
    command = [interpreter, *argv[1:]]
    environment = {"HOME": "/tmp", "LANG": "C.UTF-8", "PYTHONIOENCODING": "utf-8",
                   "PYTHONDONTWRITEBYTECODE": "1"}
    if bootstrap.get("installed"):
        if "python" in deps.get("runtimes", []):
            environment["PYTHONPATH"] = "/workspace/.deps"
        if "node" in deps.get("runtimes", []):
            environment["NODE_PATH"] = "/workspace/node_modules"
    started = time.monotonic()
    container = client.containers.run(
        settings.execution_image,
        command=command,
        volumes={str(host_workspace): {"bind": "/workspace", "mode": "rw"}},
        working_dir="/workspace",
        environment=environment,
        network_disabled=not network_enabled,
        read_only=True,
        tmpfs={"/tmp": "rw,size=64m,nosuid,nodev"},
        mem_limit=memory_bytes,
        nano_cpus=cpu_millicores * 1_000_000,
        cap_drop=["ALL"],
        security_opt=["no-new-privileges:true"],
        pids_limit=64,
        detach=True,
        auto_remove=False,
        stdout=True,
        stderr=True,
    )
    job.runner_id = container.id
    job.status = "running"
    job.sandbox = "docker"
    job.started_at = utcnow()
    job.completed_at = None
    db.commit()
    stats = {}
    try:
        try:
            result = container.wait(timeout=timeout)
            exit_code = int(result.get("StatusCode", -1))
        except Exception as error:
            if "timeout" in str(error).lower():
                container.kill()
                raise ExecutionError(f"Execution timed out after {timeout} seconds")
            raise
        try:
            stats = container.stats(stream=False) or {}
        except Exception:
            stats = {}
        stdout = container.logs(stdout=True, stderr=False).decode("utf-8", "replace")
        stderr = container.logs(stdout=False, stderr=True).decode("utf-8", "replace")
        limit = settings.execution_max_output_bytes
        memory = (stats.get("memory_stats") or {}).get("max_usage") or (stats.get("memory_stats") or {}).get("usage") or 0
        cpu_total = ((stats.get("cpu_stats") or {}).get("cpu_usage") or {}).get("total_usage") or 0
        return {
            "status": "succeeded" if exit_code == 0 else "failed",
            "exit_code": exit_code, "stdout": stdout[:limit], "stderr": stderr[:limit],
            "error": "", "files_verified": 0, "workspace": str(workspace),
            "duration_ms": int((time.monotonic() - started) * 1000),
            "peak_memory_bytes": int(memory), "cpu_time_ms": int(cpu_total / 1_000_000),
            "resource_stats": {"memory_stats": stats.get("memory_stats", {}),
                               "cpu_stats": stats.get("cpu_stats", {})},
            "dependency_install": bootstrap,
        }
    finally:
        try:
            container.remove(force=True)
        except Exception:
            pass
        job.runner_id = ""
        db.commit()


def run_job(job_id: str, progress: Callable[[str], None] | None = None) -> dict:
    """Run a claimed ExecutionJob. Called only by the background worker."""
    settings = get_settings()
    if not settings.execution_enabled:
        raise ExecutionError("Skill execution is disabled on this deployment")
    from .db import SessionLocal

    with SessionLocal() as db:
        job = db.get(ExecutionJob, job_id)
        if not job:
            raise ExecutionError("Execution job no longer exists")
        package = resolve_package(db, job.skill_id, job.version)
        assert_execution_allowed(package["skill"])
        defaults = _limits()
        timeout = min(max(job.timeout_seconds or defaults[0], 1), settings.execution_max_timeout_seconds)
        memory_bytes = min(max(job.max_memory_mb or defaults[1] // (1024 * 1024), 64),
                           settings.execution_max_memory_mb) * 1024 * 1024
        cpu_millicores = min(max(job.max_cpu_millicores or 1000, 100), 4000)
        deps = detect_dependencies(package["manifest"], package["version"].snapshot_path)
        job.dependencies = deps
        job.timeout_seconds = timeout
        job.max_memory_mb = memory_bytes // (1024 * 1024)
        job.max_cpu_millicores = cpu_millicores
        db.commit()
        verified = verify_snapshot(package["version"].snapshot_path, package["manifest"])
        if progress:
            progress(f"verified {verified} immutable files")
        workspace_root = Path(settings.execution_workspace_root)
        workspace_root.mkdir(parents=True, exist_ok=True)
        workspace = Path(tempfile.mkdtemp(prefix="job-", dir=str(workspace_root)))
        try:
            files = materialize_workspace(package, workspace)
            chown_workspace(workspace)
            if progress:
                progress(f"materialized {files} files")
            argv = [job.command, *job.arguments]
            if len(argv) > 1:
                argv[1] = package["workspace_path"].rstrip("/") + "/" + normalize_package_path(package, argv[1])
            resolve_runtime(argv[0], argv[1])
            if settings.execution_driver == "docker":
                result = _run_in_docker(job, db, workspace, argv, timeout, memory_bytes,
                                        cpu_millicores, bool(job.network_enabled), deps)
                result["files_verified"] = files
                return result
            sandbox_command = build_sandbox_command(workspace, argv)
            started = time.monotonic()
            process = subprocess.Popen(
                sandbox_command,
                cwd=str(workspace),
                env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                preexec_fn=_preexec(memory_bytes, max(1, timeout)),
                start_new_session=True,
            )
            job.pid = process.pid
            job.status = "running"
            job.sandbox = "bubblewrap" if shutil.which("bwrap") else "none"
            job.started_at = utcnow()
            job.completed_at = None
            db.commit()
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                stdout, stderr = process.communicate()
                raise ExecutionError(f"Execution timed out after {timeout} seconds")
            limit = settings.execution_max_output_bytes
            result = {
                "status": "succeeded" if process.returncode == 0 else "failed",
                "exit_code": process.returncode,
                "stdout": stdout.decode("utf-8", "replace")[:limit],
                "stderr": stderr.decode("utf-8", "replace")[:limit],
                "error": "",
                "files_verified": files,
                "workspace": str(workspace),
                "duration_ms": int((time.monotonic() - started) * 1000),
                "peak_memory_bytes": 0, "cpu_time_ms": 0,
                "resource_stats": {"driver": "bubblewrap"},
                "dependency_install": {"installed": False, "locked": deps.get("locked", True),
                                       "commands": deps.get("install_commands", [])},
            }
            return result
        except Exception:
            db.rollback()
            raise
        finally:
            shutil.rmtree(workspace, ignore_errors=True)
            job.pid = None
            job.runner_id = ""
            db.commit()
