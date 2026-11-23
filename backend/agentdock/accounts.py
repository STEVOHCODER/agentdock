"""Account, team, collection, marketplace and billing API routes."""
from datetime import datetime, timedelta, timezone
import re
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from . import billing, mailer
from .common import (active_subscription, audit, collection_access, create_email_token, db_session_dependency,
                     ensure_default_collection, entitlement_summary, listing_data, listing_for_skill, money,
                     notify, premium_entitlement, public_base_url, record_usage, require_team_role, review_stats,
                     skill_data, team_ids_for, team_role, user_data, user_plan)
from .config import get_settings
from .models import (APIKey, Collection, CollectionItem, CreatorEarning, CreatorProfile, EmailToken,
                     MarketplaceListing, Notification, Payment, Purchase, Review, Skill, Subscription,
                     SubscriptionPlan, Team, TeamInvitation, TeamMember, UsageEvent, User, UserSession, utcnow)
from .schemas import (CancelSubscriptionInput, ChangePasswordInput, CheckoutInput, CollectionCreateInput,
                      CollectionUpdateInput, CreatorApplyInput, DeleteAccountInput, ForgotPasswordInput,
                      ListingInput, ListingUpdateInput, ProfileInput, PurchaseInput, RegisterInput,
                      ResetPasswordInput, ReviewInput, RightsRequestInput, TeamAcceptInput, TeamCreateInput,
                      TeamInviteInput, TeamMemberUpdateInput, TeamUpdateInput, VerifyEmailInput)
from .security import current_user, hash_token, issue_api_key, password_hash, require_scope, verify_password

router = APIRouter(prefix="/api/v1")
settings = get_settings()


def _set_session(response: Response, db: Session, user: User) -> None:
    from .security import create_session
    token = create_session(db, user)
    response.set_cookie("agentdock_session", token, httponly=True, secure=settings.session_secure_cookie,
                        samesite="lax", max_age=settings.session_days * 86400, path="/")


def _debug_link(request: Request, path: str, token: str) -> str | None:
    if settings.env == "production" or settings.smtp_configured:
        return None
    return f"{public_base_url(request)}/#/{path}?token={token}"


# ---------------------------------------------------------------------------
# Email verification and password recovery
# ---------------------------------------------------------------------------

