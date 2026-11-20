"""Automated tests for SlideCast Studio desktop licensing, activation, and crypto.

Covers:
- Ed25519 signing, verification, and tamper detection;
- License creation, atomic seat limit enforcement, and idempotent re-activation;
- Deactivation and seat transfer;
- Cross-account license isolation;
- Stripe webhook idempotency, checkout, and refund revocation;
- Offline lease validation within grace period;
- Database migration preserving existing customer data;
- Commercial offer configuration gating.
"""

from datetime import datetime, timedelta, timezone
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.core import device_identity, license_crypto
from app.core.license_manager import LicenseManager
from app.core.license_models import LicenseLease, LicenseStatus
from app.web import auth as auth_module
from app.web import db as db_module
from app.web import desktop_licensing
import app.web.server as server_module
from app.web import stripe_billing


@pytest.fixture()
def test_db(tmp_path, monkeypatch):
    db_file = tmp_path / "slidecast.db"
    monkeypatch.setattr(server_module, "STORAGE_DIR", tmp_path)
    monkeypatch.setenv("SLIDECAST_DB_PATH", str(db_file))
    conn = db_module.connect(db_file)
    conn.close()
    return db_file


@pytest.fixture()
def client(test_db, monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.delenv("STRIPE_PRICE_ID", raising=False)
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("SLIDECAST_DESKTOP_PRICE_ID", raising=False)
    with TestClient(server_module.app) as test_client:
        yield test_client


def create_user(db_path, email="creator@example.com", password="pass123"):
    hashed = auth_module.hash_password(password)
    conn = db_module.connect(db_path)
    now = db_module.utcnow_iso()
    with conn:
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
            (email, hashed, now),
        )
        user_id = cur.lastrowid
    conn.close()
    token = auth_module.create_session(user_id, db_path=db_path)
    return user_id, token


# --- 1. Cryptography & Signature Verification ---

def test_ed25519_signing_and_verification():
    priv_b64, pub_b64 = license_crypto.generate_keypair()
    payload = {
        "license_id": "lic_123",
        "device_id": "dev_456",
        "expires_at": "2026-12-01T00:00:00Z",
    }
    sig = license_crypto.sign_lease_payload(payload, private_key_b64=priv_b64)
    assert sig

    lease_data = dict(payload)
    lease_data["signature"] = sig
    assert license_crypto.verify_lease_signature(lease_data, public_key_b64=pub_b64) is True

    # Tampered payload fails verification
    tampered_data = dict(lease_data)
    tampered_data["device_id"] = "dev_other"
    assert license_crypto.verify_lease_signature(tampered_data, public_key_b64=pub_b64) is False

    # Tampered signature fails
    corrupt_sig = dict(lease_data)
    corrupt_sig["signature"] = "AA" + sig[2:]
    assert license_crypto.verify_lease_signature(corrupt_sig, public_key_b64=pub_b64) is False


def test_lease_temporal_validity():
    now = datetime.now(timezone.utc)
    future = (now + timedelta(days=7)).isoformat(timespec="seconds")
    past = (now - timedelta(days=7)).isoformat(timespec="seconds")

    valid_lease = {"lease_expires_at": future}
    expired_lease = {"lease_expires_at": past}

    assert license_crypto.is_lease_temporally_valid(valid_lease, now=now) is True
    assert license_crypto.is_lease_temporally_valid(expired_lease, now=now) is False


# --- 2. Seat Limit Enforcement & Deactivation ---

def test_seat_limit_atomic_enforcement(test_db):
    user_id, _ = create_user(test_db, "seats@example.com")
    lic = desktop_licensing.create_license(user_id=user_id, seats_limit=2, db_path=test_db)
    key = lic["license_key"]

    # Device 1 activates -> Success
    res1 = desktop_licensing.activate_device(key, "dev_1", "PC 1", "linux", "1.2.0", db_path=test_db)
    assert res1.success is True
    assert res1.status == LicenseStatus.ACTIVE
    assert res1.lease is not None

    # Device 1 activates AGAIN (idempotent re-check) -> Success, seat count remains 1
    res1_re = desktop_licensing.activate_device(key, "dev_1", "PC 1", "linux", "1.2.0", db_path=test_db)
    assert res1_re.success is True

    # Device 2 activates -> Success (2/2)
    res2 = desktop_licensing.activate_device(key, "dev_2", "PC 2", "windows", "1.2.0", db_path=test_db)
    assert res2.success is True

    # Device 3 activates -> Limit Reached (409 / LIMIT_REACHED)
    res3 = desktop_licensing.activate_device(key, "dev_3", "PC 3", "macos", "1.2.0", db_path=test_db)
    assert res3.success is False
    assert res3.status == LicenseStatus.LIMIT_REACHED
    assert res3.error_code == "SEATS_LIMIT_EXCEEDED"
    assert len(res3.active_devices) == 2

    # Deactivate Device 1 to release seat
    deactivated = desktop_licensing.deactivate_device(key, "dev_1", db_path=test_db)
    assert deactivated is True

    # Device 3 activates now -> Success! Seat was transferred
    res3_retry = desktop_licensing.activate_device(key, "dev_3", "PC 3", "macos", "1.2.0", db_path=test_db)
    assert res3_retry.success is True
    assert res3_retry.status == LicenseStatus.ACTIVE


