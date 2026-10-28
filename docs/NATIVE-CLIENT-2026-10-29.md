# 2026-10-29：官方 Codex 客户端离线复测

官方 Codex CLI `0.165.0` 和当前桌面应用附带的 CLI `0.165.0-alpha.1.2`，均通过 Windows 原生文件操作、Reflow 协议和原生插件的定向离线检查。这些覆盖路径已可使用未修改的官方客户端；此前本地 `0.164.0` 补丁构件的证据继续保留。

本次使用合成 ChatGPT 凭据和本地模拟上游，原生客户端串行执行。没有读取现有登录文件，没有新增真实模型会话，也没有启动或重启桌面应用。

## 已运行结果

| 检查 | 官方 CLI `0.165.0` | 应用附带 CLI `0.165.0-alpha.1.2` |
| --- | --- | --- |
| Code Mode 宿主启动、命令写文件、原生文件系统写入及目录边界预检 | 通过 | 通过 |
| 五个原生写入场景 | 5/5 通过；含父测试共 6 个通过项 | 5/5 通过；含父测试共 6 个通过项 |
| CLI、app-server、插件协议回归，启用 race | 7 个通过项，0 跳过、0 失败 | 7 个通过项，0 跳过、0 失败 |

五个写入场景沿用 [原生写文件探针](NATIVE-WRITE-PROBE.md)：经 Reflow 续接后的补丁修改、直接补丁修改、直接新建文件、关闭 daemon 后直接修改，以及经 Reflow 的命令写入与读回。协议检查沿用既有测试，包括 MCP 工具结果回传、app-server 的 `legacy`/`paginated` 两种历史格式及关闭进程后的恢复，以及本地市场插件安装和 stdio 调用。

通过项按 Go 的父测试和子测试事件计数，不能当作独立场景数量。本次没有重跑全项目测试；2026-10-27 的 79 项完整客户端回归和远程 CI 是另外的记录。

两版客户端、配套 Code Mode 宿主和 Reflow 二进制的前后散列一致，隔离测试目录已清理。Reflow 沿用 `0.1.0-dev.4`，没有为新客户端修改续接规则、工具处理或沙箱权限。

## 版本与证据

官方 [更新记录](https://learn.chatgpt.com/docs/changelog) 列出了 `0.165.0`。测试构件通过固定版本的 `@openai/codex@0.165.0` 安装在项目 `.tools` 目录，未进行全局安装。应用附带 CLI 的版本由原二进制在隔离用户目录中执行 `--version` 得到。

本页只确认已测行为恢复正常，没有据此认定某个具体上游提交已被包含，也没有将上游修复记作本项目贡献。旧版 `0.164.0` 和 `0.164.0-alpha.11.1` 的失败记录不作修改。

- 测试源码：`3c76d3a08812100cb9ac00207cca5ba19b008138`；测试文件和执行脚本散列均有记录。
- 机器可读证据：[native-client-2026-10-29.json](evidence/native-client-2026-10-29.json)，包含客户端与宿主散列、npm 完整性信息、通过项名称、原始报告位置及散列。
- 原始定向测试：`build/native-client-20261029/`；无账号预检：`build/evaluations/20261028-173410-132810/` 与 `build/evaluations/20261028-174314-879682/`。

复测时，将 `REFLOW_CODEX_BIN` 指向待测 CLI，`REFLOW_PROXY_BIN` 指向固定的 Reflow 构件，`REFLOW_PLUGIN_MARKETPLACE` 指向同版插件市场目录；各测试自行创建合成登录和临时工作区。具备对应 Go/C 工具链后串行运行：

```powershell
python evaluations/run.py --preflight-only --codex $env:REFLOW_CODEX_BIN
go test -p=1 -tags native_write_probe -run '^TestCodexNativeWriteProbe$' -count=1 -timeout=5m ./integration
go test -p=1 -race -run '^TestCodex(NativeLoginOffline|AppServerOffline|PluginInstallAndStdioOffline)$' -count=1 -timeout=5m ./integration
```

## 单次真实验证方案，已获批执行

准备时确定使用上述官方 `0.165.0` 和相同 Reflow dev.4，执行一次 NDJSON 开启组诊断。方案用于补充官方发行版的真实兼容性证据，减少对本地补丁构件的依赖。原提示、评分器和续接规则均保持不变。

- 模型 `gpt-6.1-sol/high`，仅一个会话，并发 1、禁用子代理；模型会话最多 180 秒，每轮最多续接一次。一个会话可能包含多次推理请求。
- 无账号预检通过后，才检查现有原生 ChatGPT 登录的模式、令牌声明中的 issuer 和有效期，并复制到临时目录；这个检查不等同于验证令牌签名。不主动测试 Token 刷新。
- 检测到限流即停止；不因没有触发续接而自动追加会话。一次性入口即使预检失败也消耗本次执行机会。
- 不包含 Desktop/dot 界面、生产配置修改、客户端替换、服务重启、推送、发布或提交。

参数、源码和构件散列见 [准备时的计划快照](evidence/next-live-official-0165-plan.json)。用户随后明确授权，该方案已执行完毕。一次性入口 `build/run-authorized-official-0165-live.py` 对应的 `started.once` 已创建，不能再次用于执行；`--check-only` 仍只校验离线文件。

实际在 61.101 秒正常结束，评分 9/9，6 次推理请求，续接 0 次；一次命令失败后继续完成任务，未检测到限流。单条件诊断不能建立质量改善结论，完整续接验收仍缺证据。结果与隔离核对见 [官方版实测](LIVE-OFFICIAL-0165-2026-10-29.md)。累计为 8 次真实会话、46 次观察到的推理请求、1 次续接；Desktop/dot 按用户决定继续保留未验收。
