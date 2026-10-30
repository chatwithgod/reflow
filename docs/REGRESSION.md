# 回归测试与离线流水线

`scripts/verify.ps1` 运行 Go 测试、race、vet 和解码器 fuzz。不提供 `CodexExe`、`PiCli` 或 `PluginMarketplace` 路径时，对应客户端测试会明确跳过；这种运行不能替代原生客户端联调。提供完整参数的最新本地验收为 79 个通过项、0 跳过，使用本地修复版 Codex 和模拟上游，新增 app-server 的两种历史格式检查，见 [补充验证](APP-SERVER-2026-10-27.md)。此前 [dev.4 的 76 项](VERIFICATION-0.1.0-dev.4.md)和 dev.3 的 65 项记录继续保留。

默认回归不包含 `native_write_probe` 标签下的原生文件编辑探针。已测两版官方 Windows CLI 仍有失败记录；加入上游修复的本地构件已通过五个场景。不能把默认回归与这些定向结果混作同一次全量验收。复现命令和对照结果见 [写入探针](NATIVE-WRITE-PROBE.md)。

## 评测自检

在源码目录使用新增入口，会构建代理与合成 agent，然后运行进程检查和 4 项任务评分器自检。Windows 共 10 项进程检查；其他平台只包含 5 项通用检查：

```sh
python scripts/check-evaluation.py --go /absolute/path/to/go
```

也可用 `--proxy /absolute/path/to/reflow` 检查已有构件。这两条路径均已在 Windows 通过。报告位于 `build/evaluation-process/`，含步骤退出码、二进制散列和测试日志。

合成 agent 只接受测试凭据，通过本地健康接口检查参数，再写入参考解。它不是 Codex，不构成模型质量证据。自检不会读取真实账号或执行模型调用。

Windows 检查另覆盖 Code Mode 宿主缺失、原生文件 helper 启动失败、工作区外写入未被拦截时，在读取登录文件前停止。`python evaluations/run.py --preflight-only --codex /absolute/path/to/codex.exe` 可对指定客户端单独运行同一无账号检查；它不会进入模型试验。

## 公开 CI

源码中的 `.github/workflows/offline.yml` 将上述入口接入 Ubuntu、Windows 和 macOS 的托管运行器矩阵，固定 Go 1.26.8、Python 3.13。三个 GitHub 官方 action 固定到已核对的 v7 提交：

- [checkout](https://github.com/actions/checkout)：`3d3c42e5aac5ba805825da76410c181273ba90b1`
- [setup-go](https://github.com/actions/setup-go)：`b7ad1dad31e06c5925ef5d2fc7ad053ef454303e`
- [setup-python](https://github.com/actions/setup-python)：`6d4fd22b20465ccc0f7354476588e8df7c9ca0e0`

仓库权限为只读 `contents`，不配置模型凭据，不包含发布步骤。工作流未提供客户端路径，因此会跳过 Codex CLI、Codex app-server、Pi 和原生插件四项测试。工作流文件此前已通过 actionlint 1.7.12；2026-10-28 已随公开源码实际运行。首次发现路径文字比较断言在 Windows/macOS 失败；改用目录身份比较后，三个平台均为 69 个通过项、4 个跳过项，race/vet/fuzz 和合成进程、评分器自检通过。见 [CI 与修复记录](PUBLICATION-2026-10-28.md)。

首次本地离线脚本记为 78 个通过项、3 个客户端测试跳过，其中 20 个通过项来自 `dist` 中的适配器副本。现已添加模块边界排除生成目录，并重跑了完整客户端模拟验收。原始记录、计数更正和两种评测自检路径的证据见 [offline-ci-prep.json](evidence/offline-ci-prep.json)。该文件是公开 CI 运行之前的历史记录。

Magpie 的 `scripts/check-magpie.py` 支持 `--phase suite --race`，可用 `--compiler` 指定 C 编译器；`--serial` 使包编译/运行及并行测试各最多一个。入口保持临时用户目录、固定 Go 缓存和锁文件核对。历史夹具结果见 [Magpie 夹具记录](../adapters/magpie/WINDOWS-FIXTURES.md)，新下游 WebSocket 与固定上游移植见 [2026-10-30 记录](../adapters/magpie/UPSTREAM-2026-10-30.md)。

2026-10-30 的 [Pi 新 OpenAI 入口](PI-PUBLIC-RESPONSES-2026-10-30.md)补充公共 OAuth/API key SSE、保留原生 OAuth 字段限制的负向对照及五项传输边界检查。最新源码普通/race 各 80 通过、4 跳过，vet/fuzz 通过。`scripts/check-native-clients.py` 现在核对并加载解压包内的两个 Pi 扩展及辅助模块；另串行执行 `pi_probe` 标签的普通/race 检查，验证只读探针正常完成、限流停止和越界阻断。本机 Windows 原生普通/race 各 14 项、写入五场景及探针普通/race 各 4 项通过，全部合成凭据、真实模型调用 0；新改动尚未远程执行。

公开模块构建可指定 `--modfile go.reflow.mod`，与 `--workspace` 二选一；该路径相对 `--magpie`，必须在宿主源码目录内。入口传入 `-mod=readonly`，并核对默认及替代模块锁文件在检查前后没有变化。见 [公开模块验证](../adapters/magpie/PUBLIC-MODULE.md)。

2026-10-31 新增独立的 `scripts/check-magpie-external.py`，在固定且未修改的 Magpie checkout 前启动独立 Reflow，串行运行 7 场景普通/race、账号故障和标准模式对照。Reflow 与 Magpie 两侧均启用 race；原生客户端、真实账号及完整宿主测试不在此范围。该入口尚未接入 CI，命令及通过记录见[外置方案](../adapters/magpie/EXTERNAL.md)。本地完整 Reflow 普通/race 各 90 通过、4 跳过，vet 通过；使用当前项目文件的隔离副本，避免收进 build 目录中的历史故障样本。
