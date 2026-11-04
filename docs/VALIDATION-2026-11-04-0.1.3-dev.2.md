# Issue #2 修复与本地候选验证

日期：2026-11-04。候选：`0.1.3-dev.2`，Windows amd64。

**结论：本次已定位并修复 CPA 插件路径改坏 collaboration 工具参数类型的问题。修复前后对照和隔离回归通过；尚未证明真实模型端验收，也没有发布或安装生产。**

## 为什么会出错

[Issue #2](https://github.com/chatwithgod/cpa-plugin-codexreflow/issues/2) 报告 CPA `8.0.47` + CodexReflow `0.1.2` 在带多智能体工具时，第一轮就失败，并非 516 续接之后才失败。

CPA 会把 Codex 工具 schema 中的 `number` 规整为 `integer`。原生 Codex 执行器已有豁免，但插件执行器不在这个豁免范围内。因此插件收到的 `Payload` 已被修改，而 `OriginalRequest` 仍保留客户端定义。

依据是 CPA 固定版本源码和真实隔离进程观察，不靠提示词推测：

- [CPA 8.0.47 的 payload finalizer 与原生执行器豁免](https://github.com/router-for-me/CLIProxyAPI/blob/v8.0.47/internal/runtime/executor/helps/payload_helpers.go)。
- [插件适配器：先处理 Payload，另行保留 OriginalRequest](https://github.com/router-for-me/CLIProxyAPI/blob/v8.0.47/internal/pluginhost/adapters_executors.go)。
- [工具类型规整，包括 additional_tools](https://github.com/router-for-me/CLIProxyAPI/blob/v8.0.47/internal/client/codex/tool-schema/tool_schema.go)。
- [上游原生执行器豁免修复](https://github.com/router-for-me/CLIProxyAPI/commit/a8ffd5a8432849cdefe333ffa132b8ada770c671)。

没有采用 issue 中“删掉 collaboration 工具”的建议：首轮同样需要这些工具，删掉可能直接破坏多智能体功能。

## 补丁做了什么

- 在 `executeStream` 创建折叠状态前恢复参数类型，首轮与后续轮次使用同一份修正后的声明。
- 原生 WS 增量续接在准备完整重放前同样恢复当前声明；根请求缓存保存已经修正的设置。
- 仅处理显式 `collaboration` namespace 下、名称能对应的 function 参数 schema。只还原匹配已知规整结果的 `type`：`number → integer`，以及对应的类型数组去重结果。
- 原始类型是 `integer` 就继续保持 `integer`。工具列表、模型映射、提示词、缓存键、描述、约束和其他命名空间不整体替换。不会把宿主已删除的工具补回来。
- 顶层工具和每个 `additional_tools` 声明块分别对应，防止同名工具在不同作用域中原本使用不同类型时相互污染。
- 不新增用户配置，不记录原始 schema、请求正文、回答、工具结果或凭证。SDK 继续固定 `v8.0.13`，不修改续接条件、预算或传输路由。

### 明确的边界

缺少/损坏的原始定义、无法对应的工具、重复身份和超过 schema 遍历限制的请求，不会猜测或强改类型。这可能意味着请求继续收到原来的错误，而不是伪造一次“修复成功”。遍历上限为深度 64、16,384 个 schema 节点；超限时整份修正计划不应用。

`additional_tools` 有 ID 时要求两边 ID 唯一；没有 ID 时按声明块顺序对应，要求块数相同。这覆盖了所测 CPA 保持声明块相对顺序、但可能删除前置 system 消息的行为，不承诺处理任意第三方对匿名声明块的重新排序。

不修复其他 namespace、任意扁平工具名、工具重命名、非类型字段改写或上游另行变更的保留 schema。此补丁也不表示所有 502、网络断开或 516 记录都由这个问题造成。

## 修复前后对照

同一官方 CPA `8.0.47`，只更换测试用 DLL。服务端使用严格合成 schema 校验；类型错误或工具被删会拒绝请求。

| 场景 | 已发布 v0.1.2 | 候选 v0.1.3-dev.2 |
| --- | --- | --- |
| Codex UA + 顶层 collaboration，HTTP | 被改成 integer，模拟上游拒绝 | 保留 number，完整结束 |
| Codex UA + additional_tools，HTTP | 被改成 integer，模拟上游拒绝 | 保留各声明的原始类型，完整结束 |
| 上述两种请求，WebSocket | 模拟上游拒绝，客户端连接结束 | 完整结束，未回退 HTTP |
| 插件停用，HTTP / WS 对照 | 原生路径成功 | 原生路径成功 |

旧版报告共 6 项：4 项**预期失败**和 2 项停用对照，不能把它写成旧版“兼容测试全通过”。模拟的 HTTP 400 / WS error 是测试判定器，并非真实 OpenAI 错误的现场重放。

候选专项 18 项还覆盖：516 续接、顶层与动态同名工具共存、原本就是整数的参数、nullable 类型、非 Codex UA、无工具请求、原生 WS 缓存设置继承，以及真实 WS 握手下的模拟 collaboration 调用/结果回传/父响应 ID 衔接。所有 WS 场景明确检查未回退 HTTP。

## 同一候选构件的验证结果

| 验证 | 结果 | 范围 |
| --- | --- | --- |
| Go unit / race / vet | 通过 | 候选 Go 源码快照 |
| 新 schema fuzz | 通过 | 30 秒，846,166 次执行；不是全面形式化证明 |
| Python 单元测试 | 48 项通过 | 打包、证据约束、诊断等 |
| 原生 C ABI | 原库与 ZIP 解出库各 46 项通过 | 原有 34 项 + 12 项 schema 用例，含缺失 OriginalRequest；两次执行不是 92 种用例 |
| CPA 8.0.47 专项 | 18 项通过 | HTTP/WS、续接、动态工具与工具往返 |
| CPA 8.0.47 预热 | 2 项通过 | 空/非空输入、同一 WS 上的后继请求 |
| CPA 8.0.13 原有回归 | 50 项通过 | 23 项 HTTP/WS + 13 项父 ID 桥接 + 14 项原生增量 |

使用真实 CPA 二进制和真实 DLL，只有上游与客户端请求是合成的。本次没有打开生产配置、使用账号凭证、重启用户服务或调用真实模型。没有为了每次 CPA 更新重复验证全部历史版本；这次只测了问题报告宿主和既有 SDK 基线。

## 构件与可复核信息

- 开发分支：`fix/collaboration-schema`，基线提交 `9b261194c416f8affab23c9bf02448cc022f2cf2`。
- DLL：`build/0.1.3-dev.2/codexreflow-v0.1.3-dev.2.dll`。
- DLL SHA256：`f0c9f4ba44cbe420ff58e45b566bd5c20093c6ac6cc21194f91a97fb5f669201`。
- Go 源文件与 go.mod/go.sum 指纹：`eac1d09b5bfa93aa92a6547c967eff5aef1f61a238d6b4c1c8d97edee9221fd9`；工作区和用于编译的源码快照相同。
- 旧版对照 DLL SHA256：`db956e8e05241692ce123f138358c209347e3c4ab41f801f7a681ba73414079d`，未覆盖。
- CPA 8.0.47 官方 Windows exe SHA256：`90cf448b09da5b8ce03990669e8915638b12ed30abefa4f8546e42c4e7e18e7b`。
- 候选注册版本为 `0.1.3-dev.2`、来源为 `local://codexreflow`；正式 `VERSION` 和公开下载链接保留 `0.1.2`。
- ZIP：`dist/0.1.3-dev.2-local-candidate/codexreflow_0.1.3-dev.2_windows_amd64_LOCAL-CANDIDATE.zip`，SHA256 `2a27fc940e1b516cb4ee8914816192a5e165d67f2974b0db29c20938ff2d4bce`。8 个白名单文件逐项校验，包内 DLL 与测试构件逐字节相同；未包含源码请求、原始测试日志或本机配置。
- 报告校验值和打包核对结果见 [脱敏证据索引](validation/2026-11-04-0.1.3-dev.2.json)。该索引不包含日志、请求内容或本机账号路径。

## 重跑专项

在仓库根目录，使用独立保存的 CPA 8.0.47 和候选 DLL。脚本只创建自有临时目录、回环监听与独立进程，退出后关闭和清理它们；不要把生产配置传进去。

```powershell
python scripts/tool_schema_smoke.py --cpa <独立CPA的exe路径> --dll <候选DLL路径> --cpa-version 8.0.47 --report <新的报告路径>
```

用冻结的 `v0.1.2` DLL 加 `--expect-defect` 运行反向对照。报告路径必须是新文件，不覆盖既有报告。其他回归入口为 `native_smoke.py`、`ws_prewarm_smoke.py`、`isolated_cpa_smoke.py`、`ws_incremental_smoke.py` 和 `ws_incremental_fold_smoke.py`；不要使用 Python `-O` 禁用断言。

## 交付边界

产物是 **Windows 本地候选包，不是插件商店正式版**。未推送源码、创建 PR、打 tag、发布 Release、更新商店或回复 issue，也未安装到生产。真实 Codex CLI / Desktop、多智能体模型端验收，以及 Linux/macOS 构建仍待后续独立步骤。

仓库中已有的两处商店文案改动保持原样，与本次修复分开。
