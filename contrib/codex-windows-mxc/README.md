# Codex Windows MXC：文件系统 helper 遗漏 SystemRoot

本目录保存本地复现脚本和待审阅补丁，没有提交上游，也没有替换用户的 Codex。

在当前 Windows 环境，CLI `0.164.0` 和 `0.164.0-alpha.11.1` 的原生沙箱文件写入 RPC 都返回：MXC 的显式子进程环境缺少 `SYSTEMROOT`，无法启动 helper。源码中的环境白名单保留了 `SystemDrive`、`LOCALAPPDATA` 和 `PATH`，漏掉了 `SystemRoot`。[固定源码](https://github.com/openai/codex/blob/6aaac694803004a63c6f393d153c96d22521a6b9/codex-rs/exec-server/src/fs_sandbox.rs#L371-L382)

仅给相同 MXC 启动请求补回宿主的 `SystemRoot`，允许目录内写入就成功；目录外写入仍返回拒绝访问。测试没有启用默认环境继承，也没有放宽文件或网络权限。原生 `apply_patch` 经此文件系统 helper 执行；底层错误在补丁工具输出中被外层“Failed to write file”掩盖。[调用路径](https://github.com/openai/codex/blob/6aaac694803004a63c6f393d153c96d22521a6b9/codex-rs/core/src/tools/runtimes/apply_patch.rs#L177-L200)、[错误输出](https://github.com/openai/codex/blob/6aaac694803004a63c6f393d153c96d22521a6b9/codex-rs/apply-patch/src/lib.rs#L408-L425)

## 离线复现

需要 Windows 原生 MXC、Python 3 和上述两版 CLI 之一。脚本使用已核对的内部接口，因此拒绝其他版本；不登录、不调用模型、不读取现有配置，只在自动清理的临时目录内运行固定请求。测试进程串行执行。

```powershell
python reproduce.py --codex C:/absolute/path/to/codex.exe --report-dir D:/temporary/reflow-mxc-reports
```

它先用本地 stdio exec-server 取得底层错误，再对照缺少/保留 `SystemRoot` 的启动环境，并核对目录外写入仍受限制。退出码 0 表示成功复现缺陷并通过环境控制实验，**不表示原生编辑兼容性通过**。报告明确设置 `native_patch_compatibility_accepted=false`。两版 CLI 均已运行通过这套诊断；机器可读结果见 [证据记录](../../docs/evidence/native-write-probe-2026-10-26.json)。

## 最小候选补丁

`systemroot.patch` 基于 OpenAI Codex 标签 `rust-v0.164.0`，提交 `6aaac694803004a63c6f393d153c96d22521a6b9`。只扩充 Windows helper 的白名单，并在现有单元测试中覆盖混合大小写的 `SystemRoot`，同时拒绝相似前缀和密钥变量。

已验证补丁可应用到该提交，结果与本地候选文件一致。当前机器没有 Rust 工具链，**尚未运行 Rust 单元测试、编译修复后的 CLI 或完成其原生工具复测**。对应检查命令是在 Codex 源码的 `codex-rs` 目录中运行：

```powershell
cargo test -p codex-exec-server --lib helper_env_preserves_windows_runtime_variables_without_leaking_secrets
```

补丁沿用 [OpenAI Codex 的 Apache-2.0 许可证](https://github.com/openai/codex/blob/6aaac694803004a63c6f393d153c96d22521a6b9/LICENSE)。本地 Reflow 的协议代码没有因此改动。公开报告 [#56918](https://github.com/openai/codex/issues/56918) 存在相同表面报错，但不能据此认定对方根因相同。

本诊断解释了可复现的 helper 启动故障，不证明此前真实会话的 180 秒超时由它造成。真实续接后的完整会话仍待单独验收。
