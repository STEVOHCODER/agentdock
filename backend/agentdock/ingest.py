import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .admission import REDISTRIBUTION_LICENSES, evaluate_candidate
from .config import get_settings
from .github import GitHubClient, days_since, parse_repo_url
from .models import Repository, Skill, SkillVersion, TrustedPublisher, utcnow
from .vault import make_version, save_snapshot, slugify


# Hidden directories that legitimately hold agent skills. Hidden files and any
# other dot-prefixed directories (for example .git) stay excluded.
SKILL_CONTAINER_DIRS = {".agents", ".claude", ".cursor", ".devin", ".github", ".well-known"}


def synchronized_skill_status(skill: Skill, evaluation, repository: Repository) -> str:
    """Decide the status of a skill imported during repository synchronization.

    Security findings and licence problems always win. Auto-approval only
    applies to new/qualified skills from an already approved repository.
    """
    if evaluation.security_status != "clear":
        return "quarantined"
    if not evaluation.license_allowed:
        return "pending_review"
    if skill.status in {"approved", "withdrawn"}:
        return skill.status
    settings = get_settings()
    if settings.auto_approve_synced_skills and repository.status == "approved":
        return "approved"
    return evaluation.status


def parse_frontmatter(text: str) -> tuple[str, str]:
    name = ""
    description = ""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].splitlines():
                key, sep, value = line.partition(":")
                if sep and key.strip().lower() in {"name", "description"}:
                    parsed = value.strip().strip("\"'")
                    if key.strip().lower() == "name":
                        name = parsed
                    else:
                        description = parsed
    if not name:
        name = re.sub(r"\s+", " ", text.splitlines()[0].lstrip("# ").strip()) if text else "Community skill"
    if not description:
        for line in text.splitlines():
            if line.strip() and not line.strip().startswith("#"):
                description = line.strip()[:400]
                break
    return name[:160] or "Community skill", description[:400]


def category_for(name: str, description: str, explicit: str | None) -> str:
    if explicit:
        return explicit
    text = f"{name} {description}".lower()
    rules = [
        ("Frontend", ("react", "frontend", "next.js", "css", "vue", "ui")),
        ("Backend", ("backend", "api", "server", "node.js", "fastapi", "django")),
        ("Data Analysis", ("data analysis", "pandas", "sql", "analytics", "visualization")),
        ("DevOps", ("devops", "docker", "kubernetes", "ci/cd", "infrastructure")),
        ("AI Engineering", ("agent", "llm", "machine learning", "model", "prompt")),
        ("Documentation", ("documentation", "docs", "technical writing")),
        ("Testing", ("test", "qa", "quality assurance", "playwright")),
    ]
    return next((category for category, words in rules if any(word in text for word in words)), "Development")


def skill_license_id(files: dict[str, bytes], repository_license: str) -> str:
    markdown = files["SKILL.md"].decode("utf-8", errors="replace")
    if markdown.startswith("---"):
        sections = markdown.split("---", 2)
        if len(sections) >= 3:
            for line in sections[1].splitlines():
                key, separator, value = line.partition(":")
                if separator and key.strip().lower() in {"license", "spdx-license-identifier"}:
                    declared = value.strip().strip("\"'")
                    return declared if declared in REDISTRIBUTION_LICENSES or re.fullmatch(r"[A-Za-z0-9.+-]{2,80}", declared) else "unknown"
    local_licenses = [data.decode("utf-8", errors="replace") for path, data in files.items()
                      if path.split("/")[-1].lower() in {"license", "license.md", "license.txt"}]
    for text in local_licenses:
        spdx = re.search(r"SPDX-License-Identifier:\s*([A-Za-z0-9.+-]+)", text, re.I)
        if spdx:
            return spdx.group(1)
        first_lines = " ".join(text.splitlines()[:4]).lower()
        if "mit license" in first_lines:
            return "MIT"
        if "apache license" in first_lines and "2.0" in first_lines:
            return "Apache-2.0"
        if "bsd 3-clause" in first_lines:
            return "BSD-3-Clause"
        if "bsd 2-clause" in first_lines:
            return "BSD-2-Clause"
        return "unknown"
    return repository_license


