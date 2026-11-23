from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.agentdock import ingest, main, vault
from backend.agentdock.db import Base
from backend.agentdock.models import (APIKey, ImportBatch, MarketplaceListing, Payment, Repository,
                                      RightsRequest, Skill, SkillVersion, SubscriptionPlan,
                                      SynchronizationJob, Team, TeamMember, User, utcnow)
from backend.agentdock.security import password_hash
from backend.agentdock.vault import save_snapshot


@pytest.fixture
def clients(tmp_path):
    # Keep the app's process-local request limiter isolated across test cases.
    main._request_times.clear()
    main._auth_request_times.clear()
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.drop_all(test_engine)
    Base.metadata.create_all(test_engine)
    TestSession = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)
    original_engine, original_session = main.engine, main.SessionLocal
    import backend.agentdock.db as db_module
    original_db_session = db_module.SessionLocal
    original_storage = main.settings.storage_path
    original_email, original_password = main.settings.admin_email, main.settings.admin_password
    original_seed = main.settings.seed_library
    main.engine, main.SessionLocal = test_engine, TestSession
    db_module.SessionLocal = TestSession
    main.settings.storage_path = tmp_path / "vault"
    main.settings.admin_email, main.settings.admin_password = "admin@example.com", "a-long-test-password-123"
    main.settings.seed_library = False
    with TestClient(main.app) as client:
        db = TestSession()
        user = User(email="member@example.com", password_hash=password_hash("a-long-member-password-123"), role="free")
        db.add(user)
        db.commit()
        db.close()
        admin_client = TestClient(main.app)
        admin_response = admin_client.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": "a-long-test-password-123"})
        assert admin_response.status_code == 200
        yield client, admin_client, TestSession
        admin_client.close()
    main.engine, main.SessionLocal = original_engine, original_session
    db_module.SessionLocal = original_db_session
    main.settings.storage_path = original_storage
    main.settings.admin_email, main.settings.admin_password = original_email, original_password
    main.settings.seed_library = original_seed
    Base.metadata.drop_all(test_engine)
    test_engine.dispose()


def test_public_health_and_skill_search(clients):
    client, _, _ = clients
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert client.get("/api/v1/skills/search").json() == {"items": [], "total": 0, "limit": 20, "offset": 0}


def test_postgres_multiword_skill_search_uses_or_terms():
    class PostgreSQLBind:
        class dialect:
            name = "postgresql"

    class SearchSession:
        @staticmethod
        def get_bind():
            return PostgreSQLBind()

    statement, _rank = main.skill_search_query(SearchSession(), "react development")
    compiled = statement.compile(dialect=postgresql.dialect())
    assert "websearch_to_tsquery" in str(compiled)
    assert "react OR development" in compiled.params.values()


def test_production_startup_rejects_http_and_insecure_cookie_configuration(clients, monkeypatch):
    settings = main.settings
    monkeypatch.setattr(settings, "env", "production")
    monkeypatch.setattr(settings, "secret_key", "x" * 48)
    monkeypatch.setattr(settings, "public_url", "http://agentdock.example")
    monkeypatch.setattr(settings, "session_secure_cookie", False)
    monkeypatch.setattr(settings, "frontend_origins", "http://agentdock.example")
    with pytest.raises(RuntimeError, match="PUBLIC_URL to use HTTPS"):
        main.startup()

    monkeypatch.setattr(settings, "public_url", "https://agentdock.example")
    with pytest.raises(RuntimeError, match="SESSION_SECURE_COOKIE=true"):
        main.startup()

    monkeypatch.setattr(settings, "session_secure_cookie", True)
    with pytest.raises(RuntimeError, match="browser origins must all use HTTPS"):
        main.startup()

    monkeypatch.setattr(settings, "frontend_origins", "https://agentdock.example")
    main.startup()


def test_interactive_api_docs_allow_only_the_assets_the_page_needs(clients):
    client, _, _ = clients
    docs = client.get("/api/docs")
    assert docs.status_code == 200
    assert "swagger-ui" in docs.text
    assert "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net" in docs.headers["content-security-policy"]
    assert "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net" in docs.headers["content-security-policy"]
    health = client.get("/api/health")
    assert "cdn.jsdelivr.net" not in health.headers["content-security-policy"]


def test_regular_user_cannot_open_admin_control_center(clients):
    client, _, _ = clients
    response = client.get("/api/v1/admin/overview")
    assert response.status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": "member@example.com", "password": "a-long-member-password-123"}).status_code == 200
    assert client.get("/api/v1/admin/overview").status_code == 403


