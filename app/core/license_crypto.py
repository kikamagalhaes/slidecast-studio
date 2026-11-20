"""Cryptographic signing and verification for SlideCast Studio desktop leases.

Uses Ed25519 asymmetric signatures. The private signing key resides exclusively
on the server. The public verification key is embedded for offline verification
and can be overridden via the SLIDECAST_LICENSE_ED25519_PUBLIC_KEY env var.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import json
import logging
import os
from typing import Any, Dict, Optional, Tuple

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

logger = logging.getLogger(__name__)

# Default embedded public key for local offline verification
DEFAULT_PUBLIC_KEY_B64 = "d1jGvia2V30jgxtOGOXThJNZH2dNyJfC1FjSAQLSlNw="

# Default dev/test private key (used ONLY in non-production environments when not set in env)
DEV_FALLBACK_PRIVATE_KEY_B64 = "+MoUmfwXdl7UJ7lbiLSe86avZJ7dbF491EyiNdcxh7A="


def canonical_json_bytes(data: Dict[str, Any]) -> bytes:
    """Serialize dictionary to deterministic, canonical JSON UTF-8 bytes."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def get_public_key_b64() -> str:
    """Get active public key base64 from environment or embedded default."""
    return os.environ.get("SLIDECAST_LICENSE_ED25519_PUBLIC_KEY", DEFAULT_PUBLIC_KEY_B64).strip()


def get_private_key_b64() -> Optional[str]:
    """Get server private key base64 from environment or dev fallback if allowed."""
    key = os.environ.get("SLIDECAST_LICENSE_ED25519_PRIVATE_KEY", "").strip()
    if key:
        return key
    is_prod = os.environ.get("ENV") == "production" or os.environ.get("APP_ENV") == "production"
    if not is_prod:
        return DEV_FALLBACK_PRIVATE_KEY_B64
    return None


def generate_keypair() -> Tuple[str, str]:
    """Generate a fresh Ed25519 keypair, returning (private_b64, public_b64)."""
    priv = ed25519.Ed25519PrivateKey.generate()
    priv_raw = priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub = priv.public_key()
    pub_raw = pub.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return (
        base64.b64encode(priv_raw).decode("utf-8"),
        base64.b64encode(pub_raw).decode("utf-8"),
    )


def sign_lease_payload(payload: Dict[str, Any], private_key_b64: Optional[str] = None) -> str:
    """Sign payload dictionary with Ed25519 private key, returning base64 signature."""
    priv_b64 = private_key_b64 or get_private_key_b64()
    if not priv_b64:
        raise ValueError("SLIDECAST_LICENSE_ED25519_PRIVATE_KEY must be configured on the server.")

    raw_priv = base64.b64decode(priv_b64)
    private_key = ed25519.Ed25519PrivateKey.from_private_bytes(raw_priv)

    clean_payload = dict(payload)
    clean_payload.pop("signature", None)

    data_bytes = canonical_json_bytes(clean_payload)
    sig_bytes = private_key.sign(data_bytes)
    return base64.b64encode(sig_bytes).decode("utf-8")


def verify_lease_signature(lease_data: Dict[str, Any], public_key_b64: Optional[str] = None) -> bool:
    """Verify Ed25519 signature of lease dictionary against public key."""
    signature_b64 = lease_data.get("signature")
    if not signature_b64:
        return False

    pub_b64 = public_key_b64 or get_public_key_b64()
    try:
        raw_pub = base64.b64decode(pub_b64)
        public_key = ed25519.Ed25519PublicKey.from_public_bytes(raw_pub)
        raw_sig = base64.b64decode(signature_b64)
    except Exception as exc:
        logger.warning("Invalid base64 in signature or public key: %s", exc)
        return False

    clean_payload = dict(lease_data)
    clean_payload.pop("signature", None)
    data_bytes = canonical_json_bytes(clean_payload)

    try:
        public_key.verify(raw_sig, data_bytes)
        return True
    except InvalidSignature:
        logger.warning("Ed25519 signature verification failed.")
        return False
    except Exception as exc:
        logger.warning("Signature verification exception: %s", exc)
        return False


def is_lease_temporally_valid(lease_data: Dict[str, Any], now: Optional[datetime] = None, grace_seconds: int = 3600) -> bool:
    """Check if lease expiry timestamp is in the future (with clock drift grace)."""
    expiry_iso = lease_data.get("lease_expires_at")
    if not expiry_iso:
        return False

    now_dt = now or datetime.now(timezone.utc)
    try:
        expires_dt = datetime.fromisoformat(expiry_iso)
        if expires_dt.tzinfo is None:
            expires_dt = expires_dt.replace(tzinfo=timezone.utc)
    except Exception:
        return False

    # Check expiration with grace allowance
    time_remaining = (expires_dt - now_dt).total_seconds()
    return (time_remaining + grace_seconds) >= 0
