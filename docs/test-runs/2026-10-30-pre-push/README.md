# 2026-10-30 推送前完整后端验证

基线：组员完成测试的 `0112c82`，加本次提交中的本地评估与记录补充。
结果：**224 passed、2 skipped、1 warning，9.09 秒，退出码 0**。

- [pytest 完整逐项日志](pytest-verbose.log)
- [JUnit XML](junit.xml)
- [退出码](exit-code.txt)

从仓库根目录使用 `.venv/bin/python`，工作目录为 `services/api`，执行：

```text
python -m pytest -vv -ra --tb=long --color=no --junitxml=<本目录>/junit.xml
```

仅在测试子进程设置 `DATABASE_URL`、`TEST_POSTGRES_URL` 指向独立
`127.0.0.1:55437/retrieval_test`，并强制 `OPENAI_API_KEY` 为空、
`RUN_LIVE_EMBEDDING_EVAL=0`。环境由 [compose.test.yaml](../../../services/api/compose.test.yaml) 管理，
PostgreSQL 17.11 / pgvector 0.8.7；未更改应用 `.env`。

仅以下两项跳过：

```text
tests/test_course_retrieval_eval.py::test_live_course_benchmark
tests/test_retrieval_eval.py::test_live_model_topic_quality
```

唯一警告为已有 Starlette/AnyIO BlockingPortal 弃用提示。
SQL、迁移、事务与并发测试使用真实 PostgreSQL；embedding 调用使用测试替身。
本次没有生成真实模型的 Recall/MRR 数值，也没有重复调用 Codex 生成实验。
本次未修改前端，因此浏览器 QA 保留组员及此前复核记录，未在本轮重跑。
