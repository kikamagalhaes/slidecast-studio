#!/usr/bin/env bash
# Script para iniciar o SlideCast Studio em modo Web (FastAPI)

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

export LD_LIBRARY_PATH="$DIR/libs:${LD_LIBRARY_PATH:-}"

echo "======================================================"
echo "🎬 SlideCast Studio Web Server iniciando..."
echo "Acesse no navegador: http://localhost:8000"
echo "======================================================"

uvicorn app.web.server:app --host 0.0.0.0 --port 8000 --reload
