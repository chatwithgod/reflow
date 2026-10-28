# Magpie 脱敏耗时检查的修正

2026-10-29，第七份 `masking-duration-tests.patch` 修正了把合法零耗时当成失败的测试断言，并补充确定性的计时回归。它只修改两个测试文件，不改变生产计时、脱敏或记账逻辑；按 [清单](patches/manifest.json) 接在前六份补丁后应用。

此前全量中的 `TestMaskedRecordKeepsSentAndBack` 要求记录耗时大于 0。诊断使用临时 Go overlay，只输出耗时数字，不改工作区源码：50 次离线请求中，34 次原始耗时已经是 0 纳秒；50 次从产生值到写入记录均相同。这说明这些样本没有在传递时丢失计时，原断言不能接受时钟未前进的情况。记录使用整数微秒，亚微秒值也会截断为 0。

修正后保留回复恢复次数、发送内容检查，并拒绝负耗时，允许合法的零值。新增 `TestMaskingDurationPreserved` 使用 Go 的虚拟时钟，分别验证 JSON 和文本两条路径的 0、500 纳秒、37 微秒，从测量一直核对到记录中的整数微秒。不用忙等或真实睡眠保证耗时大于某个阈值。

已经核对的结果见 [机器可读证据](../../docs/evidence/magpie-masking-time-2026-10-29.json)：

- 强制提供零耗时时，旧断言失败，修正后的断言通过；回复恢复和发送内容检查仍执行。
- 分别人为抹掉 JSON 路径计时、文本路径计时、最终记录值，新增测试均出现真实失败。
- 修正后另做 50 次数字诊断，全部通过，其中 36 次原始耗时为 0，50 次数值均完整保留。
- 原始模块和公开 Reflow 模块下，定向 race 各 8 项通过；公开模块下再跑 20 轮 race，共 160 项通过。
- Windows 普通构建、Windows/Linux 可选构建和对应全量 vet 通过。Linux 为交叉检查，未在 Linux 上执行测试。
- 七份补丁重建后的 32 个变更文件与测试源码一致，原六份补丁字节未变。

在 [公开模块构建](PUBLIC-MODULE.md) 所述的临时用户目录、固定缓存和 `GOWORK=off` 环境下，定向重复检查可运行：

```powershell
go test "-modfile=go.reflow.mod" -mod=readonly -tags "nogui reflow" -race -count=20 -timeout=3m -run '^Test(MaskingDurationPreserved|MaskedRecordKeepsSentAndBack)$' ./internal/gateway
```

反向检查只在临时副本或 Go overlay 中进行，结束后恢复原文件：

| 注入方式 | 检查及预期 |
| --- | --- |
| JSON 测量赋值后再设 `o.h.took = 0`，同时恢复旧的 `r.Took <= 0` 断言 | `TestMaskedRecordKeepsSentAndBack` 失败；同一零值下恢复新断言后通过 |
| 仅在 JSON 测量赋值后设 `o.h.took = 0` | `TestMaskingDurationPreserved/json` 的非零纳秒场景失败 |
| 仅在文本测量赋值后设 `o.h.took = 0` | `TestMaskingDurationPreserved/text` 的非零纳秒场景失败 |
| 在记录赋值后设 `rec.Took = 0` | 两条路径的 37 微秒场景失败 |

完整宿主本次为 12,219 项通过、615 项跳过、36 项失败，没有超时或未结束测试。此前的脱敏耗时失败项已通过，没有新增失败；其余 36 项仍未解决。并发保存检查本次也通过，但没有修改，仍不算作已修复。

本次修正不构成真实账号、原生窗口、Desktop/dot 或整个 Magpie 的验收；没有真实模型调用或生产配置变更。临时诊断和故障注入均未进入提交源码。
