import ast
import base64
import hashlib
import io
import ipaddress
import logging
import re
import time
import zipfile
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import case, func, literal_column, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from redis.asyncio import Redis
from starlette.concurrency import run_in_threadpool

from .config import get_settings
from .common import (create_email_token, entitlement_summary, enrich_skill, listing_for_skill,
                     premium_entitlement, public_base_url, record_usage, review_stats)
from .db import Base, SessionLocal, engine
from .github import parse_repo_url
from .models import (APIKey, AdmissionDecision, AuditLog, Collection, CollectionItem, ExecutionJob, ImportBatch,
                     MarketplaceListing, Purchase, Repository, Skill, SkillVersion, Subscription,
                     SynchronizationJob, Team, TeamMember, TrustedPublisher, UsageEvent, User, UserSession,
                     utcnow)
from .schemas import (APIKeyInput, CollectionInput, DecisionInput, ExecutionInput, ImportBatchInput, ImportInput,
                      ImportSourceInput, LoginInput, RegisterInput, RepositoryStatusInput, TrustedPublisherInput)
from .security import admin_user, create_session, current_user, optional_user, issue_api_key, password_hash, require_scope, verify_password
from .vault import read_resource
from . import accounts, admin as admin_routes, execution as execution_routes, mailer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("agentdock")
settings = get_settings()


def request_source(request: Request) -> str:
    if request.headers.get("x-agentdock-source") == "mcp":
        return "mcp"
    if request.headers.get("authorization", "").startswith("Bearer"):
        return "api"
    return "web"


def record_failure(db: Session, user: User | None, event: str, source: str,
                   details: dict | None = None) -> None:
    if user is None:
        return
    record_usage(db, user, None, event, source, details=details)
    db.commit()


@asynccontextmanager
async def lifespan(application: FastAPI):
    startup()
    redis_client = None
    if settings.env == "production":
        if not settings.redis_url:
            raise RuntimeError("Set AGENTDOCK_REDIS_URL to enable shared production rate limiting")
        redis_client = Redis.from_url(settings.redis_url, socket_connect_timeout=3, socket_timeout=2,
                                      health_check_interval=30, decode_responses=True)
        try:
            await redis_client.ping()
        except Exception as exc:
            await redis_client.aclose()
            raise RuntimeError("The production rate limiting service is unavailable") from exc
    application.state.rate_limiter = redis_client
    try:
        yield
    finally:
        if redis_client:
            await redis_client.aclose()


