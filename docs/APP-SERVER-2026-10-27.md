# Codex app-server 后端验证

2026-10-27，使用 Reflow `0.1.0-dev.4` 和本地修复版 Codex `0.164.0`，在隔离目录中验证了 Desktop 使用的 app-server 协议。`legacy` 和 `paginated` 两种历史格式均通过。所有上游响应与凭据都是合成数据；没有新增真实账号或模型调用，没有启动、重启或改动生产 Desktop。

## 已验证行为

两种格式分别串行执行相同流程，每次只运行一个 app-server 进程：

1. 启动 `app-server --listen stdio://`，在任何会话请求前核对其实际 `CODEX_HOME` 为临时目录。
2. 读取账号与配置：合成账号识别为 `chatgpt`，内置 provider 保持 `openai`，模型为 `gpt-6.1-sol`。没有请求 Token 刷新。
3. 通过 Reflow 配置控制器接入临时配置文件；请求地址来自文件，而非仅用命令行覆盖。
4. 第一轮模拟响应满足续接条件。中间工具调用被舍弃，保留的 Code Mode 调用只执行一次本地只读 MCP，工具结果回传后会话正常结束。
5. 关闭第一个 app-server，确认正常退出，再用同一临时目录启动第二个进程、恢复持久会话。历史中的工具调用、工具结果和前一轮最终回答均回传，下一轮正常完成。
6. 关闭第二个进程，调用还原入口，核对配置文件逐字节等于接入前内容。

每种格式均观察到 4 次模拟推理请求、1 次续接、2 个完成的用户轮次；全部经过 WebSocket，没有 HTTP 推理回退。工具响应、调用与结果关联计数各为 1，跟踪丢弃为 0；输入用量 400、输出用量 616，用量完整。这些数字用于协议断言，不代表真实模型用量。

夹具自行创建合成凭据、本地 TLS 账号发现接口与本地 MCP。未配置的外部 HTTP(S) 请求由本地拒绝代理拦截。测试不读取现有账号；诊断只保存结果和计数，不保存 RPC 正文。

## 回归与复现

最终全量报告位于 `build/verification/20261027-054112-483/`：79 个通过项、0 跳过，race、vet 和解码器 fuzz 全部通过。通过项包括父测试、子测试和 fuzz 种子；不含生成目录副本，也不含另行运行的原生写入探针。此前 77 项中间结果保留，最终两种历史格式以本次 79 项为准。

设置 `REFLOW_CODEX_BIN` 为支持本记录协议的客户端，`REFLOW_PROXY_BIN` 为待验证 Reflow 后，可单独复现：

```sh
go test -count=1 -v ./integration -run '^TestCodexAppServerOffline$'
```

完整检查使用 `scripts/verify.ps1` 的 `CodexExe`、`PiCli`、`NodeExe`、`ProxyExe`、`PluginMarketplace` 参数。测试夹具见 `integration/app_server_test.go` 和共享的 `integration/codex_test.go`。未提供客户端路径时，app-server 测试明确跳过，不把父测试无实际执行记为通过。

本次仅修改测试、验证报告和文档，沿用已校验的 dev.4 构件，不覆盖旧包。关键 SHA256：

- Reflow Windows：`4e82a9db2c46d967650bc936edae46bb8eb705f8efc135f1f13ecc7179aea3ee`。
- 本地 Codex：`f8b4684f683a03841e90ef363044c12042e4eb37e59ab1b97ae1a11150d5f415`。
- 同版本 Code Mode 宿主：`4d82e0157eba9afdb48650cb3bdd7c709d5bb1ce08ec661941ba74c605f2f0d3`。

Codex 使用固定源码加已合并的上游 Windows 修复，不是官方发布二进制；来源见 [写入探针](NATIVE-WRITE-PROBE.md)。机器可读结果、源码散列、日志散列与桌面只读检查摘要见 [app-server-2026-10-27.json](evidence/app-server-2026-10-27.json)。

## Desktop/dot 的范围

已只读检查安装包 `26.1021.3705.0`（内部 package 版本 `26.1021.31345`）的启动代码，确认存在以下候选入口：

- `CODEX_ELECTRON_USER_DATA_PATH`：在获取单实例锁前设置 Electron 用户数据目录。
- `CODEX_HOME`：选择 Codex 配置目录；启动环境重载时保留显式值还依赖同时设置上述用户数据目录。
- `CODEX_CLI_PATH`：指定后端 CLI。
- `CODEX_APP_SERVER_FORCE_CLI=1`：选择 CLI 后端而非已配置的 WebSocket 地址。

这些只是安装包源码观察，未通过 GUI 运行验证，不能据此保证整个桌面状态已隔离。没有生成或执行未验证的桌面启动器。当前自动化工具未提供原生桌面控制，也未暴露 Dot 浏览器操作入口；这不表示产品没有 dot 入口。专用 Codex 工具也未提供可用的正常文本会话 UI 控制路径。

因此本次只证明后端协议在上述场景中成立。dot 入口显示、实际界面会话、真实 Token 刷新以及“真实续接、工具成功、会话正常结束”仍未完成验收。既有真实测试累计仍为 6 次会话、35 次推理请求、1 次续接；本次未增加额度消耗。最新真实诊断见 [实测记录](LIVE-SMOKE-2026-10-27.md)。
