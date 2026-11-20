"""FastAPI router for SlideCast Desktop licensing and activation."""

from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.core.license_models import LicenseStatus
from app.web import auth as auth_module
from app.web import desktop_licensing
from app.web import stripe_billing

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/license", tags=["desktop-license"])


def _public_site_url() -> str:
    """Return canonical public base URL respecting PUBLIC_SITE_URL."""
    override = os.environ.get("PUBLIC_SITE_URL", "").strip()
    if override:
        return override.rstrip("/")
    domain = os.environ.get("APP_DOMAIN", "localhost:8000").strip()
    scheme = "http" if domain.startswith("localhost") else "https"
    return f"{scheme}://{domain}/slidecast" if "kikamagalhaes.com.br" in domain else f"{scheme}://{domain}"


class ActivateRequest(BaseModel):
    license_key: str = Field(..., description="Chave da licença (formato SCST-XXXX-XXXX-XXXX-XXXX)")
    device_id: str = Field(..., description="Identificador anônimo estável do dispositivo")
    device_name: str = Field(..., description="Nome amigável do dispositivo")
    platform: str = Field(default="linux", description="Sistema operacional: windows, linux ou macos")
    app_version: str = Field(default="1.2.0", description="Versão do SlideCast Studio instalado")


class ValidateRequest(BaseModel):
    license_key: str = Field(..., description="Chave da licença")
    device_id: str = Field(..., description="Identificador anônimo do dispositivo")


class DeactivateRequest(BaseModel):
    license_key: str = Field(..., description="Chave da licença ou ID")
    device_id: str = Field(..., description="Identificador anônimo do dispositivo")


class CheckoutRequest(BaseModel):
    plan_type: str = Field(default="standard", description="Identificador do plano desktop")


@router.get("/plans")
async def list_desktop_plans():
    """List commercial desktop license plans or report pending configuration."""
    desktop_price_id = os.environ.get("SLIDECAST_DESKTOP_PRICE_ID", "").strip()
    desktop_price_amount = os.environ.get("SLIDECAST_DESKTOP_PRICE_AMOUNT", "").strip()
    desktop_currency = os.environ.get("SLIDECAST_DESKTOP_PRICE_CURRENCY", "BRL").strip().upper()

    if not desktop_price_id:
        return {
            "available": False,
            "message": "Ofertas comerciais em definição pela proprietária. Vendas de produção desativadas.",
            "plans": [],
        }

    return {
        "available": True,
        "plans": [
            {
                "id": "standard",
                "name": "SlideCast Studio Desktop — Licença Padrão",
                "price_id": desktop_price_id,
                "amount": int(desktop_price_amount) if desktop_price_amount.isdigit() else 0,
                "currency": desktop_currency,
                "seats_limit": int(os.environ.get("SLIDECAST_DESKTOP_SEATS_LIMIT", "2")),
                "features": ["Exportação local ilimitada", "Gravação em tela dupla", "Editor 4 faixas"],
            }
        ],
    }


@router.post("/checkout")
async def create_desktop_checkout(
    body: CheckoutRequest,
    user: dict = Depends(auth_module.current_user),
):
    """Create a Stripe Checkout session for a desktop license."""
    stripe_key = os.environ.get("STRIPE_SECRET_KEY", "").strip()
    price_id = os.environ.get("SLIDECAST_DESKTOP_PRICE_ID", "").strip()

    if not stripe_key or not price_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Venda de licença desktop ainda não configurada comercialmente.",
        )

    base = _public_site_url()
    success_url = f"{base}/?checkout=sucesso&session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{base}/?checkout=cancelado"

    client = stripe_billing._get_client()
    try:
        session = client.v1.checkout.sessions.create(
            {
                "mode": os.environ.get("SLIDECAST_DESKTOP_CHECKOUT_MODE", "payment"),
                "client_reference_id": str(user["id"]),
                "customer_email": user.get("email"),
                "line_items": [{"price": price_id, "quantity": 1}],
                "success_url": success_url,
                "cancel_url": cancel_url,
                "metadata": {
                    "type": "desktop_license",
                    "user_id": str(user["id"]),
                    "plan_type": body.plan_type,
                    "seats_limit": os.environ.get("SLIDECAST_DESKTOP_SEATS_LIMIT", "2"),
                },
            }
        )
        return {"checkout_url": session["url"]}
    except Exception as exc:
        logger.error("Failed to create Stripe checkout session: %s", exc)
        raise HTTPException(status_code=502, detail=f"Erro no provedor de pagamento: {exc}")


@router.get("/status")
async def get_user_licenses_status(user: dict = Depends(auth_module.current_user)):
    """Return all licenses and active devices belonging to the authenticated user."""
    licenses = desktop_licensing.list_user_licenses(user["id"])
    return {
        "user_id": user["id"],
        "email": user["email"],
        "licenses_count": len(licenses),
        "licenses": licenses,
    }


@router.post("/activate")
async def activate_license(
    req: ActivateRequest,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    """Activate license on this device under atomic seat limits."""
    user_id = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1].strip()
        auth_user = auth_module.user_from_token(token)
        if auth_user:
            user_id = auth_user["id"]

    client_ip = request.client.host if request.client else None
    result = desktop_licensing.activate_device(
        license_key=req.license_key,
        device_id=req.device_id,
        device_name=req.device_name,
        platform=req.platform,
        app_version=req.app_version,
        user_id=user_id,
        ip_address=client_ip,
    )

    if not result.success:
        if result.status == LicenseStatus.LIMIT_REACHED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=result.to_dict(),
            )
        if result.error_code == "FORBIDDEN_LICENSE_OWNER":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=result.to_dict(),
            )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND if result.error_code == "LICENSE_NOT_FOUND" else status.HTTP_400_BAD_REQUEST,
            detail=result.to_dict(),
        )

    return result.to_dict()


@router.post("/validate")
async def validate_license(req: ValidateRequest, request: Request):
    """Validate activation status and refresh signed lease."""
    client_ip = request.client.host if request.client else None
    result = desktop_licensing.validate_device(
        license_key=req.license_key,
        device_id=req.device_id,
        ip_address=client_ip,
    )

    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=result.to_dict(),
        )

    return result.to_dict()


@router.post("/deactivate")
async def deactivate_license(
    req: DeactivateRequest,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    """Deactivate device to release seat."""
    user_id = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1].strip()
        auth_user = auth_module.user_from_token(token)
        if auth_user:
            user_id = auth_user["id"]

    client_ip = request.client.host if request.client else None
    success = desktop_licensing.deactivate_device(
        license_key_or_id=req.license_key,
        device_id=req.device_id,
        user_id=user_id,
        ip_address=client_ip,
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"success": False, "message": "Ativação não encontrada ou não pertence ao usuário."},
        )

    return {"success": True, "message": "Dispositivo desativado com sucesso. O assento foi liberado."}
