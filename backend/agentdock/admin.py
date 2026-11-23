"""Administrator control center, analytics, billing operations and webhooks."""
import hashlib
import hmac
import json
from collections import Counter
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from . import billing, discovery, mailer
from .common import (audit, db_session_dependency, listing_data, money, notify, public_base_url,
                     review_stats, skill_data, team_role, user_data, utcnow)
from .config import get_settings
from .models import (APIKey, AdmissionDecision, AuditLog, CreatorEarning, CreatorProfile, DiscoveryRun,
                     EmailToken, MarketplaceListing, Notification, Payment, Purchase, Repository, Review,
                     RightsRequest, SecurityScan, Skill, SkillVersion, Subscription, SubscriptionPlan,
                     SystemSetting, SynchronizationJob, Team, TeamMember, TrustedPublisher, UsageEvent, User)
from .schemas import (AdminSubscriptionInput, CreatorStatusInput, DiscoveryInput, ListingStatusInput,
                      PaymentActionInput, PlanInput, RightsResolveInput, RoleInput, SettingInput,
                      UserStatusInput)
from .security import admin_user

router = APIRouter(prefix="/api/v1")
settings = get_settings()
KNOWN_SETTINGS = {"discovery", "marketplace", "security", "general", "payment_prices"}


def _count(db: Session, model, *conditions) -> int:
    return db.scalar(select(func.count(model.id)).where(*conditions)) or 0


def _money(cents: int, currency: str = "USD") -> str:
    return money(cents, currency)


def _subscription_value(db: Session, subscription: Subscription) -> tuple[int, str, str]:
    plan = db.get(SubscriptionPlan, subscription.plan_code)
    if not plan:
        return 0, "USD", subscription.plan_code
    amount = plan.annual_price_cents if subscription.interval == "year" else plan.price_cents
    return amount, plan.currency, plan.name


