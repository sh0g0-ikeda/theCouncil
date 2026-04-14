from __future__ import annotations

import json
import logging
import os
from typing import Any

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from api.deps import RequestUser, require_user
from db.client import DatabaseClient, get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/billing", tags=["billing"])

PLAN_PRICE_MAP = {
    "pro": "STRIPE_PRO_PRICE_ID",
    "ultra": "STRIPE_ULTRA_PRICE_ID",
}


def _stripe_client() -> stripe.StripeClient:
    secret = os.getenv("STRIPE_SECRET_KEY")
    if not secret:
        raise HTTPException(status_code=503, detail="Stripe not configured")
    return stripe.StripeClient(secret)


@router.get("/me")
async def get_billing_info(
    user: RequestUser = Depends(require_user),
    db: DatabaseClient = Depends(get_db),
) -> dict[str, Any]:
    user_record = await db.fetch_user(user.id)
    if not user_record:
        return {"plan": "free", "stripe_customer_id": None}
    return {
        "plan": user_record.get("plan", "free"),
        "stripe_customer_id": user_record.get("stripe_customer_id"),
    }


class CheckoutRequest(BaseModel):
    plan: str  # "pro" | "ultra"
    success_url: str
    cancel_url: str


def _subscription_is_cancelable(subscription: Any) -> bool:
    status = getattr(subscription, "status", None)
    return status not in {"canceled", "incomplete_expired"}


def _list_cancelable_subscriptions(subscriptions: Any) -> list[Any]:
    return [sub for sub in getattr(subscriptions, "data", []) if _subscription_is_cancelable(sub)]


@router.post("/checkout")
async def create_checkout_session(
    body: CheckoutRequest,
    user: RequestUser = Depends(require_user),
    db: DatabaseClient = Depends(get_db),
) -> dict[str, Any]:
    if body.plan not in PLAN_PRICE_MAP:
        raise HTTPException(status_code=400, detail="Invalid plan")

    price_id_env = PLAN_PRICE_MAP[body.plan]
    price_id = os.getenv(price_id_env)
    if not price_id:
        raise HTTPException(status_code=503, detail=f"{price_id_env} not configured")

    client = _stripe_client()

    # Fetch or create Stripe customer ID
    user_record = await db.fetch_user(user.id)
    if not user_record:
        raise HTTPException(status_code=404, detail="User not found")

    stripe_customer_id = user_record.get("stripe_customer_id")
    if not stripe_customer_id:
        customer = client.customers.create(
            params={
                "email": user_record.get("email") or "",
                "metadata": {"user_id": user.id},
            }
        )
        stripe_customer_id = customer.id
        await db.update_user_stripe_customer(user.id, stripe_customer_id)

    session = client.checkout.sessions.create(
        params={
            "customer": stripe_customer_id,
            "mode": "subscription",
            "line_items": [{"price": price_id, "quantity": 1}],
            "success_url": body.success_url,
            "cancel_url": body.cancel_url,
            "metadata": {"user_id": user.id, "plan": body.plan},
            "subscription_data": {
                "metadata": {"user_id": user.id, "plan": body.plan},
            },
        }
    )
    return {"url": session.url}


@router.post("/cancel")
async def cancel_subscription(
    user: RequestUser = Depends(require_user),
    db: DatabaseClient = Depends(get_db),
) -> dict[str, Any]:
    user_record = await db.fetch_user(user.id)
    if not user_record:
        raise HTTPException(status_code=404, detail="User not found")

    current_plan = user_record.get("plan", "free")
    if current_plan == "free":
        return {"ok": True, "plan": "free"}

    stripe_customer_id = user_record.get("stripe_customer_id")
    if stripe_customer_id:
        client = _stripe_client()
        subscriptions = client.subscriptions.list(
            params={"customer": stripe_customer_id, "status": "all", "limit": 20}
        )
        for subscription in _list_cancelable_subscriptions(subscriptions):
            client.subscriptions.cancel(subscription.id)

    await db.update_user_plan(user.id, "free")
    logger.info("Subscription cancelled immediately for user %s -> free", user.id)
    return {"ok": True, "plan": "free"}


@router.get("/portal")
async def billing_portal(
    return_url: str,
    user: RequestUser = Depends(require_user),
    db: DatabaseClient = Depends(get_db),
) -> dict[str, Any]:
    user_record = await db.fetch_user(user.id)
    if not user_record:
        raise HTTPException(status_code=404, detail="User not found")

    stripe_customer_id = user_record.get("stripe_customer_id")
    if not stripe_customer_id:
        raise HTTPException(status_code=400, detail="No billing account found")

    client = _stripe_client()
    session = client.billing_portal.sessions.create(
        params={"customer": stripe_customer_id, "return_url": return_url}
    )
    return {"url": session.url}


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="stripe-signature"),
    db: DatabaseClient = Depends(get_db),
) -> dict[str, str]:
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    if not webhook_secret:
        raise HTTPException(status_code=503, detail="Webhook not configured")

    secret_key = os.getenv("STRIPE_SECRET_KEY")
    if not secret_key:
        raise HTTPException(status_code=503, detail="Stripe not configured")

    payload = await request.body()

    try:
        event = stripe.Webhook.construct_event(
            payload,
            stripe_signature or "",
            webhook_secret,
        )
    except stripe.SignatureVerificationError as e:
        logger.warning("Stripe webhook signature verification failed: %s", e)
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        logger.warning("Stripe webhook parse error: %s", e)
        raise HTTPException(status_code=400, detail="Invalid payload")

    await _handle_stripe_event(event, db)
    return {"status": "ok"}


async def _handle_stripe_event(event: Any, db: DatabaseClient) -> None:
    event_type = event["type"]

    if event_type in ("customer.subscription.created", "customer.subscription.updated"):
        sub = event["data"]["object"]
        await _apply_subscription(sub, db)

    elif event_type == "customer.subscription.deleted":
        sub = event["data"]["object"]
        user_id = sub.get("metadata", {}).get("user_id")
        if user_id:
            await db.update_user_plan(user_id, "free")
            logger.info("Subscription cancelled for user %s → free", user_id)

    elif event_type == "checkout.session.completed":
        session = event["data"]["object"]
        # plan is also set via subscription events; this is a fallback
        user_id = session.get("metadata", {}).get("user_id")
        plan = session.get("metadata", {}).get("plan")
        if user_id and plan:
            await db.update_user_plan(user_id, plan)
            logger.info("Checkout completed for user %s → %s", user_id, plan)

    elif event_type in ("invoice.payment_failed",):
        logger.warning("Payment failed: %s", event["data"]["object"].get("customer"))


async def _apply_subscription(sub: Any, db: DatabaseClient) -> None:
    status = sub.get("status")
    user_id = sub.get("metadata", {}).get("user_id")
    plan = sub.get("metadata", {}).get("plan")

    if not user_id or not plan:
        logger.warning("Subscription missing user_id or plan metadata: %s", sub.get("id"))
        return

    if status in ("active", "trialing"):
        await db.update_user_plan(user_id, plan)
        logger.info("Subscription %s for user %s → %s", status, user_id, plan)
    elif status in ("canceled", "unpaid", "past_due"):
        await db.update_user_plan(user_id, "free")
        logger.info("Subscription %s for user %s → free", status, user_id)
