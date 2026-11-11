# 开发与验证

[返回 README](../README.md)

这里集中记录构建方法、自动测试结果和平台限制。版本使用说明见首页。

## 当前验证范围

2026-11-12，后续源码 `952bbba` 的[常规 CI](https://github.com/chatwithgod/reflow/actions/runs/43110438507)和[原生客户端 CI](https://github.com/chatwithgod/reflow/actions/runs/43110438307)在三个平台均通过。常规普通/race 各 106 项通过、4 项可选客户端检查跳过；专用原生普通/race 各 14 项、五个写文件场景及 Pi 模拟探针各 4 项通过。

托管 Windows 改用官方 `elevated` 沙箱后，原来的五项写文件失败已解决，文件越界拒绝、离线账号身份及清理检查通过。**该沙箱仍能连接本机回环端口，这是明确保留的网络限制；本轮通过的是文件集成验收，不是完整网络隔离验收。** 本机默认 MXC 保持不变，原始用例和断言保留，原生任务并发 1，真实模型调用 0。详见[Windows 修复与验收](WINDOWS-NATIVE-CI-2026-11-12.md)。

### 已发布构件的历史验证

2026-11-12 发布的两类包均固定到提交 `b0543cf`。19 个附件已全部匿名下载，逐字节和 SHA256 核对一致；两轮标签 CI 已结束。

| 项目 | 已验证范围 |
| --- | --- |
| 独立版常规回归 | Windows、Ubuntu、macOS 的普通/race 各 97 通过、4 跳过；vet、fuzz 等检查通过 |
| 独立版原生客户端 | Windows amd64、Linux amd64、macOS arm64 的协议/插件/Pi 普通及 race 各 14 项通过；三个平台的发布程序与发布前原生 CI 程序一致 |
| 原生客户端写文件 | 发布当时 Ubuntu/macOS 的五个场景通过，托管 Windows 五个场景失败；后续源码 CI 的修复结果见上方，历史标签结果不回写 |
| 独立版其余架构 | Linux arm64、macOS amd64 已交叉编译并检查包内容，未完成原生运行验收 |
| CPA 五平台 | 原生构建、普通/race/vet/fuzz、打包校验及打包前后各 46 个 ABI 模拟场景通过；公开 Windows 包的同一动态库再次通过 46 个 ABI 场景 |

标签 CI：[dev.6 常规](https://github.com/chatwithgod/reflow/actions/runs/43090980485)、[dev.6 原生客户端](https://github.com/chatwithgod/reflow/actions/runs/43090980692)、[dev.6 CPA 五平台](https://github.com/chatwithgod/reflow/actions/runs/43090980576)；[0.1.4 常规](https://github.com/chatwithgod/reflow/actions/runs/43092668100)、[0.1.4 原生客户端](https://github.com/chatwithgod/reflow/actions/runs/43092668196)、[0.1.4 CPA 五平台](https://github.com/chatwithgod/reflow/actions/runs/43092668105)。

本次发布验证没有真实模型调用。旧独立版 dev.5 曾完成 Windows 原生登录和 Desktop 真实续接，dot 本机读取也有独立记录；这些历史结果不会自动覆盖新构件。Pi 按模拟范围验收，Magpie 的固定宿主证据与限制见其接入说明。没有 Windows 代码签名、macOS 签名或公证，也没有质量收益结论。

[原生登录历史验收](NATIVE-LOGIN-ACCEPTANCE.md) · [Desktop 续接](DESKTOP-CONTINUATION-2026-11-05.md) · [Desktop/dot](DESKTOP-DOT-2026-11-05-FOLLOWUP.md) · [兼容性](COMPATIBILITY.md) · [评测](EVALUATION.md)

## 开发与构建

CI 使用 Go 1.26.8。独立程序可从源码构建：

```sh
git clone https://github.com/chatwithgod/reflow.git
cd reflow
go build ./cmd/reflow
go test ./...
go test -race ./...
go vet ./...
```

CPA 在 `adapters/cpa` 中使用独立 Go 模块；根目录测试不覆盖它，需另行运行：

```sh
cd adapters/cpa
go test ./...
go test -race ./...
go vet ./...
```

CPA 构建还需要 C 编译器和原生 ABI 检查。两类程序都需要完整仓库中的共用 `core/`。独立包不包含 CPA SDK 或动态库，CPA 的 SDK 依赖留在自己的模块内。

PowerShell 可用 `scripts/build.ps1 -AllPlatforms -WithCodexPlugin` 生成独立程序与 Codex 插件包；需要 Python，产物按版本和时间戳另存。CPA 的五平台构建入口及源码指纹规则见[开发说明](CPA-INTEGRATION.md)。
