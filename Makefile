.PHONY: install up down logs test lint migrate seed

install:
	python3.12 -m venv .venv
	. .venv/bin/activate && pip install --upgrade pip && pip install -e .[dev]

up:
	docker compose up --build

down:
	docker compose down -v

logs:
	docker compose logs -f api celery_worker

migrate:
	alembic upgrade head

seed:
	python scripts/seed.py

lint:
	ruff check .

test:
	pytest
