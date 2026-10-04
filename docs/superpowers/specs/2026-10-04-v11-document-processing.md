# CourseMate-AI V1.1 Milestone
## End-to-End Document Processing

Work from the latest `ver2` branch.

The repository currently has a reliable PDF processing core with:

- Course CRUD
- PDF upload
- SHA-256 Content deduplication
- shared `Document` / `Content` model
- PDF text extraction
- page-local chunking
- atomic chunk replacement
- failed-refresh preservation
- serialized Content processing
- PostgreSQL concurrency tests
- approximately 46 backend tests when optional PostgreSQL tests are enabled

The next goal is to turn these isolated capabilities into a complete **V1.1 document-processing workflow**.

The finished user flow should be:

```text
User opens Course
    ↓
Uploads PDF
    ↓
Document appears immediately
    ↓
Backend automatically schedules processing
    ↓
PDF is parsed in a dedicated DB session
    ↓
Chunks are stored
    ↓
Frontend refreshes status
    ↓
Document becomes ready
```

Failure flow:

```text
Upload succeeds
    ↓
Processing fails
    ↓
Document remains recorded
    ↓
Frontend shows failed
    ↓
User can retry processing
```

Also complete the basic Document lifecycle:

```text
Document can be deleted
    ↓
Shared Content is preserved if still referenced
    ↓
Unreferenced Content/file cleanup behaviour is explicit and safe
```

Do NOT implement:

- embeddings
- vector search
- RAG
- LLM chat
- OCR
- authentication
- Redis
- Celery
- Dramatiq
- distributed queues
- major frontend redesign
- framework migrations

This task should complete the **document ingestion layer**, not the AI layer.

---

# Branch discipline

Do not work directly on `main`.

Create and work on a dedicated branch from the current `ver2`, for example:

```text
feature/v1.1-document-processing
```

Do not merge automatically.

Use logical commits.

Before changing anything, verify the current branch and baseline commit.

---

# Phase 1 — Repository inspection

Before modifying code, reconstruct the current document lifecycle.

Inspect at minimum:

- Course model
- Document model
- Content model
- Chunk model
- SQLAlchemy relationships
- cascade configuration
- Alembic migrations
- document upload router
- course detail router/schema
- `process_content`
- DB session factory
- storage helpers
- current frontend Course detail page
- API client helpers
- parsing tests
- upload tests
- PostgreSQL processing tests

Trace the current flow:

```text
browser
→ upload request
→ temporary file
→ SHA-256
→ storage
→ Content
→ Document
→ commit
→ response
```

Then trace separately:

```text
process_content
→ locking
→ parsing
→ chunk replacement
→ status
```

Identify exactly where these flows should connect.

Run the current baseline before modification.

Backend:

```bash
cd services/api
python -m pytest -q
```

If `TEST_POSTGRES_URL` is available, also run PostgreSQL integration tests.

Frontend:

```bash
cd apps/web
npm run lint
npm run build
```

Record the baseline results.

---

# Phase 2 — Define Content processing state semantics

Preserve the current status vocabulary unless there is a compelling reason not to:

```text
uploaded
processing
ready
failed
pending_cleanup
```

Before implementation, document the intended semantics of every status.

Important:

The current `process_content()` transaction keeps `processing` transaction-local, so readers may observe:

```text
uploaded → ready
```

instead of:

```text
uploaded → processing → ready
```

Do not weaken transaction safety solely to make `processing` visible.

If you decide to expose a public processing state, first prove that the change does not reintroduce:

- stale task corruption
- failed-refresh data loss
- abandoned permanent processing rows

Prefer correctness over cosmetic progress reporting.

---

# Phase 3 — Automatic processing after upload

Integrate document upload with automatic PDF processing.

Processing must only be scheduled **after the upload database transaction commits successfully**.

Never start processing before:

- Content is persisted
- Document is persisted
- file storage is complete
- upload transaction commits

Background processing must receive only:

```text
content_id
```

Do not pass:

- request-scoped SQLAlchemy Session
- ORM Content instance
- request object

The worker must:

```text
receive content_id
→ create dedicated Session
→ reload Content
→ inspect current state
→ decide whether processing is needed
→ call process_content
→ handle error
→ close Session
```

Every Session must be closed reliably.

Processing failures must be logged.

