# RAG Retrieval Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Retrieve ranked canonical Chunks for a Course and query using PostgreSQL/pgvector while preserving existing ingestion.

**Architecture:** Add vector/configuration fields directly to Chunk, isolate provider calls in embeddings.py, and expose search_course with a Course-filtered database query. A separate backfill module owns generation transactions; retrieval uses the caller's read-only Session. Exact cosine ranking establishes the initial correctness baseline.

**Tech Stack:** Existing FastAPI, SQLAlchemy, Alembic, psycopg, pytest; pgvector Python; an HTTP client for the OpenAI embeddings endpoint; PostgreSQL 17 with pgvector.

**Spec:** `docs/superpowers/specs/2026-10-08-rag-retrieval-foundation-design.md`, approved on 2026-10-08.

## Global Constraints

- Base branch: `codex/rag-retrieval-foundation`, starting at remote ver2 commit `259609e41da4da7b5d6b9ba0effb22a3ca20c996`. Do not merge to main.
- Vector dimension: 1536. Initial model: text-embedding-3-small. Configuration identity includes provider, model, dimension, and revision.
- New migration follows `9a2f1c0e4b7d`; do not modify either old revision.
- Search top-k default: 5, environment-configurable; valid range: 1–50. Query: stripped, nonblank, maximum 2000 characters.
- No vectors, storage paths, hashes, provider exceptions, or secrets in normal API responses or logs.
- No changes to PDF extraction, chunking, upload dispatch, or canonical Content processing architecture.
- No LLM answers, chat, agents, OCR, authentication, queues, separate vector database, or RAG framework.
- Lower modules never import routers; parsing never imports retrieval; generation owns a dedicated Session's commit/rollback; retrieval never commits/closes/mutates the caller's Session.
- No speculative frameworks. Use explicit functions and only data structures needed for the current contract.

## Review Focus

- Same Content referenced by several Course-local Documents: return one canonical Chunk with a deterministic Course-local Document (Task 4).
- Generation races with successful PDF refresh: the Content lock prevents writing vectors for stale Chunk rows (Task 3).
- Configuration changes between embedding request and persistence: capture one immutable configuration for the operation (Tasks 2–4).
- Invalid, infinite, NaN, or zero provider vectors: reject them before persistence or cosine comparison (Tasks 2–3).
- Commit failure or caller's pending unrelated writes: roll back generation, preserve old embeddings/text, and avoid committing unrelated state (Task 3).

## Execution and baseline

Recommended execution: native implementation in this chat because tasks share a small set of interfaces and transaction rules. User approved the plan and selected native execution on 2026-10-08; execution and the final independent review are complete.

Use the existing Python 3.13 environment for read-only baseline checks; create a worktree-local .venv for dependencies during execution. Create a separate disposable pgvector container/database for verification, leaving the user's running PostgreSQL container untouched. Persist exact commands and results in `docs/RAG_RETRIEVAL_FOUNDATION.md`.

### Task 1: Vector storage and additive migration

**Files:** Modify `services/api/app/models/chunk.py`, `services/api/requirements.txt`, `services/api/compose.yaml`; create `services/api/alembic/versions/c81d4a6b209f_chunk_embeddings.py`, `services/api/tests/conftest.py`, and `services/api/tests/test_retrieval_postgres.py`; adjust PostgreSQL fixture setup in `services/api/tests/test_processing_postgres.py` only if necessary to create the extension before model tables.

**Interfaces:** Consume existing Chunk and Base metadata. Produce `Chunk.embedding` (nullable vector(1536), JSON variant on SQLite), `Chunk.embedding_config` (nullable string), paired-null constraint `ck_chunks_embedding_pair`, and migration head `c81d4a6b209f`.

- [x] Write `test_embedding_round_trip` asserting a 1536-vector and configuration persist without changing text/page/index; `test_vector_dimension_enforced` asserting PostgreSQL rejects a 3-vector; and `test_embedding_pair_constraint` asserting incomplete pairs fail. Put shared PostgreSQL setup in conftest with random temporary schemas and explicit opt-in TEST_POSTGRES_URL.
- [x] Run `python -m pytest tests/test_retrieval_postgres.py -q` with the disposable TEST_POSTGRES_URL; verify expected failures due to absent embedding fields.
- [x] Add the fields/constraint and new migration. Enable vector idempotently on upgrade; leave the extension installed on downgrade. Pin the installed pgvector dependency and production HTTP client dependency. Switch Compose to `pgvector/pgvector:pg17` without changing PostgreSQL major version or existing volume conventions.
- [x] Run the new persistence tests and the existing default suite; verify the SQLite variant preserves the pre-existing tests.
- [x] Commit only Task 1 files: `feat(api): add pgvector chunk embedding storage`.

