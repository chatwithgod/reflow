# 开发与维护

[返回使用说明](README.md) · [配置说明](docs/CONFIGURATION.md)

## 维护原则

1. 用最小、脱敏的合成事件复现问题，区分客户端 → CPA、宿主 → 插件、插件 → 客户端三段。
2. 改动解码、折叠、终止事件、用量或格式声明时，新增对应回归测试。
3. 固定 SDK；涉及插件接口、HTTP/WS 路径或新增故障时，选择相关宿主和协议做回归。CPA 的普通版本更新不要求机械重跑全套测试；不把 HTTP 回退计为 WS 成功。
4. Windows 开发命令见下文；`scripts/native_smoke.py` 通过真实 DLL 调用 C ABI，但它不是 CPA 宿主集成测试。
5. 测试记录必须写明日期、版本、场景、实际传输和证据等级；不要上传账号、请求原文、加密推理或生产数据库。
6. 发布是单独步骤，按 `docs/RELEASING.md` 执行。故障版本不移动旧标签，用新的补丁版本修复。

## 本地开发：Windows x64

需要 Python 3.11+。以下命令下载并校验项目内的 Go / LLVM-MinGW 工具，工具和缓存放在 `.tools/`，不修改系统 PATH：

```powershell
python scripts/bootstrap_windows_tools.py
. ./scripts/dev_env.ps1
go test ./... -count=1
go test ./... -race -count=1
go vet ./...
go test -run '^$' -fuzz '^FuzzDecoderChunkBoundaries$' -fuzztime=15s -parallel=2
./scripts/build_windows.ps1
python scripts/native_smoke.py build/codexreflow.dll --report build/native-smoke.json
```

开发 DLL 位于 `build/codexreflow.dll`。构建和原生测试使用合成宿主，不安装生产插件，也不调用真实模型。已有构件和报告应保留，重复验证使用新的输出位置。

## 隔离 CPA 集成测试

已有 CPA `8.0.13` 可执行文件时，可以运行：

```powershell
python scripts/isolated_cpa_smoke.py <CPA可执行文件> build/codexreflow.dll --report build/isolated-cpa-smoke.json
python scripts/isolated_cpa_smoke.py <CPA可执行文件> build/codexreflow.dll --auto-models --report build/isolated-auto-models.json
python scripts/ws_incremental_smoke.py --cpa <CPA可执行文件> --dll build/codexreflow.dll --native-folds --report build/ws-incremental.json
python scripts/ws_incremental_fold_smoke.py --cpa <CPA可执行文件> --dll build/codexreflow.dll --report build/ws-incremental-fold.json
python scripts/ws_prewarm_smoke.py --cpa <CPA可执行文件> --dll <待验收动态库> --cpa-version 8.0.38 --report build/ws-prewarm.json
```

使用其他宿主版本时，明确追加对应的 `--cpa-version`，例如 `--cpa-version 8.0.16`。测试会核对实际版本；填写参数本身不代表该版本已经通过验证。

测试启动独立端口、空账号目录和本地模拟上游，不读取生产账号或配置。覆盖 HTTP/SSE、WebSocket、续接、工具事件、上下文衔接及异常终止。模拟测试不替代真实客户端的完整体验验证。

预热回归会分别发送空数组和非空输入的 `generate: false` 请求，检查预热原样通过，再在同一条 WebSocket 上生成下一轮回答。它同时核对上下游均使用 WebSocket，避免把 HTTP 回退算作预热通过。

SDK 固定为 CPA `v8.0.13`。五个平台的原生构建、包内动态库验证和构件汇总方法见[五平台构建说明](docs/MULTIPLATFORM.md)。

## 仓库与发布

开发和修复使用工作分支；`origin` 指向 [LaoPiLao/cpa-plugin-codexreflow](https://github.com/LaoPiLao/cpa-plugin-codexreflow)，
`upstream` 保留 [uf-hy/cpa-plugin-codexcomp](https://github.com/uf-hy/cpa-plugin-codexcomp)。保留上游历史和本地
`v0.1.7` 来源标签，不把继承的标签当作新插件的正式版本推送；代码推送不等于 Release 或商店提交授权。

维护目录的本地 `v0.1.0` 同样继承自 CodexComp，保留不动；Reflow 的远程 `v0.1.0` 指向
实际被测源码 `875864934cf82dbba90a7f85985f36ebd3a256d1`。不要整批推送/强制同步标签；
使用明确源码 SHA 或新检出验证版本，详见 [发布记录](docs/RELEASE-2026-10-08-0.1.0.md)。
