# v0.1.1 商店重提与读回记录 — 2026-10-09

## 当前结论

经独立授权，已于 **2026-10-09 19:44:58（UTC+8）**创建
[商店 PR #225](https://github.com/router-for-me/CLIProxyAPI-Plugins-Store/pull/225)。
本次文档同步前复核为 **开放、非 draft、未合并，待维护者审核**；官方注册表仍有 111 个条目，
尚无 `codexreflow`。提交申请不是审核通过、正式收录或生产升级。

GitHub 读回 `mergeStateStatus: CLEAN`，表示当时可合并且没有冲突，**不是审核通过**。
当次 `reviewDecision` 为空、`statusCheckRollup` 为空；不据此声称商店检查通过或审核完成。
状态可能随后改变，后续以 PR 和官方注册表的实际读回为准。

## 提交范围与源码

| 项目 | 已读回证据 |
|---|---|
| 官方目标 | `router-for-me/CLIProxyAPI-Plugins-Store` 的 `main` |
| 提交分支 | `LaoPiLao/CLIProxyAPI-Plugins-Store` 的 `add-codexreflow-v0.1.1` |
| 提交基线 | `6e2874ce32f5cc7d277903b2547a8d266b3d9348` |
| 注册表提交 | [`b296293cd6c6804b278c65fdf9e93aa8f400cc25`](https://github.com/LaoPiLao/CLIProxyAPI-Plugins-Store/commit/b296293cd6c6804b278c65fdf9e93aa8f400cc25) |
| PR 文件范围 | 仅 `registry.json`，10 行新增、0 行删除 |
| 数据变化 | 只追加一个 `codexreflow` 条目，111 → 112；原有 111 条及顶层 schema 数据完全一致 |
| 已提交 Git blob | `85d147183720937e78d90488dff645a0a15e4ccd` |
| 已提交文件 SHA256 | `08c86db2fd9d7b2c3e03678cd19eeccf9669632a3bf8cd35b3fc9b1b1a953742` |

这里的文件哈希按 Git 实际提交的 LF 字节计算，不按 Windows 工作树转换后的 CRLF 字节计算。
远端文件与提交 blob 逐字节相同，JSON 值也与原注册表加一条模板完全一致；没有整表重排或替换其他插件。

没有向商店仓库上传动态库、配置、生产日志、凭证、提示词、回答或验收报告。
旧 [PR #222](https://github.com/router-for-me/CLIProxyAPI-Plugins-Store/pull/222) 保持关闭、未合并，
没有重新打开或追加评论；旧提交分支和 fork 的 `main` 保留不动。

## 重提前的资产复核

旧 PR 因只有 Windows 包被关闭；根据
[审核反馈](https://github.com/router-for-me/CLIProxyAPI-Plugins-Store/pull/222#issuecomment-6069997676)，
发布五平台包后新提 PR，而不是仅删除平台限制说明。

- 重新读取官方规则、注册表及已有 PR，确认 ID 唯一、没有重复开放 PR。
- [v0.1.1 latest stable](https://github.com/LaoPiLao/cpa-plugin-codexreflow/releases/tag/v0.1.1)
  含 Windows amd64、Linux amd64/arm64、Darwin amd64/arm64 五个 ZIP 和统一 `checksums.txt`。
- 六份资产再次以不携带 GitHub 认证头/令牌或登录 cookie 的请求公开下载，
  与封存、被测 main-CI 字节比较，大小、SHA256、全部 ZIP CRC、架构、根目录布局及许可字节一致。
- Release 标签/被测源码仍固定到 `6c71eee479e9939a3d300b9231117fae11eef296`，
  发布资产来源为[五平台原生 CI #37916034316](https://github.com/LaoPiLao/cpa-plugin-codexreflow/actions/runs/37916034316)。
  正式包完整哈希与原生验收范围见[发布记录](RELEASE-2026-10-09-0.1.1.md)。

## 未改变与未验收的边界

商店重提及随后文档同步没有修改插件运行实现、SDK pin、续接策略、版本、Release 正文/资产/标签，
没有安装/启用生产插件、改 CPA/Codex 配置、切换传输、重启服务或新增真实模型测试请求。
先前发布记录里的“尚未重提”是发布当时的状态；商店提交发生在随后，不回改已封存记录或 Release 正文。

五平台原生 ABI 证据不是全面 CPA/HTTP/WebSocket、真实模型或 Desktop 验收。
模型选择仍是名称启发式；516 不证明降智，续接不保证新增推理或答案质量，追加调用会增加费用和延迟。
公开发布、商店收录及生产试装仍是不同步骤，不能用一种状态代替另一种。

## 下一步

等待维护者审核，再根据反馈处理。合并后另读取官方注册表确认条目，
生产试装与真实模型测试仍需单独授权，不因 PR 开放或无冲突自动执行。
