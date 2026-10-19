"""页面外壳与导航（2026-10-18 迁入）。

为什么先做"外壳"而不是直接搬整个界面：界面里真正难的是**数据从哪来**（会话、冻结计划、
签名复核、回执），那部分要等 core 适配；而外壳与页面渲染只吃 dict，可以先用示例数据测。

三条约束写死在这里，后面所有页面都继承：

1. **配色只走 CSS 变量**：`theme.py` 里一套 `:root` + 深色变体；页面里不许出现硬编码色值
   （否则调品牌色时总有几页不跟着变）；
2. **动作只走插槽**：页面把按钮 HTML 交给 `state_page(..., actions=...)`，不允许各自拼 `<body>`；
3. **侧栏只放真能点的入口**：未就绪的用 `disabled + aria-disabled` + "待实现"徽标，
   绝不出现"点了没反应"的假菜单。
"""
from __future__ import annotations

import html
from dataclasses import dataclass, field
from typing import Any

from .theme import STYLE

ACTIONS_SLOT = "<!--__ACTIONS__-->"
NAV_SLOT = "<!--__NAV__-->"
UI_SCHEMA = "maccleaner-ui-v1"


@dataclass(frozen=True)
class NavItem:
    key: str
    label: str
    action: str
    enabled: bool = True
    badge: str = ""
    group: str = ""


@dataclass(frozen=True)
class NavGroup:
    title: str
    items: tuple[NavItem, ...] = field(default_factory=tuple)


# 三个真实入口 + 一个"技能说明"页；未实现的能力不列（宁缺勿假）。
NAV_GROUPS: tuple[NavGroup, ...] = (
    NavGroup("清理", (NavItem("clean", "Mac 清理", "start"),)),
    NavGroup(
        "应用",
        (
            NavItem("uninstall", "软件卸载（彻底）", "uninstall-list"),
            NavItem("updates", "软件更新", "updates-open"),
        ),
    ),
    NavGroup("技能", (NavItem("skills", "可调用的 Skill", "skills-open"),)),
)


# 页面运行时（2026-10-18）：把点击变成一次 `/action` 投递。
# 为什么不用行内 onclick：动作必须带 CSRF 头，且要按勾选框收集 id——集中一处才不会各页各写一套。
_RUNTIME_JS = """
<script>
(function(){
  const csrf = () => {
    const m = document.cookie.match(/(?:^|;\\s*)mc_csrf=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  };
  window.maccleanerAction = async function(action, payload){
    const response = await fetch('/action', {
      method: 'POST',
      credentials: 'same-origin',
      headers: {'Content-Type':'application/json','X-MC-CSRF':csrf(),'X-MC-Action':'1'},
      body: JSON.stringify({action: action, payload: payload || {}})
    });
    let result = {};
    try { result = await response.json(); } catch (e) {}
    if (!response.ok || !result.accepted) { throw new Error(result.error || '动作未被接受'); }
    // 关键：动作只是**入队**，页面由服务端稍后才发布。若此时立刻 reload，取回的仍是旧页，
    // 用户就会觉得"点了没反应"（2026-10-18 真浏览器实测：四次点击的显示都慢一拍）。
    // 这里轮询到页面真的变了再刷新；最多等 ~3 秒，超时也刷新一次（总比不动强）。
    const before = document.documentElement.dataset.stage + '|' + document.body.innerHTML.length;
    for (let attempt = 0; attempt < 15; attempt++) {
      await new Promise((resolve) => setTimeout(resolve, 200));
      try {
        const text = await (await fetch('/', {credentials: 'same-origin', cache: 'no-store'})).text();
        const stage = (text.match(/data-stage="([a-z-]+)"/) || [])[1] || '';
        const changed = stage !== document.documentElement.dataset.stage
          || (text.match(/<body[\s\S]*<\/body>/) || [''])[0].length !== document.body.innerHTML.length;
        if (changed) { location.reload(); return result; }
      } catch (e) { /* 网络抖动就再试一次 */ }
    }
    location.reload();
    return result;
  };
  const ids = (selector) => Array.from(document.querySelectorAll(selector))
      .filter(node => node.checked).map(node => node.dataset.itemId || node.dataset.updateId);
  document.addEventListener('click', async (event) => {
    // 两种按钮都要接：正文动作（data-bridge-action）与侧栏导航（data-nav-action）。
    // 2026-10-18 真机发现：原来只监听前者，于是**四个侧栏入口点了完全没反应**。
    const button = event.target.closest('[data-bridge-action],[data-nav-action]');
    if (!button || button.disabled) return;
    event.preventDefault();
    const action = button.dataset.bridgeAction || button.dataset.navAction;
    let payload = {};
    try { payload = button.dataset.bridgePayload ? JSON.parse(button.dataset.bridgePayload) : {}; } catch (e) {}
    if (action === 'uninstall-apply') { payload.selected_ids = ids('[data-item-id]'); }
    if (action === 'updates-apply') { payload.ids = ids('[data-update-id]'); }
    button.disabled = true;
    button.classList.add('is-busy');   // 立刻有反馈：转圈，而不是等下一次刷新
    try { await window.maccleanerAction(action, payload); }
    catch (error) { button.disabled = false; alert(error.message); }
  });
  setInterval(() => fetch('/ready', {credentials:'same-origin',cache:'no-store'}).catch(()=>{}), 15000);
  addEventListener('pagehide', () => fetch('/closed', {credentials:'same-origin',keepalive:true}).catch(()=>{}));
})();
</script>
"""