def _analytics(db: Session) -> dict:
    now = utcnow()
    month_ago = now - timedelta(days=30)
    active_subs = db.scalars(select(Subscription).where(Subscription.status == "active")).all()
    mrr_cents = 0
    for subscription in active_subs:
        amount, _currency, _name = _subscription_value(db, subscription)
        mrr_cents += round(amount / 12) if subscription.interval == "year" else amount
    paid_payments = db.scalars(select(Payment).where(Payment.status == "paid")).all()
    gross_cents = sum(payment.amount_cents for payment in paid_payments)
    refunded = db.scalar(select(func.coalesce(func.sum(Payment.amount_cents), 0)).where(
        Payment.status == "refunded")) or 0
    marketplace_gmv = db.scalar(select(func.coalesce(func.sum(Purchase.amount_cents), 0)).where(
        Purchase.status == "paid")) or 0
    commission = 0
    for purchase in db.scalars(select(Purchase).where(Purchase.status == "paid")).all():
        listing = db.get(MarketplaceListing, purchase.listing_id)
        if listing:
            commission += round(purchase.amount_cents * listing.commission_bps / 10000)
    creator_liability = db.scalar(select(func.coalesce(func.sum(CreatorEarning.amount_cents), 0)).where(
        CreatorEarning.status == "pending")) or 0

    start = (now - timedelta(days=13)).date()
    series = {str(start + timedelta(days=index)): {"date": str(start + timedelta(days=index)),
                                                  "retrievals": 0, "signups": 0} for index in range(14)}
    for created_at in db.scalars(select(UsageEvent.created_at).where(
            UsageEvent.event == "skill.retrieved", UsageEvent.created_at >= now - timedelta(days=14))).all():
        key = str(created_at.date())
        if key in series:
            series[key]["retrievals"] += 1
    for created_at in db.scalars(select(User.created_at).where(User.created_at >= now - timedelta(days=14))).all():
        key = str(created_at.date())
        if key in series:
            series[key]["signups"] += 1

    status_counts = dict(db.execute(select(Skill.status, func.count(Skill.id)).group_by(Skill.status)).all())
    category_counts = [{"category": category, "count": count} for category, count in db.execute(
        select(Skill.category, func.count(Skill.id)).where(Skill.status == "approved")
        .group_by(Skill.category).order_by(func.count(Skill.id).desc()).limit(10)).all()]
    return {
        "generated_at": now,
        "users": {"total": _count(db, User), "new_30d": _count(db, User, User.created_at >= month_ago),
                  "active": _count(db, User, User.is_active.is_(True)),
                  "verified": _count(db, User, User.email_verified_at.is_not(None))},
        "workspaces": {"total": _count(db, Team),
                       "active": db.scalar(select(func.count(Team.id)).where(
                           Team.id.in_(select(TeamMember.team_id).distinct()))) or 0},
        "sync": {"total": _count(db, SynchronizationJob),
                 "queued": _count(db, SynchronizationJob, SynchronizationJob.status == "queued"),
                 "running": _count(db, SynchronizationJob, SynchronizationJob.status == "running"),
                 "failed": _count(db, SynchronizationJob, SynchronizationJob.status == "failed"),
                 "health": "healthy" if _count(db, SynchronizationJob, SynchronizationJob.status == "failed") == 0 else "degraded",
                 "last_completed_at": db.scalar(select(func.max(SynchronizationJob.completed_at)))},
        "revenue": {"gross_cents": gross_cents, "refunded_cents": refunded,
                    "net_cents": gross_cents - refunded, "mrr_cents": mrr_cents,
                    "arr_cents": mrr_cents * 12, "marketplace_gmv_cents": marketplace_gmv,
                    "commission_cents": commission, "creator_liability_cents": creator_liability,
                    "currency": settings.payment_currency},
        "subscriptions": {"active": len(active_subs),
                          "cancelling": sum(subscription.cancel_at_period_end for subscription in active_subs),
                          "by_plan": dict(Counter(subscription.plan_code for subscription in active_subs))},
        "catalogue": {"skills": _count(db, Skill), "approved": _count(db, Skill, Skill.status == "approved"),
                      "pending": _count(db, Skill, Skill.status.in_(["pending_review", "qualified"])),
                      "quarantined": _count(db, Skill, Skill.status == "quarantined"),
                      "premium": _count(db, Skill, Skill.is_premium.is_(True)),
                      "by_status": status_counts, "top_categories": category_counts,
                      "repositories": _count(db, Repository),
                      "discovered_repositories": _count(db, Repository, Repository.status == "discovered")},
        "marketplace": {"listings": _count(db, MarketplaceListing),
                        "pending_listings": _count(db, MarketplaceListing, MarketplaceListing.status == "pending"),
                        "purchases": _count(db, Purchase, Purchase.status == "paid"),
                        "creators": _count(db, CreatorProfile),
                        "pending_creators": _count(db, CreatorProfile, CreatorProfile.status == "pending"),
                        "reviews": _count(db, Review, Review.status == "published")},
        "operations": {"retrievals": _count(db, UsageEvent, UsageEvent.event == "skill.retrieved"),
                       "queued_jobs": _count(db, SynchronizationJob, SynchronizationJob.status == "queued"),
                       "running_jobs": _count(db, SynchronizationJob, SynchronizationJob.status == "running"),
                       "failed_jobs": _count(db, SynchronizationJob, SynchronizationJob.status == "failed"),
                       "open_rights": _count(db, RightsRequest, RightsRequest.status.in_(["open", "reviewing"])),
                       "security_findings": _count(db, SecurityScan, SecurityScan.status != "clear"),
                       "emails_sent": None,
                       "api_requests": _count(db, UsageEvent, UsageEvent.source == "api"),
                       "mcp_requests": _count(db, UsageEvent, UsageEvent.source == "mcp"),
                       "web_requests": _count(db, UsageEvent, UsageEvent.source == "web"),
                       "total_events": _count(db, UsageEvent),
                       "sync_health": "healthy" if _count(db, SynchronizationJob, SynchronizationJob.status == "failed") == 0 else "degraded",
                       "last_sync_at": db.scalar(select(func.max(SynchronizationJob.completed_at)))},
        "series": list(series.values()),
        "recent_users": [user_data(user) for user in db.scalars(
            select(User).order_by(User.created_at.desc()).limit(5)).all()],
        "recent_payments": [{"id": payment.id, "reference": payment.reference, "amount_cents": payment.amount_cents,
                             "currency": payment.currency, "status": payment.status, "purpose": payment.purpose,
                             "provider": payment.provider, "created_at": payment.created_at}
                            for payment in db.scalars(select(Payment).order_by(Payment.created_at.desc()).limit(5)).all()],
        "recent_decisions": [{"skill": (db.get(Skill, item.skill_id).name if db.get(Skill, item.skill_id) else "Removed skill"),
                              "decision": item.decision, "reason": item.reason,
                              "created_at": item.created_at}
                             for item in db.scalars(select(AdmissionDecision)
                                                    .order_by(AdmissionDecision.created_at.desc())
                                                    .limit(5)).all()],
        "recent_sync_jobs": [{"id": job.id, "repository_id": job.repository_id, "status": job.status,
                              "started_at": job.started_at, "completed_at": job.completed_at,
                              "error": job.error}
                             for job in db.scalars(select(SynchronizationJob)
                                                   .order_by(SynchronizationJob.created_at.desc())
                                                   .limit(5)).all()],
    }


