from pathlib import Path

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


SUPPORTED_SCOPES = {
    "skills:read", "library:read", "library:write", "account:read",
    "teams:read", "teams:write", "marketplace:read", "marketplace:write", "billing:read",
    "execution:run",
}


class ExecutionInput(BaseModel):
    skill: str = Field(min_length=1, max_length=200)
    version: str = Field(default="", max_length=120)
    command: str = Field(default="python3", max_length=64)
    arguments: list[str] = Field(default_factory=list, max_length=64)
    team_id: str | None = Field(default=None, max_length=36)
    timeout_seconds: int | None = Field(default=None, ge=1, le=600)
    max_memory_mb: int | None = Field(default=None, ge=64, le=4096)
    max_cpu_millicores: int | None = Field(default=None, ge=100, le=4000)
    network: bool = False


class RegisterInput(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=200)
    name: str = Field(default="", max_length=120)


class LoginInput(BaseModel):
    email: EmailStr
    password: str = Field(max_length=200)


class VerifyEmailInput(BaseModel):
    token: str = Field(min_length=20, max_length=200)


class ForgotPasswordInput(BaseModel):
    email: EmailStr


class ResetPasswordInput(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=12, max_length=200)


class ChangePasswordInput(BaseModel):
    current_password: str = Field(max_length=200)
    new_password: str = Field(min_length=12, max_length=200)


class ProfileInput(BaseModel):
    name: str = Field(default="", max_length=120)


class DeleteAccountInput(BaseModel):
    password: str = Field(max_length=200)


class SearchInput(BaseModel):
    q: str = ""
    category: str | None = None
    verified: bool | None = None
    limit: int = Field(default=20, ge=1, le=50)
    offset: int = Field(default=0, ge=0)


class ImportInput(BaseModel):
    repository_url: str = Field(min_length=18, max_length=500)
    skill_path: str | None = Field(default=None, max_length=300)
    category: str | None = Field(default=None, max_length=80)
    community: str = Field(default="", max_length=120)


class ImportSourceInput(BaseModel):
    repository_url: str = Field(min_length=18, max_length=500)
    skill_paths: list[str] = Field(default_factory=list, max_length=500)
    community: str = Field(default="", max_length=120)
    category: str | None = Field(default=None, max_length=80)

    @field_validator("skill_paths")
    @classmethod
    def validate_skill_paths(cls, value: list[str]) -> list[str]:
        paths = [path.strip().strip("/") for path in value]
        if any(not path or "\\" in path or ".." in path.split("/") or "\x00" in path for path in paths):
            raise ValueError("Skill paths must be safe repository-relative directories")
        if len(set(paths)) != len(paths):
            raise ValueError("Skill paths must be unique per repository")
        return paths


class ImportBatchInput(BaseModel):
    sources: list[ImportSourceInput] = Field(min_length=1, max_length=250)

    @model_validator(mode="after")
    def cap_selected_skills(self):
        if sum(len(source.skill_paths) for source in self.sources) > 5000:
            raise ValueError("A batch can select at most 5,000 skill folders")
        return self


class DecisionInput(BaseModel):
    decision: str
    reason: str = Field(min_length=4, max_length=1000)


class APIKeyInput(BaseModel):
    name: str = Field(default="AgentDock MCP", min_length=1, max_length=80)
    scopes: list[str] = Field(default_factory=lambda: ["skills:read", "library:read", "library:write", "account:read", "teams:read", "marketplace:read"], min_length=1, max_length=9)

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value) or not set(value).issubset(SUPPORTED_SCOPES):
            raise ValueError("Choose only the supported, non-duplicate API key scopes")
        return value


class CollectionInput(BaseModel):
    skill_id: str
    collection: str = Field(default="Favorites", min_length=1, max_length=80)


class CollectionCreateInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=300)
    team_id: str | None = None


class CollectionUpdateInput(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=300)


class TrustedPublisherInput(BaseModel):
    github_handle: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9-]+$")
    kind: str = Field(default="user", pattern=r"^(user|organization)$")
    trust_level: str = Field(default="verified", pattern=r"^(verified|established)$")
    notes: str = Field(default="", max_length=1000)


class RepositoryStatusInput(BaseModel):
    status: str
    reason: str = Field(min_length=4, max_length=1000)


class CheckoutInput(BaseModel):
    plan_code: str = Field(min_length=2, max_length=40)
    interval: str = Field(default="month", pattern=r"^(month|year)$")
    team_id: str | None = None


class CancelSubscriptionInput(BaseModel):
    reason: str = Field(default="", max_length=500)


