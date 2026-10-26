# Reflow (0.1.0-dev.3)

Reflow 是一个运行在本地的轻量代理服务，用于为 Codex 终端提供长思考过程的自动续接支持。

当模型输出符合特定用量特征、携带加密推理状态且仍在设定的轮次预算内时，Reflow 会在后台自动发起续接请求。在此期间，服务会暂存中间的回答内容与工具调用，并在达到停止条件后，将保留的最终结果与整理后的总用量合并返回给 Codex。

续接会在后台增加上游请求次数和等待时间；常见的“516”特征也只是触发判断的一种启发式线索，无法作为推理是否充分展开或输出质量好坏的确定依据。

## 当前状态

Reflow 的核心逻辑源自 `chatwithgod/cpa-plugin-codexreflow`，经过提取、解耦与适配后，转为不依赖 CPA SDK 的独立 Go 程序。

当前开发版本为 `0.1.0-dev.3`，已实现独立核心、代理服务和 Codex 原生插件的配置与诊断入口，尚未公开发布。打包程序的 73 个测试项、race、vet 和 fuzz 通过，详细范围见 [dev.3 验证](docs/VERIFICATION-0.1.0-dev.3.md)与[兼容性说明](docs/COMPATIBILITY.md)。

- **Codex CLI**：真实客户端配合合成 ChatGPT 凭证和模拟上游，完成续接，并实际执行本地 MCP 工具。
- **Pi 1.4.0**：`openai-codex` 路径的 SSE 与 WebSocket 续接、工具执行和结果回传通过。见 [Pi 接入说明](adapters/pi/README.md)。
- **Codex 原生插件**：本地市场注册安装、缓存二进制、4 个 stdio MCP 工具，以及真实 Codex 会话通过 Code Mode 调用 `status` 均已验证。见 [插件说明](plugins/codex/README.md)。
- **Magpie**：可选 Go 执行扩展和嵌入适配已通过四条模拟接入路径与 race；宿主全量测试未通过，选定失败项在干净上游和修改版复查时失败集合相同。见 [适配与补丁](adapters/magpie/README.md)。
- **开关评测**：4 项任务、34 个评分检查点，评分器和进程管理自检通过，尚无真实模型质量结果。见 [评测说明](docs/EVALUATION.md)。

这些验证使用隔离目录和模拟上游，没有调用真实账号，也没有改动生产配置。真实账号、Desktop/dot 和任务质量验收仍未完成。

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

Windows 构件已通过上述 CLI 验证；Linux/macOS 只做交叉编译，尚无原生运行证据。详细范围见 [dev.2 验证记录](docs/VERIFICATION-0.1.0-dev.2.md)，以及保留的 [dev.1 记录](docs/VERIFICATION-2026-10-26.md)。

这些测试只证明已覆盖场景的行为符合预期，不等同于真实线上账号的 OAuth 验收，也尚未验证真实 Token 自动刷新、Codex Desktop / dot、跨连接恢复的完整边界或实际模型输出质量。

## 开发与复现

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
