# Reflow (0.1.0-dev.1)

Reflow 是一个运行在本地的轻量代理服务，用于为 Codex 终端提供长思考过程的自动续接支持。

当模型输出符合特定用量特征、携带加密推理状态且仍在设定的轮次预算内时，Reflow 会在后台自动发起续接请求。在此期间，服务会暂存中间的回答内容与工具调用，并在达到停止条件后，将保留的最终结果与整理后的总用量合并返回给 Codex。

续接会在后台增加上游请求次数和等待时间；常见的“516”特征也只是触发判断的一种启发式线索，无法作为推理是否充分展开或输出质量好坏的确定依据。

## 当前状态

Reflow 的核心逻辑源自 `chatwithgod/cpa-plugin-codexreflow`，经过提取、解耦与适配后，转为不依赖 CPA SDK 的独立 Go 程序。

当前版本为 `0.1.0-dev.1`，处于早期开发阶段：

- 目前支持直接从源码构建，**尚未公开发布正式的二进制文件或安装包**。
- 已针对 Pi 1.4.0 提供适配扩展（`adapters/pi/reflow.ts`），可以在保留原有登录与模型列表的前提下按需挂载。见 [Pi 接入说明](adapters/pi/README.md)。
- Codex 原生插件接入以及 Magpie 支持目前均未完成。

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
```

服务运行后，可通过浏览器或命令行查看健康状态：
`GET http://127.0.0.1:18516/healthz`

### 2. 客户端配置与手动还原

目前没有配套自动切换或恢复工具，修改配置时需要手动操作：

1. **记录原有配置**：修改前，先记下你当前 Codex 配置里的 `openai_base_url`（如果有）。
2. **连接本地代理**：将 Codex 的用户级 `openai_base_url` 指向 `http://127.0.0.1:18516`。继续保留内置的官方 provider 即可，无需创建 `model_providers.openai`。
3. **手动还原设置**：停止或退出 Reflow 服务前，请手动把 `openai_base_url` 改回原样或直接删除该字段，避免后续请求因端口无响应而报错。

## 验证范围与局限

当前开发版已在本地模拟环境下验证了以下覆盖场景：

- 续接过程中的工具隔离与上下文串联
- 下一轮交互所需的父响应 ID 衔接
- WebSocket 连接预热与多通道并发
- HTTP 请求取消与压缩请求处理

近期在本地模拟环境下补充了两组真实 CLI 的链路验证：

- **Pi CLI 1.4.0**：临时隔离环境配合合成 OAuth 凭证，跑通 SSE 与 WebSocket 双路径的续接流程。内置 `read` 工具读取合成文件，工具结果回传；被舍弃轮次的读操作没有执行。
- **Codex CLI 0.164.0-alpha.11.1**：使用合成 ChatGPT 凭证，纯 WebSocket、无 HTTP 回退，实际执行一次本地只读 MCP 工具，并回传结果。此前 shell 工具测试有过断言误判，已修正并保留失败记录。

同一 Windows 构件已通过上述 CLI 验证；Linux/macOS 构件当前仅完成交叉编译。详细范围见 [验证记录](docs/VERIFICATION-2026-10-26.md)。

这些测试只证明已覆盖场景的行为符合预期，不等同于真实线上账号的 OAuth 验收，也尚未验证真实 Token 自动刷新、Codex Desktop / dot、跨连接恢复的完整边界或实际模型输出质量。

## 开发与复现

需要 Go 1.26。核心及代理测试默认只调用回环模拟上游：

```sh
go test ./...
go test -race ./...
go vet ./...
```

真实客户端的隔离测试默认跳过。设置 `REFLOW_CODEX_BIN` 指向 Codex CLI，或设置 `REFLOW_PI_CLI` 指向 Pi 1.4.0 的 `dist/bundle/cli.js` 后，可以运行对应测试；`REFLOW_NODE_BIN` 指定 Node，`REFLOW_PROXY_BIN` 指定待验收的 Reflow 构件。测试自行创建合成凭证，不读取现有账号。

PowerShell 下可使用 `scripts/verify.ps1` 保存验证记录，使用 `scripts/build.ps1 -AllPlatforms` 生成五个平台的本地构件。构件存放在版本号和时间戳目录中，不覆盖旧构件。

## 来源与致谢

Reflow 建立在社区先行者的探索之上，完整保留并致谢以下上游项目的代码成果与开源许可证：

- `chatwithgod/cpa-plugin-codexreflow`
- `uf-hy/cpa-plugin-codexcomp`
- `dzshzx/codexcomp`
- `neteroster/CodexCont`
