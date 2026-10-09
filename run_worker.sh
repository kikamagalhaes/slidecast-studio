#!/usr/bin/env bash
# Local render worker for QUEUE_BACKEND=redis (needs a reachable Redis).
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

export PYTHONPATH="$DIR:${PYTHONPATH:-}"

echo "SlideCast render worker (queue: slidecast)..."
exec rq worker --url "${REDIS_URL:-redis://localhost:6379/0}" slidecast
