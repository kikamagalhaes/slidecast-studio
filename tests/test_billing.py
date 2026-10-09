"""Trial/quota/ownership gating plus Stripe checkout/portal/webhook."""

import hashlib
import hmac
import json
import time
import uuid

import pytest
from fastapi.testclient import TestClient

import app.web.server as server_module
from app.web import billing as billing_module
from app.web import db as db_module
from app.web import stripe_billing
from tests.test_web_api import make_pdf_bytes, make_wav_bytes


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server_module, "STORAGE_DIR", tmp_path / "storage")
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.delenv("STRIPE_PRICE_ID", raising=False)
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "0")
    with TestClient(server_module.app) as test_client:
        yield test_client


def register(client, email="user@example.com", password="password123"):
    res = client.post("/api/auth/register", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    body = res.json()
    headers = {"Authorization": f"Bearer {body['token']}"}
    return body["user"]["id"], headers


def upload(client, headers):
    return client.post(
        "/api/upload",
        files={
            "pdf_file": ("slides.pdf", make_pdf_bytes(), "application/pdf"),
            "audio_file": ("narr.wav", make_wav_bytes(), "audio/wav"),
        },
        headers=headers,
    )


def render(client, headers, project_id, durations=(1.0, 1.0)):
    return client.post(
        f"/api/projects/{project_id}/render",
        json={
            "durations": list(durations),
            "resolution_w": 320,
            "resolution_h": 240,
            "fps": 15,
        },
        headers=headers,
    )


def expire_trial(user_id):
    conn = db_module.connect(server_module.STORAGE_DIR / "slidecast.db")
    try:
        conn.execute(
            "UPDATE subscriptions SET trial_ends_at = '2000-01-01T00:00:00+00:00'"
            " WHERE user_id = ?",
            (user_id,),
        )
        conn.commit()
    finally:
        conn.close()


def stripe_env(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_dummy")
    monkeypatch.setenv("STRIPE_PRICE_ID", "price_dummy")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_dummy")


def sign_webhook(payload: bytes, secret: str = "whsec_dummy") -> str:
    ts = int(time.time())
    mac = hmac.new(
        secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256
    ).hexdigest()
    return f"t={ts},v1={mac}"


def post_webhook(client, event: dict, secret: str = "whsec_dummy"):
    payload = json.dumps(event).encode()
    return client.post(
        "/api/billing/webhook",
        content=payload,
        headers={"stripe-signature": sign_webhook(payload, secret)},
    )


def test_trial_allows_upload_and_counts_quota(client):
    user_id, headers = register(client)
    assert upload(client, headers).status_code == 200
    project_id = upload(client, headers).json()["project_id"]
    assert render(client, headers, project_id).status_code == 200
    me = client.get("/api/auth/me", headers=headers).json()
    assert me["plan"]["state"] == "trial"
    assert me["plan"]["renders_used"] == 1
    assert me["plan"]["renders_left"] == me["plan"]["renders_limit"] - 1
    assert user_id


def test_quota_blocks_renders_over_limit(client, monkeypatch):
    monkeypatch.setenv("PLAN_MONTHLY_RENDERS", "1")
    _, headers = register(client)
    project_id = upload(client, headers).json()["project_id"]
    assert render(client, headers, project_id).status_code == 200
    res = render(client, headers, project_id)
    assert res.status_code == 403
    assert "Limite mensal" in res.json()["detail"]


def test_zero_quota_means_unlimited(client, monkeypatch):
    monkeypatch.setenv("PLAN_MONTHLY_RENDERS", "0")
    _, headers = register(client)
    project_id = upload(client, headers).json()["project_id"]
    assert render(client, headers, project_id).status_code == 200
    assert render(client, headers, project_id).status_code == 200
    me = client.get("/api/auth/me", headers=headers).json()
    assert me["plan"]["renders_left"] is None


def test_expired_trial_blocks_new_work_but_keeps_reads(client):
    user_id, headers = register(client)
    project_id = upload(client, headers).json()["project_id"]
    job_id = render(client, headers, project_id).json()["job_id"]
    expire_trial(user_id)

    assert upload(client, headers).status_code == 403
    assert render(client, headers, project_id).status_code == 403
    ai_sync = client.post(
        f"/api/projects/{project_id}/ai-sync", json={}, headers=headers
    )
    assert ai_sync.status_code == 403
    # Past work stays readable while logged in.
    assert (
        client.get(f"/api/projects/{project_id}/thumbnail/0", headers=headers).status_code
        == 200
    )
    assert client.get(f"/api/jobs/{job_id}", headers=headers).status_code == 200
    me = client.get("/api/auth/me", headers=headers).json()
    assert me["plan"]["state"] == "expired"


def test_cross_user_access_is_404(client):
    _, headers_a = register(client, "a@example.com")
    _, headers_b = register(client, "b@example.com")
    project_id = upload(client, headers_a).json()["project_id"]
    job_id = render(client, headers_a, project_id).json()["job_id"]

    assert (
        client.get(f"/api/projects/{project_id}/thumbnail/0", headers=headers_b).status_code
        == 404
    )
    assert (
        client.post(f"/api/projects/{project_id}/ai-sync", json={}, headers=headers_b).status_code
        == 404
    )
    assert render(client, headers_b, project_id).status_code == 404
    assert client.get(f"/api/jobs/{job_id}", headers=headers_b).status_code == 404
    assert (
        client.get(f"/api/jobs/{job_id}/download", headers=headers_b).status_code == 404
    )
    assert client.delete(f"/api/jobs/{job_id}", headers=headers_b).status_code == 404


def test_protected_endpoints_require_auth(client):
    pid = str(uuid.uuid4())
    assert upload(client, {}).status_code == 401
    assert client.get(f"/api/projects/{pid}/thumbnail/0").status_code == 401
    assert client.post(f"/api/projects/{pid}/ai-sync", json={}).status_code == 401
    assert (
        client.post(f"/api/projects/{pid}/render", json={"durations": [1.0]}).status_code
        == 401
    )
    assert client.get(f"/api/jobs/{pid}").status_code == 401
    assert client.delete(f"/api/jobs/{pid}").status_code == 401
    assert client.post("/api/billing/checkout").status_code == 401
    assert client.post("/api/billing/portal").status_code == 401


def test_billing_unconfigured_answers_503(client):
    _, headers = register(client)
    assert client.post("/api/billing/checkout", headers=headers).status_code == 503
    assert client.post("/api/billing/portal", headers=headers).status_code == 503
    res = client.post("/api/billing/webhook", content=b"{}")
    assert res.status_code == 503


def test_checkout_and_portal_with_stubbed_stripe(client, monkeypatch):
    stripe_env(monkeypatch)
    user_id, headers = register(client)

    calls = {}

    class StubSessions:
        def __init__(self, url):
            self.url = url

        def create(self, params):
            calls.setdefault("params", []).append(params)
            return {"url": self.url}

    class StubV1:
        def __init__(self):
            self.checkout = type("C", (), {"sessions": StubSessions("https://checkout/x")})()
            self.billing_portal = type(
                "P", (), {"sessions": StubSessions("https://portal/y")}
            )()

    class StubClient:
        def __init__(self):
            self.v1 = StubV1()

    monkeypatch.setattr(stripe_billing, "_get_client", lambda: StubClient())

    res = client.post("/api/billing/checkout", headers=headers)
    assert res.status_code == 200
    assert res.json() == {"url": "https://checkout/x"}
    assert calls["params"][0]["customer_email"] == "user@example.com"

    # Portal before any subscription is a conflict, not a Stripe call.
    assert client.post("/api/billing/portal", headers=headers).status_code == 409

    billing_module.link_stripe_subscription(
        user_id,
        customer_id="cus_1",
        subscription_id="sub_1",
        status="active",
        period_end=None,
        db_path=server_module.STORAGE_DIR / "slidecast.db",
    )
    res = client.post("/api/billing/portal", headers=headers)
    assert res.status_code == 200
    assert res.json() == {"url": "https://portal/y"}


def test_webhook_checkout_activates_subscription(client, monkeypatch):
    stripe_env(monkeypatch)
    user_id, headers = register(client)
    expire_trial(user_id)
    assert upload(client, headers).status_code == 403

    event = {
        "id": "evt_checkout",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "client_reference_id": str(user_id),
                "customer": "cus_1",
                "subscription": {
                    "id": "sub_1",
                    "status": "active",
                    "current_period_end": 2000000000,
                },
            }
        },
    }
    res = post_webhook(client, event)
    assert res.status_code == 200, res.text
    me = client.get("/api/auth/me", headers=headers).json()
    assert me["plan"]["state"] == "active"
    assert me["plan"]["has_subscription"] is True
    assert upload(client, headers).status_code == 200


