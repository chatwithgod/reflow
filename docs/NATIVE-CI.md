# 原生客户端离线流水线

原有 `offline.yml` 会在没有安装客户端时跳过 Codex CLI、app-server、Pi 和插件联调。新增的 `native-clients.yml` 专门运行这四组测试，并增加原生写文件探针。缺少客户端、测试被跳过或缺少预期测试的完成记录，都会使这条流水线失败。

这条流水线已在本机 Windows 通过，尚未推送，也尚未在 GitHub 的 Linux/macOS runner 执行。它不能提前补齐另外两个系统的验收。

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

Linux/macOS 要等对应 runner 实际执行成功后才更新状态。即使三个系统均通过，也只证明所覆盖的官方客户端与打包构件在合成登录、本地上游下可用；真实续接后的工具成功和正常结束、真实 Token 刷新及 Desktop/dot 仍需各自的验收证据。

原有 7 次真实会话、40 次观察到的推理请求、1 次续接的累计值不变。之前准备的官方 `0.165.0` 单次真实验证仍待单独授权；这条流水线不使用那份登录文件或一次性执行入口。
