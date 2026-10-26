# 真实课程 retrieval 测试交接

## 仓库检查与本次范围

2026-10-21 获取了所有远程分支。工作基线为
`codex/rag-testing-without-api` 的 `eaccba0`（10 月 11 日）。
该分支已经具备 embedding provider、pgvector 存储、embedding backfill、
`POST /courses/{course_id}/search` 和原有 authored 课程评估。

其他分支的状态：

- `main`：`4d03922`，9 月 16 日合并 ver1 前端集成。
- `ver2`：`259609e`，10 月 2 日的 PDF 解析、分块和处理事务可靠性。
- `feature/v1.1-document-processing`：`d4b2f9e`，10 月 4 日的自动处理、
  状态轮询、重试与 document 生命周期；它不是 retrieval 分支的祖先。
- `codex/rag-testing-without-api`：在 ver2 上开发检索基础。
  原有 `parallel_computing.json` 是 authored TXT/逻辑页，不是真实 PDF，
  所以本次独立增加 MIT 课程，不替换或重标原测试。

本次只增加课程测试资料、评估辅助工具和 Course 详情页的调试面板。
没有修改 embedding、embedding backfill、pgvector 模型/迁移、SQL 排序、
PDF 解析器、search 路由，也没有合并其他分支或接入 LLM。

## 交付物

- [25 道题目与中文核对表](../evals/retrieval/MIT_6006_QUESTIONS.md)
- [机器可读标签](../evals/retrieval/mit_6006.json)
- [原始 PDF 下载器](../evals/retrieval/download_mit_sources.py)
- [专用 Course 解析与 embedding 准备](../evals/retrieval/prepare_mit_course.py)
- [离线校验及 HTTP 批量评估](../evals/retrieval/evaluate_mit.py)
- [本次 PDF 标签校验记录](../evals/retrieval/results/mit-6006-source-validation-2026-10-21.json)

课程为 MIT OCW 6.006（Spring 2020），5 份真实 PDF、25 道项目编写的自然问法。
问题不是课件句子的逐字复制，也不声称由学生采样而来。
英文查询配英文资料；中文答案要点仅供审查，不测跨语言检索。
本次只覆盖选定五讲，不能代表整门课程或所有课程。

页码从 PDF 实际第 1 页开始，末尾 OCW 署名页也计入总页数。
所有标签在真实检索测量前固定；记录 PDF SHA-256 防止资料版本变化。
PDF 在 MIT 下载、本地忽略，仓库不再分发；保留 MIT、三位讲师和许可归属。

## 1. 下载与离线核对（无需 key / 数据库）

从仓库根目录执行。Windows 使用已经安装 API requirements 的虚拟环境：

```powershell
services/api/.venv/Scripts/python.exe evals/retrieval/download_mit_sources.py
services/api/.venv/Scripts/python.exe evals/retrieval/evaluate_mit.py validate
```

macOS/Linux 将解释器改为 `services/api/.venv/bin/python`。
首次使用按 API README 安装依赖。PDF 保存至 `evals/retrieval/sources/`；
下载器保留已有文件，且拒绝校验值不符的文件。该子目录不是项目镜像的只读
`sources/`，而是新建的本地评估缓存。

当前解析和分块器从 5 份原件生成 **46 个 chunk**。已检查 25 题及替代证据的
锚点落在标注页和至少一个实际 chunk 内。这证明标签可定位，不证明检索准确。

## 2. 准备专用测试 Course

先按 API README 启动独立的本地 PostgreSQL/pgvector 测试库并运行迁移。
设置 `DATABASE_URL`、`OPENAI_API_KEY`、模型及 revision；密钥不写入前端或 Git。
打开前端新建专用 Course，将下载的五份 PDF 按原下载文件名上传。
记录 Course ID，避免混入其他材料。

**此分支的上传只保存文件；不会自动解析或生成 embedding。**
本次没有移植 v1.1 的自动处理代码，而是提供只作用于专用 Course 的准备脚本。
从仓库根目录执行（替换 Course ID）：

```powershell
services/api/.venv/Scripts/python.exe evals/retrieval/prepare_mit_course.py --course-id 1
```

脚本先校验该 Course 恰好包含五份基准 PDF 且 SHA-256 一致，然后对未 ready 的
Content 调用现有 `process_content` 解析，再对每个 Content 调用现有
`embed_content` 生成 embedding（已有当前配置的有效向量会跳过）。
它不修改其他 Course 或 Content。只想先检查解析时加 `--parse-only`，不调用
embedding 服务。退出 2 表示 Course 材料不符；退出 1 表示解析或 embedding 失败
（例如未设置 `OPENAI_API_KEY`）。正常时每行显示 `status=ready`，五份合计 46 个 chunk。

