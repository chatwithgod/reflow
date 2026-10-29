# Codex for OSS 申请草稿

表单字段于 2026-10-27 核对，项目事实于 2026-10-30 更新。草稿未提交；独立源码现已公开于 [chatwithgod/reflow](https://github.com/chatwithgod/reflow)，三平台离线 CI 记录见 [公开证据](PUBLICATION-2026-10-28.md)。带客户端的 Windows 回归基线为 `fa2c622`，真实调用累计数见 [最新验证](LIVE-LEDGER-WORKSPACE-2026-10-30.md)。个人资料仍未填写。

申请表要求公开的 GitHub 账号和仓库链接，选择主要或核心维护者身份；项目价值、API 额度用途和补充说明三段文字各限 500 字符。具体字段以提交时的 [官方申请表](https://openai.com/form/codex-for-oss/) 为准。[计划介绍](https://developers.openai.com/community/codex-for-oss)允许规模较小但有生态价值的项目说明理由，不代表一定入选。

下面按现有事实说明跨客户端兼容性与可复现维护价值。没有把回归测试计数写成采用量，也没有声称续接能提高回答质量。三段英文同时保存在 [结构化文本](oss-application-fields.json)，便于核对和复制；字符数包含空格与标点，不包含字段名。

## 项目价值：466 字符

Reflow is an early-stage standalone Go engine and local proxy for budget-bounded continuation, decoupled from CPA. It holds intermediate outputs while preserving retained tool calls, usage totals, and client-managed login. Integrations are prepared for Codex CLI, app-server, a Codex plugin, and Pi 1.4.0, with local Magpie patches. Its 79 passing regression checks use synthetic upstreams. The aim is reproducible maintenance of cross-client protocol compatibility.

中文意思：独立 Reflow 的价值在于让多客户端共享有限预算的续接、工具调用和用量处理，并提供可复现的兼容性检查；目前仍是早期开发项目。

## API 额度用途：373 字符

Credits would fund planned maintenance: small-batch, budget-capped API runs checking protocol compatibility, tool-use round-trips, and disconnect recovery. We would reproduce failures, compare upstream versions, review fixes, and validate releases. These proposed API workloads are separate from our previous ChatGPT subscription tests, which are not an API-spend baseline.

中文意思：这是未来 API 维护工作的用途草稿，包括有限批次的协议、工具往返和断连验证。既有 ChatGPT 订阅测试不作为 API 花费依据。本草稿不预选申请项目，只有决定申请 API 额度时才使用这一段。

## 补充说明：476 字符

The source is public; no packaged release or verified adoption data yet. Twelve native-login sessions produced 69 inference requests and two continuations. One run continued, returned a matching tool result, scored 18/18 and ended normally, but had two command failures. The latest run finished 18/18 with no tool failures and no continuation. These separate sessions do not prove the complete chain. Desktop/dot UI is pending; local Magpie patches are not submitted upstream.

中文意思：最新已有续接、匹配工具回传和正常结束的同会话证据，但两次命令失败的对应关系未明，严格验收仍未通过。后续诊断没有触发续接；继续如实说明公开发布、社区采用和界面验收方面的缺口。

## 各项说法的依据

| 申请说法 | 可核对的本地依据 |
| --- | --- |
| 独立核心、客户端接入和插件入口 | [兼容性说明](COMPATIBILITY.md)、[插件说明](../plugins/codex/README.md)、[Pi 适配](../adapters/pi/README.md) |
| 79 个回归通过项 | [app-server 验证](APP-SERVER-2026-10-27.md)；含子测试和 fuzz 种子，模拟上游，0 个测试跳过 |
| 公开源码及三平台离线 CI | [仓库](https://github.com/chatwithgod/reflow)、[修复提交](https://github.com/chatwithgod/reflow/commit/23eb3bef11f2cb5951599d08ca6ecd76a946619d)、[通过的 CI](https://github.com/chatwithgod/reflow/actions/runs/40679721072)；各 69 个通过项，4 个客户端联调跳过 |
| 原生登录 12 次会话、69 次推理请求、2 次续接 | [续接对账任务](LIVE-LEDGER-2026-10-30.md)与[最新验证](LIVE-LEDGER-WORKSPACE-2026-10-30.md)；最新为 18/18、工具失败 0、续接 0，不能跨会话合并验收；本轮记录尚未推送 |
| 官方 API 1 次会话、2 次推理请求、0 次续接 | [API 流式与工具回传](LIVE-API-KEY-2026-10-29.md)；专用 Responses 客户端，固定本地函数执行与最终答案核对通过；记录已随 `e2f4dda` 公开 |
| Ubuntu 固定配置下的离线写入恢复 | [获批手动对照](https://github.com/chatwithgod/reflow/actions/runs/40824531617)；同一 runner 写入 0/5 到 5/5，隔离边界和清理通过；明确 ABI 告警例外，默认 CI 失败保留 |
| Magpie 本地补丁 | [补丁清单](../adapters/magpie/patches/manifest.json)、[PR 草稿](../adapters/magpie/PR-DRAFTS.md)；公开模块及设置页检查见[最新记录](../adapters/magpie/PUBLIC-MODULE.md)，宿主全量仍未通过 |

官方版实测记录已随 [fdef7b5](https://github.com/chatwithgod/reflow/commit/fdef7b50c1fe93130f02bb500f16aa90c3a07562) 及其前序提交公开。申请时可引用上述固定提交及 CI 链接；最新宿主对照状态见 [Ubuntu 对照记录](LINUX-SANDBOX-CONTROL.md)。Magpie 补丁仍未提交上游，不能写成已合并贡献。

公开仓库 URL 已补入草稿。提交前仍需填写姓名、ChatGPT 账号邮箱和 GitHub 账号，确认个人资料可见性、维护者身份、申请哪些支持及所需的组织信息。尚未收集独立版采用数据，相关指标暂不填写。Desktop/dot 暂留未验收，申请草稿没有改变工程验收状态。二进制发布、上游提交和正式申请仍按 [计划](../PLAN.md) 分别处理。
