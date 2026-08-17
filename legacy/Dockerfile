# Use official Python runtime as a base image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=5000

# Set working directory
WORKDIR /app

# 1. Install system dependencies & FFmpeg for audio processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ffmpeg \
    xvfb \
    libffi-dev \
    libssl-dev \
    libportaudio2 \
    portaudio19-dev \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 2. Upgrade pip and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# 3. Install Playwright with official Google Chrome support + system dependencies
# Playwright automatically handles cross-platform binaries (ARM64 vs x86_64)
RUN playwright install chromium --with-deps

# 4. Copy application code
COPY . .

# 5. Expose application port
EXPOSE 5000

# 6. Run FastAPI server
CMD ["uvicorn", "main:socket_app", "--host", "0.0.0.0", "--port", "5000"]