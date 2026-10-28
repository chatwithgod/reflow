# Magpie 基准失败排查

固定基准为 `a1174674da9d1435443e95ffac7d0300ce8b59d6`。在改进隔离环境后，选定失败项的复查在干净上游和修改版均得到同一组 50 个失败项。完整范围见 [验证记录](VERIFICATION.md)，以下是进一步读取源码得到的线索。

| 失败类别 | 已核实的代码与日志关系 |
| --- | --- |
| 钥匙串模拟 | `internal/provider/codex_store_test.go` 的 `codexInKeychain` 只启用假的钥匙串，并未在配置中关闭 `secret_auth_storage`。`codex_store.go` 仍采用 Windows 默认 `true`，而 `keychainItem` 要求 `!Secrets`，因此测试没有进入想模拟的 macOS 钥匙串路径 |
| 应用配置目录 | `internal/gui/backup_test.go` 的 `sandboxHome` 清空 `APPDATA` 与 `LOCALAPPDATA`。`lody_test.go` 随后调用 `os.UserConfigDir()`，在 Windows 报 `%AppData% is not defined` |
| SQLite 子进程 | `internal/sqlitedb/sqlitedb_test.go` 的 `TestSQLiteSurvivesMalformedEnv` 主动向子进程传入不含等号的环境项；当前 Windows 运行在 `fork/exec` 阶段报参数错误，没有进入 SQLite 检查 |
| 符号链接 | 多项测试在 `os.Symlink` 阶段报告权限不足。已确认的是当前测试进程无法创建该链接；没有检查或改变开发者模式、系统权限等设置，也未验证链接创建后的行为 |

2026-10-27，前两类问题已在独立测试补丁中修正。定向正向与反向检查通过；本轮全量为 12,204 通过、615 跳过、36 失败，旧失败集合中的 14 项改为通过。见 [Windows 夹具修正](WINDOWS-FIXTURES.md)。表格保留的是修正前的原因分析。

SQLite 子进程、符号链接、handover socket、AutoVision 分配次数和部分跨平台路径等剩余失败仍未全部解决，不能一概称为环境问题。没有修改系统权限，也没有将失败项改为跳过。已有 cgroup 根路径修复和新增夹具修正分别保留独立验证记录。

测试夹具修正已经单独成补丁；未解决项仍需继续定位，或形成明确的上游问题。当前没有提交 issue 或 PR，对外提交仍须单独授权，不能凭局部修正宣布全量宿主测试通过。

2026-10-28 的公开模块检查另修正了启用 Reflow 时暴露的 10 个测试失败项：固定插件数、固定启动配置、旧 TOML 诊断及缺失翻译。旧 workspace 能复现同一组失败，因此并非只有公开模块路径才会触发。修正后的全量又出现并发保存读取检查、脱敏耗时检查失败和窗口定位测试未返回；这些未解决项单独保留，不能继续把宿主状态概括为固定的 36 个失败。详见 [本次记录](PUBLIC-MODULE.md)。
