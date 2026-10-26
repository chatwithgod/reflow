# Magpie 基准失败排查

固定基准为 `a1174674da9d1435443e95ffac7d0300ce8b59d6`。在改进隔离环境后，选定失败项的复查在干净上游和修改版均得到同一组 50 个失败项。完整范围见 [验证记录](VERIFICATION.md)，以下是进一步读取源码得到的线索。

| 失败类别 | 已核实的代码与日志关系 |
| --- | --- |
| 钥匙串模拟 | `internal/provider/codex_store_test.go` 的 `codexInKeychain` 只启用假的钥匙串，并未在配置中关闭 `secret_auth_storage`。`codex_store.go` 仍采用 Windows 默认 `true`，而 `keychainItem` 要求 `!Secrets`，因此测试没有进入想模拟的 macOS 钥匙串路径 |
| 应用配置目录 | `internal/gui/backup_test.go` 的 `sandboxHome` 清空 `APPDATA` 与 `LOCALAPPDATA`。`lody_test.go` 随后调用 `os.UserConfigDir()`，在 Windows 报 `%AppData% is not defined` |
| SQLite 子进程 | `internal/sqlitedb/sqlitedb_test.go` 的 `TestSQLiteSurvivesMalformedEnv` 主动向子进程传入不含等号的环境项；当前 Windows 运行在 `fork/exec` 阶段报参数错误，没有进入 SQLite 检查 |
| 符号链接 | 多项测试在 `os.Symlink` 阶段报告权限不足。已确认的是当前测试进程无法创建该链接；没有检查或改变开发者模式、系统权限等设置，也未验证链接创建后的行为 |

Handover socket、AutoVision 分配次数和部分跨平台路径等失败仍未充分定位，不能一概称为环境问题。

这些是源码和既有日志的对应分析，不是修复结果，也不是已提交的上游 issue。没有据此修改、跳过或重新定义原测试。已有 cgroup 根路径修复具有独立的正向与反向验证，应与此处未修复的问题分开看待。

后续应将测试夹具的修正放入单独补丁，并确认旧代码真实失败、修改后通过；无法修正的项需形成明确的上游问题。对外提交仍须单独授权，不能凭这份排查记录宣布全量宿主测试通过。
