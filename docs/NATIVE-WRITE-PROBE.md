# Windows 原生写文件离线复现

2026-10-26，在当前 Windows 环境中，Codex 的 `apply_patch` 写文件探针失败。经过 Reflow 和绕过 Reflow 都能复现，普通命令写文件则通过。进一步检查已确认原生文件系统 helper 因遗漏 `SYSTEMROOT` 而无法启动；候选补丁尚未编译验收，完整原生工作区编辑兼容性仍未通过，不能用默认回归通过来覆盖。

## 已运行的对照

测试使用真实 CLI、临时用户目录、合成登录凭据和本地模拟上游；并发为一个测试客户端，不调用真实模型。写入权限为 `:workspace`，Windows 使用 MXC。探针核对宿主文件内容、被丢弃工具没有执行、MCP 读回结果，以及下一轮请求确实包含该结果。

| 操作 | Desktop 所带 CLI `0.164.0-alpha.11.1` | 隔离安装的官方 CLI `0.164.0` |
| --- | --- | --- |
| 经 Reflow 续接后，`apply_patch` 修改现有文件 | 失败 | 失败 |
| 绕过 Reflow，`apply_patch` 修改现有文件 | 失败 | 失败 |
| 绕过 Reflow，`apply_patch` 新建文件 | 失败 | 失败 |
| 绕过 Reflow，关闭 daemon 后修改文件 | 未运行 | 失败 |
| 经 Reflow 续接后，命令写文件并读回 | 通过 | 通过 |

失败的补丁用例记录了 `backend=windows_mxc reason=failed_to_write_file`，目标文件未按要求改变。命令用例通过三次模拟上游响应完成一次续接、实际文件修改和工具结果回传；丢弃轮次的写入没有执行。

官方 CLI 通过独立 npm 目录安装并固定版本，没有替换 Desktop 的 CLI 或修改生产配置。版本、二进制和日志散列见 [机器可读证据](evidence/native-write-probe-2026-10-26.json)。

## 已确认的 helper 启动故障

直接调用两版 CLI 的本地 stdio exec-server，在同样的 MXC 文件写入路径得到底层错误：显式子进程环境缺少 `SYSTEMROOT`。官方 `0.164.0` 源码的文件系统 helper 白名单确实漏掉这个变量；补丁工具仅显示外层写入错误。

控制实验保持文件和网络权限不变：缺少该变量时无法启动；仅保留宿主的 `SystemRoot` 后，允许目录内写入成功；目录外写入仍被拒绝。已准备最小白名单修复和单元测试补充，但本机缺少 Rust 工具链，尚未编译修复后的 CLI。复现脚本、源码定位和可审阅补丁见 [Codex 上游贡献草稿](../contrib/codex-windows-mxc/README.md)。以上检查均无账号和模型调用。

## 其他已排查因素

- 保留 `SystemDrive` 后，MXC 的固定命令写入预检通过；本探针已保留该变量。
- MXC 内的 PowerShell 为 `ConstrainedLanguage`：直接调用 `.NET` 写文件方法报 `MethodInvocationNotSupportedInConstrainedLanguage`，而 `Set-Content` 和 `cmd` 重定向均能修改宿主工作区文件。上述原生补丁路径使用 Rust helper，不能用这个 PowerShell 限制解释其环境变量遗漏；没有修改系统语言策略。
- 早期绕过代理的用例先在模拟账号路由阶段失败，不能用作文件写入对照。修正本地 TLS 账号查询后，才得到上表所列结果。

真实测试没有保留工具错误正文，模拟上游也不包含真实服务的全部元数据。因此这些结果不能证明真实测试中的工具失败或 180 秒超时由同一问题导致，也不能证明 Reflow 在所有真实路径中无关。真实追加诊断正常结束但未触发续接，结论仍见 [真实测试记录](LIVE-SMOKE-2026-10-26.md)。

## 复现入口

设置 `REFLOW_CODEX_BIN` 指向待测 CLI；可选 `REFLOW_PROXY_BIN` 指向打包 Reflow，未设置时使用测试内代理。然后在项目根目录运行：

```powershell
go test -tags native_write_probe ./integration -run '^TestCodexNativeWriteProbe$' -count=1 -timeout=5m -json
```

五个场景串行执行。当前环境的补丁失败会使此命令返回非零退出码，不是预期通过测试，也没有被改写为跳过。测试仅使用临时目录内的合成登录信息。

默认 `scripts/verify.ps1` 不包含这个显式构建标签。其最近一次结果为 65 个通过项、0 跳过，race/vet/fuzz 通过；该结果覆盖协议和 MCP 路径，不能表述为原生写文件探针已通过。下一步需要编译验证候选修复，并分别复验原生补丁写入与真实续接后的完整会话；真实调用仍须另行授权。
