"""Payment-provider abstraction and idempotent entitlement fulfillment.

AgentDock never grants a paid entitlement from a browser redirect. A payment is
fulfilled only by a verified provider webhook or by an administrator recording a
manual bank/mobile-money payment.
"""
import hashlib
import hmac
import json
import logging
import secrets
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .common import active_subscription, audit, money, notify, public_base_url
from .config import get_settings
from .mailer import send_payment_receipt
from .models import (CreatorEarning, MarketplaceListing, Payment, PaymentEvent, Purchase, Subscription,
                     SubscriptionPlan, Team, User, utcnow)

logger = logging.getLogger("agentdock.billing")
SUPPORTED_PROVIDERS = {"manual", "paddle", "flutterwave", "urubutopay"}


def provider_name() -> str:
    name = (get_settings().payment_provider or "manual").strip().lower()
    if name not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=503, detail="The configured payment provider is not supported")
    return name


def provider_status() -> dict:
    settings = get_settings()
    name = provider_name()
    configured = {
        "manual": True,
        "paddle": bool(settings.paddle_api_key and settings.paddle_webhook_secret),
        "flutterwave": bool(settings.flutterwave_secret_key and settings.flutterwave_webhook_hash),
        "urubutopay": bool(settings.urubutopay_api_key and settings.urubutopay_webhook_secret and settings.urubutopay_checkout_url),
    }[name]
    labels = {"manual": "Manual invoice", "paddle": "Paddle", "flutterwave": "Flutterwave", "urubutopay": "UrubutoPay"}
    return {"provider": name, "label": labels[name], "configured": configured,
            "manual": name == "manual",
            "message": ("Payments are recorded by an administrator after the invoice is settled."
                        if name == "manual" else
                        f"{labels[name]} is configured." if configured else
                        f"{labels[name]} credentials are not configured. Add them in the server environment.")}


def all_providers() -> list[dict]:
    """Every supported provider, including ones awaiting credentials."""
    settings = get_settings()
    active = provider_name()
    definitions = [
        ("manual", "Manual invoice", True, "Administrator records payment after the invoice is settled."),
        ("paddle", "Paddle", bool(settings.paddle_api_key and settings.paddle_webhook_secret),
         "Cards and subscriptions. Needs API key, webhook secret and price IDs."),
        ("flutterwave", "Flutterwave", bool(settings.flutterwave_secret_key and settings.flutterwave_webhook_hash),
         "Cards and mobile money. Needs secret key and webhook hash."),
        ("urubutopay", "UrubutoPay",
         bool(settings.urubutopay_api_key and settings.urubutopay_webhook_secret and settings.urubutopay_checkout_url),
         "Hosted checkout. Needs API key, webhook secret and checkout URL."),
    ]
    return [{"provider": name, "label": label, "configured": configured, "active": name == active,
             "available": configured, "description": description,
             "status": "active" if name == active and configured else
                       "ready" if configured else "available" if name != "manual" else "active"}
            for name, label, configured, description in definitions]


def _reference(prefix: str = "ADK") -> str:
    return f"{prefix}-{datetime.now(timezone.utc):%Y%m%d}-{secrets.token_hex(4).upper()}"


def _paddle_prices(db: Session) -> dict:
    from .models import SystemSetting
    setting = db.get(SystemSetting, "payment_prices")
    return (setting.value if setting else {}).get("paddle", {})


