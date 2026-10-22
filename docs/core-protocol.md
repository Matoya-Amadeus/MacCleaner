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

> **取消语义（2026-10-22）**：协作式取消——响应当前命令的部分结果（`status: "cancelled"`、
> `moved[]`、`remaining[]`），**已移走的不回滚**。目前支持：`files.trash`、`orphans.apply`；
> **已支持全部五个执行命令**：`files.trash`、`orphans.apply`、`clean`、`uninstall.apply`、`updates.apply`。
> 粒度：`updates.apply` 在**组与组之间**停（不打断正在跑的 brew），`uninstall.apply`/`clean` 在**项与项之间**停；
> 都返回 `cancelled: true` 与 `remaining[]`。

`progress` 目前未使用：细粒度进度需要内核在扫描/清理里回调，计划在 M2 里补
（届时会带 `done` / `bytes` / `phase`）。**界面不能假设一定会有 `progress`**。

## 3. 命令

| cmd | 参数 | 返回 `data` | 备注 |
|---|---|---|---|
| `tools.list` | — | `{mcp[],commands[],example}` | AI 可调用面：MCP 工具 + stdio 命令 + 示例 |
| `cancel` | — | `{cancelled:true}` | **不进队列**：立刻置标志，正在执行的操作在下一项前停下 |
| `ping` | — | `{pong:true,v}` | 连通性 |
| `disk.summary` | — | `{total,used,free,percent}` | **毫秒级**，只做 statfs，不读受保护目录 |
| `disk` | — | `{total,used,free,percent,sections[],system{}}` | 会对各目录跑 `du`；**需要「完全磁盘访问权限」**，否则体积全 0 |
| `system` | — | `{load[],cpu_count,memory_*,processes[],power{},thermal{}}` | 只读 |
| `skills` | — | `{skills[]}` | 每项 `{name,description,path,root}` |
| `apps` | — | `{apps[],groups[],count}` | 每项 `{name,bundle_id,path,category,...}`；`groups` 按 macOS 官方分类排好序 |
| `scan` | — | `{report{}}` | 内核原始审计报告（调试用） |
| `review.payload` | — | `{candidates[],groups[],count,total_bytes}` | **分组已在核内**（系统数据/浏览器/App/开发工具/容器/你的文件/废纸篓） |
| `updates.list` | — | `{items[],groups[],sparkle_updates[],sparkle_rest[],notes[]}` | 只把**确认有更新**的 Sparkle 放 `sparkle_updates` |
| `orphans.list` | — | `{items[],groups[],count,total_bytes}` | 按 `~/Library/<子目录>` 分桶 |
| `large.list` | — | `{items[],count,total_bytes,roots[],min_bytes}` | 按体积降序 |
| `clean` | `approved_ids[]`,`selected_ids[]` | `{completion{},moved_count}` | **空 `approved_ids` 直接拒绝**；`completion` 给完成页口径（可恢复/实际释放/跳过/回执） |
| （以上四个执行命令的公共字段） | — | `result{kind,title,count,bytes,failed_count,failures[],cancelled}` | `uninstall.apply` / `updates.apply` / `orphans.apply` / `clean` 都附 `result`，界面用同一张结果页 |
| `uninstall.plan` | `path`（必需）,`bundle_id`,`name` | 卸载计划（`app`,`items[]`,`user_total_bytes`） | 只读，不删 |
| `uninstall.apply` | `path`,`item_ids[]` | 执行结果 | **空 `item_ids` 直接拒绝** |
| `updates.check` | — | `{items[],sparkle[],notes[]}` | 六源并行 + Sparkle appcast |
| `updates.apply` | `ids[]` | 结果分组 | id 用 **`manager\|kind\|name`**（也兼容旧的数组下标）；空数组拒绝 |
| `orphans.scan` | — | 残留报告 | |
| `orphans.apply` | `paths[]` | 结果 | 传**路径**（内核 `orphans_clean(home, paths)`）；空数组拒绝 |
| `files.trash` | `paths[]` | `{moved[],failed[]}` | 大文件页用；空数组拒绝 |
| `app.open` | `path` | `{opened}` | 只接受**存在且以 `.app` 结尾**的路径（Sparkle 应用内更新） |
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
