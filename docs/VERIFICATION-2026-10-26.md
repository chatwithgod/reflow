# 0.1.0-dev.1 开发验证

这是开发记录，不是生产部署或模型质量认证。没有调用真实账号或计费模型，也没有修改生产 CPA/ECPA/Codex 配置。

## 固定基线

- 原始 CPA Reflow：`9b261194c416f8affab23c9bf02448cc022f2cf2`。
- Go：`go1.26.8 windows/amd64`。
- 本机 Codex CLI：`0.164.0-alpha.11.1`。
- Pi npm 包：`@earendil-works/pi-coding-agent@1.4.0`；Node `v24.17.0`，仅在忽略目录中安装，禁用安装生命周期脚本。
- Windows 构件 SHA256：`3f305ecf1925a7d1fa36e6f601e0891b8a4832371e79643159631b48ed962aa3`。

## 已覆盖的行为

| 层次 | 证据与范围 |
| --- | --- |
| 核心 | 续接预算、无加密状态、未知父响应不做不完整重放、用量合并、中间工具隔离、失败终止、输入不变、缓冲限制与 JSON/SSE 解码 |
| HTTP | 实际回环连接；工具结果的下一次请求；压缩和模型目录透传；客户端断开；追加轮失败；gzip/zstd 请求；拒绝跨源重定向跟随 |
| WebSocket | 实际回环握手；预热；完整续接；父响应 ID 映射；下一轮工具结果；两个命名通道 |
| Codex CLI | 使用临时目录与合成 ChatGPT 登录文件；全程 WebSocket；3 次模拟推理请求；实际调用一次本地只读 MCP 工具；被舍弃工具调用零次；无 HTTP 回退 |
| Pi CLI | 使用临时目录与合成 OAuth 文件，实际加载 `adapters/pi/reflow.ts`；SSE 与 WebSocket 分别完成 3 次模拟请求，实际读取合成文件并回传；未读取被舍弃轮次的文件 |
| 构件 | 上述两种 CLI 均通过同一 Windows EXE，而非仅通过测试进程中的 Go handler |

完整验证为 37 个通过项（包含子测试和 fuzz 种子），0 个跳过；race、vet 和额外 5 秒解码器 fuzz 通过。它不表示 37 种互不重复的真实生产场景。

原始记录保存在忽略目录 `build/verification/20261026-143503-850/`：`tests.jsonl`、`race.jsonl`、`vet.txt`、`fuzz.txt` 和 `summary.json`。所有凭证与模型响应均为合成数据。

构件位于 `dist/0.1.0-dev.1/20261026-142557-811/`。Windows amd64、Linux amd64/arm64、macOS amd64/arm64 均完成交叉编译与 ZIP 校验。Linux/macOS 没有在对应操作系统运行；清单中的 `runtime_tested: false` 是构建当时的状态，之后的 Windows 验证以本记录和 SHA256 为准。

## 已纠正的测试误判

首次 CLI 测试只检查工具返回文本含标记。实际 shell 命令被隔离策略拒绝，错误文本仍包含命令标记；加强退出状态断言后发现此误判。该次失败保存在 `build/verification/20261026-141025-919/`。

现改用本地只读 MCP fixture，直接统计工具服务的真实调用次数，并核对结果回传。还补齐模拟上游的 WebSocket 支持和消息大小限制，显式要求没有 HTTP 回退。当前通过记录使用这些更严格的断言。

## 仍需验收

- 真实 ChatGPT/OAuth 账号、Token 刷新和模型实际续接效果。
- Codex Desktop 和 dot 的完整流程。
- 跨连接恢复、缓存过期与丢失父响应、WebSocket 中途取消等完整边界。
- Linux/macOS 原生运行与客户端接入。
- Codex 原生插件入口、Magpie 适配。
- 有真实任务评分依据的开关对照评测。

官方接入依据：[内置提供商地址覆盖](https://learn.chatgpt.com/docs/config-file/config-advanced)、[WebSocket 预热和增量请求](https://developers.openai.com/api/docs/guides/websocket-mode)。