def test_webhook_subscription_lifecycle(client, monkeypatch):
    stripe_env(monkeypatch)
    user_id, headers = register(client)
    dbp = server_module.STORAGE_DIR / "slidecast.db"
    billing_module.link_stripe_subscription(
        user_id,
        customer_id="cus_1",
        subscription_id="sub_9",
        status="active",
        period_end=None,
        db_path=dbp,
    )

    updated = {
        "id": "evt_upd",
        "type": "customer.subscription.updated",
        "data": {"object": {"id": "sub_9", "status": "past_due",
                            "current_period_end": 2000000000}},
    }
    assert post_webhook(client, updated).status_code == 200
    me = client.get("/api/auth/me", headers=headers).json()
    assert me["plan"]["state"] == "past_due"
    assert upload(client, headers).status_code == 403

    failed = {
        "id": "evt_fail",
        "type": "invoice.payment_failed",
        "data": {"object": {"subscription": "sub_9"}},
    }
    assert post_webhook(client, failed).status_code == 200
    me = client.get("/api/auth/me", headers=headers).json()
    assert me["plan"]["state"] == "past_due"

    deleted = {
        "id": "evt_del",
        "type": "customer.subscription.deleted",
        "data": {"object": {"id": "sub_9"}},
    }
    assert post_webhook(client, deleted).status_code == 200
    me = client.get("/api/auth/me", headers=headers).json()
    assert me["plan"]["state"] == "expired"


