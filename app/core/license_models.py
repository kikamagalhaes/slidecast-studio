"""Data models, enums, and typed schemas for SlideCast Studio licensing."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class LicenseStatus(str, Enum):
    UNACTIVATED = "unactivated"
    ACTIVE = "active"
    PENDING = "pending"
    EXPIRED = "expired"
    LIMIT_REACHED = "limit_reached"
    REVOKED = "revoked"
    NO_CONNECTION = "no_connection"

    @property
    def label_pt(self) -> str:
        labels = {
            self.UNACTIVATED: "Não ativado",
            self.ACTIVE: "Ativo",
            self.PENDING: "Aguardando confirmação",
            self.EXPIRED: "Expirado",
            self.LIMIT_REACHED: "Limite de dispositivos atingido",
            self.REVOKED: "Revogado",
            self.NO_CONNECTION: "Modo offline (sem conexão)",
        }
        return labels.get(self, self.value)

    @property
    def badge_class(self) -> str:
        classes = {
            self.ACTIVE: "badge-success",
            self.NO_CONNECTION: "badge-neutral",
            self.PENDING: "badge-warning",
            self.UNACTIVATED: "badge-warning",
            self.LIMIT_REACHED: "badge-warning",
            self.EXPIRED: "badge-error",
            self.REVOKED: "badge-error",
        }
        return classes.get(self, "badge-neutral")


@dataclass
class LicenseLease:
    version: int
    license_id: str
    license_key: str
    user_id: Optional[int]
    user_email: Optional[str]
    device_id: str
    device_name: str
    status: str
    features: List[str]
    issued_at: str
    lease_expires_at: str
    signature: str = ""

    def payload_dict(self) -> Dict[str, Any]:
        """Dictionary used for canonical signing (excluding signature field)."""
        data = asdict(self)
        data.pop("signature", None)
        return data

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LicenseLease":
        return cls(
            version=int(data.get("version", 1)),
            license_id=str(data.get("license_id", "")),
            license_key=str(data.get("license_key", "")),
            user_id=data.get("user_id"),
            user_email=data.get("user_email"),
            device_id=str(data.get("device_id", "")),
            device_name=str(data.get("device_name", "")),
            status=str(data.get("status", "active")),
            features=list(data.get("features", ["all"])),
            issued_at=str(data.get("issued_at", "")),
            lease_expires_at=str(data.get("lease_expires_at", "")),
            signature=str(data.get("signature", "")),
        )


@dataclass
class ActivationResult:
    success: bool
    status: LicenseStatus
    message: str
    lease: Optional[LicenseLease] = None
    active_devices: List[Dict[str, Any]] = field(default_factory=list)
    seats_limit: int = 2
    error_code: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "status": self.status.value,
            "status_label": self.status.label_pt,
            "message": self.message,
            "lease": self.lease.to_dict() if self.lease else None,
            "active_devices": self.active_devices,
            "seats_limit": self.seats_limit,
            "error_code": self.error_code,
        }
