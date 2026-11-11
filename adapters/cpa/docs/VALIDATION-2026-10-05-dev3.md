# dev.3 · WebSocket 后继上下文衔接与续写证据

日期：2026-10-05。开发构件 `0.1.0-dev.3`，Windows amd64；CPA / SDK `8.0.13`。
构建和修补阶段只修改项目代码及隔离测试，不部署生产 DLL，不修改生产配置，不调用真实模型。
后续独立授权安装记录见本页末尾，不将部署注册验证混同于真实模型验收。

## 问题与修补

旧版把隐藏追加轮折叠成一个客户端响应，保持第一轮 ID，但上游缓存可能已经推进到最后一轮。
下一次客户端仍引用第一轮 ID，就可能遇到 `previous_response_not_found`。
这与 [OpenAI 官方 WS 文档](https://developers.openai.com/api/docs/guides/websocket-mode) 中连接缓存、
`store=false` 无持久化回退的语义相符；不代表已经证明每条线上同码错误的因果。

修补保持客户端整个流的响应身份不变：

1. 折叠成功终止后，保存可见 ID → 最终上游 ID 的别名。
2. 下一次原生 WS 请求仅在同连接、原始模型和通道的已知 ID 命中时改写父 ID。
3. 工具回传和文本增量不变，不删除父 ID、不伪造终止 ID、不重放客户端增量。
4. 原生凭证选择、固定账号、连接策略和原生错误处理不变；原生增量生成不追加思考。
5. 使用可信 host `execution_session_id`，不采用客户端会话头作为连接身份。只保存 ID 和运行标识，
   不缓存提示词、完整上下文、回答或加密推理；最多 4096 项、TTL 一小时，shutdown 清空。
6. 终止输出失败时只撤销本次别名修订，避免误删并发的新修订。未知父 ID 或作用域不符保留原生处理。

首个 dev.3 候选在真实隔离 CPA 中失败：`ws_context_bridge=not_applicable`。
原因是 CPA self-executor 已把输入格式转换为插件声明的 `codex`，代码却只接受转换前的
`openai-response`。本次修正，并用实际后继请求验证，未仅依据单元测试宣布修复。
依据为固定 SDK `internal/pluginhost/adapters_executors.go` 的 `prepareExecutorCall` / `buildExecutorRequest`。

## 新增诊断

终止事件保留原有 `proxy_rounds` / `proxy_billed_usage` / `proxy_stopped_reason`，另添加 `proxy_reflow`。
默认 INFO `fold_finished` 日志独立于 `debug_log`，按一次折叠生成 run ID，不复用 WS 请求/连接 ID。

| 字段 | 解释 |
|---|---|
| `run_id` | 独立折叠标识；不是账号、会话或上游响应 ID |
| `rounds_started` | 尝试开启的轮数，不是已确认计费请求数 |
| `rounds_completed` | 收到终止事件的轮数，含失败/不完整终止；不保证成功 |
| `continuations_started/completed` | 对应轮数扣除首轮的追加计数 |
| `stop_reason` | 正常、预算、缺少状态、上游错误/EOF/失败/不完整等停止分类 |
| `ws_context_bridge` | ID 衔接是否注册、是否需要或缺少作用域等 |
| 日志 `result` / `emission` | 终止类型/执行结果与宿主输出接受情况 |

`host_accepted` 不等于客户端实际接收确认。父 ID 改写另写 `ws_parent_remapped`，引用来源 run ID。
新增日志不含请求、提示词、回答、凭证、原生响应 ID、加密内容；并非每个绕过请求都会记录日志。
错误日志不再把缺失终止或上游失败误标为正常。

## 本次实际验证

| 验证 | 结果与边界 |
|---|---|
| Go 单元测试 | 通过；新增作用域、TTL、LRU、修订撤销、并发、增量原样保留和错误诊断测试 |
| Go race | 通过；缓存并发测试包含 32 个作用域各反复写读同一个可见 ID |
| Go vet | 通过 |
| 解码器 fuzz，15 秒预算 | 通过，89,065 次执行；不是质量测试 |
| 发布防误打包 Python 测试 | 6 项通过 |
| 原生 Windows DLL + 合成 C ABI 宿主 | 29 项通过；保留原 20 项，新增 EOF/failed/incomplete 三种负载形状；终止 metadata 与日志逐字段一致 |
| 真实隔离 CPA + 自动选择合成 HTTP/WS 上游 | 23 项通过 |
| 真实隔离 CPA + 独立旧白名单回归 | 8 项通过 |
| 真实隔离 CPA + 严格连接缓存 WS 回归 | 13 项符合预期；详情如下 |
| 旧 dev.2 DLL 对照 | `--expect-defect` 验证旧后继请求失败，不能将“符合诊断预期”称为功能通过 |

严格 WS 集覆盖：插件关/开与普通/516 对照；一次/多次追加后的第二、第三个请求；合成工具回传；
完整重放；新连接不能借用旧别名但可完整输入恢复；原始模型前缀/后缀；原生增量 516 不被追加；
配置重载的关/开插件对照；两个并发连接都显示 `resp_1`、却分别衔接 `resp_2` / `resp_3`，且 run ID 不同。
所有该集上游调用均为实际 WS，无 HTTP 回退。

配置重载新增测试最初要求旧连接直接继续，实际失败。隔离日志确认固定 CPA 关闭上游执行器
（`reason=executor_shutdown`），插件关闭的对照也复现；修订测试验证新连接完整重放恢复及
`max_continue: 0` 的真实生效，不声称插件支持跨宿主重载的无缝会话连续性。

原 23 / 8 项存在重复基线，WS 集也包含控制组；不将各组相加宣传为互不重复的验收场景。
合成加密字段只是虚构测试值，不构成真实推理签名或模型上下文接受验证；实际签名检查仍由宿主处理。

本地报告在忽略目录 `build/`：
`unit-tests-dev3.jsonl`、`native-smoke-dev3.json`、`isolated-auto-models-dev3.json`、
`isolated-legacy-dev3.json`、`ws-incremental-dev3.json`、`ws-incremental-dev2-control.json`、`validation-dev3.json`。

本地 DLL SHA256：

```text
e8cc23d80e1828da0e7a34718d0aa5341ff105e3c965c9d85c7e50918e88f071
```

## 发布与验收边界

- 构建/修补阶段未安装生产环境；后续授权安装见下节。其他分支的问题不在本次排查范围。
- 真实账号、Desktop、多模型效果、客户端取消、超时、长会话、通道 multiplexing/fork 仍未验收。
- 原生 `previous_response_id` 生成仍绕过续思考折叠；它们的 516 记录可能继续出现。
- 原始用量记录不会因输出合并而消失；有追加轮也不保证回答质量提高。
- CI 文件不是跨平台运行证据；仅实际验证 Windows amd64。
- 未创建 GitHub 仓库、提交/推送、发布 Release 或提交插件商店。

## 后续独立授权部署

2026-10-05 16:20（北京时间），用户在“备份后安装 dev.3”的建议后要求继续。
以相同 SHA256 的版本化 DLL 本地安装，CPA / SDK 仍为 `8.0.13`。

- 先备份 CPA / ECPA / Codex 配置和所有已有插件 DLL，并核对备份哈希。
- 保留旧 dev.2 文件，不覆盖原 DLL；通过 CPA 支持的本地版本选择器指定 dev.3，未执行商店下载。
- 仅改变 `plugins.configs.codexreflow.store.version`；对整个 CPA YAML 的语义比较仅出现该字段。
- 反复读回 dev.3 的选中路径、metadata 版本与 `registered=true` / `effective_enabled=true`。
- 保留原启用状态、`model_mode=auto`、`max_continue=3` 及所有其他 Reflow 选项；CodexComp 仍关闭。
- ECPA / Codex TOML 字节哈希未变；其他插件配置、加载状态及所有原有 DLL 均未变。
- `supports_websockets=true` 未修改；未主动重启 CPA 服务，只触发版本选择配置的热重载。
  配置重载仍可能关闭原生上游执行会话，不能据此宣称已有 WS 会话无缝连续。
- 对已安装文件另跑真实 DLL + 合成 C ABI 的 29 项测试，均通过；未发起生产模型测试请求。

部署回执保存在忽略目录 `.tools/last-upgrade-dev3.json`，安装副本和配置/原 DLL 备份由该回执定位。
这是安装和运行注册证明，不是生产模型执行或新增 ID 桥运行验收；此前构建回执保持其当时的未部署状态。
回滚应通过版本选择器切回 dev.2，保留后续无关配置，不能直接覆盖整份旧配置。

下一步：由用户新开聊天连续发送两轮，先验收后继文本/工具请求；遇到 516 后核对
`proxy_reflow.run_id`、续写计数、停止原因与最终回答。不为消灭 516 而扩大拦截范围。
