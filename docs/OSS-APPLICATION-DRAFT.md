# Codex for OSS 申请草稿

官方项目页和申请表已于 2026-11-05 再次只读核对。Desktop 前序任务、dot 本机读取和历史失败已公开至 1bece8f，对应 CI 没有新增失败；随后新的 Desktop 样本已在同一会话完成真实续接、成功工具往返、18/18、正常结束及保护文件检查，见[新证据](DESKTOP-CONTINUATION-2026-11-05.md)。本草稿准备时，新样本记录仍在本地待公开。运行代码及发布构件未改，仍为固定 3e0ea18 的 [dev.5 预发布版](https://github.com/chatwithgod/reflow/releases/tag/v0.1.0-dev.5)。以下三段各不超过申请表要求的 500 字符，包含空格与标点；可复制文本见[结构化草稿](oss-application-fields.json)。

[官方计划](https://developers.openai.com/community/codex-for-oss)允许申请者说明项目的生态价值，[申请表](https://openai.com/form/codex-for-oss/)同时关注实际使用和持续维护证据。当前 Reflow 是早期项目，申请理由集中在可复用的协议兼容性维护，不声称已被广泛采用或能够提高回答质量。

## 项目价值：471 字符

Reflow is an early-stage MIT Go core and local proxy for budget-bounded Responses continuation, decoupled from CPA. It preserves client-managed login, keeps discarded tool calls from clients, and tracks folded usage. Codex, Pi and external Magpie integrations share protocol regressions. A dev.5 preview is public. We have no verified adoption metrics; the proposed ecosystem value is reusable compatibility checks for tool round-trips, cancellation and history recovery.

中文意思：独立核心、有限预算的续接、工具隔离和用量处理可以减少不同客户端及网关重复维护兼容性的工作；预发布与回归已经公开，但生态价值仍是申请理由，不是已经证实的采用规模。

## API 额度用途：373 字符

Credits would fund planned maintenance: small-batch, budget-capped API runs checking protocol compatibility, tool-use round-trips, and disconnect recovery. We would reproduce failures, compare upstream versions, review fixes, and validate releases. These proposed API workloads are separate from our previous ChatGPT subscription tests, which are not an API-spend baseline.

中文意思：拟把额度用于小批次、设有预算的官方 API 维护检查，覆盖协议、工具往返、断连和发布验证。这是后续用途草稿，既有 ChatGPT 订阅测试不作为 API 花费基线；尚未替用户选择申请 API 额度。

## 补充说明：459 字符

A native ChatGPT-login Desktop session completed continuation, successful tool use, 18/18 and normal completion with protected files unchanged. Dot's file read produced no local Reflow inference requests. Earlier CLI samples retain a config-audit exception. Source CI passes on three OSes; native CI passes Ubuntu/macOS, with hosted Windows write failures. Linux arm64/Intel Mac are build-only. Magpie #4497 is a discussion. No quality gain or adoption claim.

中文意思：原生登录 Desktop 新样本在同一会话完成真实续接、工具成功、18/18 和正常结束，保护文件未变。dot 成功读取本机文件，但该次没有产生本地 Reflow 推理请求。早期 CLI 的配置审计例外保留；Ubuntu/macOS 原生 CI 通过，托管 Windows 写入仍失败，另外两个平台仅交叉编译。Magpie 仍是设计讨论，不宣称质量收益或外部采用。

## 可核对的项目材料

| 申请说法 | 依据与限制 |
| --- | --- |
| 独立核心、客户端与插件接入 | [兼容性](COMPATIBILITY.md)、[插件说明](../plugins/codex/README.md)、[Pi 适配](../adapters/pi/README.md)。Pi 按用户选择通过模拟验收，不再等待真实登录 |
| 可安装的公开预发布 | [dev.5 Release](https://github.com/chatwithgod/reflow/releases/tag/v0.1.0-dev.5)及[核验记录](RELEASE-0.1.0-dev.5.md)：五平台 10 个 ZIP，全部 12 个附件公开下载散列一致；其中两个平台只有交叉编译证据 |
| 共享回归与维护流程 | [11 月 5 日常规 CI](https://github.com/chatwithgod/reflow/actions/runs/41957150159)：三平台普通/race 各 90 通过、4 跳过，vet/fuzz 和评测自检通过。计数包含父测试和子测试，不作为采用量 |
| 原生客户端的覆盖与已知失败 | [11 月 5 日原生 CI](https://github.com/chatwithgod/reflow/actions/runs/41957150411)：三个平台普通/race 各 14 项通过；Ubuntu/macOS 后续写入与 Pi 探针通过，托管 Windows 保留相同的五个写入场景失败，整体仍为失败。原生任务实际串行，未手动重跑；此前 Ubuntu 转为通过的原因未确定 |
| 有限真实功能证据 | [原生验收总表](NATIVE-LOGIN-ACCEPTANCE.md)：Desktop 新样本 6 次请求、1 次续接、匹配工具回传、18/18、正常完成和保护文件检查通过。CLI 历史仍为 26 次会话、134 次已观察请求、4 次续接，保留批次审计例外；双方分别统计，不补写旧记录 |
| Desktop 与 dot 的有限人工验收 | [Desktop 新样本](DESKTOP-CONTINUATION-2026-11-05.md)补上同一会话的真实续接；前序同聊天两轮任务和 [dot 本机读取](DESKTOP-DOT-2026-11-05-FOLLOWUP.md)另记。dot 那次本地 Reflow 推理请求为 0，不能写成 dot 经本地 Reflow 推理或所有 dot 功能通过 |
| 官方 API 路径 | [独立记录](LIVE-API-KEY-2026-10-29.md)：1 次会话、2 次推理请求、0 次续接，与原生登录和订阅用量分开 |
| Magpie 外置接入及协作 | [外置说明](../adapters/magpie/EXTERNAL.md)、[公开讨论 #4497](https://github.com/yetone/magpie/issues/4497)。本机固定源码的七场景普通/race 通过；讨论尚无回复，嵌入式补丁没有作为 Magpie PR 提交或合并 |
| 使用与影响数据 | [11 月 5 日快照](evidence/oss-readiness-2026-11-05.json)：仓库公开，1 星、0 分叉、0 未关闭 issue；没有已验证的外部采用数据。自身发布核验下载不计为外部使用 |

已保存的 Codex Windows 沙箱修复是 OpenAI 已合并修复的本地回移，不计作本项目新提交的上游贡献。旧 CPA 版的发布和用户情况也不能充当独立 Reflow 的采用量。

## 提交前仍需用户提供或确认

需要姓名、ChatGPT 账号邮箱、申请者的公开 GitHub 账号、维护角色，以及希望申请的支持项目。仓库所有者已核对为 `chatwithgod`，但尚未代替用户确认申请身份或选择主要/核心维护者。

表单文本还包含组织 ID 和 API 额度用途；本轮只读核对页面，没有操作选项，因此这些字段随选项变化的必填关系仍以正式填写时为准。不把旧 API key 或已有账号信息当作填写授权。

正式提交前应由用户审阅[项目条款](https://learn.chatgpt.com/docs/codex-for-oss-terms)，并明确授权提交。当前没有在网页填写字段、选择支持项目或发送申请；这份草稿也没有改变完整工程 goal 的未完成状态。