该步骤会向配置的 embedding 服务发送公开课件文本。

## 3. 批量测量

保持 API 运行，从仓库根目录执行（替换 Course ID）：

```powershell
services/api/.venv/Scripts/python.exe evals/retrieval/evaluate_mit.py run --course-id 123 --top-k 5 --output evals/retrieval/results/mit-6006-live-run1.json
```

工具先校验本地 PDF，再用 GET 检查专用 Course 的五个文件名和 ready 状态，
随后逐题调用现有 POST search 接口。它不写数据库、不生成文档 embedding；
后端每题可能调用一次收费的 query embedding。需要使用刚校验的五份 PDF 上传，
因为 HTTP summary 不暴露文件 hash，单靠返回的文件名不能证明远端内容相同。

报告保留原问题、期望页、全部返回原文、score、实际名次和 HTTP 搜索延迟。
已有输出文件不会被覆盖。退出 2 / `status=blocked` 表示配置、服务、材料或请求错误；
部分成功结果会保留，但聚合指标保持 null。退出 0 表示测量完成，
**不表示检索质量已经通过验收**。

指标分开记录：

- `source_page_hit_at_1/3/5`：结果是否命中一组已标注的文件和页码。
- `anchor_hit_at_1/3/5`：同一正确来源页的 chunk 是否还包含短证据锚点。
- `anchor_mrr_at_K`：第一次锚点命中的倒数名次，截断到请求的 K；
  它不是 full-corpus MRR，也不是答案正确率。

一个问题对应一个证据单元，显式 alternative source 视为等价来源；多个重叠 chunk
不会增加分母。页码命中不足以证明段落正确，短锚点命中也可能缺乏完整回答上下文。
必须人工对照题表和 PDF。没有命中锚点的回答型段落可能是假阴性，先人工判断，
有依据的标签修改要提升版本，不能看了分数再任意放宽标签。
不得将这些定位指标称为所有相关 chunk 的 Recall。

API 无结果时先检查解析、Content ready、backfill 和 embedding 配置匹配。
它不等于学生问题无法回答；本工具将空候选情况记为 blocked。
对完整但名次不佳的运行，检查真实 Top K、分块边界、证据位置及其他相似章节，
保留实际例子后再判断是否需要调优。cosine score 不是答案置信度，不加臆测阈值。

## 4. Course 页调试面板

进入任意 Course 详情，展开 Documents 下的 **Retrieval debug**。
输入问题，选 Top K，点击 **Search passages**。每条结果显示：

- 排名、PDF 名和实际页码（null 显示 unavailable）
- chunk ID、document ID、cosine score 和完整文本

面板按 API 原始顺序显示，不做 rerank、拼答案或调用 LLM。
显示 loading、空结果、网络失败、404/422/503 错误；切换课程时丢弃旧查询状态。

## 本次验证与测量边界

- 五份原始 PDF 的 hash、页数、所有证据定位通过离线校验，46 个实际 chunk。
- 后端回归：137 passed、61 skipped。跳过项需要 PostgreSQL / live embedding。
- 前端 API 传输测试：6 passed；包含请求参数、空结果、404/422/503 与取消。
- lint 通过；Next.js Webpack 生产构建通过。
- 默认 Turbopack 在本机 CSS 子进程启动时内部失败；没有为此改项目构建配置。
- 初始离线核验时未配置 key、数据库与 Docker，因此当时没有真实模型检索质量结论。
  后续补充的本地模型测量见第 5 节；生产 OpenAI 模型尚待额度恢复后验证。
- 2026-10-21 补充本地端到端：pgvector 容器 + 迁移；前端新建 Course 并上传五份 PDF；
  `prepare_mit_course.py --parse-only` 解析为 ready，合计 46 个 chunk，与离线校验一致。
  无 key 时 embedding 步骤按预期失败（退出 1）；`evaluate_mit.py run` 返回
  `status=blocked`（无可检索 chunk），不产生指标。
- 浏览器实测：Course 详情页展开 Retrieval debug，提交问题后调用 search。
  无 embedding 时显示空结果提示；有本地 embedding 后正确显示排名、PDF 名、页码、
  score、chunk/document ID 与全文（以 D01 为例，第 2 名即正确页）。
- 页面交互已补测：独立 Chromium headless 浏览器运行生产构建，
  **15 passed、0 skipped、0 failed**，没有重试；375/768/1280px 截图已人工检查。
  使用真实 FastAPI 路由与内存数据库，检索内容/score 是明确标记的 UI fixture。
  这证明界面交互，不证明 semantic search 模型质量。
  详见 [页面交互实测报告](RETRIEVAL_UI_QA.md)。

