.PHONY: install test lint check run-backend run-web

install:
	cd backend && pip install -e ".[dev]"
	cd apps/web && npm install

test:
	cd backend && python -m pytest -q

lint:
	cd backend && python -m ruff check app tests

check: lint test

run-backend:
	cd backend && uvicorn app.main:app --reload --port 8000

run-web:
	cd apps/web && npm run dev
