# CourseMate AI API

Minimal FastAPI backend for local CourseMate AI development.

## Database configuration

Set `DATABASE_URL` to a PostgreSQL connection URL that uses the psycopg driver:

```bash
export DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5432/coursemate"
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
