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
本次没有移植 v1.1 的自动处理代码。可在 `services/api` 目录开启 Python，
把下面的 `123` 替换为专用 Course ID，调用现有解析函数：

```python
import json
from pathlib import Path
from sqlalchemy import select
from app.database import get_session_factory
from app.models.content import Content
from app.models.document import Document
from app.parsing import process_content

course_id = 123
fixture = json.loads(Path("../../evals/retrieval/mit_6006.json").read_text(encoding="utf-8"))
expected = {doc["name"]: doc["sha256"] for doc in fixture["documents"]}
factory = get_session_factory()
with factory() as db:
    rows = db.execute(select(Document.name, Content.id, Content.content_hash)
                      .join(Content, Content.id == Document.content_id)
                      .where(Document.course_id == course_id)).all()

assert len(rows) == len(expected)
assert {name for name, _, _ in rows} == set(expected)
assert all(expected[name] == digest for name, _, digest in rows)
content_ids = sorted({content_id for _, content_id, _ in rows})
for content_id in content_ids:
    with factory() as db:
        content = db.get(Content, content_id)
        if content.status != "ready":
            process_content(db, content)

print("Only these benchmark Content IDs:", content_ids)
```

随后仅针对打印出的每个 ID 执行既有命令：

```bash
python -m app.embedding_backfill --content-id 123
```

这里的 `123` 是 **Content ID**，不是 Course ID；逐个替换。
该步骤会向配置的 embedding 服务发送公开课件文本。已 ready 的 Content 不必重解析；
成功重解析会替换 chunk，需要重新 backfill。不要对其他课程批量刷新。

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
- 本机没有 OPENAI_API_KEY、DATABASE_URL、TEST_POSTGRES_URL，Docker daemon 未运行。
  **本次没有真实模型 Top K、准确率或检索质量结论。**
- Chrome 自动操作未获准，本轮没有完成浏览器交互实测；构建和传输测试不冒充视觉验证。

此文档中的新测试仅验证辅助工具和接口调用契约，不替代已有 pgvector SQL 回归，
也不把测试里的 stub 返回当成真实模型测量。
