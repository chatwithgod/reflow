# 2026-10-28：公开源码与三平台离线 CI

用户授权后，已创建公开仓库 [chatwithgod/reflow](https://github.com/chatwithgod/reflow)，将此前审阅的 `d5fea7d5d74400504e801ca00be9241b7b816871` 及其历史推送到 `main`。这是开发预览源码；没有发布二进制 Release、上架商店、提交 Magpie 上游 PR 或提交 OSS 申请。

## 首轮失败及修复

[首次 CI](https://github.com/chatwithgod/reflow/actions/runs/40678141661) 中，Linux 通过，Windows 和 macOS 都在 `TestPluginHomeUsesOwningProfileAndRejectsUnknownLayout` 失败。插件目录发现会解析路径，但测试直接比较路径文字；Windows 短路径以及 macOS `/var` 与 `/private/var` 的别名可能指向同一目录，写法却不同。

本机用 Windows 短路径临时目录复现了旧断言失败。修复使用 `os.Stat` 和 `os.SameFile` 核对实际目录归属，未知插件布局的拒绝断言继续保留。运行时代码没有改动。修复后的同一复现通过；本地离线回归为 69 个通过项、4 个客户端测试跳过，race、vet、fuzz 和 10 项评测进程检查通过。

修复提交：[23eb3be](https://github.com/chatwithgod/reflow/commit/23eb3bef11f2cb5951599d08ca6ecd76a946619d)。

## 三平台复核

[修复后的 CI](https://github.com/chatwithgod/reflow/actions/runs/40679721072) 在三个平台均已完成并通过：

| 平台 | 普通 Go 回归 | Race | Vet / fuzz | 评测进程及评分器自检 |
| --- | --- | --- | --- | --- |
| Windows | 69 通过、4 跳过 | 通过，同样 4 跳过 | 通过 | 通过 |
| Linux | 69 通过、4 跳过 | 通过，同样 4 跳过 | 通过 | 通过 |
| macOS | 69 通过、4 跳过 | 通过，同样 4 跳过 | 通过 | 通过 |

四项跳过分别是 Codex CLI、app-server、Pi 和原生插件联调，原因是远程流水线没有安装并指定这些客户端。代理协议测试使用模拟客户端和上游；进程自检会构建 Reflow 与合成 agent，检查启动、开关、退出、限流和超时等行为。这些结果不等于真实 OAuth、官方客户端或已打包下载构件在三个系统上均验收通过。

来源与散列、两次 CI 的提交及状态、测试计数、修复前后复现见 [机器可读记录](evidence/publication-2026-10-28.json)。首次失败记录保留，没有用重新运行来掩盖失败。

## 仍未完成

本次没有新增真实模型调用，生产 CPA/ECPA/Codex 配置没有改动。真实测试累计仍是 7 次会话、40 次推理请求、1 次续接。完整真实续接闭环、Desktop/dot 界面和真实 Token 刷新仍未验收；Magpie 宿主全量仍有 36 个失败项。公开源码及离线 CI 通过没有改变这些限制。
