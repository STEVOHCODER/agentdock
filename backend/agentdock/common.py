"""Shared domain helpers used by the REST API, MCP and admin modules."""
from datetime import datetime, timedelta, timezone
from typing import Iterable

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .admission import REDISTRIBUTION_LICENSES
from .config import get_settings
from .models import (AuditLog, Collection, CollectionItem, EmailToken, MarketplaceListing, Notification, Purchase,
                     Review, Skill, SkillVersion, Subscription, SubscriptionPlan, Team, TeamMember, UsageEvent,
                     User, utcnow)
from .security import hash_token


def db_session_dependency():
    from .db import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def user_data(user: User) -> dict:
    return {
        "id": user.id, "email": user.email, "name": user.name, "role": user.role,
        "email_verified": bool(user.email_verified_at), "created_at": user.created_at,
        "last_login_at": user.last_login_at,
    }


def audit(db: Session, actor: User | None, action: str, target_type: str = "",
          target_id: str = "", details: dict | None = None) -> None:
    db.add(AuditLog(actor_id=actor.id if actor else None, action=action, target_type=target_type,
                    target_id=target_id, details=details or {}))


def notify(db: Session, user_id: str | None, title: str, body: str = "", *,
           kind: str = "system", link: str = "", audience: str = "user") -> None:
    db.add(Notification(user_id=user_id, audience=audience, kind=kind, title=title, body=body, link=link))


def public_base_url(request=None) -> str:
    configured = get_settings().public_url.strip().rstrip("/")
    if configured and configured != "http://localhost:5173":
        return configured
    if request is not None:
        return str(request.base_url).rstrip("/")
    return configured or "http://localhost:8000"


def get_skill(db: Session, identifier: str, include_unapproved: bool = False) -> Skill:
    skill = db.scalar(select(Skill).where((Skill.id == identifier) | (Skill.slug == identifier)))
    if not skill or (not include_unapproved and skill.status != "approved"):
        raise HTTPException(status_code=404, detail="Skill not found")
    return skill


def must_have_license(skill: Skill) -> None:
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


def listing_for_skill(db: Session, skill_id: str, public_only: bool = False) -> MarketplaceListing | None:
    query = select(MarketplaceListing).where(MarketplaceListing.skill_id == skill_id)
    if public_only:
        query = query.where(MarketplaceListing.status == "approved")
    return db.scalar(query)


def review_stats(db: Session, listing_id: str) -> tuple[float, int]:
    row = db.execute(select(func.avg(Review.rating), func.count(Review.id)).where(
        Review.listing_id == listing_id, Review.status == "published")).one()
    return (round(float(row[0] or 0), 1), int(row[1] or 0))


def listing_data(db: Session, listing: MarketplaceListing, include_skill: bool = True) -> dict:
    skill = db.get(Skill, listing.skill_id) if include_skill else None
    rating, count = review_stats(db, listing.id)
    creator = db.get(User, listing.creator_id) if listing.creator_id else None
    result = {
        "id": listing.id, "skill_id": listing.skill_id, "title": listing.title,
        "summary": listing.summary, "price_cents": listing.price_cents, "currency": listing.currency,
        "status": listing.status, "featured": listing.featured, "commission_bps": listing.commission_bps,
        "creator": creator.name or creator.email.split("@")[0] if creator else "AgentDock Studio",
        "creator_id": listing.creator_id, "rating": rating, "review_count": count,
        "published_at": listing.published_at, "created_at": listing.created_at,
    }
    if skill:
        result["skill"] = {
            "id": skill.id, "slug": skill.slug, "name": skill.name, "description": skill.description,
            "category": skill.category, "creator": skill.creator, "license": skill.license_id,
            "version": skill.latest_version, "security_status": skill.security_status,
            "source_url": skill.source_url, "stars": skill.stars, "technologies": skill.technologies,
            "compatibility": skill.compatibility,
        }
    return result


