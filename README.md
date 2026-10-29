# Reflow (0.1.0-dev.4)

Reflow 是一个运行在本地的轻量代理服务，用于为 Codex 终端提供长思考过程的自动续接支持。

当模型输出符合特定用量特征、携带加密推理状态且仍在设定的轮次预算内时，Reflow 会在后台自动发起续接请求。在此期间，服务会暂存中间的回答内容与工具调用，并在达到停止条件后，将保留的最终结果与整理后的总用量合并返回给 Codex。

续接会在后台增加上游请求次数和等待时间；常见的“516”特征也只是触发判断的一种启发式线索，无法作为推理是否充分展开或输出质量好坏的确定依据。

## 当前状态

Reflow 的核心逻辑源自 `chatwithgod/cpa-plugin-codexreflow`，经过提取、解耦与适配后，转为不依赖 CPA SDK 的独立 Go 程序。

当前开发版本为 `0.1.0-dev.4`，源码已在 [chatwithgod/reflow](https://github.com/chatwithgod/reflow) 公开，尚未发布二进制 Release。已实现独立核心、代理服务和 Codex 原生插件的配置与诊断入口。此前带客户端的 Windows 本地回归为 79 个通过项、0 跳过，Codex 使用加入上游修复的隔离源码构件。公开后的三平台离线 CI 均通过，各为 69 个通过项、4 个未配置客户端的测试跳过；race、vet、fuzz 和评测自检通过。范围见 [公开与 CI 记录](docs/PUBLICATION-2026-10-28.md)、[app-server 验证](docs/APP-SERVER-2026-10-27.md)与[兼容性说明](docs/COMPATIBILITY.md)。

- **Codex CLI**：真实客户端配合合成 ChatGPT 凭证和模拟上游，完成续接，并实际执行本地 MCP 工具。
- **Codex app-server**：两种历史格式下，续接、工具回传、关闭进程后恢复会话及配置还原通过；这是后端协议验证，Desktop/dot 界面仍未验收。
- **Pi 1.4.0**：`openai-codex` 路径的 SSE 与 WebSocket 续接、工具执行和结果回传通过。见 [Pi 接入说明](adapters/pi/README.md)。
- **Codex 原生插件**：本地市场注册安装、缓存二进制、4 个 stdio MCP 工具，以及真实 Codex 会话通过 Code Mode 调用 `status` 均已验证。见 [插件说明](plugins/codex/README.md)。
- **Magpie**：可选 Go 执行扩展和嵌入适配已通过四条模拟接入路径与 race；支持固定公开 Reflow 模块，设置页覆盖两种浏览器和五种语言。宿主全量仍未通过，见 [适配与补丁](adapters/magpie/README.md)。
- **开关评测**：4 项任务、34 个评分检查点，评分器和进程管理自检通过，尚无真实模型质量结果。见 [评测说明](docs/EVALUATION.md)。

上述自动回归使用隔离目录和模拟上游。后续原生 ChatGPT 登录实测中，关闭组正常完成；开启组观察到一次真实续接且文件评分 9/9，但会话达到 180 秒上限，尚未完整验收。见 [真实测试记录](docs/LIVE-SMOKE-2026-10-26.md)。生产配置未改，Desktop/dot 和质量改善结论仍待验证。

2026-10-27 的修复版单次真实诊断在 61.647 秒正常结束，4 次推理请求、文件评分 9/9、工具失败 0 次；本次未触发续接，因此整体验收仍未完成。见 [修复版 NDJSON 实测](docs/LIVE-SMOKE-2026-10-27.md)。

随后单独授权的拓扑排序诊断在 36.771 秒正常结束，5 次推理请求、评分 8/8、工具失败 0 次，仍未触发续接。见 [拓扑排序实测](docs/LIVE-TOPO-2026-10-27.md)。2026-10-29，未修改的官方 CLI `0.165.0` 在一次 NDJSON 实测中于 61.101 秒正常结束，6 次推理请求、评分 9/9、续接 0 次；中间有一次命令失败，后续完成任务。该次结束时原生登录累计 8 次真实会话、46 次推理请求、1 次续接。见 [官方版实测](docs/LIVE-OFFICIAL-0165-2026-10-29.md)。

后续另获授权的 [LRU 实测](docs/LIVE-LRU-2026-10-29.md)在 43.533 秒正常结束，评分 9/9，5 次推理请求、续接 0 次；一次命令失败后完成修改。

2026-10-30 的 [续接对账任务](docs/LIVE-LEDGER-2026-10-30.md)在 157.988 秒正常结束，评分 18/18，观察到 1 次真实续接及 1 个匹配工具回传；但两次命令失败尚不能与续接精确对应，完整验收仍未通过。另行获批的[补充诊断](docs/LIVE-LEDGER-DIAGNOSTIC-2026-10-30.md)正常结束、18/18，未触发续接，记录到一次未分类命令失败。测试并发始终为 1，没有自动重跑。后续获批的[固定校验入口验证](docs/LIVE-LEDGER-WORKSPACE-2026-10-30.md)在 112.589 秒正常结束，18/18、工具失败 0 次，但续接仍为 0。原生登录最新累计为 12 次会话、69 次推理请求、2 次续接；新增任务须显式选择，默认四项评测不变。

同日，用户授权的临时官方 API key 经 Reflow dev.4 完成 2 次 SSE 请求、1 次固定本地函数执行及结果回传，最终答案核对通过。此次使用小型 Responses 客户端，推理 token 与续接均为 0；API 证据单独记录，见 [官方 API 检查](docs/LIVE-API-KEY-2026-10-29.md)。

此前官方 `0.164.0` 和 `0.164.0-alpha.11.1` 的 Windows 原生补丁写入失败；加入上游修复的隔离源码构件通过了五个写入场景，以及原生协议、插件回归，见 [历史复现](docs/NATIVE-WRITE-PROBE.md)。后续 `0.165.0` 和 `0.165.0-alpha.1.2` 已通过本机 Windows 的定向离线检查，见 [官方客户端复测](docs/NATIVE-CLIENT-2026-10-29.md)。三平台原生 CI 的客户端普通/race 均通过，macOS arm64 写入通过，Ubuntu/托管 Windows 写入仍失败；[宿主对照](docs/NATIVE-CI.md)已复现对应基础隔离限制。

后续获批的 [Ubuntu 兼容对照](docs/LINUX-SANDBOX-CONTROL.md)已使同一 runner 的五个写入场景从 0/5 变为 5/5，文件/网络边界及配置清理也通过。成功依赖固定发行版配置和明确的 ABI 告警例外；该选项默认关闭，原有自动 CI 失败记录保留。托管 Windows 和完整真实续接验收仍待完成。

公开仓库、发布和维护证据的准备状态见 [开源准备清单](docs/OSS-READINESS.md)。

## 凭据与网络边界

- **凭据透传**：用户的 Codex 客户端继续自行负责账号登录与 Token 刷新。Reflow 仅在转发时将客户端自带的 `Authorization` 等凭据送往固定上游，本身不读取 `auth.json`，不参与鉴权逻辑管理，也不会记录或留存凭据。
- **本地监听**：服务默认仅监听本地回环地址 `127.0.0.1:18516`，默认将请求发送至官方地址 `https://chatgpt.com/backend-api/codex`。

## 运行与配置说明

### 1. 常用命令

```bash
# 启动本地服务（默认监听 127.0.0.1:18516）
reflow -listen 127.0.0.1:18516

# 设置最大续接次数为 0，即可关闭自动续接
reflow -listen 127.0.0.1:18516 --max-continue 0

# 查看当前版本
reflow -version

# 评测时启用只包含数字的上游计数
reflow -metrics
```

服务运行后，可通过浏览器或命令行查看健康状态：
`GET http://127.0.0.1:18516/healthz`

`-metrics` 默认关闭；启用后可读取 `/metrics` 的请求数、实际续接次数和上游报告的 token 总量。计数不包含账号、模型名、响应 ID 或正文，也不写入磁盘。预热单列；缺失或无法解析用量时 `usage_complete` 为 `false`。这些计数不代表美元费用，范围限于 Responses 流。

dev.4 增加续接后工具响应、工具调用和匹配结果回传的数字计数。它们用于核对协议往返，不能单独证明工具成功或任务完成。保留的关联状态只有有上限、会过期的摘要；详情见 [评测说明](docs/EVALUATION.md)。

### 2. 客户端配置与还原

先启动服务，再预览并接入。工具只修改用户级 `openai_base_url`，继续使用 Codex 内置 provider 和原有登录；明确选择了其他 provider 时会拒绝自动切换。

```sh
reflow codex-config --action preview
reflow codex-config --action connect
# 停止服务前还原
reflow codex-config --action restore
```

只有实际改变配置后才需要重启 Codex。还原保留其他设置的后续修改；路由已被手动改动时会拒绝覆盖。可用 `--codex-home` 指定另一份配置目录。原生插件提供相同的预览、接入和还原工具，安装插件不会自动启动代理。

## 验证范围与局限

当前开发版已在本地模拟环境下验证了以下覆盖场景：

- 续接过程中的工具隔离与上下文串联
- 下一轮交互所需的父响应 ID 衔接
- WebSocket 连接预热与多通道并发
- HTTP 请求取消与压缩请求处理
- WebSocket 中途取消、断开、丢失父响应后的完整重放，以及过期缓存的清理
- 遇到已由上游执行的工具时停止续接，避免重新执行其副作用

近期在本地模拟环境下补充了两组真实 CLI 的链路验证：

- **Pi CLI 1.4.0**：临时隔离环境配合合成 OAuth 凭证，跑通 SSE 与 WebSocket 双路径的续接流程。内置 `read` 工具读取合成文件，工具结果回传；被舍弃轮次的读操作没有执行。
- **Codex CLI 0.164.0-alpha.11.1**：使用合成 ChatGPT 凭证，纯 WebSocket、无 HTTP 回退，实际执行一次本地只读 MCP 工具，并回传结果。此前 shell 工具测试有过断言误判，已修正并保留失败记录。

Windows amd64 本机、macOS arm64 CI，以及采用上述固定发行版配置的 Ubuntu amd64 已有原生客户端和打包构件的离线执行证据。默认三平台 CI 的协议/插件/Pi 普通及 race 检查通过；其 Ubuntu/托管 Windows 写入失败仍保留，Linux arm64/macOS amd64 尚缺原生验证。最新范围见 [原生 CI 记录](docs/NATIVE-CI.md)与[兼容性](docs/COMPATIBILITY.md)；此前 [dev.2](docs/VERIFICATION-0.1.0-dev.2.md)与 [dev.1](docs/VERIFICATION-2026-10-26.md)记录继续保留。

这些测试只证明已覆盖场景的行为符合预期，不等同于真实线上账号的 OAuth 验收，也尚未验证真实 Token 自动刷新、Codex Desktop / dot、跨连接恢复的完整边界或实际模型输出质量。

## 开发与复现

公开预览目前从源码构建，需要 Go 1.26：

```sh
git clone https://github.com/chatwithgod/reflow.git
cd reflow
go build ./cmd/reflow
```

Windows 生成 `reflow.exe`，其他系统生成 `reflow`。插件开发包可用下述构建脚本生成。

需要 Go 1.26。核心及代理测试默认只调用回环模拟上游：

```sh
go test ./...
go test -race ./...
go vet ./...
```

真实客户端的隔离测试默认跳过。设置 `REFLOW_CODEX_BIN` 指向 Codex CLI，或设置 `REFLOW_PI_CLI` 指向 Pi 1.4.0 的 `dist/bundle/cli.js` 后，可以运行对应测试；`REFLOW_NODE_BIN` 指定 Node，`REFLOW_PROXY_BIN` 指定待验收的 Reflow 构件，`REFLOW_PLUGIN_MARKETPLACE` 指定已打包的本地插件市场目录。测试自行创建合成凭证，不读取现有账号。

PowerShell 下可使用 `scripts/verify.ps1` 保存验证记录，使用 `scripts/build.ps1 -AllPlatforms -WithCodexPlugin` 生成五个平台的独立服务和插件包。构建需要 Go 1.26 和 Python 3.9+；验证脚本的 `-PluginMarketplace` 参数对应上述插件目录。构件存放在版本号和时间戳目录中，不覆盖旧构件。

## 来源与致谢

Reflow 建立在社区先行者的探索之上，完整保留并致谢以下上游项目的代码成果与开源许可证：

- `chatwithgod/cpa-plugin-codexreflow`
- `uf-hy/cpa-plugin-codexcomp`
- `dzshzx/codexcomp`
- `neteroster/CodexCont`
