# Magpie 使用公开 Reflow 模块构建

这条接入路径针对 Magpie 固定基准 `a1174674da9d1435443e95ffac7d0300ce8b59d6` 加本目录的补丁。它让启用 Reflow 的构建从公开 Go 模块加载固定提交，不再要求本地 Reflow 源码工作区。正常的 Magpie `go.mod`、`go.sum` 保持原样；这不是上游已接受的插件或二进制发布。

## 固定依赖

| 项目 | 固定值 |
| --- | --- |
| Reflow 源码 | [6d8e7a534060af4ea013877ae069f93c3b830b76](https://github.com/chatwithgod/reflow/commit/6d8e7a534060af4ea013877ae069f93c3b830b76) |
| Go 模块版本 | `v0.0.0-20261028113656-6d8e7a534060` |
| 模块校验和 | `h1:fOBElfEzRq3pYtJvTSKk4z9omiAdyzZGDaL7zluiQCw=` |
| 模块 go.mod 校验和 | `h1:0QoO1RWkvGkZZagc+/vOd9aIiVSyCGQE56PTwcv+4l4=` |
| 构建工具 | Go 1.26.8，跟随固定 Magpie 基准 |

这是固定源码提交对应的 Go 版本号，不是新创建的 Git 标签或 Release。第五份 `reflow-module.patch` 增加 `go.reflow.mod`、`go.reflow.sum` 及宿主构建说明，也修正启用可选插件时的宿主测试假设并补齐设置页翻译。仅在选择该模块文件时，websocket、compress、go-toml 分别使用 `1.8.15`、`1.20.3`、`2.4.3`；这些版本与此前本地 workspace 桥接选用的版本一致。

## 构建

在固定 Magpie 副本中按 [补丁清单](patches/manifest.json) 的顺序应用补丁。先关闭 Go workspace，再预取已锁定依赖。PowerShell 示例：

```powershell
$env:GOWORK = 'off'
go mod download "-modfile=go.reflow.mod"
go build "-modfile=go.reflow.mod" -mod=readonly -tags "nogui reflow" .
```

Linux/macOS shell 使用 `export GOWORK=off`，其余 Go 参数相同。参数中的引号可以保留，避免 PowerShell 拆分带点的 `-modfile` 值。不要使用 `@latest` 替换锁定的提交。

需要本地共同修改 Magpie 与 Reflow 时，仍可使用原来的 `go.work` 联调方式。`scripts/check-magpie.py` 的 `--workspace` 与 `--modfile` 二选一；采用公开模块的验证例子：

```sh
python scripts/check-magpie.py --magpie /absolute/path/to/magpie --go /absolute/path/to/go --modfile go.reflow.mod --phase suite --tags "nogui reflow" --packages ./internal/gateway ./plugins/reflow --run "^Test(Reflow|ZeroDefault)" --race
```

Windows 可用 `--compiler` 指定 race 检查需要的 C 编译器。该入口隔离 HOME 和应用目录、固定 Go 缓存、关闭测试阶段的模块下载，保存命令、源码散列和结果；模块文件相对 `--magpie` 解析，测试前后核对默认及替代锁文件都未改变。

插件仍默认 `maxContinue=0`，其配置与生命周期规则见 [适配说明](README.md)。不加 `reflow` 标签的普通构建不会注册执行扩展。

## 验证范围

本次从模块缓存加载公开版本，未使用本地 `replace` 或 `go.work`。已逐文件核对独立核心、代理及适配器的 10 个运行时 Go 源文件与公开提交一致；三个共享依赖的选择也与此前 workspace 相同。这不是对所有不参与构建的模块元数据做完整图比较。

Reflow 自身的最终默认回归为 69 个通过项、4 个客户端测试跳过，race、vet、解码器 fuzz 均通过。这次没有提供原生客户端路径，不替代已有的 79 项完整客户端模拟记录。

- 7 个 Reflow 桥接及默认关闭通过项通过 race，0 跳过、0 失败。
- 使用替代模块文件的 Windows/Linux `nogui reflow` 构建与全量 vet 通过。
- 使用原始模块文件的 Windows 普通构建与全量 vet 通过。
- TOML 错误位置及插件列表、启动配置、翻译的 11 个定向测试通过 race；原始依赖和可选依赖分别验证。
- Chromium、WebKit 各 5 组页面测试通过，覆盖英语、简体中文、繁体中文、日语和德语。新增 Reflow 检查验证 0、3、7 的保存、非法数值不提交、开关保留设置、刷新后保留 0，以及 420px 窄窗和页面错误。
- 换回旧语言文件后，新页面测试在中文翻译处失败；换回旧测试源码并使用原来的 `go.work`，同样复现本轮发现的 10 个 Go 失败项。
- Linux 检查是 Windows 上的交叉构建与 vet，不是 Magpie 原生 Linux 运行。页面测试使用真实页面资源与模拟 API；Magpie 原生窗口、真实后端设置持久化及 Codex Desktop/dot 没有因此获得界面验收。

本轮全量检查发现旧测试固定假设只有 14 个内置插件、启动配置只有 Gateway，且绑定了旧 TOML 依赖的诊断字节位置。补丁改为核对实际注册项，同时仍要求全部 14 个标准插件存在、没有重复项；TOML 测试仅接受已核对的两版依赖诊断，仍检查文件名、位置及错误类型。运行时 TOML 解析逻辑没有修改。另补齐 Reflow 的四种翻译，并让翻译检查正确识别语言块的第一个词条。

页面检查使用固定 Playwright `1.64.1`。先将它及 Chromium、WebKit 安装到隔离工具目录，再设置 `NODE_PATH` 和 `PLAYWRIGHT_BROWSERS_PATH` 指向该目录。在临时 HOME、USERPROFILE、APPDATA、LOCALAPPDATA 和 TEMP 下运行，两个引擎依次执行：

```powershell
$env:BROWSER = 'chromium' # 完成后改为 webkit，再运行一次
node --test --test-concurrency=1 internal/gui/tests/reflow-settings.test.cjs internal/gui/tests/builtins.test.cjs internal/gui/tests/plugin-kernel.test.cjs
```

这些测试截获页面请求并返回夹具，不启动 Magpie 网关，也不使用真实账号。翻译反向检查可将 `MAGPIE_REFLOW_ASSETS` 指向应用第五份补丁之前的 `internal/gui/assets`，仅运行新增的 `reflow-settings.test.cjs`；之后移除该变量。

宿主全量仍未通过。修正前的可选构建全量为 12,201 通过、615 跳过、46 失败；修正后记录 12,201 通过、615 跳过、38 失败，另有 `omarchy` 包达到 45 分钟超时。`TestPlacePanel` 没有正常结束，该包随后七项测试没有运行；38 仅统计已输出失败结果的测试项，不包含这次超时。目标的 10 个失败项已消失，但不能把这次运行写成完整通过。完整对照见 [机器可读证据](../../docs/evidence/magpie-public-module-2026-10-28.json)，没有新增真实账号测试。

新增全量运行还观察到 `TestSaveConcurrent` 和 `TestMaskedRecordKeepsSentAndBack` 失败。前者报告 518 次读取或 JSON 解析错误，保存错误和字段丢失计数均为 0；原断言没有区分读取失败与解析失败，因此不能据此断言数据已损坏。后者的脱敏记录耗时为 0 微秒，未满足测试的正数要求，在更早的宿主记录中也曾失败。这两项在旧 workspace 和本次公开模块下各定向重查一次，均通过；原因仍未解决，不把定向通过当作全量修复。

超时栈已定位到 `fakeNiri` 测试夹具的清理：`niri_test.go:148` 关闭监听器后等待 goroutine，而该 goroutine 仍在 `niri_test.go:137` 读取已经接受的连接。相同未改动源码在旧 workspace 下带 race 连续检查 20 轮，两项窗口定位测试共 40 个通过项；这不能替代全量结果。该夹具尚未修正，也没有据此断言生产窗口存在同样故障。

上段保留的是第五份补丁检查时的状态。其后的第六份补丁增加了稳定重现方式并修正测试夹具清理，见 [独立修正记录](NIRI-FIXTURE.md)；本页的原始全量失败及超时记录没有被覆盖。

本次另外读取了上游 `56602426d3a26c0048d97bb0a4d91a77a566efc6` 的 [gateway middleware 文档](https://github.com/yetone/magpie/blob/56602426d3a26c0048d97bb0a4d91a77a566efc6/docs/subsystems/gateway-middleware.md)，其中仍描述 JS 钩子的时限。本轮没有将补丁移植到这个新提交并运行，兼容范围仍限定在上述固定基准。

以后升级 Magpie 基准时，应从新的 `go.mod`、`go.sum` 重新生成替代模块文件、固定 Reflow 提交并重新验证，不能把当前文件当作适用于任意上游版本的通用锁文件。
