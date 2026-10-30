# Pi 客户端接入（Pi 1.4.0）

Pi 1.4.0 的两种 OpenAI 入口使用不同的上游地址。Reflow 提供两个独立扩展，模型目录、登录与 Token 刷新继续由 Pi 管理。

| Pi provider | 扩展 | Reflow 默认端口 | Reflow 上游 | 当前模拟验证 |
| --- | --- | --- | --- | --- |
| `openai-codex`（Pi 标为 legacy） | `reflow.ts` | 18516 | `https://chatgpt.com/backend-api/codex` | 合成 OAuth，SSE 与 WebSocket |
| `openai` | `reflow-openai.ts` | 18517 | `https://api.openai.com/v1` | 合成 ChatGPT OAuth 与 API key，SSE |

## Pi 的新 OpenAI 入口

先启动专用 Reflow 实例：

```sh
reflow -listen 127.0.0.1:18517 -upstream https://api.openai.com/v1
pi --extension /absolute/path/adapters/pi/reflow-openai.ts --provider openai --model <你的模型名称>
```

通过 Pi 的 `/login` 选择 OpenAI 的 ChatGPT 登录，或使用该 provider 原本支持的 API key。选择该账号可用的模型。新的 Sign in with ChatGPT 需要自己的客户端注册和套餐使用授权；现有 Codex 登录不等同于这项授权。该 OAuth 路径使用公共 Responses API，要求 `store: false` 和 `stream: true`，参见[官方推理说明](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference)与[登录流程](https://developers.openai.com/siwc/token-sharing-open-source/sign-in)。

新扩展保留模型的官方 `baseUrl`，复用 Pi 的 Responses 实现，仅通过请求级 `fetch` 把 `POST /v1/responses` 转到本地 Reflow。这样保留 Pi 对 ChatGPT OAuth 的字段限制、API key 行为、事件解析和用量处理。它不接管登录、模型目录查询、图片或分类接口。与其他配置发生地址冲突时明确报错；不会把自定义网关悄悄改接到官方服务。本地 Reflow 失败后也不会直接回退到上游。

必须保留扩展旁的 `lib/openai-transport.mjs`。Pi 1.4 的扩展加载器通过根 SDK 导入提供兼容 API；使用此加载方式已在实际 CLI 中验证。没有修改 Pi 的安装文件。本入口尚未证明 WebSocket 或其他 Pi 版本兼容。

## 旧 OpenAI Codex 入口

```sh
reflow -listen 127.0.0.1:18516
pi --extension /absolute/path/adapters/pi/reflow.ts --provider openai-codex --model <你的模型名称>
```

该扩展仅覆盖 `openai-codex` 的服务地址为本地 `/backend-api`，保留旧入口原有的模型目录和 OAuth 行为。已有 `models.json` 的模型级地址可能优先于扩展，应核对最终地址。

两个入口均可通过 `REFLOW_URL` 指定其他回环 HTTP 地址。去掉对应 `--extension` 参数后，Pi 恢复原有行为。扩展不会自行改写 `models.json` 或 `auth.json`。

## 验证范围

临时目录、合成凭据与本地模拟上游下，表中四条正向路径均完成模拟续接、实际 `read` 工具执行和结果回传，被舍弃轮次的读取没有执行。负向对照确认：只改新入口的 `baseUrl` 会带上 ChatGPT 登录不支持的请求字段。另有五项无账号检查覆盖回环地址、请求正文与头部、路由范围、取消和禁止回退。

真实 Pi 账号、浏览器登录、Token 刷新及其他 Pi 版本尚未验收。Codex CLI 的真实成功记录不替代 Pi 的账号验收。完整范围见[新入口验证记录](../../docs/PI-PUBLIC-RESPONSES-2026-10-30.md)，另有[只读账号探针](../../docs/PI-OAUTH-PROBE.md)。接口依据还包括[Pi 自定义提供商文档](https://github.com/earendil-works/pi/blob/d5b3de22d0e24a3e9c38a9410d3329b099717283/packages/coding-agent/docs/custom-provider.md)。
