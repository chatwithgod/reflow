# 按次诊断（dev.5）

## 能回答什么

一次插件处理生成一个随机 `run_id`，首轮和所有追加轮共用它；下一次处理另起编号。
`metadata.proxy_reflow.run_id` 可与插件日志直接对应。无需开启 `debug_log` 或请求正文日志。
这不是会话 ID、上游 response ID，也不是 CPA 用量表的 execution ID。

dev.5 在默认 INFO 日志增加：

| 事件 | 含义 |
|---|---|
| `fold_started` | 插件开始处理；可能随后启动失败，不能据此认定发生了付费调用 |
| `round_finished` | 某轮收到 completed / failed / incomplete 终止事件；含轮号及白名单 token 计数 |
| `fold_finished` | 结束结果、尝试/终止轮数、续接次数、停止原因、输出阶段 |

每轮 `reported_usage` 只包含输入、输出、总量、缓存和推理 token 五个数字。
这些是**上游原样报告的计数语义**，不是 CPA 账单规范化后的计数；不能再把推理数无条件加到输出数上。
缺失、负数、非整数或超出安全整数范围的值写为 `null`，实际零值保留 `0`。
一轮 `response.failed` 也属于“收到了终止事件”，不是成功回答。
正常完成的 N 轮处理会有 N+2 条上述诊断日志，另可能有父 ID 衔接日志。

当宿主在原生 WS 响应钩子前拦截了错误、但插件已经建立该次状态时，生命周期回调可补充
`host_lifecycle_failed/canceled/rejected`；`emission: not_confirmed` 不宣称输出送达。
如果宿主在建立插件状态之前就失败，则没有该次插件诊断；缺日志不等于没错误。
进程终止、日志丢失、TTL 清理和不接管的请求，也不保证有成对的开始/结束记录。

## 为什么暂时不能精确关联 ECPA 的每一行

检查了锁定 SDK `v8.0.13` 和用于兼容检查的 CPA `v8.0.16` 源码，**没有升级 SDK**：

- `pluginapi.UsageRecord.RequestID` 是用量执行实例 ID；`redisqueue` 把它写为 `execution_id`。
- 执行器请求和 host model stream 返回没有提供这个同一编号。
- `StreamChunkInterceptRequest.RequestID` 来自独立的 lifecycle tracker；在上述源码中每次 tracker 新建 UUID，
  **它不是 WS 连接 ID，也不能直接视为用量执行 ID**。
- `TraceID` 指向父请求，WS 多次生成/隐藏续接可能共享，不能作为单轮唯一键。

因此 `metadata.proxy_reflow.usage_join` 固定标注 `unavailable`。没有添加用量订阅、消费生产 usage 队列，
没有通过时间、相同 token 数、请求头或内容哈希伪造精确关联，也不为追踪而修改请求路由。
后续要实现“ECPA 行 ↔ 插件轮次”的严格连接，需要宿主在两端暴露同一个执行编号，或另经验证的宿主接口。

源码位置：`sdk/pluginapi/types.go` 的 `UsageRecord`、`ExecutorRequest`、`HostModelStreamResponse`；
`sdk/api/handlers/handlers_interceptors.go` 的 `newRequestLifecycleTracker`；
`internal/redisqueue/plugin.go` 的 `executionID := record.RequestID`。

## 本地汇总

仅对你已导出的日志执行，不会连接 CPA，也不需要管理密钥：

```powershell
python scripts/summarize_diagnostics.py <已导出的日志文件> --output <新的脱敏报告.json>
```

工具只导出白名单字段，支持普通 CPA 日志、JSON 日志和单条 JSON 诊断。
它会按 `run_id` 分组并按轮号排序，而不是按时间拼接；相同 516 的并发请求不合并。
`evidence_complete` 只表示开始、逐轮、结束计数互相对得上，**不是成功、送达或质量评级**。
缺开始/结束/轮次、重复记录、相互冲突的路径会使它为 false；重复数据不被默默去重成成功。
`observed_reasoning_sum` 只合计已观测终止轮；任一轮未知则为 null，无终止轮也不制造 0。
报表不直接读取旧 dev.4 日志并补造新证据。无有效新记录时 `runs` 为空。

输入逐行限长 16 KiB，最多 10000 次处理、200000 条事件、单次轮号最多 4096，超出计数限制明确报错。
输出文件必须不存在，防止覆盖原始记录。不要公开分享原始 CPA 日志，它仍可能包含宿主或其他插件记录的敏感信息。
脱敏报告虽无正文/凭证，仍暴露使用量和可关联的随机编号，应按运行诊断数据保管。

## 不变的边界

- 这版不更改自动模型规则、续写预算、加密状态要求、路由或 HTTP/WS 策略。
- 不把 516 的消失当成目标，不把追加轮次当成质量提升。
- `host_accepted` 和 `interceptor_returned` 均不是客户端收件回执。
- 新增诊断仅在安装新 DLL 后对新请求可见；候选包本身不会安装或启用插件。
