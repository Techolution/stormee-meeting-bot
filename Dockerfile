# ──────────────────────────────────────────────────────────────
# 1. BUILDER – install *all* npm deps + download Playwright browsers
# ──────────────────────────────────────────────────────────────
FROM node:20-slim AS builder

WORKDIR /app

# ---- System deps needed only to *download* Playwright ----
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates wget \
    && rm -rf /var/lib/apt/lists/*

# ---- npm cache (persisted across builds) ----
COPY package*.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci --verbose

# ---- Install Playwright + browsers (cached in /root/.cache) ----
RUN --mount=type=cache,target=/root/.cache \
    npx playwright install --with-deps chromium

# ---- Copy source (last, so it invalidates cache only when code changes) ----
COPY . .

# ──────────────────────────────────────────────────────────────
# 2. PRUNER – keep only production node_modules
# ──────────────────────────────────────────────────────────────
FROM node:20-slim AS pruner

WORKDIR /app
COPY package*.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci --omit=dev && npm cache clean --force

# ──────────────────────────────────────────────────────────────
# 3. FINAL – runtime image (tiny + all Playwright runtime deps)
# ──────────────────────────────────────────────────────────────
FROM node:20-slim

WORKDIR /app

# ---- Runtime system deps (Playwright + FFmpeg) ----
RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg \
      ca-certificates \
      fonts-liberation \
      libasound2 \
      libatk-bridge2.0-0 \
      libatk1.0-0 \
      libcups2 \
      libdbus-1-3 \
      libdrm2 \
      libgbm1 \
      libglib2.0-0 \
      libnspr4 \
      libnss3 \
      libx11-6 \
      libxcomposite1 \
      libxdamage1 \
      libxext6 \
      libxfixes3 \
      libxrandr2 \
    && rm -rf /var/lib/apt/lists/*

# ---- Production node_modules (from pruner) ----
COPY --from=pruner /app/node_modules ./node_modules

# ---- Application code + Playwright system libs (from builder) ----
COPY --from=builder /app .

# ---- Playwright browsers (the *only* thing that must survive) ----
COPY --from=builder /root/.cache/ms-playwright /root/.cache/ms-playwright

EXPOSE 80
USER node
CMD ["npm", "start"]