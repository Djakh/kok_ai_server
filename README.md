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

## Kindwise configuration

Required for live analysis:

```dotenv
KOK_KINDWISE_API_KEY=your-server-side-key
KOK_KINDWISE_BASE_URL=https://plant.id/api/v3
KOK_KINDWISE_HEALTH_MODE=off
```

`off` avoids optional health-credit use. Allowed health modes are `off`, `auto`, and `all`. Automated tests use fixtures and never make live Kindwise calls.

## Quality checks

```bash
.venv/bin/ruff check app tests
.venv/bin/mypy app
.venv/bin/pytest
alembic heads
```

Mobile developers should use the authoritative [mobile integration guide](docs/KOKAI_MOBILE_BACKEND_CONTRACT.md).
Backend implementation history remains in the [implementation report](docs/KOKAI_BACKEND_IMPLEMENTATION_REPORT.md)
and [execution plan](docs/KOKAI_BACKEND_EXECUTION_PLAN.md).
