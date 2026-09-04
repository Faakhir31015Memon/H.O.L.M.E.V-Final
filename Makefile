.PHONY: install test run-backend run-web check

install:
	cd backend && pip install -r pyproject.toml
	cd apps/web && npm install

test:
	cd backend && python -m pytest tests

run-backend:
	cd backend && uvicorn app.main:app --reload --port 8000

run-web:
	cd apps/web && npm run dev

check:
	cd backend && python -m pytest tests