A later processing failure must NOT retroactively turn a successful upload HTTP response into a failed upload.

---

# Phase 4 — Background execution mechanism

For this local prototype, implement the smallest sensible mechanism.

FastAPI `BackgroundTasks` is acceptable if appropriate.

Do not add Redis or an external worker framework.

However, structure the code so that processing execution is separated from scheduling.

Prefer something conceptually like:

```text
schedule_content_processing(content_id)

process_content_job(content_id)
```

rather than embedding all logic directly inside the HTTP route.

This separation should make it possible to replace the in-process runner with a durable queue later without rewriting the actual processing logic.

Document explicitly:

> In-process background tasks are not durable. Work may be lost if the API process crashes or restarts after the upload commit but before/during processing.

Do not pretend this limitation has been solved.

---

# Phase 5 — State-aware scheduling

Avoid unnecessary work.

The background worker must reload current Content state using a fresh Session.

Define behaviour for:

## uploaded

Eligible for automatic first processing.

## ready

Automatic upload reuse should NOT reprocess it.

If an identical PDF is uploaded into another Course and the shared Content is already ready:

```text
reuse Content
reuse existing chunks
new Document immediately observes ready
```

## processing

Do not launch another automatic processing attempt.

Do not blindly reset historical processing records.

## failed

Do not create an infinite automatic retry loop.

Failed processing should require an explicit retry action.

## pending_cleanup

Do not process until lifecycle cleanup semantics are resolved.

The final authoritative state check must happen inside the background worker, not only inside the upload request.

---

# Phase 6 — Manual retry API

Implement an explicit processing retry endpoint for failed Content through the Document-facing API.

Choose a clear REST shape consistent with the current codebase.

For example:

```text
POST /courses/{course_id}/documents/{document_id}/retry
```

or another justified equivalent.

Required behaviour:

### failed

Accept retry and schedule processing.

### uploaded

May schedule processing if not already scheduled.

### ready

Do not perform unnecessary processing.

Return a sensible response indicating that processing is already complete.

### processing

Do not schedule duplicate work.

Return a sensible idempotent response or conflict response.

### wrong Course / missing Document

Return correct 404 behaviour.

### pending_cleanup

Reject retry.

Retry must operate through the Document → Content relationship.

Do not expose raw arbitrary Content IDs as a user-facing API unless justified.

---

# Phase 7 — Document deletion

Implement single-document deletion.

The user must be able to remove a Document from a Course without deleting the entire Course.

Add an API such as:

```text
DELETE /courses/{course_id}/documents/{document_id}
```

Requirements:

- verify the Document belongs to the Course
- delete only that Document association
- do not accidentally delete Content that another Document references
- preserve shared chunks while Content remains referenced
- return correct 404 behaviour
- maintain transactional consistency

---

# Phase 8 — Define orphan Content cleanup

The current design allows multiple Documents to reference the same Content.

Therefore:

```text
Course A → Document A ┐
                      ├→ Content X → Chunks
Course B → Document B ┘
```

If Document A is deleted:

```text
Content X must remain
```

because Document B still references it.

If the last Document referencing Content X is deleted, decide and implement a conservative lifecycle policy.

Evaluate two reasonable V1.1 choices:

### Option A — immediate cleanup

Delete:

```text
Content
Chunks
stored PDF
```

after the last Document reference disappears.

### Option B — pending cleanup

Mark Content:

```text
pending_cleanup
```

and remove data/files through a separate cleanup function.

Choose whichever is safer and simpler given the current transaction/file-storage architecture.

Important:

Database deletion and filesystem deletion cannot share one ACID transaction.

Design around this honestly.

Avoid a state where:

```text
DB transaction rolls back
but PDF has already been permanently deleted
```

If filesystem cleanup can fail:

- do not corrupt DB relationships
- log the failure
- preserve enough information to retry cleanup

Do not introduce a distributed garbage collector.

Implement only a clean V1.1 lifecycle.

---

# Phase 9 — Upload race-condition review

The earlier audit identified that same-Course duplicate upload protection relies partly on application logic.

Review this area again.

Determine whether there is currently a database-level guarantee equivalent to:

```text
UNIQUE(course_id, content_id)
```

for Documents.

If not, evaluate adding one.

If it is semantically correct for the product, add the database constraint through a new Alembic migration.

Handle resulting IntegrityError cleanly.

