# 商店收录核对记录 — 2026-10-11

## 结论

[商店 PR #225](https://github.com/router-for-me/CLIProxyAPI-Plugins-Store/pull/225)
已于 **2026-10-10 06:06:14（UTC+8）**合并。
10 月 11 日 16:56（UTC+8）的独立只读核对确认：合并提交在官方 `main` 上，
官方注册表含唯一的 `codexreflow` 条目，全部字段与本项目提交模板一致。
这是官方注册表收录证明，不是本机插件升级、客户端商店 UI、全面 CPA/真实模型或答案质量验收。

## 已读回证据

| 项目 | 结果 |
|---|---|
| PR 状态 | `closed`、`merged: true`；关闭是合并后的状态，不是再次拒绝 |
| 合并时间（UTC） | `2026-10-09T22:06:14Z` |
| PR 提交 | `b296293cd6c6804b278c65fdf9e93aa8f400cc25` |
| 合并提交 | [`a789e63450c11593eeef4d559ce8d4444977f32d`](https://github.com/router-for-me/CLIProxyAPI-Plugins-Store/commit/a789e63450c11593eeef4d559ce8d4444977f32d) |
| 当次官方 main | `bf611ec30b175f9b8a00e96eecbae63418716ff3`；包含上面的合并提交 |
| 注册表 blob | `390ca7be4486efdb2fddceac89c2204b736b477d` |
| 注册表 SHA256 | `2cde7423a07b022f381091d6e0fd41a6ab89c1e9451ece37c7393d09a6568565` |
| 当次条目计数 | 全表 114 条；`codexreflow` 恰好 1 条，与提交模板完全一致 |
| PR 修改范围 | 仅 `registry.json`，10 行新增、0 行删除；原有 111 条及 schema 保留 |

注册表以[本次固定 main 快照](https://github.com/router-for-me/CLIProxyAPI-Plugins-Store/blob/bf611ec30b175f9b8a00e96eecbae63418716ff3/registry.json)核对，
后续可读取[官方当前注册表](https://github.com/router-for-me/CLIProxyAPI-Plugins-Store/blob/main/registry.json)。
官方表在本项目提交后还收录了其他项目，114 不是本 PR 新增条目数，也不是覆盖全表的证据。

## 版本、历史与边界

- 作者/仓库读回为 `LaoPiLao` / [cpa-plugin-codexreflow](https://github.com/LaoPiLao/cpa-plugin-codexreflow)，许可为 MIT。
- latest stable 仍为 [v0.1.1](https://github.com/LaoPiLao/cpa-plugin-codexreflow/releases/tag/v0.1.1)，五平台资产、正文及标签与封存记录一致；本次不重新构建或替换发布资产。
- 六份公开资产的匿名下载和同字节验收来自[10 月 9 日发布记录](RELEASE-2026-10-09-0.1.1.md)及[重提记录](STORE-SUBMISSION-2026-10-09-0.1.1.md)，不是声称本次重新下载了全部资产。
- 10 月 9 日记录里的“待审核/未合并”是当时状态，保留原文作为历史快照；本记录补充之后的实际合并与收录，不回改旧 Release 正文或验收报告。
- 旧 [PR #222](https://github.com/router-for-me/CLIProxyAPI-Plugins-Store/pull/222) 保持关闭、未合并。本次没有另发/评论 PR、改官方或 fork 注册表、移动标签、上传 Release、修改运行代码/SDK/版本或生产配置。
- 收录核对及文档同步不安装/启用生产插件，不重启生产服务，不切换传输，不调用真实模型，也不消费生产 usage 队列。未核对客户端商店 UI。
- 516 不是降智证明；续接是有预算的启发式，不保证推理增加或答案改善，可能增加费用和延迟。

## 下一步

对已发布 `v0.1.1` 的 Windows DLL 字节做合成隔离 CPA HTTP/WebSocket 回归，使用空账号目录和模拟上游。
其结果另行记录，不改写历史证据；生产试装和真实模型测试仍需单独授权。