@router.post("/auth/verify-email")
def verify_email(payload: VerifyEmailInput, request: Request, db: Session = Depends(db_session_dependency)):
    token = db.scalar(select(EmailToken).where(EmailToken.token_hash == hash_token(payload.token),
                                                EmailToken.purpose == "verify_email"))
    if not token or token.used_at or token.expires_at.replace(tzinfo=timezone.utc) < utcnow():
        raise HTTPException(status_code=422, detail="This verification link is invalid or has expired")
    user = db.get(User, token.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Account not found")
    user.email_verified_at = utcnow()
    token.used_at = utcnow()
    audit(db, user, "account.email_verified", "user", user.id)
    db.commit()
    return {"ok": True, "email_verified": True, "user": user_data(user)}


@router.post("/auth/resend-verification")
def resend_verification(request: Request, db: Session = Depends(db_session_dependency)):
    user = current_user(request, db)
    require_scope(request, "account:read")
    if user.email_verified_at:
        return {"ok": True, "message": "Email is already verified."}
    token = create_email_token(db, user, "verify_email", 24 * 60)
    db.commit()
    link = f"{public_base_url(request)}/#/verify-email?token={token}"
    sent = mailer.send_verification(user.email, link)
    return {"ok": True, "sent": sent, "debug_link": _debug_link(request, "verify-email", token)}


@router.post("/auth/forgot-password")
def forgot_password(payload: ForgotPasswordInput, request: Request, db: Session = Depends(db_session_dependency)):
    user = db.scalar(select(User).where(User.email == str(payload.email).lower(), User.is_active.is_(True)))
    debug = None
    if user:
        token = create_email_token(db, user, "reset_password", 60)
        db.commit()
        link = f"{public_base_url(request)}/#/reset-password?token={token}"
        mailer.send_password_reset(user.email, link)
        debug = _debug_link(request, "reset-password", token)
    return {"ok": True, "message": "If an account exists, a reset link has been sent.",
            "debug_link": debug}


@router.post("/auth/reset-password")
def reset_password(payload: ResetPasswordInput, response: Response, db: Session = Depends(db_session_dependency)):
    token = db.scalar(select(EmailToken).where(EmailToken.token_hash == hash_token(payload.token),
                                                EmailToken.purpose == "reset_password"))
    if not token or token.used_at or token.expires_at.replace(tzinfo=timezone.utc) < utcnow():
        raise HTTPException(status_code=422, detail="This reset link is invalid or has expired")
    user = db.get(User, token.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=404, detail="Account not found")
    user.password_hash = password_hash(payload.password)
    user.email_verified_at = user.email_verified_at or utcnow()
    token.used_at = utcnow()
    db.query(UserSession).filter(UserSession.user_id == user.id).delete()
    audit(db, user, "account.password_reset", "user", user.id)
    db.commit()
    _set_session(response, db, user)
    db.commit()
    return {"ok": True, "user": user_data(user)}


# ---------------------------------------------------------------------------
# Account
# ---------------------------------------------------------------------------

@router.get("/plans")
def public_plans(db: Session = Depends(db_session_dependency)):
    plans = db.scalars(select(SubscriptionPlan).where(SubscriptionPlan.is_active.is_(True))
                       .order_by(SubscriptionPlan.sort_order, SubscriptionPlan.price_cents)).all()
    return {"items": [{"code": p.code, "name": p.name, "description": p.description,
                       "price_cents": p.price_cents, "annual_price_cents": p.annual_price_cents,
                       "currency": p.currency, "member_limit": p.member_limit, "execution_quota": p.execution_quota, "features": p.features} for p in plans],
            "billing": billing.provider_status(), "providers": billing.all_providers()}


@router.get("/account/entitlements")
def account_entitlements(request: Request, team_id: str | None = None, db: Session = Depends(db_session_dependency)):
    user = current_user(request, db)
    require_scope(request, "account:read")
    return entitlement_summary(db, user, team_id)


@router.get("/account/subscription")
def account_subscription(request: Request, team_id: str | None = None, db: Session = Depends(db_session_dependency)):
    user = current_user(request, db)
    require_scope(request, "account:read")
    summary = entitlement_summary(db, user, team_id)
    subscription = None
    if team_id:
        subscription = active_subscription(db, team_id=team_id)
    else:
        subscription = active_subscription(db, user_id=user.id)
    return {"entitlements": summary,
            "subscription": None if not subscription else {
                "id": subscription.id, "plan_code": subscription.plan_code, "status": subscription.status,
                "interval": subscription.interval, "provider": subscription.provider,
                "current_period_start": subscription.current_period_start,
                "current_period_end": subscription.current_period_end,
                "cancel_at_period_end": subscription.cancel_at_period_end,
            },
            "provider": billing.provider_status()}


@router.post("/account/subscription/checkout", status_code=202)
def subscription_checkout(payload: CheckoutInput, request: Request, db: Session = Depends(db_session_dependency)):
    user = current_user(request, db)
    require_scope(request, "account:read")
    plan = db.get(SubscriptionPlan, payload.plan_code)
    if not plan or not plan.is_active:
        raise HTTPException(status_code=404, detail="Subscription plan not found")
    if plan.price_cents <= 0:
        raise HTTPException(status_code=422, detail="The Free plan does not require checkout")
    if plan.member_limit > 1:
        if not payload.team_id:
            raise HTTPException(status_code=422, detail="Choose a team before subscribing to a team plan")
        require_team_role(db, payload.team_id, user.id, ("owner",))
        team = db.get(Team, payload.team_id)
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")
    elif payload.team_id:
        raise HTTPException(status_code=422, detail="This plan is personal and cannot be assigned to a team")
    amount = plan.annual_price_cents if payload.interval == "year" else plan.price_cents
    payment = billing.new_payment(db, user=user, purpose="subscription", amount_cents=amount,
                                  currency=plan.currency,
                                  metadata={"plan_code": plan.code, "interval": payload.interval,
                                            "team_id": payload.team_id, "email": user.email, "name": user.name},
                                  team_id=payload.team_id)
    db.commit()
    result = billing.create_checkout(db, payment, description=f"{plan.name} plan ({payload.interval})", request=request)
    audit(db, user, "subscription.checkout_created", "payment", payment.id,
          {"plan_code": plan.code, "interval": payload.interval, "team_id": payload.team_id})
    db.commit()
    return result


@router.post("/account/subscription/cancel")
def cancel_subscription(payload: CancelSubscriptionInput, request: Request, team_id: str | None = None,
                        db: Session = Depends(db_session_dependency)):
    user = current_user(request, db)
    require_scope(request, "account:read")
    if team_id:
        require_team_role(db, team_id, user.id, ("owner",))
        subscription = active_subscription(db, team_id=team_id)
    else:
        subscription = active_subscription(db, user_id=user.id)
    if not subscription:
        raise HTTPException(status_code=404, detail="No active paid subscription found")
    subscription.cancel_at_period_end = True
    audit(db, user, "subscription.cancelled", "subscription", subscription.id,
          {"reason": payload.reason, "period_end": str(subscription.current_period_end)})
    db.commit()
    return {"ok": True, "cancel_at_period_end": True,
            "message": "Your plan stays active until the end of the current billing period."}


@router.get("/account/billing")
def account_billing(request: Request, db: Session = Depends(db_session_dependency)):
    user = current_user(request, db)
    require_scope(request, "account:read")
    subscription = active_subscription(db, user_id=user.id)
    payments = db.scalars(select(Payment).where(Payment.user_id == user.id)
                          .order_by(Payment.created_at.desc()).limit(50)).all()
    purchases = db.scalars(select(Purchase).where(Purchase.user_id == user.id)
                           .order_by(Purchase.created_at.desc()).limit(50)).all()
    return {
        "subscription": None if not subscription else {
            "id": subscription.id, "plan_code": subscription.plan_code, "status": subscription.status,
            "interval": subscription.interval, "current_period_end": subscription.current_period_end,
            "cancel_at_period_end": subscription.cancel_at_period_end,
        },
        "provider": billing.provider_status(),
        "providers": billing.all_providers(),
        "payments": [{"id": p.id, "reference": p.reference, "purpose": p.purpose, "amount_cents": p.amount_cents,
                      "currency": p.currency, "status": p.status, "provider": p.provider,
                      "checkout_url": p.checkout_url, "created_at": p.created_at, "paid_at": p.paid_at}
                     for p in payments],
        "purchases": [{"id": p.id, "listing_id": p.listing_id, "amount_cents": p.amount_cents,
                       "currency": p.currency, "status": p.status, "created_at": p.created_at,
                       "paid_at": p.paid_at} for p in purchases],
    }


@router.patch("/account/profile")
def update_profile(payload: ProfileInput, request: Request, db: Session = Depends(db_session_dependency)):
    user = current_user(request, db)
    require_scope(request, "account:read")
    user.name = payload.name.strip()
    audit(db, user, "account.profile_updated", "user", user.id)
    db.commit()
    return {"ok": True, "user": user_data(user)}


@router.post("/account/change-password")
def change_password(payload: ChangePasswordInput, request: Request, response: Response,
                    db: Session = Depends(db_session_dependency)):
    user = current_user(request, db)
    require_scope(request, "account:read")
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=403, detail="Current password is incorrect")
    user.password_hash = password_hash(payload.new_password)
    db.query(UserSession).filter(UserSession.user_id == user.id).delete()
    db.query(APIKey).filter(APIKey.user_id == user.id, APIKey.revoked_at.is_(None)).update({"revoked_at": utcnow()})
    _set_session(response, db, user)
    audit(db, user, "account.password_changed", "user", user.id)
    db.commit()
    return {"ok": True, "message": "Password updated. Other sessions and API keys were revoked."}