def test_configured_admin_bootstrap_promotes_existing_account_only_with_matching_password(clients, monkeypatch):
    _, _, TestSession = clients
    db = TestSession()
    current_admin = db.scalar(select(User).where(User.role == "admin"))
    current_admin.role = "free"
    db.commit()
    db.close()

    monkeypatch.setattr(main.settings, "admin_email", "member@example.com")
    monkeypatch.setattr(main.settings, "admin_password", "a-long-member-password-123")
    main.startup()

    db = TestSession()
    promoted = db.scalar(select(User).where(User.email == "member@example.com"))
    assert promoted.role == "admin"
    db.close()


def test_configured_admin_bootstrap_rejects_password_mismatch_for_existing_account(clients, monkeypatch):
    _, _, TestSession = clients
    db = TestSession()
    current_admin = db.scalar(select(User).where(User.role == "admin"))
    current_admin.role = "free"
    db.commit()
    db.close()

    monkeypatch.setattr(main.settings, "admin_email", "member@example.com")
    monkeypatch.setattr(main.settings, "admin_password", "different-bootstrap-password")
    with pytest.raises(RuntimeError, match="password must match"):
        main.startup()

    db = TestSession()
    member = db.scalar(select(User).where(User.email == "member@example.com"))
    assert member.role == "free"
    db.close()


def test_configured_admin_bootstrap_rejects_short_password_even_in_development(clients, monkeypatch):
    monkeypatch.setattr(main.settings, "admin_email", "new-admin@example.com")
    monkeypatch.setattr(main.settings, "admin_password", "short-pass")
    with pytest.raises(RuntimeError, match="at least 12 characters"):
        main.startup()


def test_api_key_is_one_time_and_works_for_mcp(clients):
    client, _, TestSession = clients
    assert client.post("/api/v1/auth/login", json={"email": "member@example.com", "password": "a-long-member-password-123"}).status_code == 200
    created = client.post("/api/v1/auth/api-keys", json={"name": "Test MCP"})
    assert created.status_code == 201
    raw_key = created.json()["api_key"]
    db = TestSession()
    stored = db.scalar(select(APIKey).where(APIKey.name == "Test MCP"))
    assert stored.key_hash != raw_key
    assert len(stored.key_hash) == 64
    db.close()
    headers = {"Authorization": "Bearer " + raw_key, "Accept": "application/json, text/event-stream"}
    response = client.post("/mcp", headers=headers, json={
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}},
    })
    assert response.status_code == 200
    assert response.json()["result"]["serverInfo"]["name"] == "agentdock"
    listing = client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert "search_skills" in [tool["name"] for tool in listing.json()["result"]["tools"]]
    search = client.post("/mcp", headers=headers, json={
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "search_skills", "arguments": {"query": "dashboard"}},
    })
    assert "error" not in search.json()
    failed = client.post("/mcp", headers=headers, json={
        "jsonrpc": "2.0", "id": 4, "method": "tools/call",
        "params": {"name": "get_skill", "arguments": {"id": "missing-skill"}},
    })
    assert "error" in failed.json()
    usage = client.get("/api/v1/account/usage").json()["stats"]
    assert usage["searches_executed"] == 1
    assert usage["executions"] == 1
    assert usage["executions_failed"] == 1
    assert usage["retrievals_failed"] == 1


def test_api_key_scopes_limit_library_and_admin_access(clients):
    client, admin_client, _ = clients
    assert client.post("/api/v1/auth/login", json={"email": "member@example.com", "password": "a-long-member-password-123"}).status_code == 200
    restricted = client.post("/api/v1/auth/api-keys", json={"name": "Search only", "scopes": ["skills:read"]})
    assert restricted.status_code == 201
    limited_headers = {"Authorization": "Bearer " + restricted.json()["api_key"]}
    assert client.get("/api/v1/user/library", headers=limited_headers).status_code == 403
    assert client.post("/api/v1/auth/api-keys", json={"name": "Invalid", "scopes": ["admin:*"]}).status_code == 422

    admin_key = admin_client.post("/api/v1/auth/api-keys", json={"name": "Admin MCP"})
    assert admin_key.status_code == 201
    admin_headers = {"Authorization": "Bearer " + admin_key.json()["api_key"]}
    assert admin_client.get("/api/v1/admin/overview", headers=admin_headers).status_code == 403


def test_mcp_rejects_unknown_protocol_version(clients):
    client, _, _ = clients
    response = client.post("/mcp", headers={"Accept": "application/json, text/event-stream"}, json={
        "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "1900-01-01"},
    })
    assert response.status_code == 400


