# Ubuntu 原生写入：发行版沙箱依赖对照

状态：本地候选流程和控制测试已准备，尚未推送，也未在 Ubuntu 上执行。没有新增真实账号调用。

此前[第四轮宿主对照](NATIVE-CI.md)确认，Ubuntu runner 的独立 user namespace/UID 映射检查被拒绝，直接 Codex 沙箱命令也因 bubblewrap 权限失败。AppArmor 的全局 user namespace 限制值为 1。现有证据没有证明全部补丁失败都来自同一原因。

[OpenAI 官方说明](https://learn.chatgpt.com/docs/sandboxing?surface=app&translationFallback=zh-Hans)建议在 Linux 安装发行版 `bubblewrap`；Ubuntu 24.04 可能还需要加载发行版附带的 `bwrap-userns-restrict` 配置。[Codex 0.165.0 的启动代码](https://github.com/openai/codex/blob/rust-v0.165.0/codex-rs/linux-sandbox/src/launcher.rs)也优先选择系统 bwrap，并检查其支持的选项。此次候选对照依据这一路径，不修改 Reflow、Codex 二进制或原有五个写入场景。

## 准备的执行流程

单独的 [Linux 工作流](../.github/workflows/linux-sandbox-control.yml)只接受手动触发，确认开关默认为关闭。脚本还检查仓库、工作流名称、手动事件、GitHub 托管环境、Ubuntu 24.04 amd64 和非 root 用户。与原生客户端工作流共用串行队列，跨工作流也只运行一个原生客户端任务。

1. 在同一临时 runner 先运行原来的完整客户端检查。若已经全部通过，仅补查文件和网络边界，不安装软件或加载配置。
2. 只有普通/race 均通过、五个写入场景全部失败，并复现原先的 bubblewrap/UID 映射拒绝时，才继续尝试发行版依赖。其他失败直接停止。
3. 在该临时 runner 安装 `bubblewrap`、`apparmor-profiles`、`apparmor-utils`，记录安装前后的相关软件包版本与系统 bwrap 散列，再进行无账号对照。若安装软件包已解决直接启动问题，不额外加载配置。
4. 若仍失败，只读取发行版原文件，确认它声明的配置名称恰好是 `bwrap` 和 `unpriv_bwrap`，且同名配置尚未加载，才用 `apparmor_parser --add` 加载。拒绝覆盖已有配置，不复制自定义规则到系统目录，也不修改全局 sysctl。
5. 再运行原来的普通、race 和五个写入场景，所有断言仍必须通过。另用无账号直接命令检查工作区可写、工作区外写入被拒绝，以及普通进程可连接的本地监听端口在沙箱内不可连接。
6. 正常或异常退出时，移除本次尝试加载的两项配置，包括部分加载的情况；核对配置确已移除、记录的三项内核设置未变。若手动加载解决了直接启动问题，卸载后还必须再次复现原先的拒绝，才能完成前后对照。

边界探针的临时目录位于 checkout 的同级目录，拒绝写入的目标同时位于工作区、`TMPDIR` 和 `/tmp` 之外，避免把默认允许的临时文件写入当作越界。网络探针只连接同机临时监听端口，不访问账号或模型服务。

软件包安装和配置加载会改变这台临时 Ubuntu runner，所以执行需要新的明确授权。软件包保留到该 runner 销毁，不尝试卸载系统依赖；本脚本显式移除自己加载的配置。任务被平台强制终止时，依赖临时 runner 的销毁回收，不能保证 Python 的清理代码有机会运行。Windows 本机和生产 CPA/ECPA/Codex 配置不参与这一步。

## 本地验证与范围

控制测试使用固定的历史 CI 数字记录和替代操作对象，不执行 sudo、apt 或 AppArmor。覆盖未授权或不匹配环境拒绝、异常基线停止、原生断言缺失拒绝、已有配置保护、部分加载清理、候选仍失败、边界检查缺失或失败、全局设置变化和清理失败。另用本地短生命周期 Python 子进程验证输出内容不进入摘要，以及超时停止。

运行方式：

```powershell
python scripts/test-linux-sandbox-control.py
python scripts/check-linux-sandbox.py --check-only
```

这些检查不能证明 Ubuntu 内核会接受发行版配置，也不能证明五个补丁场景会恢复。实际报告将分别记录安装软件包、加载配置和卸载配置的阶段；不能把整个依赖安装过程的效果都归因于单独一条 AppArmor 规则。任何最终原生断言、文件/网络边界或清理核对失败，新的手动任务仍判失败。原来的三平台原生流水线不自动加载配置，既有失败不会被隐藏。

机器可读的准备记录见 [本地验证证据](evidence/linux-sandbox-control-preparation-2026-10-29.json)。AppArmor 的添加、拒绝覆盖及移除语义按 [Ubuntu 24.04 手册](https://manpages.ubuntu.com/manpages/noble/man8/apparmor_parser.8.html)核对。
