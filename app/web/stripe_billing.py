"""Stripe Checkout + Customer Portal + webhooks (single plan).

Configuration (all required for billing; otherwise checkout/portal answer 503
and the webhook refuses to verify):

- ``STRIPE_SECRET_KEY`` — secret key (test ``sk_test_...`` or live);
- ``STRIPE_PRICE_ID`` — recurring price of the single plan;
- ``STRIPE_WEBHOOK_SECRET`` — signing secret of the webhook endpoint;
- ``APP_DOMAIN`` — used for checkout success/cancel return URLs.

Money path uses the official ``stripe`` client. Webhook signatures are always
verified; unverified payloads are rejected without touching the database.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

import stripe
from fastapi import HTTPException
from stripe._error import SignatureVerificationError

from app.web import billing as billing_module

logger = logging.getLogger(__name__)

DbPath = Optional[Union[str, Path]]


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def is_configured() -> bool:
    return bool(
        _env("STRIPE_SECRET_KEY")
        and _env("STRIPE_PRICE_ID")
        and _env("STRIPE_WEBHOOK_SECRET")
    )


def _get_client() -> "stripe.StripeClient":
    return stripe.StripeClient(_env("STRIPE_SECRET_KEY"))


def _base_url() -> str:
    domain = _env("APP_DOMAIN") or "localhost:8000"
    scheme = "http" if domain.startswith("localhost") else "https"
    return f"{scheme}://{domain}"


def _sid(value) -> Optional[str]:
    if isinstance(value, dict):
        return value.get("id")
    return value or None


def _period_end_iso(value) -> Optional[str]:
    try:
        moment = datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None
    return moment.isoformat(timespec="seconds")


def _as_dict(obj) -> dict:
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    return dict(obj)


def _retrieve_subscription(sub_id: str) -> Optional[dict]:
    try:
        return _as_dict(_get_client().v1.subscriptions.retrieve(sub_id))
    except Exception as exc:  # noqa: BLE001 - Stripe/network failure
        logger.warning("Could not retrieve subscription %s: %s", sub_id, exc)
        return None


def _require_configured() -> None:
    if not is_configured():
        raise HTTPException(
            status_code=503,
            detail="Cobrança ainda não configurada. Fale com o suporte.",
        )


def create_checkout_session(
    user_id: int, email: str, db_path: DbPath = None
) -> str:
    """Creates a subscription Checkout Session; returns its URL."""
    _require_configured()
    sub = billing_module.get_subscription(user_id, db_path) or {}
    params: dict = {
        "mode": "subscription",
        "line_items": [{"price": _env("STRIPE_PRICE_ID"), "quantity": 1}],
        "client_reference_id": str(user_id),
        "success_url": f"{_base_url()}/?checkout=success",
        "cancel_url": f"{_base_url()}/?checkout=cancel",
        "allow_promotion_codes": True,
        "subscription_data": {
            "metadata": {"user_id": str(user_id), "app": "slidecast"}
        },
    }
    if sub.get("stripe_customer_id"):
        params["customer"] = sub["stripe_customer_id"]
    else:
        params["customer_email"] = email
    session = _get_client().v1.checkout.sessions.create(params)
    return session["url"]


def create_portal_session(user_id: int, db_path: DbPath = None) -> str:
    """Creates a Customer Portal session; returns its URL."""
    _require_configured()
    sub = billing_module.get_subscription(user_id, db_path) or {}
    if not sub.get("stripe_customer_id"):
        raise HTTPException(
            status_code=409,
            detail="Nenhuma assinatura encontrada. Assine primeiro.",
        )
    session = _get_client().v1.billing_portal.sessions.create(
        {
            "customer": sub["stripe_customer_id"],
            "return_url": f"{_base_url()}/",
        }
    )
    return session["url"]


def _handle_checkout_completed(obj: dict, db_path: DbPath = None) -> None:
    try:
        user_id = int(obj.get("client_reference_id") or 0)
    except (TypeError, ValueError):
        user_id = 0
    if not user_id:
        logger.warning("checkout.session.completed without client_reference_id")
        return
    customer_id = _sid(obj.get("customer"))
    sub_ref = obj.get("subscription")
    status: Optional[str] = None
    period_end: Optional[str] = None
    if isinstance(sub_ref, dict):
        status = sub_ref.get("status")
        period_end = _period_end_iso(sub_ref.get("current_period_end"))
        sub_id = sub_ref.get("id")
    else:
        sub_id = sub_ref
    if sub_id and status is None:
        full = _retrieve_subscription(sub_id)
        if full:
            status = full.get("status")
            period_end = _period_end_iso(full.get("current_period_end"))
    billing_module.link_stripe_subscription(
        user_id,
        customer_id=customer_id,
        subscription_id=sub_id,
        status=status or "active",
        period_end=period_end,
        db_path=db_path,
    )


def _handle_subscription_changed(obj: dict, deleted: bool) -> None:
    sub_id = obj.get("id")
    if not sub_id:
        return
    status = "canceled" if deleted else (obj.get("status") or "active")
    period_end = None if deleted else _period_end_iso(obj.get("current_period_end"))
    if not billing_module.set_status_by_stripe_id(
        sub_id, status=status, period_end=period_end
    ):
        logger.warning("Webhook for unknown subscription %s", sub_id)


def _handle_payment_failed(obj: dict) -> None:
    sub_id = _sid(obj.get("subscription"))
    if sub_id and not billing_module.set_status_by_stripe_id(
        sub_id, status="past_due"
    ):
        logger.warning("payment_failed for unknown subscription %s", sub_id)


def _handle_payment_succeeded(obj: dict) -> None:
    """Re-syncs from the API so a recovered card clears past_due promptly."""
    sub_id = _sid(obj.get("subscription"))
    if not sub_id:
        return
    full = _retrieve_subscription(sub_id)
    if full is None:
        return
    if not billing_module.set_status_by_stripe_id(
        sub_id,
        status=full.get("status") or "active",
        period_end=_period_end_iso(full.get("current_period_end")),
    ):
        logger.warning("payment_succeeded for unknown subscription %s", sub_id)


def handle_webhook(payload: bytes, signature: Optional[str]) -> str:
    """Verifies and applies a Stripe webhook; returns the event type."""
    _require_configured()
    if not signature:
        raise HTTPException(status_code=400, detail="Assinatura ausente.")
    try:
        event = stripe.Webhook.construct_event(
            payload, signature, _env("STRIPE_WEBHOOK_SECRET")
        )
    except (ValueError, SignatureVerificationError) as exc:
        raise HTTPException(status_code=400, detail=f"Assinatura inválida: {exc}")
    # v16 returns its own object type: normalize to a plain (deep) dict so the
    # handlers below can use .get() uniformly.
    evt = event.to_dict() if hasattr(event, "to_dict") else dict(event)
    event_type = evt.get("type", "")
    if not billing_module.note_webhook_event(evt.get("id", ""), event_type):
        logger.info("Skipping duplicate Stripe event %s", evt.get("id"))
        return event_type
    obj = (evt.get("data") or {}).get("object") or {}
    if event_type == "checkout.session.completed":
        _handle_checkout_completed(obj)
    elif event_type == "customer.subscription.updated":
        _handle_subscription_changed(obj, deleted=False)
    elif event_type == "customer.subscription.deleted":
        _handle_subscription_changed(obj, deleted=True)
    elif event_type == "invoice.payment_failed":
        _handle_payment_failed(obj)
    elif event_type == "invoice.payment_succeeded":
        _handle_payment_succeeded(obj)
    else:
        logger.info("Ignoring Stripe event %s", event_type)
    return event_type
