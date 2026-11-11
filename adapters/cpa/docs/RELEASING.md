# 发布清单

## 当前正式版 v0.1.2 — 2026-10-24

[`v0.1.2`](https://github.com/chatwithgod/cpa-plugin-codexreflow/releases/tag/v0.1.2) 已正式发布并读回为 latest stable。源码标签固定到 `2769784c70ce3786c48cff3b342f95e29f254975`；五平台原生 CI、47 项 Python、每平台原库/包内库各 34 项 ABI 均通过。Windows 正式字节另通过 CPA 8.0.13 的 50 项 HTTP/WS 回归与 CPA 8.0.38 的 2 项预热检查。

五个 ZIP 和统一 checksums 已经匿名下载核对，与被测 CI 构件相同。完整证据和 SHA256 见 [本版发布记录](RELEASE-2026-10-24-0.1.2.md)。正式构件的声明仓库为 `https://github.com/chatwithgod/cpa-plugin-codexreflow`；CPA SDK 仍固定 `8.0.13`。旧 Release、标签和本地开发构件保留。

## v0.1.1 发布与商店状态（历史）— 2026-10-09

[`v0.1.1` 五平台 Release](https://github.com/LaoPiLao/cpa-plugin-codexreflow/releases/tag/v0.1.1)
已于 2026-10-09 18:43:21（UTC+8）公开并读回为 latest stable，五个 ZIP / 统一 checksums
通过匿名下载及字节验收；公开 Windows DLL 另通过 31 项原生离线案例。未安装到生产。
旧 `v0.1.0` 的正文、标签及资产保持不变；最近一次已记录的授权部署是 `0.1.0-dev.5`，本轮不替换生产安装。
**构建、合并、发布、商店重提与文档推送分别获授权；旧 PR #222 已关闭，新 [PR #225](https://github.com/router-for-me/CLIProxyAPI-Plugins-Store/pull/225) 已于 2026-10-10 06:06:14（UTC+8）合并，10 月 11 日读回官方注册表已收录。**
五个平台资产已补齐，但原生 ABI 通过不等于全面 CPA/HTTP/WS、真实模型或 Desktop 验收。
仓库：[LaoPiLao/cpa-plugin-codexreflow](https://github.com/LaoPiLao/cpa-plugin-codexreflow)。

| 项目 | 已有证据 / 尚待完成 |
|---|---|
| SDK / 来源与许可 | SDK 固定 `8.0.13`；注册来源和 ZIP 内上游版权/第三方许可已逐字节复核 |
| v0.1.1 正式构件 | 五平台原生 unit/race/vet/fuzz、47 项 Python 回归、原库及包内库各 31 项 C ABI 合成宿主案例；两组各 155 次案例执行，不是 310 种场景 |
| v0.1.1 远程 CI | 源提交 `6c71eee` 的 main 五平台运行 `37916034316` 全部成功；发布六份资产取自这次被测 CI，不使用旧分支候选 |
| v0.1.1 公开下载 | 全六份匿名下载与被测字节一致，大小/SHA256/CRC/架构/许可复核通过；公开 Windows DLL 本地另通过 31 项原生案例 |
| v0.1.1 全面集成 | 五平台实际 CPA/HTTP/WS、真实模型/客户端未全面验收，未评价答案质量；旧构件报告不移作新包证明 |
| 历史 dev.5 离线/隔离 | 31 项原生 ABI、19 项 Python；CPA `8.0.13` / `8.0.15` / `8.0.16` 各 50 次隔离案例执行，共 150 次，不是独立场景数 |
| 历史 dev.5 有限真实使用 | 截至 10 月 8 日 01:42:48（UTC+8），22 条已完成 WS 上游行、16 次客户端用量核对、6 次续接；两个聊天均有工具往返和完整回答，不代表新包在线验收 |
| 仓库与发布授权 | `LaoPiLao` 公开仓库已创建；代码推送、正式包验收和 Release 分别获授权；`upstream` 及本地继承标签保留 |
| 历史 v0.1.0 构件 | Windows DLL 通过 unit/race/vet/fuzz、31 项原生 ABI、19 项 Python、三宿主 150 次隔离案例；其开发 CI 不是正式 DLL 哈希证明 |
| v0.1.1 Windows 固定宿主隔离 | 同一公开 ZIP 内 DLL 通过 31 项原生 ABI，以及 CPA 8.0.13/8.0.15/8.0.16 各 50 次合成 HTTP/WS 用例执行；10 月 11 日完成、12 日读回；不代表真实模型/生产或其他平台 CPA 集成 |
| Release / 商店 | `v0.1.1` 已公开并验收下载，`v0.1.0` 封存保留；PR #225 经独立授权重提，仅新增一个条目，原 111 条及 schema 不变；已合并，官方注册表中本项目条目唯一且与模板一致；不是生产安装或客户端 UI 验收 |

当前证据：[v0.1.1 Windows 隔离验收](VALIDATION-2026-10-12-0.1.1.md)、[商店收录核对](STORE-LISTING-2026-10-11.md)、[v0.1.1 发布与下载核验](RELEASE-2026-10-09-0.1.1.md)、[五平台流程](MULTIPLATFORM.md)。[重提记录](STORE-SUBMISSION-2026-10-09-0.1.1.md)保留 10 月 9 日提交时状态。
历史证据：[v0.1.0 发布](RELEASE-2026-10-08-0.1.0.md)、[0.1.0 本地验收](VALIDATION-2026-10-08-0.1.0.md)、[dev.5 隔离](VALIDATION-2026-10-07-dev5.md)、[有限真实核对](VALIDATION-2026-10-08-live-dev5.md)。
提交材料：[商店提交材料与状态](../store/SUBMISSION-DRAFT.md)；[0.1.0 首发草稿](RELEASE-NOTES-0.1.0-DRAFT.md)仅供历史参考。

## 本地候选与正式版分开

本地候选使用独立的 `scripts/package_candidate.py --version <编号开发版本> --library <DLL> --report <原生报告> --report <隔离报告>`。
它核对真实 DLL 注册信息、同构件测试报告和 Windows amd64 格式，保留 `local://codexreflow`，拒绝覆盖已有版本输出。
ZIP 包含许可证、脱敏证据计数/哈希、逐文件清单和只读诊断汇总工具；不会安装、发布或放宽正式版来源检查。
见 [本地候选说明](LOCAL-CANDIDATE.md)。

已经生成的 dev.5 ZIP 及其 manifest 是打包当时的不可变快照，其中 `live_model_acceptance: pending`
不能事后改写成通过；后续有限真实使用证据保存在独立核对文档。不覆盖旧 ZIP，也不把它改名为正式包。

## 已核对的商店规则

2026-10-08 首发核对、10 月 9 日重提时再次复核 [官方商店说明](https://github.com/router-for-me/CLIProxyAPI-Plugins-Store#release-requirements)：

- 注册表保留插件信息；二进制、校验和 Release 说明放在作者自己的仓库。条目须有 ID、名称、简介、作者和真实仓库；提交当天重查 ID 唯一性。
- 商店读取仓库 latest Release；标签为 `v` 加点分数字版本。开发版 `0.1.0-dev.5` 不符合该正式版本要求。
- 每个支持平台提供 `<id>_<version>_<goos>_<goarch>.zip`，附 `checksums.txt`（SHA256，sha256sum 格式）。
- 动态库必须在 ZIP 根部；Windows 为 `codexreflow.dll`，不能有多份动态库、绝对或越界路径。
- 只提交注册表变更，并提供真实仓库、Release 标签及 ZIP/校验文件存在证据。草稿和本地测试报告不能代替下载核验。

旧 `v0.1.0` 仅 Windows amd64。2026-10-09 的 [审核反馈](https://github.com/router-for-me/CLIProxyAPI-Plugins-Store/pull/222#issuecomment-6069997676)
及 [项目 issue #1](https://github.com/LaoPiLao/cpa-plugin-codexreflow/issues/1) 明确要求五个平台预编译包；
此前 README 的“每个支持平台”不足以确认只发布 Windows 可收录，不能再按这个假设重提。
`v0.1.1` 已发布全部五个平台资产，流程见 [五平台构建与验收](MULTIPLATFORM.md)；
编译/原生 ABI 通过仍不是全面真实 CPA 集成认证，补齐资产也不保证商店收录。
重提前已复核规则、ID 唯一性及全部公开资产；任何未来提交仍需当日重查。

## v0.1.1 已完成检查与待办

以下只对本次 `v0.1.1`，不把旧 DLL 的高一级证据移用：

- [x] 用户确认 `LaoPiLao/cpa-plugin-codexreflow` 为公开仓库，授权建仓及代码推送。
- [x] `go.mod` 使用 `github.com/LaoPiLao/cpa-plugin-codexreflow`；SDK 固定 `8.0.13`。
- [x] 五平台构建、main 合并、新版 Release 与文档推送分别获授权，发布及公开下载验收已完成。
- [x] 首次商店 PR #222 单独获授权并提交，但因缺少平台资产被关闭。
- [x] 商店重提独立获授权，PR #225 已提交并读回为仅改 `registry.json`；不从已有构建/发布授权推定。
- [x] PR #225 已合并，官方注册表中本项目条目唯一；按合并事实和注册表证明收录，不把此前 `CLEAN` 当作审核通过。生产安装及客户端 UI 未验收。
- [x] 五平台正式库 ID/版本/仓库来源已原生读回；公开 Windows DLL 另读回 `0.1.1` 与真实仓库，商店草稿不冒充 uf-hy。
- [x] ZIP 内 LICENSE、第三方声明和完整许可文本逐字节核对，上游档案保留来源标注。
- [x] 发布源 main CI 五平台 unit/race/vet/fuzz、47 项 Python、原生 ABI 与包内字节回归通过，汇总 job 成功。
- [x] 六份公开资产匿名下载逐字节核对；公开 Windows DLL 同组 31 项原生案例再验收通过。
- [x] 正式 Windows ZIP 内同一 DLL 另在三个固定 CPA 宿主完成 150 次合成 HTTP/WS 用例执行；复核 31 项原生 ABI及宿主/报告哈希，保留首次安全检查拦截与重新完整验证记录。
- [x] `docs/COMPATIBILITY.md` 区分 v0.1.1 原生 ABI、旧正式包隔离与 dev.5 有限真实证据；未验收边界明确列为限制。
- [x] README 不声称未验证的平台、全模型支持或普遍质量提升。
- [x] 发布内容不包含密钥、账号或生产请求记录；商店草稿填写已验证的真实资产链接。
- [ ] 五平台全面实际 CPA/HTTP/WS 和真实模型/客户端验收未完成，不将此处原生结果宣传为全面通过。
- [ ] 生产试装与新增真实模型测试另行取得授权；发布不自动修改生产状态。

只改正式版本/仓库 metadata 也会产生新的 DLL 哈希；不能把 dev.5 的哈希、报告或使用样本改个版本名当作正式构件证明。
先确定来源与公开范围，再生成新构件和对应报告；任何生产试装或新增付费调用仍需另行授权。

## 构建流程（不覆盖已封存版本）

`v0.1.0` 与 `v0.1.1` 均已封存发布；`VERSION` 保留 `0.1.1`，不要重建覆盖同名 Release 资产。
下述命令用于生成新的不可覆盖候选，不代表获准发布；新正式版本需单独确定编号、来源与授权。
在匹配的原生宿主和已提交源码上执行（Windows 先载入 `scripts/dev_env.ps1`）：

```powershell
python scripts/build_platform.py --goos windows --goarch amd64
```

每个平台打包到独立、不可覆盖的目录；根部为 `.dll` / `.so` / `.dylib` 与三个许可文件。
先验证原生注册及同库 ABI 报告，再从 ZIP 实际字节重跑相同测试；汇总器核对全部五个目录、
来源/源码/版本、报告及文件哈希，生成统一五行 `checksums.txt`。完整命令见 [五平台流程](MULTIPLATFORM.md)。
不要因为文件叫 `build/codexreflow.dll` 就认为它是最新构件；该非版本化路径可能保留旧构建。
正式打包前必须成功执行上面的构建，并读回注册 metadata 与 SHA256，不跳过打包器的拒绝检查。

远程 `v0.1.1` 固定到 `6c71eee479e9939a3d300b9231117fae11eef296`，
旧 `v0.1.0` 仍固定到 `875864934cf82dbba90a7f85985f36ebd3a256d1`；不是后续仅修改文档的 `main`。
本地两个同名标签均继承自 CodexComp，保留不动，**不要执行 `git push --tags`、整批标签同步或强制移动标签**。
新检出可正常取得 Reflow 的远程标签；已有继承标签的维护目录须使用明确源码 SHA，不以本地同名标签推定源码。

经独立授权，已向 [官方注册表](https://github.com/router-for-me/CLIProxyAPI-Plugins-Store)提交仅改 `registry.json` 的 PR #225，
附仓库、版本、五平台构件下载证据及功能简介；维护者随后合并，现已读回官方注册表确认收录。
本次只同步文档，不再次提交/评论 PR；后续修改或新提交保持独立授权。
发布/上传/发 PR 都不能因为写好了脚本或用户要求测试而自动执行。

目前 workflow 只有 read 权限，只产出开发/正式包候选；尚无自动发布任务。
后续文档提交会再次触发 CI，即使候选版本/文件名相同，也不覆盖已发布包，不移动固定标签。

推荐下一步：只读核对实际 CPA 的安装版本和商店显示；Windows 正式包隔离通过不代表生产已升级或新构件在线验收。
不覆盖旧 Release，不因离线 ABI 通过而扩大真实集成或质量声明，不改生产安装。