def _read_skill_files(client: GitHubClient, owner: str, repo: str, branch: str, tree: list[dict], skill_path: str, settings) -> dict[str, bytes]:
    prefix = f"{skill_path}/" if skill_path else ""
    files = {}
    total = 0
    entries = [item for item in tree if item.get("type") == "blob" and item.get("mode") != "120000" and item.get("path", "").startswith(prefix)]
    if not skill_path:
        entries = [item for item in entries if len(item["path"].split("/")) == 1 or item["path"].split("/")[0] in {"assets", "references", "scripts"}]
    def _safe_path(item_path: str) -> bool:
        parts = item_path.split("/")
        for part in parts:
            if not part.startswith("."):
                continue
            is_file = part == parts[-1]
            if is_file or part not in SKILL_CONTAINER_DIRS:
                return False
        return True

    entries = [item for item in entries if _safe_path(item["path"])]
    if len(entries) > settings.max_skill_files:
        raise HTTPException(status_code=413, detail=f"Skill contains too many files (limit {settings.max_skill_files})")
    selected = []
    for item in entries:
        relative = item["path"][len(prefix):] if prefix else item["path"]
        if not relative or item.get("size", 0) > settings.max_skill_bytes:
            continue
        selected.append((relative, item["path"]))
    if len(selected) > settings.max_skill_files:
        raise HTTPException(status_code=413, detail=f"Skill contains too many files (limit {settings.max_skill_files})")
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(selected)))) as pool:
        jobs = {pool.submit(client.file, owner, repo, branch, path, settings.max_skill_bytes): relative
                for relative, path in selected}
        for job in as_completed(jobs):
            relative = jobs[job]
            data = job.result()
            total += len(data)
            if total > settings.max_skill_bytes:
                raise HTTPException(status_code=413, detail=f"Skill package exceeds {settings.max_skill_bytes} bytes")
            files[relative] = data
    if "SKILL.md" not in files:
        instruction_keys = [key for key in files if key.split("/")[-1].lower() == "skill.md"]
        if instruction_keys:
            files["SKILL.md"] = files.pop(instruction_keys[0])
    if "SKILL.md" not in files:
        raise HTTPException(status_code=422, detail="The selected folder does not contain SKILL.md")
    return files


def _tree_directory(client: GitHubClient, owner: str, repo: str, ref: str, path: str,
                    node_budget: int) -> str:
    """Resolve a repository-relative directory to its Git tree SHA."""
    current_ref = ref
    visited = 0
    for segment in (part for part in path.split("/") if part):
        response = client.tree(owner, repo, current_ref, recursive=False)
        if response.get("truncated"):
            raise HTTPException(status_code=422, detail="GitHub returned an incomplete directory listing")
        children = response.get("tree", [])
        visited += len(children)
        if visited > node_budget:
            raise HTTPException(status_code=413, detail="Selected GitHub path requires too many directory entries to inspect")
        match = next((item for item in children if item.get("path") == segment and item.get("type") == "tree"), None)
        if match is None or not match.get("sha"):
            raise HTTPException(status_code=404, detail=f"Selected GitHub directory was not found: {path}")
        current_ref = match["sha"]
    return current_ref


def _selected_paths_tree(client: GitHubClient, owner: str, repo: str, ref: str,
                         selected_paths: list[str], settings) -> list[dict]:
    """Fetch only selected skill folders when GitHub truncates the repository tree."""
    node_budget = max(1_000, min(10_000, settings.max_skill_files * 10))
    grouped: dict[str, list[str]] = {}
    for skill_path in selected_paths:
        parent = skill_path.rpartition("/")[0]
        grouped.setdefault(parent, []).append(skill_path)

    result: list[dict] = []
    for parent, paths in grouped.items():
        parent_ref = _tree_directory(client, owner, repo, ref, parent, node_budget) if parent else ref
        parent_tree = client.tree(owner, repo, parent_ref, recursive=True)
        if not parent_tree.get("truncated"):
            for item in parent_tree.get("tree", []):
                item_path = item.get("path", "")
                result.append({**item, "path": f"{parent}/{item_path}" if parent and item_path else parent or item_path})
            continue

        # The common parent is too large for GitHub's recursive tree limit. Narrow
        # further to each requested skill folder and traverse only if that folder
        # itself exceeds the recursive endpoint limit.
        for skill_path in paths:
            relative = skill_path[len(parent) + 1:] if parent else skill_path
            skill_ref = _tree_directory(client, owner, repo, parent_ref, relative, node_budget)
            skill_tree = client.tree(owner, repo, skill_ref, recursive=True)
            if not skill_tree.get("truncated"):
                for item in skill_tree.get("tree", []):
                    item_path = item.get("path", "")
                    if item_path:
                        result.append({**item, "path": f"{skill_path}/{item_path}"})
                continue

            stack = [(skill_ref, skill_path)]
            visited = 0
            while stack:
                directory_ref, directory_path = stack.pop()
                directory_tree = client.tree(owner, repo, directory_ref, recursive=False)
                if directory_tree.get("truncated"):
                    raise HTTPException(status_code=422, detail="GitHub returned an incomplete selected skill directory")
                for item in directory_tree.get("tree", []):
                    visited += 1
                    if visited > node_budget:
                        raise HTTPException(status_code=413, detail="Selected skill directory is too large to inspect")
                    item_path = f"{directory_path}/{item.get('path', '')}" if item.get("path") else directory_path
                    normalized = {**item, "path": item_path}
                    if item.get("type") == "tree" and item.get("sha"):
                        stack.append((item["sha"], item_path))
                    else:
                        result.append(normalized)
    return result


