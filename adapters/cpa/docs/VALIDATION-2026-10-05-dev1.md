# dev.1 · 断流复现、修补与隔离回归

日期：2026-10-05。开发构件 `0.1.0-dev.1`，Windows amd64；CPA/SDK `8.0.13`，宿主 commit `d7914afd`。

## 原因与证据

用户启用 `0.1.0-dev` 后仍不回答。客户端日志是 `upstream_error`，而非先前的 `upstream_eof`。
当时 WebSocket 已关闭，思考 token 为 0 的普通响应也失败，不能把这次故障归因于 516 或 WS。

真实 CPA HTTP Codex executor 用 `bufio.Scanner` 把 SSE 分成行，去掉换行后原样交给插件。
控制行与数据行于是成为两个独立回调：

```text
callback 1: event: response.created
callback 2: data: {"type":"response.created", ...}
```

旧解码器拼成 `event: response.createddata: {...}`，将其当作未结束的控制行；后续事件全部累积，
到 EOF 才报残缺事件，插件生成 `response.incomplete / upstream_error`。原生模拟只覆盖带换行的 SSE 和裸 JSON，遗漏了真实宿主的控制行形状。

在独立 CPA 实例、同一份合成回答中：

| 构件 / 配置 | 上游输出 | 下游结果 |
|---|---|---|
| 旧构件，插件关闭，带控制行 | 完整 | completed，回答完整 |
| 旧构件，插件开启，无控制行 | 完整 | completed，回答完整 |
| 旧构件，插件开启，带控制行 | 完整 | incomplete / upstream_error，仅终止错误，无回答 |
| dev.1，插件开启，带控制行 | 完整 | completed，回答完整 |

这是稳定复现的插件兼容性缺陷；没有记录线上响应原文，也不声称已排除真实环境中的所有其他故障。
修补只在 JSON 外，前一条待结束控制行与下一回调的 SSE 字段之间恢复分隔，不改 JSON 内容或生产宿主。

## 本次实际验证

- `go test ./... -count=1`、`go test ./... -race`、`go vet ./...`：通过。
- 解码器 fuzz：15 秒预算，80,025 次执行，通过。
- 真实 DLL + 模拟 C ABI 宿主：14 项通过，其中新增 CPA 去换行逐行回调的正常、续写、工具、上游取消 4 项。
- 发布防误打包 Python 单元测试：6 项通过。
- 真实 CPA 进程 + 本地合成上游：8 项通过：
  - HTTP：插件关闭基线、开启无控制行、开启带控制行、带控制行续写、带控制行工具事件。
  - WS：正常回答、续写、工具事件；客户端及上游均实际 WS，断言没有 HTTP 回退。
  - 断言完整文本/工具参数、单终止事件、序号、response ID、轮数及合成多轮用量，不只是收到 HTTP 200。

隔离测试使用独立临时目录、端口、空 OAuth 目录及固定的虚构凭证，仅指向本地合成上游。
未读取生产账号文件，未改动生产配置，主动发起的可计费模型请求为 0；测试结束已停止隔离 CPA 进程。

dev.1 DLL SHA256：

```text
5c205a037448f6dea78c70ce9173ee60013ea313f1f01b70e1a4c28c679605da
```

旧部署 DLL SHA256（用于复现）：

```text
636f47a1682908e4298aa59a24705cfe4e3c4a89718256ceea2fdb82f09c228b
```

## 修补验证时的部署状态与未验证项

生产管理接口读回：CodexReflow 已关闭，CodexComp 也关闭，原部署 DLL 未替换。
Codex provider 的 `supports_websockets=false` 保持不变；其他已启用插件未改动。
dev.1 只构建在本地项目，等待明确授权后备份/替换及用户客户端验收。

真实 OpenAI 账号、Codex Desktop、工具执行后回传、多轮增量上下文、预热、断开重连、并发和真实取消仍未通过验收。
不以合成测试、管理接口成功或 516 统计代替这些验收；尚未推送、发布或上架。

## 用户授权替换 · 2026-10-05 03:30 +08:00

用户确认继续后，已将 dev.1 放入生产插件目录，使用独立版本化文件名
`codexreflow-v0.1.0-dev.1.dll`，不覆盖 CPA 可能仍持有句柄的旧 DLL。
旧 DLL 与完整 CPA 配置已备份，旧构件也保留在原目录；管理接口已选中新路径。

再次直接读取已安装 DLL 运行原生模拟：实际版本 `0.1.0-dev.1`，14 项通过，SHA256 与上述构件一致。
CodexReflow 和 CodexComp 仍关闭；因此生产内未注册或执行，不能把新路径识别当作真实客户端验收。
CPA/Codex/ECPA 三个配置文件的 SHA256 均未变化，其他插件的文件与启用状态也未变化。
没有重启 CPA、修改 WebSocket 设置或发起真实模型测试。下一步由用户单独启用 CodexReflow，在现有 HTTP 通道做客户端验收。
