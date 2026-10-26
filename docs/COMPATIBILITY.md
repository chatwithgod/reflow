# Reflow 兼容性（0.1.0-dev.3）

Reflow 是独立 Go 服务，不依赖 CPA SDK。以下记录的是已运行的验证，不把交叉编译、模拟上游或健康检查当作真实账号验收。

| 接入方式 | 版本与范围 | 已验证行为 |
| --- | --- | --- |
| Codex CLI | `0.164.0-alpha.11.1` | 真实客户端、合成 ChatGPT 凭据和模拟上游下，WebSocket 续接、最终 MCP 工具执行及结果回传通过 |
| Pi | `1.4.0` 的 `openai-codex` provider | 保留内置 OAuth 和模型目录，只改请求地址；SSE、WebSocket、工具执行与回传通过。新的 `openai` provider 未适配 |
| Codex 原生插件 | 本地开发包 | 在临时 `CODEX_HOME` 注册市场、安装缓存二进制；4 个 stdio MCP 工具通过，真实会话经 Code Mode 调用 `status` 通过。插件提供配置与诊断，代理服务需独立启动 |
| Magpie | 固定提交 `a1174674da9d1435443e95ffac7d0300ce8b59d6` 加本地补丁 | 原生 HTTP、zstd、上游 WebSocket、托管 Responses 透传四条路径的模拟续接和 race 通过。补丁未提交上游 |

Windows amd64 已原生运行。Linux/macOS 的 amd64、arm64 目前仅交叉编译通过，尚未原生运行验收。

独立代理还覆盖 HTTP/SSE、预热、取消、gzip/zstd 请求、compact 透传、多轮恢复与缓存隔离。上述协议回归主要使用模拟客户端/上游，不能推导为 Desktop/dot 已验收。详情见 [dev.3 验证记录](VERIFICATION-0.1.0-dev.3.md)。

## Magpie 边界

可信 Go 扩展 `gwexec` 只进入流式 Responses 兼容直通路径；跨协议、非流式和 compact 旁路。可选 `reflow` 构建标签启用桥接代码，`maxContinue` 默认 0，显式设置 1–7 才注册续接。尚无公开可引用的 Reflow Go 模块版本，当前通过本地 `go.work` 关联源码。

Windows 普通 GUI 构建、Windows `nogui reflow` 构建、Linux `nogui` 构建通过。Magpie 全量 `nogui` 测试为 12180 个通过项、615 个跳过项、60 个失败项。改进隔离环境后，对原失败项进行复查，干净上游和修改版均为 12 通过、0 跳过、50 失败，失败集合相同。这是选定失败项的对照，不是双边全量通过，也未确定所有失败根因。见 [宿主证据](../adapters/magpie/VERIFICATION.md)。

## 尚未完成

真实账号的推理续接与登录刷新、Codex Desktop/dot、Linux/macOS 原生运行、生产接入和公共发布均未完成。评测器的 4 项任务、34 个检查点已自检，尚无真实模型的质量结果。插件安装成功或 `/healthz` 正常，只说明相应组件可用，不证明模型请求已经经过 Reflow。
