# 兼容性与验收边界

## 本地候选：v0.1.3-dev.2（尚未发布）

针对 [Issue #2](https://github.com/chatwithgod/cpa-plugin-codexreflow/issues/2)，候选版从原始请求中恢复被 CPA 插件路径误改的协作工具参数类型，不删除多智能体工具、不整体覆盖宿主处理后的请求。包含 HTTP/SSE、WS、516 续接与动态 `additional_tools` 覆盖。

同一 Windows DLL 在 CPA 8.0.47 上通过 18 项专项与 2 项预热回归，在 SDK 基线 CPA 8.0.13 上通过 50 项原有集成回归；另用已发布的旧 DLL 做反向对照。全部上游为本地模拟，没有真实模型调用。此候选尚未安装生产、提交公开发布或完成 Linux/macOS 验收，也不是“所有 schema 错误都能自动修复”。详见[范围、限制与复现方法](VALIDATION-2026-11-04-0.1.3-dev.2.md)。

## 当前正式版 v0.1.2（2026-10-24）

[`v0.1.2`](https://github.com/chatwithgod/cpa-plugin-codexreflow/releases/tag/v0.1.2) 修复 WebSocket 预热请求被接管、空输入 `[]` 被改成 `null` 导致 HTTP 400 的问题。`generate: false` 留在 CPA 原生路径；普通流式请求同样保留空数组。

五个平台各通过 Go unit/race/vet/fuzz、47 项 Python 回归，以及构建库和包内库各 34 项原生 ABI 用例。同一 Windows 正式 DLL 通过 CPA 8.0.13 的 50 项 HTTP/WS/续接回归和 CPA 8.0.38 的 2 项预热回归。五个 ZIP 与 checksums 经匿名下载逐字节核对。SDK 仍固定 v8.0.13。

这些 CPA 测试使用本地模拟上游；Linux/macOS 实际 CPA/客户端/模型集成仍待独立验收。完整源码、构件哈希及证据范围见 [v0.1.2 发布记录](RELEASE-2026-10-24-0.1.2.md)。

## 历史正式发布与证据分层

此前 [`v0.1.1`](https://github.com/LaoPiLao/cpa-plugin-codexreflow/releases/tag/v0.1.1) 于 2026-10-09 公开，
提供 Windows amd64、Linux amd64/arm64、macOS amd64/arm64 包。
[发布源提交的原生 CI](https://github.com/LaoPiLao/cpa-plugin-codexreflow/actions/runs/37916034316)
五平台各通过 Go unit/race/vet/fuzz、47 项 Python 回归、原库及包内库各 31 项 C ABI 合成宿主案例；
同组案例每组共 155 次执行，不是 310 种独立场景。六份公开资产经匿名下载逐字节复核，
公开 Windows DLL 本地另重跑 31 项原生案例通过。SDK 仍固定 `v8.0.13`，运行实现及策略未变。
**未安装生产、未新增真实模型测试，也未完成五平台实际 CPA/HTTP/WS 集成验收。**
Linux 旧 glibc/musl、旧 macOS 及签名/公证未验收；旧 DLL 的隔离/在线证据不转用于新构件。
见 [v0.1.1 发布与验收](RELEASE-2026-10-09-0.1.1.md)、[五平台流程](MULTIPLATFORM.md)。

`v0.1.1` Windows 正式 ZIP 内的同一 DLL 随后于 10 月 11 日通过独立隔离集成：
CPA `8.0.13` / `8.0.15` / `8.0.16` 各 50 次 HTTP/WS 合成用例执行，共 150 次全部符合断言，
另重跑 31 项原生 ABI；10 月 12 日读回构件、宿主和报告哈希。
没有重新编译或替换发布资产；这组新构件证据不借用旧 DLL 的测试结果。
首次临时目录保护检查拦下的是 Windows 宿主影子 DLL 副本，不是 14 项 WS 用例失败；
保存首次报告，修正 ignored 验收运行器的安全清理规则后在新目录完整重跑。
详见 [Windows 正式包隔离验收](VALIDATION-2026-10-12-0.1.1.md)。
该证据仍仅是 Windows 固定宿主和模拟上游，不是五平台全面集成、生产安装、真实模型或质量认证。

历史 [`v0.1.0`](https://github.com/LaoPiLao/cpa-plugin-codexreflow/releases/tag/v0.1.0) 仅 Windows amd64，保留不变。
正式 DLL 独立通过 31 项原生 ABI、19 项 Python 测试，以及 CPA 8.0.13/8.0.15/8.0.16
各 50 次隔离 HTTP/WS 案例执行；公开 ZIP/校验文件与封存包匿名下载核对一致。
它没有安装到生产或调用真实模型；下面 dev.5 的在线样本是历史证据，不转为正式 DLL 在线验收。
见 [正式包验收](VALIDATION-2026-10-08-0.1.0.md)、[公开发布记录](RELEASE-2026-10-08-0.1.0.md)。

## dev.5 历史证据

dev.5 沿用以下传输/续写实现，增加脱敏逐轮诊断；同一 DLL 已在 CPA 8.0.13、8.0.15、8.0.16
各完成 50 次隔离案例执行，另通过 31 项原生 ABI 和 19 项 Python 测试；
远程结果请查看 [Actions](https://github.com/LaoPiLao/cpa-plugin-codexreflow/actions)，不能以本地通过代替远程结果。
随后获授权本地安装并读回有效启用。10 月 8 日截至 01:42:48（UTC+8），两个已有会话的 22 条已完成
上游 WS 记录均为 HTTP 200，16 次处理与客户端合并用量吻合，6 次实际续接（其中 4 次原生增量），
均有工具往返和完整回答记录。真实 HTTP/SSE、复杂历史、取消/重连的全面边界仍待验收，不评价答案质量。
见 [dev.5 验证](VALIDATION-2026-10-07-dev5.md)、[部署记录](DEPLOYMENT-2026-10-07-dev5.md)、
[限定窗口真实核对](VALIDATION-2026-10-08-live-dev5.md)。

## 修补依据

- 上游基线：`uf-hy/cpa-plugin-codexcomp` `v0.1.7`，commit `25c139b49984e91fcc26896a7caf64b806b4deee`。
- 宿主源码基线 / 固定 SDK：CLIProxyAPI `v8.0.13`；dev.4 相同构件另在 `8.0.15` / `8.0.16` 实际隔离进程验证，未升级 SDK。
- CPA 从 `v8.0.9` 起允许 Codex → Responses 的正常事件字节不变透传，但插件适配器把这个结果当成缺失翻译而丢弃。
  本插件直接声明 `openai-response` 输出，让 Responses 请求走同格式分支，不修改生产宿主。
- CPA downstream WS 路径的 `host.model.stream_read` 提供裸 JSON；旧插件只寻找 `data:`，导致零事件被解析。
  新解码器支持裸 JSON、SSE 和事件分块，继续交给同一折叠状态机。
- 插件输出仍是完整 SSE 事件；CPA WebSocket forwarder 会提取 JSON 并发送 WS 消息。插件不创建另一层 WS 代理。
- CPA HTTP Codex executor 的 `bufio.Scanner` 去掉换行，每次回调可以仅是 `event:`、注释、`id:` 或 `retry:` 行。
  `0.1.0-dev` 的解码器把控制行与下一次 `data:` 拼接，等待永远不会到来的换行，最终生成 `upstream_error`。
  `0.1.0-dev.1` 仅在 JSON 外恢复这类回调边界，不搜索或修改 JSON 字符串内容。

源码参照：
[格式选择与丢弃条件](https://github.com/router-for-me/CLIProxyAPI/blob/v8.0.13/internal/pluginhost/adapters_executors.go#L477-L624)、
[WS 回调](https://github.com/router-for-me/CLIProxyAPI/blob/v8.0.13/internal/runtime/executor/codex_websockets_stream.go#L465-L477)、
[WS 下游提取](https://github.com/router-for-me/CLIProxyAPI/blob/v8.0.13/sdk/api/handlers/openai/openai_responses_websocket_forward.go#L547-L577)。

## 默认模型匹配（dev.2）

- 新配置不填写模型列表即可使用 `auto`：按请求名称匹配 GPT-5 及以上标准文本系列，支持前缀和末尾推理后缀；不会改写原始模型 ID。
- 名称中的 image / audio / realtime / transcribe / transcription / tts / video / embedding(s) / moderation 词段会被排除。规则不等同于真实能力判断。
- 固定 CPA SDK / ABI 没有插件直接读取模型目录的回调。本版没有管理 API 轮询、密钥读取、模型注册或任意别名推断；CPA 仍负责可用性、原生别名映射和上游选择。
- 旧显式 `models` 白名单没有 `model_mode` 时继续精确匹配，包括旧空名单的三个默认 ID 回退。显式 `auto` 忽略保留名单，显式 `manual` 空名单不接管；`exclude_models` 两种模式下均优先。
- 配置元数据提供 `auto` / `manual` 枚举，已验证原生注册和隔离 CPA 配置热重载；没有自动操作 ECPA 界面，不能声称其具体控件已验收。
- 接管并不等于追加调用：仍需成功终止、匹配截断启发式、加密推理状态及续写预算。默认最多追加三轮；实验性最低思考 token 阈值仍关闭。

## 已有可执行的合成覆盖（dev.1–dev.3 历史）

- 继承上游配置、截断启发式、轮数限制、metadata、usage 和路由测试。
- 新增 SSE / 裸 JSON 等价、每个分块边界、逐字节及合并事件、UTF-8、转义字符串、畸形/超大/残缺事件和 fuzz。
- 注册信息测试：新 ID；Responses 直接输出；保留 codex 输入/输出兼容。
- 原生 C ABI 合成宿主：dev.3 共 29 项，保留原有 20 项，增加三种负载形状的 EOF / failed / incomplete；终止 metadata 与日志逐字段核对，错误不得标为正常。
- 原生测试断言单个终止事件、连续 sequence_number、稳定 response ID、工具参数和合成多轮合计用量。
- 真实 CPA 8.0.13 进程 + 本地合成上游：23 项默认自动选择回归，另独立重跑 8 项旧白名单 HTTP/WS 场景；正常文本、续写、工具事件均通过。
  WS 客户端和合成上游均完成实际握手，并断言未回退 HTTP、未绕过插件。
  自动选择覆盖新名称、前缀/后缀、非标准别名绕过、旧名单不扩大、显式切换、排除项、缺少加密状态及默认最多四轮。
  dev.1 曾在同一宿主上稳定复现修补前构件的 `upstream_error`，修补后保留完整回答；dev.2 不改其流式逻辑。
- dev.3 严格 WS 缓存集：13 项通过，覆盖续写后的第二/第三次请求、连续 516、工具回传、完整重放、重连、请求模型前缀/后缀、原生增量 516 不被追加、并发同可见 ID 不同父 ID。
  另用旧 DLL 运行 `--expect-defect`，刻意复现其父 ID 缓存错误，不把预期失败称为功能通过。
  配置重载的开/关插件对照均发现宿主 `executor_shutdown`，验证新连接完整重放恢复，不声称旧连接缓存可跨重载使用。

## WS 衔接与诊断（dev.3，dev.4 保留此桥）

- CPA self-executor 适配器将输入转为插件声明的 `codex`，不是原始 `openai-response`。首个候选版本因只认原格式而跳过注册；真实隔离 CPA 已验证修正。
- 终止输出前注册首轮可见 ID → 最后一轮实际 ID；后继请求在原生选取凭证之后只改命中的 `previous_response_id`。
- 作用域为宿主生成的 execution session、原始请求模型和通道；客户端会话头不能代替可信连接身份。TTL 一小时、最多 4096 项，只保存身份和诊断 ID，终止发送失败撤销该修订，shutdown 清空。
- dev.3 的 `previous_response_id` 生成不交给折叠器；dev.4 仍不更改其首次上游路由，但增加下节的响应阶段折叠。工具增量和文本输入保持不变。不跨连接/模型/通道改写，不新增 HTTP 回退或账号选择。
- 增加独立 `proxy_reflow.run_id` 与默认 INFO 日志，区分尝试轮、收到终止事件的轮、停止原因和宿主输出接受情况；不记录请求/回答/凭证/加密内容。详情见 [dev.3 记录](VALIDATION-2026-10-05-dev3.md)。
- 通道键仅用于隔离，本次没有证明新版 OpenAI multiplexing 或跨通道 fork 支持；跨通道父 ID 不会被该桥改写。

**模拟上游取消不等同于真实客户端断开；合成模型与实际 WS 握手不等同于真实账号或 Desktop 验收。**

## 原生 WS 增量续写（dev.4，后续授权本地安装）

- 不直接扩大 self-executor 模型路由。CPA 的增量 WS 请求选择该执行器可能先走 HTTP replay-required 分支，
  在折叠器执行前已失败；候选采用响应流钩子，让首次上游调用继续走原生 WS。
- 根请求完成后在可信 socket/model/lane 作用域内保留最新完整上下文。增量首次生成仍保留父 ID 和客户端增量，
  满足原截断启发式、完整上下文命中、加密状态及预算后，才以完整上下文追加隐藏调用。
  缓存命中仅接受该作用域最新响应的可见/实际 ID，不是任意历史分叉恢复。
- 隐藏完整重放继承增量中省略的设置，显式覆盖（包括 null）优先；提交历史排除丢弃的暂定文本/工具和续写 marker。
  未命中、过期、容量/大小超限不追加，不删父 ID 后只发送当前 delta。流资源耗尽明确返回 incomplete。
- **隐私变化：** dev.3 的 ID 别名缓存仍是 ID-only，但 dev.4 新增的上下文缓存不是。
  它在内存保留完整输入/输出、设置及不透明加密推理，不写入插件日志/磁盘；最多 64 项、每项 16 MiB、
  合计 64 MiB、惰性 TTL 15 分钟。活动请求另限 64 项、请求/累计流序列化字节合计 64 MiB，生命周期/shutdown 清理。
  此限制不保证 Go 堆/RSS 上限或敏感内存安全擦除。升级前活动连接可能没有上下文。
- 每种 CPA `8.0.13` / `8.0.15` 各跑 14 项新增增量、13 项原衔接和 23 项自动选择回归，均符合预期；
  共 100 次案例执行，含重复基线与控制组，不宣传为 100 种独立场景。相同 DLL 另通过 29 项原生 ABI、Go 单元/race/vet。
- 新增集验证 516/1034、根折叠后再增量折叠、工具回传前后、连续截断、省略设置、零新增思考、预算限制、
  无加密状态、失败/不完整和同可见 ID 并发连接。成功 WS 样例维持上下游实际 WS，无 HTTP 回退。
- 原生 `response.failed` 可被 CPA 在响应钩子之前拦截并关闭 socket；这是保留的宿主失败，不是插件将其修成成功。
  响应钩子日志 `interceptor_returned` 只表示返回字节，不等于宿主接受或客户端送达。
- 构建、修补和隔离验证不修改生产环境、不主动调用真实模型。之后另获授权，在用户指定的两个聊天空闲时
  备份并切换到相同 dev.4 DLL；CPA `8.0.15` 读回注册/有效启用，模型和传输设置不变，未发起额外模型测试。
  详情、哈希、复现命令和独立部署回执见 [dev.4 验证记录](VALIDATION-2026-10-05-dev4.md)。

## 尚待在线验收

下面均指真实模型和客户端，不是本地合成测试。用户已报告 dev.1 HTTP/WS 能成功通信；dev.2 / dev.3
均随后获授权安装并读回加载。此前核对用户指定的两个现有会话时，已观察到 dev.3 的 HTTP/WS 隐藏追加及
客户端折叠输出，同时存在原生 WS 增量绕过；追加轮零思考时最终仍为 516。该有限请求证据不是全面客户端或质量认证。
dev.4 已随后获授权安装。10 月 7 日对两个现有聊天核对到 14 次真实续写，其中 12 次走新增 WS 增量路径，
客户端合并用量与追加轮次吻合，后继父 ID 衔接有记录。该有限样本不代表整个安装期间无错误或质量提高；
另补跑 CPA 8.0.16 的 50 次隔离案例执行，均符合预期。见 [10 月 7 日核对记录](VALIDATION-2026-10-07-live-dev4.md)。

**dev.2 及更早版的已知缺陷：** 在同一 WS 连接内，插件追加一轮后仍对客户端维持第一轮的 response ID，
而合成上游的最近响应缓存已推进到追加轮。随后客户端引用旧 ID 发送增量请求，可触发
`previous_response_not_found`。真实隔离 CPA 的四组对照已复现，仅“启用插件 + 首轮触发追加”失败；
没有调用真实模型，不能据此宣称所有线上同码错误均已逐包归因。
详见 [新增增量诊断](DIAGNOSIS-2026-10-05-ws-incremental.md)。此前首轮 WS 测试不覆盖这个后继请求，不能作为完整兼容证明。
dev.3 已在相同严格合成上游条件修补并验证，之后获授权安装并读回加载状态；有限在线记录不覆盖以下全部边界。

| 场景 | HTTP/SSE | WebSocket |
|---|---|---|
| dev.1 基本通信 | 用户报告成功 | 用户报告成功 |
| dev.3 隐藏追加及折叠输出 | 有限现有请求已观察 | 有限现有请求已观察 |
| dev.5 已完成处理及客户端用量 | 待补 dev.5 真实样本 | 16 次处理核对，22 条已完成上游行；不含活动请求 |
| dev.5 可触发续思考并合并输出 | 待补 dev.5 真实样本 | 6 次续接，含一次 516 → 0；不代表质量提升 |
| dev.5 原生增量请求的隐藏续写 | 不在新增范围 | 上述 6 次中的 4 次，有限真实样本 |
| 工具调用及回传后继续 | 待测 | dev.5 两会话共 14 次调用 / 14 次返回，完整边界待补 |
| 多轮历史 / 增量上下文 | 待测 | 有限真实后继衔接已观察，复杂历史待补 |
| 用户取消、超时、断开、重连 | 待测 | 有 interrupted 记录但未精确归因，全面边界待补 |
| 多请求并发、配置重载 | 待测 | 待测 |
| Chat Completions / Messages 翻译 | 待测 | 不作默认保证 |

WS 的 `generate:false` 预热与 `previous_response_id` 需专门核对宿主是否先还原完整输入。
模型路由器保留 `previous_response_id` 不接管规则；dev.4 仅在响应钩子中有条件追加，不为了“命中插件”
删除上下文或无条件接管增量请求。
模型目录可识别某模型不等于它具备 `518n-2` 行为，也不等于该模型已通过插件验收。

使用记录是上游轮次，不会因客户端输出折叠而抹去 516。WS 连接的 request ID 还可能被多个
`response.create` 共用；不要仅据同一 request ID 的记录数推算某次插件续写轮数。
需核对单次最终事件中的 `proxy_reflow.run_id`、续写计数、`proxy_rounds` / `proxy_billed_usage`，并结合真实回答验收。

## 推荐验证方式

复制最小配置到独立 CPA 实例并使用不同端口，不改生产配置。经明确授权后才使用指定的测试凭证、
极少量模型请求和明确费用/轮数上限。记录实际 WS 握手/事件和最终回答；遇到 HTTP 回退必须标注。
不要把同一模型同时交给两个续写插件。
