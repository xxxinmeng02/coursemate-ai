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

## Embedding configuration

Chunk vectors use pgvector `vector(1536)` and OpenAI `text-embedding-3-small`.
Configure `OPENAI_API_KEY`, `EMBEDDING_MODEL`, and `EMBEDDING_REVISION` in `.env`
or the process environment. Keys are never part of stored configuration IDs.
The provider boundary is `app/embeddings.py`; it requests 1536 dimensions and
validates finite, nonzero float32 values and safely normalizes them before
persistence or search. Existing non-unit vectors are normalized only in the SQL
expression, without writing to Chunk rows.

Each stored vector tracks `openai:{model}:1536:{revision}`. Search compares only
vectors from the query's configuration. `text-embedding-3-large` can also be
selected with an explicit 1536-dimensional output; changing models/revisions
requires re-embedding. Changing dimension requires another migration. Model
aliases are not immutable snapshots: bump the revision for incompatible provider
or input changes even if the alias stays the same. No automatic LLM generation
or PDF processing integration is introduced.

PostgreSQL must have pgvector 0.7.0 or later installed for `l2_normalize`.
Compose uses PostgreSQL 17 with pgvector;
the additive migration enables the extension (the migration role needs extension
privileges). Downgrade removes only the Chunk fields/constraint and retains the
shared extension. Existing SQLite tests use JSON only for persistence; they do
not substitute for PostgreSQL vector ranking tests.

## Generate embeddings

After migration and PDF processing, run from `services/api`:

```bash
python -m app.embedding_backfill
python -m app.embedding_backfill --content-id 123
python -m app.embedding_backfill --content-id 123 --force
```

The command processes ready Content once, regardless of how many Courses refer
to it. It skips valid embeddings for the current configuration. Use `--force`
for an explicit refresh; changing model/revision also replaces incompatible
vectors. Each Content uses a dedicated Session and one atomic transaction.
Provider/validation/persistence failures preserve all prior chunks and vectors;
the command reports counts and exits nonzero if any Content fails, while keeping
previously completed Contents. Retry safely after resolving the failure.

Generation uses the same Content write lock as PDF processing, held during the
bounded provider calls. Competing writers wait. Successful PDF refresh replaces
the canonical chunks and therefore requires another embedding backfill; failed
refreshes retain existing data. Upload does not automatically parse or embed.
Never pass a request Session or ORM object to future background work: create a
new Session and pass only Content IDs to `embed_content`.

## Course semantic search

```http
POST /courses/123/search
Content-Type: application/json

{"query": "What is parallel speedup?", "top_k": 5}
```

`top_k` defaults to `RETRIEVAL_DEFAULT_TOP_K` (5), with a valid range of 1–50.
Queries are trimmed, nonblank, and limited to 2000 characters. Missing Courses
return 404, invalid requests 422, and embedding failures a safe 503. Invalid
server defaults also return a safe 503 when used; explicit valid `top_k` bypasses
that default. Courses
without eligible embeddings return `{"results": []}` without a provider call.

Results contain `chunk_id`, `text`, `page_number`, `document_id`, `document_name`,
and `score` (cosine similarity = 1 − cosine distance, not a probability).
Search filters ready Content reached through the requested Course's Documents,
and only vectors matching the captured embedding configuration. Shared Content
is available from every referencing Course. Duplicate Course-local Documents
produce one canonical result, with the lowest Document ID's metadata. Sorting
uses exact pgvector cosine distance with Chunk ID ties, followed by `top_k`.
There is no approximate index in this foundation.

Internal consumers call `search_course(db, course_id, query, top_k)` in
`app/retrieval.py`; the caller owns the read-only Session. Routers only validate
and translate errors. SQL ranking is isolated from the embedding provider, and
neither module depends on PDF parsing. A future reranker/hybrid search belongs
inside retrieval; future answer generation consumes retrieval results.

## Retrieval evaluation and PostgreSQL verification

The three-topic fixture is `evals/retrieval/topics.json`: parallel programming,
TCP/networking, and accounting, each with a related natural-language query.
Deterministic tests use clearly labeled synthetic vectors and real pgvector to
verify ranking. Those tests establish database/query correctness, not embedding
model quality. No SQL similarity behavior is mocked.

For real model quality, configure `OPENAI_API_KEY` and an explicit separate test
database (the account needs schema and extension privileges):

```bash
TEST_POSTGRES_URL='postgresql+psycopg://USER:PASSWORD@HOST:PORT/TEST_DB' \
  python -m app.retrieval_eval
TEST_POSTGRES_URL='postgresql+psycopg://USER:PASSWORD@HOST:PORT/TEST_DB' \
  RUN_LIVE_EMBEDDING_EVAL=1 python -m pytest tests/test_retrieval_eval.py -q
```

The command uses real embeddings, seeds only a temporary schema, reports
expected/actual topics and scores, and removes that schema on success/failure.
Success requires finite scores and the expected topic strictly above unrelated
topics; ties do not count as semantic success.
It never seeds normal Course tables. A successful small fixture is a sanity
check; evaluate representative course queries and recall before adding answers.

```bash
python -m pytest -q
TEST_POSTGRES_URL='postgresql+psycopg://USER:PASSWORD@HOST:PORT/TEST_DB' python -m pytest -q
TEST_POSTGRES_URL='postgresql+psycopg://USER:PASSWORD@HOST:PORT/TEST_DB' \
  python -m pytest tests/test_retrieval_postgres.py tests/test_retrieval_migrations.py -q
alembic heads
```

The migration test creates pre-retrieval rows at the existing head, upgrades to
pgvector, checks preservation/type/extension, runs `alembic check`, and exercises
downgrade/re-upgrade. All PostgreSQL tests isolate their tables in random schemas.
Without a test URL they skip explicitly; live quality additionally requires the
opt-in flag and API key. See [the implementation report](../../docs/RAG_RETRIEVAL_FOUNDATION.md)
for exact results, maintainability review, and limitations.