class TeamCreateInput(BaseModel):
    name: str = Field(min_length=2, max_length=120)


class TeamUpdateInput(BaseModel):
    name: str = Field(min_length=2, max_length=120)


class TeamInviteInput(BaseModel):
    email: EmailStr
    role: str = Field(default="member", pattern=r"^(admin|member)$")


class TeamMemberUpdateInput(BaseModel):
    role: str = Field(pattern=r"^(admin|member)$")


class TeamAcceptInput(BaseModel):
    token: str = Field(min_length=20, max_length=200)


class ListingInput(BaseModel):
    skill_id: str
    title: str = Field(min_length=2, max_length=160)
    summary: str = Field(default="", max_length=3000)
    price_cents: int = Field(default=0, ge=0, le=1_000_000)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    team_id: str | None = None


class ListingUpdateInput(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=160)
    summary: str | None = Field(default=None, max_length=3000)
    price_cents: int | None = Field(default=None, ge=0, le=1_000_000)
    status: str | None = Field(default=None, pattern=r"^(draft|pending|approved|rejected|paused)$")
    featured: bool | None = None


class PurchaseInput(BaseModel):
    listing_id: str
    team_id: str | None = None


class ReviewInput(BaseModel):
    rating: int = Field(ge=1, le=5)
    body: str = Field(default="", max_length=2000)


class CreatorApplyInput(BaseModel):
    display_name: str = Field(min_length=2, max_length=120)
    bio: str = Field(default="", max_length=3000)
    website: str = Field(default="", max_length=300)


class CreatorStatusInput(BaseModel):
    status: str = Field(pattern=r"^(pending|approved|rejected|suspended)$")
    reason: str = Field(default="", max_length=1000)


class RightsRequestInput(BaseModel):
    requester_name: str = Field(min_length=2, max_length=120)
    requester_email: EmailStr
    skill_id: str | None = None
    repository_url: str = Field(default="", max_length=500)
    claim_type: str = Field(default="takedown", pattern=r"^(takedown|copyright|licence|privacy|other)$")
    details: str = Field(min_length=20, max_length=5000)


class RightsResolveInput(BaseModel):
    status: str = Field(pattern=r"^(open|reviewing|resolved|rejected)$")
    resolution: str = Field(min_length=4, max_length=3000)
    suspend_distribution: bool = False


class RoleInput(BaseModel):
    role: str = Field(pattern=r"^(free|developer|creator|admin|super_admin)$")


class UserStatusInput(BaseModel):
    active: bool
    reason: str = Field(min_length=4, max_length=500)


class PaymentActionInput(BaseModel):
    reason: str = Field(min_length=4, max_length=500)
    provider_ref: str = Field(default="", max_length=200)


class AdminSubscriptionInput(BaseModel):
    user_id: str | None = None
    team_id: str | None = None
    plan_code: str = Field(min_length=2, max_length=40)
    interval: str = Field(default="month", pattern=r"^(month|year)$")
    reason: str = Field(min_length=4, max_length=500)


class DiscoveryInput(BaseModel):
    topics: list[str] = Field(default_factory=list, max_length=20)
    keywords: list[str] = Field(default_factory=list, max_length=20)
    languages: list[str] = Field(default_factory=list, max_length=10)
    min_stars: int = Field(default=100, ge=0, le=1_000_000)
    per_page: int = Field(default=30, ge=1, le=100)


class SettingInput(BaseModel):
    key: str = Field(min_length=2, max_length=100)
    value: dict = Field(default_factory=dict)


class PlanInput(BaseModel):
    code: str = Field(min_length=2, max_length=40, pattern=r"^[a-z0-9-]+$")
    name: str = Field(min_length=2, max_length=80)
    description: str = Field(default="", max_length=300)
    price_cents: int = Field(default=0, ge=0, le=10_000_000)
    annual_price_cents: int = Field(default=0, ge=0, le=100_000_000)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    member_limit: int = Field(default=1, ge=1, le=1000)
    execution_quota: int = Field(default=20, ge=0, le=1_000_000)
    features: list[str] = Field(default_factory=list, max_length=30)
    is_active: bool = True
    sort_order: int = 0


class ListingStatusInput(BaseModel):
    status: str = Field(pattern=r"^(draft|pending|approved|rejected|paused)$")
    reason: str = Field(default="", max_length=1000)
    featured: bool | None = None


class SkillRightsInput(BaseModel):
    commercial_ok: bool
    reason: str = Field(min_length=4, max_length=1000)
