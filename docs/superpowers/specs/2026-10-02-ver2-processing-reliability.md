# Task: CourseMate-AI Ver2 — Make PDF Processing Reliable

Work from the current `ver2` branch.

The current repository already has:

- Course management
- PDF upload
- SHA-256 content deduplication
- `Document` / `Content` / `Chunk` models
- PDF text extraction with `pypdf`
- page-local chunking
- `process_content(...)`
- 33 passing backend tests

Do **not** implement embeddings, vector search, RAG, AI chat, OCR, authentication, or unrelated UI features.

The goal of this task is to make the existing PDF processing pipeline **safe, retryable, and ready to be connected to automatic processing**.

Create a new branch from `ver2`, for example:

```text
fix/ver2-processing-reliability
```

Do not merge into `main`.

---

# Phase 1 — Inspect before changing anything

Before editing files:

1. Inspect the current implementation of:
   - `Content`
   - `Chunk`
   - `process_content`
   - upload route
   - database transaction handling
   - parsing tests
   - relevant migrations

2. Run the backend baseline:

```bash
cd services/api
python -m pytest -q
```

Expected current baseline is approximately:

```text
33 passed
```

3. Reproduce and explain these two known problems.

### Problem A — Concurrent processing

Two database sessions process the same `Content`.

Current observed failure scenario:

```text
worker A starts processing
worker B starts processing

worker A successfully commits chunks

worker B later fails

worker B failure cleanup deletes chunks by content_id

result:
Content.status = failed
Chunks = 0
```

This allows one failed worker to destroy another worker's successful result.

### Problem B — Failed reprocessing destroys old data

Current behaviour is approximately:

```text
existing ready Content
→ delete old chunks
→ commit deletion
→ start new extraction
→ extraction fails
→ Content becomes failed
→ old working chunks are permanently lost
```

Confirm whether the current code behaves this way.

Do not change files until you understand the root cause.

Provide a short inspection summary first.

---

# Phase 2 — Define safe processing semantics

Implement the following behaviour.

## Requirement 1 — Only one active processing attempt per Content

The system must prevent two processing attempts for the same `Content` from corrupting each other's data.

Choose the simplest robust approach appropriate for the current architecture.

Possible mechanisms may include:

- PostgreSQL row locking
- optimistic state transition
- processing token / attempt ID
- another small explicit mechanism

Do not add a distributed task framework merely to solve this problem.

Explain your choice.

The critical guarantee is:

> A stale or failed processing attempt must never delete or overwrite the successful result of another processing attempt.

---

# Phase 3 — Make reprocessing failure-safe

Change the processing lifecycle so that existing usable chunks are not destroyed before a replacement is ready.

Desired semantics:

```text
existing valid chunks
        ↓
start new processing attempt
        ↓
extract + prepare new chunks
        ↓
if successful:
    atomically replace old chunks
    mark Content ready

if failed:
    preserve previous valid chunks
    record processing failure appropriately
```

Do not leave the Content in a misleading state.

If preserving `ready` while recording a failed refresh requires a small model/status change, stop and evaluate whether it is actually necessary.

Prefer the smallest solution compatible with the current schema.

Do not make speculative schema changes.

---

# Phase 4 — Transaction design

Review the transaction boundary of `process_content`.

The successful database transition should be as atomic as practical.

Avoid intermediate commits such as:

```text
delete old chunks
COMMIT
...
insert new chunks
COMMIT
```

when they expose invalid intermediate state.

A successful replacement should ideally behave like:

```text
BEGIN

validate processing ownership
delete/replace old chunks
insert complete new chunk set
update Content state

COMMIT
```

On database failure:

```text
ROLLBACK
```

and previously committed valid data must remain usable.

Clearly explain:

- where transactions begin
- where commits happen
- where rollback happens
- why partial chunk sets cannot survive

---

# Phase 5 — Add regression tests

Add tests that reproduce the bugs **before** the fix and verify the corrected behaviour.

At minimum add tests for:

## Test A — Concurrent/stale processing attempt

Simulate two processing attempts for the same content.

Verify that a stale failing attempt cannot remove a successful chunk set.

## Test B — Failed reprocessing

Start with:

```text
Content.status = ready
existing valid chunks
```

Force the new parse attempt to fail.

Verify:

- the original chunks remain intact
- there is no partial replacement
- the final Content state is internally consistent

## Test C — Successful reprocessing

Start with old chunks.

Run successful processing.

Verify:

- old chunks are replaced
- only the new canonical chunk set exists
- `(content_id, chunk_index)` remains valid
- Content ends in `ready`

## Test D — Persistence failure

Force database persistence to fail during replacement.

Verify:

- rollback occurs
- old valid chunks remain intact
- no partial new chunk set survives

Keep tests deterministic.

---

# Phase 6 — PostgreSQL compatibility review

The normal unit tests currently use SQLite.

Review whether the concurrency/locking mechanism you choose actually behaves correctly on PostgreSQL.

Do not pretend SQLite verifies PostgreSQL locking behaviour.

If the repository already has a usable PostgreSQL test setup, add a focused integration test.

If not, document exactly what still requires PostgreSQL integration verification.

Do not build a large testing framework just for this task.

---

# Phase 7 — Prepare for upload integration

After processing reliability is fixed, inspect the upload route.

Do **not** fully implement a task queue yet.

Instead, answer:

1. At what exact point should automatic parsing be triggered after upload?
2. Should already-existing shared `Content` be parsed again?
3. What should happen when:
   - Content is `uploaded`
   - Content is `processing`
   - Content is `ready`
   - Content is `failed`
4. How should retry behave?
5. Should request-scoped DB sessions ever be passed into background work?

If there is one small refactor necessary to make future background execution safe, it may be implemented.

Do not introduce Celery, Redis, Dramatiq, or another queue in this task.

---

# Phase 8 — Final verification

Run:

```bash
cd services/api
python -m pytest -q
```

Report:

- total passed tests
- warnings
- newly added tests
- any PostgreSQL-specific limitation still not covered

Also inspect Alembic state if any schema change was made.

If no migration was necessary, explicitly say so.

---

# Deliverable

Provide a final engineering report with:

## Root causes

Explain why the two original consistency bugs existed.

## Design

Explain the processing ownership / concurrency solution.

## Transaction lifecycle

Show the final state transitions.

For example:

```text
uploaded
   ↓
processing
   ↓
ready
```

and all important failure/retry paths.

## Changes made

For every important modification:

```text
Problem
→ Root cause
→ Fix
→ Why this fix
→ Test proving it
```

## Tests

Give exact final results.

## Remaining risks

Especially distinguish:

- SQLite-tested behaviour
- PostgreSQL-dependent behaviour
- future background-task concerns

## Next step

Do not implement embeddings or RAG.

State whether the code is now safe enough for the next task:

> upload → automatic PDF processing → frontend status refresh

Do not merge anything automatically.

Commit the fixes in logical commits on the dedicated branch.