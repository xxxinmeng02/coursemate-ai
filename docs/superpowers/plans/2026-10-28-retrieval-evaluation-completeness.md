# Retrieval Evaluation Completeness Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans in this session; user chose native execution. No push or merge.

**Goal:** Add proven full-corpus MRR and explicit model provenance to the existing MIT evaluator.

**Architecture:** Reuse source validation to create a manifest and verify the full HTTP ranking. Keep model receipt parsing in a small evaluation-only module shared by the HTTP evaluator and existing local runner; leave production retrieval unchanged.

**Tech Stack:** Existing Python standard library, pytest, current parser and HTTP API.

**Spec:** `docs/superpowers/specs/2026-10-28-retrieval-evaluation-completeness-design.md`

## Global Constraints

- Baseline `0112c82`; preserve historical results and pre-existing untracked report.
- No push, merge, new production endpoint, dependency, local-model installation or paid API call.
- Full MRR requires matching all locally verified chunks and consistent canonical IDs; maximum 49 with one extra probe slot within the API cap 50.
- Model declarations must state their provenance and lack of server verification; unknown versions remain null.

## Review Focus

- A rank-six hit contributes to full MRR but not MRR@5; misses stay in the denominator.
- Missing vectors, changed/foreign text, duplicate signatures and corpus changes cannot produce a complete ranking claim.
- Missing/invalid model metadata, unknown keys and secrets are rejected before requests.
- Legacy records are preserved, while the CLI requires explicit metadata for new measurement.
- Runtime receipts do not import/download the model, do not override files and do not claim an immutable upstream revision.

### Task 1: Full ranking and model provenance

**Files:** modify `evals/retrieval/evaluate_mit.py`, `local_embeddings.py`; create `embedding_record.py`, an OpenAI declaration template; extend `services/api/tests/test_real_course_http_eval.py` and add receipt tests.

- [x] Write tests for hand-derived full/capped MRR, full ranking verification, partial corpus, model records, runtime receipt and CLI wiring.
- [x] Run new tests RED and inspect expected failures (21 failed, 1 source-cache skip before implementation).
- [x] Implement manifest verification and full metrics; add strict provenance record loading and optional local receipt output.
- [x] Run focused tests GREEN (49 passed), then full backend suite (165 passed, 61 skipped, 1 existing warning). Do not change history or fabricate live metrics.

### Task 2: Handoff and review

**Files:** update `docs/REAL_COURSE_RETRIEVAL.md`, `evals/retrieval/README.md`; create `docs/RETRIEVAL_STATUS_2026-10-28.md`.

- [x] Document new commands, metadata trust boundary, latency scope and historical-result limitations.
- [x] Review responsibilities, duplicated logic, transaction ownership, mutation points and unnecessary abstractions.
- [x] Verify no production retrieval changes, no secret persistence, valid source labels, and clean whitespace.
- [x] Leave all changes local for user review; report exact results and blocked live evaluation.

## Execution and review record

- User's native execution choice and no-push instruction are preserved; no additional design approval was requested for these explicitly authorized corrections.
- Ruling: model provenance is explicitly declared / local receipt, not remotely attested; changing the production API is out of this small evaluation task. Cost: operator must keep the declaration aligned with the running server.
- Ruling: preserve old storage identities and historical results instead of retroactively relabeling BGE vectors. Cost: the physical identifier retains its legacy prefix; the new logical provider field is required to interpret it.
- Independent read-only review found 2 Important issues, no Critical/Minor. Three tests reproduced them RED: an exact-N request hid a trailing chunk; a 50-chunk manifest cannot probe the API cap; local receipt preceded app environment initialization.
- Fixed both findings in one pass: request N+1 and reject N>=50; write local API receipt after app initialization. New regressions GREEN; full suite GREEN as above.
- Ruling: the complete benchmark limit is 49 with current API cap 50; support for larger corpora would need a separate completeness mechanism. Cost: a larger dataset is blocked rather than assigned a misleading full MRR.
- Declined-to-judge audit: real model quality and paid API availability remain unmeasured; no model installation, remote attestation or database writes were added. Remaining documentation was completed after review. No speculative architecture was introduced to close these unrelated gaps.
- No deferred minors. Current changes remain uncommitted and unpushed, as local reviewable files.
