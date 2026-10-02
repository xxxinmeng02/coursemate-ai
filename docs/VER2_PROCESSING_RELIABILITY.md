# Ver2 PDF 处理可靠性工程报告

日期：2026 年 10 月 2 日。基线：`ver2` / `82a11060dbb264b7074ea1769b9ab65a3cf2418e`。
修复分支：`fix/ver2-processing-reliability`。本次未接入上传自动处理，未新增队列、AI 功能或数据库字段。

## 1. 检查与根因

修改前检查了 Content、Chunk、上传路由、数据库会话、解析函数、解析测试和两份现有迁移。后端基线重新运行得到 **33 passed, 1 warning**。

原函数先设置 `processing`、删除全部旧分块并提交，然后才解析文件。解析或写入失败后，它再次按 `content_id` 删除分块，设置 `failed` 并提交。

- **问题 A：并发处理。** 两个处理会话没有数据库所有权保护；一个失败会话可以删除另一个会话已提交的结果。最小交错复现得到 `failed`、0 个分块。
- **问题 B：失败刷新。** 原分块已经在解析前永久删除，新解析失败无法回滚早先的提交。已有 `ready` 内容刷新失败的复现同样得到 `failed`、0 个分块。

## 2. 设计选择

保留 `process_content(db, content)` 接口，使用一个外层数据库事务持有内容记录的写锁：

```sql
UPDATE contents
SET status = contents.status
WHERE id = :content_id
RETURNING ...;
```

这是不改变业务状态的 UPDATE，但 PostgreSQL 会对相应行加写锁，直到外层事务结束。同一内容的另一个处理任务会等待；SQLite 使用写锁，范围是数据库而非单行。RETURNING 同时读取锁内的最新数据，配合 `populate_existing` 刷新过期的 ORM 对象，避免用旧的 `uploaded` 状态覆盖刚完成的 `ready` 结果。

选择这种机制的原因：不需要 attempt ID、租约、新迁移或分布式任务框架；避免仅用 SQLite 会忽略的 `SELECT FOR UPDATE`；锁由事务和连接生命周期管理，不需要手工清除处理所有权。

代价是解析期间持有事务及连接，竞争任务会等待，而不会立即返回“正在处理”。不同内容在 PostgreSQL 上可使用不同的行锁；SQLite 的并发写入能力更有限。锁等待和解析超时应由后续运行环境配置，本次未增加超时框架。

`ready` 表示当前已有可用的规范分块，不表示最近一次刷新一定成功。刷新失败保留 `ready`，同时抛出带原始原因的 `ContentProcessingError` 并记录带内容 ID 的异常日志。没有增加持久化错误历史；现有模式足以表达可用性，后台任务的错误展示属于后续集成工作。

## 3. 事务生命周期

### 成功路径

```text
SQLAlchemy 自动开启外层事务（或沿用专用会话的读取事务）
  → no-op UPDATE 获取内容写锁并刷新状态
  → 校验 uploaded / failed / ready
  → SAVEPOINT
      → processing（只在当前事务内）
      → 提取文本、规范化、准备全部新分块
      → DELETE 旧分块
      → INSERT 完整新分块集
      → ready
      → flush
  → RELEASE SAVEPOINT（不是 COMMIT，锁仍保留）
  → COMMIT 外层事务（成功处理唯一的一次提交）
```

旧分块在新文本全部准备完成前不会删除。删除、插入和 `ready` 更新处于同一事务中。其他 PostgreSQL 读取会话在提交前看到旧的已提交状态及数据；提交后看到完整的新版本，不能看到半套新分块。

### 解析或 flush 失败

```text
ROLLBACK TO SAVEPOINT
  → 原分块恢复，内容写锁仍属于当前外层事务
  → 原状态是 ready：保持 ready
  → 原状态是 uploaded / failed：设置 failed
  → COMMIT 一致的最终状态
  → 日志 + ContentProcessingError
```

保存点回滚保护已提交的规范数据，并清除本次尝试的插入。失败处理不再执行任何“删除全部分块”的清理。

### 锁获取或最终提交失败

```text
ROLLBACK 外层事务
  → 不进行第二个无锁清理或状态写入
  → ContentProcessingError
```

提交前失败时，之前提交的数据和状态保持不变。若连接在服务器已提交但客户端尚未收到确认时断开，结果可能不确定；事务仍保持整体原子性，调用方应通过新会话重新读取状态，不得假定失败就删除数据。