@router.get("/admin/analytics")
def admin_analytics(request: Request, db: Session = Depends(db_session_dependency)):
    admin_user(request, db)
    return _analytics(db)


@router.get("/admin/users")
def admin_users(request: Request, q: str = "", role: str | None = None, limit: int = 50,
                offset: int = 0, db: Session = Depends(db_session_dependency)):
    admin_user(request, db)
    limit = min(max(limit, 1), 100)
    query = select(User)
    if q.strip():
        term = f"%{q.strip()[:80]}%"
        query = query.where(or_(User.email.ilike(term), User.name.ilike(term)))
    if role:
        query = query.where(User.role == role)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    users = db.scalars(query.order_by(User.created_at.desc()).offset(max(offset, 0)).limit(limit)).all()
    items = []
    for user in users:
        subscription = db.scalar(select(Subscription).where(
            Subscription.user_id == user.id, Subscription.status == "active")
            .order_by(Subscription.created_at.desc()))
        team_count = db.scalar(select(func.count(TeamMember.id)).where(TeamMember.user_id == user.id)) or 0
        items.append({**user_data(user), "is_active": user.is_active, "subscription": None if not subscription else {
            "plan_code": subscription.plan_code, "status": subscription.status,
            "interval": subscription.interval, "current_period_end": subscription.current_period_end},
            "teams": team_count,
            "skills_retrieved": db.scalar(select(func.count(UsageEvent.id)).where(
                UsageEvent.user_id == user.id, UsageEvent.event == "skill.retrieved")) or 0,
            "api_keys": db.scalar(select(func.count(APIKey.id)).where(
                APIKey.user_id == user.id, APIKey.revoked_at.is_(None))) or 0})
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.patch("/admin/users/{user_id}/role")
def admin_set_role(user_id: str, payload: RoleInput, request: Request,
                   db: Session = Depends(db_session_dependency)):
    admin = admin_user(request, db)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id and payload.role not in {"admin", "super_admin"}:
        raise HTTPException(status_code=422, detail="You cannot remove your own administrator access")
    previous = user.role
    user.role = payload.role
    audit(db, admin, "user.role_changed", "user", user.id, {"from": previous, "to": payload.role})
    notify(db, user.id, "Account role updated", f"Your account role is now {payload.role}.", kind="account")
    db.commit()
    return {"ok": True, "user": user_data(user)}


@router.post("/admin/users/{user_id}/status")
def admin_set_user_status(user_id: str, payload: UserStatusInput, request: Request,
                          db: Session = Depends(db_session_dependency)):
    admin = admin_user(request, db)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id and not payload.active:
        raise HTTPException(status_code=422, detail="You cannot deactivate your own account")
    user.is_active = payload.active
    if not payload.active:
        db.query(APIKey).filter(APIKey.user_id == user.id, APIKey.revoked_at.is_(None)).update(
            {"revoked_at": utcnow()})
    audit(db, admin, "user.status_changed", "user", user.id,
          {"active": payload.active, "reason": payload.reason})
    db.commit()
    return {"ok": True, "active": user.is_active}