def render_nav(current: str) -> str:
    rows: list[str] = []
    for group in NAV_GROUPS:
        if group.title:
            rows.append(f'<p class="side-group">{html.escape(group.title)}</p>')
        for item in group.items:
            if not item.enabled:
                rows.append(
                    f'<button class="side-item" type="button" disabled aria-disabled="true">{html.escape(item.label)}'
                    f'<span class="side-badge">{html.escape(item.badge or "待实现")}</span></button>'
                )
                continue
            is_current = item.key == current
            cls = "side-item is-current" if is_current else "side-item"
            aria = ' aria-current="page"' if is_current else ""
            rows.append(
                f'<button class="{cls}" type="button" data-nav-action="{html.escape(item.action)}"{aria}>'
                f"{html.escape(item.label)}</button>"
            )
    return '<nav class="side" aria-label="功能导航">' + "".join(rows) + "</nav>"


def state_page(
    payload: dict[str, Any],
    *,
    stage: str,
    title: str,
    body: str,
    actions: str = "",
    current: str = "clean",
    with_nav: bool = True,
    subtitle: str = "",
    meta: str = "",
) -> str:
    """拼一页：顶栏 + 侧栏 + 标题区 + 动作插槽 + 内联脚本。

    `actions` 为空时插槽留空（静态预览与"只读页"都走这条）。
    """
    message = html.escape(str(payload.get("message", "") or ""))
    detail = html.escape(str(payload.get("detail", "") or ""))
    nav_html = render_nav(current) if with_nav else ""
    page = f"""<!doctype html>
<html lang="zh-CN" data-ui-schema="{UI_SCHEMA}" data-stage="{html.escape(stage)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<style>{STYLE}</style>
</head>
<body class="{'has-nav' if with_nav else ''}">
{NAV_SLOT}
<main class="app">
  <header class="topbar">
    <div class="brand">
      <span class="mark">M</span>
      <div>
        <h1>{html.escape(title)}</h1>
        {f'<p class="subtitle">{html.escape(subtitle)}</p>' if subtitle else ''}
      </div>
    </div>
    {f'<div class="topmeta">{html.escape(meta)}</div>' if meta else ''}
  </header>
  <section class="state card">
    <p class="state-head">{html.escape(body)}</p>
    <p class="state-msg">{message}</p>
    <p class="state-detail">{detail}</p>
    {ACTIONS_SLOT}
  </section>
</main>
{_RUNTIME_JS if with_nav else ""}
</body>
</html>
"""
    return page.replace(NAV_SLOT, nav_html).replace(ACTIONS_SLOT, actions)


__all__ = ["ACTIONS_SLOT", "NAV_GROUPS", "NAV_SLOT", "NavGroup", "NavItem", "render_nav", "state_page"]
