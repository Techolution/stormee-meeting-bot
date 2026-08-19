# Targets run against whatever Python is active. The project's environment is
# the "meeting-bot" conda env (Python 3.12), shared with the bot worker:
#
#   conda activate meeting-bot
#
# Override for a one-off without activating:
#   make test PYTHON=/path/to/python

PYTHON ?= python
UVICORN = $(PYTHON) -m uvicorn

.PHONY: install run run-local test lint deploy pods

install:
	$(PYTHON) -m pip install -r requirements.txt

run:
	$(UVICORN) app.main:app --reload --host 0.0.0.0 --port 8000

test:
	$(PYTHON) -m pytest -q

lint:
	$(PYTHON) -m compileall -q app

# Run against a bot pod outside the cluster:
#   kubectl port-forward pod/<bot-pod> 5000:5000
#   make run-local
run-local:
	KUBERNETES_ENABLED=false BOT_SERVICE_URL=$${BOT_SERVICE_URL:-http://localhost:5000} \
		$(UVICORN) app.main:app --reload --host 0.0.0.0 --port 8000

deploy:
	kubectl apply -f deploy/k8s/serviceaccount.yaml
	kubectl apply -f deploy/k8s/rbac.yaml
	kubectl apply -f deploy/k8s/configmap.yaml
	kubectl apply -f deploy/k8s/deployment.yaml
	kubectl apply -f deploy/k8s/service.yaml

# What the handler can see in the cluster. First thing to check when a
# dispatch returns no_bot_pod_available.
pods:
	kubectl exec deploy/meeting-bot-handler -- \
		$(PYTHON) -c "import urllib.request,sys; sys.stdout.write(urllib.request.urlopen('http://localhost:8000/bot-pods').read().decode())"