### Task 2: Isolated embedding provider and configuration identity

**Files:** Create `services/api/app/embeddings.py` and `services/api/tests/test_embeddings.py`; modify `services/api/.env.example` and `services/api/README.md`.

**Interfaces:** Produce immutable `EmbeddingConfig` containing model/revision and a canonical identifier, `get_embedding_config() -> EmbeddingConfig`, `embed_text(text: str, *, config: EmbeddingConfig | None = None) -> list[float]`, `validate_embedding(vector: list[float]) -> list[float]`, and `EmbeddingError`. Keys are read from environment at call time and excluded from configuration identity/repr. Model and revision are captured once per operation.

- [x] Write provider HTTP tests asserting request model, dimensions=1536, encoding_format=float, nonblank input, finite timeout, and parsed output. Mock HTTP only here; no SQL mocks. Add cases for missing key, unsupported model, malformed response, provider failure, wrong length, NaN/infinity, zero vector, and no secret/provider-body exposure in error/log text.
- [x] Run `python -m pytest tests/test_embeddings.py -q`; confirm missing module/interface failures.
- [x] Implement explicit functions using one HTTP client. Support text-embedding-3-small initially and text-embedding-3-large at explicitly requested 1536 dimensions; reject unsupported models. Identity format is `openai:{model}:1536:{revision}`; revision defaults to v1. Validate vector length/finite components/nonzero norm, including float32 storage compatibility. Wrap provider failures with safe generic messages, without logging underlying response bodies.
- [x] Document OPENAI_API_KEY, EMBEDDING_MODEL, EMBEDDING_REVISION, dimension migration requirements, and alias/revision limitations. Environment examples contain no real key.
- [x] Run provider tests; commit `feat(api): isolate embedding provider and version identity`.

### Task 3: Retryable embedding generation and command

**Files:** Create `services/api/app/embedding_backfill.py` and `services/api/tests/test_embedding_backfill.py`; extend `services/api/tests/test_retrieval_postgres.py`; update `services/api/README.md`.

**Interfaces:** Consume Task 2 interfaces. Produce `embed_content(db: Session, content_id: int, *, force: bool = False, config: EmbeddingConfig | None = None) -> dict[str, int]` with generated/skipped counts, and a `python -m app.embedding_backfill [--content-id ID] [--force]` entry point. The function owns commit/rollback; CLI opens/closes dedicated sessions.

- [x] Write tests for persisted vectors/configuration, idempotent retry with no provider calls, forced replacement, stale-config replacement, non-ready rejection, and failure on a later chunk preserving all prior stored rows/vectors/status. Check no text duplication or Chunk insertion/deletion.
- [x] Add pending-write and caller-savepoint rejection tests; inject first-commit failure and assert no secondary cleanup write. Add PostgreSQL contention tests proving generation/refresh and two generation attempts serialize on Content ownership.
- [x] Run `python -m pytest tests/test_embedding_backfill.py tests/test_retrieval_postgres.py -q`; confirm missing generation-interface failures.
- [x] Implement the same no-op Content UPDATE lock convention as processing, refreshed under lock. Capture configuration once, select chunks in index order, skip valid current vectors unless forced, validate replacements, and commit one Content atomically. Catch failures with rollback and safe errors; preserve existing rows. CLI processes distinct ready Content IDs and reports counts/failures with nonzero exit for failures.
- [x] Run generation/provider/storage tests plus PostgreSQL contention tests. Document that successful PDF refresh requires a backfill and provider calls hold the Content lock.
- [x] Commit `feat(api): add retryable ready-content embedding backfill`.

### Task 4: Course-scoped retrieval and minimal API

**Files:** Create `services/api/app/retrieval.py`, `services/api/app/schemas/retrieval.py`, and `services/api/tests/test_retrieval_api.py`; modify `services/api/app/routers/courses.py`; extend `services/api/tests/test_retrieval_postgres.py` and `.env.example`.

**Interfaces:** Consume Chunk fields and Task 2 interfaces. Produce `search_course(db: Session, course_id: int, query: str, top_k: int) -> list[RetrievalResult]`, internal `_search_course_vectors(...)` in the same module, and `CourseNotFoundError`. RetrievalResult is an explicit data result with chunk_id/text/page_number/document_id/document_name/score. API request/result schemas handle serialization and validation; routers translate domain errors to HTTP.