### 对外可见状态与重试

| 初始状态 | 尝试成功 | 解析／flush 失败 | 外层提交前失败 |
| --- | --- | --- | --- |
| `uploaded` | `ready` + 新分块 | `failed` | 原 `uploaded` 保留 |
| `failed` | `ready` + 新分块 | `failed` | 原 `failed` 保留 |
| `ready` | `ready` + 原子替换后的分块 | `ready` + 原分块 | 原 `ready` 和分块保留 |
| 已提交的 `processing` | 拒绝处理 | 状态不变 | 状态不变 |
| `pending_cleanup` | 拒绝处理 | 状态不变 | 状态不变 |

新函数的 `processing` 是事务内状态，**不会提交给前端作为处理进度**。读者在首次处理期间仍看到 `uploaded`，刷新期间仍看到旧的 `ready`；处理完成后再看到最终状态。

进程中断或连接关闭时，未提交的状态和分块变更回滚，数据库释放锁。不会因为本实现先提交 `processing` 而产生永久挂起记录。旧实现或其他写入者留下的已提交 `processing` 必须核查真实任务和分块，再明确修复状态；不能仅按时间猜测任务失效并抢占。

## 4. 主要修改及对应证据

| 问题 | 根因 | 修复与理由 | 验证测试 |
| --- | --- | --- | --- |
| 失败任务删除其他任务成果 | 没有所有权；失败后全量清理 | 写锁贯穿处理；失败不删除规范分块 | `test_postgres_waiting_failed_attempt_preserves_winner`、`test_competing_connection_cannot_extract_while_owner_is_active` |
| 旧 ORM 状态覆盖新成果 | 锁外缓存可能仍是 uploaded | RETURNING 在锁内刷新状态 | `test_stale_failed_attempt_preserves_latest_success` |
| 刷新失败丢失旧数据 | 解析前删除并提交 | 新数据准备完毕后事务内替换，保存点失败回滚 | `test_failed_refresh_preserves_ready_chunks` |
| 替换中途持久化失败 | 删除和插入分开提交 | 删除、插入与状态使用同一事务 | `test_failed_replacement_rolls_back_old_chunks`、`test_postgres_constraint_failure_rolls_back_replacement` |
| 规范分块重复或残留 | 重试需要完整替换 | 原子替换，连续 chunk_index | `test_successful_refresh_replaces_complete_canonical_set`、`test_postgres_successful_refresh_is_canonical` |
| 提交失败后继续无锁清理 | 回滚后再次删除、更新 | 外层提交失败仅回滚并报错 | `test_final_commit_failure_preserves_previous_data` |
| 意外处理清理中或已标记处理中的记录 | 没有状态准入校验 | 在锁内限制可处理状态 | `test_ineligible_content_is_not_processed` |
| 意外提交调用方未保存的 ORM 修改 | 处理函数拥有 commit | 拒绝 new / dirty / deleted 对象及调用方保存点 | `test_processing_does_not_commit_unrelated_pending_changes` |

处理函数必须使用专用会话。待提交 ORM 对象的检查是一道防护，不能识别调用方此前已 flush 的所有业务写入；因此不得将它用于含无关未提交业务操作的会话。后台执行时应创建新的 Session，按内容 ID 重新读取对象，并在结束时关闭会话。

## 5. 测试结果

### RED → GREEN

- SQLite 回归测试在原实现上得到 **7 failed, 10 passed**，失败原因符合预期：旧分块丢失、没有互斥、状态和会话边界未受保护。成功替换及部分已有安全行为在基线上已通过。
- 首批 3 个 PostgreSQL 测试在独立副本的原解析实现上得到 **2 failed, 1 passed**，分别证实没有处理锁和刷新失败丢失旧数据。
- 修复后，SQLite 后端套件为 **42 passed, 1 warning**。
- 启用 PostgreSQL 检查后的完整套件为 **46 passed, 1 warning**。

基线为 33 项测试；新增 9 个 SQLite 测试用例（其中状态测试参数化为 2 个）及 4 个 PostgreSQL 检查。原有重试和持久化失败测试也更新以对应新事务边界。

### PostgreSQL 检查范围

本次实际使用隔离的 PostgreSQL 17 容器。每个集成测试建立随机临时 schema，并在结束时删除；没有使用或改动用户现有的课程数据库。

