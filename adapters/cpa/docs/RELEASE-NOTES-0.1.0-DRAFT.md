# CodexReflow v0.1.0 — 首发说明草稿及发布补记

本文件保留首发准备材料，**最终说明以 [公开 Release](https://github.com/LaoPiLao/cpa-plugin-codexreflow/releases/tag/v0.1.0) 为准**。
2026-10-08 另获授权后发布 Windows amd64 包，并完成匿名下载/字节复核；见 [发布记录](RELEASE-2026-10-08-0.1.0.md)。
正式构件是新构建，不是开发 DLL 改名；未安装到生产，先前 dev.5 未替换，商店 PR 未提交。

## 项目简介

CodexReflow · 续流是基于 CodexComp v0.1.7 的独立 CPA 插件分支，关注推理续接和流式事件兼容，
不是 OpenAI 或 CLIProxyAPI 官方插件。保留 MIT 许可证及上游版权、第三方声明。

## 首发内容

- HTTP/SSE 和裸 JSON/WS 事件共用有界解码器，处理分块、合并事件和宿主去除的 SSE 控制行边界；
  Responses 直接输出，不重复翻译。
- 全新配置默认按 GPT-5 及以上标准文本名称匹配，无须手写模型白名单；兼容旧手动名单及可选排除项。
  **这是名称规则，不是精确同步 CPA 模型目录或发现能力。**
- 保留加密推理状态续接及多轮用量合并。默认最多追加 3 轮；只有符合启发式并具备加密状态时才续接。
- 稳定客户端响应 ID，并对同连接/模型/通道的后继父 ID 做已知映射；完整上下文已知时支持原生 WS 增量续接。
  未知、过期或过大的历史不进行残缺重放，不切换为 HTTP 来伪装 WS 成功。
- 无请求/回答正文的按次逐轮诊断，以及本地只读汇总工具；`usage_join: unavailable` 明示不提供精确计费行连接。

## 证据与首发范围

**正式 `0.1.0` 的本地证据：**

- Windows amd64：Go unit/race/vet/fuzz，31 项原生 ABI、19 项 Python 测试；相同 DLL 在 CPA
  `8.0.13` / `8.0.15` / `8.0.16` 各通过 50 次隔离案例执行，SDK 固定为 `8.0.13`。
  合成上游不调用真实账号；150 次执行并非 150 种独立场景。
- 正式 ZIP 内容/校验文件通过；其中的实际 DLL 与被测构件逐字节相同，另重跑同一组 31 项原生 ABI 通过。
- 源码提交 `875864934cf82dbba90a7f85985f36ebd3a256d1` 的远程 Windows/Linux CI 成功；
  workflow 构建的是开发版本，不是正式 DLL 哈希的远程证明。

**dev.5 的历史真实使用证据，不移作正式 DLL 在线通过：**

- 2026-10-08 截至 01:42:48（UTC+8）的两个已有聊天：22 条已完成上游 WS 行均为 200；
  16 次处理的五项客户端合并用量吻合，6 次实际续接（含 4 次原生增量），两聊天均有工具往返和完整回答。
- 这个正式 DLL 没有调用真实模型或安装到生产，完整线上边界及质量仍待验收。
- 首发资产仅为 Windows amd64；Linux 源码/合成 ABI CI 通过不等于 Linux/macOS 正式资产或完整 CPA 集成验收。

具体限制及时间窗口见 [正式包验收](VALIDATION-2026-10-08-0.1.0.md)、[兼容性](COMPATIBILITY.md)、
[dev.5 隔离验证](VALIDATION-2026-10-07-dev5.md)、
[dev.5 真实核对](VALIDATION-2026-10-08-live-dev5.md)。不公开原始生产日志或使用量数据库。

## 已知限制与费用/隐私提醒

- 516 是续接启发式的一种命中值，不证明降智；续接不保证提高质量，也不会抹去 CPA 的原始上游记录。
  已观察到 `516 → 0`：实际追加了请求但没有新增推理 token。
- 追加调用增加 token 消耗及延迟。`max_continue: 0` 可禁用额外调用；不建议为增大数字开启实验阈值。
- WS 续接需在进程内存暂存完整输入/输出、设置及不透明加密推理；有容量/TTL 限制，不持久化正文，
  也不保证安全内存擦除。配置重载可能关闭原生 WS 会话，缓存不能保证跨重载/重连保持。
- 不同时启用 CodexComp 和 CodexReflow 接管同一模型。未验证的宿主版本、任意别名和非 Responses 客户端不作默认保证。
- `host_accepted` / `interceptor_returned` 不是送达回执；有限真实样本不是长期可靠性或质量认证。

## 已发布信息（后续补记）

- 仓库与维护者：[LaoPiLao/cpa-plugin-codexreflow](https://github.com/LaoPiLao/cpa-plugin-codexreflow)，公开源码；正式 Release 已单独获授权。
- 远程标签：`v0.1.0`，固定到被测源码 `875864934cf82dbba90a7f85985f36ebd3a256d1`；DLL 注册 `0.1.0` 和真实仓库来源。
- Windows 资产：[codexreflow_0.1.0_windows_amd64.zip](https://github.com/LaoPiLao/cpa-plugin-codexreflow/releases/download/v0.1.0/codexreflow_0.1.0_windows_amd64.zip)，根目录仅一份 `codexreflow.dll`，附许可证。
- ZIP SHA256：`63e0c62b414bea0dd98f1225f7507b78dcf8d0e7505e88147542a013ae8bd52d`，与本地 `checksums.txt` 一致。
- DLL SHA256：`6f2bb2cec1adb8db02925170fb3c35b0176ea474687f7620bf993816ad8402a0`，对应上述全部 DLL 回归报告。
- 校验文件：[checksums.txt](https://github.com/LaoPiLao/cpa-plugin-codexreflow/releases/download/v0.1.0/checksums.txt)；两份资产已匿名下载并核验，不会自动安装，商店尚未收录。

推荐下一步：按 [发布清单](RELEASING.md) 审阅商店提交草稿，再单独确认注册表 PR 授权；生产安装不在发布授权内。
