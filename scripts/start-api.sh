#!/bin/sh
set -eu

stage="migrations"
trap 'status=$?; if [ "$status" -ne 0 ]; then echo "API startup failed during $stage (exit $status)" >&2; fi' EXIT

echo "API startup: applying migrations"
alembic upgrade head
stage="seed"
echo "API startup: seeding database"
python -m scripts.seed
stage="FastAPI launch"
echo "API startup: migrations and seed complete; starting FastAPI"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-access-log