四个 PostgreSQL 检查分别验证：真实双会话写锁等待与过期失败任务、已执行 INSERT 后的失败回滚、成功刷新规范分块，以及实际 `23505` 唯一约束错误后保存点恢复。并发检查用事件协调，并查询 `pg_stat_activity` 的 Lock 等待状态，不依赖猜测任务完成时间。

默认命令不要求 PostgreSQL；没有 `TEST_POSTGRES_URL` 时四项集成检查明确跳过：

```bash
cd services/api
python -m pytest -q
```

需要真实 PostgreSQL 检查时：

```bash
TEST_POSTGRES_URL='postgresql+psycopg://USER:PASSWORD@HOST:PORT/TEST_DB' \
  python -m pytest -q
```

测试账号需能创建和删除 schema。应使用独立测试库。

现有唯一警告来自 Starlette TestClient 使用 AnyIO 的弃用接口；本次不扩展依赖升级范围。

### 迁移

没有修改模型和 Alembic 迁移，**不需要新迁移**。`alembic heads` 仍为 `9a2f1c0e4b7d (head)`。此次检查的是迁移目录状态，没有声称已经重新验证完整迁移部署流程。

## 6. 上传集成准备

### 6.1 自动解析应何时触发

在 `upload_document` 成功执行 `db.commit()`、内容与文档关联已持久化之后，再以 `content_id` 提交处理任务。不得在 commit 前启动，不得在 `finally` 中无条件触发，也不得把后台解析失败解释为已经成功的上传事务失败。

上传事务成功、但任务提交失败时，保留文件和 `uploaded` 状态，让后续恢复逻辑重新调度。直接在请求结束后启动内存任务无法保证服务重启后任务不丢失；下一阶段需要明确这一恢复策略。

### 6.2 已有共享 Content 是否需要重解析

| 状态 | 建议的自动集成行为 |
| --- | --- |
| `uploaded` | 调度首次解析，按内容 ID 去重；不能只按文档 ID 去重 |
| `processing` | 不再次调度；对于已提交的旧记录，核查任务和历史数据后再恢复 |
| `ready` | 复用已有分块，不因新增课程关联而重解析；用户显式刷新才替换 |
| `failed` | 允许明确的重试；错误输入需先提示用户处理，避免无限循环 |
| `pending_cleanup` | 不调度；先协调清理与重新引用的生命周期 |

当前 `process_content` 支持对 `ready` 的显式刷新，因此重复排队的任务可能在锁后依次解析。后续自动集成应在**相同的锁内**增加“ready 则跳过”的调度语义；仅在入队或获取锁前检查状态不能完全避免重复工作。这不是本次已实现的自动调度功能。

### 6.3 重试和后台会话

重试使用新的专用数据库会话，重新加载内容并通过同样的处理锁。成功替换整个规范集合；失败保留旧的可用成果。对数据库或提交错误，应先读取最终状态，再决定是否重试。

**不得向后台任务传递请求作用域 Session 或 ORM 对象。** 只传递内容 ID，后台任务通过 `get_session_factory()` 创建、关闭自己的 Session。请求会话可能已关闭，也不能跨线程共用。上传接口本次没有改变，不新增任务框架。

## 7. 剩余边界与下一步

- SQLite 的普通内存测试验证数据和状态，不验证 PostgreSQL 行锁；文件型 SQLite 和实际 PostgreSQL 测试分别覆盖其竞争行为。
- PostgreSQL 测试覆盖正常隔离配置下的两个会话，未覆盖高并发压力、死锁、数据库故障切换、网络中断时的提交结果不确定性或所有隔离级别。
- 事务锁会持有连接直到解析结束。后续应配置处理与锁等待超时，并评估真实课件的耗时和资源使用。
- 本次仍没有持久化任务进度、失败历史和后台任务恢复机制；不能声称前端已经能看到 processing 进度。
- 所有处理写入者必须遵守该事务协议。后续清理、重新引用及解析任务应协调内容写锁，不能由其他路径直接覆盖状态或删除分块。
- 上传自身的并发去重、共享内容垃圾回收及单文档删除不属于本次修复；下一阶段不应把这些已有边界视为已解决。

现有解析函数已经解决本任务发现的成果破坏与失败刷新问题，可以作为下一阶段 **“上传 → 自动 PDF 处理 → 前端状态刷新”** 的基础。自动集成仍需补上提交后调度、锁内跳过 ready、专用会话、任务恢复及前端状态语义。无需先实施 embeddings 或 RAG。
