# v0.1.1 Windows 正式包隔离验收记录 — 2026-10-12

## 结论与时间

从封存的公开 `v0.1.1` Windows ZIP 提取同一份 DLL，**不重新编译**，
完成 31 项原生 C ABI 测试及三个固定 CPA 宿主共 150 次合成隔离 HTTP/WebSocket 用例执行，全部符合断言。
完整重跑于 **2026-10-11 17:13:31（UTC+8）**完成；10 月 12 日读回构件、宿主和全部报告哈希后整理本文。
150 是同一批测试跨三个宿主执行的次数，不是 150 种独立场景；31 项原生 ABI 单列，不混入 150。

没有安装到生产、修改生产配置、切换生产传输、重启生产服务、消费生产 usage 队列或调用真实模型。
本次记录不代表 Linux/macOS CPA 集成、真实客户端/Desktop、答案质量或全面生产验收。

## 构件及来源

| 项目 | 已核对值 |
|---|---|
| 插件 ID / 注册版本 | `codexreflow` / `0.1.1` |
| 注册作者 / 仓库 | `CodexReflow contributors` / [LaoPiLao/cpa-plugin-codexreflow](https://github.com/LaoPiLao/cpa-plugin-codexreflow) |
| 发布源 / 标签提交 | `6c71eee479e9939a3d300b9231117fae11eef296` |
| 验收时仅文档的 main 提交 | `bf99c6efec6cf68707dfc615ba3f0654b4a8d7dc`；不是移动后的发布标签 |
| SDK / 平台 | 固定 CPA `v8.0.13` / Windows amd64 |
| Release / 资产身份 | `407813768` / Windows ZIP `624662706`；与封存发布记录一致 |
| ZIP SHA256 | `22fe218dd0cf6f9cad1d697a854dae14fa4553092859c2764c5f30aae52c13ca` |
| DLL SHA256 | `36c27836f4f6c16ff296b5685cfdc68fc9adabd17421086bd59b0fa0d307f497` |
| ignored 验收汇总 SHA256 | `affc0c25bba3673115eb3ffdd8eb3d51f1d2c15b188a7fc496f8ece9ea6f4154` |

[Windows 公开 ZIP](https://github.com/LaoPiLao/cpa-plugin-codexreflow/releases/download/v0.1.1/codexreflow_0.1.1_windows_amd64.zip)
与[统一 checksums](https://github.com/LaoPiLao/cpa-plugin-codexreflow/releases/download/v0.1.1/checksums.txt)
的身份/哈希读回一致；本次使用此前已匿名下载核对的封存字节，不声称再次下载了全部五平台资产。
重新验证 ZIP CRC、根部四成员、Windows amd64 DLL 类型及许可证字节，再提取到全新独立目录。
完整公开资产与原生 CI 来源见[发布记录](RELEASE-2026-10-09-0.1.1.md)。

发布源[五平台 CI #37916034316](https://github.com/LaoPiLao/cpa-plugin-codexreflow/actions/runs/37916034316)
的 Go unit/race/vet/fuzz 是已有源构建证据；本次没有把后续文档 CI 候选替换为正式 Release，
也没有借用 dev.5 或 v0.1.0 的 DLL 哈希/测试报告证明新构件。

## 同一 DLL 的固定宿主测试

| CPA 宿主 | 原生 WS 增量续接 | 父 ID / 重连 / 重载衔接 | HTTP/WS 自动选择 | 每宿主执行次数 |
|---|---:|---:|---:|---:|
| 8.0.13 | 14 | 13 | 23 | 50 |
| 8.0.15 | 14 | 13 | 23 | 50 |
| 8.0.16 | 14 | 13 | 23 | 50 |

宿主可执行文件运行前后固定为：

| CPA 宿主 | SHA256 |
|---|---|
| 8.0.13 | `5c3f35c5b2bd8e205379e6fe38d8c541b991bebdabdea8bb6b891ad7c630b6b6` |
| 8.0.15 | `2b436a0fd64e8242f6816fc548f5ad0cfee0d9973d48f49d8da98fda83c239db` |
| 8.0.16 | `ac12f37afda88d8fb0090b848569af6ff7ec74575393dec5e8ce49f3a97c2e7b` |

每个实例使用独立 loopback 端口、空账号目录、全新最小配置、合成凭据和本地模拟上游。
子进程不继承真实 provider 凭据、外部存储设置或代理环境；测试 HOME、配置及临时目录独立。
不读取生产配置，也不对生产管理 API 发请求。宿主响应头版本与明确选择一致；没有修改 SDK pin。

- HTTP/SSE、上下游实际 WS 握手、无 HTTP 回退、正常文本及工具返回通过。
- 516/1034、重复截断、零新增推理、根折叠后增量续接、省略设置继承及预算限制均符合断言。
- 自动名称匹配、旧白名单/显式模式/排除项、无加密状态不续接、稳定父 ID、完整重放、重连及并发隔离通过。
- failed/incomplete 和宿主提前关闭 socket 按负面预期保留，不把这些用例“通过”解释为错误被修成正常回答。
- 逐轮诊断、合并用量及终止元数据按测试断言核对；不声称已获得 ECPA 精确执行 ID 连接。

## 首次保护检查及安全清理

首次执行的 31 项原生 ABI 和第一组 14 项 WS 用例已经通过，但运行器随后要求临时目录绝对为空，
因此在 Windows 宿主留下影子 DLL 副本时主动中止，**没有将这一轮标为整体验收通过**。
副本名称/位置与固定 SDK 的 Windows 加载器实现相符，全部副本与被测 DLL 的 SHA256 相同；
检查未发现遗留测试宿主进程。它不是 14 项 WS 用例失败，也不作为线上插件故障的证据。

仅修正 ignored 本地验收运行器：先确认显式测试目录的绝对归属、无 symlink/junction、PID 已退出，
再按完整名称及同字节哈希逐文件清理本次测试产生的影子 DLL，最后删除空目录；不递归删除计算出的子树。
未知文件、活动 PID 或路径越界仍会拒绝清理。不涉及原始 DLL、旧 Release、生产文件或 SDK/插件实现修改。

首次日志、报告及运行器快照保留；在全新的版本化输出目录从头重跑 31 项原生 ABI 和完整 150 次隔离执行。
上表只统计这次完整重跑，不重复计入首次的 14 项。新旧测试临时根均确认清空，测试宿主均已退出。
报告及清理回执保存在 ignored 验收目录，不提交原始流、配置、账号或凭据。

## 尚未验收与后续步骤

- Linux/macOS 的证据仍是原生 ABI/打包层，未新增这些平台的实际 CPA HTTP/WS 集成测试。
- 未安装生产或使用真实模型/真实客户端；没有重新验证真实取消/断开、复杂长历史、重载等全部边界。
- 自动匹配仍是名称启发式，不是同步 CPA 模型目录；`usage_execution_join` 仍为 `unavailable`。
- 516 不证明降智；续接不保证推理增加或答案质量改善，真实追加调用可能增加费用及延迟。
- 商店已收录，见[独立收录记录](STORE-LISTING-2026-10-11.md)；本次没有另发/评论 PR、改注册表、上传 Release 或移动标签。

下一步只读核对当前 CPA 的安装版本和商店显示情况，再单独讨论有回滚方案的生产试装；
试装、启用及真实模型测试保持独立授权，不因隔离通过自动执行。
