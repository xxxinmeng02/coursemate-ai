# Retrieval Evaluation — 2026-10-11

**结论：评估 harness 已完成；真实模型评估 blocked。不能据本次测试宣称检索质量已验证。**
分支 `codex/rag-retrieval-foundation`，起点 `813e4ea`；不合并 main。

## 数据集与问题

[parallel_computing.json](../evals/retrieval/parallel_computing.json) 是本次编写的“并行计算基础”测试课程，
扩展项目已有 parallel-programming 主题，并非真实大学课件或独立收集的学生问题。
四份讲义、12 个明确的逻辑页，复用现有分块器生成 **24 个 canonical Chunks**。
Chunk 长度 458–1197 字符；目标 1200、重叠 200，不跨页。
这次评估针对已提取的页文本，不评估 PDF 提取/OCR/图片中的内容。

| 讲义 | 页数 / Chunks | 问题数 |
| --- | --- | --- |
| 01-performance-notes.txt：性能、Amdahl、扩展性 | 3 / 6 | 7 |
| 02-shared-memory-notes.txt：竞争、同步、调度、缓存 | 3 / 6 | 5 |
| 03-message-passing-notes.txt：MPI、集合通信、通信成本 | 3 / 6 | 7 |
| 04-decomposition-notes.txt：任务图、halo、流水线、数值结果 | 3 / 6 | 6 |