@router.get("/admin/subscriptions")
def admin_subscriptions(request: Request, status: str | None = None, limit: int = 100,
                        db: Session = Depends(db_session_dependency)):
    admin_user(request, db)
    query = select(Subscription)
    if status:
        query = query.where(Subscription.status == status)
    rows = db.scalars(query.order_by(Subscription.created_at.desc()).limit(min(max(limit, 1), 200))).all()
    items = []
    for subscription in rows:
        plan = db.get(SubscriptionPlan, subscription.plan_code)
        user = db.get(User, subscription.user_id) if subscription.user_id else None
        team = db.get(Team, subscription.team_id) if subscription.team_id else None
        items.append({"id": subscription.id, "plan_code": subscription.plan_code,
                      "plan_name": plan.name if plan else subscription.plan_code,
                      "status": subscription.status, "interval": subscription.interval,
                      "provider": subscription.provider, "provider_ref": subscription.provider_ref,
                      "user_id": subscription.user_id, "user_email": user.email if user else None,
                      "team_id": subscription.team_id, "team_name": team.name if team else None,
                      "current_period_end": subscription.current_period_end,
                      "cancel_at_period_end": subscription.cancel_at_period_end,
                      "created_at": subscription.created_at})
    return {"items": items}


@router.post("/admin/subscriptions/activate", status_code=201)
def admin_activate_subscription(payload: AdminSubscriptionInput, request: Request,
                                db: Session = Depends(db_session_dependency)):
    admin = admin_user(request, db)
    plan = db.get(SubscriptionPlan, payload.plan_code)
    if not plan or not plan.is_active:
        raise HTTPException(status_code=404, detail="Subscription plan not found")
    if bool(payload.user_id) == bool(payload.team_id):
        raise HTTPException(status_code=422, detail="Choose exactly one user or team")
    if payload.user_id and not db.get(User, payload.user_id):
        raise HTTPException(status_code=404, detail="User not found")
    if payload.team_id and not db.get(Team, payload.team_id):
        raise HTTPException(status_code=404, detail="Team not found")
    amount = plan.annual_price_cents if payload.interval == "year" else plan.price_cents
    payment = Payment(user_id=payload.user_id, team_id=payload.team_id, purpose="subscription",
                      reference=f"ADMIN-{utcnow():%Y%m%d}-{hashlib.sha256((payload.reason + utcnow().isoformat()).encode()).hexdigest()[:8].upper()}",
                      provider="manual", amount_cents=amount, currency=plan.currency, status="pending",
                      metadata_json={"plan_code": plan.code, "interval": payload.interval,
                                     "team_id": payload.team_id, "admin_reason": payload.reason,
                                     "email": "", "name": ""})
    db.add(payment)
    db.flush()
    billing.fulfill_payment(db, payment, provider_ref=f"admin:{admin.id}")
    audit(db, admin, "subscription.activated_by_admin", "payment", payment.id,
          {"plan_code": plan.code, "interval": payload.interval, "reason": payload.reason,
           "user_id": payload.user_id, "team_id": payload.team_id})
    db.commit()
    return {"ok": True, "payment_id": payment.id, "reference": payment.reference}


@router.get("/admin/payments")
def admin_payments(request: Request, status: str | None = None, limit: int = 100,
                   db: Session = Depends(db_session_dependency)):
    admin_user(request, db)
    query = select(Payment)
    if status:
        query = query.where(Payment.status == status)
    payments = db.scalars(query.order_by(Payment.created_at.desc()).limit(min(max(limit, 1), 200))).all()
    items = []
    for payment in payments:
        user = db.get(User, payment.user_id) if payment.user_id else None
        items.append({"id": payment.id, "reference": payment.reference, "purpose": payment.purpose,
                      "amount_cents": payment.amount_cents, "currency": payment.currency,
                      "status": payment.status, "provider": payment.provider,
                      "provider_ref": payment.provider_ref, "checkout_url": payment.checkout_url,
                      "user_id": payment.user_id, "user_email": user.email if user else None,
                      "team_id": payment.team_id, "metadata": payment.metadata_json,
                      "created_at": payment.created_at, "paid_at": payment.paid_at})
    return {"items": items}


