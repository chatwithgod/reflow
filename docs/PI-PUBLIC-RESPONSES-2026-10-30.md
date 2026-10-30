# Pi 新 OpenAI 入口适配

2026-10-30 核对 npm 发布元数据，当前 `@earendil-works/pi-coding-agent` 仍为 1.4.0。该版本把 `openai-codex` 标为 legacy；新的 `openai` 同时保留 API key 和 ChatGPT OAuth。后者使用公共 Responses 路径和独立客户端授权，不能把旧入口的地址与登录直接当作同一流程。

新增 `adapters/pi/reflow-openai.ts`，复用 Pi 的原生 OpenAI Responses 实现，保留官方模型 URL，仅在请求级 `fetch` 将 Responses 转发到回环 Reflow。推荐单独使用 18517 端口及 `https://api.openai.com/v1` 上游。模型目录、OAuth、原生重试、解析和用量处理仍由 Pi 实现；原有 `reflow.ts` 旧入口未改。操作方法见[Pi 接入](../adapters/pi/README.md)。

这是必要的行为区别：Pi 1.4 用模型的规范地址识别 ChatGPT 登录，并据此去掉不支持的请求字段。直接把 `baseUrl` 改成回环地址，会失去该识别。负向对照实际观察到受限字段混入；新适配保留 OAuth 限制，API key 路径原本的输出上限字段也保持可用。新适配没有重写请求正文或读取登录文件。

| 检查 | 结果与范围 |
| --- | --- |
| 源码普通/race、vet、fuzz | 普通/race 各 80 通过、4 个未配置客户端的测试跳过，vet/fuzz 通过 |
| Windows 解压包原生普通/race | 各 14 通过、0 跳过；包括 Codex CLI/app-server/插件和 Pi |
| 原生写入 | 原有 5 个场景通过，含父测试计为 6 个通过项 |
| Pi 正向路径 | 旧入口 SSE/WS、新入口合成 OAuth/API key SSE；各 3 次模拟请求、1 次续接、实际 read 工具及匹配回传 |
| 新入口负向对照 | 直接替换地址会破坏 OAuth 请求限制；断言保留该差异 |
| 传输边界 | 5 项 Node 检查：回环地址、请求/头部、路由范围、取消、不直接回退到上游 |
| Pi 只读探针 | 普通/race 各 4 个通过项，含正常、429、越界读取及父测试；后两种对照均只有 1 次请求 |
| 评测器 | 49 项通过，包含凭据类型/有效期/scope、脱敏、限流停止及原有 Codex 回归 |

所有测试使用合成凭据和本地模拟上游，客户端串行。没有读取现有登录、修改生产配置或新增真实模型调用。新扩展及辅助模块直接从解压后的构件加载，文件散列与源码一致；官方客户端二进制未变，临时环境清理完成。其他操作系统的本轮改动尚未远程执行。

排查记录保留两次准备阶段问题。首次使用 SDK 子路径导入时，Pi 1.4 宿主的兼容导入映射无法解析；改用宿主提供的根 SDK 工厂后通过，未修改 Pi 安装文件。随后只读探针发现工具回传计数为 0：原夹具的工具条目 ID 缺少 `fc_` 前缀，Pi 补前缀后不再与原条目 ID 完全相同。修正 Pi 专用夹具并加上精确回传计数断言后通过；没有放宽 Reflow 匹配规则，也没有修改核心续接判断。

用户已明确“我说的是pi”“你模拟测试通过就行了”：Pi 按上述模拟结果验收通过，不再要求首次登录或追加真实调用，见[验收范围记录](evidence/pi-simulated-acceptance-2026-10-30.json)。已准备的[只读探针](PI-OAUTH-PROBE.md)仅保留为可选诊断工具，旧冻结方案不再是待执行任务。Pi 的真实账号、浏览器登录和刷新没有因此被标为实测通过。原生 Codex 的 21 次会话、114 次已观察请求、4 次续接累计值不变，API key 历史单独记录。

机器可读来源、测试日志和构件散列见[准备证据](evidence/pi-public-responses-preparation-2026-10-30.json)。本轮修改仅在本地，未推送、发布或对外提交。

接口来源：[OpenAI 公共 OAuth 推理](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference)、[客户端注册与登录](https://developers.openai.com/siwc/token-sharing-open-source/sign-in)，以及固定 Pi 1.4.0 安装包中的 Responses、OAuth 和扩展组合实现。