def test_search_save_retrieve_and_resource_delivery(clients):
    client, _, TestSession = clients
    db = TestSession()
    repository = Repository(url="https://github.com/acme/dashboard-skills", owner="acme",
                            name="dashboard-skills", license_id="MIT", status="approved")
    db.add(repository)
    db.flush()
    skill = Skill(repository_id=repository.id, slug="react-dashboard", name="React dashboard",
                  description="Create clear analytics layouts.",
                  instructions="---\nname: React dashboard\ndescription: Build a dashboard\n---\nUse charts and responsive cards.",
                  path="skills/react-dashboard", category="Frontend", creator="acme", license_id="MIT",
                  source_url=repository.url, stars=2400, score=96, status="approved",
                  security_status="clear", latest_version="git-abcd12345678")
    db.add(skill)
    db.flush()
    snapshot, digest, manifest = save_snapshot(skill.id, skill.latest_version,
        {"SKILL.md": skill.instructions.encode(), "references/charts.md": b"Accessible chart guidance."})
    db.add(SkillVersion(skill_id=skill.id, version=skill.latest_version, source_commit="abcd12345678",
                        content_hash=digest, manifest=manifest, snapshot_path=snapshot))
    db.commit()
    db.close()

    login = client.post("/api/v1/auth/login", json={"email": "member@example.com", "password": "a-long-member-password-123"})
    assert login.status_code == 200
    search = client.get("/api/v1/skills/search?q=dashboard charts")
    assert search.status_code == 200
    assert search.json()["items"][0]["slug"] == "react-dashboard"
    detail = client.get("/api/v1/skills/react-dashboard")
    assert detail.status_code == 200
    assert "instructions" not in detail.json()
    retrieval = client.post("/api/v1/skills/react-dashboard/retrieve", json={})
    assert retrieval.status_code == 200
    assert "responsive cards" in retrieval.json()["skill"]["instructions"]
    assert len(retrieval.json()["resource_manifest"]) == 2
    saved = client.post("/api/v1/user/library", json={"skill_id": retrieval.json()["skill"]["id"]})
    assert saved.status_code == 201
    assert len(client.get("/api/v1/user/library").json()["items"]) == 1
    resource = client.get("/api/v1/skills/react-dashboard/resources/references/charts.md?version=git-abcd12345678")
    assert resource.status_code == 200
    assert resource.text == "Accessible chart guidance."
    assert client.get("/api/v1/account/usage").json()["skills_retrieved"] == 1
    assert client.get("/api/v1/skills/search?limit=999").status_code == 422
    assert client.post("/api/v1/skills/missing-skill/retrieve", json={}).status_code == 404
    stats = client.get("/api/v1/account/usage").json()["stats"]
    assert stats["searches_executed"] == 1
    assert stats["searches_failed"] == 1
    assert stats["retrievals_success"] == 1
    assert stats["retrievals_failed"] == 1


def test_admin_endpoints_require_administrator(clients):
    client, admin_client, _ = clients
    assert client.post("/api/v1/auth/login", json={"email": "member@example.com", "password": "a-long-member-password-123"}).status_code == 200
    protected = [
        "/api/v1/admin/overview",
        "/api/v1/admin/analytics",
        "/api/v1/admin/users",
        "/api/v1/admin/payments",
        "/api/v1/admin/skills",
        "/api/v1/admin/repositories",
        "/api/v1/admin/security",
        "/api/v1/admin/system",
        "/api/v1/admin/audit-logs",
    ]
    for path in protected:
        response = client.get(path)
        assert response.status_code == 403, f"{path} should require an administrator"
    for path in protected:
        response = admin_client.get(path)
        assert response.status_code == 200, f"administrator should access {path}"
    _, admin_client, TestSession = clients
    db = TestSession()
    skill = Skill(slug="unknown-license-skill", name="Unknown licence skill", license_id="unknown",
                  status="pending_review", security_status="clear", score=90)
    db.add(skill)
    db.commit()
    skill_id = skill.id
    db.close()
    response = admin_client.post("/api/v1/admin/skills/" + skill_id + "/decision",
                                json={"decision": "approved", "reason": "Looks useful and complete."})
    assert response.status_code == 422


def test_trusted_publishers_are_admin_only_and_audited(clients):
    client, admin_client, _ = clients
    assert client.post("/api/v1/auth/login", json={"email": "member@example.com", "password": "a-long-member-password-123"}).status_code == 200
    denied = client.post("/api/v1/admin/trusted-publishers", json={"github_handle": "acme"})
    assert denied.status_code == 403
    added = admin_client.post("/api/v1/admin/trusted-publishers", json={
        "github_handle": "acme", "kind": "organization", "trust_level": "verified", "notes": "Owner reviewed.",
    })
    assert added.status_code == 201
    assert admin_client.get("/api/v1/admin/trusted-publishers").json()["items"][0]["github_handle"] == "acme"