The goal is:

> Concurrent uploads of the same file into the same Course must not produce duplicate Document rows.

Do not rely exclusively on:

```text
SELECT first
then INSERT
```

because concurrent transactions can race.

If a schema change is made:

- create a new migration
- do not edit historical migrations
- test it

---

# Phase 10 — API schemas

Review Course detail / Document schemas.

Expose enough information for the frontend to render:

- Document ID
- filename/display name
- creation time
- processing status

Do not expose:

- internal storage path
- raw filesystem key unless genuinely required
- unnecessary Content implementation details

The frontend should not need to understand storage internals.

---

# Phase 11 — Frontend processing UX

Update the existing Course detail UI conservatively.

Do not redesign the whole application.

Each Document should show a clear status.

Examples:

```text
Uploaded
Processing
Ready
Failed
```

If `processing` is not publicly observable because of transaction semantics, do not fake it.

A simpler visible lifecycle such as:

```text
Processing…
Ready
Failed
```

may map `uploaded` to user-facing "Processing…" once work has been scheduled.

Document this mapping clearly.

---

# Phase 12 — Polling

After upload succeeds, frontend status should update automatically.

Implement bounded polling.

Conceptually:

```text
upload succeeds
→ document appears
→ start polling course details
→ observe terminal state
→ stop
```

Requirements:

- reasonable interval
- no ultra-fast polling
- do not create multiple timers for the same page
- stop when all relevant documents are terminal
- clean up timer on component unmount
- stop after a reasonable maximum duration
- surface polling/API errors separately from document-processing errors
- retrying a failed Document should restart polling

Do not add WebSockets in this task.

---

# Phase 13 — Retry UI

For failed Documents, add a small Retry action.

User flow:

```text
Failed
[Retry]
```

Clicking retry:

```text
POST retry endpoint
→ UI enters processing/pending state
→ polling starts
→ Ready or Failed
```

Prevent accidental rapid duplicate retry requests.

---

# Phase 14 — Delete Document UI

Add a Delete action for individual Documents.

Use confirmation appropriate to the existing UI.

After successful deletion:

- remove Document from frontend state
- ensure polling logic no longer tracks it

If deletion causes Content cleanup internally, the frontend does not need to know those storage details.

---

# Phase 15 — Backend tests

Expand tests based on behaviour rather than coverage percentage.

At minimum verify:

### Automatic processing

- new Content schedules processing after upload
- processing is not scheduled before upload commit
- background worker creates its own Session
- background worker reloads Content by ID
- worker always closes Session
- successful processing produces ready + chunks
- processing failure preserves uploaded Document and produces correct Content state
- processing failure does not affect upload HTTP success

### Shared Content

- existing ready Content is reused
- ready shared Content is not automatically reprocessed
- new Document observes the shared ready status/chunks

### Retry

- failed Document can retry
- ready Document does not unnecessarily reprocess
- processing Document does not schedule duplicate work
- invalid Course/Document relationship returns 404
- pending cleanup cannot retry

### Delete

- deleting Document removes only the relationship
- shared Content remains while referenced
- last-reference behaviour follows the chosen cleanup policy
- filesystem cleanup failure is safe
- missing Document returns 404

### Concurrent duplicate upload

If `(course_id, content_id)` uniqueness is implemented:

- concurrent/simulated duplicate insert cannot create two rows
- IntegrityError maps to predictable API behaviour

Preserve all existing parsing/concurrency tests.

---

# Phase 16 — PostgreSQL integration tests

SQLite does not prove PostgreSQL locking or constraint behaviour.

Extend the existing optional PostgreSQL test suite where useful.

At minimum verify the PostgreSQL-specific behaviour for any newly added:

- unique constraint
- delete/reference lifecycle
- retry interaction with Content locking

Continue using isolated temporary schemas.

Do not touch the developer's real CourseMate database.

---

# Phase 17 — Frontend verification

Use existing tooling.

Run:

```bash
cd apps/web
npm run lint
npm run build
```

If a frontend test framework already exists, add focused tests.

If no frontend test framework exists, do not introduce a large framework solely for this task.

Instead document manual verification.

---

# Phase 18 — Manual end-to-end verification

Run the complete local stack with PostgreSQL.

Verify with real PDFs.

Scenario A:

