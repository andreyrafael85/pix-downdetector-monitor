# ============================================================================
# PIX DownDetector Monitor — Dockerfile
# Multi-stage build for minimal production image
# ============================================================================

# ----------------------------------------------------------------------------
# Stage 1: Builder
# ----------------------------------------------------------------------------
FROM python:3.10-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ----------------------------------------------------------------------------
# Stage 2: Production
# ----------------------------------------------------------------------------
FROM python:3.10-slim AS production

LABEL maintainer="YOUR_ORG"
LABEL description="PIX DownDetector Monitor for O11y"
LABEL version="1.0.0"

# Create non-root user for security
RUN groupadd -r monitor && useradd -r -g monitor monitor

# Install Playwright system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxcb1 \
    libxkbcommon0 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Install Playwright browsers
RUN playwright install chromium && playwright install-deps chromium

# Copy source code
COPY src/ ./src/

# Create screenshot directory with correct permissions
RUN mkdir -p /tmp/downdetector && chown -R monitor:monitor /tmp/downdetector /app

# Switch to non-root user
USER monitor

# Health check: validate environment variables are set
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import os; assert os.getenv('AUTH') and os.getenv('DT_URL') and os.getenv('DT_API_TOKEN'), 'Missing env vars'" || exit 1

# Run the monitor
CMD ["python", "-m", "downdetector_monitor.monitor"]
