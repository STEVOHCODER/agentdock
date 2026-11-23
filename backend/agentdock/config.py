from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="AGENTDOCK_", extra="ignore")

    env: str = "development"
    secret_key: str = Field(default="development-only-change-me", validation_alias=AliasChoices("AGENTDOCK_SECRET_KEY", "SECRET_KEY"))
    admin_email: str = ""
    admin_password: str = ""
    storage_path: Path = Path("./data/skillvault")
    s3_bucket: str = ""
    s3_region: str = "us-east-1"
    s3_endpoint_url: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_prefix: str = "agentdock"
    database_url: str = Field(default="sqlite:///./agentdock.db", validation_alias=AliasChoices("AGENTDOCK_DATABASE_URL", "DATABASE_URL"))
    redis_url: str = ""
    trusted_proxies: str = ""
    database_pool_size: int = 8
    database_max_overflow: int = 12
    database_pool_timeout_seconds: int = 30
    request_rate_limit_per_minute: int = Field(default=300, ge=1, le=100_000)
    auth_rate_limit_per_minute: int = Field(default=12, ge=1, le=10_000)
    frontend_origins: str = Field(default="http://localhost:5173,http://127.0.0.1:5173", validation_alias=AliasChoices("AGENTDOCK_FRONTEND_ORIGINS", "FRONTEND_ORIGINS"))
    github_token: str = Field(default="", validation_alias=AliasChoices("AGENTDOCK_GITHUB_TOKEN", "GITHUB_TOKEN"))
    github_webhook_secret: str = ""
    first_party_owners: str = ""
    session_days: int = 14
    session_secure_cookie: bool = Field(default=False, validation_alias=AliasChoices("AGENTDOCK_SESSION_SECURE_COOKIE"))
    github_timeout_seconds: float = 12
    max_skill_files: int = 100
    max_skills_per_repository: int = 500
    max_skill_bytes: int = 2_000_000
    max_repository_import_bytes: int = 200_000_000
    max_import_sources_per_batch: int = 250
    max_selected_skills_per_batch: int = 5000
    worker_lease_minutes: int = 45
    import_progress_interval: int = 5
    auto_migrate: bool = Field(default=True, validation_alias=AliasChoices("AGENTDOCK_AUTO_MIGRATE"))
    seed_library: bool = True
    public_url: str = Field(default="http://localhost:5173", validation_alias=AliasChoices("AGENTDOCK_PUBLIC_URL", "PUBLIC_URL"))

    # Email delivery (SMTP). Without SMTP, verification and reset links are logged
    # and returned to the browser only in non-production environments.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "AgentDock <no-reply@agentdock.local>"
    smtp_starttls: bool = True
    require_email_verification: bool = False

    # Skill execution bridge. Execution runs in the background worker, never in
    # the web process, and is confined with bubblewrap when available.
    execution_enabled: bool = Field(default=False, validation_alias=AliasChoices("AGENTDOCK_EXECUTION_ENABLED"))
    execution_workspace_root: str = Field(default="/tmp/agentdock-exec", validation_alias=AliasChoices("AGENTDOCK_EXECUTION_WORKSPACE_ROOT"))
    execution_timeout_seconds: int = Field(default=120, validation_alias=AliasChoices("AGENTDOCK_EXECUTION_TIMEOUT_SECONDS"))
    execution_max_memory_mb: int = Field(default=1024, validation_alias=AliasChoices("AGENTDOCK_EXECUTION_MAX_MEMORY_MB"))
    execution_max_output_bytes: int = Field(default=262144, validation_alias=AliasChoices("AGENTDOCK_EXECUTION_MAX_OUTPUT_BYTES"))
    execution_allowed_skills: str = Field(default="", validation_alias=AliasChoices("AGENTDOCK_EXEC_ALLOWED_SKILLS"))
    execution_require_bubblewrap: bool = Field(default=True, validation_alias=AliasChoices("AGENTDOCK_EXEC_REQUIRE_BUBBLEWRAP"))
    execution_driver: str = Field(default="bubblewrap", validation_alias=AliasChoices("AGENTDOCK_EXECUTION_DRIVER"))
    execution_host_workspace_root: str = Field(default="/opt/agentdock/exec-workspaces", validation_alias=AliasChoices("AGENTDOCK_EXEC_HOST_WORKSPACE_ROOT"))
    execution_image: str = Field(default="python:3.13-slim", validation_alias=AliasChoices("AGENTDOCK_EXECUTION_IMAGE"))
    execution_uid: int = Field(default=10001, validation_alias=AliasChoices("AGENTDOCK_EXECUTION_UID"))
    execution_gid: int = Field(default=10001, validation_alias=AliasChoices("AGENTDOCK_EXECUTION_GID"))
    execution_runtimes: str = Field(default="python3,python,node,nodejs,bash,sh", validation_alias=AliasChoices("AGENTDOCK_EXECUTION_RUNTIMES"))
    execution_allow_dependency_network: bool = Field(default=True, validation_alias=AliasChoices("AGENTDOCK_EXEC_ALLOW_DEPENDENCY_NETWORK"))
    execution_allow_unlocked_dependencies: bool = Field(default=False, validation_alias=AliasChoices("AGENTDOCK_EXEC_ALLOW_UNLOCKED_DEPS"))
    execution_max_timeout_seconds: int = Field(default=600, validation_alias=AliasChoices("AGENTDOCK_EXEC_MAX_TIMEOUT_SECONDS"))
    execution_default_daily_quota: int = Field(default=20, validation_alias=AliasChoices("AGENTDOCK_EXEC_DEFAULT_DAILY_QUOTA"))

    # Payments. "manual" is a real invoice workflow: an administrator records the
    # payment before entitlement is granted. Paddle/Flutterwave/UrubutoPay activate
    # only after a verified provider webhook.
    payment_provider: str = "manual"
    payment_currency: str = "USD"
    paddle_api_key: str = ""
    paddle_webhook_secret: str = ""
    paddle_environment: str = "sandbox"
    flutterwave_secret_key: str = ""
    flutterwave_webhook_hash: str = ""
    urubutopay_api_key: str = ""
    urubutopay_webhook_secret: str = ""
    urubutopay_checkout_url: str = ""
    manual_billing_email: str = "billing@agentdock.local"
    platform_commission_bps: int = 1500

    # Automated GitHub discovery defaults. Administrators can override these
    # values in the control center without redeploying.
    discovery_enabled: bool = True
    discovery_interval_hours: int = 24
    discovery_topics: str = "agent-skills,claude-skills,ai-agent-skills,codex-skills"
    discovery_keywords: str = "agent skills,SKILL.md"
    discovery_min_stars: int = 100
    discovery_per_page: int = 30

    # When enabled, synchronization may publish new skills from an already
    # approved repository without a separate admin decision, provided the skill
    # has an allowed redistribution licence and a clear security scan.
    auto_approve_synced_skills: bool = Field(default=False, validation_alias=AliasChoices("AGENTDOCK_AUTO_APPROVE_SYNCED_SKILLS"))

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.frontend_origins.split(",") if origin.strip()]

    @property
    def discovery_topic_list(self) -> list[str]:
        return [item.strip() for item in self.discovery_topics.split(",") if item.strip()]

    @property
    def discovery_keyword_list(self) -> list[str]:
        return [item.strip() for item in self.discovery_keywords.split(",") if item.strip()]

    @property
    def first_party_owner_list(self) -> list[str]:
        return [item.strip().lower() for item in self.first_party_owners.split(",") if item.strip()]

    @property
    def execution_runtime_set(self) -> set[str]:
        return {item.strip().lower() for item in self.execution_runtimes.split(",") if item.strip()}

    @property
    def execution_allowed_skill_list(self) -> set[str]:
        return {item.strip().lower() for item in self.execution_allowed_skills.split(",") if item.strip()}

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_from)

    @property
    def production(self) -> bool:
        return self.env.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
