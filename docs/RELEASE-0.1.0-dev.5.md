# dev.5 预发布与核验记录

2026-10-31，经用户授权，将固定提交 `3e0ea1858d1af83a5efe156be101e50b1713d008` 发布为 [v0.1.0-dev.5 预发布版](https://github.com/chatwithgod/reflow/releases/tag/v0.1.0-dev.5)。标签、本地源码与远端提交核对一致。提供五个平台的独立服务和 Codex 插件共 10 个 ZIP，另有 `release-manifest.json` 和 `SHA256SUMS.txt`，共 12 个附件。

逐个公开下载核验不带 GitHub 登录凭据，共读取 61,936,580 字节，12 个 SHA256 均与发布前冻结清单一致。包内文件、架构标记、Unix 执行权限、插件市场入口和版本均检查通过，Windows 解压后的二进制也已运行版本查询。构建没有改动运行源码或生产配置，144 个旧构件及清单文件保持原散列；本次真实模型调用为 0。

## 每个平台的证据

| 平台 | 与发布前原生 CI 二进制相同 | 通过范围 | 限制 |
| --- | --- | --- | --- |
| Windows amd64 | 是，服务与插件两包 | 客户端普通/race 各 14 项；本机解压运行版本查询 | 托管 Windows 的五个写入场景仍失败 |
| Linux amd64 | 是，服务与插件两包 | 客户端普通/race 各 14 项 | 默认 Ubuntu runner 的五个写入场景仍失败 |
| Linux arm64 | 无对应原生 CI | 交叉编译、架构与包内容核对 | 未在原生系统运行 |
| macOS amd64 | 无对应原生 CI | 交叉编译、架构与包内容核对 | 未在 Intel Mac 运行 |
| macOS arm64 | 是，服务与插件两包 | 客户端普通/race 各 14 项、五个写入场景、Pi 只读探针普通/race 各 4 项 | 模拟登录与上游，不是全面真实账号验收 |

匹配对象是明确记录的[发布前原生 CI](https://github.com/chatwithgod/reflow/actions/runs/41141793654)，不是对任意后续重建散列的保证。发布前[三平台常规 CI](https://github.com/chatwithgod/reflow/actions/runs/41141793802)普通/race 各 90 通过、4 跳过，vet、fuzz 与评测自检通过。

创建标签又自动触发了已有工作流。[标签常规 CI](https://github.com/chatwithgod/reflow/actions/runs/41144772748)三平台通过，普通/race 仍各 90 通过、4 跳过；[标签原生 CI](https://github.com/chatwithgod/reflow/actions/runs/41144772772)三平台客户端检查通过，macOS 后续检查通过，Ubuntu/Windows 写入失败名称与固定错误标记和前一轮相同。原生 CI 整体结论仍为失败。两轮的三个原生任务分别串行执行，没有手动追加或重跑工作流。

## 使用这些证据时的边界

- 包含父测试与子测试的通过项计数不是用户数、采用量或独立功能数量。上述 12 次附件下载是发布核验，不作为外部使用证据。
- 较早的原生 ChatGPT 登录功能样本保留自己的二进制来源及配置审计例外，见[原生验收总表](NATIVE-LOGIN-ACCEPTANCE.md)。发布没有增加真实样本，也不证明本次所有构件都经过真实账号验收。
- Magpie 外置接入的七场景普通/race 证据来自本机 Windows、固定上游与本地模拟 HTTP 后端；该完整链路不在自动 CI 内。见[外置接入](../adapters/magpie/EXTERNAL.md)。
- Desktop/dot、账号刷新、其余平台的原生运行及质量收益仍未验证。Pi 按用户选择的模拟范围验收，发布不会重新引入真实 Pi 登录要求。
- 这是手动解压的预发布包，尚无插件商店提交、Windows 代码签名或 macOS 开发者签名/公证。

准备过程中曾遇到核验脚本的 UTF-8 解码问题、首次草稿列表读取未及时出现新草稿，以及 GitHub 匿名 API 配额限制。脚本修正后完成包检查；确认并沿用同一草稿；停止匿名 API 请求后，直接核验公开页面与附件。没有为处理这些问题重建发布、改动构件或追加模型调用。机器可读来源、散列、CI 结果与限制见[发布证据](evidence/release-dev5-2026-10-31.json)。

## 发布后的独立检查点：2026-11-04

以上保留发布当日结果。后续文档提交 `6d6cfbf` 的默认 Ubuntu 原生 CI 首次全部通过，原因未确定；macOS 继续通过，托管 Windows 仍有旧写入失败，见[最新 CI](NATIVE-CI.md)。已发布的 Windows 独立二进制另完成[原生登录开关对照](LIVE-SCHEDULER-PAIR-2026-11-04.md)，两组均正常结束、18/18、零工具失败、保护文件未变，但没有续接。本次没有替换发布附件，也不把新检查倒填成发布当日的验收结果。