app = FastAPI(title="AgentDock API", version="0.1.0", description="Curated, on-demand skills for AI coding agents.",
              openapi_url="/api/openapi.json", docs_url="/api/docs", redoc_url=None, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                   allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"], allow_headers=["Authorization", "Content-Type", "Mcp-Session-Id", "MCP-Protocol-Version"])


@app.middleware("http")
async def cache_control(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/assets/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif path == "/" or path.endswith(".html"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response
_request_times: dict[str, deque[float]] = defaultdict(deque)
_auth_request_times: dict[str, deque[float]] = defaultdict(deque)
_local_limit_calls = 0
_RATE_LIMIT_SCRIPT = "local count=redis.call('INCR',KEYS[1]); if count==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end; return count"


def _client_identifier(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    try:
        peer_ip = ipaddress.ip_address(peer)
        trusted_networks = [ipaddress.ip_network(value.strip(), strict=False)
                            for value in settings.trusted_proxies.split(",") if value.strip()]
    except ValueError:
        return peer
    if not any(peer_ip in network for network in trusted_networks):
        return str(peer_ip)
    chain = []
    for value in request.headers.get("x-forwarded-for", "").split(","):
        try:
            chain.append(ipaddress.ip_address(value.strip()))
        except ValueError:
            continue
    chain.append(peer_ip)
    position = len(chain) - 1
    while position > 0 and any(chain[position] in network for network in trusted_networks):
        position -= 1
    return str(chain[position])


async def _rate_limit_hit(request: Request, scope: str, limit: int, window_seconds: int = 60) -> bool | None:
    global _local_limit_calls
    client = _client_identifier(request)
    redis_client = getattr(request.app.state, "rate_limiter", None)
    if redis_client:
        window = int(time.time()) // window_seconds
        key = f"agentdock:rate:{scope}:{client}:{window}"
        try:
            return int(await redis_client.eval(_RATE_LIMIT_SCRIPT, 1, key, window_seconds)) <= limit
        except Exception:
            logger.exception("Shared request limiter is unavailable")
            return None
    if settings.env == "production":
        return None
    mapping = _auth_request_times if scope == "auth" else _request_times
    now = time.monotonic()
    bucket = mapping[client]
    while bucket and bucket[0] < now - window_seconds:
        bucket.popleft()
    allowed = len(bucket) < limit
    if allowed:
        bucket.append(now)
    _local_limit_calls += 1
    if _local_limit_calls % 256 == 0:
        for records in (_request_times, _auth_request_times):
            for address, recent in list(records.items()):
                while recent and recent[0] < now - window_seconds:
                    recent.popleft()
                if not recent:
                    records.pop(address, None)
    return allowed


@app.middleware("http")
async def request_safety(request: Request, call_next):
    overall_allowed = await _rate_limit_hit(request, "all", settings.request_rate_limit_per_minute)
    if overall_allowed is None:
        return JSONResponse(status_code=503, content={"detail": "Request protection is temporarily unavailable."})
    if not overall_allowed:
        return JSONResponse(status_code=429, content={"detail": "Too many requests. Please try again shortly."}, headers={"Retry-After": "60"})
    if request.url.path in {"/api/v1/auth/login", "/api/v1/auth/register", "/api/v1/auth/token",
                            "/api/v1/auth/forgot-password", "/api/v1/auth/reset-password"}:
        auth_allowed = await _rate_limit_hit(request, "auth", settings.auth_rate_limit_per_minute)
        if auth_allowed is None:
            return JSONResponse(status_code=503, content={"detail": "Request protection is temporarily unavailable."})
        if not auth_allowed:
            return JSONResponse(status_code=429, content={"detail": "Too many sign-in attempts. Wait a minute and try again."}, headers={"Retry-After": "60"})
    if ((request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.url.path.startswith("/api/")) or request.url.path == "/mcp"):
        origin = request.headers.get("origin")
        if origin and origin not in settings.cors_origins:
            return JSONResponse(status_code=403, content={"detail": "Request origin is not allowed"})
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    policy = "default-src 'self'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'; connect-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com"
    if request.url.path == "/api/docs":
        # FastAPI's interactive docs load their bundle and stylesheet from jsDelivr
        # and include a small inline initializer. Keep that exception on this page.
        policy = "default-src 'self'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'; connect-src 'self'; img-src 'self' data: https://fastapi.tiangolo.com; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; font-src 'self' https://cdn.jsdelivr.net"
    response.headers["Content-Security-Policy"] = policy
    if settings.env == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api/") else "public, max-age=60"
    return response


def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def user_data(user: User) -> dict:
    return {"id": user.id, "email": user.email, "name": user.name, "role": user.role,
            "email_verified": bool(user.email_verified_at), "created_at": user.created_at,
            "last_login_at": user.last_login_at}


def audit(db: Session, actor: User | None, action: str, target_type: str = "", target_id: str = "", details: dict | None = None):
    db.add(AuditLog(actor_id=actor.id if actor else None, action=action, target_type=target_type,
                    target_id=target_id, details=details or {}))


def queue_import_batch(db: Session, admin: User, sources: list[ImportSourceInput]) -> dict:
    if len(sources) > settings.max_import_sources_per_batch:
        raise HTTPException(status_code=413, detail=f"A batch can contain at most {settings.max_import_sources_per_batch} repositories")
    selected_total = sum(len(source.skill_paths) for source in sources)
    if selected_total > settings.max_selected_skills_per_batch:
        raise HTTPException(status_code=413, detail=f"A batch can select at most {settings.max_selected_skills_per_batch} skill folders")
    prepared = []
    seen_urls = set()
    for source in sources:
        owner, repo_name, canonical = parse_repo_url(source.repository_url)
        if canonical in seen_urls:
            raise HTTPException(status_code=422, detail=f"List each repository once per batch: {canonical}")
        seen_urls.add(canonical)
        prepared.append((owner, repo_name, canonical, source))

    batch = ImportBatch(submitted_by=admin.id, source_count=len(prepared), status="queued")
    db.add(batch)
    db.flush()
    for owner, repo_name, canonical, source in prepared:
        values = {"url": canonical, "owner": owner, "name": repo_name,
                  "community": source.community.strip()[:120]}
        dialect = db.get_bind().dialect.name
        if dialect == "postgresql":
            statement = pg_insert(Repository).values(**values).on_conflict_do_nothing(index_elements=[Repository.url])
        elif dialect == "sqlite":
            statement = sqlite_insert(Repository).values(**values).on_conflict_do_nothing(index_elements=[Repository.url])
        else:
            raise HTTPException(status_code=503, detail="Concurrent-safe imports require PostgreSQL or SQLite")
        db.execute(statement)
        repository = db.scalar(select(Repository).where(Repository.url == canonical).with_for_update())
        if not repository:
            raise HTTPException(status_code=503, detail="Could not register the repository for import")
        if repository.status == "excluded":
            raise HTTPException(status_code=409, detail=f"Repository is excluded: {canonical}")
        active_job = db.scalar(select(SynchronizationJob.id).where(
            SynchronizationJob.repository_id == repository.id,
            SynchronizationJob.status.in_(["queued", "running"])).limit(1))
        if active_job:
            raise HTTPException(status_code=409, detail=f"Repository already has queued or running work: {canonical}")
        db.add(SynchronizationJob(batch_id=batch.id, repository_id=repository.id,
                                  operation="import", source_url=canonical,
                                  skill_paths=source.skill_paths, community=source.community.strip()[:120],
                                  progress_total=len(source.skill_paths), status="queued"))
    audit(db, admin, "import_batch.queued", "import_batch", batch.id,
          {"repositories": len(prepared), "selected_skill_folders": selected_total})
    db.commit()
    return {"id": batch.id, "status": batch.status, "source_count": batch.source_count,
            "selected_skill_folders": selected_total, "created_at": batch.created_at}


def import_batch_data(db: Session, batch: ImportBatch) -> dict:
    jobs = db.scalars(select(SynchronizationJob).where(
        SynchronizationJob.batch_id == batch.id).order_by(SynchronizationJob.created_at)).all()
    succeeded = sum(job.status == "succeeded" for job in jobs)
    failed = sum(job.status in {"failed", "source_unavailable"} and job.next_retry_at is None for job in jobs)
    retrying = any(job.status == "failed" and job.next_retry_at is not None for job in jobs)
    active = any(job.status in {"queued", "running"} for job in jobs) or retrying
    status = ("running" if any(job.status == "running" for job in jobs) else "queued") if active else (
        "partial_failure" if failed and succeeded else "failed" if failed else "succeeded")
    return {"id": batch.id, "status": status, "source_count": len(jobs),
            "completed_count": succeeded + failed, "failed_count": failed,
            "created_at": batch.created_at, "completed_at": batch.completed_at,
            "jobs": [{"id": job.id, "repository_url": job.source_url,
                      "community": job.community, "status": job.status,
                      "attempt_count": job.attempt_count, "progress_current": job.progress_current,
                      "progress_total": job.progress_total, "result_count": job.result_count,
                      "error": job.error, "created_at": job.created_at,
                      "completed_at": job.completed_at} for job in jobs]}


def skill_search_query(db: Session, q: str = "", category: str | None = None,
                       community: str | None = None):
    statement = select(Skill, Repository).outerjoin(Repository, Skill.repository_id == Repository.id).where(
        Skill.status == "approved")
    if category:
        statement = statement.where(Skill.category == category)
    if community:
        statement = statement.where(func.lower(Skill.community) == community.strip().lower())
    rank = None
    query = q.strip()[:120]
    if query:
        terms = list(dict.fromkeys(re.findall(r"[\w]+", query, flags=re.UNICODE)))[:8] or [query]
        escaped_query = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        phrase_pattern = f"%{escaped_query}%"
        if db.get_bind().dialect.name == "postgresql":
            empty_text = literal_column("''")
            document_text = (func.coalesce(Skill.name, empty_text) + literal_column("' '") +
                             func.coalesce(Skill.description, empty_text) + literal_column("' '") +
                             func.coalesce(Skill.category, empty_text) + literal_column("' '") +
                             func.coalesce(Skill.creator, empty_text) + literal_column("' '") +
                             func.coalesce(Skill.community, empty_text))
            text_config = literal_column("'simple'::regconfig")
            document = func.to_tsvector(text_config, document_text)
            # OR semantics make ordinary multiword searches useful when the
            # catalogue uses different terminology for the same skill.
            parsed = func.websearch_to_tsquery(text_config, " OR ".join(terms))
            statement = statement.where(document.op("@@")(parsed))
            rank = func.ts_rank_cd(document, parsed) + case(
                (Skill.name.ilike(phrase_pattern, escape="\\"), 16), else_=0)
        else:
            terms = [term for term in terms if len(term) > 1] or [query]
            expressions = [or_(Skill.name.ilike(f"%{term}%"), Skill.description.ilike(f"%{term}%"),
                               Skill.category.ilike(f"%{term}%"), Skill.creator.ilike(f"%{term}%"),
                               Skill.community.ilike(f"%{term}%"))
                           for term in terms]
            if expressions:
                statement = statement.where(or_(*expressions))
            rank = sum((case((Skill.name.ilike(f"%{term}%"), 4),
                             (Skill.description.ilike(f"%{term}%"), 2),
                             (Skill.creator.ilike(f"%{term}%"), 1), else_=0)
                        for term in terms), 0) + case(
                            (Skill.name.ilike(phrase_pattern, escape="\\"), 16), else_=0)
    return statement, rank


def get_skill(db: Session, identifier: str) -> Skill:
    skill = db.scalar(select(Skill).where((Skill.id == identifier) | (Skill.slug == identifier)))
    if not skill or skill.status != "approved":
        raise HTTPException(status_code=404, detail="Skill not found")
    return skill


def skill_data(skill: Skill, repository: Repository | None = None) -> dict:
    result = {"id": skill.id, "slug": skill.slug, "name": skill.name, "description": skill.description,
              "category": skill.category, "creator": skill.creator, "license": skill.license_id,
              "source_url": skill.source_url, "stars": skill.stars, "score": skill.score,
              "verified": skill.status == "approved", "status": skill.status,
              "security_status": skill.security_status, "version": skill.latest_version,
              "premium": skill.is_premium, "community": skill.community or (repository.community if repository else ""),
              "updated_at": skill.updated_at,
              "repository": repository.url if repository else skill.source_url}
    return result


def must_have_license(skill: Skill):
    from .admission import REDISTRIBUTION_LICENSES
    if skill.license_id not in REDISTRIBUTION_LICENSES:
        raise HTTPException(status_code=422, detail="This skill cannot be distributed without a verified redistribution licence")


def get_version(db: Session, skill: Skill, version: str | None) -> SkillVersion:
    query = select(SkillVersion).where(SkillVersion.skill_id == skill.id)
    if version:
        query = query.where(SkillVersion.version == version)
    else:
        query = query.order_by(SkillVersion.created_at.desc())
    item = db.scalar(query)
    if not item:
        raise HTTPException(status_code=404, detail="Skill version not found")
    return item


def startup():
    try:
        [ipaddress.ip_network(value.strip(), strict=False)
         for value in settings.trusted_proxies.split(",") if value.strip()]
    except ValueError as exc:
        raise RuntimeError("AGENTDOCK_TRUSTED_PROXIES must contain valid IP addresses or CIDR ranges") from exc
    if settings.env == "production" and len(settings.secret_key) < 32:
        raise RuntimeError("Set AGENTDOCK_SECRET_KEY to a random value of at least 32 characters")
    if settings.env == "production":
        public_url = urlparse(settings.public_url)
        if public_url.scheme != "https" or not public_url.netloc:
            raise RuntimeError("Production requires AGENTDOCK_PUBLIC_URL to use HTTPS")
        if not settings.session_secure_cookie:
            raise RuntimeError("Production requires AGENTDOCK_SESSION_SECURE_COOKIE=true")
        if any(urlparse(origin).scheme != "https" for origin in settings.cors_origins):
            raise RuntimeError("Production browser origins must all use HTTPS")
    if bool(settings.admin_email) != bool(settings.admin_password):
        raise RuntimeError("Set both AGENTDOCK_ADMIN_EMAIL and AGENTDOCK_ADMIN_PASSWORD for bootstrap")
    if settings.admin_password and len(settings.admin_password) < 12:
        raise RuntimeError("AGENTDOCK_ADMIN_PASSWORD must contain at least 12 characters")
    if settings.env != "production":
        Base.metadata.create_all(bind=engine)
    if not settings.s3_bucket:
        settings.storage_path.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as db:
        existing_admin = db.scalar(select(User).where(User.role.in_(["admin", "super_admin"])))
        if settings.env == "production" and not existing_admin and not settings.admin_email:
            raise RuntimeError("Configure an initial administrator before production startup")
        if settings.admin_email and settings.admin_password:
            configured_admin = db.scalar(select(User).where(User.email == settings.admin_email.lower()))
            if configured_admin is None:
                db.add(User(email=settings.admin_email.lower(), password_hash=password_hash(settings.admin_password), role="admin"))
                db.commit()
            elif existing_admin is None and configured_admin.role not in {"admin", "super_admin"}:
                if not configured_admin.is_active:
                    raise RuntimeError("The configured administrator account is inactive; reactivate it before bootstrap")
                if not verify_password(settings.admin_password, configured_admin.password_hash):
                    raise RuntimeError("The configured administrator already exists; its password must match the existing account to grant administrator access")
                configured_admin.role = "admin"
                db.commit()
        if settings.seed_library:
            from .seed import seed_library
            try:
                seed_library(db)
            except Exception as exc:
                db.rollback()
                logger.warning("Starter library seeding skipped (%s)", type(exc).__name__)


@app.get("/api/health")
async def health(request: Request, db: Session = Depends(db_session)):
    try:
        await run_in_threadpool(db.execute, select(1))
    except Exception as exc:
        logger.error("Health check database failure: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Database unavailable")
    redis_client = getattr(request.app.state, "rate_limiter", None)
    if redis_client:
        try:
            await redis_client.ping()
        except Exception as exc:
            logger.error("Health check request limiter failure: %s", type(exc).__name__)
            raise HTTPException(status_code=503, detail="Request protection unavailable")
    return {"status": "ok", "service": "agentdock", "database": "ok",
            "request_limiter": "ok" if redis_client else "development_fallback"}


@app.post("/api/v1/auth/register", status_code=201)
def register(payload: RegisterInput, response: Response, request: Request, db: Session = Depends(db_session)):
    email = str(payload.email).lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="An account with that email already exists")
    user = User(email=email, password_hash=password_hash(payload.password), role="free",
                name=payload.name.strip()[:120])
    db.add(user)
    db.flush()
    token = create_session(db, user)
    if not db.scalar(select(Collection).where(Collection.user_id == user.id)):
        db.add(Collection(user_id=user.id, name="Favorites", description="Your saved skills"))
    verification_token = create_email_token(db, user, "verify_email", 24 * 60)
    audit(db, user, "account.registered", "user", user.id)
    db.commit()
    link = f"{public_base_url(request)}/#/verify-email?token={verification_token}"
    sent = mailer.send_verification(user.email, link)
    response.set_cookie("agentdock_session", token, httponly=True, secure=settings.session_secure_cookie,
                        samesite="lax", max_age=settings.session_days * 86400, path="/")
    debug_link = None if settings.production or settings.smtp_configured else link
    return {"user": user_data(user), "email_verification": "sent" if sent else "pending_configuration",
            "debug_verification_link": debug_link,
            "message": "Check your inbox to verify your email address." if sent else
                       "Email delivery is not configured yet; an administrator can verify your account."}


@app.post("/api/v1/auth/login")
def login(payload: LoginInput, response: Response, db: Session = Depends(db_session)):
    user = db.scalar(select(User).where(User.email == str(payload.email).lower()))
    if not user or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email or password is incorrect")
    if (settings.require_email_verification and settings.smtp_configured
            and not user.email_verified_at and user.role not in {"admin", "super_admin"}):
        raise HTTPException(status_code=403, detail="Verify your email address before signing in")
    token = create_session(db, user)
    db.commit()
    response.set_cookie("agentdock_session", token, httponly=True, secure=settings.session_secure_cookie,
                        samesite="lax", max_age=settings.session_days * 86400, path="/")
    return {"user": user_data(user)}


@app.post("/api/v1/auth/logout")
def logout(request: Request, response: Response, db: Session = Depends(db_session)):
    raw = request.cookies.get("agentdock_session")
    if raw:
        session = db.get(UserSession, hashlib.sha256(raw.encode()).hexdigest())
        if session:
            db.delete(session)
            db.commit()
    response.delete_cookie("agentdock_session", path="/", httponly=True, secure=settings.session_secure_cookie, samesite="lax")
    return {"ok": True}


@app.get("/api/v1/auth/me")
def me(request: Request, db: Session = Depends(db_session)):
    return {"user": user_data(current_user(request, db))}


@app.post("/api/v1/auth/token")
def create_token(payload: LoginInput, db: Session = Depends(db_session)):
    user = db.scalar(select(User).where(User.email == str(payload.email).lower()))
    if not user or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email or password is incorrect")
    token = issue_api_key(db, user, "API access token")
    db.commit()
    return {"access_token": token, "token_type": "Bearer", "warning": "This token is shown once. Store it securely."}


@app.get("/api/v1/auth/api-keys")
def list_api_keys(request: Request, db: Session = Depends(db_session)):
    user = current_user(request, db, allow_key=False)
    items = db.scalars(select(APIKey).where(APIKey.user_id == user.id, APIKey.revoked_at.is_(None)).order_by(APIKey.created_at.desc())).all()
    return {"items": [{"id": x.id, "name": x.name, "prefix": x.prefix, "scopes": x.scopes,
                        "created_at": x.created_at, "last_used_at": x.last_used_at} for x in items]}


@app.post("/api/v1/auth/api-keys", status_code=201)
def create_key(payload: APIKeyInput, request: Request, db: Session = Depends(db_session)):
    user = current_user(request, db, allow_key=False)
    token = issue_api_key(db, user, payload.name, payload.scopes)
    db.flush()
    key_id = db.scalar(select(APIKey.id).where(APIKey.key_hash == hashlib.sha256(token.encode()).hexdigest()))
    db.commit()
    return {"api_key": token, "key_id": key_id, "warning": "Copy this key now. It will not be shown again."}


@app.delete("/api/v1/auth/api-keys/{key_id}")
def revoke_key(key_id: str, request: Request, db: Session = Depends(db_session)):
    user = current_user(request, db, allow_key=False)
    item = db.scalar(select(APIKey).where(APIKey.id == key_id, APIKey.user_id == user.id, APIKey.revoked_at.is_(None)))
    if not item:
        raise HTTPException(status_code=404, detail="API key not found")
    item.revoked_at = utcnow()
    audit(db, user, "api_key.revoked", "api_key", item.id)
    db.commit()
    return {"ok": True}


@app.get("/api/v1/skills")
@app.get("/api/v1/skills/search")
def search_skills(request: Request, q: str = "", category: str | None = None, community: str | None = None,
                 verified: bool | None = None,
                 limit: int = 20, offset: int = 0, db: Session = Depends(db_session)):
    user = optional_user(request, db)
    source = request_source(request)
    if not 1 <= limit <= 50 or offset < 0:
        record_failure(db, user, "search_failed", source, {"reason": "invalid pagination"})
        raise HTTPException(status_code=422, detail="Use limit 1–50 and a non-negative offset")
    try:
        statement, rank = skill_search_query(db, q, category, community)
        if verified is True:
            statement = statement.where(Skill.score >= 75)
        total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
        order = [rank.desc()] if rank is not None else []
        rows = db.execute(statement.order_by(*order, Skill.score.desc(), Skill.stars.desc(),
                                             Skill.updated_at.desc()).offset(offset).limit(limit)).all()
    except Exception as exc:
        db.rollback()
        record_failure(db, user, "search_failed", source, {"error": str(exc)[:200], "query": q[:120]})
        raise
    if user:
        record_usage(db, user, None, "search_executed", source, details={"query": q[:120]})
        db.commit()
    return {"items": [enrich_skill(db, skill, repo) for skill, repo in rows], "total": total,
            "limit": limit, "offset": offset}


@app.get("/api/v1/skills/discovery")
def discover_skills(request: Request, track: bool = True, db: Session = Depends(db_session)):
    user = optional_user(request, db)
    source = request_source(request)
    approved = Skill.status == "approved"
    def top_skills(*ordering):
        rows = db.execute(select(Skill, Repository).outerjoin(Repository, Skill.repository_id == Repository.id)
                          .where(approved).order_by(*ordering).limit(4)).all()
        return [skill_data(skill, repository) for skill, repository in rows]

    popular = top_skills(Skill.stars.desc(), Skill.score.desc(), Skill.updated_at.desc())
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    trending_rows = db.execute(
        select(Skill, Repository, func.count(UsageEvent.id).label("retrievals"))
        .join(UsageEvent, UsageEvent.skill_id == Skill.id)
        .outerjoin(Repository, Skill.repository_id == Repository.id)
        .where(approved, Skill.community != "", UsageEvent.event == "skill.retrieved", UsageEvent.created_at >= cutoff)
        .group_by(Skill.id, Repository.id)
        .having(func.count(func.distinct(UsageEvent.user_id)) >= 3)
        .order_by(func.count(UsageEvent.id).desc(), Skill.score.desc(), Skill.updated_at.desc())
        .limit(20)
    ).all()
    trending_community = []
    seen_communities = set()
    for skill, repository, retrievals in trending_rows:
        community = skill.community or (repository.community if repository else "")
        if community and community not in seen_communities:
            seen_communities.add(community)
            trending_community.append({"community": community, "skill": skill_data(skill, repository),
                                       "retrievals_7d": retrievals})
        if len(trending_community) == 4:
            break
    community_picks = []
    seen_communities.clear()
    for skill in popular:
        community = skill.get("community")
        if community and community not in seen_communities:
            seen_communities.add(community)
            community_picks.append(skill)
        if len(community_picks) == 4:
            break
    payload = {
        "recommended": top_skills(Skill.score.desc(), Skill.stars.desc(), Skill.updated_at.desc()),
        "popular": popular,
        "recently_updated": top_skills(Skill.updated_at.desc(), Skill.score.desc()),
        "trending_community": trending_community,
        "community_picks": community_picks,
        "trend_window_days": 7,
    }
    if user and track:
        record_usage(db, user, None, "discovery_executed", source)
        db.commit()
    return payload


@app.get("/api/v1/categories")
def categories(db: Session = Depends(db_session)):
    rows = db.execute(select(Skill.category, func.count(Skill.id)).where(Skill.status == "approved").group_by(Skill.category).order_by(Skill.category)).all()
    return {"items": [{"name": name, "count": count} for name, count in rows]}


@app.get("/api/v1/communities")
def communities(db: Session = Depends(db_session)):
    rows = db.execute(select(Skill.community, func.count(Skill.id)).where(
        Skill.status == "approved", Skill.community != "").group_by(Skill.community).order_by(Skill.community)).all()
    return {"items": [{"name": name, "count": count} for name, count in rows]}


@app.get("/api/v1/skills/{identifier}")
def skill_detail(identifier: str, db: Session = Depends(db_session)):
    item = get_skill(db, identifier)
    repo = db.get(Repository, item.repository_id) if item.repository_id else None
    return enrich_skill(db, item, repo)


@app.post("/api/v1/skills/{identifier}/retrieve")
def retrieve_skill(identifier: str, request: Request, db: Session = Depends(db_session)):
    user = current_user(request, db)
    require_scope(request, "skills:read")
    source = request_source(request)
    skill = None
    try:
        skill = get_skill(db, identifier)
        must_have_license(skill)
        if skill.is_premium and not premium_entitlement(db, user, skill):
            raise HTTPException(status_code=402, detail="Purchase this skill to retrieve it")
        version = get_version(db, skill, None)
        try:
            instructions = read_resource(version.snapshot_path, "SKILL.md").decode("utf-8", errors="replace")
        except (ValueError, FileNotFoundError):
            raise HTTPException(status_code=503, detail="Skill snapshot is unavailable")
    except HTTPException as exc:
        record_failure(db, user, "retrieve_failed", source,
                       {"identifier": identifier[:120], "error": str(exc.detail)[:200]})
        raise
    except Exception as exc:
        db.rollback()
        record_failure(db, user, "retrieve_failed", source,
                       {"identifier": identifier[:120], "error": str(exc)[:200]})
        raise
    record_usage(db, user, skill, "skill.retrieved", source)
    db.commit()
    skill_result = enrich_skill(db, skill, db.get(Repository, skill.repository_id) if skill.repository_id else None)
    skill_result["instructions"] = instructions
    return {"skill": skill_result, "version": version.version,
            "version_hash": version.content_hash, "source_commit": version.source_commit,
            "resource_manifest": version.manifest, "attribution": {"creator": skill.creator, "source": skill.source_url, "license": skill.license_id}}


@app.get("/api/v1/skills/{identifier}/versions")
def skill_versions(identifier: str, db: Session = Depends(db_session)):
    skill = get_skill(db, identifier)
    versions = db.scalars(select(SkillVersion).where(SkillVersion.skill_id == skill.id).order_by(SkillVersion.created_at.desc())).all()
    return {"items": [{"version": v.version, "source_commit": v.source_commit, "version_hash": v.content_hash,
                        "files": len(v.manifest), "created_at": v.created_at} for v in versions]}


@app.get("/api/v1/skills/{identifier}/resources")
def skill_resources(identifier: str, request: Request, version: str | None = None,
                    db: Session = Depends(db_session)):
    skill = get_skill(db, identifier)
    user = optional_user(request, db)
    if skill.is_premium and (user is None or not premium_entitlement(db, user, skill)):
        raise HTTPException(status_code=402, detail="Purchase this skill to retrieve it")
    item = get_version(db, skill, version)
    return {"skill_id": skill.id, "version": item.version, "items": item.manifest}


@app.get("/api/v1/skills/{identifier}/resources/{resource_path:path}")
def skill_resource(identifier: str, resource_path: str, request: Request, version: str | None = None,
                   db: Session = Depends(db_session)):
    skill = get_skill(db, identifier)
    must_have_license(skill)
    user = optional_user(request, db)
    if skill.is_premium and (user is None or not premium_entitlement(db, user, skill)):
        raise HTTPException(status_code=402, detail="Purchase this skill to retrieve it")
    item = get_version(db, skill, version)
    try:
        content = read_resource(item.snapshot_path, resource_path)
    except (ValueError, FileNotFoundError):
        raise HTTPException(status_code=404, detail="Skill resource not found")
    from fastapi.responses import Response as RawResponse
    return RawResponse(content, media_type="text/plain; charset=utf-8", headers={"ETag": f'"{hashlib.sha256(content).hexdigest()}"'})


def _execution_job_data(job: ExecutionJob) -> dict:
    return {
        "id": job.id, "skill_id": job.skill_id, "version": job.version,
        "version_hash": job.version_hash, "command": job.command, "arguments": job.arguments,
        "status": job.status, "stdout": job.stdout, "stderr": job.stderr,
        "error": job.error, "exit_code": job.exit_code, "sandbox": job.sandbox,
        "created_at": job.created_at, "started_at": job.started_at, "completed_at": job.completed_at,
    }


def _package_payload(db: Session, package: dict) -> dict:
    version = package["version"]
    return {
        "skill": {"id": package["skill"].id, "slug": package["skill"].slug, "name": package["skill"].name,
                  "license": package["skill"].license_id, "source_url": package["skill"].source_url},
        "version": version.version, "version_hash": version.content_hash,
        "source_commit": version.source_commit, "workspace_path": package["workspace_path"],
        "manifest": package["manifest"], "groups": package["groups"],
        "statistics_bundle_coverage": package.get("statistics_bundle_coverage", {}),
        "immutable": True,
    }


@app.get("/api/v1/skills/{identifier}/package")
def skill_package(identifier: str, request: Request, version: str | None = None,
                  db: Session = Depends(db_session)):
    user = current_user(request, db)
    require_scope(request, "skills:read")
    try:
        return _package_payload(db, execution_routes.resolve_package(db, identifier, version, user))
    except execution_routes.ExecutionError as error:
        message = str(error)
        status = 402 if "Purchase" in message else 403 if "approved" in message or "allow-list" in message else 404
        raise HTTPException(status_code=status, detail=message)


@app.get("/api/v1/skills/{identifier}/package.zip")
def skill_package_zip(identifier: str, request: Request, version: str | None = None,
                      db: Session = Depends(db_session)):
    user = current_user(request, db)
    require_scope(request, "skills:read")
    try:
        package = execution_routes.resolve_package(db, identifier, version, user)
    except execution_routes.ExecutionError as error:
        message = str(error)
        status = 402 if "Purchase" in message else 403 if "approved" in message else 404
        raise HTTPException(status_code=status, detail=message)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for entry in package["manifest"]:
            path = execution_routes.safe_relative_path(entry["path"])
            content = read_resource(package["version"].snapshot_path, path)
            if hashlib.sha256(content).hexdigest() != entry["sha256"]:
                raise HTTPException(status_code=500, detail=f"Snapshot hash mismatch for {path}")
            archive.writestr(f"{package['workspace_path']}/{path}", content)
    record_usage(db, user, None, "package.downloaded", source=request_source(request),
                 details={"skill_id": package["skill"].id, "version": package["version"].version,
                          "files": len(package["manifest"])})
    db.commit()
    filename = f"{package['skill'].slug}-{package['version'].version}.zip"
    return Response(buffer.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"',
                             "X-AgentDock-Version": package["version"].version,
                             "X-AgentDock-Version-Hash": package["version"].content_hash})


@app.get("/api/v1/skills/{identifier}/package/requirements")
def skill_package_requirements(identifier: str, request: Request, version: str | None = None,
                               db: Session = Depends(db_session)):
    user = current_user(request, db)
    require_scope(request, "skills:read")
    try:
        package = execution_routes.resolve_package(db, identifier, version, user)
        return execution_routes.detect_requirements(package["manifest"], package["version"].snapshot_path)
    except execution_routes.ExecutionError as error:
        raise HTTPException(status_code=402 if "Purchase" in str(error) else 403, detail=str(error))


@app.post("/api/v1/executions", status_code=202)
def create_execution(payload: ExecutionInput, request: Request, db: Session = Depends(db_session)):
    user = current_user(request, db)
    require_scope(request, "execution:run")
    if not settings.execution_enabled:
        raise HTTPException(status_code=503, detail="Skill execution is disabled on this deployment")
    if payload.team_id and not db.scalar(select(TeamMember.id).where(
            TeamMember.team_id == payload.team_id, TeamMember.user_id == user.id)):
        raise HTTPException(status_code=403, detail="You are not a member of that team")
    try:
        package = execution_routes.resolve_package(db, payload.skill, payload.version or None, user)
        execution_routes.assert_execution_allowed(package["skill"])
    except execution_routes.ExecutionError as error:
        raise HTTPException(status_code=402 if "Purchase" in str(error) else 403, detail=str(error))
    manifest_paths = {entry["path"] for entry in package["manifest"]}
    script = execution_routes.normalize_package_path(package, payload.arguments[0] if payload.arguments else "")
    if not script or script not in manifest_paths:
        raise HTTPException(status_code=422, detail="arguments[0] must be a script path from the approved package")
    arguments = [script, *payload.arguments[1:]]
    job = ExecutionJob(
        user_id=user.id, team_id=payload.team_id, skill_id=package["skill"].id,
        version=package["version"].version, version_hash=package["version"].content_hash,
        command=payload.command, arguments=arguments, status="queued",
    )
    db.add(job)
    record_usage(db, user, None, "execution.requested", source="api",
                 details={"skill_id": package["skill"].id, "version": package["version"].version,
                          "script": script})
    db.commit()
    return _execution_job_data(job)


@app.get("/api/v1/executions")
def list_executions(request: Request, limit: int = 20, offset: int = 0, db: Session = Depends(db_session)):
    user = current_user(request, db)
    require_scope(request, "execution:run")
    rows = db.scalars(select(ExecutionJob).where(ExecutionJob.user_id == user.id)
                      .order_by(ExecutionJob.created_at.desc()).offset(max(0, offset)).limit(min(max(limit, 1), 100))).all()
    return {"items": [_execution_job_data(row) for row in rows]}


@app.get("/api/v1/executions/{job_id}")
def get_execution(job_id: str, request: Request, db: Session = Depends(db_session)):
    user = current_user(request, db)
    require_scope(request, "execution:run")
    job = db.get(ExecutionJob, job_id)
    if not job or job.user_id != user.id:
        raise HTTPException(status_code=404, detail="Execution not found")
    return _execution_job_data(job)


@app.post("/api/v1/executions/{job_id}/cancel")
def cancel_execution(job_id: str, request: Request, db: Session = Depends(db_session)):
    user = current_user(request, db)
    require_scope(request, "execution:run")
    job = db.get(ExecutionJob, job_id)
    if not job or job.user_id != user.id:
        raise HTTPException(status_code=404, detail="Execution not found")
    if job.status in {"succeeded", "failed", "canceled"}:
        raise HTTPException(status_code=409, detail="Execution is already finished")
    job.status = "canceled"
    job.completed_at = utcnow()
    job.error = "Canceled by user"
    db.commit()
    return _execution_job_data(job)


@app.get("/api/v1/user/library")
def library(request: Request, db: Session = Depends(db_session)):
    user = current_user(request, db)
    require_scope(request, "library:read")
    collection = db.scalar(select(Collection).where(Collection.user_id == user.id).order_by(Collection.created_at).limit(1))
    if not collection:
        collection = Collection(user_id=user.id, name="Favorites")
        db.add(collection)
        db.commit()
    rows = db.execute(select(Skill, Repository).join(CollectionItem, CollectionItem.skill_id == Skill.id)
                      .outerjoin(Repository, Skill.repository_id == Repository.id)
                      .where(CollectionItem.collection_id == collection.id, Skill.status == "approved")
                      .order_by(CollectionItem.added_at.desc())).all()
    return {"collection": collection.name, "items": [skill_data(s, r) for s, r in rows]}


@app.get("/api/v1/user/vault")
def user_vault(request: Request, db: Session = Depends(db_session)):
    user = current_user(request, db)
    require_scope(request, "library:read")
    collection = db.scalar(select(Collection).where(Collection.user_id == user.id).order_by(Collection.created_at).limit(1))
    if not collection:
        return {"summary": {"archived_skills": 0, "available_versions": 0, "last_sync_at": None,
                            "last_known_available": 0, "upstream_unavailable": 0, "verified_skills": 0}, "items": []}
    version_counts = (select(SkillVersion.skill_id.label("skill_id"), func.count(SkillVersion.id).label("version_count"))
                      .group_by(SkillVersion.skill_id).subquery())
    rows = db.execute(
        select(Skill, Repository, func.coalesce(version_counts.c.version_count, 0))
        .join(CollectionItem, CollectionItem.skill_id == Skill.id)
        .outerjoin(Repository, Skill.repository_id == Repository.id)
        .outerjoin(version_counts, version_counts.c.skill_id == Skill.id)
        .where(CollectionItem.collection_id == collection.id, Skill.status == "approved")
        .order_by(CollectionItem.added_at.desc())
    ).all()
    items = []
    for skill, repository, version_count in rows:
        upstream_status = ("unavailable" if repository and repository.status == "source_unavailable" else
                           "not_checked" if not repository or not repository.last_sync_at else "last_known_available")
        item = skill_data(skill, repository)
        item.update({"version_count": int(version_count or 0), "last_sync_at": repository.last_sync_at if repository else None,
                     "upstream_status": upstream_status,
                     "verification_status": "verified" if skill.security_status == "clear" and skill.status == "approved" else "review_needed"})
        items.append(item)
    sync_dates = [item["last_sync_at"] for item in items if item["last_sync_at"]]
    summary = {
        "archived_skills": sum(item["version_count"] > 0 for item in items),
        "available_versions": sum(item["version_count"] for item in items),
        "last_sync_at": max(sync_dates) if sync_dates else None,
        "last_known_available": sum(item["upstream_status"] == "last_known_available" for item in items),
        "upstream_unavailable": sum(item["upstream_status"] == "unavailable" for item in items),
        "verified_skills": sum(item["verification_status"] == "verified" for item in items),
    }
    return {"summary": summary, "items": items}


@app.post("/api/v1/user/library", status_code=201)
def save_to_library(payload: CollectionInput, request: Request, db: Session = Depends(db_session)):
    user = current_user(request, db)
    require_scope(request, "library:write")
    skill = get_skill(db, payload.skill_id)
    collection = db.scalar(select(Collection).where(Collection.user_id == user.id, Collection.name == payload.collection))
    if not collection:
        collection = Collection(user_id=user.id, name=payload.collection)
        db.add(collection)
        db.flush()
    existing = db.scalar(select(CollectionItem).where(CollectionItem.collection_id == collection.id, CollectionItem.skill_id == skill.id))
    if not existing:
        db.add(CollectionItem(collection_id=collection.id, skill_id=skill.id))
    db.commit()
    return {"ok": True, "collection": collection.name, "skill_id": skill.id}


@app.delete("/api/v1/user/library/{skill_id}")
def remove_from_library(skill_id: str, request: Request, collection_name: str = "Favorites", db: Session = Depends(db_session)):
    user = current_user(request, db)
    require_scope(request, "library:write")
    item = db.scalar(select(CollectionItem).join(Collection).where(Collection.user_id == user.id,
                         Collection.name == collection_name, CollectionItem.skill_id == skill_id))
    if item:
        db.delete(item)
        db.commit()
    return {"ok": True}


@app.get("/api/v1/account/usage")
def usage(request: Request, db: Session = Depends(db_session)):
    user = current_user(request, db)
    require_scope(request, "account:read")
    summary = entitlement_summary(db, user)
    total = db.scalar(select(func.count(UsageEvent.id)).where(
        UsageEvent.user_id == user.id, UsageEvent.event == "skill.retrieved")) or 0
    recent = db.scalars(select(UsageEvent).where(UsageEvent.user_id == user.id)
                        .order_by(UsageEvent.created_at.desc()).limit(20)).all()
    by_source = {source: count for source, count in db.execute(
        select(UsageEvent.source, func.count(UsageEvent.id)).where(
            UsageEvent.user_id == user.id, UsageEvent.event == "skill.retrieved")
        .group_by(UsageEvent.source)).all()}
    start = utcnow().date() - timedelta(days=13)
    series = {str(start + timedelta(days=index)): 0 for index in range(14)}
    for created_at in db.scalars(select(UsageEvent.created_at).where(
            UsageEvent.user_id == user.id, UsageEvent.event == "skill.retrieved",
            UsageEvent.created_at >= utcnow() - timedelta(days=14))).all():
        key = str(created_at.date())
        if key in series:
            series[key] += 1
    def event_count(event):
        return db.scalar(select(func.count(UsageEvent.id)).where(
            UsageEvent.user_id == user.id, UsageEvent.event == event)) or 0
    stats = {
        "searches_executed": event_count("search_executed"),
        "searches_failed": event_count("search_failed"),
        "discovered": event_count("discovery_executed"),
        "discovered_failed": event_count("discovery_failed"),
        "retrievals_success": total,
        "retrievals_failed": event_count("retrieve_failed"),
        "executions": event_count("mcp_executed"),
        "executions_failed": event_count("mcp_failed"),
    }
    return {"skills_retrieved": total, "plan": summary["plan_name"],
            "plan_code": summary["plan_code"], "entitlements": summary, "stats": stats,
            "by_source": by_source,
            "series": [{"date": key, "retrievals": value} for key, value in series.items()],
            "items": [{"event": event.event, "skill_id": event.skill_id,
                       "source": event.source, "created_at": event.created_at} for event in recent]}


@app.get("/api/v1/integrations")
def integrations(request: Request, db: Session = Depends(db_session)):
    user = current_user(request, db)
    require_scope(request, "account:read")
    base = public_base_url(request)
    key_count = db.scalar(select(func.count(APIKey.id)).where(
        APIKey.user_id == user.id, APIKey.revoked_at.is_(None))) or 0
    return {"items": [
        {"id": "mcp", "name": "Model Context Protocol", "status": "available",
         "endpoint": f"{base}/mcp", "connected": bool(key_count),
         "description": "Connect Claude Code, Cursor, Windsurf or any MCP-compatible agent.",
         "config": {"mcpServers": {"agentdock": {"url": f"{base}/mcp",
                                                 "headers": {"Authorization": "Bearer <your AgentDock API key>"}}}}},
        {"id": "rest", "name": "REST API", "status": "available", "endpoint": f"{base}/api/v1",
         "docs": f"{base}/api/docs", "connected": bool(key_count),
         "description": "Search, retrieve and manage skills from your own tools."},
        {"id": "cli", "name": "AgentDock CLI", "status": "available", "install": "pip install agentdock",
         "connected": bool(key_count), "description": "Search and retrieve skills from your terminal.",
         "commands": ["agentdock login", "agentdock search dashboard", "agentdock get react-analytics-dashboard --output .agent/skills"]},
        {"id": "github", "name": "GitHub discovery", "status": "available" if settings.github_token else "needs_configuration",
         "description": "Automatically discover repositories that publish agent skills.",
         "connected": bool(settings.github_token)},
    ], "api_keys": key_count}


@app.get("/api/v1/admin/overview")
def admin_overview(request: Request, db: Session = Depends(db_session)):
    admin_user(request, db)
    count = lambda model, *conds: db.scalar(select(func.count(model.id)).where(*conds)) or 0
    return {"indexed_repositories": count(Repository), "discovered_skills": count(Skill),
            "approved_skills": count(Skill, Skill.status == "approved"),
            "pending_reviews": count(Skill, Skill.status == "pending_review") + count(Skill, Skill.status == "qualified"),
            "rejected_skills": count(Skill, Skill.status == "rejected"),
            "quarantined_skills": count(Skill, Skill.status == "quarantined"),
            "users": count(User), "retrievals": count(UsageEvent, UsageEvent.event == "skill.retrieved"),
            "analytics": admin_routes._analytics(db),
            "recent_decisions": [{"skill": db.get(Skill, item.skill_id).name if db.get(Skill, item.skill_id) else "Removed skill",
                                  "decision": item.decision, "reason": item.reason, "created_at": item.created_at}
                                 for item in db.scalars(select(AdmissionDecision).order_by(AdmissionDecision.created_at.desc()).limit(8)).all()]}


@app.get("/api/v1/admin/skills")
def admin_skills(request: Request, status: str = "pending_review", db: Session = Depends(db_session)):
    admin_user(request, db)
    items = db.scalars(select(Skill).where(Skill.status == status).order_by(Skill.created_at.desc()).limit(100)).all()
    return {"items": [{**skill_data(s), "path": s.path, "source_url": s.source_url} for s in items]}


@app.get("/api/v1/admin/repositories")
def admin_repositories(request: Request, db: Session = Depends(db_session)):
    admin_user(request, db)
    items = db.scalars(select(Repository).order_by(Repository.created_at.desc()).limit(100)).all()
    return {"items": [{"id": r.id, "url": r.url, "owner": r.owner, "name": r.name, "stars": r.stars,
                        "community": r.community, "forks": r.forks, "license": r.license_id, "status": r.status, "branch": r.default_branch,
                        "last_commit_sha": r.last_commit_sha,
                        "last_sync_at": r.last_sync_at} for r in items]}


@app.post("/api/v1/admin/import-batches", status_code=202)
def admin_queue_import_batch(payload: ImportBatchInput, request: Request, db: Session = Depends(db_session)):
    admin = admin_user(request, db)
    return queue_import_batch(db, admin, payload.sources)


@app.get("/api/v1/admin/import-batches")
def admin_import_batches(request: Request, limit: int = 30, db: Session = Depends(db_session)):
    admin_user(request, db)
    batches = db.scalars(select(ImportBatch).order_by(ImportBatch.created_at.desc()).limit(min(max(limit, 1), 100))).all()
    return {"items": [import_batch_data(db, batch) for batch in batches]}


@app.get("/api/v1/admin/import-batches/{batch_id}")
def admin_import_batch(batch_id: str, request: Request, db: Session = Depends(db_session)):
    admin_user(request, db)
    batch = db.get(ImportBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Import batch not found")
    return import_batch_data(db, batch)


@app.get("/api/v1/admin/trusted-publishers")
def trusted_publishers(request: Request, db: Session = Depends(db_session)):
    admin_user(request, db)
    items = db.scalars(select(TrustedPublisher).order_by(TrustedPublisher.github_handle)).all()
    return {"items": [{"id": p.id, "github_handle": p.github_handle, "kind": p.kind,
                        "trust_level": p.trust_level, "notes": p.notes, "created_at": p.created_at}
                       for p in items]}


@app.post("/api/v1/admin/trusted-publishers", status_code=201)
def add_trusted_publisher(payload: TrustedPublisherInput, request: Request, db: Session = Depends(db_session)):
    admin = admin_user(request, db)
    handle = payload.github_handle.lower()
    existing = db.scalar(select(TrustedPublisher).where(TrustedPublisher.github_handle.ilike(handle)))
    if existing:
        raise HTTPException(status_code=409, detail="That publisher is already trusted")
    publisher = TrustedPublisher(github_handle=handle, kind=payload.kind,
                                 trust_level=payload.trust_level, notes=payload.notes)
    db.add(publisher)
    db.flush()
    audit(db, admin, "publisher.trusted", "trusted_publisher", publisher.id, {"handle": handle, "kind": payload.kind})
    db.commit()
    return {"id": publisher.id, "github_handle": publisher.github_handle,
            "kind": publisher.kind, "trust_level": publisher.trust_level}


@app.delete("/api/v1/admin/trusted-publishers/{publisher_id}")
def remove_trusted_publisher(publisher_id: str, request: Request, db: Session = Depends(db_session)):
    admin = admin_user(request, db)
    publisher = db.get(TrustedPublisher, publisher_id)
    if not publisher:
        raise HTTPException(status_code=404, detail="Trusted publisher not found")
    handle = publisher.github_handle
    db.delete(publisher)
    audit(db, admin, "publisher.untrusted", "trusted_publisher", publisher_id, {"handle": handle})
    db.commit()
    return {"ok": True}


@app.post("/api/v1/admin/repositories/{repository_id}/status")
def set_repository_status(repository_id: str, payload: RepositoryStatusInput,
                          request: Request, db: Session = Depends(db_session)):
    admin = admin_user(request, db)
    if payload.status not in {"approved", "paused", "excluded"}:
        raise HTTPException(status_code=422, detail="Choose approved, paused or excluded")
    repository = db.get(Repository, repository_id)
    if not repository:
        raise HTTPException(status_code=404, detail="Repository not found")
    if payload.status == "approved":
        statuses = db.scalars(select(Skill.status).where(Skill.repository_id == repository.id)).all()
        if not statuses or any(status != "approved" for status in statuses):
            raise HTTPException(status_code=422, detail="Review and approve every skill before resuming repository synchronization")
    previous = repository.status
    repository.status = payload.status
    if payload.status == "excluded":
        skills = db.scalars(select(Skill).where(Skill.repository_id == repository.id, Skill.status == "approved")).all()
        for skill in skills:
            skill.status = "withdrawn"
    audit(db, admin, "repository.status_changed", "repository", repository.id,
          {"from": previous, "to": payload.status, "reason": payload.reason})
    db.commit()
    return {"ok": True, "status": repository.status}


@app.post("/api/v1/admin/repositories/import", status_code=202)
def admin_import(payload: ImportInput, request: Request, db: Session = Depends(db_session)):
    admin = admin_user(request, db)
    source = ImportSourceInput(repository_url=payload.repository_url,
                               skill_paths=[payload.skill_path] if payload.skill_path else [],
                               category=payload.category, community=payload.community)
    return queue_import_batch(db, admin, [source])


@app.post("/api/v1/admin/skills/{skill_id}/decision")
def admin_decision(skill_id: str, payload: DecisionInput, request: Request, db: Session = Depends(db_session)):
    admin = admin_user(request, db)
    if payload.decision not in {"approved", "rejected", "quarantined", "withdrawn"}:
        raise HTTPException(status_code=422, detail="Choose approved, rejected, quarantined or withdrawn")
    skill = db.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    if payload.decision == "approved":
        must_have_license(skill)
        if skill.security_status != "clear":
            raise HTTPException(status_code=422, detail="A skill with security findings must be cleared before approval")
        if skill.repository_id:
            source = db.get(Repository, skill.repository_id)
            if source and source.status == "excluded":
                raise HTTPException(status_code=422, detail="An excluded repository cannot be distributed")
    previous = skill.status
    skill.status = payload.decision
    db.add(AdmissionDecision(skill_id=skill.id, actor_id=admin.id, decision=payload.decision,
                             reason=payload.reason, score=skill.score))
    audit(db, admin, "skill.admission_decided", "skill", skill.id,
          {"from": previous, "to": payload.decision, "reason": payload.reason})
    if skill.repository_id:
        repository = db.get(Repository, skill.repository_id)
        if repository:
            states = db.scalars(select(Skill.status).where(Skill.repository_id == repository.id)).all()
            repository.status = "approved" if states and all(state == "approved" for state in states) else "pending_review"
    db.commit()
    return {"ok": True, "skill_id": skill.id, "status": skill.status}


@app.post("/api/v1/admin/repositories/{repository_id}/sync", status_code=202)
def trigger_sync(repository_id: str, request: Request, db: Session = Depends(db_session)):
    admin = admin_user(request, db)
    repository = db.scalar(select(Repository).where(Repository.id == repository_id).with_for_update())
    if not repository:
        raise HTTPException(status_code=404, detail="Repository not found")
    if repository.status == "excluded":
        raise HTTPException(status_code=409, detail="An excluded repository cannot be synchronized")
    active_job = db.scalar(select(SynchronizationJob).where(
        SynchronizationJob.repository_id == repository.id,
        SynchronizationJob.status.in_(["queued", "running"])).order_by(SynchronizationJob.created_at).limit(1))
    if active_job:
        return {"job_id": active_job.id, "status": active_job.status,
                "message": "Work is already queued for this repository."}
    job = SynchronizationJob(repository_id=repository.id, source_url=repository.url,
                             operation="sync", status="queued")
    db.add(job)
    db.flush()
    audit(db, admin, "repository.sync_requested", "repository", repository.id, {"job_id": job.id})
    db.commit()
    return {"job_id": job.id, "status": job.status, "message": "The background worker will process this job."}


@app.get("/api/v1/admin/synchronization")
def synchronization_jobs(request: Request, db: Session = Depends(db_session)):
    admin_user(request, db)
    jobs = db.scalars(select(SynchronizationJob).order_by(SynchronizationJob.created_at.desc()).limit(100)).all()
    return {"items": [{"id": job.id, "repository_id": job.repository_id,
                        "repository_url": job.source_url, "operation": job.operation,
                        "batch_id": job.batch_id, "community": job.community,
                        "status": job.status, "attempt_count": job.attempt_count,
                        "progress_current": job.progress_current, "progress_total": job.progress_total,
                        "result_count": job.result_count, "error": job.error,
                        "started_at": job.started_at, "completed_at": job.completed_at,
                        "created_at": job.created_at} for job in jobs]}


@app.get("/api/v1/admin/audit-logs")
def audit_logs(request: Request, limit: int = 50, db: Session = Depends(db_session)):
    admin_user(request, db)
    items = db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(min(max(limit, 1), 100))).all()
    return {"items": [{"action": e.action, "target_type": e.target_type, "target_id": e.target_id,
                        "details": e.details, "created_at": e.created_at} for e in items]}


def mcp_result(request: Request, db: Session, params: dict) -> dict:
    user = current_user(request, db)
    name = params.get("name")
    args = params.get("arguments") or {}
    required_scope = {
        "search_skills": "skills:read", "get_skill": "skills:read",
        "get_skill_resource": "skills:read", "list_categories": "skills:read", "list_communities": "skills:read",
        "list_skill_versions": "skills:read", "get_skill_metadata": "skills:read",
        "browse_marketplace": "marketplace:read", "list_my_purchases": "marketplace:read",
        "save_skill_to_collection": "library:write", "list_user_collections": "library:read",
        "list_teams": "teams:read", "check_subscription": "account:read", "get_usage": "account:read",
        "resolve_skill_package": "skills:read", "list_skill_files": "skills:read",
        "retrieve_skill_file": "skills:read", "execute_skill_script": "execution:run",
        "get_execution_status": "execution:run", "retrieve_execution_result": "execution:run",
        "cancel_execution": "execution:run",
    }.get(name)
    if required_scope:
        require_scope(request, required_scope)
    if name == "search_skills":
        q = str(args.get("query", ""))[:120]
        query, rank = skill_search_query(db, q, str(args.get("category", "")) or None,
                                         str(args.get("community", "")) or None)
        ordering = [rank.desc()] if rank is not None else []
        rows = db.execute(query.order_by(*ordering, Skill.score.desc(), Skill.stars.desc()).limit(8)).all()
        data = [skill_data(skill, repository) for skill, repository in rows]
        record_usage(db, user, None, "search_executed", "mcp", details={"query": q})
    elif name in {"get_skill", "get_skill_metadata"}:
        skill = get_skill(db, str(args.get("id") or args.get("name") or ""))
        if name == "get_skill":
            must_have_license(skill)
            if skill.is_premium and not premium_entitlement(db, user, skill):
                raise HTTPException(status_code=402, detail="Purchase this skill to retrieve it")
            version = get_version(db, skill, None)
            try:
                instructions = read_resource(version.snapshot_path, "SKILL.md").decode("utf-8", errors="replace")
            except (ValueError, FileNotFoundError):
                raise HTTPException(status_code=503, detail="Skill snapshot is unavailable")
            data = {**skill_data(skill), "instructions": instructions, "version": version.version,
                    "version_hash": version.content_hash, "source_commit": version.source_commit,
                    "resource_manifest": version.manifest}
        else:
            data = skill_data(skill)
    elif name == "list_categories":
        data = categories(db)["items"]
    elif name == "list_communities":
        data = communities(db)["items"]
    elif name == "list_skill_versions":
        skill = get_skill(db, str(args.get("id", "")))
        data = skill_versions(skill.id, db)["items"]
    elif name == "get_skill_resource":
        skill = get_skill(db, str(args.get("id", "")))
        must_have_license(skill)
        version = get_version(db, skill, args.get("version"))
        try:
            content = read_resource(version.snapshot_path, str(args.get("path", "SKILL.md")))
        except (ValueError, FileNotFoundError):
            raise HTTPException(status_code=404, detail="Skill resource not found")
        data = {"version": version.version, "path": args.get("path", "SKILL.md"), "content": content.decode("utf-8", errors="replace")}
    elif name == "save_skill_to_collection":
        skill = get_skill(db, str(args.get("id", "")))
        collection = db.scalar(select(Collection).where(Collection.user_id == user.id, Collection.name == str(args.get("collection", "Favorites"))))
        if not collection:
            collection = Collection(user_id=user.id, name=str(args.get("collection", "Favorites"))[:80])
            db.add(collection)
            db.flush()
        exists = db.scalar(select(CollectionItem).where(CollectionItem.collection_id == collection.id, CollectionItem.skill_id == skill.id))
        if not exists:
            db.add(CollectionItem(collection_id=collection.id, skill_id=skill.id))
            db.commit()
        data = {"saved": True, "collection": collection.name, "skill_id": skill.id}
    elif name == "list_user_collections":
        data = [{"name": name, "skills": count} for name, count in db.execute(
            select(Collection.name, func.count(CollectionItem.id)).outerjoin(CollectionItem, CollectionItem.collection_id == Collection.id)
            .where(Collection.user_id == user.id).group_by(Collection.name)).all()]
    elif name == "check_subscription":
        data = entitlement_summary(db, user)
    elif name == "get_usage":
        total = db.scalar(select(func.count(UsageEvent.id)).where(
            UsageEvent.user_id == user.id, UsageEvent.event == "skill.retrieved")) or 0
        by_source = {source: count for source, count in db.execute(
            select(UsageEvent.source, func.count(UsageEvent.id)).where(
                UsageEvent.user_id == user.id, UsageEvent.event == "skill.retrieved")
            .group_by(UsageEvent.source)).all()}
        data = {"retrievals": total, "by_source": by_source,
                "plan": entitlement_summary(db, user)["plan_name"]}
    elif name == "browse_marketplace":
        limit = min(max(int(args.get("limit", 10)), 1), 25)
        rows = db.execute(select(MarketplaceListing, Skill)
                          .join(Skill, Skill.id == MarketplaceListing.skill_id)
                          .where(MarketplaceListing.status == "approved", Skill.status == "approved")
                          .order_by(MarketplaceListing.featured.desc(), MarketplaceListing.created_at.desc())
                          .limit(limit)).all()
        from .common import listing_data
        data = [listing_data(db, listing) for listing, _skill in rows]
    elif name == "list_my_purchases":
        purchases = db.scalars(select(Purchase).where(
            Purchase.user_id == user.id, Purchase.status == "paid")
            .order_by(Purchase.created_at.desc()).limit(50)).all()
        data = [{"purchase_id": purchase.id, "listing_id": purchase.listing_id,
                 "skill_id": (db.get(MarketplaceListing, purchase.listing_id).skill_id
                              if db.get(MarketplaceListing, purchase.listing_id) else None),
                 "amount_cents": purchase.amount_cents, "currency": purchase.currency,
                 "created_at": purchase.created_at} for purchase in purchases]
    elif name == "list_teams":
        teams = db.scalars(select(Team).join(TeamMember, TeamMember.team_id == Team.id)
                           .where(TeamMember.user_id == user.id).order_by(Team.created_at)).all()
        data = []
        for team in teams:
            member = db.scalar(select(TeamMember).where(TeamMember.team_id == team.id,
                                                        TeamMember.user_id == user.id))
            data.append({"id": team.id, "name": team.name, "plan_code": team.plan_code,
                         "role": member.role if member else None, "seat_limit": team.seat_limit})
    elif name == "resolve_skill_package":
        try:
            package = execution_routes.resolve_package(db, str(args.get("id", "")), args.get("version") or None, user)
        except execution_routes.ExecutionError as error:
            raise HTTPException(status_code=402 if "Purchase" in str(error) else 403, detail=str(error))
        data = _package_payload(db, package)
        data["requirements"] = execution_routes.detect_requirements(package["manifest"], package["version"].snapshot_path)
    elif name == "list_skill_files":
        try:
            package = execution_routes.resolve_package(db, str(args.get("id", "")), args.get("version") or None, user)
        except execution_routes.ExecutionError as error:
            raise HTTPException(status_code=402 if "Purchase" in str(error) else 403, detail=str(error))
        data = {
            "version": package["version"].version,
            "version_hash": package["version"].content_hash,
            "workspace_path": package["workspace_path"],
            "groups": package["groups"],
            "files": package["manifest"],
            "statistics_bundle_coverage": package.get("statistics_bundle_coverage", {}),
        }
    elif name == "retrieve_skill_file":
        try:
            package = execution_routes.resolve_package(db, str(args.get("id", "")), args.get("version") or None, user)
        except execution_routes.ExecutionError as error:
            raise HTTPException(status_code=402 if "Purchase" in str(error) else 403, detail=str(error))
        path = execution_routes.normalize_package_path(
            package, execution_routes.safe_relative_path(str(args.get("path", ""))))
        try:
            content = read_resource(package["version"].snapshot_path, path)
        except (ValueError, FileNotFoundError):
            raise HTTPException(status_code=404, detail="Skill file not found in this immutable version")
        data = {"path": path, "version": package["version"].version,
                "sha256": hashlib.sha256(content).hexdigest(),
                "encoding": "base64", "content": base64.b64encode(content).decode("ascii")}
    elif name == "execute_skill_script":
        if not settings.execution_enabled:
            raise HTTPException(status_code=503, detail="Skill execution is disabled on this deployment")
        try:
            package = execution_routes.resolve_package(db, str(args.get("id", "")), args.get("version") or None, user)
            execution_routes.assert_execution_allowed(package["skill"])
        except execution_routes.ExecutionError as error:
            raise HTTPException(status_code=402 if "Purchase" in str(error) else 403, detail=str(error))
        script = execution_routes.normalize_package_path(package, str(args.get("script", "")))
        manifest_paths = {entry["path"] for entry in package["manifest"]}
        if not script or script not in manifest_paths:
            raise HTTPException(status_code=422, detail="script must be a file from the approved package")
        command = str(args.get("command", "python3"))
        if Path(command).name not in {"python", "python3"}:
            raise HTTPException(status_code=422, detail="Only python3 execution is supported")
        extra = args.get("arguments") or []
        if not isinstance(extra, list) or any(not isinstance(item, str) for item in extra):
            raise HTTPException(status_code=422, detail="arguments must be a list of strings")
        job = ExecutionJob(
            user_id=user.id, skill_id=package["skill"].id, version=package["version"].version,
            version_hash=package["version"].content_hash, command=command,
            arguments=[script, *extra], status="queued")
        db.add(job)
        record_usage(db, user, None, "execution.requested", "mcp",
                     details={"skill_id": package["skill"].id, "version": package["version"].version, "script": script})
        db.commit()
        data = _execution_job_data(job)
    elif name in {"get_execution_status", "retrieve_execution_result"}:
        job = db.get(ExecutionJob, str(args.get("job_id", "")))
        if not job or job.user_id != user.id:
            raise HTTPException(status_code=404, detail="Execution not found")
        data = _execution_job_data(job)
    elif name == "cancel_execution":
        job = db.get(ExecutionJob, str(args.get("job_id", "")))
        if not job or job.user_id != user.id:
            raise HTTPException(status_code=404, detail="Execution not found")
        if job.status in {"succeeded", "failed", "canceled"}:
            raise HTTPException(status_code=409, detail="Execution is already finished")
        job.status = "canceled"
        job.completed_at = utcnow()
        job.error = "Canceled by user"
        db.commit()
        data = _execution_job_data(job)
    else:
        raise HTTPException(status_code=404, detail="Unknown AgentDock tool")
    if name in {"get_skill", "get_skill_resource"}:
        skill_id = str(args.get("id", ""))
        skill = db.scalar(select(Skill).where((Skill.id == skill_id) | (Skill.slug == skill_id)))
        record_usage(db, user, skill, "skill.retrieved", "mcp")
    record_usage(db, user, None, "mcp_executed", "mcp", details={"tool": name or ""})
    db.commit()
    import json
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}], "structuredContent": data}


