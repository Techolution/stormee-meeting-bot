# ============ Builder Stage ============
FROM node:20-slim AS builder

WORKDIR /app

# Install only essential system deps for Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Copy package files
COPY package*.json ./

# Install ALL dependencies (including dev) for build
RUN npm install

# Install Playwright browsers (cached in this stage)
RUN npx playwright install --with-deps chromium

# Copy source
COPY . .

# ============ Pruner Stage (Optional but recommended) ============
FROM node:20-slim AS pruner
WORKDIR /app
COPY package*.json ./
RUN npm install --omit=dev && npm cache clean --force
# Keep only production node_modules

# ============ Final Stage ============
FROM node:20-slim

WORKDIR /app

# Install runtime system dependencies for Playwright + FFmpeg
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

# Copy node_modules (prod only) from pruner
COPY --from=pruner /app/node_modules ./node_modules

# Copy built app and Playwright deps from builder
COPY --from=builder /app /app

# Copy Playwright system deps and browsers (critical!)
COPY --from=builder /root/.cache/ms-playwright /root/.cache/ms-playwright

# Copy Playwright browsers for node user
COPY --from=builder /root/.cache/ms-playwright /home/node/.cache/ms-playwright

# Fix permissions
RUN chown -R node:node /app /home/node/.cache

# Expose port
EXPOSE 80

# Use non-root user (security)
USER node

# Start app
CMD ["npm", "start"]
