# 原生客户端离线流水线

原有 `offline.yml` 会在没有安装客户端时跳过 Codex CLI、app-server、Pi 和插件联调。新增的 `native-clients.yml` 专门运行这四组测试，并增加原生写文件探针。缺少客户端、测试被跳过或缺少预期测试的完成记录，都会使这条流水线失败。

这条流水线已随 `066973b` 公开并在三个 GitHub runner 执行。macOS arm64 全部通过；Ubuntu amd64 和托管 Windows 的四组客户端普通/race 检查通过，但五个写文件场景全部失败。此前本机 Windows 的成功记录继续保留，不能将两种宿主环境混为一谈。

## 公开 CI：2026-10-29

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

新分类单测普通/race 各通过 1 项，vet 通过；本机 Windows 正向四组客户端普通/race 仍各通过 10 项，五个写入场景通过。源码与数字证据见 [工具结果诊断验证](evidence/native-tool-diagnostics-2026-10-29.json)。这份后续采集改动仍处于本地准备阶段，推送和新一轮 CI 需要对应授权。

## 执行内容

1. 按 [依赖锁文件](../ci/native-clients/package-lock.json) 安装 Codex `0.165.0` 和 Pi `1.4.0`；Node 固定为 `24.17.0`。客户端安装在项目 `.tools/native-clients`，安装时禁用 lifecycle scripts。
2. `build.ps1 -CurrentPlatform -WithCodexPlugin` 为当前机器生成独立包和插件包。原有默认 Windows amd64 与 `-AllPlatforms` 行为保留；两个平台选项不能同时使用。
3. 检查 ZIP 散列、文件路径和可执行权限位，解压到临时目录，再核对二进制散列。后续代理进程和插件安装都使用解压包。
4. 串行执行 CLI、app-server、Pi 和插件的普通及 race 测试，再单独执行五个写文件场景。Go 使用 `-p=1 -parallel=1`，CI 三个平台也按 `max-parallel: 1` 排队。
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

macOS arm64 的结果覆盖所测官方客户端、Pi 和 ZIP 解压包；Linux/托管 Windows 的写入问题仍待诊断，Linux arm64 和 macOS amd64 也未新增原生运行证据。即使三个系统均通过，也只证明所覆盖的官方客户端与打包构件在合成登录、本地上游下可用；真实续接后的工具成功和正常结束、真实 Token 刷新及 Desktop/dot 仍需各自的验收证据。

原有 7 次真实会话、40 次观察到的推理请求、1 次续接的累计值不变。之前准备的官方 `0.165.0` 单次真实验证仍待单独授权；这条流水线不使用那份登录文件或一次性执行入口。
