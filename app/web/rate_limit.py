"""Tiny in-process sliding-window rate limiter (no extra dependency).

Applied to the expensive API endpoints (upload, AI sync, render) via the
``enforce_rate_limit`` FastAPI dependency. Tuned through the environment
(read on every request, no restart needed):

- ``RATE_LIMIT_ENABLED`` (default ``"1"``; ``"0"`` disables)
- ``RATE_LIMIT_PER_MINUTE`` (default ``120``)
- ``RATE_LIMIT_WINDOW_SECONDS`` (default ``60``)

Counters live in process memory; behind multiple uvicorn workers each
worker enforces its own share. Deployments needing exact global limits
should terminate rate limiting at the edge (e.g. Traefik middlewares).
"""

import logging
import os
import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional

from fastapi import Depends, HTTPException, Request  # noqa: F401  (re-exported)

logger = logging.getLogger(__name__)

_hits: Dict[str, Deque[float]] = defaultdict(deque)
_lock = threading.Lock()


def _settings():
    enabled = os.environ.get("RATE_LIMIT_ENABLED", "1") != "0"
    try:
        limit = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "120"))
    except ValueError:
        limit = 120
    try:
        window = float(os.environ.get("RATE_LIMIT_WINDOW_SECONDS", "60"))
    except ValueError:
        window = 60.0
    return enabled, max(1, limit), max(1.0, window)


def reset() -> None:
    """Clears all counters (used by tests)."""
    with _lock:
        _hits.clear()


def check_rate_limit(key: str, now: Optional[float] = None) -> Optional[int]:
    """Registers a hit; returns None when allowed, else seconds until retry."""
    enabled, limit, window = _settings()
    if not enabled:
        return None
    moment = now if now is not None else time.monotonic()
    with _lock:
        hits = _hits[key]
        cutoff = moment - window
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if len(hits) >= limit:
            return max(1, int(hits[0] + window - moment) + 1)
        hits.append(moment)
        return None


def _client_ip(request: Request) -> str:
    if request.client:
        return request.client.host or "unknown"
    return "unknown"


async def enforce_rate_limit(request: Request) -> None:
    """FastAPI dependency rejecting over-limit clients with HTTP 429."""
    route = request.scope.get("route")
    route_path = getattr(route, "path", request.url.path)
    key = f"{_client_ip(request)}:{route_path}"
    retry_after = check_rate_limit(key)
    if retry_after is not None:
        logger.warning("Rate limit exceeded for %s", key)
        raise HTTPException(
            status_code=429,
            detail="Muitas requisições. Aguarde um instante e tente novamente.",
            headers={"Retry-After": str(retry_after)},
        )
