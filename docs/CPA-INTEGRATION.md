# 共用核心与 CPA 接入

本次统一源码与开发入口。独立服务、Codex 插件和 CPA 原生插件仍分别出包，安装身份不变；旧 CPA 仓库、公开附件、商店入口和生产配置没有在此步骤中迁移。

## 来源与历史

- 独立版基线：`6d32acd01d96d28514e9107a5ae82df78ba69f6b`，已发布运行代码来自 `v0.1.0-dev.5`。
- CPA 导入基线：`ad0a644c5612548bdca12cee5ea0a311fb62a680`，包含 `v0.1.3` 修复与验证记录。
- 通过保留双方历史的 subtree merge 导入 `adapters/cpa`，没有重写旧提交、旧标签或旧构件。
- CPA 原工作目录里未提交的两份商店草稿没有纳入导入，也没有修改。此处 `store/` 和嵌套 `.github/` 是所选提交中的历史文件，不是已更新的商店申请或正在执行的工作流。
- 两边原有 MIT 许可、上游署名和第三方许可证一并保留。

## 代码边界

```text
core/                 共用续接、事件缓冲/合并、用量计算、流解码
proxy/                独立服务的 HTTP/WebSocket 与账号范围隔离
cmd/reflow/           独立程序入口
adapters/cpa/         CPA 原生 ABI、SDK、配置、诊断、历史衔接
adapters/pi/          Pi 接入说明
adapters/magpie/      Magpie 接入
plugins/codex/        Codex 配置与诊断插件
```

CPA 依赖固定的 `CLIProxyAPI/v8 v8.0.13`，位于自己的 `go.mod` 中。它通过 `replace github.com/chatwithgod/reflow => ../..` 使用同一提交下的核心；构建需完整克隆本仓库，不能只复制 `adapters/cpa`。根模块没有引入 CPA SDK。

两种运行方式调用同一个 `core.FoldState`，处理输出事件、最终工具释放、序号、推理累加、续接条件与重放内容。独立版的 `Session` 管理网络请求之间的状态；CPA 的 `foldState` 管理宿主回调和日志。

保留的边界差异：

| 行为 | 独立版 | CPA 插件 |
| --- | --- | --- |
| 按模型设置最低推理量 | 不开放此项配置 | 保留原有 `min_reasoning_tokens` |
| 事件接收与响应 ID | 保留严格校验、克隆和 ID 归一化 | 保留已有宿主事件契约 |
| 已在上游执行的工具 | 保留停止续接保护 | 保留原 CPA 策略，本轮不扩大行为变更 |
| 无法恢复父响应 | 核心返回停止原因 | 宿主适配层检查历史与资源限制 |
| 工具参数被宿主改写 | 原样保留工具声明 | 按 `OriginalRequest` 恢复已知类型改写 |
| 诊断元数据 | 独立代理计数 | 保留 CPA 日志和 `proxy_reflow` 字段 |

CPA 的专用兼容逻辑不能直接套到原生登录路径。工具声明回归同时覆盖 HTTP、WebSocket、首轮、续接及动态 `additional_tools`。

## 本地验证

在根目录运行普通测试、race 和 vet；再在 `adapters/cpa` 重复这三项。两套测试都是必需的，`go test ./...` 不跨越嵌套模块。

CPA 的原生 ABI 和打包检查使用合成数据、模拟宿主，无真实模型调用：

```sh
cd adapters/cpa
python -m unittest discover -s scripts -p 'test_*.py'
go build -trimpath -buildmode=c-shared -ldflags '-X main.pluginVersion=0.1.4 -X main.pluginRepository=https://github.com/chatwithgod/reflow' -o build/0.1.4/codexreflow.dll .
python scripts/native_smoke.py build/0.1.4/codexreflow.dll --report build/0.1.4/native-smoke.json
```