def skill_data(skill: Skill, repository=None, listing: MarketplaceListing | None = None,
               rating: float = 0.0, review_count: int = 0) -> dict:
    return {
        "id": skill.id, "slug": skill.slug, "name": skill.name, "description": skill.description,
        "category": skill.category, "creator": skill.creator, "license": skill.license_id,
        "source_url": skill.source_url, "stars": skill.stars, "score": skill.score,
        "verified": skill.status == "approved", "status": skill.status,
        "security_status": skill.security_status, "version": skill.latest_version,
        "premium": skill.is_premium, "featured": skill.is_featured,
        "community": skill.community or (repository.community if repository else ""),
        "updated_at": skill.updated_at, "technologies": skill.technologies or [],
        "compatibility": skill.compatibility or [], "dependencies": skill.dependencies or [],
        "permissions": skill.permissions or [], "changelog": skill.changelog or "",
        "commercial_ok": skill.commercial_ok,
        "repository": repository.url if repository else skill.source_url,
        "listing_id": listing.id if listing else None,
        "price_cents": listing.price_cents if listing else 0,
        "currency": listing.currency if listing else "USD",
        "rating": rating, "review_count": review_count,
    }


def enrich_skill(db: Session, skill: Skill, repository=None) -> dict:
    listing = listing_for_skill(db, skill.id, public_only=True)
    rating, count = review_stats(db, listing.id) if listing else (0.0, 0)
    return skill_data(skill, repository, listing, rating, count)


def active_subscription(db: Session, *, user_id: str | None = None, team_id: str | None = None) -> Subscription | None:
    now = utcnow()
    query = select(Subscription).where(Subscription.status == "active")
    if user_id:
        query = query.where(Subscription.user_id == user_id, Subscription.team_id.is_(None))
    elif team_id:
        query = query.where(Subscription.team_id == team_id)
    else:
        return None
    subscription = db.scalar(query.order_by(Subscription.created_at.desc()))
    if not subscription:
        return None
    end = subscription.current_period_end
    if end is not None:
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        if end <= now:
            subscription.status = "expired"
            db.commit()
            return None
    return subscription


def plan_by_code(db: Session, code: str) -> SubscriptionPlan:
    plan = db.get(SubscriptionPlan, code)
    if not plan:
        raise HTTPException(status_code=404, detail="Subscription plan not found")
    return plan


def free_plan(db: Session) -> SubscriptionPlan:
    plan = db.get(SubscriptionPlan, "free")
    if plan:
        return plan
    plan = SubscriptionPlan(code="free", name="Free", description="Catalogue access", price_cents=0,
                            annual_price_cents=0, member_limit=1, features=[
                                "Public skill discovery", "Basic skill retrieval", "Basic MCP integration",
                                "Access to free community skills"], sort_order=0)
    db.add(plan)
    db.commit()
    return plan


def team_ids_for(db: Session, user_id: str) -> list[str]:
    return list(db.scalars(select(TeamMember.team_id).where(TeamMember.user_id == user_id)).all())


def team_role(db: Session, team_id: str, user_id: str) -> str | None:
    member = db.scalar(select(TeamMember).where(TeamMember.team_id == team_id, TeamMember.user_id == user_id))
    return member.role if member else None


def require_team_role(db: Session, team_id: str, user_id: str, roles: Iterable[str] = ("owner", "admin")) -> TeamMember:
    member = db.scalar(select(TeamMember).where(TeamMember.team_id == team_id, TeamMember.user_id == user_id))
    if not member or member.role not in set(roles):
        raise HTTPException(status_code=403, detail="You do not have permission to manage this team")
    return member


def user_plan(db: Session, user: User, team_id: str | None = None) -> tuple[SubscriptionPlan, Subscription | None]:
    if team_id:
        team = db.get(Team, team_id)
        if team and team_role(db, team.id, user.id):
            subscription = active_subscription(db, team_id=team.id)
            plan_code = subscription.plan_code if subscription else team.plan_code
            plan = db.get(SubscriptionPlan, plan_code) or free_plan(db)
            return plan, subscription
    subscription = active_subscription(db, user_id=user.id)
    plan = db.get(SubscriptionPlan, subscription.plan_code) if subscription else free_plan(db)
    return plan or free_plan(db), subscription