def test_bulk_import_batch_queues_sources_and_tracks_community(clients):
    _, admin_client, TestSession = clients
    response = admin_client.post("/api/v1/admin/import-batches", json={"sources": [
        {"repository_url": "https://github.com/community-a/skill-pack", "community": "Community A",
         "skill_paths": ["skills/react", "skills/python"]},
        {"repository_url": "https://github.com/community-b/agent-recipes", "community": "Community B"},
    ]})
    assert response.status_code == 202
    batch_id = response.json()["id"]
    assert response.json()["source_count"] == 2
    detail = admin_client.get(f"/api/v1/admin/import-batches/{batch_id}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "queued"
    assert {job["community"] for job in detail.json()["jobs"]} == {"Community A", "Community B"}
    db = TestSession()
    batch = db.get(ImportBatch, batch_id)
    jobs = db.scalars(select(SynchronizationJob).where(SynchronizationJob.batch_id == batch_id)).all()
    assert batch.source_count == 2
    assert len(jobs) == 2
    assert all(job.operation == "import" and job.status == "queued" for job in jobs)
    assert sorted(len(job.skill_paths) for job in jobs) == [0, 2]
    db.close()


def test_bulk_import_batch_validates_duplicate_urls_and_requires_admin(clients):
    client, admin_client, _ = clients
    source = {"repository_url": "https://github.com/community-a/skill-pack", "skill_paths": ["skills/react"]}
    assert client.post("/api/v1/admin/import-batches", json={"sources": [source]}).status_code == 401
    duplicate = admin_client.post("/api/v1/admin/import-batches", json={"sources": [
        source, {"repository_url": "https://github.com/community-a/skill-pack/", "skill_paths": ["skills/python"]},
    ]})
    assert duplicate.status_code == 422
    unsafe = admin_client.post("/api/v1/admin/import-batches", json={"sources": [
        {"repository_url": "https://github.com/community-a/skill-pack", "skill_paths": ["skills/../../outside"]},
    ]})
    assert unsafe.status_code == 422


def test_multiple_workers_claim_different_import_jobs(clients):
    _, admin_client, TestSession = clients
    queued = admin_client.post("/api/v1/admin/import-batches", json={"sources": [
        {"repository_url": "https://github.com/community-a/one", "community": "Community A"},
        {"repository_url": "https://github.com/community-b/two", "community": "Community B"},
    ]})
    assert queued.status_code == 202
    from backend.agentdock.worker import claim_job
    db = TestSession()
    first = claim_job(db)
    second = claim_job(db)
    assert first.status == second.status == "running"
    assert first.id != second.id
    db.close()


def test_skillvault_can_use_shared_s3_storage(monkeypatch):
    settings = main.settings
    monkeypatch.setattr(settings, "s3_bucket", "agentdock-test")
    monkeypatch.setattr(settings, "s3_prefix", "test-vault")

    class FakeS3:
        objects = {}

        def put_object(self, Bucket, Key, Body, **kwargs):
            self.objects[(Bucket, Key)] = Body if isinstance(Body, bytes) else Body.read()

        def get_object(self, Bucket, Key):
            from io import BytesIO
            return {"Body": BytesIO(self.objects[(Bucket, Key)])}

    storage = FakeS3()
    monkeypatch.setattr(vault, "_s3_client", lambda: storage)
    uri, digest, manifest = vault.save_snapshot("skill-id", "git-abc123", {
        "SKILL.md": b"# Example", "references/guide.md": b"Shared object storage",
    })
    assert uri == "s3://agentdock-test/test-vault/skill-id/git-abc123"
    assert len(digest) == 64
    assert len(manifest) == 2
    assert vault.read_resource(uri, "references/guide.md") == b"Shared object storage"


def test_import_selection_is_incremental_and_repository_attributed(clients, monkeypatch):
    _, _, TestSession = clients
    skills = {
        "skills/react/SKILL.md": b"---\nname: React layouts\ndescription: Build React interfaces\n---\nUse semantic components.",
        "skills/python/SKILL.md": b"---\nname: Python services\ndescription: Build Python APIs\n---\nValidate inputs.",
    }

    class FakeGitHubClient:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return None

        def repository(self, _owner, _repo):
            return {"private": False, "archived": False, "default_branch": "main",
                    "license": {"spdx_id": "MIT"}, "stargazers_count": 450,
                    "forks_count": 20, "pushed_at": "2026-11-20T00:00:00Z"}

        def commit(self, _owner, _repo, _branch):
            return "1234567890abcdef1234567890abcdef12345678"

        def tree(self, _owner, _repo, _branch):
            return {"truncated": False, "tree": [{"path": path, "type": "blob", "mode": "100644",
                                                   "size": len(body)} for path, body in skills.items()]}

        def file(self, _owner, _repo, _branch, path, _max_bytes=None):
            return skills[path]

    monkeypatch.setattr(ingest, "GitHubClient", FakeGitHubClient)
    progress = []
    db = TestSession()
    selected = ingest.import_repository(db, "https://github.com/community-a/skill-pack",
                                        skill_paths=["skills/react"], community="Community A",
                                        progress_callback=lambda current, total: progress.append((current, total)))
    assert len(selected["skills"]) == 1
    assert selected["skills"][0]["path"] == "skills/react"
    assert selected["repository"]["last_commit_sha"] == ""
    full = ingest.import_repository(db, "https://github.com/community-a/skill-pack", community="Community A")
    repeated = ingest.import_repository(db, "https://github.com/community-a/skill-pack", community="Community A")
    assert len(full["skills"]) == len(repeated["skills"]) == 2
    assert set(progress) == {(0, 1), (1, 1)}
    indexed = db.scalars(select(Skill).where(Skill.repository_id == full["repository"]["id"])).all()
    assert {skill.community for skill in indexed} == {"Community A"}
    assert all(skill.instructions == "" for skill in indexed)
    versions = db.scalars(select(SkillVersion).where(SkillVersion.skill_id.in_([skill.id for skill in indexed]))).all()
    assert len(versions) == 2
    db.close()


def test_import_selected_skill_when_repository_tree_is_truncated(clients, monkeypatch):
    _, _, TestSession = clients
    skill_md = b"---\nname: Community skill\ndescription: Selected from a large repository\n---\nUse safe defaults."

    class FakeGitHubClient:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return None

        def repository(self, _owner, _repo):
            return {"private": False, "archived": False, "default_branch": "main",
                    "license": {"spdx_id": "MIT"}, "stargazers_count": 450,
                    "forks_count": 20, "pushed_at": "2026-11-20T00:00:00Z"}

        def commit(self, _owner, _repo, _branch):
            return "1234567890abcdef1234567890abcdef12345678"

        def tree(self, _owner, _repo, ref, recursive=True):
            if ref == "main" and recursive:
                return {"truncated": True, "tree": []}
            if ref == "main":
                return {"truncated": False, "tree": [
                    {"path": "skills", "type": "tree", "sha": "skills-tree"},
                ]}
            if ref == "skills-tree" and recursive:
                return {"truncated": True, "tree": []}
            if ref == "skills-tree":
                return {"truncated": False, "tree": [
                    {"path": "react", "type": "tree", "sha": "react-tree"},
                    {"path": "python", "type": "tree", "sha": "python-tree"},
                ]}
            if ref == "react-tree" and recursive:
                return {"truncated": False, "tree": [
                    {"path": "SKILL.md", "type": "blob", "mode": "100644", "size": len(skill_md)},
                ]}
            raise AssertionError(f"Unexpected GitHub tree lookup: {ref}, recursive={recursive}")

        def file(self, _owner, _repo, _branch, path, _max_bytes=None):
            assert path == "skills/react/SKILL.md"
            return skill_md

    monkeypatch.setattr(ingest, "GitHubClient", FakeGitHubClient)
    db = TestSession()
    result = ingest.import_repository(db, "https://github.com/community-a/large-pack",
                                      skill_paths=["skills/react"], community="Community A")
    assert len(result["skills"]) == 1
    assert result["skills"][0]["path"] == "skills/react"
    assert result["skills"][0]["name"] == "Community skill"
    db.close()


def _token_from_link(link):
    parsed = urlparse(link)
    query = parsed.query
    fragment = parsed.fragment
    if "?" in fragment:
        query = fragment.split("?", 1)[1]
    return parse_qs(query)["token"][0]


def _invite_from_link(link):
    parsed = urlparse(link)
    query = parsed.query
    fragment = parsed.fragment
    if "?" in fragment:
        query = fragment.split("?", 1)[1]
    return parse_qs(query)["invite"][0]


def test_registration_verification_and_password_reset(clients):
    client, _, _ = clients
    registered = client.post("/api/v1/auth/register", json={
        "email": "new@example.com", "password": "a-long-new-password-123", "name": "New User"})
    assert registered.status_code == 201
    assert registered.json()["user"]["name"] == "New User"
    link = registered.json()["debug_verification_link"]
    verified = client.post("/api/v1/auth/verify-email", json={"token": _token_from_link(link)})
    assert verified.status_code == 200
    assert verified.json()["email_verified"] is True
    assert client.post("/api/v1/auth/verify-email", json={"token": _token_from_link(link)}).status_code == 422

    forgot = client.post("/api/v1/auth/forgot-password", json={"email": "new@example.com"})
    assert forgot.status_code == 200
    reset = client.post("/api/v1/auth/reset-password", json={
        "token": _token_from_link(forgot.json()["debug_link"]), "password": "another-long-password-456"})
    assert reset.status_code == 200
    assert client.post("/api/v1/auth/login", json={
        "email": "new@example.com", "password": "a-long-new-password-123"}).status_code == 401
    assert client.post("/api/v1/auth/login", json={
        "email": "new@example.com", "password": "another-long-password-456"}).status_code == 200


def test_teams_invitations_and_seat_limits(clients):
    client, _, TestSession = clients
    assert client.post("/api/v1/auth/login", json={
        "email": "member@example.com", "password": "a-long-member-password-123"}).status_code == 200
    team = client.post("/api/v1/teams", json={"name": "Core Platform"})
    assert team.status_code == 201
    team_id = team.json()["id"]
    db = TestSession()
    db.add(User(email="teammate@example.com", password_hash=password_hash("a-long-teammate-password-123"), role="free"))
    db.commit()
    db.close()

    invited = client.post(f"/api/v1/teams/{team_id}/invitations",
                          json={"email": "teammate@example.com", "role": "member"})
    assert invited.status_code == 201
    invite_token = _invite_from_link(invited.json()["invite_link"])
    teammate = TestClient(main.app)
    assert teammate.post("/api/v1/auth/login", json={
        "email": "teammate@example.com", "password": "a-long-teammate-password-123"}).status_code == 200
    accepted = teammate.post("/api/v1/teams/invitations/accept", json={"token": invite_token})
    assert accepted.status_code == 200
    detail = client.get(f"/api/v1/teams/{team_id}")
    assert detail.status_code == 200
    assert len(detail.json()["members"]) == 2
    overflow = client.post(f"/api/v1/teams/{team_id}/invitations",
                           json={"email": "third@example.com", "role": "member"})
    assert overflow.status_code == 409


def _approved_skill(db, slug, price=0, commercial=True, premium=True):
    skill = Skill(repository_id=None, slug=slug, name=slug.replace("-", " ").title(),
                  description="A useful skill for the test suite.", instructions="",
                  category="Testing", creator="Tester", license_id="MIT", stars=10, score=90,
                  status="approved", is_premium=premium, commercial_ok=commercial,
                  security_status="clear", latest_version="1.0.0", technologies=[])
    db.add(skill)
    db.flush()
    snapshot, digest, manifest = save_snapshot(skill.id, "1.0.0",
                                                {"SKILL.md": b"Use the documented workflow."})
    db.add(SkillVersion(skill_id=skill.id, version="1.0.0", content_hash=digest,
                        manifest=manifest, snapshot_path=snapshot))
    db.flush()
    return skill


def test_marketplace_search_and_pagination_use_database_filters(clients):
    client, _, TestSession = clients
    db = TestSession()
    member = db.scalar(select(User).where(User.email == "member@example.com"))
    member.name = "Member"
    entries = [
        ("react-layouts", "React interface patterns", "Development guidance for responsive apps", "Frontend", 300, True, member.id),
        ("python-jobs", "Python job helpers", "Automate repeatable tasks", "Backend", 100, False, None),
        ("design-review", "Design review checklist", "Review interface decisions", "Frontend", 500, False, None),
    ]
    for slug, name, description, category, price, featured, creator_id in entries:
        skill = _approved_skill(db, slug)
        skill.name = name
        skill.description = description
        skill.category = category
        db.add(MarketplaceListing(skill_id=skill.id, title=name, summary=description,
                                  price_cents=price, status="approved", featured=featured,
                                  creator_id=creator_id, published_at=utcnow()))
    db.commit()
    db.close()

    search = client.get("/api/v1/marketplace/listings", params={"q": "react development"})
    assert search.status_code == 200
    assert search.json()["total"] == 1
    assert search.json()["items"][0]["title"] == "React interface patterns"

    by_creator = client.get("/api/v1/marketplace/listings", params={"q": "member"})
    assert by_creator.json()["total"] == 1
    assert by_creator.json()["items"][0]["creator"] == "Member"

    page_one = client.get("/api/v1/marketplace/listings", params={"sort": "price_low", "limit": 1})
    page_two = client.get("/api/v1/marketplace/listings", params={"sort": "price_low", "limit": 1, "offset": 1})
    assert page_one.json()["total"] == 3
    assert page_one.json()["items"][0]["price_cents"] == 100
    assert page_two.json()["items"][0]["price_cents"] == 300
    assert page_two.json()["offset"] == 1

    featured = client.get("/api/v1/marketplace/listings", params={
        "featured": "true", "category": "Frontend", "q": "react development"})
    assert featured.json()["total"] == 1
    categories = client.get("/api/v1/marketplace/categories")
    assert categories.json()["items"] == [
        {"name": "Backend", "count": 1}, {"name": "Frontend", "count": 2},
    ]


def test_marketplace_free_and_manual_paid_purchase_unlock_retrieval(clients):
    client, admin_client, TestSession = clients
    db = TestSession()
    free_skill = _approved_skill(db, "free-marketplace-skill", price=0)
    paid_skill = _approved_skill(db, "paid-marketplace-skill", price=500)
    db.add(MarketplaceListing(skill_id=free_skill.id, title="Free marketplace skill",
                              summary="Useful and free.", price_cents=0, status="approved", published_at=utcnow()))
    db.add(MarketplaceListing(skill_id=paid_skill.id, title="Paid marketplace skill",
                              summary="Premium guidance.", price_cents=500, status="approved", published_at=utcnow()))
    db.commit()
    free_listing_id = db.scalar(select(MarketplaceListing.id).where(MarketplaceListing.skill_id == free_skill.id))
    paid_listing_id = db.scalar(select(MarketplaceListing.id).where(MarketplaceListing.skill_id == paid_skill.id))
    db.close()

    client.post("/api/v1/auth/login", json={"email": "member@example.com", "password": "a-long-member-password-123"})
    assert client.post(f"/api/v1/skills/{paid_skill.slug}/retrieve", json={}).status_code == 402

    free = client.post("/api/v1/marketplace/purchases", json={"listing_id": free_listing_id})
    assert free.status_code == 202
    assert free.json()["status"] == "paid"
    assert client.post(f"/api/v1/skills/{free_skill.slug}/retrieve", json={}).status_code == 200

    paid = client.post("/api/v1/marketplace/purchases", json={"listing_id": paid_listing_id})
    assert paid.status_code == 202
    payment_id = paid.json()["payment_id"]
    assert client.post(f"/api/v1/skills/{paid_skill.slug}/retrieve", json={}).status_code == 402
    fulfilled = admin_client.post(f"/api/v1/admin/payments/{payment_id}/fulfill",
                                  json={"reason": "Bank transfer received and reconciled."})
    assert fulfilled.status_code == 200
    assert fulfilled.json()["status"] == "paid"
    assert client.post(f"/api/v1/skills/{paid_skill.slug}/retrieve", json={}).status_code == 200
    assert client.get("/api/v1/marketplace/purchases").json()["items"][0]["skill_id"] == paid_skill.id


def test_subscription_checkout_and_admin_billing_fulfilment(clients):
    client, admin_client, TestSession = clients
    db = TestSession()
    db.add(SubscriptionPlan(code="developer", name="Developer", price_cents=300,
                             annual_price_cents=3000, member_limit=1, features=["Advanced discovery"]))
    db.commit()
    db.close()
    client.post("/api/v1/auth/login", json={"email": "member@example.com", "password": "a-long-member-password-123"})
    checkout = client.post("/api/v1/account/subscription/checkout",
                           json={"plan_code": "developer", "interval": "month"})
    assert checkout.status_code == 202
    assert checkout.json()["provider"] == "manual"
    billing = client.get("/api/v1/account/billing")
    assert billing.status_code == 200
    assert billing.json()["provider"]["configured"] is True
    payment_id = billing.json()["payments"][0]["id"]
    assert billing.json()["payments"][0]["status"] == "pending"
    fulfilled = admin_client.post(f"/api/v1/admin/payments/{payment_id}/fulfill",
                                  json={"reason": "Manual invoice reconciled."})
    assert fulfilled.status_code == 200
    entitlements = client.get("/api/v1/account/entitlements")
    assert entitlements.status_code == 200
    assert entitlements.json()["plan_code"] == "developer"
    assert "Advanced discovery" in entitlements.json()["features"]


def test_admin_analytics_settings_plans_and_rights_requests(clients):
    client, admin_client, TestSession = clients
    db = TestSession()
    db.add(SubscriptionPlan(code="audit-2026", name="Audit", price_cents=0, member_limit=1))
    db.commit()
    db.close()
    analytics = admin_client.get("/api/v1/admin/analytics")
    assert analytics.status_code == 200
    assert analytics.json()["revenue"]["currency"] == "USD"
    assert "series" in analytics.json()

    updated = admin_client.patch("/api/v1/admin/plans/audit-2026", json={
        "code": "audit-2026", "name": "Audit Team", "description": "Updated",
        "price_cents": 0, "annual_price_cents": 0, "currency": "USD",
        "member_limit": 2, "features": ["Audit access"], "is_active": True, "sort_order": 9})
    assert updated.status_code == 200

    settings = admin_client.patch("/api/v1/admin/settings", json=[
        {"key": "security", "value": {"scan_on_import": True, "minimum_score": 75}}])
    assert settings.status_code == 200
    discovery = admin_client.get("/api/v1/admin/discovery")
    assert discovery.status_code == 200

    rights = client.post("/api/v1/rights-requests", json={
        "requester_name": "Rights Holder", "requester_email": "rights@example.com",
        "repository_url": "https://github.com/acme/dashboard-skills",
        "claim_type": "takedown", "details": "This skill reproduces content we own."})
    assert rights.status_code == 201
    request_id = rights.json()["id"]
    listed = admin_client.get("/api/v1/admin/rights-requests")
    assert listed.status_code == 200
    resolved = admin_client.post(f"/api/v1/admin/rights-requests/{request_id}/resolve",
                                 json={"status": "resolved", "resolution": "Contacted and removed from the catalogue."})
    assert resolved.status_code == 200


def test_starter_library_seed_is_idempotent(clients):
    _, _, TestSession = clients
    from backend.agentdock.seed import seed_library
    main.settings.seed_library = True
    try:
        db = TestSession()
        first = seed_library(db)
        second = seed_library(db)
        assert first["seeded"] == 16
        assert second["seeded"] == 0
        assert db.scalar(select(func.count(Skill.id))) == 16
        assert db.scalar(select(func.count(SubscriptionPlan.code))) == 5
        assert db.scalar(select(func.count(MarketplaceListing.id))) == 3
        assert [(plan.code, plan.price_cents, plan.member_limit) for plan in db.query(SubscriptionPlan).order_by(SubscriptionPlan.sort_order)] == [
            ("free", 0, 1), ("developer", 300, 1), ("duo", 500, 2), ("team", 800, 4), ("growth", 1000, 7)]
        db.close()
    finally:
        main.settings.seed_library = False


def test_hidden_skill_directory_import_with_first_party_authorization(clients, monkeypatch):
    _, _, TestSession = clients
    monkeypatch.setattr(main.settings, "first_party_owners", "acme")
    skill_md = b"---\nname: Hidden workflow\ndescription: Lives in a dot-prefixed skills folder\n---\nFollow the checklist."
    files = {
        ".agents/skills/hidden-workflow/SKILL.md": skill_md,
        ".agents/skills/hidden-workflow/checklist.md": b"Review the output.",
    }
    pushed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    class FakeGitHubClient:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return None

        def repository(self, _owner, _repo):
            return {"private": False, "archived": False, "default_branch": "main",
                    "license": None, "stargazers_count": 450, "forks_count": 12,
                    "pushed_at": pushed_at}

        def commit(self, _owner, _repo, _branch):
            return "abcdef1234567890abcdef1234567890abcdef12"

        def tree(self, _owner, _repo, ref, recursive=True):
            if ref != "main" or not recursive:
                return {"truncated": False, "tree": []}
            return {"truncated": False, "tree": [
                {"path": path, "type": "blob", "mode": "100644", "size": len(body)}
                for path, body in files.items()
            ]}

        def file(self, _owner, _repo, _branch, path, _max_bytes=None):
            return files[path]

    monkeypatch.setattr(ingest, "GitHubClient", FakeGitHubClient)
    db = TestSession()
    result = ingest.import_repository(db, "https://github.com/acme/hidden-skills",
                                      skill_paths=[".agents/skills/hidden-workflow"])
    assert len(result["skills"]) == 1
    skill = db.get(Skill, result["skills"][0]["id"])
    assert skill.status == "qualified"
    assert skill.score >= 75
    assert skill.license_id == "OWNER-AUTHORIZED"
    assert skill.commercial_ok is True
    repository = db.get(Repository, skill.repository_id)
    assert repository.rights_status == "owner_authorized"
    db.close()


def test_all_payment_providers_are_visible_even_without_credentials(clients):
    client, _, _ = clients
    data = client.get("/api/v1/plans").json()
    providers = {item["provider"]: item for item in data["providers"]}
    assert set(providers) == {"manual", "paddle", "flutterwave", "urubutopay"}
    assert providers["manual"]["active"] is True
    assert providers["paddle"]["status"] == "available"
    assert "credentials" in providers["urubutopay"]["description"].lower() or providers["urubutopay"]["status"] == "available"
