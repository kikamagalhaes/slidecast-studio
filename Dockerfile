FROM python:3.12-slim

# Install system dependencies including FFmpeg
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libxcb-cursor0 \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install python dependencies (web-only, without desktop PySide6 GUI overhead)
COPY requirements-base.txt requirements-web.txt ./
RUN pip install --no-cache-dir -r requirements-web.txt

# Copy application files
COPY . .

# Create storage directory for uploaded files and outputs
RUN mkdir -p /app/storage

EXPOSE 8000

# Default: single worker (in-memory queue). Raise UVICORN_WORKERS only with
# QUEUE_BACKEND=redis; see entrypoint.sh and compose.production.yml.
RUN chmod +x /app/entrypoint.sh
CMD ["./entrypoint.sh"]
