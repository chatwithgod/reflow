# dev.4 · 原生 WebSocket 增量续写候选

日期：2026-10-05（北京时间）。候选 `0.1.0-dev.4`，Windows amd64。
**构建/修补阶段未安装生产环境**。该阶段仅修改项目代码/文档、构建并运行隔离实例；没有生产配置写入、
真实模型调用、新建聊天、Git 提交/推送、Release 或商店提交。后续独立授权部署见本页末尾，
不将部署注册验证混同于新增路径的真实模型验收。

## 为什么需要新路径

dev.3 的 ID 桥能让客户端在隐藏追加后引用正确的上游父响应，但不会给原生增量生成追加思考。
因此，同一 WS 会话中根请求被折叠，不代表后续每个增量请求都会被折叠。
这也不意味着出现 516 一定是降智：上游轮次记录与单次客户端合并输出是不同层。

不能仅删除模型路由的 `previous_response_id` 排除条件。固定宿主的 self-executor 路径会影响
原生 WS 增量路由，可能在插件执行前落入 HTTP replay-required 分支。
本版保留首次上游增量请求的原生路由，使用响应流钩子，在首轮终止后有条件追加隐藏续写。

## 修补与边界

1. 完整输入请求仍走现有执行器；携带父 ID 的首次上游请求继续由 CPA 原生执行，保留增量、工具回传、
   原生凭证和传输策略。不创建另一层 WS 代理，不改模型名单或 Codex 传输设置。
2. 根请求成功后保存最新完整输入/输出及请求设置。同 host-owned socket、原始请求模型及通道内，
   只接受最新响应的可见或实际父 ID，重建完整输入后才允许隐藏续写。
3. 隐藏调用必须满足原截断启发式、加密推理状态和预算。省略设置继承上轮；显式设置（包括 null）优先。
   隐藏重放包含完整上下文及所需加密推理，不是丢父 ID 后仅发送当前 delta。
4. 丢弃中间暂定文本/工具事件，终止成功时提交规范历史；不把续写 marker 留在客户端后继上下文。
   可见响应 ID 保持稳定，下一次增量父 ID 仍由原桥指向最后一轮上游响应。
5. 缓存未知、过期、跨作用域或超限时不追加模型调用；不猜测残缺历史。资源耗尽返回明确 incomplete，
   失败/取消清理状态。已有升级前连接不保证有完整重放缓存。
6. `proxy_reflow.path=ws_incremental` 区分新增路径。日志 `interceptor_returned` 只表示响应钩子返回字节，
   不保证宿主接受、网络送达或客户端显示。用量继续保留上游轮次记录。

### 内存与隐私变化

dev.3 的别名桥只存 ID；dev.4 **另有完整上下文内存缓存**，包括用户输入、回答、请求设置和不透明加密推理。
这些内容不写入插件日志或磁盘，但不能继续宣传“插件完全不保存提示词/加密推理”。

| 状态 | 预算与清理 |
|---|---|
| 最新规范上下文 | 最多 64 个 scope；每项 16 MiB；序列化合计 64 MiB；TTL 15 分钟，访问/写入时惰性清理 |
| 活动增量折叠 | 最多 64 项；请求/重建输入预算 16 MiB；单个回调块 8 MiB；单次累计原生及隐藏流 16 MiB；活动序列化字节合计 64 MiB；20 分钟惰性到期及生命周期清理 |
| 原 ID 别名 | 保留 dev.3 的独立容量/TTL及作用域规则 |
| shutdown | 清空新增上下文、活动请求和原别名状态 |

以上是序列化负载计数，不是 Go 堆/RSS 或系统总内存上限。清理解除引用，不承诺即时 GC、物理内存擦除或
OS 不交换内存。长会话、超过缓存预算、跨连接恢复均需要客户端完整重放；不能从缓存未命中推出质量差。

## 实际验证

同一候选 DLL SHA256：

```text
e1ab6b911691b3450aee1609b766b8d510b16a80cc9aad33eaff371d10db6a15
```

SDK / 模块依赖仍锁定 CLIProxyAPI `v8.0.13`；构建工具 Go `1.26.8`、项目本地 LLVM-MinGW。
测试脚本通过管理响应头核对宿主版本，必须显式选择 `8.0.15`，不会追随 latest。

