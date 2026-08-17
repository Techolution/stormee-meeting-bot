# Meeting bot runtime image.
#
# Two stages. The builder compiles wheels; the runtime carries only what is
# needed to run, which keeps the image smaller and removes the compilers from
# the deployed surface.
#
# The Chromium download is a deliberate layer of its own: it is the slowest and
# largest step, and isolating it means an application change rebuilds in seconds
# rather than re-downloading a browser.

# --------------------------------------------------------------------------
# Stage 1 — build wheels
# --------------------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .
RUN pip wheel --wheel-dir /wheels -r requirements.txt

# --------------------------------------------------------------------------
# Stage 2 — runtime
# --------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    APP_PORT=5000 \
    # Playwright's default location is under $HOME, which differs for the
    # non-root user; pin it so root installs a browser the app user can read.
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright

# ffmpeg is used for audio container conversion; the rest are Chromium's
# runtime libraries, installed by `playwright install --with-deps` below.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN pip install --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels requirements.txt

# Its own layer: slow, large, and unaffected by application changes.
RUN playwright install --with-deps chromium

WORKDIR /app

# Non-root. Chromium is given --no-sandbox because the kernel sandbox needs
# privileges a hardened pod does not grant; dropping root is what limits the
# blast radius of a browser compromise instead.
RUN useradd --create-home --uid 10001 bot \
    && mkdir -p /app /data/chrome_profile \
    && chown -R bot:bot /app /data

COPY --chown=bot:bot pyproject.toml README.md ./
COPY --chown=bot:bot app ./app

# Installed so `importlib.metadata` can report the real version on /health.
RUN pip install --no-deps -e . \
    && chown -R bot:bot /app

USER bot

EXPOSE 5000

# Liveness only — it must not depend on anything external. Readiness is checked
# by the orchestrator against /ready; see deploy/k8s/deployment.yaml.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://localhost:${APP_PORT}/api/meet/health" || exit 1

# One worker, deliberately: a worker owns a browser and a meeting, and a second
# would double the pod's memory while breaking the one-meeting-per-pod contract.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${APP_PORT} --workers 1 --no-access-log"]