def entitlement_summary(db: Session, user: User, team_id: str | None = None) -> dict:
    plan, subscription = user_plan(db, user, team_id)
    teams = []
    for team in db.scalars(select(Team).join(TeamMember, TeamMember.team_id == Team.id)
                           .where(TeamMember.user_id == user.id).order_by(Team.created_at)).all():
        role = team_role(db, team.id, user.id)
        member_count = db.scalar(select(func.count(TeamMember.id)).where(TeamMember.team_id == team.id)) or 0
        teams.append({"id": team.id, "name": team.name, "role": role, "plan_code": team.plan_code,
                      "seat_limit": team.seat_limit, "member_count": member_count})
    return {
        "plan_code": plan.code, "plan_name": plan.name,
        "status": subscription.status if subscription else "active",
        "interval": subscription.interval if subscription else "month",
        "current_period_end": subscription.current_period_end if subscription else None,
        "cancel_at_period_end": subscription.cancel_at_period_end if subscription else False,
        "features": plan.features or [], "member_limit": plan.member_limit,
        "teams": teams, "premium_entitlements": [
            purchase.listing_id for purchase in db.scalars(select(Purchase).where(
                Purchase.user_id == user.id, Purchase.status == "paid")).all()
        ],
    }


def premium_entitlement(db: Session, user: User, skill: Skill) -> bool:
    if not skill.is_premium:
        return True
    if user.role in {"admin", "super_admin"}:
        return True
    listing = listing_for_skill(db, skill.id, public_only=True)
    if not listing:
        return False
    if listing.price_cents == 0:
        return True
    team_ids = team_ids_for(db, user.id)
    owners = [Purchase.user_id == user.id]
    if team_ids:
        owners.append(Purchase.team_id.in_(team_ids))
    purchase = db.scalar(select(Purchase).where(
        Purchase.listing_id == listing.id, Purchase.status == "paid", or_(*owners),
    ).limit(1))
    return purchase is not None


def record_usage(db: Session, user: User | None, skill: Skill | None, event: str, source: str,
                 team_id: str | None = None, details: dict | None = None) -> None:
    db.add(UsageEvent(user_id=user.id if user else None, team_id=team_id, skill_id=skill.id if skill else None,
                      event=event, source=source, details=details or {}))


def ensure_default_collection(db: Session, user: User) -> Collection:
    collection = db.scalar(select(Collection).where(Collection.user_id == user.id, Collection.team_id.is_(None))
                           .order_by(Collection.created_at).limit(1))
    if not collection:
        collection = Collection(user_id=user.id, name="Favorites", description="Your saved skills")
        db.add(collection)
        db.commit()
    return collection


def collection_access(db: Session, collection_id: str, user: User, write: bool = False) -> Collection:
    collection = db.get(Collection, collection_id)
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")
    if collection.team_id:
        role = team_role(db, collection.team_id, user.id)
        if role is None:
            raise HTTPException(status_code=403, detail="This shared collection belongs to another team")
        if write and role not in {"owner", "admin", "member"}:
            raise HTTPException(status_code=403, detail="You cannot modify this collection")
    elif collection.user_id != user.id:
        raise HTTPException(status_code=403, detail="This collection belongs to another account")
    return collection


def create_email_token(db: Session, user: User, purpose: str, minutes: int) -> str:
    import secrets
    raw = secrets.token_urlsafe(32)
    db.add(EmailToken(user_id=user.id, purpose=purpose, token_hash=hash_token(raw),
                      expires_at=datetime.now(timezone.utc) + timedelta(minutes=minutes)))
    return raw


def money(amount_cents: int, currency: str = "USD") -> str:
    return f"{currency} {amount_cents / 100:,.2f}"


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def paginate(query, limit: int, offset: int):
    return query.limit(min(max(limit, 1), 100)).offset(max(offset, 0))


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
