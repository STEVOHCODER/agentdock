import argparse
import logging
import os
import signal
import time
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import and_, or_, select, update

from .config import get_settings
from .db import Base, SessionLocal, engine
from .github import parse_repo_url
from .ingest import import_repository
from .models import AuditLog, ExecutionJob, ImportBatch, Repository, SynchronizationJob, utcnow
from .billing import expire_due_subscriptions
from .discovery import run_discovery_if_due
from . import execution as execution_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("agentdock.worker")
TERMINAL_STATUSES = {"succeeded", "source_unavailable", "failed"}


def schedule_hours(repository: Repository) -> int:
    if repository.stars >= 2000:
        return 6
    if repository.stars >= 100:
        return 24
    return 24 * 7


def enqueue_due(db, limit: int = 200) -> int:
    """Enqueue due syncs while locking source rows so multiple workers cannot duplicate them."""
    now = utcnow()
    due = db.scalars(
        select(Repository)
        .where(Repository.status == "approved",
               or_(Repository.next_sync_at.is_(None), Repository.next_sync_at <= now))
        .order_by(Repository.next_sync_at.asc().nullsfirst(), Repository.id)
        .with_for_update(skip_locked=True)
        .limit(limit)
    ).all()
    created = 0
    for repository in due:
        active = db.scalar(select(SynchronizationJob.id).where(
            SynchronizationJob.repository_id == repository.id,
            SynchronizationJob.status.in_(["queued", "running"])).limit(1))
        if active:
            continue
        db.add(SynchronizationJob(repository_id=repository.id, source_url=repository.url, operation="sync"))
        repository.next_sync_at = now + timedelta(hours=schedule_hours(repository))
        created += 1
    db.commit()
    return created


def recover_expired_leases(db) -> int:
    now = utcnow()
    stale_before = now - timedelta(minutes=get_settings().worker_lease_minutes)
    result = db.execute(
        update(SynchronizationJob)
        .where(SynchronizationJob.status == "running",
               or_(SynchronizationJob.lease_expires_at <= now,
                   and_(SynchronizationJob.lease_expires_at.is_(None),
                        or_(SynchronizationJob.started_at.is_(None), SynchronizationJob.started_at <= stale_before))))
        .values(status="queued", lease_expires_at=None,
                error="Worker lease expired; job returned to the queue.")
    )
    db.commit()
    return result.rowcount or 0


def refresh_batch(db, batch_id: str | None) -> None:
    if not batch_id:
        return
    batch = db.get(ImportBatch, batch_id)
    if not batch:
        return
    jobs = db.scalars(select(SynchronizationJob).where(SynchronizationJob.batch_id == batch_id)).all()
    succeeded = sum(job.status == "succeeded" for job in jobs)
    failed = sum(job.status in {"failed", "source_unavailable"} and job.next_retry_at is None for job in jobs)
    batch.completed_count = succeeded + failed
    batch.failed_count = failed
    active = any(job.status in {"queued", "running"} or
                 (job.status == "failed" and job.next_retry_at and job.next_retry_at > utcnow()) for job in jobs)
    if active:
        batch.status = "running" if any(job.status == "running" for job in jobs) else "queued"
        batch.completed_at = None
    elif failed:
        batch.status = "partial_failure" if succeeded else "failed"
        batch.completed_at = utcnow()
    else:
        batch.status = "succeeded"
        batch.completed_at = utcnow()


