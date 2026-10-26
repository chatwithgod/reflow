# Reflow 开关对照评测

评测包含区间合并、拓扑排序、分块 NDJSON 解析、LRU 缓存 4 项维护任务，共 34 个检查点。评分器自检中，参考实现全部通过，预置错误实现都未全过。已有一次 NDJSON 真实对照，但开启组超时，不能得出质量改善结论；见 [实测记录](LIVE-SMOKE-2026-10-26.md)。

后续修复版的单次开启组正常完成，评分 9/9，未触发续接。它不是新的配对结果，也不能用于证明续接后的完整验收，见 [2026-10-27 记录](LIVE-SMOKE-2026-10-27.md)。

默认每项任务分别关闭 Reflow（0 次续接）和开启 Reflow（最多 3 次续接），共 8 次试验。`--repeats` 指定重复次数，`--seed` 决定任务顺序；同一任务的开关先后顺序随重复轮次交替。两组使用相同模型、思考层级和初始源码。

每次试验使用临时 `CODEX_HOME` 和工作目录，结束后清理凭据与自有子进程，不改生产配置。评分在单独的 Python 进程中执行，超时为 10 秒。这是目录和环境隔离，不是操作系统安全沙箱。

真实测试会话串行执行，禁用原生子代理，默认组间等待 30 秒。Windows 在读取登录文件之前，依次检查配套 Code Mode 宿主能否启动、MXC 命令写入、原生文件 RPC 写入及工作区外写入阻断；任一失败均停止。代理执行阶段仍采用工作区写入权限，两组显式启用 Code Mode。评分器自身仍使用上述单独 Python 进程。检测到限流事件会停止代理和后续试验。

运行记录只保存评分、耗时、退出状态及白名单用量数字，不保存模型聊天或工具正文。`client_reported_usage` 是客户端看到的用量；`upstream_metrics` 记录实际请求数、续接次数与 Responses 上游报告的 token。只有全部用量都被观察到，才填写 `upstream_reported_usage`，否则为 `null`。预热单列，其他 API 不在统计范围内；这些数字不是美元费用。

进程测试使用合成代理程序和真实打包 Reflow，只查询健康接口并写入参考解。五项通用测试验证开关参数、失败退出、超时清理、限流停止、敏感标记不落盘，以及没有代理推理流量时拒绝成功状态；Windows 另有五项测试前检查。它们不构成模型质量证据。

记录额外包含 `artifact_changed` 和最多 80 条匿名事件时间线。时间线只保留事件类型、工具类别、状态、退出码和相对时间，不保留正文、命令、路径或响应 ID。`--conditions on` 只选开启组，结果标为单条件诊断，不能用于开关质量比较。

dev.4 的 `/metrics` 新增以下可选数字；评测器仍能读取旧版指标，并用 `tool_roundtrip_metrics_available` 标识新字段是否存在：

| 字段 | 含义 |
| --- | --- |
| `continued_tool_responses` | 续接后保留的最终响应中有客户端工具调用，且相关事件已写出 |
| `continued_tool_calls` | 上述响应中的 function/custom 工具调用数 |
| `continued_tool_results` | 后续请求中能与上述调用对应的结果数，重复回传只计一次 |
| `tool_tracking_drops` | 因容量、标识冲突或到期而放弃关联的调用数 |

关联要求凭据范围、模型、工具类型和调用标识一致，并匹配客户端看到的父响应，或完整历史中保留的原始工具项。移除标识的历史可能无法计入；回传工具失败信息也能被计入。因此 `continuation_tool_result_observed=true` 只证明协议上有匹配结果，不能证明工具成功或任务结束，仍需结合事件状态、文件评分和会话退出状态。失败的事件写出、取消和预热不会作为完成的工具响应计入。最多暂存 256 个摘要，30 分钟后在后续观测时清理，不保存原始标识或正文。

在源码目录运行以下命令不会调用模型：

```sh
python evaluations/run.py --self-test
python evaluations/run.py --model gpt-6.1-sol --repeats 3
python evaluations/run.py --preflight-only --codex /absolute/path/to/codex.exe
```

完整的进程自检可运行 `python scripts/check-evaluation.py --go /absolute/path/to/go`。它会自行构建合成 agent 和代理，不再需要手工准备测试二进制；可通过 `--proxy` 使用已有构件。见 [回归入口](REGRESSION.md)。

第二条只生成 24 次试验的计划；第三条仅检查客户端，不读取登录文件。结果位于 `build/evaluations/`。真实运行需用户单独授权，并显式提供 `--run-live`、`--codex`、`--reflow`、`--auth-file` 和 `--model`；登录文件必须是原生 ChatGPT 登录，Reflow 构件须支持 `-metrics`。若没有观察到代理上的推理请求，或遇到启动、客户端错误、超时，会停止后续试验，保留已完成的数字记录。

这是一组小型可复现实验。只比较完整成对的真实结果，并同时报告成功率和耗时；不能将结论直接外推到全部编程任务。
