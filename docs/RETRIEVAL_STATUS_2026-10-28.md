# CourseMate-AI 当前状态：完整 MRR、模型记录与无 API 使用边界

后续记录（2026-10-29）：已配置独立 PostgreSQL/pgvector 测试环境，并将此前未执行的
59 项非 live 集成测试全部补跑通过，0 失败、0 跳过。两项真实模型测试仍排除。
详细原始日志和环境见 [59 项实际补跑记录](test-runs/2026-10-29-postgres59/README.md)。
下文测试表保留 10 月 28 日当时的历史状态。

日期：2026-10-28，Australia/Adelaide。工作区基于组员最新 `0112c82`，
分支为 `codex/rag-testing-without-api`。本次新增修改只保存在本地，未推送、未合并。
原有未跟踪工程总结与历史结果均保留。

## 已完成的代码变化

| 文件 | 功能与理由 |
| --- | --- |
| `evals/retrieval/evaluate_mit.py` | 用已校验 PDF 创建 Chunk manifest；核对全部 HTTP 返回集合，保存完整排序，补完整 MRR；避免只取得 Top 5 却宣称完整指标 |
| `evals/retrieval/embedding_record.py` | 一个小模块统一加载/校验两种实际来源的模型记录；不导入数据库、parser 或 router，不是 provider 工厂 |
| `evals/retrieval/embedding-configs/openai-small-v1.json` | 显式人工声明模板，不含 key；方便下次 OpenAI 测量，不猜测正在运行的服务模型 |
| `evals/retrieval/local_embeddings.py` | 可选输出本地进程配置 receipt；应用环境初始化后记录实际存储 ID，不覆盖旧记录，不在记录步骤下载模型 |
| `services/api/tests/test_retrieval_evaluation_records.py` | 数学口径、完整性、元数据、安全错误、真实 HTTP CLI 交互及两个独立审查问题的回归 |
| 本状态与运行说明 | 更新参数、测量口径、信任边界及之后有 key 的操作步骤 |

生产 embedding provider、检索 SQL、backfill、parser、API 契约、数据模型及迁移均未修改。
既有 25 题和黄金标签也未修改。没有引入新依赖、本地生成模型、关键词搜索或 RAG。

## 完整 MRR 的定义与保护

MIT 语料仍为五份原件、25 题、46 个实际 Chunk。主指标 `mrr` 是所有问题首次命中
“正确文档/页且含预审证据锚点”的排名倒数平均；未命中贡献零。另提供
`source_page_mrr` 作来源页诊断。锚点仍可能漏判语义等价段落，需人工审查，不能解释为回答正确率。

`--top-k 5` 保留 Top 1/3/5 与 `anchor_mrr_at_5` 诊断，但每题实际请求 47：
46 个期望块，加一个额外探测位置。应只返回全部 46 块。
按文档、页号和原文 SHA-256 比较 multiset，保留重复文本数量；各题 canonical IDs 也需一致。
少块、额外块、替换文本、错误页或中途重建会 blocked，聚合指标为空。

不能只请求期望条数：额外的第 47 块可能藏在截断之后。现有 API 上限为 50，
因此无新增接口时，完整模式最多证明 49 个期望块；50 块及以上明确拒绝，避免漏掉未知尾部。
这是当前小基准的保护，不是为大规模评估实现分页或更改生产限制。

历史 `mit-6006-local-bge-small-run1.json` 只保存 Top 5，原有 MRR@5 为 0.6933。
本次没有把报告文字里的第 9/12/18 名拼进旧 JSON，也没有生成虚假的完整 MRR 数值。
新代码已可测完整指标；真实完整 MRR 尚待下次模型运行。

## 模型版本与记录的信任边界

新结果保存 provider、模型名称、应用 revision、补零前模型输出维度、存储维度、
实际 `storage_config_id`、上游模型版本（未知则 null）、已知运行库版本、记录来源和评估脚本 SHA-256。

OpenAI 模板是 `operator_declared`，需要操作方确认与 API、已回填向量的配置一致。
本地 BGE 可生成 `local_runtime_receipt`，明确其真实 provider 为 fastembed，输出 384 维、
补零后存储 1536 维。为保持兼容，旧存储标识仍原样记录，不假称数据库已有新前缀。
receipt 在 `.env` 加载后生成，避免实际使用 large 配置却记录为默认 small。

两种记录都写明 `verification=not_verified_by_search_api`：现有 HTTP 接口不返回模型身份，
本次没有增加服务端证明接口。模型别名并非不可变快照，应用 revision 也不等于上游版本。
不知道的值留空，不从文件名或当前安装环境倒填历史事实。
未知字段（例如 api_key）、非法维度和不一致 revision 会被拒绝，不把原值输出到错误信息。

## 测试与独立审查

本次先观察到 21 项新测试失败，再实现功能。独立审查发现两个 Important：
完整请求可能隐藏额外尾部块，以及 receipt 早于 `.env` 加载。
新增 3 项回归先复现失败，再修复；没有 Critical 或待处理 Minor。

