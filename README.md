# Reflow（0.1.0-dev.6 开发候选）

Reflow 为长思考过程提供自动续接支持。同一套核心可作为独立本地代理运行，也可构建为 CPA 的 CodexReflow 插件。

当模型输出符合特定用量特征、携带加密推理状态且仍在设定的轮次预算内时，Reflow 会在后台自动发起续接请求。在此期间，服务会暂存中间的回答内容与工具调用，并在达到停止条件后，将保留的最终结果与整理后的总用量合并返回给 Codex。

续接会在后台增加上游请求次数和等待时间；常见的“516”特征也只是触发判断的一种启发式线索，无法作为推理是否充分展开或输出质量好坏的确定依据。

## 当前状态

当前源码已将 CPA `v0.1.3` 的代码和提交历史汇入 `adapters/cpa`，共用不依赖宿主 SDK 的续接判断、事件合并、用量计算和流解码。独立版候选为 `0.1.0-dev.6`，CPA 候选为 `0.1.4`；它们分别构建、分别验证，尚未发布。CPA 的工具参数恢复修复仍在 CPA 层。结构、验证入口与迁移边界见[共用核心与 CPA 接入](docs/CPA-INTEGRATION.md)。

2026-11-12 本机 Windows 离线检查通过：独立版普通/race 各 97 通过、4 跳过；CPA 各 220 通过，vet 通过；CPA 动态库打包前后各 46 个 ABI 场景通过。新独立包完成模拟续接，两个产品仍独立打包。数字和未覆盖范围见[本轮记录](docs/evidence/cpa-integration-2026-11-12.json)。

