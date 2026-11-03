# syntax=docker/dockerfile:1
# Stage 1: build do frontend (Node só existe aqui; nunca entra no runtime)
FROM node:20-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
ARG VITE_BASE=/
# vite.config.ts escreve em ../app/web/static/studio relativo ao frontend/
RUN mkdir -p /app/web/static/studio && npm run build

# Stage 2: runtime Python (sem Node, sem PySide6, sem SDKs de IA)
FROM python:3.12-slim AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements-base.txt requirements-web.txt ./
RUN pip install --no-cache-dir -r requirements-web.txt
COPY app/ ./app/
COPY entrypoint.sh run_worker.sh ./
COPY --from=frontend /app/web/static/studio ./app/web/static/studio
RUN mkdir -p /app/storage && chmod +x /app/entrypoint.sh
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"
CMD ["./entrypoint.sh"]
