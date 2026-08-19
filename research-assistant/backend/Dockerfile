# Multi-stage Dockerfile for FastAPI + AI Agent Backend
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Install system dependencies (Tesseract OCR, build essentials, libpq)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    libpq-dev \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy and install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Expose port
EXPOSE 8000

# Run uvicorn.
# --proxy-headers makes uvicorn rewrite the client address from the
# X-Forwarded-For nginx sets. Without it every request behind the reverse
# proxy reports the nginx container's IP, so the IP-based rate limits
# (GlobalIPRateLimitMiddleware, and slowapi's unauthenticated fallback)
# collapse into a single bucket shared by the entire user base.
# Trusting the header is only safe because the backend port is not publicly
# reachable — see the loopback port binding in docker-compose.yml.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
