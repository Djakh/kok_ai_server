# KOK.AI backend

FastAPI/PostgreSQL/PostGIS backend for the KOK.AI mobile app. The authoritative registration flow is:

`POST /api/v1/tree-analyses` → `GET /api/v1/trees/nearby` → `POST /api/v1/trees`

Kindwise Plant.id is called only by this backend. The API key, provider token, and raw provider response are never returned to mobile clients.

## Run locally

Docker is the supported full-stack path:

```bash
cp .env.example .env
# Put your Kindwise key in KOK_KINDWISE_API_KEY in .env.
docker compose up --build
```

Compose waits for PostgreSQL health, then `scripts/start-api.sh` runs migrations,
seed, and FastAPI in order. A migration or seed failure logs the failed stage and
exits nonzero; FastAPI starts only after both succeed. Uvicorn runs without reload
and replaces the shell so it receives container shutdown signals directly.
Use `docker compose up --build --wait` to wait for the API healthcheck and
`docker compose logs api` to inspect startup failures.

Then open:

- API: `http://localhost:8000`
- Swagger: `http://localhost:8000/docs`
- readiness: `http://localhost:8000/ready`
- MinIO console: `http://localhost:9001`

Run commands individually when dependencies are already available:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
alembic upgrade head
uvicorn app.main:app --reload
```

For a physical phone, use `http://<computer-LAN-IP>:8000`; Android Emulator uses `http://10.0.2.2:8000`.
Set `KOK_PUBLIC_API_BASE_URL` to that same reachable origin. In production it must be the public
HTTPS API origin (for example, `https://api.example.com`), because media URLs are built from it.

## Kindwise configuration

Required for live analysis:

```dotenv
KOK_KINDWISE_API_KEY=your-server-side-key
KOK_KINDWISE_BASE_URL=https://plant.id/api/v3
KOK_KINDWISE_HEALTH_MODE=off
```

`off` avoids optional health-credit use. Allowed health modes are `off`, `auto`, and `all`. Automated tests use fixtures and never make live Kindwise calls.

## Quality checks

`app/common/db/models.py` is the canonical ORM registry used by Alembic and runtime
sessions (including seed and Celery). Add new mapped classes there and keep model
definitions in `app/modules/<module>/models.py`, importing the shared Base from
`app.common.db.base`. Model modules must not import the session module or registry.
Fresh-process tests check registry completeness, shared metadata, and every foreign
key target without relying on API router imports.

```bash
.venv/bin/ruff check app tests
.venv/bin/mypy app
.venv/bin/pytest
alembic heads
```

Mobile developers should use the authoritative [mobile integration guide](docs/KOKAI_MOBILE_BACKEND_CONTRACT.md)
and the focused [create-tree and Kindwise workflow](docs/CREATE_TREE_KINDWISE_WORKFLOW.md).
The copy-ready mobile optimization task is in
[MOBILE_IMAGE_OPTIMIZATION_PROMPT.md](docs/MOBILE_IMAGE_OPTIMIZATION_PROMPT.md). Production Nginx
must include [kokai-upload-limits.conf](deploy/nginx/kokai-upload-limits.conf) inside the API
`server` block so proxy and application limits are aligned.
Backend implementation history remains in the [implementation report](docs/KOKAI_BACKEND_IMPLEMENTATION_REPORT.md)
and [execution plan](docs/KOKAI_BACKEND_EXECUTION_PLAN.md).
