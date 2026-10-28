# Reflow 兼容性（0.1.0-dev.4）

Reflow 是独立 Go 服务，不依赖 CPA SDK。以下记录的是已运行的验证，不把交叉编译、模拟上游或健康检查当作真实账号验收。

| 接入方式 | 版本与范围 | 已验证行为 |
| --- | --- | --- |
| Codex CLI | 2026-10-29：官方 `0.165.0`；应用附带的 `0.165.0-alpha.1.2` 另在本机 Windows 验证 | 真实客户端、合成 ChatGPT 凭据和模拟上游下，WebSocket 续接、最终 MCP 工具执行及结果回传通过；写入结果依宿主环境而异，见下方 CI 记录。旧版失败记录保留 |
| Codex app-server | 同上两版官方客户端；`legacy` 和 `paginated` 历史格式 | 合成登录仍识别为 ChatGPT，provider 保持 `openai`；续接后执行本地 MCP、回传结果，关闭进程后恢复会话并完成下一轮；接入配置精确还原。仅后端 RPC，未验证 Desktop/dot 界面 |
| Pi | `1.4.0` 的 `openai-codex` provider | 保留内置 OAuth 和模型目录，只改请求地址；SSE、WebSocket、工具执行与回传通过。新的 `openai` provider 未适配 |
| Codex 原生插件 | 本地开发包 | 在临时 `CODEX_HOME` 注册市场、安装缓存二进制；4 个 stdio MCP 工具通过，真实会话经 Code Mode 调用 `status` 通过。插件提供配置与诊断，代理服务需独立启动 |
| Magpie | 固定提交 `a1174674da9d1435443e95ffac7d0300ce8b59d6` 加本地补丁 | 原生 HTTP、zstd、上游 WebSocket、托管 Responses 透传四条路径的模拟续接和 race 通过；可通过替代模块文件使用公开 Reflow 固定提交。补丁未提交上游 |

Windows amd64 已进行原生客户端联调。2026-10-28 的 Windows、Linux、macOS 源码离线 CI 均通过，覆盖模拟协议和合成评测进程；Codex CLI、app-server、Pi 与插件四项联调在当时的远程 CI 跳过。Linux/macOS 各架构的打包构件当时只有交叉编译记录，后续原生执行结果见下方。历史范围见 [公开与 CI 记录](PUBLICATION-2026-10-28.md)。

2026-10-29，[原生客户端流水线](NATIVE-CI.md) 已公开并完成三平台执行：固定客户端依赖，按当前平台打包，并实际运行 ZIP 解压后的独立服务和插件。三个 runner 的四组客户端普通/race 检查均为 10 通过、0 跳过；macOS arm64 的五个写文件场景也通过。Ubuntu amd64 和托管 Windows 的五个写入场景全部失败，原因尚未确认；此前本机 Windows 的五场景成功记录单独保留。Linux arm64/macOS amd64 尚缺原生验证。

2026-10-26 测得官方 `0.164.0` 和应用附带的 `0.164.0-alpha.11.1` 写入失败；本地加入上游修复后通过，见 [历史复现](NATIVE-WRITE-PROBE.md)。2026-10-29，上表两版未修改的官方客户端在本机 Windows 均通过无账号预检、五个写入场景和协议/插件 race 定向检查。这是本机新版本的离线行为证据，真实会话仍未完整验收。见 [新版本复测](NATIVE-CLIENT-2026-10-29.md)。

独立代理还覆盖 HTTP/SSE、预热、取消、gzip/zstd 请求、compact 透传、多轮恢复与缓存隔离。上述协议回归主要使用模拟客户端/上游，不能推导为 Desktop/dot 已验收。详情见 [dev.4 验证记录](VERIFICATION-0.1.0-dev.4.md)。