@router.post("/account/delete")
def delete_account(payload: DeleteAccountInput, request: Request, response: Response,
                   db: Session = Depends(db_session_dependency)):
    user = current_user(request, db, allow_key=False)
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=403, detail="Password is incorrect")
    user.is_active = False
    db.query(UserSession).filter(UserSession.user_id == user.id).delete()
    db.query(APIKey).filter(APIKey.user_id == user.id, APIKey.revoked_at.is_(None)).update({"revoked_at": utcnow()})
    audit(db, user, "account.deactivated", "user", user.id)
    db.commit()
    response.delete_cookie("agentdock_session", path="/")
    return {"ok": True, "message": "Your account has been deactivated."}


@router.get("/account/notifications")
def list_notifications(request: Request, db: Session = Depends(db_session_dependency)):
    user = current_user(request, db)
    require_scope(request, "account:read")
    items = db.scalars(select(Notification).where(Notification.user_id == user.id)
                       .order_by(Notification.created_at.desc()).limit(50)).all()
    return {"items": [{"id": n.id, "kind": n.kind, "title": n.title, "body": n.body,
                       "link": n.link, "read": bool(n.read_at), "created_at": n.created_at} for n in items],
            "unread": sum(not n.read_at for n in items)}


@router.post("/account/notifications/{notification_id}/read")
def read_notification(notification_id: str, request: Request, db: Session = Depends(db_session_dependency)):
    user = current_user(request, db)
    item = db.scalar(select(Notification).where(Notification.id == notification_id, Notification.user_id == user.id))
    if not item:
        raise HTTPException(status_code=404, detail="Notification not found")
    item.read_at = utcnow()
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------

def _team_slug(db: Session, name: str) -> str:
    base = "".join(ch.lower() if ch.isalnum() else "-" for ch in name).strip("-") or "team"
    base = "-".join(part for part in base.split("-") if part)[:100]
    candidate, index = base, 2
    while db.scalar(select(Team.id).where(Team.slug == candidate)):
        candidate = f"{base}-{index}"
        index += 1
    return candidate


def _team_data(db: Session, team: Team, viewer: User, include_invites: bool = False) -> dict:
    role = team_role(db, team.id, viewer.id)
    members = []
    for member, user in db.execute(select(TeamMember, User).join(User, User.id == TeamMember.user_id)
                                   .where(TeamMember.team_id == team.id).order_by(TeamMember.joined_at)).all():
        members.append({"user_id": user.id, "email": user.email, "name": user.name,
                        "role": member.role, "joined_at": member.joined_at})
    plan = db.get(SubscriptionPlan, team.plan_code)
    result = {"id": team.id, "name": team.name, "slug": team.slug, "owner_id": team.owner_id,
              "plan_code": team.plan_code, "plan_name": plan.name if plan else team.plan_code,
              "seat_limit": team.seat_limit, "member_count": len(members), "role": role,
              "members": members, "created_at": team.created_at}
    if include_invites and role in {"owner", "admin"}:
        invitations = db.scalars(select(TeamInvitation).where(TeamInvitation.team_id == team.id,
                                                              TeamInvitation.accepted_at.is_(None))
                                 .order_by(TeamInvitation.created_at.desc())).all()
        result["invitations"] = [{"id": i.id, "email": i.email, "role": i.role, "expires_at": i.expires_at,
                                  "created_at": i.created_at} for i in invitations]
    return result


@router.get("/teams")
def list_teams(request: Request, db: Session = Depends(db_session_dependency)):
    user = current_user(request, db)
    require_scope(request, "teams:read")
    teams = db.scalars(select(Team).join(TeamMember, TeamMember.team_id == Team.id)
                       .where(TeamMember.user_id == user.id).order_by(Team.created_at)).all()
    return {"items": [_team_data(db, team, user) for team in teams]}


@router.post("/teams", status_code=201)
def create_team(payload: TeamCreateInput, request: Request, db: Session = Depends(db_session_dependency)):
    user = current_user(request, db)
    require_scope(request, "teams:write")
    team = Team(name=payload.name.strip(), slug=_team_slug(db, payload.name), owner_id=user.id,
                plan_code="free", seat_limit=2)
    db.add(team)
    db.flush()
    db.add(TeamMember(team_id=team.id, user_id=user.id, role="owner"))
    audit(db, user, "team.created", "team", team.id, {"name": team.name})
    notify(db, user.id, f"Team {team.name} created", "Invite teammates from the Team workspace.",
           kind="team", link="/team")
    db.commit()
    return _team_data(db, team, user, include_invites=True)


@router.get("/teams/{team_id}")
def get_team(team_id: str, request: Request, db: Session = Depends(db_session_dependency)):
    user = current_user(request, db)
    require_scope(request, "teams:read")
    team = db.get(Team, team_id)
    if not team or team_role(db, team.id, user.id) is None:
        raise HTTPException(status_code=404, detail="Team not found")
    return _team_data(db, team, user, include_invites=True)


