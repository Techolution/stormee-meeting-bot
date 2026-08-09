
# . .env
# . venv/bin/activate
# python3 main.py

# docker stop meet-bot-python-container || true
# docker rm meet-bot-python-container || true
# docker build -t meet-bot-python-image .
# docker run -p 5000:5000 --ipc=host -v "$(pwd)/chrome_profile:/app/chrome_profile" --name meet-bot-python-container meet-bot-python-image

# !/bin/bash

# Stop and remove existing container
# docker stop meet-bot-python-container || true
# docker rm meet-bot-python-container || true

# # Rebuild image
# docker build -t meet-bot-python-image .

# # Get Mac IP address
# MAC_IP=$(ipconfig getifaddr en0 || ipconfig getifaddr en1)
# xhost + $MAC_IP > /dev/null 2>&1

# # Run container with display forwarding
# docker run -p 5000:5000 \
#   --ipc=host \
#   -e DISPLAY=$MAC_IP:0 \
#   -e HEADLESS=false \
#   -v "$(pwd)/chrome_profile:/app/chrome_profile" \
#   --name meet-bot-python-container \
#   meet-bot-python-image

#!/bin/bash

CONTAINER_NAME="meet-bot-python-container"
IMAGE_NAME="meet-bot-python-image"

# 1. Force stop and remove existing container if it exists
echo "🧹 Cleaning up existing container..."
docker stop $CONTAINER_NAME 2>/dev/null || true
docker rm -f $CONTAINER_NAME 2>/dev/null || true

# 2. Build docker image
echo "🔨 Building Docker image..."
docker build -t $IMAGE_NAME .

# 3. Run container in HEADLESS mode
echo "🚀 Starting container in headless mode..."
docker run -p 5000:5000 \
  --ipc=host \
  -e HEADLESS=true \
  -v "$(pwd)/chrome_profile:/app/chrome_profile" \
  --name $CONTAINER_NAME \
  $IMAGE_NAME