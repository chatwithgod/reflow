# CodexReflow 配置说明

[返回使用说明](../README.md)

全新安装后，在 CPA 的插件界面启用 CodexReflow 即可。只有需要调整模型范围或续接次数时，才需要修改以下选项。

本文中的 YAML 片段对应 **CodexReflow 自己的配置**，不是整份 CPA 配置。修改前保留原配置，并等正在生成的回答结束。

## 默认行为

| 选项 | 默认值 | 作用 |
|---|---|---|
| `model_mode` | `auto` | 自动按名称匹配 GPT-5 及以上的标准文本模型 |
| `models` | 不填写 | 手动模式下的模型名单；新配置可以省略 |
| `exclude_models` | 空 | 优先排除的模型，两种模式都生效 |
| `max_continue` | `3` | 最多追加 3 轮，总计最多 4 轮；设为 `0` 可禁止追加请求 |
| `max_tier_n` | `6` | 允许续接的 `518n-2` 数字档位上限；设为 `0` 表示不限制档位 |
| `marker_text` | `Continue thinking...` | 续接时插入的提示文字 |
| `debug_log` | `false` | 是否开启额外调试日志；基本逐轮诊断无需打开它 |
| `min_reasoning_tokens` | 不启用 | 实验性选项，不建议为了增加 token 数而开启 |

默认示意如下，无需为了采用默认值而手动填写：

```yaml
model_mode: auto
max_continue: 3
max_tier_n: 6
marker_text: "Continue thinking..."
debug_log: false
```

启用插件、匹配模型和真正追加请求是三件事。追加请求还需要满足续接条件、具备上游返回的加密推理状态，并且没有用完续接次数。

## 自动匹配哪些模型？

`auto` 按请求名称匹配小写的 GPT-5 及以上标准文本系列，例如：

- `gpt-5.6-sol`
- `gpt-6-astra`
- `gpt-6-sol`
- `gpt-6-luna`
- 带 CPA 路由前缀或末尾推理后缀的名称，如 `lab/gpt-6-sol(max)`

名称中的 `image`、`audio`、`realtime`、`transcribe`、`transcription`、`tts`、`video`、`embedding`、`embeddings`、`moderation` 词段会被排除。

这是名称规则，不是模型能力检测，也不会读取或同步 CPA 的模型目录。插件不会注册新模型；模型是否可用、别名指向哪里，仍由 CPA 决定。名称像 GPT 的别名也不保证背后一定是 GPT。

## 常用调整

### 减少额外请求

```yaml
max_continue: 1
```

最多追加一次。设置为 `0` 会禁止续接，但不会直接停用整个插件。续接可能增加费用和延迟，也可能没有新增思考 token。

### 排除一个模型

```yaml
model_mode: auto
exclude_models:
  - gpt-6-luna
```

裸模型名也会排除带路由前缀或推理后缀的形式；写明前缀的排除项只影响该路由。不支持通配符，也不会解析任意自定义别名。

### 只处理指定模型或别名

```yaml
model_mode: manual
models:
  - my-coder
  - lab/gpt-6-sol(max)
```

手动模式按原始请求中的完整 ID 精确匹配，名单会替换原名单。空名单表示不处理任何模型。`exclude_models` 的优先级仍高于这份名单。

## 从旧配置升级

升级不会擅自扩大旧配置的模型范围：

| 配置情况 | 实际行为 |
|---|---|
| 没有 `model_mode`，也没有 `models` | 自动模式 |
| 只有旧的非空 `models` 名单 | 保留手动精确匹配 |
| 只有旧的 `models: []` 或 `models: null` | 保留历史三个 ID：`gpt-5.5`、`gpt-5.6-luna`、`gpt-5.6-terra` |
| 明确设置 `model_mode: auto` | 使用自动规则，忽略保留的 `models` 名单 |
| 明确设置 `model_mode: manual` | 仅处理 `models` 中的 ID；缺省或空名单不处理任何模型 |

想从旧名单切换到自动匹配，只需明确设置 `model_mode: auto`。宿主界面如何展示字段取决于 CPA / ECPA 版本。

## 进一步排查

续接条件、WebSocket 上下文限制和缓存说明见[兼容性文档](COMPATIBILITY.md)。逐轮用量、停止原因及脱敏日志工具见[诊断说明](DIAGNOSTICS.md)。
