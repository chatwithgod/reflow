# Pi 公共 OAuth 只读探针（可选）

用户已明确以模拟测试作为 Pi 的验收条件，本项目的 Pi 接入已按该范围通过，见[验收记录](evidence/pi-simulated-acceptance-2026-10-30.json)。不再安排首次登录或真实调用。以下探针保留供未来确有需要时诊断，不是当前 goal 的待办。

`evaluations/pi_probe.py` 用于 Pi 1.4.0 的新 `openai` 入口。默认只生成方案，不读取登录、不调用模型。单次实际执行最多 180 秒、并发 1、每轮最多续接一次；只允许内置 `read` 读取临时生成的 `probe.txt` 一次，拒绝其他工具、路径或第二次读取。

```sh
python evaluations/pi_probe.py --reflow /absolute/path/reflow
```

必须使用 Pi 自己通过 OpenAI 的 ChatGPT 登录获得的 `openai` OAuth 记录。旧 Codex `auth.json`、API key、缺少套餐使用权限、没有已签发客户端 ID 或即将过期的记录都会被拒绝。新的公共流程需要该客户端的授权，参见[官方注册与登录](https://developers.openai.com/siwc/token-sharing-open-source/sign-in)。本探针不实现或替换登录流程。

取得相应真实测试授权且 Pi 已登录后，显式执行：

```sh
python evaluations/pi_probe.py --run-live --auth-file /absolute/path/pi/auth.json --reflow /absolute/path/reflow
```

当前默认模型为 `gpt-6.1-sol/high`。先最多请求一次官方账号模型目录，只有确认该模型可用才开始推理；目录正文不写入报告。这次元数据请求与推理请求分开计数。公共 OAuth 使用 `https://api.openai.com/v1/responses`，不是旧 `backend-api` 路径，参见[官方推理说明](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference)。

执行时创建独立的 Pi 配置和工作区，仅复制新鲜 access token、已签发客户端 ID、scope 与到期值；refresh token 留空。要求凭据剩余有效期覆盖整个超时窗口及刷新余量，不让探针轮换用户的可刷新会话。模型结束或失败后，临时登录、工作区和本次进程均清理。原始登录文件只做前后散列核对。

Pi 的代理层与 provider 层重试都显式设为 0，后台缓存预热和自动压缩关闭。限流、错误、工具越界会停止本次会话，不自动追加。新 API 入口目前只验收 SSE；浏览器登录、刷新、跨账号切换和 WebSocket 不包含在这个只读探针里。

报告只保留固定事件名、数字、散列及“文件读到/最终回答匹配”等布尔值。不保留模型正文、工具路径/输出、账号标识或凭据。Pi 的输入统计不包含缓存 token，报告另把输入和缓存相加后再与上游总量比较；不把这些数字换算为订阅费用。

通过基本工具往返检查要求：正常结束、恰好一次成功读取、返回内容匹配、固定文件未变、工具限制已生效、用量报告和事件探针完整、没有已观察到的上游错误。真实续接另列，未自然触发时不声称已验收 Pi 的真实续接。

离线运行方式见 `integration/pi_probe_test.go` 的 `pi_probe` 构建标签。模拟正常会话验证 3 次请求、1 次续接及匹配工具回传；429 和越界读取对照各只允许 1 次请求。打包客户端流水线串行执行普通/race 两组探针，已有 Codex 与 Pi 的其他检查继续保留。

本地的一次性[冻结方案](evidence/next-live-pi-public-plan-2026-10-30.json)曾核对源码、SDK 依赖、Node、Pi CLI 和已测 Reflow 构件散列，但没有执行真实账号测试。该文件按原散列保留为历史记录；其中的待登录状态已被后来的[模拟验收决定](evidence/pi-simulated-acceptance-2026-10-30.json)取代，不再据此发起登录或模型调用。
