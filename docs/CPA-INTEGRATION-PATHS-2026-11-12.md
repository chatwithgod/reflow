# CPA 五平台首次运行与路径测试修正

经授权推送 `b041cd4` 后，CPA 工作流已成功创建并执行。首次分支创建为何没有触发仍未定论；此次已有分支的明确工作流变更已验证能够触发。远程 main、商店和现有安装未改。

## 固定 b041cd4 的结果

- [常规回归](https://github.com/chatwithgod/reflow/actions/runs/43074686422)：三个平台普通/race 各 97 通过、4 跳过，整条工作流通过。
- [原生客户端](https://github.com/chatwithgod/reflow/actions/runs/43074686397)：Ubuntu/macOS 全部通过；Windows 普通/race 各 14 通过，保留原有五个写入场景失败，因此工作流仍为失败。
- [CPA 五平台](https://github.com/chatwithgod/reflow/actions/runs/43074686530)：Linux amd64/arm64 全部通过，打包前后各 46 个原生 ABI 场景通过。两份 CI 构件下载后已核对源码、许可证、动态库和报告散列。
- CPA 的 macOS amd64/arm64 与 Windows amd64：Go 普通/race/vet/fuzz 和动态库编译通过，随后 52 项 Python 检查中的一项失败；原生 ABI 与 ZIP 打包尚未执行，汇总任务跳过。这与独立版的托管 Windows 沙箱限制是两个不同问题。

全部运行、数字及已下载构件的散列见[本轮证据](evidence/cpa-integration-ci-paths-2026-11-12.json)。真实模型调用为 0。

## 已定位的测试误判

新增的 `test_snapshot_keeps_relative_core_dependency_and_excludes_outputs` 用原始临时路径与 `snapshot_source()` 返回的规范路径比较。macOS 的 `/var/...` 与 `/private/var/...`、Windows 的 `RUNNER~1` 与长目录名指向同一位置，却导致字符串路径不相等。

修正只对预期路径执行 `resolve()`。生产快照函数、Go 核心、CPA 接入、文件内容散列、相对核心依赖、无关输出排除和拒绝覆盖检查均保留。共用运行源码指纹仍为 `40b8a1ae0374b0935a4afef3166828b83536aa173aad1746bb5c9598664960e1`。

本机通过临时目录别名复现了旧测试的同一失败；修正后普通临时目录与别名临时目录分别运行完整 Python 校验，各 52 项通过。该修正尚未推送，也未获 macOS/托管 Windows 的远程复验，不能用本地对照代替剩余平台验收。
