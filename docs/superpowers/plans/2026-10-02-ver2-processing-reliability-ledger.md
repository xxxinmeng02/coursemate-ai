# Execution ledger

- Base: ver2 / 82a1106; dedicated branch fix/ver2-processing-reliability.
- Inspection: original 33 tests pass; problems A and B reproduce failed status with zero chunks.
- Task 1: complete — SQLite regressions RED (7 failed, 10 passed) → GREEN (42 passed). Core commit 113e30b.
- Task 2: complete — original PostgreSQL parser RED (2 failed, 1 passed); fixed full suite with PostgreSQL 46 passed, 1 pre-existing warning. Alembic head unchanged: 9a2f1c0e4b7d.
- Ruling: reuse an isolated clone because native worktree creation failed after prolonged filesystem waits; preserve commits and import the dedicated branch into the original repository if possible. Cost if import fails: review checkout remains at a separate persistent path.
- Ruling: transaction-owned write lock instead of a committed processing lease; no schema changes. Cost: transaction/connection held during parsing; processing progress is not publicly committed.
- Ruling: failed refresh retains ready and canonical data; exception plus log records failure. Cost: no persisted refresh-error history until background integration.
- Ruling: supplied implementation task authorizes completing the written requirements inline without additional plan approval. Final independent review remains required.
- Final review: independent reviewer found no production correctness issues; SQLite and PostgreSQL suites rerun independently.
- Final: Ruling: commit-failure regression gap treated as important although reviewer graded it minor — the test must catch unlocked post-rollback cleanup, a core user guarantee. Cost: one additional verification pass, no implementation expansion.
- Final: fixed commit-failure test weakness — only first commit fails; subsequent commits really persist; test asserts one attempt and intact canonical data. Original parser RED (one failure, two commit attempts) → fixed GREEN; full suite 46 passed, 1 warning.
- Final: Ruling: already-flushed caller writes remain outside the dedicated-session contract; tradeoffs of transaction-held locks, public progress, durable refresh errors and recovery remain documented. Cost: background integration must honor these contracts and cannot infer unsupported progress.
- Final: Ruling: ambiguous network commits, alternate isolation levels, uncooperative writers, historic inconsistent rows and unrelated upload/GC/AI concerns remain outside this bounded fix. Cost: operational validation and separate scoped work remain necessary.
- Task 3: complete — independent review plus strengthened regression and complete suite verified; preserve the dedicated branch, do not merge or push.
