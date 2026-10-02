# CourseMate AI API

Minimal FastAPI backend for local CourseMate AI development.

## Database configuration

Copy the local environment template if `.env` does not exist:

```bash
cp .env.example .env
```

The configured `DATABASE_URL` uses the psycopg driver and the `ai_course`
database:

```text
postgresql+psycopg://coursemate:coursemate_dev@localhost:5432/ai_course
```

Start the local PostgreSQL database with Docker Compose:

```bash
docker compose up -d postgres
docker compose ps
```

Apply the database migrations before starting the API:

```bash
alembic upgrade head
```

The application creates its SQLAlchemy engine and sessions only when database access is requested. The current root and health endpoints therefore do not require a running database.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

On Windows PowerShell, activate the environment with:

```powershell
.\.venv\Scripts\Activate.ps1
```

The API runs at <http://localhost:8000>. Swagger documentation is available at <http://localhost:8000/docs>.

## Course API

| Method | Path                 | Description                                                    |
| ------ | -------------------- | -------------------------------------------------------------- |
| POST   | `/courses`           | Create a course (`name`); duplicates get a numeric suffix.     |
| GET    | `/courses`           | List courses.                                                  |
| GET    | `/courses/{id}`      | Course detail including documents and their processing status. |
| DELETE | `/courses/{id}`      | Delete a course (its documents are removed via cascade).       |
| POST   | `/courses/{id}/documents` | Upload one PDF (maximum 10 MiB).                         |

The response schemas are defined in `app/schemas/course.py`, and the routes
live in `app/routers/courses.py`.

## Tests

Run the API test suite from `services/api`:

```bash
pip install -r requirements-dev.txt
python -m pytest
```

The PDF processor uses one transaction to lock the Content, prepare text,
and replace its canonical chunks. Failed refreshes preserve existing ready
data. It must run in a dedicated database session; request-scoped sessions
must not be passed to background work. Upload does not automatically trigger
processing yet. See [the reliability engineering report](../../docs/VER2_PROCESSING_RELIABILITY.md)
for transaction boundaries, retry semantics, and the upload integration plan.

Four focused PostgreSQL checks are optional. They create and remove a unique
temporary schema per test, so the test account needs schema privileges. Use
a separate test database:

```bash
TEST_POSTGRES_URL='postgresql+psycopg://USER:PASSWORD@HOST:PORT/TEST_DB' \
  python -m pytest -q
```

Without `TEST_POSTGRES_URL`, these checks are explicitly skipped. SQLite tests
alone do not verify PostgreSQL row locking.

## Database migrations

Run Alembic commands from `services/api` with `DATABASE_URL` set:

```bash
alembic revision --autogenerate -m "describe schema change"
alembic upgrade head
```

The current models live in `app/models/`, and the schema revisions are under
`alembic/versions/`.