def create_checkout(db: Session, payment: Payment, *, description: str, request=None) -> dict:
    settings = get_settings()
    provider = provider_name()
    base = public_base_url(request)
    if provider == "manual":
        payment.status = "pending"
        payment.provider = "manual"
        db.commit()
        return {
            "status": "pending", "payment_id": payment.id, "reference": payment.reference,
            "provider": "manual", "checkout_url": "",
            "message": (f"Your invoice reference is {payment.reference}. Send payment to "
                        f"{settings.manual_billing_email} and an administrator will activate access."),
        }
    if provider == "paddle":
        price_map = _paddle_prices(db)
        key = f"{payment.metadata_json.get('plan_code') or payment.metadata_json.get('listing_id')}:{payment.metadata_json.get('interval', 'month')}"
        price_id = price_map.get(key) or price_map.get(payment.metadata_json.get("plan_code", ""))
        if not price_id:
            raise HTTPException(status_code=503,
                                detail="Paddle price IDs are not configured. Add them in Administration → System settings.")
        endpoint = "https://sandbox-api.paddle.com/transactions" if settings.paddle_environment != "production" else "https://api.paddle.com/transactions"
        payload = {"items": [{"price_id": price_id, "quantity": 1}],
                   "custom_data": {"payment_reference": payment.reference},
                   "checkout": {"url": f"{base}/#/billing?reference={payment.reference}"}}
        with httpx.Client(timeout=20) as client:
            response = client.post(endpoint, json=payload, headers={
                "Authorization": f"Bearer {settings.paddle_api_key}", "Content-Type": "application/json"})
        if response.is_error:
            logger.error("Paddle checkout creation failed (%s)", response.status_code)
            raise HTTPException(status_code=502, detail="The payment provider could not create a checkout")
        data = response.json().get("data", {})
        payment.provider = "paddle"
        payment.provider_ref = data.get("id", "")
        payment.checkout_url = (data.get("checkout") or {}).get("url", "")
        db.commit()
        return {"status": "pending", "payment_id": payment.id, "reference": payment.reference,
                "provider": "paddle", "checkout_url": payment.checkout_url,
                "message": "Complete the secure checkout to activate access."}
    if provider == "flutterwave":
        payload = {
            "tx_ref": payment.reference, "amount": payment.amount_cents / 100,
            "currency": payment.currency, "redirect_url": f"{base}/#/billing?reference={payment.reference}",
            "customer": {"email": payment.metadata_json.get("email", ""),
                         "name": payment.metadata_json.get("name", "AgentDock customer")},
            "customizations": {"title": "AgentDock", "description": description},
        }
        with httpx.Client(timeout=20) as client:
            response = client.post("https://api.flutterwave.com/v3/payments", json=payload,
                                   headers={"Authorization": f"Bearer {settings.flutterwave_secret_key}"})
        if response.is_error:
            logger.error("Flutterwave checkout creation failed (%s)", response.status_code)
            raise HTTPException(status_code=502, detail="The payment provider could not create a checkout")
        data = response.json().get("data", {})
        payment.provider = "flutterwave"
        payment.checkout_url = data.get("link", "")
        db.commit()
        return {"status": "pending", "payment_id": payment.id, "reference": payment.reference,
                "provider": "flutterwave", "checkout_url": payment.checkout_url,
                "message": "Complete the secure checkout to activate access."}
    # UrubutoPay: a configurable checkout endpoint that returns a hosted payment URL.
    payload = {"reference": payment.reference, "amount": payment.amount_cents,
               "currency": payment.currency, "description": description,
               "callback_url": f"{base}/#/billing?reference={payment.reference}",
               "metadata": payment.metadata_json}
    with httpx.Client(timeout=20) as client:
        response = client.post(settings.urubutopay_checkout_url, json=payload,
                               headers={"Authorization": f"Bearer {settings.urubutopay_api_key}"})
    if response.is_error:
        logger.error("UrubutoPay checkout creation failed (%s)", response.status_code)
        raise HTTPException(status_code=502, detail="The payment provider could not create a checkout")
    data = response.json()
    payment.provider = "urubutopay"
    payment.provider_ref = str(data.get("id") or data.get("reference") or "")
    payment.checkout_url = data.get("checkout_url") or data.get("url") or ""
    db.commit()
    return {"status": "pending", "payment_id": payment.id, "reference": payment.reference,
            "provider": "urubutopay", "checkout_url": payment.checkout_url,
            "message": "Complete the secure checkout to activate access."}


def new_payment(db: Session, *, user: User, purpose: str, amount_cents: int, currency: str,
                metadata: dict, team_id: str | None = None) -> Payment:
    payment = Payment(user_id=user.id, team_id=team_id, purpose=purpose, reference=_reference(),
                      provider=provider_name(), amount_cents=amount_cents, currency=currency,
                      metadata_json=metadata, status="pending")
    db.add(payment)
    db.flush()
    return payment


def _period_end(start: datetime, interval: str) -> datetime:
    return start + timedelta(days=365 if interval == "year" else 30)