| 验证 | 实测结果与范围 |
|---|---|
| Go 单元测试 | 通过；上下文隔离、最新父 ID、TTL/容量/大小、设置继承、私有快照、修订撤销、并发、活动字节和生命周期清理 |
| Go race / vet / gofmt | 通过；仅本项目源码，不是宿主源码静态检查 |
| 解码器 fuzz | 本版另跑 15 秒预算，196,736 次执行，通过；不是模型质量验证 |
| Python 发布打包保护单测 | 6 项通过 |
| Windows DLL + 合成 C ABI | 29 项通过；这是原生加载/回调与折叠回归，不是真实 CPA/账号 |
| CPA 8.0.13 实际隔离进程 | 14 增量 + 13 衔接 + 23 自动选择案例符合预期 |
| CPA 8.0.15 实际隔离进程 | 相同 DLL，14 + 13 + 23 案例符合预期 |
| dev.3 对照，CPA 8.0.13 | 7 个旧行为案例符合对照预期；原生增量追加计数为零，不称作旧版增量功能通过 |

两种宿主共 100 次案例执行，包含重复基线、开关控制组及预期错误，不是 100 种独立验收场景。
每份候选原生/隔离报告均读回同一 DLL 哈希。成功 WS 场景均完成上下游真实握手，未回退 HTTP。

### 新增 14 项覆盖

- 原生增量 516 / 1034；首轮折叠后再增量折叠；连续两次增量截断。
- 工具回传后触发折叠；增量折叠后发出工具及后续工具回传；不泄露暂定工具/文本。
- 增量省略 instructions/tools/reasoning 设置时，隐藏完整重放继承设置。
- 追加轮零思考 token：仍可已追加而最终 516，不能把“数字未变”当作未执行。
- 默认最多追加三轮；`max_continue: 0` 与缺少加密状态时零追加。
- 原生 failed / incomplete：不伪装成成功。CPA 可在响应钩子前拦截 failed 并关闭 socket，
  对照验证这是宿主原生终止，不是插件产出完成回答。
- 两个并发 WS 连接使用相同响应 ID，各自完整上下文与独立 run ID 不混淆。

原 13 项衔接集保留文本后继、工具回传、完整重放、新连接、模型前后缀和配置重载控制。
配置重载仍可能引发宿主 `executor_shutdown`；测试以新 socket + 完整输入恢复，**不是无缝热重载证明**。
原 23 项自动模型选择集保留 HTTP/SSE 正常文本、控制行、续写、工具及旧配置迁移边界。

### 工作区并行改动与测试隔离

本次根目录 `go test ./...` 曾受忽略的 `build/` 下另一项宿主源码检查 Go 包影响（其依赖并非插件依赖）。
未删除、移动或修改那项工作，也未为其增加模块依赖。
随后将根目录全部 `*.go`、`go.mod`、`go.sum` 原字节复制到忽略的 `.tools/validation-dev4-source`，
逐文件 SHA256 记录于 `build/source-snapshot-dev4.json`，在该完整插件源码快照执行
`go test ./...`、`go test ./... -race`、`go vet ./...` 和构建。
因此本页通过结果针对完整插件包，不把原工作区的无关包失败掩饰为根目录全树通过。
其快照与当前插件源码哈希一致，构件和全部原生/隔离报告哈希一致。

## 复现与报告

在仅包含项目源码的 checkout 中准备项目本地工具，然后执行：

```powershell
. ./scripts/dev_env.ps1
go test ./... -count=1
go test ./... -race -count=1
go vet ./...
go test -run '^$' -fuzz '^FuzzDecoderChunkBoundaries$' -fuzztime=15s -parallel=2
./scripts/build_windows.ps1 -Version 0.1.0-dev.4
python scripts/native_smoke.py build/codexreflow.dll --report build/native-smoke-dev4.json
python -m unittest discover -s scripts -p 'test_*.py'

# 每次用对应版本的实际 CPA 文件；两种版本分别运行下列三组。
python scripts/ws_incremental_fold_smoke.py --cpa <CPA> --cpa-version 8.0.13 --dll build/codexreflow.dll --report build/ws-incremental-fold-dev4-cpa8013.json
python scripts/ws_incremental_smoke.py --cpa <CPA> --cpa-version 8.0.13 --dll build/codexreflow.dll --native-folds --report build/ws-bridge-dev4-cpa8013.json
python scripts/isolated_cpa_smoke.py <CPA> build/codexreflow.dll --cpa-version 8.0.13 --auto-models --report build/isolated-auto-dev4-cpa8013.json
# 使用 CPA 8.0.15 时同时改为 --cpa-version 8.0.15，并使用不同报告名。
```

