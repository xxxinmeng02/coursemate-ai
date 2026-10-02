# Execution ledger

- Base: ver2 / 82a1106; dedicated branch fix/ver2-processing-reliability.
- Inspection: original 33 tests pass; problems A and B reproduce failed status with zero chunks.
- Task 1: complete — SQLite regressions RED (7 failed, 10 passed) → GREEN (42 passed). Core commit 113e30b.
- Task 2: complete — original PostgreSQL parser RED (2 failed, 1 passed); fixed full suite with PostgreSQL 46 passed, 1 pre-existing warning. Alembic head unchanged: 9a2f1c0e4b7d.
- Ruling: reuse an isolated clone because native worktree creation failed after prolonged filesystem waits; preserve commits and import the dedicated branch into the original repository if possible. Cost if import fails: review checkout remains at a separate persistent path.
- Ruling: transaction-owned write lock instead of a committed processing lease; no schema changes. Cost: transaction/connection held during parsing; processing progress is not publicly committed.
- Ruling: failed refresh retains ready and canonical data; exception plus log records failure. Cost: no persisted refresh-error history until background integration.
- Ruling: supplied implementation task authorizes completing the written requirements inline without additional plan approval. Final independent review remains required.