- [x] Seed deliberately distinct vectors in real PostgreSQL and assert cosine ranking, scores, top-k, stable ID ties, closer foreign-Course exclusion, shared Content retrieval in both Courses, and one canonical result for duplicate Course-local Document references. Assert unembedded, non-ready, and mismatched-config chunks are excluded; missing Course is detected before a provider call.
- [x] Add HTTP tests for 200 response fields, empty results, 404, 422 on blank/overlong query and top-k outside 1–50, configurable default of 5, and safe 503 on provider failure. Assert vector/path/hash/configuration do not leak. Test successful retrieval leaves db pending state unchanged and never commits/closes the Session.
- [x] Run `python -m pytest tests/test_retrieval_api.py tests/test_retrieval_postgres.py -q`; confirm absent retrieval/endpoint failures.
- [x] Implement orchestration and exact SQLAlchemy cosine ranking. Build a Course-filtered per-Content Document selection (lowest ID) before joining canonical chunks; filter ready/configured/non-null vectors before ORDER BY distance, Chunk ID and LIMIT. Keep provider calls and SQL separate within retrieval.py. Handle empty candidates safely without a needless embedding request.
- [x] Add the thin POST route and validated schemas. Document `RETRIEVAL_DEFAULT_TOP_K`; defensively validate the internal function's inputs as well as HTTP inputs without building another configuration framework.
- [x] Run retrieval tests with actual pgvector and all existing tests; commit `feat(api): add course-scoped semantic search`.

### Task 5: Semantic sanity evaluation, verification, and maintainability review

**Files:** Create `evals/retrieval/topics.json`, `services/api/app/retrieval_eval.py`, and `docs/RAG_RETRIEVAL_FOUNDATION.md`; update `services/api/README.md` and add evaluation tests in `services/api/tests/test_retrieval_postgres.py`. Add `evals/retrieval/recorded_embeddings.json` only if real provider capture is available.

**Interfaces:** Consume public search_course plus embedding generation. Provide `python -m app.retrieval_eval` to evaluate topic fixtures in an isolated schema and print expected/actual ranking. Capture provider-backed vectors with model/configuration provenance when credentials are available; synthetic vectors are clearly labeled geometry tests.

- [x] Write a small parallel-programming/TCP/accounting fixture with three expected-topic queries. Add a deterministic PostgreSQL ranking check and a separate real-provider/recorded-vector evaluation path; require expected topic above unrelated chunks for every query.
- [x] Run the evaluation test before adding fixture handling; verify the expected failure, then implement a small operator command reusing generation and search_course in a dedicated temporary schema. It must not write into the user's Course tables.
- [x] Run migration verification in a disposable database: `alembic upgrade 9a2f1c0e4b7d`; seed pre-retrieval Content/Chunk/Document rows; `alembic upgrade head`; inspect extension/vector types and preserved rows; `alembic downgrade 9a2f1c0e4b7d`; `alembic upgrade head`; `alembic heads`; `alembic current`; and `alembic check`.
- [x] Run `python -m pytest -q` without PostgreSQL and then with TEST_POSTGRES_URL; separately run `python -m pytest tests/test_retrieval_postgres.py -q` with PostgreSQL. Capture exact summaries and warnings. Run the semantic evaluation; explicitly report unavailable credentials and any skips instead of claiming provider quality from synthetic vectors.
- [x] Review the whole diff against the spec and report every requested maintainability category: duplication, abstractions, coupling, function size/responsibility, Session ownership, mutation points, dead code, and speculative interfaces. Remove needless complexity and rerun affected checks. Perform the independent review required by the execution workflow only after the user's execution selection authorizes it.
- [x] Finish `docs/RAG_RETRIEVAL_FOUNDATION.md` with exact verification, limitations, dependency diagram and recommended next step (retrieval evaluation before answer generation). Commit `test(api): evaluate and document retrieval foundation`.
- [x] Deliver changed-file list and key code changes in Chinese, with clickable worktree paths, exact test/migration evidence, maintainability findings, and the implemented diagram. Leave the branch available for review; do not merge to main.

## Plan self-review

The five tasks cover all original requirements and maintainability additions.
Review Focus cases are assigned concrete tests. Interfaces use the same names
across tasks; model-dependent validation stays in embeddings.py, SQL stays in
retrieval.py, and generation remains independent of parsing. All five implementation tasks are complete. Real provider quality remains explicitly unverified because no API key is configured; the opt-in evaluation command and test are available. Final findings and verification are in `docs/RAG_RETRIEVAL_FOUNDATION.md`.
