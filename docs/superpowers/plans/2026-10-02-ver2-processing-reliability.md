# Ver2 PDF Processing Reliability Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan inline, with a final independent review. Steps use checkbox syntax for tracking.

**Goal:** Preserve usable PDF chunks across failed refreshes and prevent overlapping attempts from corrupting results.

**Architecture:** Acquire a database write lock on the Content row using a no-op UPDATE RETURNING, then hold it through extraction and replacement in one outer transaction. PostgreSQL serializes the row; file-backed SQLite serializes writers. A savepoint protects the canonical chunks so parse/flush failures can record a consistent status without releasing ownership. No schema changes or processing leases.

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL 17, SQLite, pypdf, pytest.

**Spec:** `docs/superpowers/specs/2026-10-02-ver2-processing-reliability.md` (the supplied task).

## Global Constraints

- Base commit: `82a11060dbb264b7074ea1769b9ab65a3cf2418e`, branch `fix/ver2-processing-reliability`.
- Do not merge main, add queues, embeddings, vector search, RAG, OCR, authentication, or UI features.
- Preserve `process_content(db: Session, content: Content) -> list[Chunk]`.
- Processing uses a clean, dedicated session; reject unrelated pending changes rather than committing them.
- Existing ready data remains ready on refresh failure; the exception/log records the unsuccessful refresh.
- `processing` is transaction-local, not committed progress. A disconnected transaction rolls back and releases its lock.
- No migration unless evidence shows one is required.

## Review Focus

- Stale ORM Content state must be refreshed under the lock before deciding failure status.
- A failed replacement after actual INSERT must preserve all old chunks.
- A lost final COMMIT must not launch unlocked cleanup or overwrite another worker.
- Committed legacy `processing` and `pending_cleanup` records must not be processed implicitly.
- Caller pending writes must not be committed/rolled back by processing.

### Task 1: Regression tests and reliable lifecycle

**Files:** Modify `services/api/app/parsing.py`, `services/api/tests/test_parsing.py`.

**Interfaces:** Keep `process_content`; processing errors remain `ContentProcessingError` with chained causes.

- [x] Add failed-refresh, stale-session, concurrent-connection, successful-refresh, INSERT-failure, COMMIT-failure, and pending-session regressions. Existing canonical rows and final statuses are asserted from fresh queries.
- [x] Run targeted tests against original implementation; confirm expected failures for deletion, stale state, and concurrent extraction.
- [x] Acquire ownership before extraction, refresh identity state, reject ineligible statuses, and replace only inside a savepoint. On rollback, never delete canonical rows as cleanup.
- [x] Run the whole backend suite. Expected: original 33 tests plus regressions pass.
- [x] Commit tests and implementation together after RED→GREEN evidence.

### Task 2: PostgreSQL verification and handoff documentation

**Files:** Create `services/api/tests/test_processing_postgres.py`, `docs/VER2_PROCESSING_RELIABILITY.md`; update `services/api/README.md`.

**Interfaces:** Optional `TEST_POSTGRES_URL` enables focused integration tests in a unique temporary schema; absence skips them.

- [x] Add deterministic two-session concurrency and failed-replacement integration cases; synchronize threads with events and verify PostgreSQL lock waits through `pg_stat_activity`, not sleep-based guesses.
- [x] Run them against the original parser and confirm they catch the known bugs before validating the fix.
- [x] Run tests in an isolated PostgreSQL 17 container. Never use the user's course database.
- [x] Document transaction boundaries, externally visible statuses, retry paths, upload trigger point, shared-content policy, session ownership, and remaining crash/progress limitations.
- [x] Record exact final test results and unchanged Alembic heads; commit the report and integration verification.

### Task 3: Final review and delivery

- [ ] Perform an independent branch review, fix material findings with failing regressions first, and rerun the complete suite.
- [ ] Verify clean branch, logical commits, unchanged schema, and no upload/AI scope expansion.
- [ ] Retain the dedicated branch for the user; do not merge or push automatically.
