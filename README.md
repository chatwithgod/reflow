# Reflow · 续流

**在满足条件时自动追加推理，再把多轮结果合并为一条响应。**

Reflow 支持两种运行方式：独立本地代理，以及 CPA 的 CodexReflow 原生插件。两者在同一仓库维护、共用续接核心，分别构建和安装。独立版可接入 Codex、Pi 和 Magpie，不需要 CPA。

模型的推理 token 数有时会停在 `518n−2`，例如 `516、1034、1552`。Reflow 将这个特征作为续接线索；如果还有可重放的加密推理状态和剩余预算，就请求模型继续，再整理最终回答、工具调用与用量。

这个数字特征不是截断或回答变差的确定证明。续接会增加上游请求、token 消耗和等待时间，也不保证回答质量提高。

[独立版 dev.6](https://github.com/chatwithgod/reflow/releases/tag/v0.1.0-dev.6) · [CPA 插件 0.1.4](https://github.com/chatwithgod/reflow/releases/tag/v0.1.4) · [问题反馈](https://github.com/chatwithgod/reflow/issues)

## 选择接入方式

| 你的使用方式 | 选择什么 | 说明 |
| --- | --- | --- |
| Codex 原生 ChatGPT 登录 | [独立程序 dev.6](https://github.com/chatwithgod/reflow/releases/tag/v0.1.0-dev.6) | 客户端继续管理自己的登录；Reflow 在本机转发请求 |
| 想用 Codex 插件管理接入配置 | 同一发布页的 `reflow_plugin_…` 包 | 提供本地插件市场及配置工具；仍需启动包内代理，见[插件使用说明](plugins/codex/README.md) |
| Pi | 独立程序 + [Pi 接入](adapters/pi/README.md) | 包含 `openai-codex` 与 `openai` 两种入口；OAuth/API key 的适配范围见说明 |
| Magpie | 独立程序 + [Magpie 外置接入](adapters/magpie/EXTERNAL.md) | 使用明确的 Magpie 兼容选项；宿主版本与验证范围单列 |
| CPA / ECPA | [CodexReflow 0.1.4](https://github.com/chatwithgod/reflow/releases/tag/v0.1.4) | CPA 原生插件，不需要另开独立代理 |

**dev.6 和 CPA 0.1.4 都是预发布版。** 两者均提供 Windows amd64、Linux amd64/arm64、macOS amd64/arm64。独立版有服务包和 Codex 插件包两类 ZIP，CPA 另有自己的动态库包。请按系统和接入方式选择，并核对发布页附带的 SHA256。

CPA 插件商店目前仍使用旧仓库的[稳定版 v0.1.3](https://github.com/chatwithgod/cpa-plugin-codexreflow/releases/tag/v0.1.3)；本次没有迁移商店入口。不要让独立代理、CodexReflow 和 CodexComp 在同一请求路径上重复执行续接。

## `518n−2` 实际出现多少？

下面是本项目维护者的一套 **CPA/ECPA 本地用量记录**，统计区间为 **2026-08-27 至 2026-11-11（北京时间）**。只统计 Codex 通道中被记录为成功、未取消且不是预热的 GPT 生成记录；模型名称按请求记录分组。

在 **27,638 条推理 token 大于 0 的记录**中，**3,856 条符合 `518n−2`，占 13.95%**。如果将 4,072 条零推理记录也计入分母，则为 **3,856 / 31,710 = 12.16%**。

| 模型 | 全量命中 / 有推理用量的记录 | 全量比例 | 近 30 天命中 / 有推理用量的记录 | 近 30 天比例 |
| --- | ---: | ---: | ---: | ---: |
| `gpt-6-astra` | 3,409 / 19,817 | 17.20% | 2,209 / 14,696 | 15.03% |
| `gpt-5.6-sol` | 100 / 5,581 | 1.79% | — | — |
| `gpt-6.1-sol` | 326 / 1,117 | 29.19% | 37 / 224 | 16.52% |
| `gpt-5.6-terra` | 9 / 663 | 1.36% | 0 / 58 | 0.00% |
| `gpt-5.6-luna` | 12 / 428 | 2.80% | 0 / 14 | 0.00% |
| `gpt-6-luna` | 0 / 32 | 0.00% | 0 / 32 | 0.00% |
| **合计** | **3,856 / 27,638** | **13.95%** | **2,246 / 15,024** | **14.95%** |

表中“有推理用量”指 `reasoning_tokens > 0`；近 30 天为 **2026-10-13 至 2026-11-11**，`—` 表示没有符合条件的样本。少量样本中的 0 次命中不代表出现概率为零。

**这是这份记录的经验比例，不是所有用户或模型的固定概率。** 记录包含插件续接产生的额外上游轮次，混合了任务、推理档位和历史插件状态；因此不能当成一条用户消息的首轮命中率、实际续接率或质量下降率。表中统计所有整数 `n ≥ 1`，其中 3,756 条位于默认档位 `n=1…6`；实际续接还需要满足其他条件。

[统计口径与复现方法](docs/REASONING-PATTERN-2026-11-12.md) · [仅含汇总计数的 JSON](docs/evidence/reasoning-pattern-2026-11-12.json)

## 它怎样工作？

1. **检查上游结果。** 判断推理用量是否命中规则、是否有可重放的推理状态，以及续接预算是否足够。
2. **必要时追加一轮。** 暂存中间回答和待下发的工具调用，继续请求上游；被舍弃轮次的工具不会下发给客户端执行。
3. **合并后返回。** 达到停止条件后，保留最终输出与工具调用，并整理多轮用量。失败、取消、历史无法恢复等情况另有处理边界。

支持 HTTP/SSE 和 WebSocket。独立版会在上游托管工具已经执行时停止续接；CPA 保留自己的宿主策略与工具参数恢复逻辑。两种接入的差异见[共用核心与 CPA 接入](docs/CPA-INTEGRATION.md)。

| 选项 | 默认值 | 含义 |
| --- | --- | --- |
| `max_continue` | `3` | 最多追加 3 次请求；设为 `0` 禁止续接 |
| `max_tier_n` | `6` | 默认接受 `516、1034、1552、2070、2588、3106` 六个数字档位 |

CPA 另有模型匹配和实验性的最低推理量选项，见[CPA 配置说明](adapters/cpa/docs/CONFIGURATION.md)。独立版的实际续接/停止原因可以通过可选[数字诊断](docs/DECISION-DIAGNOSTICS.md)观察。

## 独立版快速开始

解压对应平台的独立程序包，在一个终端里启动服务。以下示例最多追加一次请求：

```sh
reflow -listen 127.0.0.1:18516 -max-continue 1
```

在另一个终端中，先预览 Codex 配置，再接入：

```sh
reflow codex-config --action preview
reflow codex-config --action connect
```

它只调整用户级 `openai_base_url`，继续使用 Codex 的内置 provider 和原有登录；已有明确的其他 provider 时，会拒绝自动切换。只有配置实际变化后才需要重启 Codex。

停止代理前先还原配置，重启 Codex 后再停止服务：

```sh
reflow codex-config --action restore
```

还原会保留其他设置的后续修改；路由已被手动改动时不会直接覆盖。安装 Codex 插件本身不会启动代理，插件也提供相同的预览、接入和还原入口。

服务默认只监听 `127.0.0.1:18516`，上游默认是 `https://chatgpt.com/backend-api/codex`。客户端负责登录与 token 刷新；独立代理不读取 `auth.json`，凭据只随请求发往配置的固定上游，历史缓存按凭据与账号隔离。

如果上游访问需要网络代理，请给 Reflow 进程设置现有的 `HTTP_PROXY` / `HTTPS_PROXY`，并让 `NO_PROXY` 包含本地回环地址。它不会自动读取 Windows 系统代理。`http://127.0.0.1:18516/healthz` 只检查本地服务，不代表上游或登录已经可用。

## 当前验证范围

2026-11-12 发布的两类包均固定到提交 `b0543cf`。19 个附件已全部匿名下载，逐字节和 SHA256 核对一致；两轮标签 CI 已结束。

| 项目 | 已验证范围 |
| --- | --- |
| 独立版常规回归 | Windows、Ubuntu、macOS 的普通/race 各 97 通过、4 跳过；vet、fuzz 等检查通过 |
| 独立版原生客户端 | Windows amd64、Linux amd64、macOS arm64 的协议/插件/Pi 普通及 race 各 14 项通过；三个平台的发布程序与发布前原生 CI 程序一致 |
| 原生客户端写文件 | Ubuntu/macOS 的五个场景通过；**托管 Windows 仍有五个已知写入失败，原生客户端工作流保持失败状态** |
| 独立版其余架构 | Linux arm64、macOS amd64 已交叉编译并检查包内容，未完成原生运行验收 |
| CPA 五平台 | 原生构建、普通/race/vet/fuzz、打包校验及打包前后各 46 个 ABI 模拟场景通过；公开 Windows 包的同一动态库再次通过 46 个 ABI 场景 |

标签 CI：[dev.6 常规](https://github.com/chatwithgod/reflow/actions/runs/43090980485)、[dev.6 原生客户端](https://github.com/chatwithgod/reflow/actions/runs/43090980692)、[dev.6 CPA 五平台](https://github.com/chatwithgod/reflow/actions/runs/43090980576)；[0.1.4 常规](https://github.com/chatwithgod/reflow/actions/runs/43092668100)、[0.1.4 原生客户端](https://github.com/chatwithgod/reflow/actions/runs/43092668196)、[0.1.4 CPA 五平台](https://github.com/chatwithgod/reflow/actions/runs/43092668105)。

本次发布验证没有真实模型调用。旧独立版 dev.5 曾完成 Windows 原生登录和 Desktop 真实续接，dot 本机读取也有独立记录；这些历史结果不会自动覆盖新构件。Pi 按模拟范围验收，Magpie 的固定宿主证据与限制见其接入说明。没有 Windows 代码签名、macOS 签名或公证，也没有质量收益结论。

[原生登录历史验收](docs/NATIVE-LOGIN-ACCEPTANCE.md) · [Desktop 续接](docs/DESKTOP-CONTINUATION-2026-11-05.md) · [Desktop/dot](docs/DESKTOP-DOT-2026-11-05-FOLLOWUP.md) · [兼容性](docs/COMPATIBILITY.md) · [评测](docs/EVALUATION.md)

## 开发与构建

CI 使用 Go 1.26.8。独立程序可从源码构建：

```sh
git clone https://github.com/chatwithgod/reflow.git
cd reflow
go build ./cmd/reflow
go test ./...
go test -race ./...
go vet ./...
```

CPA 在 `adapters/cpa` 中使用独立 Go 模块；根目录测试不覆盖它，需另行运行：

```sh
cd adapters/cpa
go test ./...
go test -race ./...
go vet ./...
```

CPA 构建还需要 C 编译器和原生 ABI 检查。两类程序都需要完整仓库中的共用 `core/`。独立包不包含 CPA SDK 或动态库，CPA 的 SDK 依赖留在自己的模块内。

PowerShell 可用 `scripts/build.ps1 -AllPlatforms -WithCodexPlugin` 生成独立程序与 Codex 插件包；需要 Python，产物按版本和时间戳另存。CPA 的五平台构建入口及源码指纹规则见[开发说明](docs/CPA-INTEGRATION.md)。

## 来源与许可证

MIT 许可证，保留上游署名与许可。Reflow 源自 [CPA CodexReflow](https://github.com/chatwithgod/cpa-plugin-codexreflow)，并继承了 [uf-hy / CPA CodexComp](https://github.com/uf-hy/cpa-plugin-codexcomp)、[dzshzx / codexcomp](https://github.com/dzshzx/codexcomp) 和 [neteroster / CodexCont](https://github.com/neteroster/CodexCont) 的代码与机制探索。

详见 [LICENSE](LICENSE)、[第三方声明](THIRD_PARTY_NOTICES.md)和[第三方许可证](THIRD_PARTY_LICENSES.txt)。
