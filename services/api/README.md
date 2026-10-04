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
| POST   | `/courses/{id}/documents` | Commit upload then schedule PDF processing (maximum 10 MiB). |
| POST   | `/courses/{id}/documents/{document_id}/retry` | 202 for uploaded/failed; 200 unchanged ready/processing; 404 wrong course; 409 pending cleanup. |
| DELETE | `/courses/{id}/documents/{document_id}` | 204; detach one document and clean only newly unreferenced Content. |

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
must not be passed to background work. Upload commits before automatically scheduling `content_id` in FastAPI BackgroundTasks.
The job reloads state under a lock using its own session and only automatically
processes `uploaded`. Failed Content requires explicit Retry; shared ready
Content skips processing. Scheduling or processing failure cannot undo the
committed upload. BackgroundTasks are non-durable: restart/crash can lose work;
Retry recovers uploaded/failed rows. Historical processing rows are left alone.

The final document/course reference deletion commits `pending_cleanup` before
an idempotent cleanup job unlinks the hash file and deletes Content/chunks.
Failure retains hash metadata for recovery (the file may already be absent
if final cleanup commit failed). `python -m app.cleanup` retries pending rows.
This is a committed-intent protocol across DB/filesystem, not one ACID transaction.
`COURSEMATE_STORAGE_DIR` overrides the default local storage path.
See [the V1.1 report](../../docs/V11_DOCUMENT_PROCESSING_REPORT.md).

Ten focused PostgreSQL checks are optional, including the real Alembic upgrade chain. They create and remove a unique
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