@router.post("/admin/payments/{payment_id}/fulfill")
def admin_fulfill_payment(payment_id: str, payload: PaymentActionInput, request: Request,
                          db: Session = Depends(db_session_dependency)):
    admin = admin_user(request, db)
    payment = db.get(Payment, payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    if payment.status == "paid":
        raise HTTPException(status_code=409, detail="This payment is already fulfilled")
    result = billing.fulfill_payment(db, payment, provider_ref=payload.provider_ref or f"manual:{admin.id}")
    audit(db, admin, "payment.fulfilled_by_admin", "payment", payment.id,
          {"reason": payload.reason, "amount_cents": payment.amount_cents})
    db.commit()
    return result


@router.post("/admin/payments/{payment_id}/refund")
def admin_refund_payment(payment_id: str, payload: PaymentActionInput, request: Request,
                         db: Session = Depends(db_session_dependency)):
    admin = admin_user(request, db)
    payment = db.get(Payment, payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    result = billing.refund_payment(db, payment, payload.reason)
    audit(db, admin, "payment.refunded_by_admin", "payment", payment.id, {"reason": payload.reason})
    db.commit()
    return result


@router.get("/admin/plans")
def admin_plans(request: Request, db: Session = Depends(db_session_dependency)):
    admin_user(request, db)
    plans = db.scalars(select(SubscriptionPlan).order_by(SubscriptionPlan.sort_order,
                                                        SubscriptionPlan.price_cents)).all()
    return {"items": [{"code": plan.code, "name": plan.name, "description": plan.description,
                       "price_cents": plan.price_cents, "annual_price_cents": plan.annual_price_cents,
                       "currency": plan.currency, "member_limit": plan.member_limit,
                       "features": plan.features, "is_active": plan.is_active,
                       "sort_order": plan.sort_order} for plan in plans]}


@router.post("/admin/plans", status_code=201)
def admin_create_plan(payload: PlanInput, request: Request, db: Session = Depends(db_session_dependency)):
    admin = admin_user(request, db)
    if db.get(SubscriptionPlan, payload.code):
        raise HTTPException(status_code=409, detail="A plan with that code already exists")
    plan = SubscriptionPlan(**payload.model_dump())
    db.add(plan)
    audit(db, admin, "plan.created", "subscription_plan", plan.code, payload.model_dump())
    db.commit()
    return {"ok": True, "code": plan.code}


@router.patch("/admin/plans/{code}")
def admin_update_plan(code: str, payload: PlanInput, request: Request,
                      db: Session = Depends(db_session_dependency)):
    admin = admin_user(request, db)
    plan = db.get(SubscriptionPlan, code)
    if not plan:
        raise HTTPException(status_code=404, detail="Subscription plan not found")
    for key, value in payload.model_dump().items():
        if key != "code":
            setattr(plan, key, value)
    audit(db, admin, "plan.updated", "subscription_plan", code, payload.model_dump())
    db.commit()
    return {"ok": True, "code": plan.code}


@router.get("/admin/marketplace/listings")
def admin_listings(request: Request, status: str | None = None, limit: int = 100,
                   db: Session = Depends(db_session_dependency)):
    admin_user(request, db)
    query = select(MarketplaceListing)
    if status:
        query = query.where(MarketplaceListing.status == status)
    listings = db.scalars(query.order_by(MarketplaceListing.created_at.desc())
                          .limit(min(max(limit, 1), 200))).all()
    items = []
    for listing in listings:
        data = listing_data(db, listing)
        skill = db.get(Skill, listing.skill_id)
        data["skill_status"] = skill.status if skill else "missing"
        data["commercial_ok"] = skill.commercial_ok if skill else False
        items.append(data)
    return {"items": items}


@router.post("/admin/marketplace/listings/{listing_id}/status")
def admin_listing_status(listing_id: str, payload: ListingStatusInput, request: Request,
                         db: Session = Depends(db_session_dependency)):
    admin = admin_user(request, db)
    listing = db.get(MarketplaceListing, listing_id)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    skill = db.get(Skill, listing.skill_id)
    if payload.status == "approved":
        if not skill or skill.status != "approved":
            raise HTTPException(status_code=422, detail="The underlying skill must be approved first")
        if not skill.commercial_ok:
            raise HTTPException(status_code=422, detail="The skill is not cleared for commercial distribution")
        listing.published_at = listing.published_at or utcnow()
    listing.status = payload.status
    if payload.featured is not None:
        listing.featured = payload.featured
    if skill:
        skill.is_premium = listing.price_cents > 0 and payload.status == "approved"
    audit(db, admin, "marketplace.listing_reviewed", "listing", listing.id,
          {"status": payload.status, "reason": payload.reason, "featured": payload.featured})
    if listing.creator_id:
        notify(db, listing.creator_id, f"Listing {payload.status}",
               f"{listing.title}: {payload.reason or 'The review status changed.'}",
               kind="marketplace", link="/marketplace")
    db.commit()
    return {"ok": True, "status": listing.status}


@router.get("/admin/creators")
def admin_creators(request: Request, status: str | None = None, db: Session = Depends(db_session_dependency)):
    admin_user(request, db)
    query = select(CreatorProfile)
    if status:
        query = query.where(CreatorProfile.status == status)
    profiles = db.scalars(query.order_by(CreatorProfile.created_at.desc()).limit(200)).all()
    items = []
    for profile in profiles:
        user = db.get(User, profile.user_id)
        earnings = db.scalar(select(func.coalesce(func.sum(CreatorEarning.amount_cents), 0)).where(
            CreatorEarning.creator_id == profile.user_id,
            CreatorEarning.status != "reversed")) or 0
        pending = db.scalar(select(func.coalesce(func.sum(CreatorEarning.amount_cents), 0)).where(
            CreatorEarning.creator_id == profile.user_id, CreatorEarning.status == "pending")) or 0
        items.append({"user_id": profile.user_id, "email": user.email if user else "",
                      "display_name": profile.display_name, "bio": profile.bio,
                      "website": profile.website, "status": profile.status,
                      "revenue_share_bps": profile.revenue_share_bps,
                      "earnings_cents": earnings, "pending_cents": pending,
                      "listings": db.scalar(select(func.count(MarketplaceListing.id)).where(
                          MarketplaceListing.creator_id == profile.user_id)) or 0,
                      "created_at": profile.created_at})
    return {"items": items}


@router.post("/admin/creators/{user_id}/status")
def admin_creator_status(user_id: str, payload: CreatorStatusInput, request: Request,
                         db: Session = Depends(db_session_dependency)):
    admin = admin_user(request, db)
    profile = db.scalar(select(CreatorProfile).where(CreatorProfile.user_id == user_id))
    if not profile:
        raise HTTPException(status_code=404, detail="Creator profile not found")
    previous = profile.status
    profile.status = payload.status
    user = db.get(User, user_id)
    if user and payload.status == "approved" and user.role in {"free", "developer"}:
        user.role = "creator"
    audit(db, admin, "creator.reviewed", "creator_profile", profile.id,
          {"from": previous, "to": payload.status, "reason": payload.reason})
    notify(db, user_id, f"Creator application {payload.status}",
           payload.reason or "Your creator status changed.", kind="marketplace", link="/marketplace")
    db.commit()
    return {"ok": True, "status": profile.status}


@router.get("/admin/rights-requests")
def admin_rights_requests(request: Request, status: str | None = None,
                          db: Session = Depends(db_session_dependency)):
    admin_user(request, db)
    query = select(RightsRequest)
    if status:
        query = query.where(RightsRequest.status == status)
    requests = db.scalars(query.order_by(RightsRequest.created_at.desc()).limit(200)).all()
    items = []
    for item in requests:
        skill = db.get(Skill, item.skill_id) if item.skill_id else None
        items.append({"id": item.id, "requester_name": item.requester_name,
                      "requester_email": item.requester_email, "claim_type": item.claim_type,
                      "details": item.details, "repository_url": item.repository_url,
                      "skill_id": item.skill_id, "skill_name": skill.name if skill else None,
                      "skill_status": skill.status if skill else None, "status": item.status,
                      "resolution": item.resolution, "created_at": item.created_at,
                      "resolved_at": item.resolved_at})
    return {"items": items}


@router.post("/admin/rights-requests/{request_id}/resolve")
def admin_resolve_rights(request_id: str, payload: RightsResolveInput, request: Request,
                         db: Session = Depends(db_session_dependency)):
    admin = admin_user(request, db)
    item = db.get(RightsRequest, request_id)
    if not item:
        raise HTTPException(status_code=404, detail="Rights request not found")
    item.status = payload.status
    item.resolution = payload.resolution
    if payload.status in {"resolved", "rejected"}:
        item.resolved_at = utcnow()
    if payload.suspend_distribution and item.skill_id:
        skill = db.get(Skill, item.skill_id)
        if skill:
            skill.status = "withdrawn"
            listing = db.scalar(select(MarketplaceListing).where(MarketplaceListing.skill_id == skill.id))
            if listing:
                listing.status = "paused"
    audit(db, admin, "rights_request.resolved", "rights_request", item.id,
          {"status": payload.status, "suspend_distribution": payload.suspend_distribution,
           "resolution": payload.resolution})
    db.commit()
    return {"ok": True, "status": item.status}


@router.get("/admin/settings")
def admin_get_settings(request: Request, db: Session = Depends(db_session_dependency)):
    admin_user(request, db)
    rows = db.scalars(select(SystemSetting).order_by(SystemSetting.key)).all()
    return {
        "items": [{"key": row.key, "value": row.value, "updated_at": row.updated_at} for row in rows],
        "capabilities": {
            "email": {"configured": settings.smtp_configured,
                      "from": settings.smtp_from if settings.smtp_configured else "",
                      "require_verification": settings.require_email_verification},
            "payments": billing.provider_status(),
            "providers": billing.all_providers(),
            "discovery": {"github_token": bool(settings.github_token),
                          "webhook_secret": bool(settings.github_webhook_secret)},
            "storage": {"s3": bool(settings.s3_bucket), "path": str(settings.storage_path)},
            "environment": settings.env,
        },
    }


@router.patch("/admin/settings")
def admin_update_settings(payload: list[SettingInput], request: Request,
                          db: Session = Depends(db_session_dependency)):
    admin = admin_user(request, db)
    if not payload or len(payload) > 20:
        raise HTTPException(status_code=422, detail="Send between 1 and 20 settings")
    updated = []
    for item in payload:
        if item.key not in KNOWN_SETTINGS:
            raise HTTPException(status_code=422, detail=f"Unknown setting: {item.key}")
        row = db.get(SystemSetting, item.key)
        if row:
            row.value = item.value
            row.updated_by = admin.id
        else:
            row = SystemSetting(key=item.key, value=item.value, updated_by=admin.id)
            db.add(row)
        updated.append(item.key)
    audit(db, admin, "settings.updated", "system", "", {"keys": updated})
    db.commit()
    return {"ok": True, "updated": updated}


@router.get("/admin/discovery")
def admin_discovery(request: Request, db: Session = Depends(db_session_dependency)):
    admin_user(request, db)
    runs = db.scalars(select(DiscoveryRun).order_by(DiscoveryRun.created_at.desc()).limit(20)).all()
    return {"config": discovery.discovery_settings(db),
            "runs": [{"id": run.id, "source": run.source, "status": run.status,
                      "query": run.query, "candidates_found": run.candidates_found,
                      "created_count": run.created_count, "error": run.error,
                      "created_at": run.created_at, "completed_at": run.completed_at}
                     for run in runs],
            "github_token_configured": bool(settings.github_token)}


@router.post("/admin/discovery")
def admin_save_discovery(payload: DiscoveryInput, request: Request,
                         db: Session = Depends(db_session_dependency)):
    admin = admin_user(request, db)
    value = discovery.save_discovery_settings(db, payload.model_dump(), admin.id)
    audit(db, admin, "discovery.settings_updated", "system", "discovery", payload.model_dump())
    db.commit()
    return {"ok": True, "config": value}


@router.post("/admin/discovery/run", status_code=202)
def admin_run_discovery(request: Request, db: Session = Depends(db_session_dependency)):
    admin = admin_user(request, db)
    try:
        result = discovery.run_discovery(db, triggered_by=admin.id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="GitHub discovery failed. Check the server token and network access.") from exc
    audit(db, admin, "discovery.run", "discovery_run", result["id"],
          {"candidates_found": result["candidates_found"], "created_count": result["created_count"]})
    db.commit()
    return result


@router.get("/admin/security")
def admin_security(request: Request, db: Session = Depends(db_session_dependency)):
    admin_user(request, db)
    scans = db.scalars(select(SecurityScan).order_by(SecurityScan.created_at.desc()).limit(100)).all()
    return {
        "summary": {"scans": _count(db, SecurityScan),
                    "clear": _count(db, SecurityScan, SecurityScan.status == "clear"),
                    "flagged": _count(db, SecurityScan, SecurityScan.status != "clear"),
                    "trusted_publishers": _count(db, TrustedPublisher),
                    "open_rights": _count(db, RightsRequest, RightsRequest.status.in_(["open", "reviewing"]))},
        "scans": [{"id": scan.id, "skill_id": scan.skill_id,
                   "skill_name": (db.get(Skill, scan.skill_id).name if db.get(Skill, scan.skill_id) else "Removed skill"),
                   "status": scan.status, "findings": scan.findings, "scanner": scan.scanner,
                   "created_at": scan.created_at} for scan in scans],
        "risky_skills": [{"id": skill.id, "name": skill.name, "slug": skill.slug,
                          "security_status": skill.security_status, "status": skill.status}
                         for skill in db.scalars(select(Skill).where(
                             Skill.security_status != "clear").limit(50)).all()],
    }


@router.get("/admin/system")
def admin_system(request: Request, db: Session = Depends(db_session_dependency)):
    admin_user(request, db)
    return {
        "environment": settings.env,
        "public_url": settings.public_url,
        "payment_provider": billing.provider_status(),
        "payment_providers": billing.all_providers(),
        "email_configured": settings.smtp_configured,
        "email_verification_required": settings.require_email_verification,
        "github_token_configured": bool(settings.github_token),
        "github_webhook_configured": bool(settings.github_webhook_secret),
        "storage": "s3" if settings.s3_bucket else "local",
        "counts": {"users": _count(db, User), "skills": _count(db, Skill),
                   "teams": _count(db, Team), "payments": _count(db, Payment)},
    }


@router.post("/webhooks/github")
async def github_webhook(request: Request, db: Session = Depends(db_session_dependency)):
    """Queue a resync when a tracked repository receives a push.

    GitHub signs the raw request body. Unsigned or stale requests are rejected
    before any database work happens.
    """
    if not settings.github_webhook_secret:
        raise HTTPException(status_code=503, detail="GitHub webhooks are not configured")
    raw = await request.body()
    if len(raw) > 2_000_000:
        raise HTTPException(status_code=413, detail="Webhook payload is too large")
    signature = request.headers.get("x-hub-signature-256", "")
    expected = "sha256=" + hmac.new(settings.github_webhook_secret.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=403, detail="Invalid webhook signature")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Invalid webhook payload")
    event = request.headers.get("x-github-event", "")
    if event == "ping":
        return {"ok": True, "pong": True}
    if event != "push":
        return {"ok": True, "ignored": True}
    full_name = (payload.get("repository") or {}).get("full_name", "")
    if not full_name:
        return {"ok": True, "ignored": True}
    canonical = f"https://github.com/{full_name}"
    repository = db.scalar(select(Repository).where(Repository.url == canonical))
    if not repository:
        return {"ok": True, "ignored": True, "reason": "repository is not tracked"}
    if repository.status != "approved":
        return {"ok": True, "ignored": True, "reason": "repository is not approved for synchronization"}
    active = db.scalar(select(SynchronizationJob.id).where(
        SynchronizationJob.repository_id == repository.id,
        SynchronizationJob.status.in_(["queued", "running"])).limit(1))
    if active:
        return {"ok": True, "queued": False, "reason": "work is already queued"}
    repository.last_commit_sha = str(payload.get("after", ""))[:64]
    db.add(SynchronizationJob(repository_id=repository.id, source_url=repository.url,
                              operation="sync", status="queued"))
    db.add(AuditLog(action="repository.push_webhook", target_type="repository",
                    target_id=repository.id, details={"ref": payload.get("ref", "")}))
    db.commit()
    return {"ok": True, "queued": True, "repository": repository.url}