def claim_job(db) -> SynchronizationJob | None:
    now = utcnow()
    job = db.scalar(
        select(SynchronizationJob)
        .where(or_(SynchronizationJob.status == "queued",
                   and_(SynchronizationJob.status == "failed",
                        SynchronizationJob.next_retry_at.is_not(None),
                        SynchronizationJob.next_retry_at <= now)))
        .order_by(SynchronizationJob.created_at, SynchronizationJob.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if not job:
        return None
    job.status = "running"
    job.attempt_count += 1
    job.started_at = now
    job.completed_at = None
    job.lease_expires_at = now + timedelta(minutes=get_settings().worker_lease_minutes)
    job.next_retry_at = None
    job.error = ""
    job.progress_current = 0
    job.progress_total = len(job.skill_paths or [])
    refresh_batch(db, job.batch_id)
    db.commit()
    return job


def _refresh_job_lease(db, job_id: str, current: int, total: int) -> None:
    job = db.get(SynchronizationJob, job_id)
    if not job or job.status != "running":
        return
    job.progress_current = current
    job.progress_total = total
    job.lease_expires_at = utcnow() + timedelta(minutes=get_settings().worker_lease_minutes)
    db.commit()


def claim_execution_job(db):
    return db.scalar(
        select(ExecutionJob)
        .where(ExecutionJob.status == "queued")
        .order_by(ExecutionJob.created_at, ExecutionJob.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )


def process_execution_once() -> bool:
    """Run at most one queued execution. Returns True when work was processed."""
    if not get_settings().execution_enabled:
        return False
    with SessionLocal() as db:
        job = claim_execution_job(db)
        if not job:
            return False
        job_id = job.id
        db.commit()
        try:
            result = execution_service.run_job(job_id, progress=lambda message: logger.info("execution %s: %s", job_id, message))
            with SessionLocal() as update_db:
                current = update_db.get(ExecutionJob, job_id)
                if not current:
                    return True
                if current.status == "canceled":
                    if current.pid:
                        try:
                            os.killpg(current.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    if current.runner_id:
                        try:
                            import docker
                            docker.from_env().containers.get(current.runner_id).remove(force=True)
                        except Exception:
                            pass
                    return True
                current.status = result["status"]
                current.stdout = result["stdout"]
                current.stderr = result["stderr"]
                current.error = result["error"]
                current.exit_code = result["exit_code"]
                current.completed_at = utcnow()
                current.dependencies = result.get("dependency_install") or current.dependencies or {}
                current.duration_ms = result.get("duration_ms")
                current.peak_memory_bytes = result.get("peak_memory_bytes")
                current.cpu_time_ms = result.get("cpu_time_ms")
                current.resource_stats = result.get("resource_stats") or {}
                update_db.add(AuditLog(
                    actor_id=current.user_id, action="skill.executed", target_type="skill",
                    target_id=current.skill_id,
                    details={"job_id": job_id, "version": current.version, "exit_code": current.exit_code,
                             "files_verified": result.get("files_verified", 0),
                             "duration_ms": current.duration_ms,
                             "runtime": current.command},
                ))
                update_db.commit()
            logger.info("execution %s finished: %s", job_id, result["status"])
        except Exception as exc:
            logger.exception("execution %s failed", job_id)
            with SessionLocal() as update_db:
                current = update_db.get(ExecutionJob, job_id)
                if current and current.status != "canceled":
                    current.status = "failed"
                    current.error = str(exc)[:2000]
                    current.completed_at = utcnow()
                    update_db.commit()
        return True


def run_once() -> bool:
    if process_execution_once():
        return True
    if get_settings().env != "production":
        Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        recover_expired_leases(db)
        enqueue_due(db)
        job = claim_job(db)
        if not job:
            return False
        job_id = job.id
        batch_id = job.batch_id
        operation = job.operation or "sync"
        repository_id = job.repository_id
        repository_url = job.source_url
        skill_paths = list(job.skill_paths or [])
        community = job.community or ""
        attempt_count = job.attempt_count

        if operation == "sync" and repository_id:
            repository = db.get(Repository, repository_id)
            if not repository:
                job.status = "failed"
                job.error = "Repository record no longer exists."
                job.completed_at = utcnow()
                job.lease_expires_at = None
                refresh_batch(db, batch_id)
                db.commit()
                return True
            repository_url = repository.url

        # Serialize work for one repository while still allowing different sources
        # to be processed by separate worker processes.
        if repository_id:
            repository = db.scalar(select(Repository).where(Repository.id == repository_id).with_for_update())
            other_running = db.scalar(select(SynchronizationJob.id).where(
                SynchronizationJob.repository_id == repository_id,
                SynchronizationJob.id != job_id,
                SynchronizationJob.status == "running").limit(1))
            if other_running:
                job.status = "queued"
                job.lease_expires_at = None
                db.commit()
                return True
            if operation == "sync" and (not repository or repository.status != "approved"):
                job.status = "failed"
                job.error = "Repository is no longer approved for synchronization."
                job.completed_at = utcnow()
                job.lease_expires_at = None
                refresh_batch(db, batch_id)
                db.commit()
                return True
            db.commit()

        try:
            result = import_repository(
                db, repository_url,
                skill_paths=skill_paths if operation == "import" and skill_paths else None,
                community=community,
                progress_callback=lambda current, total: _refresh_job_lease(db, job_id, current, total),
            )
            job = db.get(SynchronizationJob, job_id)
            job.status = "succeeded"
            job.error = ""
            job.completed_at = utcnow()
            job.lease_expires_at = None
            job.result_count = len(result["skills"])
            job.progress_current = job.result_count
            job.progress_total = max(job.progress_total, job.result_count)
            repository = db.scalar(select(Repository).where(Repository.url == result["repository"]["url"]))
            if repository:
                job.repository_id = repository.id
                if repository.status == "approved":
                    repository.next_sync_at = utcnow() + timedelta(hours=schedule_hours(repository))
            refresh_batch(db, batch_id)
            db.commit()
            logger.info("%s %s; %s skills checked", operation, repository_url, job.result_count)
        except Exception as exc:
            db.rollback()
            job = db.get(SynchronizationJob, job_id)
            repository = db.get(Repository, repository_id) if repository_id else None
            permanent_client_error = isinstance(exc, HTTPException) and 400 <= exc.status_code < 500 and exc.status_code not in {408, 429}
            unavailable_sync = isinstance(exc, HTTPException) and exc.status_code == 404 and operation == "sync" and repository is not None
            exhausted = attempt_count >= 8
            job.lease_expires_at = None
            job.completed_at = utcnow()
            if unavailable_sync:
                job.status = "source_unavailable"
                job.error = "Upstream repository is unavailable; previously reviewed snapshots are retained."
                repository.status = "source_unavailable"
                db.add(AuditLog(action="repository.source_unavailable", target_type="repository",
                                target_id=repository.id,
                                details={"url": repository_url, "handling": "reviewed_snapshots_retained"}))
            elif permanent_client_error or exhausted:
                job.status = "failed"
                detail = exc.detail if isinstance(exc, HTTPException) else "Retry limit reached."
                job.error = str(detail)[:500]
                job.next_retry_at = None
            else:
                job.status = "failed"
                job.error = f"{type(exc).__name__}: {operation} failed"
                backoff = min(3600 * 24, 60 * (2 ** min(attempt_count, 10)))
                job.next_retry_at = utcnow() + timedelta(seconds=backoff)
            refresh_batch(db, batch_id)
            db.commit()
            logger.warning("%s failed for %s (%s)", operation, repository_url, type(exc).__name__)
        return True


def run_maintenance() -> dict:
    """Periodic account and discovery housekeeping, safe to run from one worker."""
    with SessionLocal() as db:
        expired = expire_due_subscriptions(db)
        discovered = False
        try:
            discovered = run_discovery_if_due(db)
        except Exception as exc:
            logger.warning("Scheduled discovery skipped (%s)", type(exc).__name__)
        if expired or discovered:
            logger.info("Maintenance: %s subscriptions expired, discovery_run=%s", expired, discovered)
        return {"expired_subscriptions": expired, "discovery_run": discovered}


def main():
    parser = argparse.ArgumentParser(description="AgentDock repository import, synchronization and maintenance worker")
    parser.add_argument("--once", action="store_true", help="Process at most one queued job and exit")
    parser.add_argument("--poll-seconds", type=int, default=5)
    parser.add_argument("--maintenance-seconds", type=int, default=600,
                        help="How often to expire subscriptions and run scheduled discovery")
    args = parser.parse_args()
    if args.once:
        run_once()
        return
    logger.info("AgentDock import/sync worker started")
    last_maintenance = 0.0
    while True:
        try:
            run_once()
            now = time.monotonic()
            if now - last_maintenance >= max(60, args.maintenance_seconds):
                run_maintenance()
                last_maintenance = now
        except Exception as exc:
            logger.error("Worker loop failed (%s)", type(exc).__name__)
        time.sleep(max(1, args.poll_seconds))


if __name__ == "__main__":
    main()
