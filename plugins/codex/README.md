# Codex 原生插件使用说明（开发版）

该插件包含 Reflow 二进制与 stdio MCP 工具：`status`、`preview_codex_config`、`connect_codex`、`restore_codex_config`，用于接入配置与状态诊断。真正的推理续接由本地代理服务完成。

插件尚未公开发布，仅供本地开发测试。注册解压后的本地市场目录并安装：

```sh
codex plugin marketplace add /absolute/path/to/marketplace --json
codex plugin add reflow@reflow-local --json
```

## 运行与接入

1. 安装插件不会自动启动代理。先运行包内 `bin/reflow`（Windows 为 `bin/reflow.exe`），默认监听 `127.0.0.1:18516`。
2. 通过插件调用 `preview_codex_config`，核对即将修改的配置项。
3. 用户明确要求接入时，调用 `connect_codex`。它只修改用户级 `config.toml` 顶层的 `openai_base_url`，将该项原值记录在 `reflow-routing.json`，不复制整份配置，也不读取 `auth.json`。若本地 Reflow 服务未就绪，或明确选择了其他 `model_provider`，工具会拒绝写入。
4. 只有接入或还原实际改变了配置文件时，才需要重启 Codex 使其生效。

使用其他本地端口时，为工具提供 `endpoint` 参数。CLI 也可预览或修改：

```sh
reflow codex-config --action preview --endpoint http://127.0.0.1:18516
reflow codex-config --action connect --endpoint http://127.0.0.1:18516
reflow codex-config --action restore
```

当前 Codex 会过滤 stdio MCP 的 `CODEX_HOME`。插件从宿主提供的 `PLUGIN_ROOT` 所在缓存路径定位所属配置目录；遇到不认识的目录结构会报错，避免改动另一份配置。命令行可显式传入 `--codex-home` 指定目录。

## 还原

停止代理前，调用 `restore_codex_config`。还原会保留其他配置项的后续修改；若路由已被手动改动，工具会拒绝覆盖。实际还原后重启 Codex，再停止服务；重复调用没有改动时不会要求重启。

安装插件、服务健康、路由生效是不同的状态。`status` 不调用模型，也不证明真实模型请求已经通过 Reflow。真实账号、Desktop/dot 和质量评测仍需单独验收。

开发验收使用真实 Codex CLI、本地市场、合成登录和模拟上游，已验证安装缓存、4 个 stdio 工具，以及会话经 Code Mode 调用 `status`。测试还核对返回的配置目录属于安装该插件的隔离环境。