@router.patch("/teams/{team_id}")
def update_team(team_id: str, payload: TeamUpdateInput, request: Request,
                db: Session = Depends(db_session_dependency)):
    user = current_user(request, db)
    require_scope(request, "teams:write")
    team = db.get(Team, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    require_team_role(db, team.id, user.id, ("owner", "admin"))
    team.name = payload.name.strip()
    audit(db, user, "team.updated", "team", team.id, {"name": team.name})
    db.commit()
    return _team_data(db, team, user, include_invites=True)


@router.delete("/teams/{team_id}")
def delete_team(team_id: str, request: Request, db: Session = Depends(db_session_dependency)):
    user = current_user(request, db)
    require_scope(request, "teams:write")
    team = db.get(Team, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    require_team_role(db, team.id, user.id, ("owner",))
    audit(db, user, "team.deleted", "team", team.id, {"name": team.name})
    db.delete(team)
    db.commit()
    return {"ok": True}


@router.post("/teams/{team_id}/invitations", status_code=201)
def invite_member(team_id: str, payload: TeamInviteInput, request: Request,
                  db: Session = Depends(db_session_dependency)):
    user = current_user(request, db)
    require_scope(request, "teams:write")
    team = db.get(Team, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    require_team_role(db, team.id, user.id, ("owner", "admin"))
    member_count = db.scalar(select(func.count(TeamMember.id)).where(TeamMember.team_id == team.id)) or 0
    pending = db.scalar(select(func.count(TeamInvitation.id)).where(
        TeamInvitation.team_id == team.id, TeamInvitation.accepted_at.is_(None),
        TeamInvitation.expires_at > utcnow())) or 0
    if member_count + pending >= team.seat_limit:
        raise HTTPException(status_code=409,
                            detail=f"This team has reached its {team.seat_limit}-member limit. Upgrade the team plan to invite more people.")
    email = str(payload.email).lower()
    existing_member = db.scalar(select(TeamMember).join(User, User.id == TeamMember.user_id)
                                .where(TeamMember.team_id == team.id, User.email == email))
    if existing_member:
        raise HTTPException(status_code=409, detail="That person is already a team member")
    db.query(TeamInvitation).filter(TeamInvitation.team_id == team.id, TeamInvitation.email == email,
                                    TeamInvitation.accepted_at.is_(None)).delete()
    raw = secrets.token_urlsafe(32)
    invitation = TeamInvitation(team_id=team.id, email=email, role=payload.role,
                                token_hash=hash_token(raw), invited_by=user.id,
                                expires_at=utcnow() + timedelta(days=7))
    db.add(invitation)
    audit(db, user, "team.invitation_created", "team", team.id, {"email": email, "role": payload.role})
    db.commit()
    link = f"{public_base_url(request)}/#/team?invite={raw}"
    sent = mailer.send_team_invitation(email, team.name, link)
    return {"id": invitation.id, "email": email, "role": payload.role, "expires_at": invitation.expires_at,
            "invite_link": link, "email_sent": sent,
            "message": "Share this one-time link with the invited teammate."}


@router.delete("/teams/{team_id}/invitations/{invitation_id}")
def revoke_invitation(team_id: str, invitation_id: str, request: Request,
                      db: Session = Depends(db_session_dependency)):
    user = current_user(request, db)
    require_scope(request, "teams:write")
    require_team_role(db, team_id, user.id, ("owner", "admin"))
    invitation = db.scalar(select(TeamInvitation).where(TeamInvitation.id == invitation_id,
                                                        TeamInvitation.team_id == team_id))
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")
    db.delete(invitation)
    audit(db, user, "team.invitation_revoked", "team", team_id, {"email": invitation.email})
    db.commit()
    return {"ok": True}


@router.post("/teams/invitations/accept")
def accept_invitation(payload: TeamAcceptInput, request: Request, db: Session = Depends(db_session_dependency)):
    user = current_user(request, db)
    invitation = db.scalar(select(TeamInvitation).where(TeamInvitation.token_hash == hash_token(payload.token)))
    if not invitation or invitation.accepted_at or invitation.expires_at.replace(tzinfo=timezone.utc) < utcnow():
        raise HTTPException(status_code=422, detail="This invitation is invalid or has expired")
    if invitation.email != user.email.lower():
        raise HTTPException(status_code=403, detail="Sign in with the invited email address to accept this invitation")
    team = db.get(Team, invitation.team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    member_count = db.scalar(select(func.count(TeamMember.id)).where(TeamMember.team_id == team.id)) or 0
    if member_count >= team.seat_limit:
        raise HTTPException(status_code=409, detail="This team is full. Ask the owner to upgrade the plan.")
    if not db.scalar(select(TeamMember).where(TeamMember.team_id == team.id, TeamMember.user_id == user.id)):
        db.add(TeamMember(team_id=team.id, user_id=user.id, role=invitation.role))
    invitation.accepted_at = utcnow()
    audit(db, user, "team.invitation_accepted", "team", team.id, {"email": user.email})
    notify(db, team.owner_id, f"{user.email} joined {team.name}", "Your teammate accepted the invitation.",
           kind="team", link="/team")
    db.commit()
    return {"ok": True, "team": _team_data(db, team, user)}


@router.patch("/teams/{team_id}/members/{member_user_id}")
def update_member(team_id: str, member_user_id: str, payload: TeamMemberUpdateInput, request: Request,
                  db: Session = Depends(db_session_dependency)):
    user = current_user(request, db)
    require_scope(request, "teams:write")
    require_team_role(db, team_id, user.id, ("owner",))
    member = db.scalar(select(TeamMember).where(TeamMember.team_id == team_id,
                                                TeamMember.user_id == member_user_id))
    if not member:
        raise HTTPException(status_code=404, detail="Team member not found")
    if member.role == "owner":
        raise HTTPException(status_code=422, detail="The owner role cannot be changed here")
    member.role = payload.role
    audit(db, user, "team.member_role_changed", "team", team_id,
          {"user_id": member_user_id, "role": payload.role})
    db.commit()
    return {"ok": True}


@router.delete("/teams/{team_id}/members/{member_user_id}")
def remove_member(team_id: str, member_user_id: str, request: Request,
                  db: Session = Depends(db_session_dependency)):
    user = current_user(request, db)
    require_scope(request, "teams:write")
    team = db.get(Team, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    member = db.scalar(select(TeamMember).where(TeamMember.team_id == team_id,
                                                TeamMember.user_id == member_user_id))
    if not member:
        raise HTTPException(status_code=404, detail="Team member not found")
    if member.role == "owner":
        raise HTTPException(status_code=422, detail="The team owner cannot be removed")
    if user.id != member_user_id:
        require_team_role(db, team_id, user.id, ("owner", "admin"))
    db.delete(member)
    audit(db, user, "team.member_removed", "team", team_id, {"user_id": member_user_id})
    db.commit()
    return {"ok": True}


@router.get("/teams/{team_id}/usage")
def team_usage(team_id: str, request: Request, db: Session = Depends(db_session_dependency)):
    user = current_user(request, db)
    require_scope(request, "teams:read")
    if team_role(db, team_id, user.id) is None:
        raise HTTPException(status_code=404, detail="Team not found")
    total = db.scalar(select(func.count(UsageEvent.id)).where(UsageEvent.team_id == team_id)) or 0
    by_source = db.execute(select(UsageEvent.source, func.count(UsageEvent.id))
                           .where(UsageEvent.team_id == team_id).group_by(UsageEvent.source)).all()
    by_skill = db.execute(select(Skill.name, func.count(UsageEvent.id)).join(UsageEvent, UsageEvent.skill_id == Skill.id)
                          .where(UsageEvent.team_id == team_id).group_by(Skill.name)
                          .order_by(func.count(UsageEvent.id).desc()).limit(10)).all()
    return {"retrievals": total, "by_source": {source: count for source, count in by_source},
            "top_skills": [{"name": name, "retrievals": count} for name, count in by_skill]}


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------

@router.get("/user/collections")
def list_collections(request: Request, db: Session = Depends(db_session_dependency)):
    user = current_user(request, db)
    require_scope(request, "library:read")
    ensure_default_collection(db, user)
    items = db.scalars(select(Collection).where(
        or_(Collection.user_id == user.id, Collection.team_id.in_(team_ids_for(db, user.id) or [""]))
    ).order_by(Collection.created_at)).all()
    result = []
    for collection in items:
        count = db.scalar(select(func.count(CollectionItem.id)).where(CollectionItem.collection_id == collection.id)) or 0
        team = db.get(Team, collection.team_id) if collection.team_id else None
        result.append({"id": collection.id, "name": collection.name, "description": collection.description,
                       "team_id": collection.team_id, "team_name": team.name if team else None,
                       "shared": bool(collection.team_id), "skill_count": count,
                       "created_at": collection.created_at})
    return {"items": result}


@router.post("/user/collections", status_code=201)
def create_collection(payload: CollectionCreateInput, request: Request,
                      db: Session = Depends(db_session_dependency)):
    user = current_user(request, db)
    require_scope(request, "library:write")
    if payload.team_id:
        require_team_role(db, payload.team_id, user.id, ("owner", "admin", "member"))
    duplicate = db.scalar(select(Collection).where(Collection.user_id == user.id,
                                                   Collection.team_id == payload.team_id,
                                                   Collection.name == payload.name.strip()))
    if duplicate:
        raise HTTPException(status_code=409, detail="A collection with that name already exists")
    collection = Collection(user_id=user.id, team_id=payload.team_id, name=payload.name.strip(),
                            description=payload.description.strip())
    db.add(collection)
    audit(db, user, "collection.created", "collection", collection.id, {"name": collection.name})
    db.commit()
    return {"id": collection.id, "name": collection.name, "description": collection.description,
            "team_id": collection.team_id, "shared": bool(collection.team_id)}


@router.patch("/user/collections/{collection_id}")
def update_collection(collection_id: str, payload: CollectionUpdateInput, request: Request,
                      db: Session = Depends(db_session_dependency)):
    user = current_user(request, db)
    require_scope(request, "library:write")
    collection = collection_access(db, collection_id, user, write=True)
    if collection.team_id:
        require_team_role(db, collection.team_id, user.id, ("owner", "admin", "member"))
    if payload.name:
        collection.name = payload.name.strip()
    if payload.description is not None:
        collection.description = payload.description.strip()
    db.commit()
    return {"ok": True, "id": collection.id, "name": collection.name}


@router.delete("/user/collections/{collection_id}")
def delete_collection(collection_id: str, request: Request, db: Session = Depends(db_session_dependency)):
    user = current_user(request, db)
    require_scope(request, "library:write")
    collection = collection_access(db, collection_id, user, write=True)
    if collection.team_id:
        require_team_role(db, collection.team_id, user.id, ("owner", "admin"))
    default = ensure_default_collection(db, user)
    if collection.id == default.id:
        raise HTTPException(status_code=422, detail="The default Favorites collection cannot be deleted")
    db.delete(collection)
    audit(db, user, "collection.deleted", "collection", collection_id, {"name": collection.name})
    db.commit()
    return {"ok": True}


@router.get("/user/collections/{collection_id}/items")
def collection_items(collection_id: str, request: Request, db: Session = Depends(db_session_dependency)):
    user = current_user(request, db)
    require_scope(request, "library:read")
    collection = collection_access(db, collection_id, user)
    rows = db.execute(select(Skill).join(CollectionItem, CollectionItem.skill_id == Skill.id)
                      .where(CollectionItem.collection_id == collection.id, Skill.status == "approved")
                      .order_by(CollectionItem.added_at.desc())).scalars().all()
    return {"collection": {"id": collection.id, "name": collection.name, "team_id": collection.team_id},
            "items": [skill_data(skill) for skill in rows]}


@router.post("/user/collections/{collection_id}/items", status_code=201)
def add_collection_item(collection_id: str, payload: dict, request: Request,
                        db: Session = Depends(db_session_dependency)):
    user = current_user(request, db)
    require_scope(request, "library:write")
    collection = collection_access(db, collection_id, user, write=True)
    skill = db.scalar(select(Skill).where((Skill.id == str(payload.get("skill_id", ""))) |
                                          (Skill.slug == str(payload.get("skill_id", "")))))
    if not skill or skill.status != "approved":
        raise HTTPException(status_code=404, detail="Skill not found")
    exists = db.scalar(select(CollectionItem).where(CollectionItem.collection_id == collection.id,
                                                    CollectionItem.skill_id == skill.id))
    if not exists:
        db.add(CollectionItem(collection_id=collection.id, skill_id=skill.id))
        audit(db, user, "collection.skill_added", "collection", collection.id, {"skill_id": skill.id})
        db.commit()
    return {"ok": True, "skill_id": skill.id, "collection_id": collection.id}


@router.delete("/user/collections/{collection_id}/items/{skill_id}")
def remove_collection_item(collection_id: str, skill_id: str, request: Request,
                           db: Session = Depends(db_session_dependency)):
    user = current_user(request, db)
    require_scope(request, "library:write")
    collection = collection_access(db, collection_id, user, write=True)
    item = db.scalar(select(CollectionItem).where(CollectionItem.collection_id == collection.id,
                                                  CollectionItem.skill_id == skill_id))
    if item:
        db.delete(item)
        db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Marketplace and creator
# ---------------------------------------------------------------------------

@router.get("/marketplace/listings")
def marketplace_listings(q: str = "", category: str | None = None, featured: bool | None = None,
                         sort: str = "featured", limit: int = 20, offset: int = 0,
                         db: Session = Depends(db_session_dependency)):
    if not 1 <= limit <= 50 or offset < 0:
        raise HTTPException(status_code=422, detail="Use limit 1–50 and a non-negative offset")
    if sort not in {"featured", "newest", "price_low", "price_high"}:
        raise HTTPException(status_code=422, detail="Use sort=featured, newest, price_low or price_high")
    query = (select(MarketplaceListing, Skill)
             .join(Skill, Skill.id == MarketplaceListing.skill_id)
             .outerjoin(User, User.id == MarketplaceListing.creator_id)
             .where(MarketplaceListing.status == "approved", Skill.status == "approved"))
    if category:
        query = query.where(Skill.category == category)
    if featured is True:
        query = query.where(MarketplaceListing.featured.is_(True))
    rank = None
    if q.strip():
        phrase = q.strip()[:100]
        terms = list(dict.fromkeys(re.findall(r"[\w]+", phrase, flags=re.UNICODE)))[:8] or [phrase]
        escaped_phrase = phrase.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        phrase_pattern = f"%{escaped_phrase}%"
        fields = (MarketplaceListing.title, MarketplaceListing.summary, Skill.name,
                  Skill.description, Skill.category, Skill.creator, User.name, User.email)
        matches = [or_(*(field.ilike(f"%{term}%") for field in fields)) for term in terms]
        query = query.where(or_(*matches))
        rank = case(
            (MarketplaceListing.title.ilike(phrase_pattern, escape="\\"), 16),
            (Skill.name.ilike(phrase_pattern, escape="\\"), 12),
            (MarketplaceListing.summary.ilike(phrase_pattern, escape="\\"), 8),
            else_=0,
        )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rank_order = [rank.desc()] if rank is not None else []
    ordering = {
        "featured": rank_order + [MarketplaceListing.featured.desc(), MarketplaceListing.created_at.desc()],
        "newest": [MarketplaceListing.created_at.desc(), *rank_order],
        "price_low": [MarketplaceListing.price_cents.asc(), *rank_order, MarketplaceListing.created_at.desc()],
        "price_high": [MarketplaceListing.price_cents.desc(), *rank_order, MarketplaceListing.created_at.desc()],
    }[sort]
    rows = db.execute(query.order_by(*ordering, MarketplaceListing.id.asc())
                      .offset(offset).limit(limit)).all()
    return {"items": [listing_data(db, listing) for listing, _skill in rows],
            "total": total, "limit": limit, "offset": offset, "sort": sort}


@router.get("/marketplace/categories")
def marketplace_categories(db: Session = Depends(db_session_dependency)):
    rows = db.execute(
        select(Skill.category, func.count(MarketplaceListing.id))
        .join(MarketplaceListing, MarketplaceListing.skill_id == Skill.id)
        .where(MarketplaceListing.status == "approved", Skill.status == "approved")
        .group_by(Skill.category).order_by(Skill.category)
    ).all()
    return {"items": [{"name": name, "count": count} for name, count in rows]}


@router.get("/marketplace/featured")
def featured_listings(db: Session = Depends(db_session_dependency)):
    rows = db.execute(select(MarketplaceListing, Skill).join(Skill, Skill.id == MarketplaceListing.skill_id)
                      .where(MarketplaceListing.status == "approved", Skill.status == "approved")
                      .order_by(MarketplaceListing.featured.desc(), MarketplaceListing.created_at.desc())
                      .limit(6)).all()
    return {"items": [listing_data(db, listing) for listing, _skill in rows]}


@router.get("/marketplace/listings/{listing_id}")
def marketplace_listing(listing_id: str, db: Session = Depends(db_session_dependency)):
    listing = db.get(MarketplaceListing, listing_id)
    if not listing or listing.status != "approved":
        raise HTTPException(status_code=404, detail="Listing not found")
    skill = db.get(Skill, listing.skill_id)
    if not skill or skill.status != "approved":
        raise HTTPException(status_code=404, detail="Listing not found")
    reviews = db.execute(select(Review, User).join(User, User.id == Review.user_id)
                         .where(Review.listing_id == listing.id, Review.status == "published")
                         .order_by(Review.created_at.desc()).limit(20)).all()
    result = listing_data(db, listing)
    result["skill"]["changelog"] = skill.changelog
    result["reviews"] = [{"rating": r.rating, "body": r.body, "author": u.name or u.email.split("@")[0],
                          "created_at": r.created_at} for r, u in reviews]
    return result


@router.get("/marketplace/purchases")
def my_purchases(request: Request, db: Session = Depends(db_session_dependency)):
    user = current_user(request, db)
    require_scope(request, "marketplace:read")
    team_ids = team_ids_for(db, user.id)
    owners = [Purchase.user_id == user.id]
    if team_ids:
        owners.append(Purchase.team_id.in_(team_ids))
    purchases = db.scalars(select(Purchase).where(or_(*owners))
                           .order_by(Purchase.created_at.desc()).limit(100)).all()
    items = []
    for purchase in purchases:
        listing = db.get(MarketplaceListing, purchase.listing_id)
        skill = db.get(Skill, listing.skill_id) if listing else None
        items.append({"id": purchase.id, "listing_id": purchase.listing_id, "skill_id": skill.id if skill else None,
                      "skill_slug": skill.slug if skill else None, "title": listing.title if listing else "Removed listing",
                      "skill_name": skill.name if skill else "", "amount_cents": purchase.amount_cents,
                      "currency": purchase.currency, "status": purchase.status, "team_id": purchase.team_id,
                      "created_at": purchase.created_at, "paid_at": purchase.paid_at})
    return {"items": items}


@router.post("/marketplace/purchases", status_code=202)
def purchase_listing(payload: PurchaseInput, request: Request, db: Session = Depends(db_session_dependency)):
    user = current_user(request, db)
    require_scope(request, "marketplace:write")
    listing = db.get(MarketplaceListing, payload.listing_id)
    if not listing or listing.status != "approved":
        raise HTTPException(status_code=404, detail="Listing not found")
    skill = db.get(Skill, listing.skill_id)
    if not skill or skill.status != "approved" or not skill.commercial_ok:
        raise HTTPException(status_code=422, detail="This skill is not cleared for marketplace distribution")
    if payload.team_id:
        require_team_role(db, payload.team_id, user.id, ("owner", "admin"))
    owners = [Purchase.user_id == user.id]
    if payload.team_id:
        owners = [Purchase.team_id == payload.team_id]
    existing = db.scalar(select(Purchase).where(Purchase.listing_id == listing.id,
                                                Purchase.status == "paid", or_(*owners)))
    if existing:
        return {"status": "already_owned", "purchase_id": existing.id, "message": "You already own this skill."}
    if listing.price_cents == 0:
        purchase = Purchase(user_id=user.id, team_id=payload.team_id, listing_id=listing.id,
                            amount_cents=0, currency=listing.currency, status="paid",
                            provider="free", paid_at=utcnow())
        db.add(purchase)
        audit(db, user, "marketplace.free_claim", "listing", listing.id)
        notify(db, user.id, f"Added {listing.title}", "The skill is available in My purchases.",
               kind="marketplace", link="/purchases")
        db.commit()
        return {"status": "paid", "purchase_id": purchase.id, "message": "Added to your account."}
    payment = billing.new_payment(db, user=user, purpose="marketplace", amount_cents=listing.price_cents,
                                  currency=listing.currency,
                                  metadata={"listing_id": listing.id, "email": user.email, "name": user.name,
                                            "team_id": payload.team_id}, team_id=payload.team_id)
    db.commit()
    result = billing.create_checkout(db, payment, description=listing.title, request=request)
    audit(db, user, "marketplace.checkout_created", "listing", listing.id, {"payment_id": payment.id})
    db.commit()
    return result


@router.get("/creator/profile")
def creator_profile(request: Request, db: Session = Depends(db_session_dependency)):
    user = current_user(request, db)
    profile = db.scalar(select(CreatorProfile).where(CreatorProfile.user_id == user.id))
    if not profile:
        return {"profile": None}
    return {"profile": {"id": profile.id, "display_name": profile.display_name, "bio": profile.bio,
                        "website": profile.website, "status": profile.status,
                        "revenue_share_bps": profile.revenue_share_bps, "created_at": profile.created_at}}


@router.post("/creator/apply", status_code=201)
def apply_creator(payload: CreatorApplyInput, request: Request, db: Session = Depends(db_session_dependency)):
    user = current_user(request, db)
    require_scope(request, "marketplace:write")
    profile = db.scalar(select(CreatorProfile).where(CreatorProfile.user_id == user.id))
    if profile:
        if profile.status == "approved":
            raise HTTPException(status_code=409, detail="Your creator profile is already approved")
        profile.display_name = payload.display_name.strip()
        profile.bio = payload.bio.strip()
        profile.website = payload.website.strip()
        profile.status = "pending"
    else:
        profile = CreatorProfile(user_id=user.id, display_name=payload.display_name.strip(),
                                 bio=payload.bio.strip(), website=payload.website.strip(), status="pending")
        db.add(profile)
    audit(db, user, "creator.applied", "creator_profile", profile.id, {"display_name": profile.display_name})
    notify(db, user.id, "Creator application received",
           "An administrator will review your creator profile.", kind="marketplace", link="/marketplace")
    db.commit()
    return {"ok": True, "status": profile.status}


@router.get("/creator/earnings")
def creator_earnings(request: Request, db: Session = Depends(db_session_dependency)):
    user = current_user(request, db)
    require_scope(request, "marketplace:read")
    earnings = db.scalars(select(CreatorEarning).where(CreatorEarning.creator_id == user.id)
                          .order_by(CreatorEarning.created_at.desc()).limit(100)).all()
    total = sum(e.amount_cents for e in earnings if e.status != "reversed")
    pending = sum(e.amount_cents for e in earnings if e.status == "pending")
    return {"total_cents": total, "pending_cents": pending,
            "items": [{"id": e.id, "purchase_id": e.purchase_id, "amount_cents": e.amount_cents,
                       "status": e.status, "created_at": e.created_at} for e in earnings]}


@router.get("/marketplace/my-listings")
def my_listings(request: Request, db: Session = Depends(db_session_dependency)):
    user = current_user(request, db)
    require_scope(request, "marketplace:read")
    listings = db.scalars(select(MarketplaceListing).where(MarketplaceListing.creator_id == user.id)
                          .order_by(MarketplaceListing.created_at.desc())).all()
    return {"items": [listing_data(db, listing) for listing in listings]}


@router.post("/marketplace/listings", status_code=201)
def create_listing(payload: ListingInput, request: Request, db: Session = Depends(db_session_dependency)):
    user = current_user(request, db)
    require_scope(request, "marketplace:write")
    profile = db.scalar(select(CreatorProfile).where(CreatorProfile.user_id == user.id))
    if not profile or profile.status != "approved":
        raise HTTPException(status_code=403, detail="An approved creator profile is required to publish a listing")
    skill = db.scalar(select(Skill).where((Skill.id == payload.skill_id) | (Skill.slug == payload.skill_id)))
    if not skill or skill.status != "approved":
        raise HTTPException(status_code=404, detail="Skill not found")
    if not skill.commercial_ok:
        raise HTTPException(status_code=422, detail="This skill has not been cleared for commercial distribution")
    attributed_to_profile = (skill.creator or "").strip().lower() == profile.display_name.strip().lower()
    if not attributed_to_profile and user.role not in {"admin", "super_admin"}:
        raise HTTPException(status_code=403,
                            detail="You can only list skills attributed to your creator profile")
    if db.scalar(select(MarketplaceListing).where(MarketplaceListing.skill_id == skill.id)):
        raise HTTPException(status_code=409, detail="This skill already has a marketplace listing")
    listing = MarketplaceListing(skill_id=skill.id, creator_id=user.id, title=payload.title.strip(),
                                 summary=payload.summary.strip(), price_cents=payload.price_cents,
                                 currency=payload.currency.upper(), status="pending",
                                 commission_bps=settings.platform_commission_bps)
    db.add(listing)
    skill.is_premium = payload.price_cents > 0
    audit(db, user, "marketplace.listing_submitted", "listing", listing.id, {"skill_id": skill.id})
    notify(db, user.id, "Listing submitted for review", listing.title, kind="marketplace", link="/marketplace")
    db.commit()
    return listing_data(db, listing)


@router.patch("/marketplace/listings/{listing_id}")
def update_listing(listing_id: str, payload: ListingUpdateInput, request: Request,
                   db: Session = Depends(db_session_dependency)):
    user = current_user(request, db)
    require_scope(request, "marketplace:write")
    listing = db.get(MarketplaceListing, listing_id)
    if not listing or listing.creator_id != user.id:
        raise HTTPException(status_code=404, detail="Listing not found")
    if payload.title is not None:
        listing.title = payload.title.strip()
    if payload.summary is not None:
        listing.summary = payload.summary.strip()
    if payload.price_cents is not None:
        listing.price_cents = payload.price_cents
        skill = db.get(Skill, listing.skill_id)
        if skill:
            skill.is_premium = payload.price_cents > 0
    if payload.status is not None:
        if payload.status not in {"draft", "pending", "paused"}:
            raise HTTPException(status_code=403, detail="Only an administrator can approve or reject a listing")
        listing.status = payload.status
    db.commit()
    return listing_data(db, listing)


@router.get("/marketplace/listings/{listing_id}/reviews")
def list_reviews(listing_id: str, db: Session = Depends(db_session_dependency)):
    rows = db.execute(select(Review, User).join(User, User.id == Review.user_id)
                      .where(Review.listing_id == listing_id, Review.status == "published")
                      .order_by(Review.created_at.desc()).limit(50)).all()
    rating, count = review_stats(db, listing_id)
    return {"rating": rating, "count": count,
            "items": [{"rating": r.rating, "body": r.body, "author": u.name or u.email.split("@")[0],
                       "created_at": r.created_at} for r, u in rows]}


@router.post("/marketplace/listings/{listing_id}/reviews", status_code=201)
def create_review(listing_id: str, payload: ReviewInput, request: Request,
                  db: Session = Depends(db_session_dependency)):
    user = current_user(request, db)
    require_scope(request, "marketplace:write")
    listing = db.get(MarketplaceListing, listing_id)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    owned = db.scalar(select(Purchase).where(Purchase.listing_id == listing.id, Purchase.user_id == user.id,
                                             Purchase.status == "paid"))
    if not owned and user.role not in {"admin", "super_admin"}:
        raise HTTPException(status_code=403, detail="Purchase this skill before reviewing it")
    review = db.scalar(select(Review).where(Review.listing_id == listing.id, Review.user_id == user.id))
    if review:
        review.rating = payload.rating
        review.body = payload.body.strip()
        review.status = "published"
    else:
        review = Review(listing_id=listing.id, user_id=user.id, rating=payload.rating,
                        body=payload.body.strip())
        db.add(review)
    audit(db, user, "marketplace.review_published", "listing", listing.id, {"rating": payload.rating})
    db.commit()
    return {"ok": True, "review_id": review.id}


@router.post("/rights-requests", status_code=201)
def create_rights_request(payload: RightsRequestInput, db: Session = Depends(db_session_dependency)):
    from .models import RightsRequest
    skill = None
    if payload.skill_id:
        skill = db.get(Skill, payload.skill_id)
        if not skill:
            raise HTTPException(status_code=404, detail="Skill not found")
    request = RightsRequest(requester_name=payload.requester_name.strip(),
                            requester_email=str(payload.requester_email).lower(),
                            skill_id=skill.id if skill else None,
                            repository_url=payload.repository_url.strip(),
                            claim_type=payload.claim_type, details=payload.details.strip())
    db.add(request)
    audit(db, None, "rights_request.created", "rights_request", request.id,
          {"claim_type": payload.claim_type, "skill_id": skill.id if skill else None})
    db.commit()
    return {"ok": True, "id": request.id,
            "message": "Your request has been received. AgentDock will review it before any further distribution."}


# ---------------------------------------------------------------------------
# Payment webhooks
# ---------------------------------------------------------------------------

@router.post("/webhooks/payments/{provider}")
async def payment_webhook(provider: str, request: Request, db: Session = Depends(db_session_dependency)):
    provider = provider.lower()
    if provider not in billing.SUPPORTED_PROVIDERS or provider == "manual":
        raise HTTPException(status_code=404, detail="Webhook provider not found")
    raw = await request.body()
    if len(raw) > 2_000_000:
        raise HTTPException(status_code=413, detail="Webhook payload is too large")
    headers = {key.lower(): value for key, value in request.headers.items()}
    if not billing.verify_webhook(provider, raw, headers):
        raise HTTPException(status_code=403, detail="Invalid webhook signature")
    import json
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Invalid webhook payload")
    return billing.process_webhook(db, provider, payload)