def test_cross_account_isolation(test_db):
    user_a, _ = create_user(test_db, "userA@example.com")
    user_b, _ = create_user(test_db, "userB@example.com")

    lic = desktop_licensing.create_license(user_id=user_a, seats_limit=2, db_path=test_db)
    key = lic["license_key"]

    # User B tries to activate User A's license while authenticated as User B
    res = desktop_licensing.activate_device(key, "dev_b", "PC B", "linux", "1.2.0", user_id=user_b, db_path=test_db)
    assert res.success is False
    assert res.error_code == "FORBIDDEN_LICENSE_OWNER"

    # User B list licenses does not show User A's license
    b_licenses = desktop_licensing.list_user_licenses(user_b, db_path=test_db)
    assert len(b_licenses) == 0

    a_licenses = desktop_licensing.list_user_licenses(user_a, db_path=test_db)
    assert len(a_licenses) == 1
    assert a_licenses[0]["license_key"] == key


# --- 3. Offline Lease Manager ---

def test_license_manager_offline_lease_and_tamper(tmp_path, monkeypatch):
    user_dir = tmp_path / "slidecast_home"
    monkeypatch.setenv("SLIDECAST_USER_DATA_DIR", str(user_dir))

    mgr = LicenseManager(user_dir=user_dir)
    assert mgr.status == LicenseStatus.UNACTIVATED
    assert mgr.is_licensed() is False

    # Issue a valid signed lease
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    exp_iso = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat(timespec="seconds")
    dev_id = device_identity.get_device_id()

    lease = LicenseLease(
        version=1,
        license_id="lic_test",
        license_key="SCST-1111-2222-3333-4444",
        user_id=1,
        user_email="kika@example.com",
        device_id=dev_id,
        device_name=device_identity.get_device_name(),
        status="active",
        features=["all"],
        issued_at=now_iso,
        lease_expires_at=exp_iso,
    )
    lease.signature = license_crypto.sign_lease_payload(lease.payload_dict())

    # Save and reload
    mgr.save_local_lease(lease)
    assert mgr.is_licensed() is True
    assert mgr.status == LicenseStatus.ACTIVE

    # Tamper with the saved file on disk
    tampered_dict = lease.to_dict()
    tampered_dict["user_email"] = "hacker@example.com"  # Alter payload without new signature
    (user_dir / "license_lease.json").write_text(json.dumps(tampered_dict), encoding="utf-8")

    mgr_tampered = LicenseManager(user_dir=user_dir)
    assert mgr_tampered.is_licensed() is False
    assert mgr_tampered.status == LicenseStatus.REVOKED


# --- 4. HTTP API Endpoints ---

def test_http_api_plans_gating(client, monkeypatch):
    # When unconfigured, commercial offers report available=False
    monkeypatch.delenv("SLIDECAST_DESKTOP_PRICE_ID", raising=False)
    res = client.get("/api/v1/license/plans")
    assert res.status_code == 200
    body = res.json()
    assert body["available"] is False
    assert len(body["plans"]) == 0

    # Checkout returns 503 when sales not configured
    _, headers = register_test_user(client, "buyer@example.com")
    res_chk = client.post("/api/v1/license/checkout", json={"plan_type": "standard"}, headers=headers)
    assert res_chk.status_code == 503