MCP_TOOLS = [
    {"name": "search_skills", "description": "Find curated AgentDock skills for a task, optionally limited to a source community.", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "community": {"type": "string"}, "category": {"type": "string"}}, "required": ["query"]}},
    {"name": "get_skill", "description": "Retrieve the full instructions and resource manifest for a skill.", "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}},
    {"name": "get_skill_resource", "description": "Retrieve a file from an authorized skill snapshot.", "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}, "path": {"type": "string"}, "version": {"type": "string"}}, "required": ["id", "path"]}},
    {"name": "list_categories", "description": "List skill categories.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "list_communities", "description": "List source communities represented in the approved catalogue.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "list_skill_versions", "description": "List immutable versions of a skill.", "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}},
    {"name": "get_skill_metadata", "description": "Get verified skill metadata.", "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}},
    {"name": "save_skill_to_collection", "description": "Save a skill to a personal collection.", "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}, "collection": {"type": "string"}}, "required": ["id"]}},
    {"name": "list_user_collections", "description": "List the signed-in user's skill collections.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "check_subscription", "description": "Check the current account's plan, entitlements, teams and premium purchases.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "get_usage", "description": "Summarize skill retrievals for the signed-in account.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "browse_marketplace", "description": "Browse approved premium and free skill listings.", "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 25}}}},
    {"name": "list_my_purchases", "description": "List premium skills purchased by the signed-in account.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "list_teams", "description": "List teams and workspaces the signed-in account belongs to.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "resolve_skill_package", "description": "Resolve a complete immutable skill package from SkillVault with grouped files and static dependency analysis.", "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}, "version": {"type": "string"}}, "required": ["id"]}},
    {"name": "list_skill_files", "description": "List every file in an immutable skill package with SHA-256 hashes and relative paths.", "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}, "version": {"type": "string"}}, "required": ["id"]}},
    {"name": "retrieve_skill_file", "description": "Retrieve one exact file from an immutable SkillVault snapshot, base64 encoded.", "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}, "path": {"type": "string"}, "version": {"type": "string"}}, "required": ["id", "path"]}},
    {"name": "execute_skill_script", "description": "Execute an approved script in an isolated temporary workspace with no network access. Returns a job id.", "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}, "script": {"type": "string"}, "version": {"type": "string"}, "command": {"type": "string"}, "arguments": {"type": "array", "items": {"type": "string"}}}, "required": ["id", "script"]}},
    {"name": "get_execution_status", "description": "Get the status of an execution job.", "inputSchema": {"type": "object", "properties": {"job_id": {"type": "string"}}, "required": ["job_id"]}},
    {"name": "retrieve_execution_result", "description": "Retrieve stdout, stderr and exit code for a finished execution job.", "inputSchema": {"type": "object", "properties": {"job_id": {"type": "string"}}, "required": ["job_id"]}},
    {"name": "cancel_execution", "description": "Cancel a queued or running execution job.", "inputSchema": {"type": "object", "properties": {"job_id": {"type": "string"}}, "required": ["job_id"]}},
]


def _mcp_dispatch(request: Request, db: Session, body) -> dict | Response:
    if not isinstance(body, dict) or body.get("jsonrpc") != "2.0" or not isinstance(body.get("method"), str):
        raise HTTPException(status_code=400, detail="Invalid JSON-RPC request")
    params = body.get("params") or {}
    if not isinstance(params, dict):
        raise HTTPException(status_code=400, detail="MCP params must be a JSON object")
    method = body.get("method", "")
    request_id = body.get("id")
    if method == "initialize":
        requested_protocol = params.get("protocolVersion", "2025-03-26")
        if requested_protocol not in {"2025-03-26", "2025-06-18", "2025-11-25"}:
            raise HTTPException(status_code=400, detail="Unsupported MCP protocol version")
        current_user(request, db)
        return {"jsonrpc": "2.0", "id": request_id, "result": {"protocolVersion": requested_protocol,
                "capabilities": {"tools": {}}, "serverInfo": {"name": "agentdock", "version": "0.1.0"}}}
    if method.startswith("notifications/"):
        current_user(request, db)
        return Response(status_code=202)
    current_user(request, db)
    if method == "tools/list":
        result = {"tools": MCP_TOOLS}
    elif method == "tools/call":
        try:
            result = mcp_result(request, db, params)
        except HTTPException as exc:
            user = current_user(request, db)
            tool = params.get("name")
            details = {"tool": tool, "error": str(exc.detail)[:200]}
            record_failure(db, user, "mcp_failed", "mcp", details)
            if tool == "search_skills":
                record_failure(db, user, "search_failed", "mcp", details)
            elif tool in {"get_skill", "get_skill_resource"}:
                record_failure(db, user, "retrieve_failed", "mcp", details)
            elif tool == "execute_skill_script":
                record_failure(db, user, "execution_failed", "mcp", details)
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32000, "message": exc.detail}}
        except Exception:
            db.rollback()
            logger.exception("MCP tool call failed")
            user = current_user(request, db)
            tool = params.get("name")
            details = {"tool": tool, "error": "Internal tool error"}
            record_failure(db, user, "mcp_failed", "mcp", details)
            if tool == "search_skills":
                record_failure(db, user, "search_failed", "mcp", details)
            elif tool in {"get_skill", "get_skill_resource"}:
                record_failure(db, user, "retrieve_failed", "mcp", details)
            elif tool == "execute_skill_script":
                record_failure(db, user, "execution_failed", "mcp", details)
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32603, "message": "Internal tool error"}}
    elif method == "ping":
        result = {}
    else:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Method not found"}}
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


@app.post("/mcp")
async def mcp_endpoint(request: Request, db: Session = Depends(db_session)):
    accept = request.headers.get("accept", "")
    if "application/json" not in accept or "text/event-stream" not in accept:
        raise HTTPException(status_code=406, detail="MCP clients must accept application/json and text/event-stream")
    content_length = request.headers.get("content-length", "0")
    if not content_length.isdigit():
        raise HTTPException(status_code=400, detail="Invalid request size")
    if int(content_length) > 2_500_000:
        raise HTTPException(status_code=413, detail="MCP request is too large")
    protocol_header = request.headers.get("mcp-protocol-version")
    supported_protocols = {"2025-03-26", "2025-06-18", "2025-11-25"}
    if protocol_header and protocol_header not in supported_protocols:
        raise HTTPException(status_code=400, detail="Unsupported MCP protocol version")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Expected a JSON-RPC request")
    return await run_in_threadpool(_mcp_dispatch, request, db, body)


@app.get("/mcp", include_in_schema=False)
def mcp_stream_not_supported():
    return Response(status_code=405, headers={"Allow": "POST"})


app.include_router(accounts.router)
app.include_router(admin_routes.router)


frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@app.get("/{full_path:path}", include_in_schema=False)
def frontend(full_path: str):
    candidate = (frontend_dist / full_path).resolve()
    if frontend_dist.exists() and frontend_dist.resolve() in candidate.parents and candidate.is_file():
        return FileResponse(candidate)
    index = frontend_dist / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse(status_code=503, content={"detail": "Frontend bundle is not built. Follow the README setup steps."})
