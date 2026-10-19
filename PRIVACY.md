# 隐私说明（Privacy）

MacCleaner 是**本地工具**：没有账号、没有云同步、没有遥测。这一页把"它到底碰了什么"写清楚，
你不需要相信描述，代码里都能对上。

## 不收集什么

- 不上传文件内容、文件名清单、路径、使用时长或任何行为数据；
- 没有 analytics / 崩溃上报 / 设备指纹；
- 不申请「完全磁盘访问」以外的权限（清理 `~/Library` 才需要），也不要求管理员权限，
  除卸载系统级残留时的一次显式授权（`--accept-admin`）。

## 会联网的地方（仅此几处）

| 场景 | 谁发起的请求 | 传出去什么 |
|---|---|---|
| `brew outdated` / `brew upgrade` | Homebrew 自己 | Homebrew 的常规元数据请求 |
| `mas outdated` / `mas upgrade` | mas（走 App Store 私有接口） | 你的 Apple ID 会话（由 mas / storeagent 处理） |
| `npm` / `pip` / `gem` / `rustup` 检查 | 各自 CLI | 各自的包索引查询 |
| App Store 更新发现兜底 | **MacCleaner 自己** | 只发 `app id` 与 `country`（如 `CN`），发往 `itunes.apple.com/lookup`；不发送任何本机信息 |
| 打开 App Store 更新页 | `open macappstore://showUpdatesPage` | 无 |

`npm`/`pip`/`gem` 的检查默认关闭（要联网且慢），可用 `MACCLEANER_UPDATE_SOURCES` 打开。

## 在本机留下什么

| 路径 | 内容 | 怎么清 |
|---|---|---|
| `~/.maccleaner/state/` | 会话状态、扫描缓存（`scan-cache.json`）、更新缓存（`updates-cache.json`） | `rm -rf ~/.maccleaner` |
| `~/.mac-storage-manager/receipts/` | 每次清理的回执（时间、目标、字节数） | 只保留需要的，其余删除即可 |
| `~/Library/Logs/MacCleaner/` | 启动日志、真机自测截图、`reveal.log`（右键"在 Finder 中显示"的记录） | 直接删 |

回执里**不含文件内容**，只有路径、体积、状态；如果你不想留痕，清理完直接删回执目录。

## 界面与访问控制

- 只监听 `127.0.0.1`，不对外暴露；
- 入口是一次性链接（`/bootstrap/<secret>`），换完 cookie 立即作废；
- 每个动作要求 cookie + 请求头双凭据并校验 Origin；
- 同一时间只允许一个会话（flock），避免两个实例互相干扰。

## 删除行为

- 清理/卸载一律**移入废纸篓**（可恢复），不做 `rm -rf`；
- 受保护路径（`.ssh`、`Keychains`、`Safari`、`Mail` 等）永不出现；
- 高风险目标（`~/Downloads`、Docker 数据）默认不可勾选，要在确认页单独确认。

## 联系

发现问题请开 issue：<https://github.com/Matoya-Amadeus/MacCleaner/issues>
