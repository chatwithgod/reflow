# Magpie 外置接入：固定源码的模拟验收

2026-10-31，在 Windows 上验证了独立 Reflow 进程接到未修改的 Magpie `bca0d6d69a806ae941bf9a5a6fafe4c7e03322b9` 前面。Magpie 在 Go 集成夹具中运行实际 `Server.Front()`、路由、账号选择和 WebSocket 入口；模型端是本地模拟 HTTP 服务。此方案不需要 `gwexec` 或 Reflow 桥接补丁。

```text
协议测试客户端 → 独立 Reflow 进程 → 原版 Magpie 入口 → 模拟 ChatGPT 后端
```

这符合维护者在 [#2118](https://github.com/yetone/magpie/issues/2118#issuecomment-6216502171) 中把后续推理循环留在客户端一侧的方向；[讨论 #4497](https://github.com/yetone/magpie/issues/4497)仍没有接受结论。这里记录本地可复现行为，不代表上游承诺接口稳定。

## 使用前提

下例的 `8000` 是示例端口，应换成已有 Magpie 网关的地址。需要包含本次修改的 Reflow 源码构件；当前没有对应的二进制 Release。

```sh
reflow --listen 127.0.0.1:18516 \
  --upstream http://127.0.0.1:8000/backend-api/codex \
  --upstream-profile magpie --max-continue 1
```

客户端使用 Reflow 的 `/responses` 入口，继续提供 Magpie 要求的鉴权。客户端必须能设置以下请求头，WebSocket 在握手时设置：

- `X-Magpie-Account`：明确指定已有账号，例如夹具中的 `spare@example.com`。它不是鉴权凭据；本方案没有新增登录方式。
- `session_id`：保持同一会话的稳定标识。

模型也要明确指定，不使用会更换模型的组。测试的原生路径使用 `gpt-5.5`；托管路径把上游改为 `/v1`，使用 `codex/gpt-5.5`。这些是模拟测试中的选择，实际使用仍取决于网关已有账号和模型。未指定账号、模型组回退、客户端不能设置上述头部的情况，不在本次通过范围内。

Reflow 的 `codex-config` 命令没有新增 Magpie 账号配置功能。本轮没有替用户安装或接入生产客户端。

## 为什么需要单独的兼容选项

默认 `standard` 模式保持标准 WebSocket 请求格式。官方文档说明 WebSocket 请求不使用 HTTP 的 `stream` 字段，见 [WebSocket mode](https://developers.openai.com/api/docs/guides/websocket-mode)。

固定 Magpie 源码有两处需要适配：HTTP 在 `store:false` 时不保存可用的父响应历史；WebSocket 将帧重新交给 HTTP 路由，却不自动补 `stream:true`。`magpie` 选项因此让 HTTP 使用 Reflow 已知的完整内存历史，并给发往 Magpie 的 WebSocket 请求补上流式标记。未知父响应仍不拼造历史；标准模式不改变。

该选项要求显式传入 `--upstream`；省略地址或传入未知选项值时，程序在监听前报错。它不改变续接阈值、账号认证、模型选择或轮次预算。

本次也补上原生 `response.interrupt` 的响应 ID 转换：客户端可见 ID 对应到正在运行的隐藏轮次，确认帧映回客户端 ID，终态保留 `interrupted` 并清空部分输出。拒绝取消的确认不会把尚在运行的回合误判为取消。既有 `response.cancel` 检查继续通过。协议依据来自固定 Magpie 源码和本地 Codex `0.164.0` 源码；这不是本轮真实 Codex 客户端验收。

## 本次结果

| 检查 | 结果与边界 |
| --- | --- |
| 原生 HTTP、托管 HTTP、原生下游 WebSocket | 三种路径均为 3 次模拟后端请求、1 次续接、1 次固定本地工具执行和结果回传；账号、凭据与模型不变；舍弃的工具不执行，最终历史不重复 |
| WebSocket 预热 | 不到模型端；随后续接、工具回传通过 |
| 未知账号 | 404，模型端请求数为 0 |
| 续接时指定账号不可用 | 停止并返回未完成；不切到备用账号，不交出舍弃轮次的工具 |
| HTTP 取消、WebSocket 中断 | 隐藏请求结束，不泄漏工具；后续请求完成，WebSocket 保持同一连接 |
| 普通与 race | 各 8 个通过项，即 7 个场景加父测试；0 跳过、0 失败。race 同时构建 Reflow 子进程和 Magpie 夹具，检查子进程的固定竞争标记 |
| 去掉账号指定的故障对照 | 抓到隐藏请求切到另一合成账号；失败符合预期 |
| 改回标准模式的对照 | HTTP 缺失父响应，WebSocket 未正常完成；两个场景都失败，不能用标准模式冒充兼容模式 |
| 原始 Reflow 取消代码对照 | 相同回归在原代码上抓到中断终态和隐藏响应 ID 的问题；本次修复后通过 |
| Reflow 完整源码 | 隔离副本普通/race 各 90 通过、4 个未提供客户端的检查跳过，vet 通过 |

全部检查串行，使用合成账号、临时用户目录和本地模拟上游，真实模型调用为 0。Magpie 受版本控制的文件、模块锁文件和受测二进制未变；临时用户目录已清理。只保存数字、测试名称、固定错误标记与散列，不保存凭据或请求/回答正文。最初的联调失败和一次对照汇总断言写错的失败也保留在[证据文件](../../docs/evidence/magpie-external-chain-2026-10-31.json)中。

本次没有使用原生 Codex/Pi 客户端，没有测试 Magpie 到模型端的 WebSocket、真实账号刷新、生产鉴权配置、其他操作系统、原生窗口或完整 Magpie 测试集。历史嵌入式适配的全量中断状态保持独立，不能据此改成通过。

## 重现

准备 Go 1.26.8、Python 3 和隔离的 Magpie checkout，固定到上述提交。先把两个项目的模块下载到 Reflow 目录的 `.tools/gopath/pkg/mod`；运行入口使用该固定缓存及 `GOPROXY=off`，不会自动联网下载依赖。Windows race 另需可用的 C 编译器。

```sh
python scripts/check-magpie-external.py \
  --magpie /absolute/path/to/isolated-magpie \
  --go /absolute/path/to/go \
  --compiler /absolute/path/to/gcc
```

入口拒绝其他提交、已修改的 Magpie 文件或无关未跟踪文件；只添加本仓库提供的专用测试夹具。默认依次执行普通、race、账号故障和标准模式对照，结果写入 `build/magpie-external-ci/`。故障对照里的非零退出码是预期结果，入口自身仍要求全部断言满足后才返回成功。这项完整链路检查尚未接入自动 CI。
