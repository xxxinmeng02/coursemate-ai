# CourseMate AI API

Minimal FastAPI backend for local CourseMate AI development.

## Database configuration

Copy the local environment template if `.env` does not exist:

```bash
cp .env.example .env
```

The configured `DATABASE_URL` uses the psycopg driver:

```text
postgresql+psycopg://coursemate:coursemate_dev@localhost:5432/coursemate
```

Start the local PostgreSQL database with Docker Compose:

```bash
docker compose up -d postgres
docker compose ps
```

The application creates its SQLAlchemy engine and sessions only when database access is requested. The current root and health endpoints therefore do not require a running database.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

The API runs at <http://localhost:8000>. Swagger documentation is available at <http://localhost:8000/docs>.

## Database migrations

Run Alembic commands from `services/api` with `DATABASE_URL` set:

```bash
alembic revision --autogenerate -m "describe schema change"
alembic upgrade head
```

No application models or schema revisions are included yet.