已发布下载仍分别为[独立版 dev.5](https://github.com/chatwithgod/reflow/releases/tag/v0.1.0-dev.5)与[CPA 插件 v0.1.3](https://github.com/chatwithgod/cpa-plugin-codexreflow/releases/tag/v0.1.3)。以下真实账号和平台验收属于这些历史版本，不自动覆盖本次合并候选。

Reflow 的核心源自 `chatwithgod/cpa-plugin-codexreflow`，已提取为不依赖 CPA SDK 的 Go 程序。2026-10-31，dev.5 源码、[实际续接决策数字诊断](docs/DECISION-DIAGNOSTICS.md)、原生实测、Pi 适配及 Magpie 新入口补丁曾随 13 个提交公开至 `304a67c`。随后发布了固定 `3e0ea18` 的 [dev.5 预发布版](https://github.com/chatwithgod/reflow/releases/tag/v0.1.0-dev.5)，提供五平台独立服务和 Codex 插件包；12 个附件已完成公开下载核验。平台差异与标签 CI 见[发布记录](docs/RELEASE-0.1.0-dev.5.md)，此前源码推送见[历史记录](docs/evidence/publication-dev5-2026-10-31.json)。

2026-10-30，未修改的官方 Codex `0.165.0` 在隔离的原生 ChatGPT 登录下，经独立 Reflow dev.5 完成 **1 次真实续接、成功工具往返、18/18 和正常结束，工具失败 0**。同批生产配置散列有变化，用户确认同期手动设置；原始不变检查保留未通过，功能结果与这一审计例外分开记录。累计数字、时间线及限制统一见[原生登录验收总表](docs/NATIVE-LOGIN-ACCEPTANCE.md)。这是发布前候选的有限样本，本次发布没有增加真实账号验收。

2026-11-04，已发布的 Windows 独立包完成一组[原生登录开关对照](docs/LIVE-SCHEDULER-PAIR-2026-11-04.md)：两组均正常结束、18/18、工具失败 0，生产配置和登录文件未变；开启组未触发续接。累计为 23 次会话、122 次已观察请求、4 次续接。新对照不能抵消旧样本的审计例外，也没有建立质量或速度收益结论。

同日随后完成预先限定的[三个开启样本](docs/LIVE-SCHEDULER-SAMPLING-2026-11-04.md)，均正常结束、18/18、工具失败 0、保护文件未变，仍无续接。CLI 累计为 **26 次会话、134 次已观察请求、4 次续接**；该批已到上限，历史 CLI 配置审计例外原样保留。

2026-11-05，已发布 dev.5 在隔离的原生 ChatGPT 登录 Desktop 中完成[同一会话的真实续接闭环](docs/DESKTOP-CONTINUATION-2026-11-05.md)：**6 次请求、1 次续接、1 次匹配工具回传、18/18 和正常回合结束**，生产配置及登录文件未变，测试进程已清理。此样本不修补旧 CLI 审计记录，也不建立质量或长期稳定性结论。

- **Codex CLI**：已有上述本机 Windows 真实会话功能证据；模拟上游还覆盖工具隔离、取消及协议恢复。
- **Codex app-server / Desktop**：两种历史格式的后端模拟续接、工具回传、关闭进程后恢复和配置还原通过；Desktop 已完成上述真实续接样本，之前同一聊天的两轮任务也通过。dot 成功读取本机随机标记文件，10 个测试文件未变；dot 那次本地 Reflow 推理请求为 0，与 Desktop 续接分开记录。见[人工验收后续](docs/DESKTOP-DOT-2026-11-05-FOLLOWUP.md)。
- **Codex 原生插件**：本地市场安装、缓存二进制、4 个 MCP 配置/诊断入口及原生调用通过；代理服务独立运行。见[插件说明](plugins/codex/README.md)。
- **Pi 1.4.0**：旧 `openai-codex` 入口的 SSE/WebSocket，以及新 `openai` 入口的 OAuth/API key SSE 均完成模拟续接和工具往返，按本项目约定通过模拟验收。见[Pi 适配](adapters/pi/README.md)。
- **Magpie**：本地外置方案在未修改的固定上游上完成 HTTP/WebSocket、预热、续接、工具往返与取消的 7 场景模拟检查，普通/race 通过；使用显式的 `--upstream-profile magpie`。历史嵌入式补丁与宿主全量状态单列。见[外置接入](adapters/magpie/EXTERNAL.md)。
- **评测**：默认 4 任务、34 个评分点；另有对账和构建计划任务，各 18 点。49 项离线评测器检查通过，新增受限的 Pi 只读探针，没有回答质量改善结论。见[评测说明](docs/EVALUATION.md)。

2026-11-04，`6d6cfbf` 的三平台常规 CI 普通/race 各 90 通过、4 跳过，vet/fuzz 和评测自检通过；三平台打包客户端普通/race 各 14 项通过。Ubuntu/macOS 的五个写入场景及 Pi 探针普通/race 各 4 项通过；托管 Windows 仍在写入阶段失败，后续探针未执行，原生 CI 整体仍为失败。Ubuntu 本次没有由工作流改动宿主配置，客户端与 CI 输入和前轮相同，转为通过的原因尚未查明。此前标签的 Ubuntu 失败和固定配置对照均保留，范围见[兼容性](docs/COMPATIBILITY.md)、[原生 CI](docs/NATIVE-CI.md)和[开源准备清单](docs/OSS-READINESS.md)。

## 凭据与网络边界

- **凭据透传**：用户的 Codex 客户端继续自行负责账号登录与 Token 刷新。Reflow 仅在转发时将客户端自带的 `Authorization` 等凭据送往固定上游，本身不读取 `auth.json`，不参与鉴权逻辑管理，也不会记录或留存凭据。
- **历史隔离**：内存中的续接历史按凭据与账号隔离。使用 Magpie 的 `X-Magpie-Account` 指定账号时，该字段也参与隔离；切换、增加或移除指定账号不会自动复用另一账号的缓存历史。它不替代网关鉴权；[缓存隔离修复](docs/evidence/magpie-external-account-scope-2026-10-31.json)与后续[外置模拟联调](adapters/magpie/EXTERNAL.md)分别记录。
- **本地监听**：服务默认仅监听本地回环地址 `127.0.0.1:18516`，默认将请求发送至官方地址 `https://chatgpt.com/backend-api/codex`。

若本机依赖网络代理，启动 Reflow 的进程需要带入已有的 `HTTP_PROXY` / `HTTPS_PROXY`，并让 `NO_PROXY` 包含本地回环地址。Reflow 使用 Go 的环境代理设置，不自动读取 Windows 系统代理配置。`/healthz` 正常只说明本地服务已启动，不证明它能访问官方上游；本次桌面测试的环境遗漏及修正见[记录](docs/DESKTOP-DOT-2026-11-05.md)。

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

dev.5 补充实际续接或停止的固定原因计数，以及最多 64 个推理 token 数字样本；核心规则没有改变。字段与局限见[决策诊断说明](docs/DECISION-DIAGNOSTICS.md)。

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

Windows amd64 本机、macOS arm64 CI，以及 11 月 4 日默认 Ubuntu amd64 runner 已有原生客户端和打包构件的离线执行证据。默认三平台 CI 的协议/插件/Pi 普通及 race 检查通过；托管 Windows 写入仍失败，Linux arm64/macOS amd64 尚缺原生验证。Ubuntu 此前失败和固定发行版配置下的通过记录均保留，不推导为所有 Linux 主机可用。最新范围见[原生 CI 记录](docs/NATIVE-CI.md)与[兼容性](docs/COMPATIBILITY.md)；此前 [dev.2](docs/VERIFICATION-0.1.0-dev.2.md)与 [dev.1](docs/VERIFICATION-2026-10-26.md)记录继续保留。

这些模拟测试只证明已覆盖场景的行为符合预期，不替代前文单列的真实账号证据。真实 Token 自动刷新、dot 的其他功能、跨连接恢复的所有边界和实际模型输出质量仍未验证。

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

CPA 使用单独的 Go 模块；根目录的 `go test ./...` 不会测试该模块，需另外运行：

```sh
cd adapters/cpa
go test ./...
go test -race ./...
go vet ./...
```

CPA 还需 C 编译器及原生 ABI 模拟宿主检查。根目录的 `cpa-packages.yml` 会串行检查五个平台，并分别验证打包前后的动态库。它只生成候选构件，不发布 Release；详见[开发说明](docs/CPA-INTEGRATION.md)。

真实客户端的隔离测试默认跳过。设置 `REFLOW_CODEX_BIN` 指向 Codex CLI，或设置 `REFLOW_PI_CLI` 指向 Pi 1.4.0 的 `dist/bundle/cli.js` 后，可以运行对应测试；`REFLOW_NODE_BIN` 指定 Node，`REFLOW_PROXY_BIN` 指定待验收的 Reflow 构件，`REFLOW_PLUGIN_MARKETPLACE` 指定已打包的本地插件市场目录。测试自行创建合成凭证，不读取现有账号。

PowerShell 下可使用 `scripts/verify.ps1` 保存验证记录，使用 `scripts/build.ps1 -AllPlatforms -WithCodexPlugin` 生成五个平台的独立服务和插件包。构建需要 Go 1.26 和 Python 3.9+；验证脚本的 `-PluginMarketplace` 参数对应上述插件目录。构件存放在版本号和时间戳目录中，不覆盖旧构件。

## 来源与致谢

Reflow 建立在社区先行者的探索之上，完整保留并致谢以下上游项目的代码成果与开源许可证：

- `chatwithgod/cpa-plugin-codexreflow`
- `uf-hy/cpa-plugin-codexcomp`
- `dzshzx/codexcomp`
- `neteroster/CodexCont`
