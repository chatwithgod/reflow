# 整合分支首次推送与 CI

经用户授权，四个整合提交及 CPA 历史已推送到 `chatwithgod/reflow` 的 `integrate/cpa-shared-core` 分支，固定头提交为 `b5e3be6d980146d01d141a6b9d18112f28352e56`。推送前后远程 `main` 均为 `6d32acd`；没有推标签、合入 main、发布 Release 或迁移商店入口。

## 已完成的检查

| 工作流 / 平台 | 结果 |
| --- | --- |
| 常规回归 / Ubuntu、Windows、macOS | 全部通过；各普通/race 97 通过、4 跳过，vet/fuzz 和离线自检通过 |
| 原生客户端 / Ubuntu | 普通/race 各 14 通过，五个写入场景通过，Pi 探针普通/race 各 4 通过 |
| 原生客户端 / macOS | 同上，全部通过 |
| 原生客户端 / 托管 Windows | 普通/race 各 14 通过；五个写入场景失败，后续 Pi 探针未执行 |
| CPA 五平台打包 | 没有创建运行记录，不能计为通过 |

运行链接：[常规回归](https://github.com/chatwithgod/reflow/actions/runs/43072324939)、[原生客户端](https://github.com/chatwithgod/reflow/actions/runs/43072324973)。三份原生客户端数字摘要已下载核对，来源提交一致，真实模型调用均为 0。完整数字、来源和摘要散列见[证据](evidence/cpa-integration-ci-2026-11-12.json)。

Windows 的五个子场景及父测试合计 6 个失败事件。直连和经 Reflow 的写入都失败；固定诊断标记为 MXC 不可用、文件系统错误，直接沙箱命令和文件系统探针也未通过，与此前托管 Windows 限制一致。保留原断言，没有把这些失败改成跳过；不将整条原生客户端工作流标为通过。

## CPA 触发缺口

远程 `.github/workflows/cpa-packages.yml` 的内容与获授权提交完全一致，但按本次提交查询仅出现上述两条工作流；CPA 工作流未出现在列表中，按文件名查询返回 404，没有可供分析的失败任务。首次未触发的原因尚未确认。

GitHub 的路径过滤对新分支与已有分支采用不同的比较基准，见[官方差异比较说明](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#git-diff-comparisons)。新工作流尚未进入默认分支、也没有首次运行记录，因此没有尝试用手动 dispatch 代替本次授权的自动检查；相关条件见[官方触发说明](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_dispatch)。这些资料不构成首次跳过原因已经证实的结论。

本地补充只把根 `.gitattributes` 加入 CPA 的 push / pull_request 触发路径，因为它会影响共用源码的字节与打包指纹。下一次推送到已存在分支时，工作流文件自身也会出现在变更中，用于验证是否能够触发。YAML、五平台目标、只读权限与原生任务并发 1 检查通过；运行代码和已验证构件未变。此补充尚未推送，CPA 的五平台验收仍待完成。
