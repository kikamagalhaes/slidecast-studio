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
COPY requirements-web.txt .
RUN pip install --no-cache-dir -r requirements-web.txt

# Copy application files
COPY . .

# Create storage directory for uploaded files and outputs
RUN mkdir -p /app/storage

EXPOSE 8000

CMD ["uvicorn", "app.web.server:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
