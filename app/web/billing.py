"""Single-plan subscription state, trial window, monthly quota, ownership.

Plan states (``plan_status()["state"]``):

- ``trial`` — inside the free trial window, no Stripe subscription yet;
- ``active`` — Stripe subscription active (or Stripe trialing);
- ``past_due`` — last payment failed, user must update the card;
- ``expired`` — trial over and no usable subscription.

Renders consume the monthly quota (``PLAN_MONTHLY_RENDERS``, 0 = unlimited).
Ownership rows isolate every project/job per user: cross-user access must be
answered with 404, never 403, to avoid leaking object existence.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from app.web import db as db_module

DbPath = Optional[Union[str, Path]]

ALLOWED_STATUSES = {"active", "trialing"}


class BillingError(ValueError):
    """User-facing billing failure carrying an HTTP status code."""

    def __init__(self, message: str, status_code: int = 403):
        super().__init__(message)
        self.status_code = status_code


def monthly_render_limit() -> int:
    try:
        return max(0, int(os.environ.get("PLAN_MONTHLY_RENDERS", "30")))
    except ValueError:
        return 30


def _current_period() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def get_subscription(user_id: int, db_path: DbPath = None) -> Optional[dict]:
    conn = db_module.connect(db_path)
    try:
        row = conn.execute(
            "SELECT user_id, status, trial_ends_at, current_period_end,"
            " stripe_customer_id, stripe_subscription_id"
            " FROM subscriptions WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def renders_used(user_id: int, db_path: DbPath = None) -> int:
    conn = db_module.connect(db_path)
    try:
        row = conn.execute(
            "SELECT renders FROM usage WHERE user_id = ? AND period = ?",
            (user_id, _current_period()),
        ).fetchone()
    finally:
        conn.close()
    return row["renders"] if row else 0


def plan_status(user_id: int, db_path: DbPath = None) -> dict:
    sub = get_subscription(user_id, db_path)
    limit = monthly_render_limit()
    used = renders_used(user_id, db_path)
    plan = {
        "state": "expired",
        "trial_ends_at": None,
        "current_period_end": None,
        "renders_used": used,
        "renders_limit": limit,
        "renders_left": None if limit == 0 else max(0, limit - used),
        "has_subscription": False,
    }
    if sub is None:
        return plan
    plan["trial_ends_at"] = sub["trial_ends_at"]
    plan["current_period_end"] = sub["current_period_end"]
    plan["has_subscription"] = bool(sub["stripe_subscription_id"])
    status = (sub["status"] or "").strip().lower()
    if status == "past_due":
        plan["state"] = "past_due"
        return plan
    if status in ALLOWED_STATUSES:
        if sub["stripe_subscription_id"]:
            plan["state"] = "active"
            return plan
        trial_end = db_module.parse_iso(sub["trial_ends_at"])
        now = datetime.now(timezone.utc)
        if trial_end is not None and now <= trial_end:
            plan["state"] = "trial"
            return plan
    plan["state"] = "expired"
    return plan


def plan_guard(user_id: int, db_path: DbPath = None) -> dict:
    """Requires trial/active; raises BillingError (403) otherwise."""
    plan = plan_status(user_id, db_path)
    if plan["state"] == "past_due":
        raise BillingError(
            "Pagamento pendente: atualize o cartão no portal de cobrança.", 403
        )
    if plan["state"] not in ("trial", "active"):
        raise BillingError(
            "Período de teste encerrado. Assine para continuar criando vídeos.",
            403,
        )
    return plan


def render_guard(user_id: int, db_path: DbPath = None) -> dict:
    """Requires plan + remaining monthly quota; raises BillingError (403)."""
    plan = plan_guard(user_id, db_path)
    limit = plan["renders_limit"]
    if limit and plan["renders_used"] >= limit:
        raise BillingError(
            f"Limite mensal de {limit} vídeos atingido."
            " O limite renova no próximo mês.",
            403,
        )
    return plan


def record_project(user_id: int, project_id: str, db_path: DbPath = None) -> None:
    conn = db_module.connect(db_path)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO ownership (kind, object_id, user_id, created_at)"
            " VALUES ('project', ?, ?, ?)",
            (project_id, user_id, db_module.utcnow_iso()),
        )
        conn.commit()
    finally:
        conn.close()


def record_render(user_id: int, job_id: str, db_path: DbPath = None) -> None:
    conn = db_module.connect(db_path)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO ownership (kind, object_id, user_id, created_at)"
            " VALUES ('job', ?, ?, ?)",
            (job_id, user_id, db_module.utcnow_iso()),
        )
        conn.execute(
            "INSERT INTO usage (user_id, period, renders) VALUES (?, ?, 1)"
            " ON CONFLICT (user_id, period)"
            " DO UPDATE SET renders = renders + 1",
            (user_id, _current_period()),
        )
        conn.commit()
    finally:
        conn.close()


def owns(user_id: int, kind: str, object_id: str, db_path: DbPath = None) -> bool:
    conn = db_module.connect(db_path)
    try:
        row = conn.execute(
            "SELECT 1 FROM ownership WHERE kind = ? AND object_id = ? AND user_id = ?",
            (kind, object_id, user_id),
        ).fetchone()
    finally:
        conn.close()
    return row is not None


def link_stripe_subscription(
    user_id: int,
    *,
    customer_id: Optional[str],
    subscription_id: Optional[str],
    status: str,
    period_end: Optional[str],
    db_path: DbPath = None,
) -> None:
    conn = db_module.connect(db_path)
    try:
        conn.execute(
            "UPDATE subscriptions SET status = ?,"
            " current_period_end = COALESCE(?, current_period_end),"
            " stripe_customer_id = COALESCE(?, stripe_customer_id),"
            " stripe_subscription_id = COALESCE(?, stripe_subscription_id),"
            " updated_at = ? WHERE user_id = ?",
            (
                (status or "").strip().lower(),
                period_end,
                customer_id,
                subscription_id,
                db_module.utcnow_iso(),
                user_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def find_user_by_stripe_subscription(
    subscription_id: str, db_path: DbPath = None
) -> Optional[int]:
    if not subscription_id:
        return None
    conn = db_module.connect(db_path)
    try:
        row = conn.execute(
            "SELECT user_id FROM subscriptions WHERE stripe_subscription_id = ?",
            (subscription_id,),
        ).fetchone()
    finally:
        conn.close()
    return row["user_id"] if row else None


def note_webhook_event(
    event_id: str, event_type: str, db_path: DbPath = None
) -> bool:
    """Records a verified webhook event; True when first seen.

    Stripe retries deliveries, so the same event may arrive twice. Callers
    must skip already-recorded events instead of reprocessing them.
    """
    if not event_id:
        return True
    conn = db_module.connect(db_path)
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO webhook_events (event_id, event_type, received_at)"
            " VALUES (?, ?, ?)",
            (event_id, event_type, db_module.utcnow_iso()),
        )
        conn.commit()
        return cur.rowcount == 1
    finally:
        conn.close()


def set_status_by_stripe_id(
    subscription_id: str,
    *,
    status: str,
    period_end: Optional[str] = None,
    db_path: DbPath = None,
) -> bool:
    user_id = find_user_by_stripe_subscription(subscription_id, db_path)
    if user_id is None:
        return False
    link_stripe_subscription(
        user_id,
        customer_id=None,
        subscription_id=None,
        status=status,
        period_end=period_end,
        db_path=db_path,
    )
    return True