def fulfill_payment(db: Session, payment: Payment, *, provider_ref: str = "", paid_at: datetime | None = None) -> dict:
    if payment.status == "paid":
        return {"status": "already_paid", "payment_id": payment.id}
    payment.status = "paid"
    payment.paid_at = paid_at or utcnow()
    if provider_ref:
        payment.provider_ref = provider_ref
    metadata = payment.metadata_json or {}
    result = {"status": "paid", "payment_id": payment.id, "reference": payment.reference}
    if payment.purpose == "subscription":
        plan = db.get(SubscriptionPlan, metadata.get("plan_code", ""))
        if not plan:
            raise HTTPException(status_code=422, detail="The purchased subscription plan no longer exists")
        interval = metadata.get("interval", "month")
        target_user_id = payment.user_id
        target_team_id = payment.team_id or metadata.get("team_id")
        now = payment.paid_at
        subscription = None
        if target_team_id:
            subscription = active_subscription(db, team_id=target_team_id)
        elif target_user_id:
            subscription = active_subscription(db, user_id=target_user_id)
        if subscription:
            subscription.plan_code = plan.code
            subscription.status = "active"
            subscription.interval = interval
            subscription.provider = payment.provider
            subscription.provider_ref = payment.provider_ref
            subscription.current_period_start = now
            subscription.current_period_end = _period_end(now, interval)
            subscription.cancel_at_period_end = False
        else:
            subscription = Subscription(user_id=target_user_id, team_id=target_team_id,
                                        plan_code=plan.code, status="active", interval=interval,
                                        provider=payment.provider, provider_ref=payment.provider_ref,
                                        current_period_start=now, current_period_end=_period_end(now, interval))
            db.add(subscription)
        if target_team_id:
            team = db.get(Team, target_team_id)
            if team:
                team.plan_code = plan.code
                team.seat_limit = plan.member_limit
        db.flush()
        result["subscription_id"] = subscription.id
        if target_user_id:
            notify(db, target_user_id, f"{plan.name} plan activated",
                   f"Your {plan.name} plan is active until {subscription.current_period_end:%Y-%m-%d}.",
                   kind="billing", link="/billing")
    elif payment.purpose == "marketplace":
        listing = db.get(MarketplaceListing, metadata.get("listing_id", ""))
        if not listing:
            raise HTTPException(status_code=422, detail="The marketplace listing no longer exists")
        purchase = db.scalar(select(Purchase).where(Purchase.payment_id == payment.id))
        if not purchase:
            purchase = Purchase(user_id=payment.user_id, team_id=payment.team_id, listing_id=listing.id,
                                payment_id=payment.id, amount_cents=payment.amount_cents,
                                currency=payment.currency, status="paid", provider=payment.provider,
                                provider_ref=payment.provider_ref, paid_at=payment.paid_at)
            db.add(purchase)
            db.flush()
            if listing.creator_id and payment.amount_cents > 0:
                creator_amount = round(payment.amount_cents * (10000 - listing.commission_bps) / 10000)
                db.add(CreatorEarning(creator_id=listing.creator_id, purchase_id=purchase.id,
                                      amount_cents=creator_amount, status="pending"))
        result["purchase_id"] = purchase.id
        if payment.user_id:
            notify(db, payment.user_id, f"Purchase complete: {listing.title}",
                   "The skill is now available in My purchases and through your connected agents.",
                   kind="marketplace", link="/purchases")
    audit(db, None, "payment.fulfilled", "payment", payment.id,
          {"purpose": payment.purpose, "amount_cents": payment.amount_cents, "provider": payment.provider})
    db.commit()
    if payment.user_id:
        user = db.get(User, payment.user_id)
        if user:
            send_payment_receipt(user.email, payment.reference, money(payment.amount_cents, payment.currency),
                                 "AgentDock access")
    return result


def refund_payment(db: Session, payment: Payment, reason: str) -> dict:
    if payment.status != "paid":
        raise HTTPException(status_code=422, detail="Only a paid transaction can be refunded")
    payment.status = "refunded"
    purchase = db.scalar(select(Purchase).where(Purchase.payment_id == payment.id))
    if purchase:
        purchase.status = "refunded"
        earning = db.scalar(select(CreatorEarning).where(CreatorEarning.purchase_id == purchase.id))
        if earning:
            earning.status = "reversed"
    subscription = db.scalar(select(Subscription).where(Subscription.provider_ref == payment.provider_ref,
                                                        Subscription.provider == payment.provider).limit(1))
    if subscription:
        subscription.status = "refunded"
        subscription.cancel_at_period_end = True
    audit(db, None, "payment.refunded", "payment", payment.id,
          {"reason": reason, "amount_cents": payment.amount_cents})
    if payment.user_id:
        notify(db, payment.user_id, "Payment refunded",
               f"Transaction {payment.reference} was refunded. {reason}", kind="billing", link="/billing")
    db.commit()
    return {"ok": True, "status": payment.status}


