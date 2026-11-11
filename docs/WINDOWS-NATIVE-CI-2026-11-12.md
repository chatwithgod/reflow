# 托管 Windows 五个写文件失败：修复候选

当前问题出在测试机的沙箱条件：CI 强制使用 MXC，但 GitHub 的 Windows Server runner 报告 `mxc_unavailable`。绕过 Reflow 的补丁用例也失败。最新失败基线是 `297966b` 的[原生 CI](https://github.com/chatwithgod/reflow/actions/runs/43099211239)。这与本机 Windows 已通过同样五个场景并不矛盾。

本次让托管 Windows 使用 Codex 官方支持的 `elevated` 沙箱。它需要管理员准备低权限沙箱账号、文件 ACL 和防火墙规则；运行工具的账号仍受沙箱限制。官方将它列为 MXC 不可用时的后备方案，见 [Windows sandbox](https://learn.chatgpt.com/docs/windows/windows-sandbox)。实现接口已核对固定 `rust-v0.165.0`、提交 `360319d8dee62d87e2d59fc0c21805d79519cfed` 的源码。

## 修改范围

- 仅 `native-clients.yml` 的托管 Windows 任务显式传入 `--windows-elevated`。本机默认仍为 MXC，Linux/macOS 路径不变。
- 开始前检查 GitHub 托管环境、Windows Server、仓库、运行标识、管理员身份及临时目录。已有 Codex 沙箱账号、组、规则或安装记录时拒绝准备，也不执行卸载。
- 使用官方 `codex sandbox setup --elevated --user … --codex-home …` 准备隔离目录。每个写入场景仍有自己的临时登录和工作目录，串行准备，不复制沙箱凭据。
- 原来五个场景全部保留：经代理改文件、直接改文件、直接新建文件、关闭 daemon 后改文件、经代理用命令写文件。文件内容、被丢弃操作未执行、MCP 读回、结果回传和续接计数都继续检查。汇总还要求五个子测试和父测试逐项完成，漏测或跳过均失败。
- 在进入用例前，必须通过直接沙箱命令、文件系统 RPC 的允许写入与越界拒绝，以及本地 TCP 端口的沙箱外可达/沙箱内阻断对照。
- 失败或结束后调用官方 `codex sandbox uninstall`，检查沙箱账号、组、已知规则、WFP 对象等已移除，系统防火墙启用状态未改变，再清理临时目录。官方卸载不恢复所有 ACL，因此仅用于任务结束后销毁的托管 runner，不能解释为整台系统恢复到逐字节一致。

原生测试矩阵 `max-parallel: 1`、Go `-p=1 -parallel=1` 保持不变。每个 CLI 用例仍最多 35 秒；新增的每次准备最多 120 秒，写入阶段单独给足串行准备时间。使用固定客户端、合成登录和本地模拟上游，真实模型调用为 0。Reflow 核心、CPA 接入、生产设置和已发布构件未改。

## 首次推送前的本地验证

| 检查 | 结果 |
| --- | --- |
| 准备、失败、清理、越界和汇总控制 | 20 项通过；无主机设置变更 |
| Go 选择及目录范围检查 | 普通/race 各 9 项通过，含父测试；vet 通过 |
| 本机原生客户端普通/race | 各 14 项通过 |
| 原来五个写文件场景，默认 MXC | 5/5 通过；含父测试为 6 项 |
| Pi 模拟探针普通/race | 各 4 项通过，无真实登录 |
| 本机直接命令、文件 RPC、越界写入拒绝 | 通过 |
| Windows 只读资源采集及拒绝在本机准备 | 通过；没有执行 setup/uninstall |
| 二进制与临时目录 | 二进制未变，测试目录已移除 |
| GitHub Windows Server 的 elevated 实测 | **尚未运行，不能宣称五项 CI 已修复** |

本机原生回归验证的是原有 MXC 路径；新增 elevated 路径目前只有控制测试与接口核对。后续须在托管 Windows 实际通过原来的五个写入场景及新边界、清理检查，才能完成验收。历史失败记录保留。

数字、源码与日志散列见[机器可读证据](evidence/windows-native-ci-preparation-2026-11-12.json)。后续远程结果应追加单独记录，不回写本次准备时的状态。

## 首轮托管对照

`af60eb1` 的[常规 CI](https://github.com/chatwithgod/reflow/actions/runs/43104607402)三平台通过，普通/race 各 106 项、4 项可选客户端检查跳过。专用[原生 CI](https://github.com/chatwithgod/reflow/actions/runs/43104607408)中，Ubuntu/macOS 的普通/race 各 14 项、五个写文件场景、Pi 普通/race 各 4 项通过。

Windows 已成功准备 elevated 沙箱，直接命令写文件、文件系统 RPC 写入与越界拒绝均通过；但 PowerShell 网络探针没有达到通过条件，因此五个正式场景尚未执行。摘要不足以判断是网络放通、进程启动还是输出处理问题，不能把它补判为其中任何一种。官方卸载成功，账号、组、规则、WFP 对象均已清理，三个防火墙配置的启用状态未变。

后续候选将网络探针替换为固定 Go 小程序，只接受 `127.0.0.1` 与有效端口；仍要求相同端口在沙箱外连通、沙箱内阻断，并新增阻断后的再次连通检查。记录退出码、字节数和固定标记，不记录正文。新增控制检查共 22 项通过；该程序在本机真实完成连通/拒绝连接检查，拒绝远程地址和非法参数，未套沙箱时不能误判为网络隔离成功。未在本机运行 elevated setup/uninstall；下一轮托管结果仍待验证。

本轮实际任务时间没有重叠，并发 1，真实模型调用 0。完整证据见[首轮托管记录](evidence/windows-native-ci-first-run-2026-11-12.json)。

## 入口

普通本机检查仍使用：

```powershell
python scripts/check-native-clients.py
```

新增控制检查不准备账号或修改主机：

```powershell
python scripts/test-windows-native-sandbox.py
```

托管 Windows 由工作流调用 `python scripts/check-native-clients.py --windows-elevated`。该参数在本机、其他仓库或非托管环境会被拒绝。只上传数字和固定标记摘要，不上传账号身份、沙箱凭据、模型正文或原始诊断日志。
