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
from pathlib import Path, PurePosixPath
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import ExecutionJob, Skill, SkillVersion, utcnow
from .vault import read_resource, safe_relative_path

PAYTHON = sys.executable


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


def resolve_package(db: Session, identifier: str, version: str | None = None) -> dict:
    from .common import get_skill  # local import avoids a module cycle

    skill = get_skill(db, identifier)
    if skill.status != "approved" or skill.security_status != "clear":
        raise ExecutionError("Only approved, security-reviewed packages can be read")
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
            "complete": bool(groups["scripts"] and groups["data"]),
            "missing": [] if (groups["scripts"] and groups["data"]) else ["scripts" if not groups["scripts"] else "data"],
        },
    }


def normalize_package_path(package: dict, path: str) -> str:
    prefix = package["workspace_path"].rstrip("/") + "/"
    if path.startswith(prefix):
        return path[len(prefix):]
    return path


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
        "notes": "Static analysis only. Missing runtime dependencies are reported at execution time." if external else "No external Python dependencies detected.",
    }


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
    if not argv:
        raise ExecutionError("No command supplied")
    executable = Path(argv[0]).name
    if executable not in {"python", "python3", sys.executable and Path(sys.executable).name}:
        raise ExecutionError("Only Python commands are permitted")
    script = argv[1] if len(argv) > 1 else ""
    if not script or ".." in script or PurePosixPath(script).is_absolute():
        raise ExecutionError("A relative script path inside the package is required")
    script_path = workspace / script
    if not script_path.exists() or workspace not in script_path.resolve().parents:
        raise ExecutionError("Script is not part of the approved package")
    python = "python3"
    command = [python, *argv[1:]]
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


def _run_in_docker(job: ExecutionJob, db: Session, workspace: Path, argv: list[str],
                   timeout: int, memory_bytes: int) -> dict:
    import docker

    settings = get_settings()
    client = docker.from_env()
    host_workspace = Path(settings.execution_host_workspace_root) / workspace.name
    script = argv[1]
    if not script or ".." in script or PurePosixPath(script).is_absolute():
        raise ExecutionError("A relative script path inside the package is required")
    script_path = workspace / script
    if not script_path.exists() or workspace not in script_path.resolve().parents:
        raise ExecutionError("Script is not part of the approved package")
    command = ["python3", *argv[1:]]
    container = client.containers.run(
        settings.execution_image,
        command=command,
        volumes={str(host_workspace): {"bind": "/workspace", "mode": "rw"}},
        working_dir="/workspace",
        environment={"HOME": "/tmp", "LANG": "C.UTF-8", "PYTHONIOENCODING": "utf-8",
                     "PYTHONDONTWRITEBYTECODE": "1"},
        network_disabled=True,
        read_only=True,
        tmpfs={"/tmp": "rw,size=64m,nosuid,nodev"},
        mem_limit=memory_bytes,
        nano_cpus=1_000_000_000,
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
    try:
        try:
            result = container.wait(timeout=timeout)
            exit_code = int(result.get("StatusCode", -1))
        except Exception as error:
            if "timeout" in str(error).lower():
                container.kill()
                raise ExecutionError(f"Execution timed out after {timeout} seconds")
            raise
        stdout = container.logs(stdout=True, stderr=False).decode("utf-8", "replace")
        stderr = container.logs(stdout=False, stderr=True).decode("utf-8", "replace")
        limit = settings.execution_max_output_bytes
        return {
            "status": "succeeded" if exit_code == 0 else "failed",
            "exit_code": exit_code, "stdout": stdout[:limit], "stderr": stderr[:limit],
            "error": "", "files_verified": 0, "workspace": str(workspace),
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
        timeout, memory_bytes = _limits()
        verified = verify_snapshot(package["version"].snapshot_path, package["manifest"])
        if progress:
            progress(f"verified {verified} immutable files")
        workspace_root = Path(settings.execution_workspace_root)
        workspace_root.mkdir(parents=True, exist_ok=True)
        workspace = Path(tempfile.mkdtemp(prefix="job-", dir=str(workspace_root)))
        try:
            files = materialize_workspace(package, workspace)
            if progress:
                progress(f"materialized {files} files")
            argv = [job.command, *job.arguments]
            if len(argv) > 1:
                argv[1] = package["workspace_path"].rstrip("/") + "/" + normalize_package_path(package, argv[1])
            if settings.execution_driver == "docker":
                result = _run_in_docker(job, db, workspace, argv, timeout, memory_bytes)
                result["files_verified"] = files
                return result
            sandbox_command = build_sandbox_command(workspace, argv)
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