```text
create Course
→ upload PDF
→ upload succeeds
→ Document appears
→ backend processing starts
→ chunks are generated
→ frontend reaches Ready
```

Scenario B:

```text
upload same PDF to second Course
→ Content reused
→ no unnecessary reprocessing
→ second Document is Ready
```

Scenario C:

```text
force processing failure
→ upload remains recorded
→ frontend reaches Failed
→ Retry
→ processing succeeds
→ frontend reaches Ready
```

Scenario D:

```text
two Courses reference same PDF
→ delete Document from Course A
→ Course B still works
→ chunks/file remain
```

Scenario E:

```text
delete final Document
→ chosen orphan cleanup policy executes
→ database/filesystem stay consistent
```

Record what was actually tested.

Do not claim tests that were not run.

---

# Phase 19 — Developer documentation

Update backend README or relevant documentation with:

- document ingestion architecture
- processing lifecycle
- retry behaviour
- deletion lifecycle
- shared Content semantics
- background task limitations
- PostgreSQL test command
- local end-to-end startup steps

Document the actual implementation only.

Do not describe future RAG functionality as implemented.

---

# Phase 20 — Final verification

Run the complete backend suite.

Default:

```bash
cd services/api
python -m pytest -q
```

PostgreSQL:

```bash
TEST_POSTGRES_URL="..." python -m pytest -q
```

Frontend:

```bash
cd apps/web
npm run lint
npm run build
```

Check:

```bash
alembic heads
```

If a migration was added, verify:

```bash
alembic upgrade head
```

against an appropriate development/test PostgreSQL database.

Report exact outputs.

Do not claim GitHub CI passed unless GitHub Actions actually ran.

---

# Final engineering report

Produce a report containing:

## 1. Architecture before and after

Show the final ingestion flow:

```text
Browser
  ↓
Upload API
  ↓
file + Document + Content commit
  ↓
schedule content_id
  ↓
background worker
  ↓
dedicated SQLAlchemy Session
  ↓
state check
  ↓
process_content()
  ↓
atomic chunks/status commit
  ↓
frontend polling
  ↓
Ready / Failed
```

## 2. State machine

Document all meaningful transitions.

For example:

```text
uploaded
   ↓
 processing attempt
   ├── success → ready
   └── failure → failed

failed
   ↓ retry
 processing attempt
   ├── success → ready
   └── failure → failed

ready
   ↓ explicit refresh only
 ready / preserved ready on refresh failure
```

Adjust this diagram to the actual implementation.

## 3. Shared Content lifecycle

Explain:

```text
Document N → Content 1
```

and exactly what happens when Documents are deleted.

## 4. Filesystem consistency

Explain how stored-file cleanup interacts with database transactions and what happens when cleanup fails.

## 5. Changes made

For each important change:

```text
Problem
→ Root cause
→ Design
→ Implementation
→ Verification
```

## 6. Tests

Report:

- default backend suite
- PostgreSQL suite
- frontend lint
- frontend build
- migration verification
- manual end-to-end scenarios

Give exact counts/results.

## 7. Known limitations

Explicitly include:

- FastAPI BackgroundTasks are not durable
- process crash may lose scheduled work
- no persistent task queue
- no OCR
- no embeddings
- no retrieval
- no authentication
- processing holds a DB connection during PDF parsing
- any remaining orphan cleanup limitations
- any historical `processing` recovery limitation

## 8. V1.1 readiness

Give a concrete answer to:

> Can a normal user now upload, process, retry, observe, and delete course PDFs through the web application without manually invoking Python functions?

Support the answer with evidence.

## 9. Next milestone

Do not implement it.

If V1.1 ingestion is stable, propose the next milestone as:

```text
Chunk
→ Embedding
→ course-scoped similarity search
→ retrieval evaluation
```

Do not start AI answer generation yet.

---

# Engineering rules

- Do not rewrite working architecture unnecessarily.
- Do not weaken existing processing transaction guarantees.
- Do not hide failures.
- Do not inflate test coverage with meaningless tests.
- Prefer database constraints for true data invariants.
- Preserve shared Content semantics.
- Use dedicated DB sessions for background work.
- Keep external side effects outside unsafe transaction ordering.
- Do not merge to `main`.
- Do not silently push unrelated changes.
- Make logical commits.
- Leave a clean branch and a detailed final report.