| 检查 | 当前结果 |
| --- | --- |
| MIT 完整排序 / provenance / 旧 HTTP 评估回归 | **49 passed** |
| 完整默认后端 | **165 passed, 61 skipped, 1 warning**，退出 0；已有 Starlette/AnyIO 弃用警告 |
| PDF 离线校验 | 5 份哈希、25 题证据、46 块 manifest 通过 |
| 真实 HTTP CLI 测试 | 本机临时 HTTP 服务完整走 CLI、序列化、排名及输出；向量/文本为受控测试数据，不作质量指标 |
| PostgreSQL / live 模型 | 本轮未执行；缺少运行中的 Docker/测试库及可用模型 API |
| 无服务时的新 CLI | 退出 2，`blocked`、`metrics=null`、`ranking_complete=false`；保存完整 manifest 和模型声明，不产生质量数据 |

目前没有新增真实模型结果，也没有新真实延迟；新完整排序的延迟不能直接同旧 Top-5 运行比较。
此前本地 BGE 的页命中 68%/88%/96%、锚点命中 56%/80%/88% 仍仅作为历史本地模型基线。
它们不能代替当前生产 OpenAI 配置的测试。

本次 [blocked 记录](../evals/retrieval/results/mit-6006-full-openai-blocked-2026-10-28.json)
故意连接本机无服务端口，验证 CLI 的失败记录；不是对组员原服务或模型可用性的测量。

可维护性自审：

- 没有新增 manager、factory、repository 或插件层；元数据模块解决 HTTP 评估和本地 runner 两个现有入口的记录校验重复。
- manifest 摘要复用原有 parser，不复制切分算法；旧 bounded 诊断保留且不输出完整主 MRR。
- 最长新增/扩展流程 `run` 为 70 行，负责一次评估编排；模型记录校验 37 行，无 provider 或数据库逻辑混入。
- 没有新增 Session 或事务；生产 Chunk/embedding 写入位置仍是既有 parser/backfill。本次仅修改本地评估 JSON 的写入，文件以独占模式创建。
- 文本 hash 及完整集合是严格契约：后端 parser 版本不同、文档不一致会阻止测量，不能静默拿另一份语料算分。
- metadata 不是服务端自动核验、超过 49 块的完整评估未实现、上游模型快照可能未知，均明确披露；没有为这些未来需求预建框架。
- 原三主题及 bounded 评估仍有实际兼容用途；未发现新增死代码。未新增生产状态修改或隐含网络重试。

独立审查未测模型质量、远端模型证明、数据库写入和收费 API；本次仍将这些保持为未验证。
审查时尚未完成的使用文档已在代码修正后补齐，没有用审查通过替代运行证据。

## 提供 API 后怎样继续

本项目现在需要的是 Embeddings API，尚未实现 GPT 生成回答。
OpenAI 官方接口说明：[Create embeddings](https://developers.openai.com/api/reference/resources/embeddings/methods/create)。
之后在 `services/api/.env` 配置 `OPENAI_API_KEY`、模型和 revision，确认 key 可调用 embedding 服务。
默认模板对应以下非秘密参数：

```dotenv
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_REVISION=v1
```

从仓库根目录执行（Windows 将解释器换为实际 `.venv/Scripts/python.exe`）：

```bash
# 先启动专用 PostgreSQL/pgvector 测试库并迁移，运行普通 API。
# 在专用 Course 上传五份原 PDF 后，为该 Course 解析并回填。
.venv/bin/python evals/retrieval/prepare_mit_course.py --course-id COURSE_ID

# 普通 API 保持运行；新文件名，避免覆盖历史证据。
.venv/bin/python evals/retrieval/evaluate_mit.py run \
  --course-id COURSE_ID --api-url http://127.0.0.1:8000 --top-k 5 \
  --embedding-record evals/retrieval/embedding-configs/openai-small-v1.json \
  --output evals/retrieval/results/mit-6006-openai-full-run1.json
```

当前 worktree 的解释器在根目录 `.venv`；其他开发者按自己环境替换。
同一轮应保持 API 和 backfill 的模型/revision 一致，并在模型变化后重嵌入。

## 最终产品没有 AI API 时，是否还能使用

可以，而且基础离线操作不需要部署开源大模型。建议区分三个能力层级：

| 层级 | 无 AI API 是否可行 | 当前状态 |
| --- | --- | --- |
| 课程管理、PDF 上传、解析与分块 | 可以，后端和数据库仍需可用 | 已有；当前分支上传不自动解析，需要现有准备/处理入口 |
| 文档文本浏览、关键词定位 | 可以，不需要模型 | 可后续增加；目前没有产品化的关键词检索降级流程 |
| 跨问法语义检索、自动总结与问答 | 依赖相应 embedding / 生成能力 | 现有语义检索依赖 API 或可选本地 BGE；生成层尚未实现 |

不安装本地模型也可以做一个有用的离线资料管理与关键词查询模式，难度主要在界面状态、
搜索入口和降级提示。它不会提供与语义检索相同的理解能力。已有云端文档向量也不能
直接让新问题离线做向量检索，因为查询本身仍需兼容的 embedding。

因此建议后续目标是“无 API 保留资料操作，有 API 开启 AI 功能”，无需把本地大模型部署
变成使用门槛。本次仅记录这一产品方向，没有提前添加关键词搜索、reranker、hybrid 或生成层。
