# 五平台构建、验收与发布边界

## 当前构建目标 v0.1.3

完整 ABI 套件为 46 项，每个平台分别在构建库和 ZIP 解出库上执行；每组五平台合计 230 次执行，不是 460 种不同场景。正式发布前必须完成本版原生构建、同字节验收和公开资产核对，不能直接沿用旧版结果。

## 历史正式版 v0.1.2

`v0.1.2` 已完成五个平台的原生构建和公开下载核验。当时完整 ABI 套件为 34 项，每个平台在构建库、包内库上各执行一组；每组共 170 次执行。完整来源、Windows CPA 回归与公开资产哈希见 [2026-10-24 发布记录](RELEASE-2026-10-24-0.1.2.md)。

下文保留 v0.1.1 的发布背景，通用构建命令和示例输出目录已按当前版更新。

## 目的与授权边界

商店 [PR #222](https://github.com/router-for-me/CLIProxyAPI-Plugins-Store/pull/222) 因缺少 Linux/macOS 资产被关闭，
[issue #1](https://github.com/LaoPiLao/cpa-plugin-codexreflow/issues/1) 明确要求五个组合：

| GOOS / GOARCH | 原生 GitHub runner | ZIP 根部动态库 |
|---|---|---|
| windows / amd64 | windows-2025 | codexreflow.dll |
| linux / amd64 | ubuntu-24.04 | codexreflow.so |
| linux / arm64 | ubuntu-24.04-arm | codexreflow.so |
| darwin / amd64 | macos-15-intel | codexreflow.dylib |
| darwin / arm64 | macos-15 | codexreflow.dylib |

runner 名称/架构依据 [GitHub 官方列表](https://docs.github.com/en/actions/reference/runners/github-hosted-runners#standard-github-hosted-runners-for-public-repositories)
核对（2026-10-09）。使用原生 runner，不把交叉编译成功当作可以加载执行。
工具链固定 Go `1.26.8`，SDK 仍为 CPA `v8.0.13`，actions 固定到具体 commit；v0.1.3 增加工具 schema 兼容修复，续接策略不变。

**`v0.1.1` 已于 2026-10-09 公开发布**，五个 ZIP 与统一 checksums 均经匿名下载逐字节核验。
发布来源为 main 提交 `6c71eee479e9939a3d300b9231117fae11eef296` 的
[原生 CI #37916034316](https://github.com/LaoPiLao/cpa-plugin-codexreflow/actions/runs/37916034316)，
五个平台及汇总 job 全部成功；公开 Windows DLL 本地另通过同组 31 项离线案例。
详见 [发布与下载记录](RELEASE-2026-10-09-0.1.1.md)，不是仅据 workflow 声称通过。

10 月 11 日对正式 Windows ZIP 内的同一 DLL 另完成固定 CPA `8.0.13` / `8.0.15` / `8.0.16`
各 50 次合成隔离 HTTP/WS 用例执行及 31 项原生 ABI；10 月 12 日核对同字节和报告哈希。
见 [Windows 正式包隔离验收](VALIDATION-2026-10-12-0.1.1.md)。这是新增的 Windows 集成层证据，
不是 Linux/macOS CPA 集成或五平台全面真实模型验收，也没有重新构建/上传正式资产。

构建/打包、main 合并、Release 和商店重提分别取得授权；
[PR #225](https://github.com/router-for-me/CLIProxyAPI-Plugins-Store/pull/225) 已于 10 月 10 日合并，10 月 11 日读回官方注册表已收录。
见 [收录核对记录](STORE-LISTING-2026-10-11.md)及历史[商店重提记录](STORE-SUBMISSION-2026-10-09-0.1.1.md)。本次同步文档，不另发/评论 PR、不安装或启用生产插件、不调用真实模型。
`v0.1.0` / `v0.1.1` 正文、ZIP、checksums、远程标签及此前开发构件保留不动。
当次发布的 `VERSION` 为 `0.1.1`，当前构建目标为 `0.1.3`；此后 CI 产生的新候选与已发布字节区分，不能覆盖同名 Release 资产。
工作流权限为 `contents: read`，仅上传有期限的 CI 候选 artifact，没有自动发布步骤。

## 每个平台的实际检查

`scripts/build_platform.py` 在匹配的 64 位原生主机上执行：

1. 确认源码已提交、宿主/Go 架构一致、CGO 开启、Go/SDK 固定。
2. 对根目录 Go 模块字节快照运行 unit、race、vet，以及 decoder/schema 各 15 秒 fuzz，避开 ignored `build` 内的其他项目。
3. 用明确版本和本项目仓库链接生成 **新的** c-shared 动态库，不覆盖原来的非版本化构建。
4. 跑全部 Python 回归（当前为 48 项）和实际库的 46 项 C ABI mock-host 测试；核对库哈希及测试版本。
5. `package_release.py` 检查 PE/ELF/Mach-O 类型与架构，真实加载并读回插件 ID/版本/仓库；只打包动态库及三个保留许可文件。
6. 读回 ZIP、CRC、许可字节和原始库字节，只把已验证的根库写入新路径，重跑同一组 46 项原生测试。
7. 输出同提交/Go 源码指纹/同库的脱敏报告与 validation 记录；不把 raw 日志或配置塞入 ZIP。

输出目录及同名包不可覆盖。校验报告中的 unknown/失败不改成成功，缺一平台或报告不全即失败。
原生 ABI mock 使用合成宿主回调，**不是实际 CPA 进程/HTTP/WS、真实模型或 Desktop 测试**。
同一组 46 项在五种主机重复执行为 230 次；包装后再执行同组 230 次，不宣传为 460 种独立场景。

## 本地使用

需 Python 3.11+、匹配架构的 Go 1.26.8/C 编译器、CGO 开启。
Windows 使用既有、校验下载的项目内工具，先执行 `. ./scripts/dev_env.ps1`；不要在 Windows 上加载 Linux/macOS 库来伪造原生验收。
在已提交源码上选择当前宿主的组合，例如：

```text
python scripts/build_platform.py --goos windows --goarch amd64
python scripts/build_platform.py --goos linux --goarch arm64
python scripts/build_platform.py --goos darwin --goarch arm64
```

默认本地新库：`build/platform-<goos>-<goarch>/`；平台候选：`dist/0.1.3/<goos>_<goarch>/`。
重跑必须选择新的 `--build-dir` / `--output-dir`（仍在 ignored build/dist 下），不删除或覆盖历史输出。

## 五平台汇总

`.github/workflows/platform-packages.yml` 每个原生 job 上传一个 `platform-<goos>-<goarch>` artifact。
下载目录必须恰好包含五个平台子目录。每个子目录包含：

```text
codexreflow_0.1.3_<goos>_<goarch>.zip
checksums.txt
registration.json
native-smoke.json
packaged-native-smoke.json
validation.json
```

汇总命令：

```text
python scripts/assemble_release.py --input-dir .tools/platform-artifacts --output-dir dist/full-platform-candidate --repository https://github.com/chatwithgod/cpa-plugin-codexreflow
```

汇总器不执行外平台库；验证的是同次可信 CI 的原生报告，不是密码学证明或全面集成认证。
要求所有平台使用同一源码提交及根 Go 指纹，检查注册信息、测试完整性、逐个报告/库/ZIP 哈希、许可字节、架构和无额外文件。
全部通过才生成五个 ZIP、统一五行 SHA256 `checksums.txt` 及独立 `validation-summary.json`；
该 JSON 是验收资料，不放入安装 ZIP 或作为本次 Release 的上传资产。

## 仍需独立验收的边界

- 本次五平台已经实际构建/加载并读回 job、候选及公开下载字节；后续每个新构件仍需独立报告，不能只引用本次通过。
- ABI 通过不替代每个平台的实际 CPA 宿主/HTTP/WS；旧 Windows `v0.1.0` 隔离报告或 dev.5 在线样本不移作 `0.1.1` 新构件证明。
- 暂不承诺任意 Linux 发行版/glibc、旧 macOS、macOS 签名/公证、所有宿主/客户端/模型或答案质量。
- 516 不是降智证明；新增构建平台不改变续接成本/隐私或提升质量的保证。

Windows 同构件隔离证据已补齐；下一步只读核对实际安装版本及商店显示，不从收录或模拟上游通过推定生产升级。
未来新版 Release、商店操作、生产试装及真实模型测试保持独立授权，不因候选 artifact 成功而自动执行。