2026-10-27 带完整客户端的本地全量回归为 79 个通过项、0 跳过，race、vet、fuzz 通过。当时的 app-server 检查沿用 dev.4 构件，没有替换生产客户端，也没有新增真实账号调用。两种历史格式的证据与桌面隔离入口的只读调查见 [app-server 记录](APP-SERVER-2026-10-27.md)。新客户端的定向检查单独记录，不混算为本次全量结果。

## Magpie 边界

可信 Go 扩展 `gwexec` 只进入流式 Responses 兼容直通路径；跨协议、非流式和 compact 旁路。可选 `reflow` 构建标签启用桥接代码，`maxContinue` 默认 0，显式设置 1–7 才注册续接。普通模块不依赖 Reflow；可选 `go.reflow.mod` 已固定公开模块版本，本地开发也可使用 `go.work`。

Windows 普通 GUI 构建、Windows `nogui reflow` 构建、Linux `nogui` 构建通过。Magpie 全量 `nogui` 测试为 12180 个通过项、615 个跳过项、60 个失败项。改进隔离环境后，对原失败项进行复查，干净上游和修改版均为 12 通过、0 跳过、50 失败，失败集合相同。这是选定失败项的对照，不是双边全量通过，也未确定所有失败根因。见 [宿主证据](../adapters/magpie/VERIFICATION.md)。

2026-10-27 的独立测试夹具补丁使 14 个旧失败项通过；新的全量为 12,204 通过、615 跳过、36 失败，剩余失败名称均已在旧记录出现。与 dev.4 结合的桥接/default-off 检查有 7 项通过 race；Windows/Linux 的上述构建和 vet 也重新通过。见 [后续证据](../adapters/magpie/WINDOWS-FIXTURES.md)。

2026-10-28 增加 [公开模块构建](../adapters/magpie/PUBLIC-MODULE.md)：无需本地 Reflow checkout，普通 Magpie 模块文件不变。补齐可选构建的测试兼容和四种语言翻译；Chromium/WebKit 的设置页及相邻插件页面测试通过。这是固定基准、模拟 API 的检查，不能替代真实账号、原生窗口或最新 Magpie 上游的验收；全量结果保留在该记录中。

同日补充 [窗口夹具退出修正](../adapters/magpie/NIRI-FIXTURE.md)：稳定重现并修正已接受连接没有随模拟服务器清理关闭的问题。只改测试代码，原生窗口和 Desktop/dot 的验收状态不因此改变。

2026-10-29 增加 [耗时检查修正](../adapters/magpie/MASKING-TIME.md)：直接核对原始计时与记录，接受合法零值，并用虚拟时钟和故障注入检查 JSON、文本两条路径及最终记录。生产计时未改动，完整宿主结果见该记录。

## 尚未完成

真实账号链路仍缺完整验收；登录刷新、Codex Desktop/dot、Linux/macOS 官方客户端与打包构件验收、生产接入和二进制发布尚未完成。源码已公开。评测器的 4 项任务、34 个检查点已自检，尚无质量改善结论。插件安装成功或 `/healthz` 正常，只说明相应组件可用，不证明模型请求已经经过 Reflow。

2026-10-26 补充：原生 ChatGPT 登录已完成真实推理请求和工作区代码修改。开启组观察到一次续接，但会话超时，尚未完成“续接、后续工具、正常结束”的整体验收。首次实测及其限制见 [真实测试记录](LIVE-SMOKE-2026-10-26.md)。

2026-10-27 补充：dev.4 加隔离修复版 Codex 的单次真实诊断正常结束，原生文件修改完成，评分 9/9，无工具失败事件；续接为 0 次，所以仍未完成上述整体验收。见 [修复版实测](LIVE-SMOKE-2026-10-27.md)。

同日后续拓扑排序诊断正常结束，评分 8/8，5 次推理请求，工具失败 0 次，续接仍为 0 次。它补充了原生登录的任务覆盖，没有完成真实续接闭环或 Desktop/dot 界面验收。见 [本次结果](LIVE-TOPO-2026-10-27.md)。
