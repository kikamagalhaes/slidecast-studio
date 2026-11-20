"""Client-side license manager for SlideCast Studio Desktop.

Manages offline signed leases, non-intrusive seat verification, device identity,
and local persistence under ~/.slidecast/license_lease.json.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

import requests

from app.core import device_identity, license_crypto
from app.core.license_models import ActivationResult, LicenseLease, LicenseStatus

logger = logging.getLogger(__name__)

DEFAULT_SERVER_URL = "https://kikamagalhaes.com.br/slidecast"


class LicenseManager:
    """Coordinates local license validation, offline grace periods, and online sync."""

    def __init__(self, user_dir: Optional[Path] = None):
        self.user_dir = user_dir or device_identity.get_slidecast_user_dir()
        self.lease_file = self.user_dir / "license_lease.json"
        self._lease: Optional[LicenseLease] = None
        self._status: LicenseStatus = LicenseStatus.UNACTIVATED
        self._last_error: Optional[str] = None
        self.load_local_lease()

    @property
    def status(self) -> LicenseStatus:
        return self._status

    @property
    def lease(self) -> Optional[LicenseLease]:
        return self._lease

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    def is_licensed(self) -> bool:
        """Return True if local lease is cryptographically valid and active (including offline mode)."""
        return self._status in (LicenseStatus.ACTIVE, LicenseStatus.NO_CONNECTION)

    def get_server_url(self) -> str:
        override = os.environ.get("SLIDECAST_LICENSE_SERVER_URL") or os.environ.get("PUBLIC_SITE_URL")
        if override:
            return override.rstrip("/")
        return DEFAULT_SERVER_URL

    def load_local_lease(self) -> LicenseStatus:
        """Load and cryptographically verify local lease file without network."""
        if not self.lease_file.is_file():
            self._lease = None
            self._status = LicenseStatus.UNACTIVATED
            return self._status

        try:
            content = self.lease_file.read_text(encoding="utf-8")
            data = json.loads(content)
            lease = LicenseLease.from_dict(data)
        except Exception as exc:
            logger.warning("Could not parse local license lease: %s", exc)
            self._lease = None
            self._status = LicenseStatus.UNACTIVATED
            return self._status

        # 1. Verify cryptographic signature
        if not license_crypto.verify_lease_signature(lease.to_dict()):
            logger.warning("Local license lease signature verification failed. Lease rejected.")
            self._lease = None
            self._status = LicenseStatus.REVOKED
            self._last_error = "Assinatura digital da licença inválida ou adulterada."
            return self._status

        # 2. Verify device identity matches current machine
        current_dev_id = device_identity.get_device_id()
        if lease.device_id != current_dev_id:
            logger.warning("Lease device ID mismatch (%s != %s).", lease.device_id, current_dev_id)
            self._lease = None
            self._status = LicenseStatus.UNACTIVATED
            self._last_error = "Licença vinculada a outro computador."
            return self._status

        # 3. Check expiration
        if not license_crypto.is_lease_temporally_valid(lease.to_dict()):
            logger.info("Local license lease has expired (%s).", lease.lease_expires_at)
            self._lease = lease
            self._status = LicenseStatus.EXPIRED
            self._last_error = "O período da licença expirou."
            return self._status

        self._lease = lease
        self._status = LicenseStatus.ACTIVE
        self._last_error = None
        return self._status

    def save_local_lease(self, lease: LicenseLease) -> bool:
        """Save verified lease to disk with mode 0600."""
        try:
            self.user_dir.mkdir(parents=True, exist_ok=True)
            payload_str = json.dumps(lease.to_dict(), indent=2, ensure_ascii=False)
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
            mode = 0o600
            fd = os.open(str(self.lease_file), flags, mode)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload_str)
            self._lease = lease
            self._status = LicenseStatus.ACTIVE
            self._last_error = None
            return True
        except OSError as exc:
            logger.error("Failed to persist license lease: %s", exc)
            return False

    def clear_local_lease(self) -> bool:
        """Clear local activation state."""
        self._lease = None
        self._status = LicenseStatus.UNACTIVATED
        self._last_error = None
        if self.lease_file.is_file():
            try:
                self.lease_file.unlink()
                return True
            except OSError:
                return False
        return True

    def activate_online(
        self,
        license_key: str,
        auth_token: Optional[str] = None,
        server_url: Optional[str] = None,
        timeout: float = 10.0,
    ) -> ActivationResult:
        """Activate device against online server."""
        base_url = (server_url or self.get_server_url()).rstrip("/")
        endpoint = f"{base_url}/api/v1/license/activate"

        payload = {
            "license_key": license_key.strip().upper(),
            "device_id": device_identity.get_device_id(),
            "device_name": device_identity.get_device_name(),
            "platform": device_identity.get_platform_name(),
            "app_version": "1.2.0",
        }

        headers = {"Content-Type": "application/json"}
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"

        try:
            res = requests.post(endpoint, json=payload, headers=headers, timeout=timeout)
        except requests.RequestException as exc:
            self._last_error = f"Sem conexão com o servidor de licença: {exc}"
            return ActivationResult(
                success=False,
                status=LicenseStatus.NO_CONNECTION,
                message="Não foi possível conectar ao servidor de licença. Verifique sua conexão.",
                error_code="NETWORK_ERROR",
            )

        try:
            body = res.json()
        except Exception:
            body = {"message": res.text}

        if res.status_code == 200 and body.get("success"):
            lease_dict = body.get("lease")
            if not lease_dict:
                return ActivationResult(
                    success=False,
                    status=LicenseStatus.UNACTIVATED,
                    message="Servidor não enviou autorização assinada.",
                    error_code="INVALID_SERVER_RESPONSE",
                )
            lease = LicenseLease.from_dict(lease_dict)
            if not license_crypto.verify_lease_signature(lease.to_dict()):
                return ActivationResult(
                    success=False,
                    status=LicenseStatus.REVOKED,
                    message="Assinatura da autorização recebida é inválida.",
                    error_code="INVALID_SIGNATURE",
                )
            self.save_local_lease(lease)
            return ActivationResult(
                success=True,
                status=LicenseStatus.ACTIVE,
                message=body.get("message", "Dispositivo ativado com sucesso!"),
                lease=lease,
                seats_limit=body.get("seats_limit", 2),
            )

        # Handle specific error statuses
        detail = body.get("detail", body)
        err_code = detail.get("error_code") if isinstance(detail, dict) else None
        active_devices = detail.get("active_devices", []) if isinstance(detail, dict) else []
        seats_limit = detail.get("seats_limit", 2) if isinstance(detail, dict) else 2
        msg = detail.get("message") if isinstance(detail, dict) else str(detail)

        if res.status_code == 409 or err_code == "SEATS_LIMIT_EXCEEDED":
            return ActivationResult(
                success=False,
                status=LicenseStatus.LIMIT_REACHED,
                message=msg or "Limite de dispositivos atingido.",
                active_devices=active_devices,
                seats_limit=seats_limit,
                error_code="SEATS_LIMIT_EXCEEDED",
            )

        return ActivationResult(
            success=False,
            status=LicenseStatus.UNACTIVATED,
            message=msg or "Falha na ativação da licença.",
            error_code=err_code or f"HTTP_{res.status_code}",
        )

    def validate_online(self, server_url: Optional[str] = None, timeout: float = 8.0) -> ActivationResult:
        """Validate current activation online and refresh offline lease."""
        if not self._lease:
            return ActivationResult(
                success=False,
                status=LicenseStatus.UNACTIVATED,
                message="Nenhuma licença ativa neste dispositivo.",
                error_code="NO_LOCAL_LICENSE",
            )

        base_url = (server_url or self.get_server_url()).rstrip("/")
        endpoint = f"{base_url}/api/v1/license/validate"
        payload = {
            "license_key": self._lease.license_key,
            "device_id": self._lease.device_id,
        }

        try:
            res = requests.post(endpoint, json=payload, timeout=timeout)
        except requests.RequestException:
            # When offline, if local lease is temporally valid, remain active in offline mode!
            if license_crypto.is_lease_temporally_valid(self._lease.to_dict()):
                self._status = LicenseStatus.NO_CONNECTION
                return ActivationResult(
                    success=True,
                    status=LicenseStatus.NO_CONNECTION,
                    message="Modo offline: licença válida localmente.",
                    lease=self._lease,
                )
            self._status = LicenseStatus.EXPIRED
            return ActivationResult(
                success=False,
                status=LicenseStatus.EXPIRED,
                message="Período offline expirado. Conecte-se à internet para revalidar.",
                error_code="OFFLINE_LEASE_EXPIRED",
            )

        if res.status_code == 200:
            body = res.json()
            lease_dict = body.get("lease")
            if lease_dict:
                lease = LicenseLease.from_dict(lease_dict)
                if license_crypto.verify_lease_signature(lease.to_dict()):
                    self.save_local_lease(lease)
                    return ActivationResult(
                        success=True,
                        status=LicenseStatus.ACTIVE,
                        message="Licença validada com sucesso.",
                        lease=lease,
                    )

        # Server rejected activation
        self._status = LicenseStatus.EXPIRED
        return ActivationResult(
            success=False,
            status=LicenseStatus.EXPIRED,
            message="Ativação não reconhecida pelo servidor.",
            error_code=f"HTTP_{res.status_code}",
        )

    def deactivate_online(self, server_url: Optional[str] = None, timeout: float = 8.0) -> bool:
        """Deactivate this device online to free up the seat."""
        if not self._lease:
            self.clear_local_lease()
            return True

        base_url = (server_url or self.get_server_url()).rstrip("/")
        endpoint = f"{base_url}/api/v1/license/deactivate"
        payload = {
            "license_key": self._lease.license_key,
            "device_id": self._lease.device_id,
        }

        try:
            requests.post(endpoint, json=payload, timeout=timeout)
        except requests.RequestException as exc:
            logger.warning("Could not contact server to deactivate seat online: %s", exc)

        # Clear local lease regardless
        self.clear_local_lease()
        return True


# Global singleton instance
_GLOBAL_LICENSE_MANAGER: Optional[LicenseManager] = None


def get_license_manager() -> LicenseManager:
    global _GLOBAL_LICENSE_MANAGER
    if _GLOBAL_LICENSE_MANAGER is None:
        _GLOBAL_LICENSE_MANAGER = LicenseManager()
    return _GLOBAL_LICENSE_MANAGER