def verify_webhook(provider: str, raw_body: bytes, headers: dict) -> bool:
    settings = get_settings()
    if provider == "paddle":
        header = headers.get("paddle-signature", "")
        parts = dict(part.split("=", 1) for part in header.split(";") if "=" in part)
        timestamp, signature = parts.get("ts", ""), parts.get("h1", "")
        if not timestamp or not signature or not settings.paddle_webhook_secret:
            return False
        try:
            if abs(time.time() - int(timestamp)) > 300:
                return False
        except ValueError:
            return False
        expected = hmac.new(settings.paddle_webhook_secret.encode(), f"{timestamp}:".encode() + raw_body,
                            hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)
    if provider == "flutterwave":
        return bool(settings.flutterwave_webhook_hash) and hmac.compare_digest(
            headers.get("verif-hash", ""), settings.flutterwave_webhook_hash)
    if provider == "urubutopay":
        signature = headers.get("x-urubutopay-signature", "")
        if not settings.urubutopay_webhook_secret:
            return False
        expected = hmac.new(settings.urubutopay_webhook_secret.encode(), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)
    return False


def parse_webhook(provider: str, payload: dict) -> dict:
    """Normalize the handful of provider event shapes into one internal shape."""
    if provider == "paddle":
        event_type = payload.get("event_type", "")
        data = payload.get("data", {})
        if event_type not in {"transaction.completed", "transaction.paid", "subscription.activated",
                              "subscription.resumed", "subscription.renewed"}:
            return {"handled": False, "event_id": payload.get("event_id", "")}
        custom = data.get("custom_data") or {}
        return {"handled": True, "event_id": payload.get("event_id", data.get("id", "")),
                "reference": custom.get("payment_reference", ""), "provider_ref": data.get("id", ""),
                "status": "paid"}
    if provider == "flutterwave":
        data = payload.get("data", payload)
        return {"handled": payload.get("event", "") == "charge.completed" or data.get("status") == "successful",
                "event_id": str(data.get("id", "")), "reference": data.get("tx_ref", ""),
                "provider_ref": str(data.get("id", "")),
                "status": "paid" if data.get("status") == "successful" else "failed"}
    if provider == "urubutopay":
        return {"handled": True, "event_id": str(payload.get("event_id") or payload.get("id", "")),
                "reference": payload.get("reference", ""), "provider_ref": str(payload.get("id", "")),
                "status": "paid" if payload.get("status") in {"paid", "successful", "completed"} else "failed"}
    return {"handled": False, "event_id": ""}


def process_webhook(db: Session, provider: str, payload: dict) -> dict:
    parsed = parse_webhook(provider, payload)
    if not parsed.get("handled"):
        return {"ok": True, "ignored": True}
    event_id = parsed.get("event_id") or f"{provider}:{parsed.get('reference')}:{parsed.get('status')}"
    existing = db.scalar(select(PaymentEvent).where(PaymentEvent.event_id == event_id))
    if existing:
        return {"ok": True, "duplicate": True}
    event = PaymentEvent(provider=provider, event_id=event_id, payload=payload)
    db.add(event)
    payment = db.scalar(select(Payment).where(Payment.reference == parsed.get("reference", "")))
    if not payment:
        event.processed_at = utcnow()
        db.commit()
        return {"ok": True, "unmatched": True}
    if parsed.get("status") == "paid":
        result = fulfill_payment(db, payment, provider_ref=parsed.get("provider_ref", ""))
    else:
        payment.status = "failed"
        db.commit()
        result = {"status": "failed"}
    event.processed_at = utcnow()
    db.commit()
    return {"ok": True, **result}


def expire_due_subscriptions(db: Session) -> int:
    now = utcnow()
    expired = 0
    for subscription in db.scalars(select(Subscription).where(Subscription.status == "active")).all():
        end = subscription.current_period_end
        if end is not None and end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        if end is not None and end <= now:
            subscription.status = "expired"
            expired += 1
            if subscription.user_id:
                notify(db, subscription.user_id, "Subscription expired",
                       "Your paid plan has expired. Your account is now on the Free plan.",
                       kind="billing", link="/billing")
    db.commit()
    return expired