共 **25 题**：事实、改写、术语、概念比较、较难语义问题各 5 题。
每题预先固定 question、expected document/page/topic 和证据段落；
完整[人工审阅题目表](../evals/retrieval/README.md#question-catalogue)与数据一致。
标签校验确认所有证据都能定位到具体 Chunk，问题没有直接复制来源完整句子。

## 实测指标与延迟

| 指标 | 本次真实模型结果 |
| --- | --- |
| Recall@1 | 未测量（blocked） |
| Recall@3 | 未测量（blocked） |
| Recall@5 | 未测量（blocked） |
| MRR | 未测量（blocked） |
| 延迟 mean / median / p95 | 未测量（blocked） |

原因：执行环境和项目 `.env` 均未配置 `OPENAI_API_KEY`。
实际命令生成了[blocked JSON 记录](../evals/retrieval/results/parallel-computing-v2-blocked-2026-10-11.json)，
退出码 **2**；`real_embeddings_used=false`，所有指标为 null，结果为空，没有调用真实 provider。
数据集 SHA-256：`c7d55c6273de37b6f0d272d1a0d15752c10b8d11b9c8a3dc1113fd3b9491f3a0`。
回归测试的合成向量只验证评估计算与 pgvector 查询，不能当作上述真实指标。

指标口径：每题只有一个黄金来源证据单元，同页包含主证据或预先审阅的等价证据的 Chunk 都是可接受选择，重叠不会增加分母。
Recall@K 是至少命中一个可接受 Chunk 的问题比例，也即该单证据定义下的 source Hit Rate@K；
不是对所有潜在相关段落计数。同一文档的无关页/段落不算命中。
MRR 使用完整课程排序的首个相关名次，未命中为零，不截断为 MRR@5。
本夹具一次调用 `search_course(..., top_k=24)`，Top 1/3/5 是该排序的前缀。
现有精确 SQL 排序保证前缀一致；没有引入分数阈值。
延迟覆盖 query embedding 网络调用及 SQL，不包含 backfill、seed 或 HTTP 路由开销。
由于排序取完整 24 条，不能直接当作生产 API top-k=5 的延迟基准。

## 代表查询与失败检查

**真实成功查询：尚无结果可报告。真实失败/弱查询：尚无结果可报告。**
没有将测试 double 的成功或失败包装成真实模型表现。
以下是预先选定、等待实测检查的代表问题，不代表已经成功：

| ID | 问题含义 | 黄金来源 |
| --- | --- | --- |
| F02 | 固定任务有十分之一只能串行，理想加速上限是多少？ | performance / p2：Amdahl limit |
| P04 | 所有机器通过 rendezvous 后时间戳仍不同，计时假设错在哪里？ | message-passing / p3：barrier 与时钟 |
| C02 | 等待所有线程完成一阶段，与保护共享更新有何不同？ | shared-memory / p2：barrier 与 mutex |
| H03 | 每个 solver worker 都需要全局最大误差，为什么只 gather 不够？ | message-passing / p2：all-reduce |
| H05 | 无数据竞争却出现求和末位差异，应先检查什么？ | decomposition / p3：浮点组合次序 |

真实运行后，JSON 保存每题实际 Top 5 的**完整 Chunk 文本、分数、页/文档、rank**，
以及完整 ranked Chunk IDs、expected Chunk IDs 和相关 Chunk 的实际全文/名次（包括第 5 名以后）。
`top_1`、`weak_top_5`、`miss_at_5` 区分第一名成功、2–5 名较弱与 Top 5 未命中。
这些记录连同 chunk manifest 可用于展示代表性失败，不能只凭低分认定模型原因。

待检查原因包括：边界上下文丢失、问法/术语错配、弱 embedding 相似度、
重复/共享 Content、score 转换、top-k 和 Course 过滤，另需排除黄金标签遗漏。
[审阅流程](../evals/retrieval/README.md#inspect-weak-and-failed-results)列出各类所需证据。
本次没有实测失败，故不对这些原因作归因。
既有 PG 回归继续验证课程隔离、共享内容、去重、score 与 top-k 正确性。

## 调优与代码变化

**没有进行检索调优，也没有 before/after 质量指标。**
embedding provider、检索 SQL、backfill、路由、模型、迁移、分块大小与重叠均未改动。
只扩展 `app/retrieval_eval.py`，增加课程数据、指标与证据输出，并共用临时 schema 生命周期。
保留原三主题评估入口。新增 pytest 覆盖标签、指标分母、完整 MRR、第 6 名结果、
实际 passage 输出、缺密钥/配置、成功和失败后的清理。
没有新依赖、后台系统、RAG、chat、citations、reranker 或 hybrid search。

独立审查发现黄金标签遗漏：H02 的锁顺序案例、H03 的 gather 解释分别还有一个完整回答段落，
原标签会误判为无关。已在真实测量前添加 `alternative_evidence` 并将数据集升为 **v2**；
原主证据、课程文本、问法、单证据分母与指标计算不变。
回归测试先复现 3 项失败，再确认两个回答段落能计为命中，而无关文档/页/段落仍被排除；
另验证错误的 alternative 字段类型不会按字符匹配。没有使用任何真实模型排名来修改标签。
保留[原 v1 blocked 记录](../evals/retrieval/results/parallel-computing-v1-blocked-2026-10-11.json)，
并验证从 v2 去掉两处 alternatives、还原 ID 后可重建其原始哈希。

所有数据库写入只发生在 CLI 创建的隔离 schema；每 Content 的 embedding 事务仍由现有 backfill 管理。
Session 创建/关闭归评估入口；检索继续使用调用方 Session。
共享的 schema context manager 仅统一两个实际评估入口的资源清理，没有引入通用评估框架。

## 验证

从 worktree 的 `services/api` 运行 `.venv`（路径为 `../../.venv/bin/python`）。
PG 使用本次独立 disposable 容器，PostgreSQL **17.11** / pgvector **0.8.7**，未改用户的现有数据库。

| 检查 | 最终结果 |
| --- | --- |
| 完整默认后端 `python -m pytest -q` | **116 passed, 61 skipped, 1 warning** |
| 启用 TEST_POSTGRES_URL 的完整后端 | **175 passed, 2 skipped, 1 warning** |
| 既有 PG retrieval + migrations | **23 passed**；完整 suite 再次覆盖 |
| 真实模型 benchmark CLI | blocked，退出 2，指标 null |
| `git diff --check` | 通过 |

PG 完整运行唯一两项跳过是旧三主题与新课程的 live embedding 评估。
默认运行跳过 PostgreSQL/live 项。唯一警告仍为已有 Starlette/AnyIO BlockingPortal 弃用。
新功能首轮 RED 为 **14 failed, 1 skipped**（PG）；实现后通过。
独立审查的标签修正先复现 **3 failed**，修正后本轮完整套件通过。
额外字段类型检查也先复现失败再修复。

本次独立审查没有 Critical 或 Minor；Important 标签遗漏已回归修正。
reviewer 未评判的模型质量/失败原因/调优收益保持未知；作者编写的语料和逻辑页边界已披露；
未改动的生产模块由现有回归验证；大规模性能没有由 24 个 Chunk 推断。
原先报告中的验证占位已替换为实测结果。

## 文件清单

| 文件 | 变化 |
| --- | --- |
| `evals/retrieval/parallel_computing.json` | 四份测试讲义、25 题、来源标签和 v2 等价证据 |
| `evals/retrieval/README.md` | 人工审阅题目表、指标口径、失败检查步骤与复现命令 |
| `evals/retrieval/results/parallel-computing-v1-blocked-2026-10-11.json` | 初始标签版本的真实 blocked 运行记录 |
| `evals/retrieval/results/parallel-computing-v2-blocked-2026-10-11.json` | 审查修正版本的真实 blocked 运行记录 |
| `services/api/app/retrieval_eval.py` | 扩展既有 CLI、标签/指标、实际 Chunk 证据、schema 生命周期 |
| `services/api/tests/test_course_retrieval_eval.py` | 20 项参数展开测试，包括 live opt-in 检查 |
| `services/api/README.md` | 新 benchmark 命令与报告链接 |
| `docs/RETRIEVAL_EVALUATION.md` | 本报告 |

## 建议与复现

按请求中的二选一，当前归入 **needs retrieval tuning first**，即暂缓 RAG generation。
准确含义是“先补真实 embedding 评估，再据证据决定调优”，不是已经确认检索实现需要修改。
即使这 25 题实测表现良好，也仍需真实课程与独立学生问法的验证，不能从共同编写的夹具推广到所有课程。

配置密钥后，从 `services/api` 运行：

```bash
TEST_POSTGRES_URL='postgresql+psycopg://USER:PASSWORD@HOST:PORT/TEST_DB' \
  python -m app.retrieval_eval --benchmark \
  --output ../../evals/retrieval/results/parallel-computing-v2-live.json
```

保留本次 blocked 记录与数据集版本。测量完成的退出 0 不代表质量验收；
逐项查看真实失败证据，再决定是否存在可小幅修正的正确性问题。
