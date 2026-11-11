# 商店提交材料与状态 — CodexReflow

**五平台 Release 已发布；[PR #225](https://github.com/router-for-me/CLIProxyAPI-Plugins-Store/pull/225) 已于 2026-10-10 06:06:14（UTC+8）合并，10 月 11 日读回官方注册表已收录。**
公开仓库为 `LaoPiLao/cpa-plugin-codexreflow`；建仓、构建/验收、main 合并、公开 Release
与文档推送分别经授权完成。`v0.1.1` 已于 2026-10-09 发布并读回为 latest stable，
五个 ZIP 及统一校验文件均经匿名下载核验。
首次商店 [PR #222](https://github.com/router-for-me/CLIProxyAPI-Plugins-Store/pull/222) 经独立授权提交，
10 月 9 日关闭、未合并：[审核反馈](https://github.com/router-for-me/CLIProxyAPI-Plugins-Store/pull/222#issuecomment-6069997676)要求补齐五平台。
随后独立获授权，10 月 9 日 19:44:58（UTC+8）创建 PR #225，只新增一条注册信息，保留原有 111 条及 schema。
本次官方注册表读回唯一的 `codexreflow` 条目，与提交模板一致；这里只同步收录状态，**不另发 PR、评论或重新打开旧 PR**。
收录依据是已合并 PR 和官方条目，不是此前的 `CLEAN`；不等于生产升级或客户端 UI 验收。见 [收录核对记录](../docs/STORE-LISTING-2026-10-11.md)、历史[商店重提记录](../docs/STORE-SUBMISSION-2026-10-09-0.1.1.md)、[本次发布证据](../docs/RELEASE-2026-10-09-0.1.1.md)
及 [五平台说明](../docs/MULTIPLATFORM.md)；[旧版发布记录](../docs/RELEASE-2026-10-08-0.1.0.md)仅作历史参考。

## 注册表条目

使用 [registry.entry.template.json](registry.entry.template.json) 作为单条来源模板。
`author`、`repository`、`homepage` 已填写真实归属；PR #225 已将对象追加到
`registry.json` 的现有 `plugins` 数组；**不是覆盖整个注册表，也不要再次追加重复条目**。
重提前已检查 `codexreflow` ID 唯一性；任何未来提交仍需重查，不代表预留名称。
不必填 legacy `version` 字段，也不添加尚未存在的 logo 链接。

## 已提交 PR 标题

`Add CodexReflow plugin (v0.1.1 five-platform packages)`

## v0.1.1 重提材料摘要（已提交）

> 实际正文以 [PR #225](https://github.com/router-for-me/CLIProxyAPI-Plugins-Store/pull/225) 为准，以下留作提交材料摘要，不用于创建重复 PR。本项目已读回合并和收录，但收录不是生产安装或全平台集成验收。

- Repository: [LaoPiLao/cpa-plugin-codexreflow](https://github.com/LaoPiLao/cpa-plugin-codexreflow)
- Latest release: [v0.1.1](https://github.com/LaoPiLao/cpa-plugin-codexreflow/releases/tag/v0.1.1)
- Source/tag: [6c71eee479e9939a3d300b9231117fae11eef296](https://github.com/LaoPiLao/cpa-plugin-codexreflow/commit/6c71eee479e9939a3d300b9231117fae11eef296)
- Windows amd64: [codexreflow_0.1.1_windows_amd64.zip](https://github.com/LaoPiLao/cpa-plugin-codexreflow/releases/download/v0.1.1/codexreflow_0.1.1_windows_amd64.zip)
- Linux amd64: [codexreflow_0.1.1_linux_amd64.zip](https://github.com/LaoPiLao/cpa-plugin-codexreflow/releases/download/v0.1.1/codexreflow_0.1.1_linux_amd64.zip)
- Linux arm64: [codexreflow_0.1.1_linux_arm64.zip](https://github.com/LaoPiLao/cpa-plugin-codexreflow/releases/download/v0.1.1/codexreflow_0.1.1_linux_arm64.zip)
- macOS amd64: [codexreflow_0.1.1_darwin_amd64.zip](https://github.com/LaoPiLao/cpa-plugin-codexreflow/releases/download/v0.1.1/codexreflow_0.1.1_darwin_amd64.zip)
- macOS arm64: [codexreflow_0.1.1_darwin_arm64.zip](https://github.com/LaoPiLao/cpa-plugin-codexreflow/releases/download/v0.1.1/codexreflow_0.1.1_darwin_arm64.zip)
- Checksums: [checksums.txt](https://github.com/LaoPiLao/cpa-plugin-codexreflow/releases/download/v0.1.1/checksums.txt); all six public assets anonymously downloaded and verified byte-for-byte, including SHA256, size, ZIP CRC, architecture and retained licenses, on October 9, 2026.
- Native package CI: [main run #37916034316](https://github.com/LaoPiLao/cpa-plugin-codexreflow/actions/runs/37916034316), five native jobs plus aggregate job all passed; these exact tested bytes were published.

完整资产大小、SHA256、来源及验收范围见 [独立发布记录](../docs/RELEASE-2026-10-09-0.1.1.md)。
公开下载的 Windows DLL 本地另读回注册并重跑 31 项原生离线案例通过；不是生产试装。

CodexReflow is an independent MIT-licensed fork of CodexComp v0.1.7. It adds
HTTP/SSE and raw WebSocket event decoding/folding, bounded native WS incremental
continuation with known complete context, automatic GPT text-name matching and
payload-free per-round diagnostics. It is not an official OpenAI or CLIProxyAPI
plugin; continuation is heuristic and may increase token usage and latency without
improving answer quality. This release provides Windows amd64, Linux amd64/arm64
and macOS amd64/arm64 packages, addressing the missing-platform feedback in the
closed PR #222. CPA SDK remains pinned to v8.0.13; Go implementation and policy
are unchanged from v0.1.0.

Each native target passed Go unit/race/vet/fuzz, all 47 Python regressions and
the same 31-case C ABI mock-host suite on both original and packaged library bytes.
That is 155 case executions per group, not 310 distinct scenarios. This is
offline native validation, not full CPA/HTTP/WebSocket, real-model or Desktop
acceptance on every platform. No production installation or live-model tests
were performed for these new binaries. Historical dev.5 and v0.1.0 integration
evidence is separate. Arbitrary older glibc/musl, older macOS and distribution
signing/notarization are not validated.

The submitted PR changes only the registry entry. Binaries, checksums and release notes
remain in the author's repository. Upstream licenses and attribution are retained.

## 已完成检查与审核待办

提交后的独立证据：10 月 11 日，同一 `v0.1.1` Windows 正式 DLL 完成三个固定 CPA 宿主共 150 次
合成隔离 HTTP/WS 用例执行及 31 项原生 ABI；10 月 12 日读回哈希。
见 [正式 Windows 包隔离验收](../docs/VALIDATION-2026-10-12-0.1.1.md)。这是后续独立记录，
不修改已提交 PR 正文、Release 资产/说明或历史报告；不扩大为五平台实际集成或真实模型认证。

- [x] 首次 PR #222 经授权提交，但因缺少平台资产被关闭。
- [x] 新版五平台 Release 独立获授权，已发布并验收；不是从工作分支/CI 授权推定。
- [x] 商店重提独立获授权，PR #225 已创建并读回；没有把发布或文档推送授权当作重提授权。
- [x] 五平台实际资产及统一 `checksums.txt` 已发布并匿名下载复核；链接不是占位符。
- [x] 正式仓库、Release、ZIP、checksums 四项链接可公开访问；不是占位符或 `local://` 来源。
- [x] 远程标签、五平台库注册版本、ZIP 名称、校验文件和仓库来源完全匹配；不以继承的本地同名标签推定来源。
- [x] 匿名下载后复核 SHA256；每个 ZIP 根部只有对应平台的一份动态库及三个许可文件，无绝对/越界路径。
- [x] 新正式构件完成五平台原生 ABI 与包内字节回归；公开 Windows 字节再验收，不挪用开发 DLL 或旧 v0.1.0 的隔离报告。
- [x] 重提时 ID 唯一，原有 111 条及 schema 保留；PR 只有 `registry.json` 的 10 行新增，不含原始日志、账号、构件或无关文件。
- [x] 草稿明确五平台实际 CPA/HTTP/WS 与真实模型未全面验收，声明不超出证据；商店是否收录由维护者审核。
- [x] 维护者已合并 PR #225，官方注册表中本项目条目唯一且与提交模板一致；不以此前开放或无冲突状态代替实际合并结果。

核对依据（10 月 8 日首发、10 月 9 日重提再次复核）：[官方商店说明](https://github.com/router-for-me/CLIProxyAPI-Plugins-Store#adding-a-plugin)、
[官方注册表](https://github.com/router-for-me/CLIProxyAPI-Plugins-Store/blob/main/registry.json)。任何未来提交仍需当日重查。

推荐下一步：只读核对实际安装版本和商店显示；不因已收录或隔离通过自动修改生产配置。
