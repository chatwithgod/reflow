# 回归测试与离线流水线

`scripts/verify.ps1` 运行 Go 测试、race、vet 和解码器 fuzz。不提供 `CodexExe`、`PiCli` 或 `PluginMarketplace` 路径时，对应客户端测试会明确跳过；这种运行不能替代原生客户端联调。提供完整参数、排除构件副本并增补 Code Mode 回归后的 dev.3 本地验收为 65 个通过项、0 跳过，见 [验证记录](VERIFICATION-0.1.0-dev.3.md)。

## 评测自检

在源码目录使用新增入口，会构建代理与合成 agent，然后运行 5 项进程检查和 4 项任务评分器自检：

```sh
python scripts/check-evaluation.py --go /absolute/path/to/go
```

也可用 `--proxy /absolute/path/to/reflow` 检查已有构件。这两条路径均已在 Windows 通过。报告位于 `build/evaluation-process/`，含步骤退出码、二进制散列和测试日志。

合成 agent 只接受测试凭据，通过本地健康接口检查参数，再写入参考解。它不是 Codex，不构成模型质量证据。自检不会读取真实账号或执行模型调用。

## CI 草稿

源码中的 `.github/workflows/offline.yml` 将上述入口接入 Ubuntu、Windows 和 macOS 的托管运行器矩阵，固定 Go 1.26.8、Python 3.13。三个 GitHub 官方 action 固定到已核对的 v7 提交：

- [checkout](https://github.com/actions/checkout)：`3d3c42e5aac5ba805825da76410c181273ba90b1`
- [setup-go](https://github.com/actions/setup-go)：`b7ad1dad31e06c5925ef5d2fc7ad053ef454303e`
- [setup-python](https://github.com/actions/setup-python)：`6d4fd22b20465ccc0f7354476588e8df7c9ca0e0`

仓库权限为只读 `contents`，不配置模型凭据，不包含发布步骤。工作流未提供客户端路径，因此会跳过 Codex、Pi 和原生插件三项测试。它已通过 actionlint 1.7.12，本地 Windows 执行了对应脚本；尚未推送或在 GitHub Actions 运行，不能作为 Linux/macOS 已运行的证据。

首次本地离线脚本记为 78 个通过项、3 个客户端测试跳过，其中 20 个通过项来自 `dist` 中的适配器副本。现已添加模块边界排除生成目录，并重跑了完整客户端模拟验收。原始记录、计数更正和两种评测自检路径的证据见 [offline-ci-prep.json](evidence/offline-ci-prep.json)。CI 未执行的边界不因这次本地复查而改变。