此文档中的新测试仅验证辅助工具和接口调用契约，不替代已有 pgvector SQL 回归，
也不把测试里的 stub 返回当成真实模型测量。

## 5. 首次实测：本地免费 embedding（2026-10-21）

OpenAI 账户无额度（HTTP 429 `insufficient_quota`），因此先用免费的本地模型
`BAAI/bge-small-en-v1.5`（fastembed/ONNX，384 维补零到 1536 维，cosine 不变）
跑完整流程。**这些数字衡量的是该本地模型，不是生产配置的 OpenAI 模型。**
有额度后用第 2、3 节的原命令重跑即可对比。

[`local_embeddings.py`](../evals/retrieval/local_embeddings.py) 只在本进程替换
`app.embeddings.embed_text`，并用独立 `EMBEDDING_REVISION=local-bge-small-en-v1.5`
存储，与 OpenAI 向量互不混用；核心代码未改。fastembed 不在 requirements 中，
需单独 `pip install fastembed`，首次运行从 Hugging Face 下载约 67 MB 模型。

```powershell
services/api/.venv/Scripts/python.exe evals/retrieval/local_embeddings.py prepare --course-id 1
services/api/.venv/Scripts/python.exe evals/retrieval/local_embeddings.py api --port 8000
services/api/.venv/Scripts/python.exe evals/retrieval/evaluate_mit.py run --course-id 1 --api-url http://127.0.0.1:8000 --output evals/retrieval/results/<new-name>.json
```

Windows 上请用 `127.0.0.1` 而不是 `localhost`：Python 先尝试 IPv6 `::1`，
每次请求会多出约 2 秒超时，延迟数据失真。

结果：[`mit-6006-local-bge-small-run1.json`](../evals/retrieval/results/mit-6006-local-bge-small-run1.json)，
Top K = 5，46 个 chunk，两次运行指标完全一致。

| 指标 | @1 | @3 | @5 |
| --- | --- | --- | --- |
| source_page_hit（正确 PDF + 页） | 0.68 | 0.88 | 0.96 |
| anchor_hit（同页且含证据锚点的 chunk） | 0.56 | 0.80 | 0.88 |

`anchor_mrr_at_5` = 0.693；HTTP 搜索延迟均值 85 ms、中位 81 ms、最大 115 ms
（含本地 query embedding）。

**锚点未进前 5 或排名靠后的题**（top_k=50 复查真实名次）：

| ID | 锚点名次 | 前几名实际返回 | 判断 |
| --- | --- | --- | --- |
| B04 | 18 | Dijkstra 运行时间、DAG 最短路 | 问法差异：题目只说“puzzle / fewest moves”，未出现 graph、BFS、distance；小模型无法把场景映射到 BFS。唯一页也未命中。 |
| B03 | 9（页第 5） | DFS cycle detection、Full-DFS | 问法差异：“every destination 存完整路线”对应 shortest-path tree / parent，原文术语缺失。 |
| D04 | 12（页第 1） | lec10 第 4 页 cycle detection chunk | 页正确，第 1 名的 chunk 也讲 reverse finishing order，但 Claim 段被分到相邻 chunk：分块边界 + 锚点较严，需人工复核是否假阴性，不擅自改标签。 |
| B01 | 4 | DFS cycle detection、lec10 首页 | 问法差异：“one-way road map”→ directed graph / incoming neighbor set。 |
| H05 | 4 | lec4 第 4 页汇总表 | 页正确第 1；含锚点的 Dynamic 小节 chunk 排在第 4，同页 chunk 竞争。 |

观察（基于本次实际返回，尚需 OpenAI 结果对照）：

- 技术术语明确的题基本第 1；弱项集中在“生活化场景”问法（B 组 3 题）。
- lec10 第 4 页的 cycle detection chunk 对多道无关题都排第 1（B01、B03、D04、B04 前列），
  是一个高频“吸附”chunk，值得在 OpenAI 结果中观察是否同样出现。
- PDF 抽取文本保留连字字符（如 `ﬁnd`、`deﬁnition` 中的 U+FB01），且 chunk 开头
  常截断在词中（`re visiting u`、`perations`）。这可能影响 embedding 和锚点匹配；
  如需处理应在解析器做 NFKC 规范化，属于核心代码改动，本次只记录不修改。
- 未加 score 阈值；正确与错误结果的 score 区间重叠（约 0.6–0.8），score 不能当置信度。
