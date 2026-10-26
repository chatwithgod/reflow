# Pi 客户端接入（Pi 1.4.0）

Reflow 已提供 `reflow.ts` 扩展，方便在 Pi 终端中使用自动续接。

该扩展仅通过 `pi.registerProvider` 覆盖内置 `openai-codex` 的服务地址，指向 `http://127.0.0.1:18516/backend-api`。Pi 原有的模型列表、OAuth 登录与 Token 刷新实现继续由 Pi 管理；当前未适配其他提供商，包括新的 `openai` 提供商。

先启动 Reflow，再执行：

```sh
pi --extension /absolute/path/reflow.ts --provider openai-codex --model <你的模型名称>
```

按 Pi 原有流程完成登录即可。若 Reflow 使用其他端口，可通过环境变量 `REFLOW_URL` 指定本地回环 HTTP 地址。

扩展不会自行改写 `models.json` 或 `auth.json`。去掉 `--extension` 参数并重新启动 Pi，即可去掉这次会话的地址覆盖。若已有 `models.json` 配置了提供商或模型级地址，要检查最终地址；Pi 的配置覆盖可能优先于扩展。

验证基线为 Pi 1.4.0：临时目录、合成 OAuth 凭证、本地模拟上游，SSE 和 WebSocket 两条路径均实际执行 `read` 工具并回传结果。真实账号、刷新流程及其他 Pi 版本尚未验收。

接口依据：[Pi 自定义提供商文档](https://github.com/earendil-works/pi/blob/d5b3de22d0e24a3e9c38a9410d3329b099717283/packages/coding-agent/docs/custom-provider.md)。
