"""内核侧文案（双语）。

为什么放在内核：分组名、条目名、hint、失败原因都是**内核生成的**，
界面只负责渲染。如果翻译放在 Swift 侧，就要维护一份"内核字符串 → key"的映射，
内核一改文案界面就静默失效——今天已经踩过一次（`updates_view` 挑了固定字段、
把新增的 electron 组整个丢掉）。

约定：
- 每条文案一个 key，`(中文, English)`；
- 未知文案**原样返回**（不翻译成空白），并在英文下保持可读；
- 只翻"给人看的"字段：label / hint / name / reason / kind。id、path 不动。
"""

from __future__ import annotations

from typing import Any

LANGS = ("zh", "en")

# key -> (zh, en)
TERMS: dict[str, tuple[str, str]] = {
    # ── 清理页分组 ──
    "group.browser": ("浏览器", "Browsers"),
    "group.app_cache": ("App 缓存与日志", "App caches & logs"),
    "group.dev": ("开发工具", "Developer tools"),
    "group.container": ("容器与虚拟机", "Containers & VMs"),
    "group.user_files": ("你的文件", "Your files"),

    "hint.browser": (
        "浏览器留下的缓存（不含 Cookies / 登录数据），默认已勾选",
        "Cache left by browsers (no Cookies or login data). Selected by default.",
    ),
    "hint.app_cache": ("应用运行时生成，删了会重建", "Created at runtime; it comes back after deletion."),
    "hint.dev": ("Xcode / 包管理器 / 编辑器缓存", "Xcode, package managers and editor caches."),
    "hint.container": ("Docker 等运行时数据，删除后需要重新拉取",
                       "Docker and similar runtime data; refetched after deletion."),
    "hint.user_files": ("Downloads、安装包、iOS 备份——删前自己确认",
                        "Downloads, installers, iOS backups — review before deleting."),

    # ── 清理页条目名 ──
    "name.browser_cache": ("浏览器缓存", "Browser cache"),
    "name.user_caches": ("用户缓存", "User caches"),
    "name.home_logs": ("Home logs", "Home logs"),
    "name.downloads": ("Downloads", "Downloads"),

    # ── 卸载页 kind ──
    "kind.app_bundle": ("应用本体", "Application"),
    "kind.support": ("应用支持", "Application Support"),
    "kind.caches": ("缓存", "Caches"),
    "kind.logs": ("日志", "Logs"),
    "kind.preferences": ("偏好设置", "Preferences"),
    "kind.container": ("沙盒容器", "Sandbox container"),
    "kind.http_storages": ("网络存储", "HTTP storages"),
    "kind.saved_state": ("窗口状态", "Saved state"),
    "kind.cookies": ("Cookies", "Cookies"),
    "kind.launch_agent": ("登录项", "Login item"),
    "kind.name_match": ("同名残留", "Name match"),
    "kind.system": ("系统级", "System-level"),

    # ── 更新页分组 ──
    "ugroup.electron": ("Electron 应用", "Electron apps"),
    "ugroup.undetectable": ("无法自动检测", "Cannot be checked"),
    "ugroup.appstore": ("App Store", "App Store"),
    "ugroup.npm": ("npm 全局包", "npm global packages"),
    "ugroup.python": ("Python 包", "Python packages"),
    "ugroup.rust": ("Rust 工具链", "Rust toolchain"),

    # ── 应用分类（卸载页分组）──
    "cat.browser": ("浏览器", "Browsers"),
    "cat.dev": ("开发工具", "Developer tools"),
    "cat.social": ("社交与通讯", "Social & messaging"),
    "cat.office": ("效率办公", "Productivity"),
    "cat.design": ("设计与图像", "Design & graphics"),
    "cat.media": ("影音", "Media"),
    "cat.game": ("游戏", "Games"),
    "cat.read": ("阅读资讯", "News & reading"),
    "cat.system": ("系统工具", "Utilities"),
    "cat.other": ("其它", "Other"),

    # ── 常见状态/原因 ──
    "reason.up_to_date": ("已是最新", "Up to date"),
    "reason.no_feed": ("没有可用的更新源", "No update feed"),
    "reason.unreachable": ("更新源不可达", "Update feed unreachable"),
    "reason.no_version": ("更新源里没有版本号", "Feed has no version"),
    "reason.self_update": ("由应用自身更新（无公开更新源）", "Updates itself (no public feed)"),
    "reason.store_not_found": ("商店上查不到", "Not found in the store"),
    "reason.no_bundle_id": ("没有 bundle id", "No bundle id"),
    "reason.no_installed_version": ("读不到已装版本", "Installed version unreadable"),
    "reason.feed_unavailable": (
        "更新源不可用（拿不到 latest-mac.yml）",
        "Update feed unavailable (latest-mac.yml missing)",
    ),
    "reason.feed_no_url": ("更新源里没有地址", "Feed has no URL"),
    "reason.feed_unreachable": ("更新源不可达", "Update feed unreachable"),
    "reason.feed_unsupported": ("更新源类型不支持", "Unsupported feed provider"),
}


def resolve(lang: str | None) -> str:
    """把外部传进来的语言名归一；默认中文。"""
    text = (lang or "zh").strip().lower()
    if text.startswith("en"):
        return "en"
    return "zh"