def test_webhook_rejects_bad_and_missing_signatures(client, monkeypatch):
    stripe_env(monkeypatch)
    register(client)
    event = {"id": "evt_x", "type": "ping", "data": {"object": {}}}
    payload = json.dumps(event).encode()

    res = client.post("/api/billing/webhook", content=payload)
    assert res.status_code == 400
    res = client.post(
        "/api/billing/webhook",
        content=payload,
        headers={"stripe-signature": "t=1,v1=deadbeef"},
    )
    assert res.status_code == 400
    res = post_webhook(client, event, secret="wrong-secret")
    assert res.status_code == 400


def test_webhook_ignores_unknown_events(client, monkeypatch):
    stripe_env(monkeypatch)
    register(client)
    event = {"id": "evt_u", "type": "something.else", "data": {"object": {}}}
    res = post_webhook(client, event)
    assert res.status_code == 200
    assert res.json()["type"] == "something.else"


def test_webhook_duplicate_delivery_processed_once(client, monkeypatch):
    stripe_env(monkeypatch)
    user_id, headers = register(client)
    event = {
        "id": "evt_dup",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "client_reference_id": str(user_id),
                "customer": "cus_dup",
                "subscription": {
                    "id": "sub_dup",
                    "status": "active",
                    "current_period_end": 2000000000,
                },
            }
        },
    }
    assert post_webhook(client, event).status_code == 200
    assert post_webhook(client, event).status_code == 200
    conn = db_module.connect(server_module.STORAGE_DIR / "slidecast.db")
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM webhook_events WHERE event_id = 'evt_dup'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == 1
    me = client.get("/api/auth/me", headers=headers).json()
    assert me["plan"]["state"] == "active"


def test_webhook_payment_succeeded_clears_past_due(client, monkeypatch):
    stripe_env(monkeypatch)
    user_id, headers = register(client)
    dbp = server_module.STORAGE_DIR / "slidecast.db"
    billing_module.link_stripe_subscription(
        user_id,
        customer_id="cus_1",
        subscription_id="sub_rec",
        status="past_due",
        period_end=None,
        db_path=dbp,
    )

    class StubSubs:
        def retrieve(self, sub_id):
            assert sub_id == "sub_rec"
            return {"id": sub_id, "status": "active",
                    "current_period_end": 2000000000}

    class StubV1:
        def __init__(self):
            self.subscriptions = StubSubs()

    class StubClient:
        def __init__(self):
            self.v1 = StubV1()

    monkeypatch.setattr(stripe_billing, "_get_client", lambda: StubClient())
    event = {
        "id": "evt_rec",
        "type": "invoice.payment_succeeded",
        "data": {"object": {"subscription": "sub_rec"}},
    }
    assert post_webhook(client, event).status_code == 200
    me = client.get("/api/auth/me", headers=headers).json()
    assert me["plan"]["state"] == "active"


def test_checkout_params_support_coupons_and_metadata(client, monkeypatch):
    stripe_env(monkeypatch)
    user_id, headers = register(client)
    calls = {}

    class StubSessions:
        def create(self, params):
            calls["params"] = params
            return {"url": "https://checkout/z"}

    class StubV1:
        def __init__(self):
            self.checkout = type("C", (), {"sessions": StubSessions()})()

    class StubClient:
        def __init__(self):
            self.v1 = StubV1()

    monkeypatch.setattr(stripe_billing, "_get_client", lambda: StubClient())
    assert client.post("/api/billing/checkout", headers=headers).status_code == 200
    assert calls["params"]["allow_promotion_codes"] is True
    assert calls["params"]["subscription_data"]["metadata"] == {
        "user_id": str(user_id),
        "app": "slidecast",
    }