def import_repository(db: Session, url: str, skill_path: str | None = None, category: str | None = None,
                     skill_paths: list[str] | None = None, community: str = "",
                     progress_callback: Callable[[int, int], None] | None = None) -> dict:
    owner, name, canonical = parse_repo_url(url)
    if skill_path is not None:
        skill_path = skill_path.strip().strip("/")
        if ".." in skill_path.split("/") or "\\" in skill_path or "\x00" in skill_path:
            raise HTTPException(status_code=422, detail="Invalid skill directory path")
    requested_paths = None
    if skill_paths is not None:
        requested_paths = [path.strip().strip("/") for path in skill_paths]
        if any(not path or ".." in path.split("/") or "\\" in path or "\x00" in path for path in requested_paths):
            raise HTTPException(status_code=422, detail="Invalid selected skill directory path")
        if len(set(requested_paths)) != len(requested_paths):
            raise HTTPException(status_code=422, detail="Selected skill directories must be unique")
    full_import = skill_path is None and not requested_paths
    settings = get_settings()
    first_party = owner.lower() in settings.first_party_owner_list
    with GitHubClient() as client:
        metadata = client.repository(owner, name)
        if metadata.get("private") or metadata.get("archived"):
            raise HTTPException(status_code=422, detail="Private or archived repositories cannot be admitted")
        branch = metadata.get("default_branch") or "main"
        license_info = metadata.get("license") or {}
        license_id = license_info.get("spdx_id", "unknown") if isinstance(license_info, dict) else "unknown"
        repository = db.scalar(select(Repository).where(Repository.url == canonical))
        previous_license = repository.license_id if repository else ""
        previous_community = repository.community if repository else ""
        pushed_at = metadata.get("pushed_at")
        if repository is None:
            repository = Repository(url=canonical, owner=owner, name=name)
            db.add(repository)
            db.flush()
        repository.default_branch = branch
        repository.stars = int(metadata.get("stargazers_count", 0))
        repository.forks = int(metadata.get("forks_count", 0))
        license_changed = previous_license != license_id
        community_changed = bool(community.strip()) and previous_community != community.strip()
        repository.license_id = license_id
        if first_party:
            repository.rights_status = "owner_authorized"
        if community:
            repository.community = community.strip()[:120]
            db.execute(update(Skill).where(Skill.repository_id == repository.id).values(community=repository.community))
        repository.last_push_at = None
        if pushed_at:
            from datetime import datetime
            repository.last_push_at = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
        commit_sha = client.commit(owner, name, branch)
        if repository.status in {"discovered", "pending_review"}:
            repository.status = "pending_review"
        repository.last_sync_at = utcnow()
        if repository.last_commit_sha and repository.last_commit_sha == commit_sha and not license_changed and not community_changed and full_import:
            existing_skills = db.scalars(select(Skill).where(Skill.repository_id == repository.id).order_by(Skill.path)).all()
            db.commit()
            return {"repository": {"id": repository.id, "url": canonical, "stars": repository.stars,
                                    "forks": repository.forks, "license": license_id, "community": repository.community,
                                    "status": repository.status, "last_commit_sha": commit_sha},
                    "skills": [{"id": skill.id, "slug": skill.slug, "name": skill.name, "path": skill.path,
                                "score": skill.score, "status": skill.status, "license": skill.license_id,
                                "license_allowed": skill.license_id in REDISTRIBUTION_LICENSES,
                                "security_status": skill.security_status, "version": skill.latest_version}
                               for skill in existing_skills]}
        tree_response = client.tree(owner, name, branch)
        if tree_response.get("truncated"):
            if full_import:
                raise HTTPException(status_code=422, detail="GitHub's repository tree is too large for a full import; select specific skill folders")
            entries = _selected_paths_tree(client, owner, name, branch, [skill_path] if skill_path is not None else requested_paths, settings)
        else:
            entries = tree_response.get("tree", [])
        discovered_paths = set()
        for item in entries:
            path = item.get("path", "")
            if item.get("type") != "blob" or item.get("mode") == "120000":
                continue
            if path in {"SKILL.md", "skill.md"}:
                discovered_paths.add("")
            elif path.endswith("/SKILL.md"):
                discovered_paths.add(path[:-len("/SKILL.md")])
            elif path.endswith("/skill.md"):
                discovered_paths.add(path[:-len("/skill.md")])
        discovered_paths = sorted(discovered_paths)
        if any(item.get("path") == "SKILL.md" and item.get("type") == "blob" for item in entries):
            discovered_paths.insert(0, "")
        if skill_path is not None:
            selected_paths = [skill_path]
        elif requested_paths:
            selected_paths = requested_paths
        else:
            selected_paths = discovered_paths
        missing_paths = sorted(set(selected_paths) - set(discovered_paths))
        if missing_paths:
            raise HTTPException(status_code=404, detail=f"No SKILL.md exists at selected path: {missing_paths[0]}")
        if not selected_paths:
            raise HTTPException(status_code=422, detail="No SKILL.md files found in this repository")
        if len(selected_paths) > settings.max_skills_per_repository:
            raise HTTPException(status_code=413, detail=f"Import contains too many skill folders (limit {settings.max_skills_per_repository})")
        trusted = db.scalar(select(TrustedPublisher).where(TrustedPublisher.github_handle.ilike(owner))) is not None
        imported = []
        seen_skill_ids = set()
        total_bytes = 0
        if progress_callback:
            progress_callback(0, len(selected_paths))
        for index, path in enumerate(selected_paths, 1):
            files = _read_skill_files(client, owner, name, branch, entries, path, settings)
            total_bytes += sum(len(value) for value in files.values())
            if total_bytes > settings.max_repository_import_bytes:
                raise HTTPException(status_code=413, detail=f"Repository import exceeds {settings.max_repository_import_bytes} bytes")
            instructions = files["SKILL.md"].decode("utf-8", errors="replace")
            skill_name, description = parse_frontmatter(instructions)
            license_for_item = skill_license_id(files, license_id)
            if first_party and license_for_item not in REDISTRIBUTION_LICENSES:
                license_for_item = "OWNER-AUTHORIZED"
            evaluation = evaluate_candidate(stars=repository.stars, trusted=trusted,
                                            last_push_days=days_since(pushed_at), skill_md=instructions,
                                            license_id=license_for_item, files=files)
            identity = slugify(f"{owner}-{name}-{path or skill_name}")
            skill = db.scalar(select(Skill).where(Skill.slug == identity))
            if skill is None:
                skill = Skill(repository_id=repository.id, slug=identity, name=skill_name,
                              description=description, path=path, category=category_for(skill_name, description, category),
                              creator=owner, community=community.strip()[:120] or repository.community,
                              license_id=license_for_item, source_url=f"{canonical}/tree/{branch}/{path}" if path else canonical,
                              stars=repository.stars)
                db.add(skill)
                db.flush()
            else:
                skill.name = skill_name
                skill.description = description
                skill.category = category_for(skill_name, description, category)
                skill.community = community.strip()[:120] or repository.community
                skill.license_id = license_for_item
                skill.stars = repository.stars
            seen_skill_ids.add(skill.id)
            version = make_version(commit_sha, files)
            existing_version = db.scalar(select(SkillVersion).where(SkillVersion.skill_id == skill.id, SkillVersion.version == version))
            if not existing_version:
                snapshot, content_hash, manifest = save_snapshot(skill.id, version, files)
                db.add(SkillVersion(skill_id=skill.id, version=version,
                                    source_commit=commit_sha, content_hash=content_hash,
                                    manifest=manifest, snapshot_path=snapshot))
            # Full instructions stay in SkillVault/object storage; the catalogue row
            # contains only searchable metadata so large imports do not inflate PostgreSQL.
            skill.instructions = ""
            skill.score = evaluation.score
            skill.commercial_ok = evaluation.license_allowed
            skill.security_status = evaluation.security_status
            skill.status = synchronized_skill_status(skill, evaluation, repository)
            skill.latest_version = version
            skill.updated_at = utcnow()
            imported.append({"id": skill.id, "slug": skill.slug, "name": skill.name, "path": path,
                             "score": evaluation.score, "criteria": evaluation.criteria,
                             "status": skill.status, "license": license_for_item, "license_allowed": evaluation.license_allowed,
                             "security_status": skill.security_status, "security_findings": evaluation.security_findings,
                             "version": version, "files": len(files)})
            if progress_callback and (index % settings.import_progress_interval == 0 or index == len(selected_paths)):
                db.flush()
                progress_callback(index, len(selected_paths))
        if full_import:
            repository.last_commit_sha = commit_sha
            removed = db.scalars(select(Skill).where(Skill.repository_id == repository.id)).all()
            for old_skill in removed:
                if old_skill.id not in seen_skill_ids and old_skill.status == "approved":
                    old_skill.status = "withdrawn"
        db.commit()
        return {"repository": {"id": repository.id, "url": canonical, "stars": repository.stars,
                                "forks": repository.forks, "license": license_id, "community": repository.community,
                                "status": repository.status, "last_commit_sha": repository.last_commit_sha},
                "skills": imported}
