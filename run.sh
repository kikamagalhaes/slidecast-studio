#!/usr/bin/env bash
# Script para iniciar o SlideCast Studio no Linux

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

# Se o ambiente virtual existir, ativa-o
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Adiciona biblioteca libxcb-cursor local se existir
export LD_LIBRARY_PATH="$DIR/libs:${LD_LIBRARY_PATH:-}"

python3 main.py "$@"
