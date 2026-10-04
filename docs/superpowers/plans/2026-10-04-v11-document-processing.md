# V1.1 Document Ingestion Implementation Plan

> Implement inline with superpowers:executing-plans; the independent frontend task uses superpowers:dispatching-parallel-agents. Final independent review required.

**Goal:** Upload, automatically parse, observe, retry and delete PDFs through the existing web application.
**Base:** latest ver2, `259609e`; branch `feature/v1.1-document-processing`.
**Spec:** `docs/superpowers/specs/2026-10-04-v11-document-processing.md`.
**Architecture:** FastAPI BackgroundTasks pass only content_id to a dedicated-session job. Reuse a transaction-held Content write lock for authoritative state checks; auto jobs process only uploaded. Retry commits failed→uploaded before scheduling. Last-reference deletion commits pending_cleanup, then an idempotent cleanup job removes the file and tombstone under lifecycle locks; failed cleanup leaves retry metadata. Hash transaction locks coordinate upload, cleanup, and failed-upload file disposal. PostgreSQL uses an advisory hash lock; SQLite uses a database write lock. Document uniqueness is enforced by a new migration. No processing leases or public progress commits.

## Constraints and state semantics

- No queues, auth, OCR, embeddings, retrieval, AI chat, redesign or framework migrations.
- `uploaded`: committed material waiting for first attempt or explicit retry; UI says pending processing, including possible lost background work.
- `processing`: transaction-local during new attempts; historical committed rows are not reset automatically.
- `ready`: usable canonical chunks; shared ready content is not reprocessed automatically.
- `failed`: needs explicit retry; automatic tasks skip it.
- `pending_cleanup`: committed unreferenced tombstone; reject upload reuse/retry, preserve hash/storage metadata if unlink or final DB deletion fails.
- No request session or ORM object goes into background work. Scheduling failures are logged after upload commit and do not change its success response.
- No merge or automatic push. Use isolated PostgreSQL schemas/database only.

## Task 1: Locking, jobs and upload (backend)

Files: `app/content_lifecycle.py`, `app/jobs.py`, `app/parsing.py`, `app/routers/documents.py`, backend tests.
- [ ] Write behaviour tests for post-commit scheduling, dedicated worker sessions, closed sessions, state-aware auto work, failure-isolated uploads and skipped shared-ready data; observe RED.
- [ ] Extract `lock_content(db, content_id)`, add `lock_content_hash(db, hash)`, `process_content_job(content_id)`, `schedule_content_processing(tasks, content_id)`.
- [ ] Integrate upload scheduling only after commit; lock hash before content lookup and file promotion; handle integrity collisions predictably. Failed-upload file disposal checks for persisted content under the same hash lock.
- [ ] Run complete backend suite and commit after GREEN.

## Task 2: Retry, deletion, cleanup and uniqueness (backend)

Files: document/course routers, lifecycle/jobs module, Document model, new Alembic revision, unit/PostgreSQL tests.
- [ ] Write RED cases for retry states and wrong-course 404, shared-reference preservation, last-reference cleanup, unlink failure, cleanup commit failure, and unique invariants.
- [ ] `POST /courses/{course_id}/documents/{document_id}/retry`: 202 + DocumentSummary for uploaded/failed; failed transitions to uploaded atomically. 200 unchanged summary for ready/processing; 409 pending_cleanup; 404 wrong relationship.
- [ ] `DELETE` same document path: 204; lock Content, remove association, mark pending_cleanup iff no remaining refs, commit before scheduling cleanup. Apply same orphan policy to course deletion.
- [ ] `cleanup_content_job(content_id)` checks pending_cleanup and no refs under locks; unlink only after durable detach intent, then delete Content/cascaded chunks. Failures retain the tombstone (possibly with already absent file) and log for idempotent retry. Provide explicit cleanup CLI for pending rows.
- [ ] Add `(course_id, content_id)` unique constraint in model and new migration. Refuse migration on historical duplicates with actionable guidance instead of silently deleting associations.
- [ ] Verify PostgreSQL constraints, lifecycle/processing interaction and migration upgrade; run full suite and commit.

## Task 3: Frontend (independent file ownership)

Files: `apps/web/app/course-api.ts`, `course-detail.tsx`, modest CSS additions only.
- [ ] Read apps/web/AGENTS.md and installed Next docs before implementation; preserve baseline styles.
- [ ] Add retry/delete API helpers matching Task 2 and conservative document actions/confirmation.
- [ ] One bounded poll loop: 3-second interval, 120-second max, abort on unmount, no overlapping requests, stop on terminal docs, separate polling errors; retry/upload restart polling. Uploaded means queued/pending, not a fictitious committed processing state.
- [ ] Verify lint/build and focused manual browser cases; do not add a new test framework or change backend files.

## Task 4: Integrated verification and report

- [ ] Run optional PostgreSQL suite and migration chain against an isolated database; preserve all existing processing tests.
- [ ] Run real local API + frontend against isolated PostgreSQL and real PDFs. Record scenarios A–E including repairable parse failure/retry and shared/final deletion; inspect actual DB chunks and files.
- [ ] Verify polling timeout/error handling and action confirmation without claiming unrun browser cases.
- [ ] Update README and `docs/V11_DOCUMENT_PROCESSING_REPORT.md` with before/after architecture, transitions, cleanup ordering, test outputs and durability/recovery limitations.
- [ ] Independent code review, fix material issues through regressions; final default/PG suite, lint/build, heads and clean branch; commit and leave unmerged.
