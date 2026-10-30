# Reflow (0.1.0-dev.5 候选)

Reflow 是一个运行在本地的轻量代理服务，用于为 Codex 终端提供长思考过程的自动续接支持。

当模型输出符合特定用量特征、携带加密推理状态且仍在设定的轮次预算内时，Reflow 会在后台自动发起续接请求。在此期间，服务会暂存中间的回答内容与工具调用，并在达到停止条件后，将保留的最终结果与整理后的总用量合并返回给 Codex。

续接会在后台增加上游请求次数和等待时间；常见的“516”特征也只是触发判断的一种启发式线索，无法作为推理是否充分展开或输出质量好坏的确定依据。

## 当前状态

Reflow 的核心源自 `chatwithgod/cpa-plugin-codexreflow`，已提取为不依赖 CPA SDK 的 Go 程序。2026-10-31，dev.5 源码、[实际续接决策数字诊断](docs/DECISION-DIAGNOSTICS.md)、原生实测、Pi 适配及 Magpie 新入口补丁已随 13 个提交公开至 `304a67c`；尚无二进制 Release。推送与自动 CI 的范围见[执行记录](docs/evidence/publication-dev5-2026-10-31.json)。

2026-10-30，未修改的官方 Codex `0.165.0` 在隔离的原生 ChatGPT 登录下，经独立 Reflow dev.5 完成 **1 次真实续接、成功工具往返、18/18 和正常结束，工具失败 0**。同批生产配置散列有变化，用户确认同期手动设置；原始不变检查保留未通过，功能结果与这一审计例外分开记录。累计数字、时间线及限制统一见[原生登录验收总表](docs/NATIVE-LOGIN-ACCEPTANCE.md)。

- **Codex CLI**：已有上述本机 Windows 真实会话功能证据；模拟上游还覆盖工具隔离、取消及协议恢复。
- **Codex app-server**：两种历史格式下，续接、工具回传、关闭进程后恢复和配置还原通过；Desktop/dot 界面仍未验收。
- **Codex 原生插件**：本地市场安装、缓存二进制、4 个 MCP 配置/诊断入口及原生调用通过；代理服务独立运行。见[插件说明](plugins/codex/README.md)。
- **Pi 1.4.0**：旧 `openai-codex` 入口的 SSE/WebSocket，以及新 `openai` 入口的 OAuth/API key SSE 均完成模拟续接和工具往返，按本项目约定通过模拟验收。见[Pi 适配](adapters/pi/README.md)。
- **Magpie**：本地外置方案在未修改的固定上游上完成 HTTP/WebSocket、预热、续接、工具往返与取消的 7 场景模拟检查，普通/race 通过；使用显式的 `--upstream-profile magpie`。历史嵌入式补丁与宿主全量状态单列。见[外置接入](adapters/magpie/EXTERNAL.md)。
- **评测**：默认 4 任务、34 个评分点；另有对账和构建计划任务，各 18 点。49 项离线评测器检查通过，新增受限的 Pi 只读探针，没有回答质量改善结论。见[评测说明](docs/EVALUATION.md)。

dev.5 的公开三平台常规 CI 普通/race 各 80 通过、4 跳过，vet/fuzz 和评测自检通过；三平台打包客户端普通/race 各 14 项通过。macOS 的五个写入场景及 Pi 只读探针普通/race 各 4 项通过；默认 Ubuntu/托管 Windows 仍在写入阶段失败，后续只读探针未执行。原生 CI 整体仍为失败，失败项和固定错误标记与旧记录一致。此前本机 Windows 的写入与探针成功结果见[Pi 新入口记录](docs/PI-PUBLIC-RESPONSES-2026-10-30.md)，固定前提下的 Ubuntu 对照也单独保留。各版本和平台范围见[兼容性](docs/COMPATIBILITY.md)、[原生 CI](docs/NATIVE-CI.md)和[开源准备清单](docs/OSS-READINESS.md)。

## 凭据与网络边界

- **凭据透传**：用户的 Codex 客户端继续自行负责账号登录与 Token 刷新。Reflow 仅在转发时将客户端自带的 `Authorization` 等凭据送往固定上游，本身不读取 `auth.json`，不参与鉴权逻辑管理，也不会记录或留存凭据。
- **历史隔离**：内存中的续接历史按凭据与账号隔离。使用 Magpie 的 `X-Magpie-Account` 指定账号时，该字段也参与隔离；切换、增加或移除指定账号不会自动复用另一账号的缓存历史。它不替代网关鉴权；[缓存隔离修复](docs/evidence/magpie-external-account-scope-2026-10-31.json)与后续[外置模拟联调](adapters/magpie/EXTERNAL.md)分别记录。
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

dev.5 候选补充实际续接或停止的固定原因计数，以及最多 64 个推理 token 数字样本；核心规则没有改变。字段与局限见[决策诊断说明](docs/DECISION-DIAGNOSTICS.md)。

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