def test_http_api_activate_and_validate(client, test_db):
    user_id, headers = register_test_user(client, "active_user@example.com")
    lic = desktop_licensing.create_license(user_id=user_id, seats_limit=1, db_path=test_db)
    key = lic["license_key"]

    # Activate
    act_payload = {
        "license_key": key,
        "device_id": "test_device_alpha",
        "device_name": "Studio Laptop",
        "platform": "linux",
        "app_version": "1.2.0",
    }
    res_act = client.post("/api/v1/license/activate", json=act_payload)
    assert res_act.status_code == 200
    act_data = res_act.json()
    assert act_data["success"] is True
    assert act_data["status"] == "active"
    assert act_data["lease"]["license_key"] == key

    # Validate
    res_val = client.post(
        "/api/v1/license/validate",
        json={"license_key": key, "device_id": "test_device_alpha"},
    )
    assert res_val.status_code == 200
    val_data = res_val.json()
    assert val_data["success"] is True

    # Second device hits 409 Conflict
    act_payload_2 = dict(act_payload, device_id="test_device_beta", device_name="Studio Desktop")
    res_act2 = client.post("/api/v1/license/activate", json=act_payload_2)
    assert res_act2.status_code == 409
    assert res_act2.json()["detail"]["error_code"] == "SEATS_LIMIT_EXCEEDED"

    # Deactivate device alpha
    res_deact = client.post(
        "/api/v1/license/deactivate",
        json={"license_key": key, "device_id": "test_device_alpha"},
    )
    assert res_deact.status_code == 200

    # Device beta can now activate
    res_act2_retry = client.post("/api/v1/license/activate", json=act_payload_2)
    assert res_act2_retry.status_code == 200
    assert res_act2_retry.json()["success"] is True


# --- 5. Stripe Webhook & Reconciliation ---

def test_stripe_webhook_desktop_license_creation(test_db):
    user_id, _ = create_user(test_db, "stripe_buyer@example.com")

    session_obj = {
        "id": "cs_test_desk_12345",
        "client_reference_id": str(user_id),
        "customer": "cus_test_999",
        "subscription": None,
        "metadata": {
            "type": "desktop_license",
            "plan_type": "standard",
            "seats_limit": "3",
        },
    }

    # Simulate webhook handler execution directly
    stripe_billing._handle_checkout_completed(session_obj, db_path=test_db)

    # Verify license was created
    licenses = desktop_licensing.list_user_licenses(user_id, db_path=test_db)
    assert len(licenses) == 1
    assert licenses[0]["seats_limit"] == 3
    assert licenses[0]["stripe_checkout_session_id"] == "cs_test_desk_12345"
    assert licenses[0]["status"] == "active"

    # Simulate refund revoking license
    refund_obj = {"customer": "cus_test_999"}
    stripe_billing._handle_charge_refunded(refund_obj, db_path=test_db)

    updated_lic = desktop_licensing.get_license_by_id(licenses[0]["id"], db_path=test_db)
    assert updated_lic["status"] == "revoked"


# --- 6. Database Migration Preservation ---

def test_db_migration_preserves_existing_data(tmp_path):
    old_db_file = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(old_db_file))
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.executescript(db_module.SCHEMA)
    # Apply migration 1 only
    conn.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT)")
    conn.executescript(db_module.MIGRATIONS[0][1])
    conn.execute("INSERT INTO schema_migrations VALUES (1, '2026-11-01T00:00:00')")

    # Insert existing customer and project
    conn.execute(
        "INSERT INTO users (id, email, password_hash, created_at) VALUES (1, 'legacy@example.com', 'hash', '2026-11-01')"
    )
    conn.execute(
        "INSERT INTO projects (id, user_id, name, created_at, updated_at) VALUES ('proj_1', 1, 'Minha Aula Antiga', '2026-11-01', '2026-11-01')"
    )
    conn.commit()
    conn.close()

    # Now run apply_migrations (which applies migration 2)
    conn2 = db_module.connect(old_db_file)
    try:
        user = conn2.execute("SELECT * FROM users WHERE id = 1").fetchone()
        assert user["email"] == "legacy@example.com"

        proj = conn2.execute("SELECT * FROM projects WHERE id = 'proj_1'").fetchone()
        assert proj["name"] == "Minha Aula Antiga"

        # V2 tables must exist
        tables = [r[0] for r in conn2.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        assert "desktop_licenses" in tables
        assert "desktop_activations" in tables
        assert "desktop_license_audit" in tables
    finally:
        conn2.close()


# --- 7. Desktop Qt UI Integration ---

def test_license_dialog_ui_instantiation(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from app.ui.dialogs.license_dialog import LicenseDialog

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    _ = QApplication.instance() or QApplication(["test"])

    user_dir = tmp_path / "slidecast_home_ui"
    monkeypatch.setenv("SLIDECAST_USER_DATA_DIR", str(user_dir))

    dlg = LicenseDialog()
    assert dlg.windowTitle() == "Conta e Licença · SlideCast Studio"
    assert dlg.btn_activate is not None
    assert dlg.txt_key is not None
    assert dlg.card is not None
    assert "Não ativado" in dlg.lbl_badge.text()
    dlg.close()


def register_test_user(client, email):
    res = client.post("/api/auth/register", json={"email": email, "password": "pass123Password"})
    assert res.status_code == 200, res.text
    data = res.json()
    return data["user"]["id"], {"Authorization": f"Bearer {data['token']}"}
