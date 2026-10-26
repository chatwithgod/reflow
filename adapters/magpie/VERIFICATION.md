# Magpie 适配验证（本地开发）

基准为 `yetone/magpie@a1174674da9d1435443e95ffac7d0300ce8b59d6`，Reflow 为 `0.1.0-dev.3`。所有调用使用合成凭据和模拟上游；没有启动生产 Magpie 或调用真实账号。

本页保留首次验证的范围。后续的测试夹具修正、完整回归及 Reflow dev.4 桥接 race 检查见 [2026-10-27 记录](WINDOWS-FIXTURES.md)。

本地提交依次为 `86f6f917`（cgroup 根路径修复）、`095889c0`（宿主执行扩展）、`7833faf3`（可选桥接）。提交后的工作区干净，代码内容与上述测试时一致；没有推送或提交 PR。

## 已通过

- 原生 HTTP、zstd、上游 WebSocket、托管 Responses 透传四条路径：隐藏中间工具，保留最终工具，并将下一轮工具结果与完整历史发回上游。三次实际模拟上游调用；跨新 WebSocket 的恢复不依赖旧连接保存的父响应 ID。
- 用量读取按多轮实际报告计入宿主账本，客户端可见 `usage` 不改；非法或低估任一原用量项的元数据回退。跨协议翻译旁路。
- 注册/解除、默认关闭、调用预算、上一响应关闭要求、取消与协程回收。定向 race 日志：`build/magpie-reflow-race-fixed.log`。
- Windows 普通构建与 vet；Windows `nogui` vet、`nogui reflow` 构建；Linux `nogui` 构建与 vet。构建不等于 GUI 运行或 Linux 原生验收。
- 三份补丁按顺序应用到基准提交的临时索引后，19 个改动文件与工作区内容一致。清单及 SHA256 见 [patches/manifest.json](patches/manifest.json)。

反向检查也真实失败：恢复旧 cgroup 根路径判断，`TestCgroupRootWalkTerminates` 报父目录遍历不终止；断开原生网关的扩展接线，`TestExecutionExtensionThroughNativeCodexGateway` 只收到一次上游调用，并泄露第一轮响应。随后恢复修复并验证通过。失败日志分别为 `build/magpie-cgroup-negative.log` 和 `build/magpie-execution-negative.log`。

## 全量宿主测试未通过

| 运行 | 通过项 | 跳过项 | 失败项 |
| --- | ---: | ---: | ---: |
| 修改版全量 `nogui`，原隔离环境 | 12180 | 615 | 60 |
| 干净基准，改进隔离环境后复查原失败项 | 12 | 0 | 50 |
| 修改版，相同改进环境和相同复查范围 | 12 | 0 | 50 |

复查使用较短的临时目录，并仅给测试子进程启用 Git 长路径设置；没有修改系统或全局 Git 配置。两份复查的失败测试名称集合完全一致，没有只在修改版出现的失败项。这只说明这组复查范围内的差异，不能将宿主全量测试写为通过，也不能断言所有失败原因已经查清。

可复查名称、命令和记录散列见 [精简证据](../../docs/evidence/magpie.json)。这些基准失败仍需在上游接收或发布前继续排查、修复或提交明确问题；本地 PR 草稿不代表上游 issue 已建立。

## 复现

先按补丁清单应用到固定基准。普通宿主检查无需 Reflow 依赖；带 `reflow` 标签的检查需用 `go.work` 同时引用 Magpie 和本仓库。使用 `scripts/check-magpie.py` 可将 HOME、应用目录和缓存分开，并保存独立日志。例如：

```sh
python scripts/check-magpie.py --magpie /absolute/path/to/magpie --go /absolute/path/to/go --phase suite --packages ./internal/gateway ./internal/gwexec --run '^Test(Execution|FoldedUsage|Bounds|Registration|Cgroup)'
python scripts/check-magpie.py --magpie /absolute/path/to/magpie --go /absolute/path/to/go --phase suite --tags 'nogui reflow' --workspace /absolute/path/to/go.work --packages ./internal/gateway ./plugins/reflow --run '^Test(Reflow|ZeroDefault)'
```

本地编译依赖预先下载到 Go 缓存；检查脚本设 `GOPROXY=off`。普通全量检查仍会包含上述已知未通过项，不会自动跳过它们。
