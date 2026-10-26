# Reflow 开关对照评测

评测包含区间合并、拓扑排序、分块 NDJSON 解析、LRU 缓存 4 项维护任务，共 34 个检查点。评分器自检中，参考实现全部通过，预置错误实现都未全过。目前没有真实模型的质量结果。

默认每项任务分别关闭 Reflow（0 次续接）和开启 Reflow（最多 3 次续接），共 8 次试验。`--repeats` 指定重复次数，`--seed` 决定任务顺序；同一任务的开关先后顺序随重复轮次交替。两组使用相同模型、思考层级和初始源码。

每次试验使用临时 `CODEX_HOME` 和工作目录，结束后清理凭据与自有子进程，不改生产配置。评分在单独的 Python 进程中执行，超时为 10 秒。这是目录和环境隔离，不是操作系统安全沙箱。

运行记录只保存评分、耗时、退出状态及白名单用量数字，不保存模型聊天或工具正文。`client_reported_usage` 是客户端看到的用量；`upstream_metrics` 记录实际请求数、续接次数与 Responses 上游报告的 token。只有全部用量都被观察到，才填写 `upstream_reported_usage`，否则为 `null`。预热单列，其他 API 不在统计范围内；这些数字不是美元费用。

进程测试使用合成代理程序和真实打包 Reflow，只查询健康接口并写入参考解。四项测试验证开关参数、失败退出、超时清理、敏感标记不落盘，以及没有代理推理流量时拒绝成功状态，不构成模型质量证据。

在源码目录运行以下命令不会调用模型：

```sh
python evaluations/run.py --self-test
python evaluations/run.py --model gpt-6.1-sol --repeats 3
```

完整的进程自检可运行 `python scripts/check-evaluation.py --go /absolute/path/to/go`。它会自行构建合成 agent 和代理，不再需要手工准备测试二进制；可通过 `--proxy` 使用已有构件。见 [回归入口](REGRESSION.md)。

第二条只生成 24 次试验的计划，结果位于 `build/evaluations/`。真实运行需用户单独授权，并显式提供 `--run-live`、`--codex`、`--reflow`、`--auth-file` 和 `--model`；登录文件必须是原生 ChatGPT 登录，Reflow 构件须支持 `-metrics`。若没有观察到代理上的推理请求，或遇到启动、客户端错误、超时，会停止后续试验，保留已完成的数字记录。

这是一组小型可复现实验。只比较完整成对的真实结果，并同时报告成功率和耗时；不能将结论直接外推到全部编程任务。
