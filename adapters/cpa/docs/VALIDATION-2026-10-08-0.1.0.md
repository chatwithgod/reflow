# 0.1.0 Windows 发布包本地验收 — 2026-10-08

**阶段说明：** 本文记录发布前的本地验收及当时授权范围。之后另获授权推送文档、发布 `v0.1.0`，
并完成公开资产匿名下载/字节复核，见 [独立发布记录](RELEASE-2026-10-08-0.1.0.md)。
下文“没有上传/推送”等表述只指本地验收阶段；生产安装、真实模型调用和商店 PR 仍未执行。

## 结论与授权范围

已从源码提交 `875864934cf82dbba90a7f85985f36ebd3a256d1` 重新构建 Windows amd64 的正式版本构件，
注册版本为 `0.1.0`，来源为 [LaoPiLao/cpa-plugin-codexreflow](https://github.com/LaoPiLao/cpa-plugin-codexreflow)。
同一新 DLL 通过离线检查及三个固定 CPA 版本的隔离 HTTP/WS 回归，随后打包并验证 ZIP 内的实际 DLL。
**这是本地发布包验收，不是已经公开发布或生产安装。**

本轮没有修改 Go 实现、SDK、续接策略或生产配置，没有替换已安装插件、重启生产服务、调用真实模型、
消费生产 usage 队列、提交/推送代码或标签、上传 Release、提交商店 PR。此前 dev.5 构件、非版本化旧
构建和不可变候选 ZIP 的 SHA256 均保持不变。

## 构件与来源

| 项目 | 内容 |
|---|---|
| 插件 ID / 注册版本 | `codexreflow` / `0.1.0` |
| 注册作者 | `CodexReflow contributors`，保留上游及第三方许可证 |
| 注册仓库 | `https://github.com/LaoPiLao/cpa-plugin-codexreflow` |
| 源码提交 | `875864934cf82dbba90a7f85985f36ebd3a256d1` |
| SDK | CLIProxyAPI `v8.0.13`，未升级 |
| 工具链 / 平台 | Go `1.26.8`、既有项目内 LLVM-MinGW；Windows amd64 |
| 构建输出 | `build/release-0.1.0-20261008/codexreflow.dll`，没有覆盖旧构建路径 |
| 版本化 ZIP | `dist/0.1.0/codexreflow_0.1.0_windows_amd64.zip` |
| 校验文件 | 同目录 `checksums.txt`，sha256sum 格式 |

DLL SHA256：

```text
6f2bb2cec1adb8db02925170fb3c35b0176ea474687f7620bf993816ad8402a0
```

ZIP SHA256：

```text
63e0c62b414bea0dd98f1225f7507b78dcf8d0e7505e88147542a013ae8bd52d
```

正式 DLL 不是 dev.5 改名：版本和来源由链接参数生成，新哈希对应本轮全部 DLL 测试报告。
没有把开发版历史报告或先前真实用量样本改成正式构件的证明。

## 已完成检查

| 检查 | 结果 |
|---|---|
| Go 格式、unit、race、vet | 通过 |
| 解码器 fuzz | 15 秒、2 worker、27237 次执行，通过 |
| 新 DLL 原生 C ABI | 31 项通过，包括正常/续接/工具及取消、失败、残缺等负面断言 |
| Python 回归 | 19 项通过，含正式打包保护、诊断和本地候选包测试 |
| DLL 注册信息与 PE 平台 | ID、数字版本、真实来源、Windows amd64 DLL 均核对通过 |
| ZIP / 校验文件 | SHA256 与 ZIP 完整性通过；仅四个预期根目录成员 |
| ZIP 内 DLL 字节与原生 C ABI | 与被测 DLL 逐字节相同；另重跑同一组 31 项，全部通过 |
| 旧构件、候选 ZIP、测试期间源码 | 哈希不变；没有覆盖历史验收报告 |

本地 ignored `build` 含其他项目的 Go 源码；本轮仍在**全部 17 个根目录 Go 文件加 go.mod/go.sum 的
逐字节快照**运行 `go test ./...`、race、vet、fuzz 及 DLL 构建，并核对原文件不变。
这不是包含其他项目的整个工作目录认证。

### 相同正式 DLL 的隔离 CPA 回归

| CPA 宿主 | 原生 WS 增量续接 | 父 ID / 重连 / 重载桥接 | HTTP/WS 自动选择 | 合计 |
|---|---:|---:|---:|---:|
| 8.0.13 | 14 | 13 | 23 | 50 |
| 8.0.15 | 14 | 13 | 23 | 50 |
| 8.0.16 | 14 | 13 | 23 | 50 |

共 **150 次案例执行**，全部满足断言；同一批用例跨宿主重跑，不是 150 种独立真实模型场景。
三种宿主可执行文件在运行前后按 SHA256 固定，响应头版本与明确选择一致；没有切换 SDK。
实例使用独立 loopback 端口、全新临时配置/空账号目录、合成凭据和上游响应，结束后清理；不读取生产配置。

- HTTP/SSE、实际双端 WS 握手、无 HTTP 回退、默认预算、无加密状态不续接通过。
- 516/1034、重复截断、零新增推理、工具返回、继承设置、稳定父 ID、并发连接与完整重放通过。
- failed/incomplete 场景按负面预期处理，不伪造成成功；宿主可能在插件响应钩子前关闭失败 socket。
- 新诊断、逐轮用量和客户端终止 metadata 按同一 `run_id` 核对；不声称已具备 ECPA 精确执行 ID 连接。

### 远程 CI 的独立边界

源提交的 [首次 CI](https://github.com/LaoPiLao/cpa-plugin-codexreflow/actions/runs/37763466572)
Windows、Linux job 均成功。该 workflow 构建的是开发版本；**不是上方正式 DLL 哈希的远程验证**。
本轮正式 DLL 的证据来自本地原生 ABI 和隔离 CPA 测试，不把源码 CI 结果挪作同构件证明。
未生成 Linux/macOS 正式资产，也未验证这些平台的完整 CPA/真实模型集成。

## ZIP 内容及隐私

根目录仅包含：

```text
codexreflow.dll
LICENSE
THIRD_PARTY_NOTICES.md
THIRD_PARTY_LICENSES.txt
```

没有嵌套或第二份动态库、绝对/越界路径、账号、密钥、配置、原始日志、提示词、回答或测试报告。
构件/报告对应关系及源文件哈希收据保存于 ignored `build/release-0.1.0-20261008/`，不随 ZIP 上传。
再次打包同版本会被正式打包器拒绝；不要覆盖现有 ZIP 或校验文件。

## 尚未验证 / 未执行

- 这个正式 DLL **没有安装到生产或调用真实模型**。dev.5 的 [有限真实使用](VALIDATION-2026-10-08-live-dev5.md)
  只能作为历史行为证据，不能改写成正式构件在线通过。
- 真实 HTTP/SSE、复杂历史、取消/超时/断连/重连的全面边界及答案质量仍未全面验收。
- 自动模型匹配仍是名称启发式，不是同步 CPA 模型目录；`usage_join: unavailable` 仍未改变。
- 516 不是降智证明，续接不保证增加推理或提高质量；更多轮数增加消耗及延迟。
- 没有创建 `v0.1.0` 标签、上传 Release 或提交商店 PR；本地 ZIP 不能代替公开资产存在证据。

## 复现要点

重复验证应使用新的输出路径，保留已封存构件。使用上述源提交的干净检出或相同逐字节源码快照，
加载项目的 `scripts/dev_env.ps1` 后，构建参数为：

```powershell
go build -trimpath -buildmode=c-shared -ldflags '-X main.pluginVersion=0.1.0 -X main.pluginRepository=https://github.com/LaoPiLao/cpa-plugin-codexreflow' -o <新的DLL路径> .
python scripts/native_smoke.py <新的DLL路径> --report <新的原生报告>
python scripts/ws_incremental_fold_smoke.py --cpa <固定宿主> --cpa-version <明确版本> --dll <新的DLL路径> --report <新的增量报告>
python scripts/ws_incremental_smoke.py --cpa <固定宿主> --cpa-version <明确版本> --dll <新的DLL路径> --native-folds --report <新的桥接报告>
python scripts/isolated_cpa_smoke.py <固定宿主> <新的DLL路径> --cpa-version <明确版本> --auto-models --report <新的自动选择报告>
```

推荐下一步：结合 [公开发布记录](RELEASE-2026-10-08-0.1.0.md) 审阅 [商店草稿](../store/SUBMISSION-DRAFT.md)，
再单独授权注册表 PR；生产安装和新增模型调用保持独立授权。
