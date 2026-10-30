# 原生客户端离线流水线

原有 `offline.yml` 会在没有安装客户端时跳过 Codex CLI、app-server、Pi 和插件联调。新增的 `native-clients.yml` 专门运行这四组测试，并增加原生写文件探针。缺少客户端、测试被跳过或缺少预期测试的完成记录，都会使这条流水线失败。

这条流水线已随 `066973b` 公开并在三个 GitHub runner 执行。macOS arm64 全部通过；Ubuntu amd64 和托管 Windows 的四组客户端普通/race 检查通过，但五个写文件场景全部失败。此前本机 Windows 的成功记录继续保留，不能将两种宿主环境混为一谈。

后续单独授权的 [Ubuntu 发行版配置对照](LINUX-SANDBOX-CONTROL.md)在 `d86ac49` 上通过：固定依赖与 AppArmor 告警例外下，五个写入场景全部通过，文件/网络边界及清理检查也通过。该选项没有自动启用于本页的默认流水线；默认 Ubuntu 和托管 Windows 的失败结果仍保留。

## 最新公开 CI：2026-10-31

经用户授权，13 个提交已推送至 `304a67c`。本轮[常规 CI](https://github.com/chatwithgod/reflow/actions/runs/41125692514)三平台全部通过，普通/race 各 80 通过、4 跳过，vet、fuzz、合成评测和宿主控制自检通过；Ubuntu 的 34 项宿主控制检查全部执行，Windows/macOS 跳过其中 3 项 Linux 专用检查。

| 环境 | 客户端普通 / race | 五个写文件场景 | 后续 Pi 只读探针普通 / race |
| --- | --- | --- | --- |
| Ubuntu amd64 runner | 各 14 通过、0 跳过 | 0/5 通过 | 写入阶段失败后未执行 |
| Windows amd64 runner | 各 14 通过、0 跳过 | 0/5 通过 | 写入阶段失败后未执行 |
| macOS arm64 runner | 各 14 通过、0 跳过 | 5/5 通过 | 各 4 通过、0 跳过 |

三平台客户端测试均包含 Pi 旧入口、新公共 OAuth/API key 入口及传输边界检查。[原生 CI](https://github.com/chatwithgod/reflow/actions/runs/41125692789)整体仍为失败：Ubuntu/托管 Windows 的五个写入场景及固定错误标记与第四轮记录一致，未发现新增失败，没有放宽断言。失败平台后续 Pi 只读探针、二进制未变和临时目录清理的最终确认字段未执行，不能借用 macOS 的成功结果补齐。

原生任务按 Ubuntu、Windows、macOS 顺序执行，实际区间没有重叠，最大并发 1。两条工作流都只执行一次，没有重跑或手动宿主对照，真实模型调用 0。完整计数、散列、任务区间与比较依据见[本轮证据](evidence/publication-dev5-2026-10-31.json)。Pi 按用户指定的模拟范围验收，不要求真实登录；本轮没有改变 Desktop/dot 未验收、Magpie 宿主全量中断或原生真实批次配置审计例外的状态。

## 历史公开 CI：2026-10-29

| 环境 | 四组客户端普通检查 | Race | 五个写文件场景 |
| --- | --- | --- | --- |
| Ubuntu amd64 runner | 10 通过、0 跳过 | 10 通过、0 跳过 | 0/5 通过；含父测试共 6 个失败项 |
| Windows amd64 runner | 10 通过、0 跳过 | 10 通过、0 跳过 | 0/5 通过；含父测试共 6 个失败项 |
| macOS arm64 runner | 10 通过、0 跳过 | 10 通过、0 跳过 | 5/5 通过；含父测试共 6 个通过项 |

[原生客户端 CI](https://github.com/chatwithgod/reflow/actions/runs/40749977296) 的整体结果为失败，没有将写入探针跳过或改成允许失败。[同一提交的常规 CI](https://github.com/chatwithgod/reflow/actions/runs/40749977201) 则在三个系统均通过：普通/race 各 69 通过、4 跳过，vet、fuzz 和合成评测自检通过。

任务实际按 Ubuntu、Windows、macOS 的顺序执行，运行区间没有重叠。机器可读结果、构件及日志散列见 [公开执行记录](evidence/native-ci-publication-2026-10-29.json)。这次没有真实账号或模型调用。

写入失败也出现在绕过 Reflow 的直接路径，因此不能将所有失败归因于 Reflow。但现有摘要缺少启动错误和工具错误的分类，仍不足以确定具体原因。失败摘要也没有独立记录二进制未变和临时目录已清理的最终检查，不能借用 macOS 的成功字段补齐这些缺项。

CLI 阶段的摘要采集已在 `3a63ae8` 获批推送后执行，准备时的 [分类和脱敏检查](evidence/native-ci-diagnostics-2026-10-29.json) 保留为历史记录。新增诊断字段不保留原始错误文本、请求/回答/工具正文或其中的路径；标记命中也不等于根因成立。

## 第二轮诊断与后续采集点

[第二轮原生 CI](https://github.com/chatwithgod/reflow/actions/runs/40754047713) 仍为 macOS 全部通过、Ubuntu/托管 Windows 写入失败；[常规 CI](https://github.com/chatwithgod/reflow/actions/runs/40754047795) 三个平台均通过。两条流水线都已结束，三平台原生任务仍串行执行。完整数字记录见 [第二轮证据](evidence/native-ci-second-run-2026-10-29.json)。

失败场景中，CLI 进程均正常退出，模拟上游收到预期的 2 次或 3 次请求，丢弃轮次的工具执行计数均为 0，但文件没有得到预期修改。Windows 的 CLI 输出出现了 MXC 标记，仍不足以确定原因。现有采集只覆盖 CLI 输出；需要进一步观察已经回传给模拟上游的工具结果，不能把尚未确认的问题归因为某个沙箱限制。

已在本地测试夹具增加工具结果分类：只在内存中匹配固定标记，输出数量及分类计数，再由摘要采集器按白名单接收。它不改变工具调用、权限或原有通过断言。为了验证采集点确实有效，用 Go overlay 将一个测试补丁的目标临时改成不存在的文件：原写入断言如期失败，摘要捕获到文件系统错误标记，测试用的正文、令牌和路径标记没有进入结果。验证脚本没有保存原始故障输出，只保留散列和分类结果。这个故障是诊断能力的对照，不是 CI 故障复现。

新分类单测普通/race 各通过 1 项，vet 通过；本机 Windows 正向四组客户端普通/race 仍各通过 10 项，五个写入场景通过。源码与数字证据见 [准备时的工具结果诊断验证](evidence/native-tool-diagnostics-2026-10-29.json)。该版本随后以 `0be9c34` 获批推送，实际结果如下。

## 第三轮：工具结果分类

[第三轮原生 CI](https://github.com/chatwithgod/reflow/actions/runs/40760670272) 的通过范围仍与前两轮相同：三个系统的客户端普通/race 均通过，macOS 五个写入场景通过，Ubuntu/托管 Windows 写入失败。[常规 CI](https://github.com/chatwithgod/reflow/actions/runs/40760670297) 普通/race 各为 70 通过、4 跳过；增加的一个通过项是分类与内容隔离单测，不是新增用户或真实模型任务。完整记录见 [第三轮证据](evidence/native-ci-third-run-2026-10-29.json)。

这次从工具结果得到以下标记：Ubuntu 的命令写入同时出现 `bubblewrap` 和 `operation_not_permitted`；Windows 的命令写入同时出现 `windows_mxc` 和 `unsupported_operation`。两个系统的补丁场景均出现 `filesystem_error`。这些结果将调查方向缩小到原生执行路径，但不能证明命令与补丁失败都来自同一原因。

runner 日志显示，Windows 使用 Server 2025 Datacenter，Ubuntu 使用 24.04.5，macOS 使用 26.6.2 arm64。MXC 需要实际设备能力支持，不能只靠系统名称或版本号判断；[官方说明](https://learn.chatgpt.com/docs/windows/windows-sandbox)提供了无账号的直接启动检查。另从 [Codex 0.165.0 源码](https://github.com/openai/codex/blob/rust-v0.165.0/codex-rs/exec-server/src/process_sandbox.rs)确认，MXC 不可用和自定义 argv0 不受支持是两个不同的拒绝分支。现有标记尚未区分它们。

Ubuntu 有通过 AppArmor 限制非特权 user namespace 的机制，见 [Ubuntu 官方说明](https://ubuntu.com/blog/ubuntu-23-10-restricted-unprivileged-user-namespaces)。这只是后续检查的背景，尚未证实本轮 runner 的具体限制。

## 第四轮：宿主对照

`3bd2b1c` 经授权推送，在原测试前增加只读的宿主信息和无账号对照：Windows 记录系统类型、直接 MXC 命令启动和既有文件系统 RPC/边界探针；Linux 读取相关内核设置，分别尝试短生命周期的 user、mount、network namespace，再运行同一客户端的直接沙箱命令。原始输出不保存，只记录退出码、布尔值、字节数和固定标记。

对照只在隔离临时目录写固定标记，namespace 仅在子进程中存在；不执行 sandbox setup，不设置 sysctl、AppArmor、系统账号或防火墙。宿主探针是诊断上下文，不代替原有五个写入场景；原有失败仍使 CI 失败。

本机 Windows 的直接命令和文件系统写入/越界拒绝检查通过，错误分类、脱敏和超时退出对照通过，分类单测普通/race 及 vet 通过；完整客户端正向检查仍为普通/race 各 10 通过、写入场景 5/5。Linux 控制未在本机执行。这些准备时结果见 [宿主探针验证](evidence/native-host-probes-2026-10-29.json)，其中准备状态保留为当时的快照。

[第四轮原生 CI](https://github.com/chatwithgod/reflow/actions/runs/40773001439) 的 Ubuntu 和 Windows 任务已结束，客户端普通/race 各 10 项通过，五个写入场景仍全部失败。新增无账号对照得到以下结果：

- Ubuntu：三种 `unshare --user --map-root-user` 对照均在 UID/GID 映射阶段被拒绝；直接 Codex 沙箱命令也出现 `bubblewrap` 与 `operation_not_permitted`。这说明存在不依赖 Reflow 或模型的基础隔离限制。AppArmor 的非特权 user namespace 限制值为 1，但尚未通过策略变更对照确定它的因果作用；不能将所有补丁失败归为同一原因。
- 托管 Windows：直接 MXC 命令与保留轮次的命令工具结果均明确命中 `mxc_unavailable`，未命中 `custom_argv0`。该 runner 无法执行所选的 MXC 路径；这不是对所有 Windows 系统的结论。文件系统 RPC 在首次工作区写入时失败，尚未执行越界检查，摘要中的 `out_of_workspace_write_blocked: false` 不能解释为越界成功。

macOS 原生任务首次因托管机容量不足、未获得 runner 而被平台取消，未执行任何步骤。在同一提交上仅补跑该任务一次，Ubuntu 和 Windows 没有重新执行。补跑后的 macOS arm64 普通/race 各 10 项通过，五个写入场景和直接沙箱命令通过；二进制未变和临时目录已清理的最终检查也通过。实际执行区间没有重叠，原生 CI 整体仍为失败。[同提交常规 CI](https://github.com/chatwithgod/reflow/actions/runs/40773001510) 三个平台普通/race 各 70 通过、4 跳过，vet、fuzz 和合成评测自检通过。

机器可读结果、宿主观察、首次取消与单任务补跑记录见 [第四轮证据](evidence/native-ci-fourth-run-2026-10-29.json)。本轮真实模型调用为 0，系统策略和生产配置未修改。失败平台摘要中仍缺二进制未变与临时目录清理的最终确认，不能套用 macOS 的成功字段。

后续 [Ubuntu 发行版依赖对照](LINUX-SANDBOX-CONTROL.md)已获批执行四轮。前三轮定位了包信息采集缺陷及 ABI 4.0 的 io_uring 告警；第四轮明确启用固定告警例外后，完整普通/race、五个写入场景、文件和网络边界、配置移除及直接命令反向对照均通过。默认原生工作流没有启用该选项，原始失败继续保留。四轮细节、此前无效的反向对照标记及适用条件见该页。

## 执行内容

1. 按 [依赖锁文件](../ci/native-clients/package-lock.json) 安装 Codex `0.165.0` 和 Pi `1.4.0`；Node 固定为 `24.17.0`。客户端安装在项目 `.tools/native-clients`，安装时禁用 lifecycle scripts。
2. `build.ps1 -CurrentPlatform -WithCodexPlugin` 为当前机器生成独立包和插件包。原有默认 Windows amd64 与 `-AllPlatforms` 行为保留；两个平台选项不能同时使用。
3. 检查 ZIP 散列、文件路径和可执行权限位，解压到临时目录，再核对二进制散列。后续代理进程和插件安装都使用解压包。
4. 串行执行 CLI、app-server、Pi 和插件的普通及 race 测试，再单独执行五个写文件场景；这些阶段通过后，再执行 Pi 只读探针的普通及 race 测试。任一阶段失败即停止后续阶段。Go 使用 `-p=1 -parallel=1`，CI 三个平台也按 `max-parallel: 1` 排队。
5. 检查客户端及 Reflow 二进制未改变，并清理临时目录。CI 只上传数字摘要，不发布二进制 Release。

测试使用合成登录文件和本地模拟上游，不需要账号或 API key。测试进程显式设置隔离的 `HOME`、`CODEX_HOME`/`PI_CODING_AGENT_DIR` 和临时目录；Codex 使用文件凭据存储，并关闭两种子代理开关。Pi 保留自己的 OAuth provider 和实际 `read` 工具路径。

下载客户端及 Go 依赖需要联网；“离线”指模型和账号链路使用本地测试服务。没有读取现有登录文件，没有修改生产配置。

## 本机验证：2026-10-29

| 项目 | Windows amd64 结果 |
| --- | --- |
| CLI、app-server、Pi、插件 | 10 个通过项，0 跳过、0 失败 |
| 上述四组的 race | 10 个通过项，0 跳过、0 失败 |
| 原生写文件探针 | 五个场景通过；含父测试共 6 个通过项 |
| 新打包独立服务与插件 | ZIP、二进制和可执行权限位检查通过；使用解压包完成上表验证 |
| 失败判定 | 缺客户端、缺测试、跳过、非零退出及缺少包完成事件均被拒绝 |

通过项包括 Go 父测试和子测试，不能混算为独立任务数量，也不是本次全项目回归计数。测试使用 `b2bddbd` 基础上的流水线和夹具修改，具体文件版本由 [机器可读证据](evidence/native-ci-2026-10-29.json) 中的散列确定。历史构件未被覆盖。

## 本地复现

需要 Go、PowerShell 7、Python、Node，以及 Go race 所需的 C 编译器。按项目锁文件安装依赖后运行：

```powershell
New-Item -ItemType Directory -Force .tools/native-clients | Out-Null
Copy-Item ci/native-clients/package*.json .tools/native-clients/
npm ci --prefix .tools/native-clients --ignore-scripts --no-audit --no-fund --registry=https://registry.npmjs.org/
python scripts/check-native-clients.py
```

可用 `--go-exe`、`--node-exe`、`--pwsh-exe`、`--compiler` 指定工具路径。报告保存在 `build/native-client-ci/<UTC 时间戳>/`；报告包含输入源码、客户端、包和测试日志的散列。脚本没有真实账号执行选项。

工作流中的 Actions 都固定到提交；Node 设置与摘要上传分别按 [setup-node](https://github.com/actions/setup-node) 和 [upload-artifact](https://github.com/actions/upload-artifact) 的官方接口配置。

## 验收边界

macOS arm64 的结果覆盖所测官方客户端、Pi 和 ZIP 解压包；Ubuntu amd64 在上述固定发行版配置下也已完成同范围验证，默认宿主上的失败没有改写。托管 Windows 的写入失败仍未解决，Linux arm64 和 macOS amd64 也未新增原生运行证据。这些结果只证明所覆盖的客户端与打包构件在合成登录、本地上游及指定宿主条件下可用；真实续接后的工具成功和正常结束、真实 Token 刷新及 Desktop/dot 仍需各自的验收证据。

这条流水线没有增加真实会话，不使用现有登录文件或真实验证的一次性入口。CI 结束时累计值仍为 7 次真实会话、40 次观察到的推理请求、1 次续接。之后另获授权执行的官方 `0.165.0` 单次真实验证单独记在 [官方版实测](LIVE-OFFICIAL-0165-2026-10-29.md)，不计入本页离线 CI 结果。
