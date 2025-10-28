docker stop meet-bot-python-container || true
docker rm meet-bot-python-container || true
docker build -t meet-bot-python-image .
docker run -d -p 5000:5000 --name meet-bot-python-container meet-bot-python-image