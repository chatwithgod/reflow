# Magpie Windows 测试夹具修正

2026-10-27，在独立 worktree 中给 `7833faf3` 追加提交 `e69f473d157577054ccd48ee1cf77d7e3704ac78`。只改三个 `_test.go` 文件，没有修改宿主运行逻辑、真实账号或生产配置。补丁为 [windows-test-fixtures.patch](patches/windows-test-fixtures.patch)，尚未推送或提交 PR。

## 修正内容

Codex 钥匙串测试模拟 macOS，却遗漏了 `secret_auth_storage=false`。在 Windows 上，生产代码按原有默认值进入加密存储路径，绕过已安装的假钥匙串。现在在合成配置中明确选择钥匙串路径，覆盖 provider 和 agent 两侧，以及回退、不可读取存储和登录状态等相邻场景；生产默认值保持原样。

回退测试原先可能没有访问假钥匙串就通过。新增断言确认确实访问过设置为拒绝读取的假钥匙串，避免把别的文件回退路径误当作该场景通过。

GUI 的 `sandboxHome` 现在把 `APPDATA`、`LOCALAPPDATA` 指向临时 home 下的 Roaming、Local 目录。原先清空这两个变量会使 Windows 的 `os.UserConfigDir()` 失败，影响 Lody、AionUi 和不可读导入状态三个场景。

## 实际检查

| 检查 | 结果 |
| --- | --- |
| 初始定向检查，修改前 | 2 通过、1 跳过、12 失败 |
| 相同定向检查，修改后 | 14 通过、1 跳过、0 失败；race 同样通过 |
| 另外两项 GUI 导入检查 | race：2 通过、0 跳过、0 失败 |
| 仅移除钥匙串夹具设置 | 回退测试真实失败：`fallback did not ask the refusing keychain` |
| 仅恢复旧 APPDATA 设置 | 三项 GUI 测试全部失败：`%AppData% is not defined` |
| 修改版全量 `nogui` | 12,204 通过、615 跳过、36 失败 |
| Windows 普通、Linux `nogui` vet/build | 全部通过；Linux 仅交叉检查 |
| Windows `nogui reflow` 构建 | 通过 |
| Reflow dev.4 桥接与默认关闭检查 | race：7 个通过项、0 跳过、0 失败 |

定向检查中的一个跳过项是原有符号链接权限测试，没有改动其跳过规则。反向检查之后恢复了修正，后续运行的源码散列与正向检查一致。构建不表示 GUI、Linux 或 macOS 原生运行通过。

此前相同隔离方式下的选定失败复查有 50 个失败项。本轮全量结果中，其中 14 项明确变为通过，剩余 36 项全部来自旧失败集合。最早的全量记录使用了不同隔离环境，不能将当时 60 项到本轮 36 项的全部差额都归因于这个补丁。全量宿主测试仍未通过，剩余问题仍需继续定位或形成具体上游问题。

## 来源与复现

补丁清单现含四份补丁。按顺序应用到固定基准 `a1174674da9d1435443e95ffac7d0300ce8b59d6` 后，22 个改动文件的 Git blob 与已测 worktree 一致；旧三份补丁的散列未变。本次夹具补丁只增加测试修正，可以单独审阅。

```sh
python scripts/check-magpie.py --magpie /absolute/path/to/patched-magpie --go /absolute/path/to/go --phase suite --race --packages ./internal/provider ./internal/agent ./internal/gui --run '^Test(CodexSignedInInKeychain|CodexKeychain.*|CodexStoreNotReadIsLeftAlone|CodexSignInKnown|CodexSignInInKeychain|LodyImportHandoff|AionUiImportRow|ImportStatusUnreadableIsUnknown)$'
```

Windows 上的 race 检查可用 `--compiler /absolute/path/to/gcc.exe` 指定已安装的 C 编译器。脚本默认隔离用户目录、固定缓存并关闭 Go 依赖下载，所有账号与上游均为合成数据。

另行读取了当时上游 `main` 的固定提交 `8ab4fd6120ad46f16e54d609072e4d01c3772818`：三处夹具仍保留相同设置，见 [provider](https://github.com/yetone/magpie/blob/8ab4fd6120ad46f16e54d609072e4d01c3772818/internal/provider/codex_store_test.go)、[agent](https://github.com/yetone/magpie/blob/8ab4fd6120ad46f16e54d609072e4d01c3772818/internal/agent/codex_keychain_test.go)、[GUI](https://github.com/yetone/magpie/blob/8ab4fd6120ad46f16e54d609072e4d01c3772818/internal/gui/backup_test.go)。这只是源码核对；上述运行仍以本项目固定基准加补丁为准，没有在最新上游提交重跑测试。

报告路径、命令、完整失败名称集合及散列见 [机器可读证据](../../docs/evidence/magpie-windows-fixtures-2026-10-27.json)。真实续接会话、Desktop/dot、公开发布和上游接受状态不因本轮离线检查而完成。
