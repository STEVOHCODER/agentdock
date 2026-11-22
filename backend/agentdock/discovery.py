"""Automated GitHub candidate discovery.

Discovery only records repository candidates. It never imports or approves a
skill; admission and legal review remain explicit administrator actions.
"""
import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .github import GitHubClient, parse_repo_url
from .models import DiscoveryRun, Repository, SystemSetting, utcnow

logger = logging.getLogger("agentdock.discovery")


def discovery_settings(db: Session) -> dict:
    settings = get_settings()
    stored = db.get(SystemSetting, "discovery")
    base = {
        "enabled": settings.discovery_enabled,
        "interval_hours": settings.discovery_interval_hours,
        "topics": settings.discovery_topic_list,
        "keywords": settings.discovery_keyword_list,
        "languages": [],
        "min_stars": settings.discovery_min_stars,
        "per_page": settings.discovery_per_page,
        "last_run_at": None,
    }
    if stored and isinstance(stored.value, dict):
        base.update(stored.value)
    return base


def save_discovery_settings(db: Session, value: dict, actor_id: str | None = None) -> dict:
    merged = {**discovery_settings(db), **value}
    setting = db.get(SystemSetting, "discovery")
    if setting:
        setting.value = merged
        setting.updated_by = actor_id
    else:
        db.add(SystemSetting(key="discovery", value=merged, updated_by=actor_id))
    db.commit()
    return merged


def build_queries(config: dict) -> list[str]:
    min_stars = max(0, int(config.get("min_stars", 100)))
    per_page = max(1, min(int(config.get("per_page", 30)), 100))
    queries: list[str] = []
    for topic in (config.get("topics") or [])[:8]:
        queries.append(f"topic:{topic} stars:>={min_stars} fork:false archived:false")
    for keyword in (config.get("keywords") or [])[:4]:
        queries.append(f'"{keyword}" in:name,description,readme stars:>={min_stars} fork:false archived:false')
    for language in (config.get("languages") or [])[:3]:
        if language:
            queries.append(f"topic:agent-skills language:{language} stars:>={min_stars} fork:false archived:false")
    if not queries:
        queries.append(f"topic:agent-skills stars:>={min_stars} fork:false archived:false")
    return queries[:12]


def run_discovery(db: Session, *, triggered_by: str | None = None, overrides: dict | None = None) -> dict:
    config = {**discovery_settings(db), **(overrides or {})}
    run = DiscoveryRun(triggered_by=triggered_by, source="github", status="running",
                       query="; ".join(build_queries(config)))
    db.add(run)
    db.commit()
    candidates: dict[str, dict] = {}
    try:
        with GitHubClient() as client:
            for query in build_queries(config):
                for item in client.search_repositories(query, config.get("per_page", 30)):
                    if item.get("private") or item.get("archived") or item.get("fork"):
                        continue
                    html_url = item.get("html_url", "")
                    try:
                        owner, name, canonical = parse_repo_url(html_url)
                    except Exception:
                        continue
                    candidates[canonical] = {
                        "owner": owner, "name": name, "canonical": canonical,
                        "stars": int(item.get("stargazers_count", 0)),
                        "forks": int(item.get("forks_count", 0)),
                        "description": item.get("description") or "",
                        "license": ((item.get("license") or {}).get("spdx_id") or "unknown"),
                        "pushed_at": item.get("pushed_at"),
                        "topics": item.get("topics") or [],
                    }
        created = 0
        for candidate in candidates.values():
            existing = db.scalar(select(Repository).where(Repository.url == candidate["canonical"]))
            if existing:
                existing.stars = candidate["stars"]
                existing.forks = candidate["forks"]
                existing.license_id = candidate["license"] or existing.license_id
                if candidate.get("pushed_at"):
                    from datetime import datetime
                    existing.last_push_at = datetime.fromisoformat(candidate["pushed_at"].replace("Z", "+00:00"))
                continue
            repository = Repository(url=candidate["canonical"], owner=candidate["owner"], name=candidate["name"],
                                    stars=candidate["stars"], forks=candidate["forks"],
                                    license_id=candidate["license"] or "unknown",
                                    status="discovered", discovered_via="github-discovery",
                                    community="", priority="standard", sync_interval_hours=24)
            if candidate.get("pushed_at"):
                from datetime import datetime
                repository.last_push_at = datetime.fromisoformat(candidate["pushed_at"].replace("Z", "+00:00"))
            db.add(repository)
            created += 1
        run.candidates_found = len(candidates)
        run.created_count = created
        run.status = "succeeded"
        run.completed_at = utcnow()
        settings_value = discovery_settings(db)
        settings_value["last_run_at"] = utcnow().isoformat()
        stored = db.get(SystemSetting, "discovery")
        if stored:
            stored.value = settings_value
        else:
            db.add(SystemSetting(key="discovery", value=settings_value))
        db.commit()
        return {"id": run.id, "status": run.status, "candidates_found": run.candidates_found,
                "created_count": run.created_count, "query": run.query,
                "candidates": list(candidates.values())[:50]}
    except Exception as exc:
        db.rollback()
        run = db.get(DiscoveryRun, run.id)
        if run:
            run.status = "failed"
            run.error = f"{type(exc).__name__}: GitHub discovery failed"
            run.completed_at = utcnow()
            db.commit()
        logger.warning("GitHub discovery failed (%s)", type(exc).__name__)
        raise


def run_discovery_if_due(db: Session) -> bool:
    config = discovery_settings(db)
    if not config.get("enabled", True):
        return False
    last = config.get("last_run_at")
    if last:
        try:
            from datetime import datetime, timezone
            parsed = datetime.fromisoformat(last)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            if parsed + timedelta(hours=max(1, int(config.get("interval_hours", 24)))) > utcnow():
                return False
        except (ValueError, TypeError):
            pass
    try:
        run_discovery(db)
        return True
    except Exception:
        return False
