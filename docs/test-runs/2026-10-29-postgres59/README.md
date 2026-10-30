# PostgreSQL / pgvector：59 项补跑记录

**实测结果：59 passed、0 failed、0 errors、0 skipped，退出码 0。**
执行于 2026-10-29 01:37:29–01:37:35（Australia/Adelaide，ACDT）；
pytest 耗时 5.86 秒。JSON 和 JUnit 的原始时间为 UTC，因此显示 2026-10-28。
这是实际运行输出，不是由测试源码推算的通过记录。

## 直接查看证据

- [完整 pytest 逐项日志](pytest-verbose.log)：`-vv -ra --tb=long`，每个选择的用例及结果、全部警告。
- [59 项逐项结果与耗时](cases.md)：从本次 JUnit 生成，便于人工阅读。
- [JUnit XML](junit.xml)：本次 59 个 testcase 的机器可读结果。
- [运行汇总](summary.json)：通过/失败/跳过、退出码和未使用真实 embedding 的标记。
- [实际选择与排除清单](selection.json)：59 个完整 node ID，以及两项明确排除的 live 测试。
- [环境与实际 pytest 参数](environment.json)：Python、依赖、数据库版本、源码基线及执行参数。
- [源代码 SHA-256](source-sha256.json)：app、tests、Alembic 的运行源码指纹；HEAD 为 `0112c82`，工作区包含此前未提交修改。
- [测试后数据库检查](post-test-db-check.txt)：临时 schema 和 public 应用表数量均为 0。
- [容器状态](container-after.json)、[镜像 digest](image-digests.json)、[退出码](exit-code.txt)。

原始汇总：

```text
collected 109 items / 50 deselected / 59 selected
59 passed, 50 deselected, 2 warnings in 5.86s
```

50 项 deselected 包含两项真实模型测试与这七个文件中的 48 项非 PostgreSQL 用例；
它们没有执行，不是失败或跳过。本次只补跑此前缺测试库而未执行的 59 项，没有重跑完整后端套件。

## 59 项覆盖分布

| 文件 | 实际通过数 | 内容 |
| --- | ---: | --- |
| `test_retrieval_postgres.py` | 22 | vector 存储/维度/配对约束、排序、top-k、课程范围、共享 Content、去重、配置与 Session、Content 写锁 |
| `test_embedding_backfill.py` | 18 | PostgreSQL 分支的回填持久化、跳过、强制/版本更新、原子回滚、Session 所有权、CLI |
| `test_retrieval_api.py` | 5 | 真正 pgvector 查询结果、默认 top-k、输入清洗、安全 503、极大/极小向量的有限分数 |
| `test_processing_postgres.py` | 4 | PDF 处理并发、失败保留旧数据、成功替换、约束回滚 |
| `test_retrieval_migrations.py` | 1 | 旧 head 升级、旧数据保留、vector 扩展/类型、Alembic check、降级再升级 |
| `test_retrieval_eval.py` | 4 | 三主题几何控制、同分不能算语义成功、成功/失败时 schema 清理 |
| `test_course_retrieval_eval.py` | 5 | 完整排名证据、成功/失败清理、H02/H03 等价黄金证据 |
| **合计** | **59** | |

两个 live 用例在收集阶段明确排除：

```text
tests/test_retrieval_eval.py::test_live_model_topic_quality
tests/test_course_retrieval_eval.py::test_live_course_benchmark
```

测试过程使用受控 embedding 向量，但存储、SQL 相似度、迁移和锁都在真实 PostgreSQL/pgvector 上执行。
`OPENAI_API_KEY` 在测试子进程中被强制置空，`RUN_LIVE_EMBEDDING_EVAL=0`；
另在现有 provider 使用的 httpx POST 边界禁止 `api.openai.com` 请求。
阻止到的请求数也为 0。本轮没有真实模型推理，不产生新的 Recall/MRR 质量结论。

两项警告原样保留，没有屏蔽：pytest 提示 AnyIO 已导入、不能重新做断言重写；
已有 Starlette/AnyIO BlockingPortal 弃用提示。它们没有导致测试失败。

## 独立测试环境

配置：[services/api/compose.test.yaml](../../../services/api/compose.test.yaml)。

| 配置 | 值 |
| --- | --- |
| PostgreSQL | 17.11 |
| pgvector 服务端扩展 | 0.8.7 |
| Python pgvector 客户端 | 0.4.2 |
| Python / pytest | 3.12.14 / 8.3.4 |
| Compose 项目 | `coursemate-retrieval-test` |
| 测试容器 | `coursemate-retrieval-test-postgres-1`，已保留运行且 healthy |
| 绑定地址 | `127.0.0.1:55437` |
| 测试数据库 / 用户 | `retrieval_test` / `retrieval_test` |
| 专用测试 volume | `coursemate-retrieval-test_pgvector_test_data` |

镜像使用已记录的不可变 digest。应用容器的 5432 端口、应用 volume 和本地 `.env` 均未改动。
测试只使用此新数据库；应用 `DATABASE_URL` 的替换仅在测试子进程内生效。
pytest fixture 为每项创建随机 schema 并清理；验证结束后无临时 schema 或 public 应用表残留。

从仓库根目录管理环境：

```bash
# 启动/等待健康
docker compose -f services/api/compose.test.yaml up -d --wait

# 查看状态
docker compose -f services/api/compose.test.yaml ps

# 暂停测试容器，保留测试 volume
docker compose -f services/api/compose.test.yaml stop
```

仅用于此本地测试环境的连接串：

```text
postgresql+psycopg://retrieval_test:retrieval_test_local_only@127.0.0.1:55437/retrieval_test
```

## 这次实际如何执行

从仓库根目录运行工作树已有 `.venv`：

```bash
.venv/bin/python docs/test-runs/2026-10-29-postgres59/run_postgres59.py \
  > docs/test-runs/2026-10-29-postgres59/pytest-verbose.log 2>&1
```

该次运行脚本在收集后按 `postgres_factory`、动态 PostgreSQL fixture 参数和迁移用例选择，
要求恰好 59 项并检查两个 live 用例均排除；否则直接报错。具体 pytest 参数见 environment.json。
脚本拒绝覆盖已有 JUnit/汇总。后续重跑应复制脚本到同级新日期/批次目录，保留本次原始证据。

这次只新增测试环境配置、运行证据和文档，没有修改生产代码或测试断言，没有提交、推送或合并。
真实模型测试继续等待提供可用 key 后单独执行。