上例用于 Windows；其他系统使用对应的 `.so` 或 `.dylib`。构建前准备新的输出目录，保留旧版本；Windows 也可用 `scripts/build_windows.ps1` 自动创建带版本和时间戳的目录。

`scripts/build_platform.py` 在独立快照中验证并打包，快照同时包含 CPA 源码、共用 `core`、两份模块文件；任一部分变更都会改变源码指纹。根目录 `cpa-packages.yml` 保留五平台原生验证、打包后再次检查和完整附件校验，任务并发为 1。它没有创建标签、发布 Release 或改写商店的权限。

独立版打包明确排除 CPA 源码、动态库、缓存及测试输出，避免把两类产品混进同一 ZIP。

## 版本与后续入口迁移

当前是未发布候选：独立版 `0.1.0-dev.6`，CPA `0.1.4`。旧公开版本的真实账号、Desktop/dot 和多平台验收不自动适用于新构件；本次结果以新的离线记录为准。

整合源码已推送并完成[五平台离线验收及合并审查](CPA-INTEGRATION-ACCEPTANCE-2026-11-12.md)。旧 CPA 仓库继续保留历史下载与现有商店入口；商店迁移、旧仓库归档和发布属于后续步骤。代码历史的导入不会自动合并两边的 Star、Issue 或 Release。

## 2026-11-12 本机离线结果

[数字记录与构件散列](evidence/cpa-integration-2026-11-12.json)保留了来源、结果和未覆盖范围。

| 检查 | 结果 |
| --- | --- |
| 独立版普通 / race | 各 97 项通过、4 项原生客户端检查默认跳过 |
| CPA 普通 / race | 各 220 项通过 |
| 两个模块的 vet | 通过 |
| CPA Python 校验 | 52 项通过 |
| CPA 解码与参数恢复 fuzz | 均通过 |
| Windows CPA 原生 ABI | 打包前、打包后各 46 场景通过 |
| Windows 独立包 | 程序启动、模拟续接、工具隔离、工具声明、合并用量通过 |
| 独立包与 Codex 插件包 | 内含程序散列一致，均不含 CPA 构件 |
| 共用源码 | 31 个文件与 Git 对象一致；两种 `autocrlf` 设置的指纹相同 |
| 工作流 | YAML、五平台目标、只读权限、原生任务并发 1 检查通过；未远程执行 |

第一次 Windows 打包的 ABI 检查已经通过，但根模块文件的 CRLF 使工作区源码指纹不同于 Git 对象。随后用 `.gitattributes` 固定 `go.mod` / `go.sum` 为 LF，重新打包并复核。修正前后的 DLL 字节一致；新的源码指纹和来源提交以记录中的修正版为准，旧候选没有覆盖。

本轮真实模型调用为 0，没有改生产配置、替换现有插件或执行发布。Linux/macOS、新版本的真实账号和完整 CPA 宿主集成仍未验收。

同日随后已获授权推送整合分支：独立版三平台常规回归通过，原生客户端 Ubuntu/macOS 通过，托管 Windows 保留已知写入失败；CPA 五平台工作流未触发，不能当作验收通过。后续状态与触发配置补充见[首轮远程检查](CPA-INTEGRATION-CI-2026-11-12.md)。

再次获授权推送 `b041cd4` 后，CPA 五平台工作流已运行：两个 Linux 平台通过；macOS 两架构和 Windows 因同一个临时路径别名比较误判停止。测试修正及本机负向/正向对照已完成，远程复验待进行，详见[路径测试修正](CPA-INTEGRATION-PATHS-2026-11-12.md)。

上述历史记录之后，修正 `c25d277` 已推送并完成复验：CPA 五平台及汇总全部通过，所有平台构件和总包下载核验一致；独立版三平台常规检查通过，原生客户端托管 Windows 的已知写入失败保留。当前审查结论和限制以[最终验收记录](CPA-INTEGRATION-ACCEPTANCE-2026-11-12.md)为准。
