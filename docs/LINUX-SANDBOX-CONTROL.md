# Ubuntu 原生写入：发行版沙箱依赖对照

状态：`cf500dd` 已公开并完成第二轮对照，软件包采集修正及依赖安装已在 Ubuntu 验证。严格模式的 AppArmor 加载失败，尚未运行修正后的原生写入检查。新增编译诊断和摘要修正已在本地准备，等待新授权。没有新增真实账号调用。

此前[第四轮宿主对照](NATIVE-CI.md)确认，Ubuntu runner 的独立 user namespace/UID 映射检查被拒绝，直接 Codex 沙箱命令也因 bubblewrap 权限失败。AppArmor 的全局 user namespace 限制值为 1。现有证据没有证明全部补丁失败都来自同一原因。

[OpenAI 官方说明](https://learn.chatgpt.com/docs/sandboxing?surface=app&translationFallback=zh-Hans)建议在 Linux 安装发行版 `bubblewrap`；Ubuntu 24.04 可能还需要加载发行版附带的 `bwrap-userns-restrict` 配置。[Codex 0.165.0 的启动代码](https://github.com/openai/codex/blob/rust-v0.165.0/codex-rs/linux-sandbox/src/launcher.rs)也优先选择系统 bwrap，并检查其支持的选项。此次候选对照依据这一路径，不修改 Reflow、Codex 二进制或原有五个写入场景。

## 准备的执行流程

单独的 [Linux 工作流](../.github/workflows/linux-sandbox-control.yml)只接受手动触发，确认开关默认为关闭。脚本还检查仓库、工作流名称、手动事件、GitHub 托管环境、Ubuntu 24.04 amd64 和非 root 用户。与原生客户端工作流共用串行队列，跨工作流也只运行一个原生客户端任务。

1. 在同一临时 runner 先运行原来的完整客户端检查。若已经全部通过，仅补查文件和网络边界，不安装软件或加载配置。
2. 只有普通/race 均通过、五个写入场景全部失败，并复现原先的 bubblewrap/UID 映射拒绝时，才继续尝试发行版依赖。其他失败直接停止。
3. 在该临时 runner 安装 `bubblewrap`、`apparmor-profiles`、`apparmor-utils`，记录安装前后的相关软件包版本与系统 bwrap 散列，再进行无账号对照。若安装软件包已解决直接启动问题，不额外加载配置。
4. 若仍失败，只读取发行版原文件，确认它声明的配置名称恰好是 `bwrap` 和 `unpriv_bwrap`，且同名配置尚未加载。新版先进行无 sudo、跳过内核加载和缓存的编译预检；通过后才用 `apparmor_parser --add` 加载。编译和加载均保留 `Werror`，同时开启对应警告的文字输出，只提取固定标记及计数。拒绝覆盖已有配置，不复制自定义规则到系统目录，也不修改全局 sysctl。
5. 再运行原来的普通、race 和五个写入场景，所有断言仍必须通过。另用无账号直接命令检查工作区可写、工作区外写入被拒绝，以及普通进程可连接的本地监听端口在沙箱内不可连接。
6. 正常或异常退出时，移除本次尝试加载的两项配置，包括部分加载的情况；核对配置确已移除、记录的三项内核设置未变。若手动加载解决了直接启动问题，卸载后还必须再次复现原先的拒绝，才能完成前后对照。

边界探针的临时目录位于 checkout 的同级目录，拒绝写入的目标同时位于工作区、`TMPDIR` 和 `/tmp` 之外，避免把默认允许的临时文件写入当作越界。网络探针只连接同机临时监听端口，不访问账号或模型服务。

软件包安装和配置加载会改变这台临时 Ubuntu runner，所以执行需要新的明确授权。软件包保留到该 runner 销毁，不尝试卸载系统依赖；本脚本显式移除自己加载的配置。任务被平台强制终止时，依赖临时 runner 的销毁回收，不能保证 Python 的清理代码有机会运行。Windows 本机和生产 CPA/ECPA/Codex 配置不参与这一步。

## 本地验证与范围

控制测试使用固定的历史 CI 数字记录和替代操作对象，不执行 sudo、apt 或加载 AppArmor 配置。覆盖未授权环境拒绝、异常基线停止、原生断言缺失拒绝、已有配置保护、部分加载清理、候选或边界检查失败、全局设置变化、编译预检失败和错误的反向对照标记。另验证内容隔离及超时停止。新增 ABI 兼容候选后，当前本机 Windows 为 31 项通过、3 项 Linux 专用检查跳过；Linux 检查分别使用私有 dpkg 数据库、只显示 AppArmor 帮助的参数识别，以及不加载配置的 ABI 编译夹具，均不修改系统策略。

运行方式：

```powershell
python scripts/test-linux-sandbox-control.py
python scripts/check-linux-sandbox.py --check-only
```

这些检查不能证明 Ubuntu 内核会接受发行版配置，也不能证明五个补丁场景会恢复。实际报告将分别记录安装软件包、加载配置和卸载配置的阶段；不能把整个依赖安装过程的效果都归因于单独一条 AppArmor 规则。任何最终原生断言、文件/网络边界或清理核对失败，新的手动任务仍判失败。原来的三平台原生流水线不自动加载配置，既有失败不会被隐藏。

机器可读的准备记录见 [本地验证证据](evidence/linux-sandbox-control-preparation-2026-10-29.json)。AppArmor 的添加、拒绝覆盖及移除语义按 [Ubuntu 24.04 手册](https://manpages.ubuntu.com/manpages/noble/man8/apparmor_parser.8.html)核对。

## 首轮执行与元数据修正

`ed695d8`、`92773f6`、`fdef7b5` 获批推送后，[常规 CI](https://github.com/chatwithgod/reflow/actions/runs/40782918223) 三个平台全部通过，Go 普通/race 各 70 通过、4 跳过，初版 15 项控制测试也全部通过。[原生 CI](https://github.com/chatwithgod/reflow/actions/runs/40782918198) 的普通/race 均通过，macOS 五个写入场景通过，Ubuntu/托管 Windows 仍全部写入失败。

[手动 Ubuntu 对照](https://github.com/chatwithgod/reflow/actions/runs/40783038407) 随后在同一串行队列执行，复现普通/race 各 10 通过、写入 0/5 通过及 namespace 拒绝。它在安装前的软件包信息采集阶段报 `package_metadata_invalid`：查询退出码为 1，随后停止。没有运行 apt，也没有加载或移除 AppArmor 配置，记录的三项内核设置未变。四个原生任务的实际执行区间没有重叠。完整结果见 [首轮公开记录](evidence/linux-sandbox-control-publication-2026-10-29.json)。

原始包信息没有保存，无法确定本轮是哪一个字段被拒绝。离线构造对照确认，旧校验会把没有版本号的合法未安装记录当作异常；这属于采集器缺陷，但不能把构造输入当作本轮 CI 原始输出。

修正版按 [dpkg-query 的状态和退出码定义](https://manpages.ubuntu.com/manpages/noble/man1/dpkg-query.1.html)逐个查询包，记录固定状态，再解释版本字段。安装前允许包不存在、未安装或仅留配置文件；安装后仍必须确认四个包都已安装、有有效版本且没有重装错误标志。数据库致命错误和未知格式继续使流程失败。只读查询固定系统数据库、关闭分页器并使用 C locale；原始输出仍不保存。

该次元数据修正只改变包信息采集函数并增加解析器，其他执行函数的 AST 与当时已公开版本一致，原生测试、特权操作和工作流均未改变。准备时的检查与限制见 [元数据修正证据](evidence/linux-sandbox-metadata-fix-2026-10-29.json)，后续实际执行见下一节。

## 第二轮：依赖安装成功，配置加载失败

`cf500dd` 获批推送后，[常规 CI](https://github.com/chatwithgod/reflow/actions/runs/40788488813) 三个平台通过；Ubuntu 的 21 项控制测试全部通过，包含真实 `dpkg-query` 私有数据库夹具，Windows/macOS 则各 20 通过、1 跳过。[自动原生 CI](https://github.com/chatwithgod/reflow/actions/runs/40788488850) 的通过范围与前轮相同。

[第二轮 Ubuntu 对照](https://github.com/chatwithgod/reflow/actions/runs/40788980877)确认安装前 `apparmor-utils` 是已知但未安装、没有版本号的记录；另外两个依赖不存在。修正版成功区分这些状态，并完成依赖安装：bubblewrap 为 `0.9.0-1ubuntu0.3`，AppArmor 相关包为 `4.0.1really4.0.1-0ubuntu0.24.04.9`。安装软件包后，直接沙箱命令仍被拒绝。

发行版配置声明的两项名称通过检查，但严格加载命令返回 1，标准输出和错误输出均为 0 字节。没有得到成功加载后的正向检查，也没有执行 candidate 原生测试。移除命令返回 254；随后直接读取已加载配置列表，确认两项目标均不存在，记录的内核设置未变。没有把移除命令的非零退出码写成成功。

旧摘要把这种“加载失败后仍被拒绝”的情况误标为 `profile_reversal_reproduced: true`。没有成功的正向条件，就不能证明反向恢复。本轮[派生记录](evidence/linux-sandbox-control-second-run-2026-10-29.json)明确作废这一字段，原始报告保留不改；本地修正只有在确认加载后的直接命令通过后，才允许记录有效反向对照。

## 编译诊断的准备依据

[上游 AppArmor 4.0.1 的警告函数](https://gitlab.com/apparmor/apparmor/-/blob/b0eb95457bc2de401920308869d016e696c73664/parser/parser_common.c)分别控制文字输出和错误退出；[默认警告集合](https://gitlab.com/apparmor/apparmor/-/blob/b0eb95457bc2de401920308869d016e696c73664/parser/parser.h)不包含这类规则告警。本地保留原函数构建的便携对照复现了：只启用 `Werror` 时静默退出 1，开启相同类别的警告后输出诊断，仍退出 1。这是函数级复现，不是 Ubuntu 二进制或内核实测，具体触发规则尚未确定。

新版增加不加载内核配置的编译预检，并保留原严格失败条件。诊断只匹配警告正文中的固定标记，忽略文件名和配置名称，避免 `bwrap-userns-restrict` 路径被误当作 user namespace 告警。编译不通过就停止，不尝试特权加载。实现、控制测试和边界见 [编译诊断准备记录](evidence/linux-sandbox-profile-diagnostics-2026-10-29.json)。

## 第三轮：捕获 io_uring 告警，加载前停止

`aec9cf9` 获批推送后，[常规 CI](https://github.com/chatwithgod/reflow/actions/runs/40819402600) 三平台全部通过。Go 普通/race 各 70 通过、4 跳过，vet、fuzz 和合成评测通过；Ubuntu 的 26 项控制测试全部执行通过，包含真实 dpkg 私有数据库与 AppArmor 参数识别检查，Windows/macOS 各 24 通过、2 项按平台跳过。

确认上述条件后，只触发一次 [Ubuntu 手动诊断](https://github.com/chatwithgod/reflow/actions/runs/40819656112)，其 `run_attempt` 为 1。依赖安装成功，版本与第二轮相同；安装后直接沙箱命令仍被拒绝。随后无 sudo、跳过内核加载的严格编译返回 1，标准输出 0 字节、错误输出 134 字节；固定分类记录各一个 `warning_as_error`、`rule_not_enforced`、`io_uring` 标记。

这是本轮遇到的首个严格告警。它把失败范围缩小到 io_uring 规则未生效，但没有区分内核特性与有效策略 ABI 的具体原因，也不能排除后续还有其他告警。不能据此断言内核必然拒绝非严格加载。此次保留 `Werror`、发行版原文件、全局限制和全部写入断言。

预检失败后未执行 `profile_add`、`profile_remove` 或 candidate 原生检查，也没有正向/反向对照或文件与网络边界的通过证据；记录的三项内核设置未变。[自动原生 CI](https://github.com/chatwithgod/reflow/actions/runs/40819402621) 仍为三平台普通/race 各 10 项通过、macOS 写入 5/5、Ubuntu/托管 Windows 写入 0/5。四个原生任务的实际时间段没有重叠，全部使用合成登录，真实模型调用 0。完整数字与散列见 [第三轮执行记录](evidence/linux-sandbox-control-third-run-2026-10-29.json)。

## 发行版 ABI 核对与待授权候选

随后从 [Ubuntu 官方源包目录](https://archive.ubuntu.com/ubuntu/pool/main/a/apparmor/)读取 CI 对应的 `4.0.1really4.0.1-0ubuntu0.24.04.9` 源码包和二进制安装包，仅在本地解出所需文件，没有安装或执行 Linux 程序。源码归档的 SHA-256 与 `.dsc` 一致；未验证 `.dsc` 的 PGP 签名。安装包中的 bwrap 配置与 CI 记录的散列完全一致，其 ABI 4.0 和 parser.conf 也与对应源码文件一致。

发行版 bwrap 配置声明 `abi <abi/4.0>`，两个 profile 各有一条 `allow io_uring`，但该 ABI 文件没有 `io_uring` 能力。核对发行版补丁后的编译器源码确认，它取内核能力与策略 ABI 的交集：只要 ABI 没有该能力，就不会生成这类规则，并发出第三轮观察到的告警。此结论可以解释固定发行版文件的行为；前轮没有保存 runner 上的 ABI、parser.conf 和编译器散列，也未直接检查内核的 io_uring 能力，不能补写为已经实测。

新的 `allow_pinned_io_uring_abi_warning` 手动选项默认关闭。开启时先核对三个 AppArmor 包版本，以及编译器、配置、ABI、bwrap profile 四个文件的固定散列和权限；拒绝已有的 profile 局部覆盖文件，还要求内核声明 userns、profile stacking 和 `sys_admin` 能力。随后仍先复现严格编译的固定失败，再以跳过内核加载的方式编译兼容候选。

**这个选项会明确省略兼容编译和加载命令中的 `Werror=rule-not-enforced`。** 它只接受两个指定 profile 各一条完整、完全匹配的 io_uring 告警，标准输出必须为空、退出码必须为 0；任何其他告警、错误、版本或文件变化都停止。发行版规则、全局 sysctl 和原生写入断言不变。加载成功后仍需通过原来的普通/race、五个写入场景、文件和网络边界，以及移除后的反向对照。发现同名配置已存在且尚未发起本次加载时，不执行移除。

本地 31 项通过、3 项 Linux 检查跳过；新增 Linux 夹具用同一个 ABI 文件，分别构造含有和不含 io_uring 的内核能力文件，检查严格模式失败和兼容编译告警，始终跳过内核加载。这项真实编译夹具尚未在 Linux 运行。后续应先确认常规 CI 三平台通过、Ubuntu 三项专用检查全部执行且无跳过，再考虑单次手动对照。候选没有推送，也没有远程执行；它改变了编译告警的处理条件，需要针对这一变化的新授权。准备证据见 [ABI 兼容候选](evidence/linux-sandbox-abi4-preparation-2026-10-29.json)。
