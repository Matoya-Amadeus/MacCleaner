# MacCleaner

![MacCleaner](assets/readme-header.svg)

> **先看清单，再决定删什么。**
>
> MacCleaner 先审计空间、生成目标清单，再按安全门禁执行清理。

[中文](README.md) · [English](README.en.md)

<details>
<summary><strong>近期更新</strong></summary>

更新时间：2026-07-11 19:08

更新内容：将长内容改为 GitHub 可折叠章节，并用独立英文 README 实现语言切换。

### 2026-05-19 21:20

更新内容：新增 generic 默认 profile、repo-evidence opt-in、受保护会话阻断、receipt、backup 和清理后残留验证。

</details>

## 目录

- [一眼看懂](#一眼看懂)
- [解决什么问题](#解决什么问题)
- [安装](#安装)
- [三分钟上手](#三分钟上手)
- [常用场景](#常用场景)
- [安全边界](#安全边界)
- [配置与参数](#配置与参数)
- [报告怎么看](#报告怎么看)
- [结构与工作链路](#结构与工作链路)
- [开发者说明](#开发者说明)
- [常见问题](#常见问题)

## 一眼看懂

| 你要做什么 | 运行什么 | 会发生什么 |
| --- | --- | --- |
| 只看空间占用 | `bash scripts/audit_storage.sh` | 只读扫描，不删除文件 |
| 生成精确清单 | `bash scripts/plan_storage.sh` | 列出计划中、需批准和被阻断的目标 |
| 清理低风险目标 | `bash scripts/apply_storage_plan.sh` | 只执行可重新生成的低风险目标 |
| 清理高风险目标 | apply 时加 `--approved-targets ID` | 只执行你明确批准的目标 |

<details id="解决什么问题">
<summary><strong>解决什么问题</strong></summary>

Mac 空间不足时，最容易出错的不是找不到大文件，而是把缓存、个人文件、浏览器登录状态和系统数据混在一起处理。

工具流程固定为：

```text
audit -> plan -> approve exact target IDs -> apply -> verify
```

</details>

<details id="安装">
<summary><strong>安装</strong></summary>

要求：macOS、Python 3.10+；不需要第三方 Python 包。wrapper 需要 `zsh`。

```bash
git clone https://github.com/Matoya-Amadeus/MacCleaner.git
cd MacCleaner
python3 scripts/mac_storage_manager.py --help
```

</details>

<details id="三分钟上手" open>
<summary><strong>三分钟上手</strong></summary>

### 1. 审计：只读查看空间

```bash
bash scripts/audit_storage.sh
```

### 2. 计划：生成精确清单

```bash
bash scripts/plan_storage.sh
```

重点看 `target_id`、`status`、`risk`、`protection` 和 `reason`。

### 3. 执行：只清理低风险目标

```bash
bash scripts/apply_storage_plan.sh
```

这条命令会实际修改文件。运行前先完成 `plan`；它默认只放行低风险、可重新生成的目标。

高风险目标必须从当前计划复制真实 ID：

```bash
bash scripts/plan_storage.sh --include-hidden-home
bash scripts/apply_storage_plan.sh \
  --include-hidden-home \
  --approved-targets TARGET_ID
```

如果目标显示 `exact_confirm`，还要同时加上 `--confirm-targets TARGET_ID`。

</details>

<details id="常用场景">
<summary><strong>常用场景</strong></summary>

只读输出：

```bash
python3 scripts/mac_storage_manager.py audit --markdown
python3 scripts/mac_storage_manager.py audit --json
```

追查反复出现的目录：

```bash
python3 scripts/mac_storage_manager.py trace \
  --path "<TARGET_PATH>" \
  --keyword "<KEYWORD>" \
  --markdown
```

聚焦某个 App 或 Flutter 工程：

```bash
python3 scripts/mac_storage_manager.py audit \
  --app-path "/Applications/Example.app" --markdown
python3 scripts/mac_storage_manager.py audit \
  --flutter-search-root "$HOME/Projects" --markdown
```

`trace` 只读，不会删除文件。把示例路径和关键词替换成真实值。

</details>

<details id="安全边界">
<summary><strong>安全边界</strong></summary>

| 目标 | 默认行为 |
| --- | --- |
| 普通缓存、日志、临时文件 | 可以计划；apply 时由 `--yes` 放行 |
| Downloads、Trash、Docker、hidden-home、App 残留、系统范围 | 默认不自动清理，需要精确批准 |
| 浏览器登录、Cookie、Session、Token、Keychain、凭据 | 永久阻断 |
| 不在当前计划中的目标 | 不执行 |

`audit`、`plan`、`trace` 都是只读命令。`apply_storage_plan.sh` 会修改文件；`safe_clean.sh` 只是旧入口的兼容 shim。

</details>

<details id="配置与参数">
<summary><strong>配置与参数</strong></summary>

- `--profile generic`：默认通用模式，不假定私有 repo 结构。
- `--profile repo-evidence`：显式开启项目证据和历史索引追踪。
- `--state-root PATH`：设置 receipt 和 backup 的默认根目录。
- `--receipt-dir PATH` / `--backup-dir PATH`：单独指定目录，优先于 `--state-root`。
- `--approved-targets ID1,ID2`：批准当前 plan 中的精确目标。
- `--confirm-targets ID1,ID2`：为 `exact_confirm` 目标提供二次确认。
- `--include-hidden-home` / `--include-system`：扩大扫描范围，默认关闭。
- `--app-path PATH` / `--flutter-search-root PATH`：聚焦扫描范围。
- `--json` / `--markdown`：选择输出格式。
- `--apply` / `--dry-run` / `--yes`：控制 `clean` 模式的执行方式。

默认状态目录是 `~/.mac-storage-manager/`。

</details>

<details id="报告怎么看">
<summary><strong>报告怎么看</strong></summary>

- `target_id`：目标编号，高风险 apply 必须从当前 plan 复制。
- `status`：`planned`、`ready`、`blocked`、`skipped` 等状态。
- `protection`：需要批准、二次确认或保持阻断的原因。
- `backup_manifest`：需要备份时的备份和 SHA-256 清单。
- `receipt`：apply 的 Markdown/JSON 清理记录路径。

`empty` 表示没有可清理内容，属于正常结果。目标反复出现时，用 `trace` 查触发源。

</details>

<details id="结构与工作链路">
<summary><strong>结构与工作链路</strong></summary>

```text
CLI/wrapper -> StorageContext -> profile discovery -> scan -> plan/gates
            -> optional apply -> renderer/receipt/residual validation
```

- `scripts/mac_storage_manager.py`：CLI 兼容 facade。
- `scripts/_mac_storage_core.py`：扫描、计划、执行、receipt、backup。
- `scripts/_mac_storage_policy.py`：风险、批准、retention、profile 策略。
- `scripts/_mac_storage_render.py`：Markdown、text、JSON 输出。
- `scripts/*_storage.sh`：audit、plan、apply wrapper。
- `tests/`、`references/`：测试和敏感场景路由说明。

</details>

<details id="开发者说明">
<summary><strong>开发者说明</strong></summary>

```bash
python3 -m unittest -v \
  tests.test_mac_storage_manager \
  tests.test_mac_storage_open_source_contract
```

提交前保持 CLI flag、wrapper、README、SKILL.md、renderer 和测试一致。

</details>

<details id="常见问题">
<summary><strong>常见问题</strong></summary>

### 我没有说“先列清单”，它会直接清理吗？

推荐流程不会跳过清单：先运行 `plan`，看完结果，再决定是否运行 apply。apply 会重新扫描，并再次执行风险和批准检查。

### `--yes` 会删除 Downloads 或 Trash 吗？

不会。`--yes` 只放行 low-risk 目标。敏感范围需要精确批准，浏览器身份和凭据数据保持阻断。

### apply 失败或没有释放空间怎么办？

查看报告里的 `blocked`、`skipped`、`failed` 和 `reason`。`empty` 表示没有可清理内容，属于正常结果。

</details>

由 **AI·Maho** 和 **人类·Matoya** 共同维护
Maintained jointly by **AI·Maho** and **Human·Matoya**