def t(key: str, lang: str | None = None) -> str:
    entry = TERMS.get(key)
    if entry is None:
        return key
    return entry[1] if resolve(lang) == "en" else entry[0]


def _lookup(text: str, table: dict[str, str], lang: str) -> str:
    key = table.get(text)
    return t(key, lang) if key else text


# 中文原文 → key。只登记"固定文案"，动态拼出来的（带数量/路径）不在此列。
GROUP_KEYS = {
    "浏览器": "group.browser",
    "App 缓存与日志": "group.app_cache",
    "开发工具": "group.dev",
    "容器与虚拟机": "group.container",
    "你的文件": "group.user_files",
}

NAME_KEYS = {
    "浏览器缓存": "name.browser_cache",
    "用户缓存": "name.user_caches",
}

KIND_KEYS = {
    "app-bundle": "kind.app_bundle",
    "app-support": "kind.support",
    "application-support-name": "kind.name_match",
    "caches": "kind.caches",
    "logs": "kind.logs",
    "preferences": "kind.preferences",
    "container": "kind.container",
    "http-storages": "kind.http_storages",
    "http-storages-cookies": "kind.cookies",
    "saved-state": "kind.saved_state",
    "launch-agent": "kind.launch_agent",
    "system": "kind.system",
}

APP_CATEGORY_LABELS = {
    "浏览器": "cat.browser",
    "开发工具": "cat.dev",
    "社交与通讯": "cat.social",
    "效率办公": "cat.office",
    "设计与图像": "cat.design",
    "影音": "cat.media",
    "游戏": "cat.game",
    "阅读资讯": "cat.read",
    "系统工具": "cat.system",
    "其它": "cat.other",
}

UPDATES_GROUP_LABELS = {
    "Electron 应用": "ugroup.electron",
    "无法自动检测": "ugroup.undetectable",
    "npm 全局包": "ugroup.npm",
    "Python 包": "ugroup.python",
    "Rust 工具链": "ugroup.rust",
}

REASON_KEYS = {
    "已是最新": "reason.up_to_date",
    # 固定长句（含括号但没有变量）走精确匹配，别让前缀规则再拼一次
    "更新源不可用（拿不到 latest-mac.yml）": "reason.feed_unavailable",
    "更新源里没有地址": "reason.feed_no_url",
    "没有可用的更新源": "reason.no_feed",
    "商店上查不到": "reason.store_not_found",
    "读不到已装版本": "reason.no_installed_version",
    "由应用自身更新（无公开更新源）": "reason.self_update",
}


def localize_groups(groups: list[dict[str, Any]], lang: str | None) -> list[dict[str, Any]]:
    """就地翻译清理页分组（label / hint）。未知文案保持原样。"""
    if resolve(lang) != "en":
        return groups
    for group in groups:
        group["label"] = _lookup(str(group.get("label") or ""), GROUP_KEYS, "en")
        hint = str(group.get("hint") or "")
        if hint:
            group["hint"] = _lookup(hint, GROUP_HINT_KEYS, "en")
    return groups


# hint 原文 → key（hint 是长句，单独一张表更好维护）
GROUP_HINT_KEYS = {
    "浏览器留下的缓存（不含 Cookies / 登录数据），默认已勾选": "hint.browser",
    "应用运行时生成，删了会重建": "hint.app_cache",
    "Xcode / 包管理器 / 编辑器缓存": "hint.dev",
    "Docker 等运行时数据，删除后需要重新拉取": "hint.container",
    "Downloads、安装包、iOS 备份——删前自己确认": "hint.user_files",
}


def localize_items(items: list[dict[str, Any]], lang: str | None) -> list[dict[str, Any]]:
    if resolve(lang) != "en":
        return items
    for item in items:
        name = str(item.get("name") or "")
        item["name"] = _lookup(name, NAME_KEYS, "en")
    return items


def localize_kind(kind: str, lang: str | None) -> str:
    if resolve(lang) != "en":
        return kind
    return _lookup(kind, KIND_KEYS, "en")


# 带括号变量的动态文案：`更新源不可达（HTTPError）` → `Update feed unreachable (HTTPError)`。
# 保留括号里的原始信息（异常名 / provider 名），它对排查有用。
DYNAMIC_REASONS = (
    ("更新源不可达（", "reason.feed_unreachable"),
    ("更新源类型不支持（", "reason.feed_unsupported"),

)


def localize_reason(reason: str, lang: str | None) -> str:
    if resolve(lang) != "en":
        return reason
    text = reason or ""
    exact = _lookup(text, REASON_KEYS, "en")
    if exact != text:
        return exact
    for prefix, key in DYNAMIC_REASONS:
        if text.startswith(prefix) and text.endswith("）"):
            inner = text[len(prefix):-1]
            return f"{t(key, 'en')} ({inner})"
    return text


def localize_app_category(label: str, lang: str | None) -> str:
    """卸载页的分类名（内核分类出来的「浏览器 / 开发工具 / …」）。"""
    if resolve(lang) != "en":
        return label
    return _lookup(label, APP_CATEGORY_LABELS, "en")


def localize_updates_group(label: str, lang: str | None) -> str:
    if resolve(lang) != "en":
        return label
    return _lookup(label, UPDATES_GROUP_LABELS, "en")