本次版本化候选在 `build/codexreflow-v0.1.0-dev.4.dll`（忽略目录，不提交）。
本地报告：`unit-tests-dev4.jsonl`、`race-dev4.log`、`vet-dev4.log`、`fuzz-dev4.log`、
`python-tests-dev4.log`、`native-smoke-dev4.json`、`ws-incremental-fold-dev4-cpa8013.json`、
`ws-incremental-fold-dev4-cpa8015.json`、`ws-bridge-dev4-cpa8013.json`、`ws-bridge-dev4-cpa8015.json`、
`isolated-auto-dev4-cpa8013.json`、`isolated-auto-dev4-cpa8015.json`、`validation-dev4.json`。
报告只包含合成测试和无敏感负载的汇总，不将真实聊天、凭证或加密字段收入 fixture。

## 尚未证明 / 下一步

- 合成加密字段不是实际模型推理签名；工具事件测试不是工具实际执行。未调用真实付费模型。
- 不保证所有模型/路由/CPA版本兼容；实际只验证上述两个 Windows 宿主。CI 文件更新不等于 CI 已运行。
- Desktop 用户取消、超时、超长请求、真实账号的加密状态接受、steering、通道 multiplexing/fork 等仍待验收。
- 不能消灭原始 516 行，也不能保证追加会增加思考 token 或提高质量。
- 本次只读核对时线上为 CPA `8.0.15` / Reflow `dev.3`，enabled / registered / effective_enabled 均为 true。
  本候选未改变生产加载版本、配置、启用状态或传输协议。

上述为构建阶段的状态和边界。后续安装不补足真实模型验收证据，也不修改原构建回执的当时状态。

## 后续独立授权部署

2026-10-05 21:48（北京时间），用户在“两个现有聊天空闲后，备份并安装 dev.4”的建议后要求继续。
安装前两次读取聊天状态，均确认用户指定的两个聊天为 idle；没有向它们发送测试消息，也没有新建聊天。

- 候选 DLL、全部隔离报告、源码快照的哈希核对通过；CPA 宿主版本/二进制与隔离验证的 `8.0.15` 相同。
  SDK 依然为 `8.0.13`。
- 先备份 CPA YAML、ECPA TOML、Codex TOML 和全部现有插件 DLL，逐个核对备份哈希。
  备份目录标识为 `codexreflow-upgrade-dev4-20261005-214848`；完整位置由忽略的部署回执定位。
- 以独占创建方式加入版本化 dev.4 DLL，不覆盖已有文件；原 dev.3 及其备份仍保留。
- 针对安装副本运行 29 项真实 DLL + 合成 C ABI 回调测试，全部通过且哈希与候选相同。
  这是独立进程的 mock-host 验证，不是生产账号或 WS 模型请求。
- 仅 PATCH `plugins.configs.codexreflow.store.version`，将 dev.3 切换为 dev.4；整份 CPA YAML 的语义比较
  仅出现该字段。没有整份配置回灌，没有关开插件或服务重启。
- 反复读回 dev.4 的选中路径、版本、`enabled=true`、`registered=true`、`effective_enabled=true`；
  另一次独立读取再次确认，未发现插件运行错误。
- `model_mode=auto`、`max_continue=3`、旧模型列表及其他 Reflow 选项全部保留；CodexComp 仍关闭。
  其他插件的配置、注册/启用状态及已有 DLL 不变；ECPA / Codex TOML 字节哈希不变。
- `supports_websockets=true` 保持不变。本次选择器热重载仍可能关闭原生上游 WS 会话；
  idle 检查仅避免中断这两个聊天的在途请求，不能保证旧连接无缝续用。
- 未发起额外模型测试请求，未创建 GitHub 项目、提交/推送、发布 Release 或上架商店。

部署回执：忽略的 `.tools/last-upgrade-dev4.json`；安装副本测试报告：`build/native-installed-dev4.json`。
原 `build/validation-dev4.json` 保留构建时未部署的状态，不用覆盖历史回执来制造“当时已上线”的证据。
回滚应通过 Reflow 版本选择器仅切回 `0.1.0-dev.3`，保留后续无关配置，不直接恢复整份旧 YAML/TOML。

下一步：直接沿用用户指定的两个现有聊天正常使用，按发生时间核对增量请求的 `path`、独立 `run_id`、
追加计数、停止原因、最终回答和工具回传；首个恢复请求可由客户端以新连接和完整输入重放。
不为了增加思考数字新建聊天或盲目扩大预算。
