.PHONY: install run test lint format

install:
	python -m pip install -r requirements.txt

run:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

test:
	pytest -q

lint:
	python -m compileall app

format:
	python -m compileall app
