# Meeting bot — development tasks.
#
# `make check` is what CI runs and what should pass before a push.

.DEFAULT_GOAL := help
SHELL := /bin/bash

PYTHON      ?= python3
VENV        ?= .venv
BIN         := $(VENV)/bin
IMAGE       ?= meeting-bot
TAG         ?= local
CONTAINER   ?= meeting-bot

.PHONY: help
help: ## Show available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# --------------------------------------------------------------------------
# Setup
# --------------------------------------------------------------------------

.PHONY: install
install: $(VENV) ## Install dependencies and the Chromium build Playwright expects
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -e ".[dev]"
	$(BIN)/playwright install --with-deps chromium

$(VENV):
	$(PYTHON) -m venv $(VENV)

.PHONY: lock
lock: ## Refresh requirements.txt from the current environment
	@echo "Review the result before committing: this captures what is installed,"
	@echo "including anything added ad hoc."
	$(BIN)/pip freeze --exclude-editable > requirements.lock.txt
	@echo "Written to requirements.lock.txt — merge into requirements.txt deliberately."

# --------------------------------------------------------------------------
# Quality gates
# --------------------------------------------------------------------------

.PHONY: check
check: lint typecheck test ## Everything CI runs

.PHONY: lint
lint: ## Static analysis
	$(BIN)/ruff check app tests scripts

.PHONY: format
format: ## Apply safe autofixes and formatting
	$(BIN)/ruff check app tests scripts --fix
	$(BIN)/ruff format app tests scripts

.PHONY: typecheck
typecheck: ## Type checking
	$(BIN)/mypy

.PHONY: test
test: ## Full test suite
	$(BIN)/pytest

.PHONY: test-unit
test-unit: ## Unit tests only
	$(BIN)/pytest tests/unit

.PHONY: coverage
coverage: ## Test suite with a coverage report
	$(BIN)/pytest --cov=app --cov-report=term-missing --cov-report=html
	@echo "HTML report: htmlcov/index.html"

# --------------------------------------------------------------------------
# Running
# --------------------------------------------------------------------------

.PHONY: run
run: ## Run locally with reload
	$(BIN)/uvicorn app.main:app --host 0.0.0.0 --port $${APP_PORT:-5000} --reload

.PHONY: run-headful
run-headful: ## Run with a visible browser, for debugging a join
	BROWSER_HEADLESS=false $(BIN)/uvicorn app.main:app --port $${APP_PORT:-5000} --reload

# --------------------------------------------------------------------------
# Docker
# --------------------------------------------------------------------------

.PHONY: docker-build
docker-build: ## Build the image
	docker build -t $(IMAGE):$(TAG) .

.PHONY: docker-run
docker-run: docker-build ## Run the image with .env and a persisted browser profile
	docker rm -f $(CONTAINER) 2>/dev/null || true
	docker run --rm -it \
		--name $(CONTAINER) \
		--ipc=host \
		-p $${APP_PORT:-5000}:5000 \
		--env-file .env \
		-v "$(PWD)/chrome_profile:/data/chrome_profile" \
		$(IMAGE):$(TAG)

.PHONY: docker-shell
docker-shell: ## Open a shell in the image
	docker run --rm -it --entrypoint bash $(IMAGE):$(TAG)

CPU_LIMIT    ?= 0.4
MEMORY_LIMIT ?= 1g

.PHONY: docker-run-low
docker-run-low: docker-build ## Run with low CPU and memory limits
	docker rm -f $(CONTAINER) 2>/dev/null || true
	docker run --rm -it \
		--name $(CONTAINER) \
		--ipc=host \
		--cpus=$(CPU_LIMIT) \
		--memory=$(MEMORY_LIMIT) \
		--memory-swap=$(MEMORY_LIMIT) \
		-p $${APP_PORT:-5000}:5000 \
		--env-file .env \
		-v "$(PWD)/chrome_profile:/data/chrome_profile" \
		$(IMAGE):$(TAG)

# --------------------------------------------------------------------------
# Utilities
# --------------------------------------------------------------------------

.PHONY: auth-profile
auth-profile: ## Sign in to Google once and persist the browser profile
	$(BIN)/python scripts/create_auth_profile.py

.PHONY: auth-profile-docker
auth-profile-docker: ## Sign in to Google using Docker and persist the browser profile
	$(SHELL) scripts/create_auth_profile_docker.sh

.PHONY: test-gcs-profile
test-gcs-profile: ## Test Chrome profile download from GCS locally
	@if [ -z "$GCS_BUCKET" ] || [ -z "$GCS_OBJECT_PATH" ]; then \
		echo "Error: GCS_BUCKET and GCS_OBJECT_PATH environment variables are required"; \
		echo ""; \
		echo "Usage:"; \
		echo "  export GCS_BUCKET=\"meeting-bot\""; \
		echo "  export GCS_OBJECT_PATH=\"profiles/chrome_profile.tar.gz\""; \
		echo "  make test-gcs-profile"; \
		echo ""; \
		echo "First, ensure you are authenticated: gcloud auth application-default login"; \
		exit 1; \
	fi
	@$(SHELL) scripts/test_gcs_profile_download.sh

.PHONY: test-gcs-profile-docker
test-gcs-profile-docker: ## Test Chrome profile download from GCS using Docker (no local gcloud needed)
	@if [ -z "$GCS_BUCKET" ] || [ -z "$GCS_OBJECT_PATH" ]; then \
		echo "Error: GCS_BUCKET and GCS_OBJECT_PATH environment variables are required"; \
		echo ""; \
		echo "Usage:"; \
		echo "  export GCS_BUCKET=\"meeting-bot\""; \
		echo "  export GCS_OBJECT_PATH=\"profiles/chrome_profile.tar.gz\""; \
		echo "  make test-gcs-profile-docker"; \
		echo ""; \
		echo "First, ensure you are authenticated: gcloud auth application-default login"; \
		exit 1; \
	fi
	@$(SHELL) scripts/test_gcs_profile_download_docker.sh

.PHONY: clean
clean: ## Remove build and test artefacts
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage build dist *.egg-info
