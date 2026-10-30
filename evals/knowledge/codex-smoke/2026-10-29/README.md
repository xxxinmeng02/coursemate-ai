# Codex 额度生成测试：一次受控小样本

日期：2026-10-29，Australia/Adelaide。**真实 Codex CLI 生成已成功，退出码 0，耗时 22.732 秒。**
这是用户授权的独立 smoke test，未接入生产服务、未训练模型、未写数据库，未提交或推送。

## 生成结果

- [直接阅读中文知识卡片与问答](preview.md)
- [模型实际输出 JSON](result.json)
- [校验结果](validation.json)
- [实际运行参数、版本、用量和时间](run.json)
- [输入来源与文件指纹](sources.json)、[提示词](prompt.txt)、[输出 JSON Schema](output-schema.json)
- [CLI 事件记录](events.jsonl)、[错误输出](stderr.log)、[登录方式检查](auth-status.txt)

输入是现有 MIT 6.006 Spring 2020 Lecture 9 的第 3、4 页，
生成 3 张中文卡片与 1 条问答：最短路径树/父指针、BFS 层集合、不可达顶点，以及是否需要保存所有完整路径。
每条都有适用条件、来源页和短引文；卡片还有中英文术语别名。

来源归属：MIT OpenCourseWare，Erik Demaine、Jason Ku、Justin Solomon；CC BY-NC-SA 4.0。
原 PDF SHA-256 已核对，模型只收到选定两页的文字和生成任务，没有收到项目 `.env` 或账号凭据。

## 使用的是哪种额度

本机 `codex login status` 返回 `Logged in using ChatGPT`。
测试通过官方 `codex exec` 复用保存的 ChatGPT 登录，并强制 `forced_login_method=chatgpt`。
子进程环境移除了 `OPENAI_API_KEY`、`CODEX_API_KEY`、`CODEX_ACCESS_TOKEN` 和自定义 `OPENAI_BASE_URL`，
没有读取或复制 auth token，也没有回退到 API key。

官方依据：

- [认证方式](https://learn.chatgpt.com/docs/auth)：ChatGPT 登录对应订阅访问，API key 对应按量访问。
- [非交互模式](https://learn.chatgpt.com/docs/non-interactive-mode)：复用 CLI 登录；支持 JSONL、输出 Schema 和结果落盘。
- [额度与计费](https://learn.chatgpt.com/docs/pricing)：Codex/Work 使用共享计划额度，API 价格与订阅使用额度分开。

本次事件报告的 usage 为输入 14367 tokens、输出 765 tokens；输入包含 CLI 自带上下文开销。
它不是美元账单，也不能直接换算为此调用扣除了多少额度百分比；当前聊天和其他任务也共享账户额度。

CLI 版本为 `0.165.0-alpha.1.2`。没有指定模型，使用 CLI 默认值。
这次事件没有返回可核实的模型标识，所以 `reported_model=null`，不根据模型自述猜测版本。
需要比较不同模型时，应另行固定可用模型并记录，不能把该样例当成生产生成模型的基准。

## 执行限制与校验

CLI 在临时空目录以 read-only sandbox 运行；关闭 shell、多 agent、apps、plugins、hooks、browser、computer use 和 image generation。
使用 ephemeral 会话、150 秒超时，没有自动重试。事件中观察到工具调用 0 次。
本次只执行一次模型生成；运行脚本拒绝覆盖已有结果，避免误触重复消耗额度。

已自动核对：

- JSON 符合约定的字段、类型和来源页范围，恰好 3 张卡片及 1 条问答，ID 不重复。
- 4 条证据锚点均能在指定原文页中准确定位。
- 每条都有适用条件；卡片带中英文别名；正文长度符合本次限制。
- 原 PDF 与输入文件 SHA-256 匹配，CLI 成功结束，无错误事件或额外工具调用。

**自动校验不证明所有解释正确。** 当前只有小样本和作者对照原文的检查，没有独立人工复核、
知识覆盖率评估或新问题检索测试。未安装本地模型，也没有实现离线知识库页面/数据库。

本次是文本知识生成，不是 embedding 生成；原来两项真实 embedding 质量测试、完整 MRR 的实测值仍待之后执行。
没有把 Codex 登录凭据变成应用的通用 API key，也没有开放可供其他用户调用的 Codex 服务。

## 脚本

从仓库根目录，重新做不消耗模型额度的结果校验：

```bash
.venv/bin/python evals/knowledge/codex-smoke/2026-10-29/validate_result.py
```

`run_cli.py` 保存了这次实际调用方式，但有已有结果时会拒绝再次生成。
后续若授权新一轮测试，应使用新的批次目录，保留本次原始输出。
