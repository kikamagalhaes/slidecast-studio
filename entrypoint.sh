#!/usr/bin/env sh
# Uvicorn entrypoint: workers and trusted-proxy flags come from the environment.
# - UVICORN_WORKERS (default 1; raise only with QUEUE_BACKEND=redis)
# - PROXY_HEADERS=1 when running behind Traefik/Nginx (fixes client IPs)
# - FORWARDED_ALLOW_IPS (default '*'; restrict when exposed directly)
set -e

WORKERS="${UVICORN_WORKERS:-1}"
ARGS="app.web.server:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WORKERS}"

if [ "${PROXY_HEADERS:-0}" = "1" ]; then
  # shellcheck disable=SC2086
  ARGS="${ARGS} --proxy-headers --forwarded-allow-ips ${FORWARDED_ALLOW_IPS:-*}"
fi

# shellcheck disable=SC2086
exec uvicorn $ARGS
