# Reflow 的 Magpie 适配

这是开发中的嵌入式适配，固定针对 `yetone/magpie` 的 `a1174674da9d1435443e95ffac7d0300ce8b59d6`，在独立分支验证，尚未推送或发布。

## 接入方式

Magpie 现有 JS 中间件有 250ms / 50ms 的执行时限，Bun 的异步 `onResponse` 只能观察已经交给客户端的回复。续接需要额外的 Go 执行扩展 `gwexec`。

本适配通过内存管道和宿主回调，复用独立 Reflow 的事件合并、缓存和取消处理，没有新增监听端口。Magpie 继续负责账号、目标地址、签名、限流和请求取消。回调只允许修改请求正文，不能切换已选模型或上游地址；交给适配器的账号标识是只在内存使用的散列。

这不是对 Go 插件的安全沙箱。它是同一进程中可信代码的调用约定，不向 JS 或 Bun 插件开放原始账号凭证。

## 支持范围

- 原生 Codex 直通，以及流式 Responses 到 Responses 的透传路由进入执行扩展。
- 跨协议翻译、非流式、compact 和其他 API 继续走原有流程。
- 每个客户端请求最多执行 8 次上游调用，包含第一轮。下一轮开始前必须关闭前一轮响应。扩展发生错误时不会自行重放第一轮；Magpie 原有的错误处理和候选回退仍在宿主层。
- Magpie 可能每轮新建上游 WebSocket。缓存中已知父响应的恢复使用完整历史重放，不依赖前一条连接保存的响应 ID。
- 超过 Reflow 16 MiB 请求上限的正文交还宿主原样处理，不改变 Magpie 原有的请求大小限制。

普通 `response.usage` 仍表示一个可见上下文。Reflow 把多轮实际消耗写入 `metadata.proxy_billed_usage`，Magpie 的透传用量读取器用它记账。缺失、非法或会降低原有任一计费项的元数据会回退到普通 `usage`；客户端收到的流不因此改写。

## 开发构建

补丁位于 [patches](patches/manifest.json)，按清单顺序应用：`00-cgroup-root.patch` 修复上游 Windows 测试中的路径循环，`host-execution.patch` 提供宿主执行扩展，`reflow-bridge.patch` 提供可选适配。当前依赖两份本地源码，通过 `go.work` 关联，尚无可引用的公开 Go 模块版本。

第四份 `windows-test-fixtures.patch` 只修正 Windows 上的测试夹具，不改变运行逻辑。其正反检查及剩余失败见 [独立记录](WINDOWS-FIXTURES.md)。

可选插件使用 `reflow` 构建标签，开发验收同时使用 `nogui`。`maxContinue` 默认是 `0`，只有显式设置为 `1` 到 `7` 才注册续接处理器。修改设置后按 Magpie 当前生命周期停用并重新启用插件。以下仅是隔离开发配置示例：

```yaml
plugins:
  - id: reflow
    enabled: true
    config:
      maxContinue: 3
```

## 验证状态

合成凭证和模拟上游下，原生 HTTP、zstd、上游 WebSocket、Magpie 管理的 Responses API key 透传已完成续接、中间工具隔离和下一轮工具结果回传。测试还核对了完整历史重放、多轮用量和翻译路由旁路。

联调修复了 Magpie 将 WebSocket 帧转成 SSE 时未标明 `Content-Type` 的问题。适配与取消回归已通过 race；完整宿主测试运行过但未通过，对原失败项的复查在干净上游和修改版得到相同失败集合。详情见 [验证记录](VERIFICATION.md)。真实账号验收尚未进行，上述结果不代表回答质量提高，也不代表已部署到生产 Magpie。

2026-10-27 补充：加入测试夹具修正后，14 个原失败项通过，全量仍有 36 个失败项。使用 Reflow dev.4 的桥接与默认关闭检查再次通过 race，共 7 个通过项。历史记录没有被覆盖，见 [本轮记录](WINDOWS-FIXTURES.md)。
