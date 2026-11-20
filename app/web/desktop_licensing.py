"""Server-side business logic and persistence for SlideCast Desktop licensing.

Implements atomic seat enforcement, signed Ed25519 lease issuance, audit logging,
and Stripe webhook event reconciliation.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import secrets
from typing import Any, Dict, List, Optional, Union
import uuid

from app.core import license_crypto
from app.core.license_models import ActivationResult, LicenseLease, LicenseStatus
from app.web import db as db_module

logger = logging.getLogger(__name__)

DbPath = Optional[Union[str, Path]]

KEY_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def generate_license_key() -> str:
    """Generate human-readable license key: SCST-XXXX-XXXX-XXXX-XXXX."""
    parts = ["SCST"]
    for _ in range(4):
        part = "".join(secrets.choice(KEY_ALPHABET) for _ in range(4))
        parts.append(part)
    return "-".join(parts)


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_license(
    user_id: int,
    plan_type: str = "standard",
    seats_limit: int = 2,
    expires_at: Optional[str] = None,
    stripe_customer_id: Optional[str] = None,
    stripe_subscription_id: Optional[str] = None,
    stripe_checkout_session_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    db_path: DbPath = None,
) -> Dict[str, Any]:
    """Create a new desktop license for a user and record audit entry."""
    conn = db_module.connect(db_path)
    lic_id = f"lic_{uuid.uuid4().hex[:16]}"
    key = generate_license_key()
    now = utcnow_iso()
    meta_json = json.dumps(metadata or {}, ensure_ascii=True)

    try:
        with conn:
            conn.execute(
                """
                INSERT INTO desktop_licenses (
                    id, user_id, license_key, status, plan_type, seats_limit,
                    expires_at, stripe_customer_id, stripe_subscription_id,
                    stripe_checkout_session_id, metadata, created_at, updated_at
                ) VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lic_id,
                    user_id,
                    key,
                    plan_type,
                    seats_limit,
                    expires_at,
                    stripe_customer_id,
                    stripe_subscription_id,
                    stripe_checkout_session_id,
                    meta_json,
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO desktop_license_audit (license_id, action, details, created_at)
                VALUES (?, 'created', ?, ?)
                """,
                (lic_id, json.dumps({"user_id": user_id, "plan_type": plan_type, "seats": seats_limit}), now),
            )
    finally:
        conn.close()

    return get_license_by_id(lic_id, db_path=db_path) or {}


def get_license_by_id(license_id: str, db_path: DbPath = None) -> Optional[Dict[str, Any]]:
    conn = db_module.connect(db_path)
    try:
        row = conn.execute("SELECT * FROM desktop_licenses WHERE id = ?", (license_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_license_by_key(license_key: str, db_path: DbPath = None) -> Optional[Dict[str, Any]]:
    cleaned_key = license_key.strip().upper()
    conn = db_module.connect(db_path)
    try:
        row = conn.execute("SELECT * FROM desktop_licenses WHERE license_key = ?", (cleaned_key,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_email(user_id: int, db_path: DbPath = None) -> Optional[str]:
    conn = db_module.connect(db_path)
    try:
        row = conn.execute("SELECT email FROM users WHERE id = ?", (user_id,)).fetchone()
        return row["email"] if row else None
    finally:
        conn.close()


def list_user_licenses(user_id: int, db_path: DbPath = None) -> List[Dict[str, Any]]:
    """Return all licenses for a user along with their active devices."""
    conn = db_module.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM desktop_licenses WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
        licenses = []
        for r in rows:
            lic = dict(r)
            act_rows = conn.execute(
                """
                SELECT id, device_id, device_name, platform, app_version, status,
                       lease_expires_at, last_validated_at, activated_at
                FROM desktop_activations
                WHERE license_id = ? AND status = 'active'
                ORDER BY activated_at ASC
                """,
                (lic["id"],),
            ).fetchall()
            lic["active_devices"] = [dict(a) for a in act_rows]
            lic["active_count"] = len(lic["active_devices"])
            licenses.append(lic)
        return licenses
    finally:
        conn.close()


def activate_device(
    license_key: str,
    device_id: str,
    device_name: str,
    platform: str,
    app_version: str,
    user_id: Optional[int] = None,
    lease_duration_days: int = 14,
    ip_address: Optional[str] = None,
    db_path: DbPath = None,
) -> ActivationResult:
    """Atomically activate device under seat limit, returning signed lease."""
    cleaned_key = license_key.strip().upper()
    conn = db_module.connect(db_path)
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat(timespec="seconds")
    lease_expires_iso = (now + timedelta(days=lease_duration_days)).isoformat(timespec="seconds")

    try:
        with conn:
            # 1. Fetch license
            lic_row = conn.execute(
                "SELECT * FROM desktop_licenses WHERE license_key = ?",
                (cleaned_key,),
            ).fetchone()
            if not lic_row:
                return ActivationResult(
                    success=False,
                    status=LicenseStatus.UNACTIVATED,
                    message="Chave de licença não encontrada.",
                    error_code="LICENSE_NOT_FOUND",
                )

            license_data = dict(lic_row)
            lic_id = license_data["id"]
            owner_id = license_data["user_id"]
            status = license_data["status"]
            seats_limit = int(license_data["seats_limit"])
            expires_at = license_data.get("expires_at")

            # Check owner isolation if user_id is provided
            if user_id is not None and user_id != owner_id:
                return ActivationResult(
                    success=False,
                    status=LicenseStatus.UNACTIVATED,
                    message="Esta licença pertence a outra conta.",
                    error_code="FORBIDDEN_LICENSE_OWNER",
                )

            # Check status
            if status != "active":
                status_enum = LicenseStatus.EXPIRED if status == "expired" else LicenseStatus.REVOKED
                return ActivationResult(
                    success=False,
                    status=status_enum,
                    message=f"Licença não está ativa (situação: {status}).",
                    seats_limit=seats_limit,
                    error_code="LICENSE_INACTIVE",
                )

            # Check expiration
            if expires_at:
                try:
                    exp_dt = datetime.fromisoformat(expires_at)
                    if exp_dt.tzinfo is None:
                        exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                    if exp_dt < now:
                        conn.execute("UPDATE desktop_licenses SET status = 'expired' WHERE id = ?", (lic_id,))
                        return ActivationResult(
                            success=False,
                            status=LicenseStatus.EXPIRED,
                            message="Esta licença expirou.",
                            seats_limit=seats_limit,
                            error_code="LICENSE_EXPIRED",
                        )
                except Exception:
                    pass

            # 2. Check existing activation for this device
            act_row = conn.execute(
                "SELECT * FROM desktop_activations WHERE license_id = ? AND device_id = ?",
                (lic_id, device_id),
            ).fetchone()

            is_already_active = act_row and act_row["status"] == "active"

            if not is_already_active:
                # Count current active activations
                count_row = conn.execute(
                    "SELECT COUNT(*) as c FROM desktop_activations WHERE license_id = ? AND status = 'active'",
                    (lic_id,),
                ).fetchone()
                active_count = count_row["c"] if count_row else 0

                if active_count >= seats_limit:
                    active_devices_rows = conn.execute(
                        "SELECT id, device_name, platform, activated_at, last_validated_at FROM desktop_activations WHERE license_id = ? AND status = 'active'",
                        (lic_id,),
                    ).fetchall()
                    active_devices = [dict(r) for r in active_devices_rows]
                    return ActivationResult(
                        success=False,
                        status=LicenseStatus.LIMIT_REACHED,
                        message=f"Limite de dispositivos atingido ({active_count}/{seats_limit}). Desative um dispositivo anterior para continuar.",
                        active_devices=active_devices,
                        seats_limit=seats_limit,
                        error_code="SEATS_LIMIT_EXCEEDED",
                    )

            # 3. Create or update activation
            if act_row:
                conn.execute(
                    """
                    UPDATE desktop_activations
                    SET status = 'active', device_name = ?, platform = ?, app_version = ?,
                        lease_expires_at = ?, last_validated_at = ?, deactivated_at = NULL
                    WHERE license_id = ? AND device_id = ?
                    """,
                    (device_name, platform, app_version, lease_expires_iso, now_iso, lic_id, device_id),
                )
            else:
                act_id = f"act_{uuid.uuid4().hex[:16]}"
                conn.execute(
                    """
                    INSERT INTO desktop_activations (
                        id, license_id, user_id, device_id, device_name, platform,
                        app_version, status, lease_expires_at, last_validated_at,
                        activated_at, deactivated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, NULL)
                    """,
                    (
                        act_id,
                        lic_id,
                        owner_id,
                        device_id,
                        device_name,
                        platform,
                        app_version,
                        lease_expires_iso,
                        now_iso,
                        now_iso,
                    ),
                )

            # 4. Audit log
            conn.execute(
                """
                INSERT INTO desktop_license_audit (license_id, action, details, ip_address, created_at)
                VALUES (?, 'activated', ?, ?, ?)
                """,
                (
                    lic_id,
                    json.dumps({"device_id": device_id, "device_name": device_name, "platform": platform}),
                    ip_address,
                    now_iso,
                ),
            )

            # Fetch owner email
            user_row = conn.execute("SELECT email FROM users WHERE id = ?", (owner_id,)).fetchone()
            user_email = user_row["email"] if user_row else None

    finally:
        conn.close()

    # 5. Build signed lease
    lease = LicenseLease(
        version=1,
        license_id=lic_id,
        license_key=cleaned_key,
        user_id=owner_id,
        user_email=user_email,
        device_id=device_id,
        device_name=device_name,
        status="active",
        features=["all"],
        issued_at=now_iso,
        lease_expires_at=lease_expires_iso,
    )
    lease.signature = license_crypto.sign_lease_payload(lease.payload_dict())

    return ActivationResult(
        success=True,
        status=LicenseStatus.ACTIVE,
        message="Dispositivo ativado com sucesso.",
        lease=lease,
        seats_limit=seats_limit,
    )


def validate_device(
    license_key: str,
    device_id: str,
    lease_duration_days: int = 14,
    ip_address: Optional[str] = None,
    db_path: DbPath = None,
) -> ActivationResult:
    """Validate activation status and refresh offline signed lease."""
    cleaned_key = license_key.strip().upper()
    conn = db_module.connect(db_path)
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat(timespec="seconds")
    lease_expires_iso = (now + timedelta(days=lease_duration_days)).isoformat(timespec="seconds")

    try:
        with conn:
            lic_row = conn.execute("SELECT * FROM desktop_licenses WHERE license_key = ?", (cleaned_key,)).fetchone()
            if not lic_row:
                return ActivationResult(
                    success=False,
                    status=LicenseStatus.UNACTIVATED,
                    message="Licença não encontrada.",
                    error_code="LICENSE_NOT_FOUND",
                )

            lic = dict(lic_row)
            lic_id = lic["id"]
            status = lic["status"]
            seats_limit = int(lic["seats_limit"])
            owner_id = lic["user_id"]

            if status != "active":
                status_enum = LicenseStatus.EXPIRED if status == "expired" else LicenseStatus.REVOKED
                return ActivationResult(
                    success=False,
                    status=status_enum,
                    message=f"Licença não está ativa ({status}).",
                    seats_limit=seats_limit,
                    error_code="LICENSE_INACTIVE",
                )

            act_row = conn.execute(
                "SELECT * FROM desktop_activations WHERE license_id = ? AND device_id = ?",
                (lic_id, device_id),
            ).fetchone()
            if not act_row or act_row["status"] != "active":
                return ActivationResult(
                    success=False,
                    status=LicenseStatus.UNACTIVATED,
                    message="Este dispositivo não possui ativação ativa para esta licença.",
                    seats_limit=seats_limit,
                    error_code="DEVICE_NOT_ACTIVATED",
                )

            device_name = act_row["device_name"]

            # Refresh lease and last_validated_at
            conn.execute(
                """
                UPDATE desktop_activations
                SET lease_expires_at = ?, last_validated_at = ?
                WHERE license_id = ? AND device_id = ?
                """,
                (lease_expires_iso, now_iso, lic_id, device_id),
            )
            conn.execute(
                """
                INSERT INTO desktop_license_audit (license_id, action, details, ip_address, created_at)
                VALUES (?, 'validated', ?, ?, ?)
                """,
                (lic_id, json.dumps({"device_id": device_id}), ip_address, now_iso),
            )

            user_row = conn.execute("SELECT email FROM users WHERE id = ?", (owner_id,)).fetchone()
            user_email = user_row["email"] if user_row else None

    finally:
        conn.close()

    lease = LicenseLease(
        version=1,
        license_id=lic_id,
        license_key=cleaned_key,
        user_id=owner_id,
        user_email=user_email,
        device_id=device_id,
        device_name=device_name,
        status="active",
        features=["all"],
        issued_at=now_iso,
        lease_expires_at=lease_expires_iso,
    )
    lease.signature = license_crypto.sign_lease_payload(lease.payload_dict())

    return ActivationResult(
        success=True,
        status=LicenseStatus.ACTIVE,
        message="Ativação válida.",
        lease=lease,
        seats_limit=seats_limit,
    )


def deactivate_device(
    license_key_or_id: str,
    device_id: str,
    user_id: Optional[int] = None,
    ip_address: Optional[str] = None,
    db_path: DbPath = None,
) -> bool:
    """Deactivate a device to free up a seat."""
    conn = db_module.connect(db_path)
    now_iso = utcnow_iso()
    cleaned = license_key_or_id.strip().upper()

    try:
        with conn:
            lic_row = conn.execute(
                "SELECT id, user_id FROM desktop_licenses WHERE id = ? OR license_key = ?",
                (license_key_or_id, cleaned),
            ).fetchone()
            if not lic_row:
                return False

            lic_id = lic_row["id"]
            if user_id is not None and lic_row["user_id"] != user_id:
                return False

            res = conn.execute(
                """
                UPDATE desktop_activations
                SET status = 'deactivated', deactivated_at = ?
                WHERE license_id = ? AND device_id = ? AND status = 'active'
                """,
                (now_iso, lic_id, device_id),
            )
            if res.rowcount > 0:
                conn.execute(
                    """
                    INSERT INTO desktop_license_audit (license_id, action, details, ip_address, created_at)
                    VALUES (?, 'deactivated', ?, ?, ?)
                    """,
                    (lic_id, json.dumps({"device_id": device_id}), ip_address, now_iso),
                )
                return True
            return False
    finally:
        conn.close()


def revoke_or_suspend_license(
    license_id_or_key: str,
    new_status: str = "revoked",
    reason: str = "",
    ip_address: Optional[str] = None,
    db_path: DbPath = None,
) -> bool:
    conn = db_module.connect(db_path)
    now_iso = utcnow_iso()
    cleaned = license_id_or_key.strip().upper()
    try:
        with conn:
            row = conn.execute(
                "SELECT id FROM desktop_licenses WHERE id = ? OR license_key = ?",
                (license_id_or_key, cleaned),
            ).fetchone()
            if not row:
                return False
            lic_id = row["id"]
            conn.execute(
                "UPDATE desktop_licenses SET status = ?, updated_at = ? WHERE id = ?",
                (new_status, now_iso, lic_id),
            )
            conn.execute(
                """
                INSERT INTO desktop_license_audit (license_id, action, details, ip_address, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (lic_id, new_status, json.dumps({"reason": reason}), ip_address, now_iso),
            )
            return True
    finally:
        conn.close()
