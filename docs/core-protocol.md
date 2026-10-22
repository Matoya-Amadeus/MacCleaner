# 内核协议（`maccleaner-core`）

> 版本：**protocol 1**（2026-10-22）。界面（SwiftUI）与 agent（CLI/MCP）都通过这一层说话，
> 内核不产出 HTML、不产出文案。

## 1. 传输

一行 JSON 一个消息，UTF-8，顺序即因果：

```
启动：  maccleaner-core serve --stdio
请求：  {"id":"1","cmd":"scan","args":{}}
事件：  {"id":"1","event":"started","op":"scan"}
终态：  {"id":"1","ok":true,"data":{...},"v":1}
```

- `id` 由调用方生成，原样回传（便于并发/多窗口区分）。缺失时服务端填空串。
- 一个请求 = **零到多个事件 + 恰好一个终态**。看到终态就代表这次请求结束。
- 每条消息立即 flush，所以事件是"流"出来的，不是攒到最后。

## 2. 事件

| event | 时机 | 字段 |
|---|---|---|
| `started` | 任何可能超过 0.3s 的操作**开始前** | `op`，可选 `count` |

`progress` 目前未使用：细粒度进度需要内核在扫描/清理里回调，计划在 M2 里补
（届时会带 `done` / `bytes` / `phase`）。**界面不能假设一定会有 `progress`**。

## 3. 命令

| cmd | 参数 | 返回 `data` | 备注 |
|---|---|---|---|
| `ping` | — | `{pong:true,v}` | 连通性 |
| `disk` | — | `{total,used,free,percent,sections[],system{}}` | `system` 是缓存读数（未授权时为空） |
| `system` | — | `{load[],cpu_count,memory_*,processes[],power{},thermal{}}` | 只读 |
| `skills` | — | `{skills[]}` | 每项 `{name,description,path,root}` |
| `apps` | — | `{apps[]}` | 每项 `{name,bundle_id,path,category,...}` |
| `scan` | — | `{report{}}` | 内核原始审计报告；**分组由内核在 M1 补**，暂由界面自行组织 |
| `clean` | `approved_ids[]`,`selected_ids[]` | 清理结果（含回执） | **空 `approved_ids` 直接拒绝** |
| `uninstall.plan` | `path`（必需）,`bundle_id`,`name` | 卸载计划（`app`,`items[]`,`user_total_bytes`） | 只读，不删 |
| `uninstall.apply` | `path`,`item_ids[]` | 执行结果 | **空 `item_ids` 直接拒绝** |
| `updates.check` | — | `{items[],sparkle[],notes[]}` | 六源并行 + Sparkle appcast |
| `updates.apply` | `ids[]` | 结果分组 | 空数组拒绝 |
| `orphans.scan` | — | 残留报告 | |
| `orphans.apply` | `ids[]` | 结果 | 空数组拒绝 |
| `system.measure` | — | 系统级目录体积 | **弹一次管理员授权，只读** |
| `system.trash` | `paths[]` | `{moved[],failed[]}` | 需授权；只接受白名单子项 |

### 为什么"空数组"要拒绝

这是产品安全规则在内核层的**最后一道闸**：界面 bug、脚本误用、agent 幻觉都可能传空数组。
"空 = 全部"会让一次误调用删掉所有候选（历史上就有过 `if not wanted` 导致全量升级的教训）。

## 4. 错误

```json
{"id":"3","ok":false,"error":{"code":"bad_args","message":"…","v":1}}
```

| code | 含义 | 调用方该做什么 |
|---|---|---|
| `bad_json` | 这一行不是 JSON | 记日志，不要重试 |
| `bad_request` | 缺 `cmd`/`id` | 修调用方 |
| `unknown_command` | 未知命令（附带 `hint`：可用命令列表） | 版本不匹配，提示升级 |
| `bad_args` | 参数缺失/类型错/空数组 | 修调用方，**不要自动重试** |
| `internal_error` | 内核异常（stderr 有完整堆栈） | 显示"可重试"，并保留 stderr |

## 5. 兼容策略

- `v` 字段每行都带；**破坏性变更必须升 `PROTOCOL_VERSION`**，界面按 `v` 做分支。
- `data` 里只增字段、不删字段；需要改语义时新增命令（如 `uninstall.plan2`）而不是改旧命令。
- 命令名用点号分层（`uninstall.plan`），便于按前缀批量处理。

## 6. 实测（本机，2026-10-22）

| 命令 | 首次耗时 | 说明 |
|---|---|---|
| `ping` | < 1 ms | |
| `disk` | 0.24 s | 目录体积走 `du`（8s 超时，拿多少算多少） |
| `scan` | **1.9 s** | 冷缓存；有缓存后 ~0.7 s |
| `uninstall.plan` | **3.4 s**（Safari） | 逐个目录核对残留 |
| `updates.check` | **5.2 s** | 六源并行 + Sparkle appcast |

这几个数字就是"必须先发 `started`"的理由。

## 7. 尚未做（M1/M2）

| 项 | 计划 |
|---|---|
| 把 `review` / `updates` 的分组逻辑从 `ui/pages.py` 迁进内核 | M1（否则 Swift 侧要复制一份规则，违背"内核是唯一真相源"） |
| 细粒度 `progress` 事件 | M2（需要内核在扫描/清理里回调） |
| 取消（`cancel` 命令 / 信号） | M3（长操作要能中断） |
| 鉴权 | 不需要：stdio 由父进程持有，没有网络面 |
