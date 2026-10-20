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
    NavGroup("清理", (NavItem("clean", "Mac 清理", "home"),)),
    NavGroup(
        "应用",
        (
            NavItem("uninstall", "软件卸载", "uninstall-list"),
            NavItem("updates", "软件更新", "updates-open"),
            NavItem("orphans", "残留体检", "orphans-open"),
        ),
    ),
    NavGroup(
        "系统",
        (
            NavItem("disk", "磁盘", "disk-open"),
            NavItem("large", "大文件", "large-open"),
            NavItem("system", "系统状态", "system-open"),
            NavItem("history", "清理历史", "history-open"),
        ),
    ),
    NavGroup("技能", (NavItem("skills", "可调用的 Skill", "skills-open"),)),
)


# 页面运行时（2026-10-18）：把点击变成一次 `/action` 投递。
# 为什么不用行内 onclick：动作必须带 CSRF 头，且要按勾选框收集 id——集中一处才不会各页各写一套。
_RUNTIME_JS = """
<script>
(function(){
  // ---- 复选框多选（2026-10-19）：Web 视图里补回 macOS 表格的手感 ----
  // Shift+点击 = 连选；Cmd/Ctrl+点击 = 加选（复选框本身行为）；批量条实时更新"已选 N 个"。
  const CHECKBOXES = '[data-target-id],[data-item-id],[data-update-id],[data-app-path]';
  let lastBox = null;

  // 统一刷新"已选 N / 共 M"，并按选择状态禁用主操作（两类列表共用）。
  function refreshSelection(){
    const apps = Array.from(document.querySelectorAll('[data-app-path]'));
    const updates = Array.from(document.querySelectorAll('[data-update-id]'));
    const picked = list => list.filter(box => box.checked).length;

    const appLabel = document.getElementById('mc-selected-count');
    if (appLabel && apps.length) {
      appLabel.textContent = '已选 ' + picked(apps) + ' / ' + apps.length;
    }
    const appBtn = document.querySelector('[data-bridge-action="uninstall-batch"]');
    if (appBtn && apps.length) appBtn.disabled = picked(apps) === 0;

    const upLabel = document.getElementById('mc-updates-count');
    if (upLabel && updates.length) {
      upLabel.textContent = '已选 ' + picked(updates) + ' / ' + updates.length;
    }
    const upBtn = document.querySelector('[data-bridge-action="updates-apply"]');
    if (upBtn && updates.length) upBtn.disabled = picked(updates) === 0;

    const larges = Array.from(document.querySelectorAll('[data-large-path]'));
    const largeLabel = document.getElementById('mc-large-count');
    if (largeLabel && larges.length) largeLabel.textContent = '已选 ' + picked(larges) + ' / ' + larges.length;
    const largeBtn = document.querySelector('[data-bridge-action="large-apply"]');
    if (largeBtn && larges.length) largeBtn.disabled = picked(larges) === 0;

    const orphans = Array.from(document.querySelectorAll('[data-orphan-path]'));
    const orphanLabel = document.getElementById('mc-orphans-count');
    if (orphanLabel && orphans.length) {
      orphanLabel.textContent = '已选 ' + picked(orphans) + ' / ' + orphans.length;
    }
    const orphanBtn = document.querySelector('[data-bridge-action="orphans-apply"]');
    if (orphanBtn && orphans.length) orphanBtn.disabled = picked(orphans) === 0;

    // 三态同步：全选框必须反映真实状态（部分选中 = indeterminate）。
    // 不做这件事时，取消一整组后主框仍是"已勾选"，再点一下反而把剩下的也清空。
    function sync(master, boxes) {
      if (!master || !boxes.length) return;
      const chosen = boxes.filter(box => box.checked).length;
      master.checked = chosen === boxes.length;
      master.indeterminate = chosen > 0 && chosen < boxes.length;
    }
    sync(document.querySelector('[data-select-all-apps]'), apps);
    sync(document.querySelector('[data-select-all-updates]'), updates);
    sync(document.querySelector('[data-select-all-orphans]'), orphans);
    sync(document.querySelector('[data-select-all-large]'), larges);
    document.querySelectorAll('[data-select-group]').forEach((master) => {
      const group = master.closest('.group');
      if (group) sync(master, Array.from(group.querySelectorAll('[data-update-id]')));
    });
  }

  function selectRange(from, to){
    const boxes = Array.from(document.querySelectorAll(CHECKBOXES));
    const a = boxes.indexOf(from), b = boxes.indexOf(to);
    if (a < 0 || b < 0) return;
    const [start, end] = a <= b ? [a, b] : [b, a];
    for (let i = start; i <= end; i++) boxes[i].checked = to.checked;
  }

  // 页面内 toast 取代 alert()：原生弹窗会打断操作，而且不跟随深色主题。
  function toast(message){
    let el = document.getElementById('mc-toast');
    if (!el) { el = document.createElement('div'); el.id = 'mc-toast'; document.body.appendChild(el); }
    el.className = 'toast is-error is-on';
    el.textContent = message;
    clearTimeout(window.__mcToastTimer);
    window.__mcToastTimer = setTimeout(() => el.classList.remove('is-on'), 3200);
  }
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
      .filter(node => node.checked)
      .map(node => node.dataset.itemId || node.dataset.updateId || node.dataset.targetId);
  document.addEventListener('click', async (event) => {
    if (suppressClick) { suppressClick = false; event.preventDefault(); event.stopPropagation(); return; }
    // 排序：纯前端重排（不重新扫盘、不发页面），再点一次反向。
    const sortBtn = event.target.closest('[data-sort]');
    if (sortBtn) {
      const container = document.querySelector('[data-sortable]');
      if (!container) return;
      const key = sortBtn.dataset.sort;
      // 首次点击用按钮上声明的方向（体积=降序、名称=升序），再点才翻转。
      // 之前写成"和当前方向取反"，结果首次点"体积"变成了升序。
      const dir = sortBtn.dataset.dir || (key === 'bytes' ? 'desc' : 'asc');
      const desc = dir === 'desc';
      sortBtn.dataset.dir = desc ? 'asc' : 'desc';
      document.querySelectorAll('[data-sort]').forEach(btn => btn.classList.remove('is-on'));
      sortBtn.classList.add('is-on');
      const rows = Array.from(container.children).filter(el => el.hasAttribute('data-sort-text'));
      rows.sort((a, b) => {
        if (key === 'bytes') {
          const av = Number(a.dataset.sortBytes || 0), bv = Number(b.dataset.sortBytes || 0);
          return desc ? bv - av : av - bv;
        }
        const av = (a.dataset.sortText || ''), bv = (b.dataset.sortText || '');
        const cmp = av.localeCompare(bv, 'zh-CN');
        return desc ? -cmp : cmp;
      });
      rows.forEach(row => container.appendChild(row));
      return;
    }

    // treemap 方块：点一下进入该目录（键盘 Enter 也可）。
    const cell = event.target.closest('[data-treemap-path]');
    if (cell) {
      window.maccleanerAction('disk-open', { path: cell.dataset.treemapPath })
        .catch((error) => toast(error.message));
      return;
    }

    // 点行（不是勾选框/按钮）= 触发这一行的主操作（卸载 → 残留预览）。
    const row = event.target.closest('[data-row]');
    if (row && !event.target.closest('input, button, a, [data-menu]')) {
      const action = row.querySelector('[data-bridge-action]');
      if (action) { event.preventDefault(); action.click(); return; }
    }

    // 复选框：处理连选与批量计数，不产生动作。
    const box = event.target.closest('input[type="checkbox"]');
    if (box && box.matches(CHECKBOXES)) {
      if (event.shiftKey && lastBox && lastBox !== box && box.matches('[data-app-path]')) {
        selectRange(lastBox, box);
      }
      lastBox = box;
          refreshSelection();
      return;
    }
    const selectApps = event.target.closest('[data-select-all-apps]');
    if (selectApps) {
      document.querySelectorAll('[data-app-path]').forEach(box => { box.checked = selectApps.checked; });
      refreshSelection();
      return;
    }
    const selectUpdates = event.target.closest('[data-select-all-updates]');
    if (selectUpdates) {
      document.querySelectorAll('[data-update-id]').forEach(box => { box.checked = selectUpdates.checked; });
      document.querySelectorAll('[data-select-group]').forEach(box => { box.checked = selectUpdates.checked; });
      refreshSelection();
      return;
    }
    const selectLarge = event.target.closest('[data-select-all-large]');
    if (selectLarge) {
      document.querySelectorAll('[data-large-path]').forEach(box => { box.checked = selectLarge.checked; });
      refreshSelection();
      return;
    }
    const selectOrphans = event.target.closest('[data-select-all-orphans]');
    if (selectOrphans) {
      document.querySelectorAll('[data-orphan-path]').forEach(box => { box.checked = selectOrphans.checked; });
      refreshSelection();
      return;
    }
    // 组头全选：只影响**这一组**内的行（共同区域的直接后果）。
    const selectGroup = event.target.closest('[data-select-group]');
    if (selectGroup) {
      const group = selectGroup.closest('.group');
      if (group) {
        group.querySelectorAll('[data-update-id]').forEach(box => { box.checked = selectGroup.checked; });
      }
      refreshSelection();
      return;
    }
    // 全选框：只是前端联动，不产生动作（审阅页/更新页都可能用到）。
    const selectAll = event.target.closest('[data-select-all]');
    if (selectAll) {
      document.querySelectorAll('[data-target-id]').forEach((node) => { node.checked = selectAll.checked; });
      return;
    }
    // 两种按钮都要接：正文动作（data-bridge-action）与侧栏导航（data-nav-action）。
    // 2026-10-18 真机发现：原来只监听前者，于是**四个侧栏入口点了完全没反应**。
    const button = event.target.closest('[data-bridge-action],[data-nav-action]');
    if (!button || button.disabled) return;
    event.preventDefault();
    const action = button.dataset.bridgeAction || button.dataset.navAction;
    let payload = {};
    try { payload = button.dataset.bridgePayload ? JSON.parse(button.dataset.bridgePayload) : {}; } catch (e) {}
    // 清理的批准必须带**用户勾选的那几组**：不带就是"全部"，与界面上"我取消了几项"不符。
    if (action === 'approval') { payload.approved_ids = ids('[data-target-id]'); }
    if (action === 'large-apply') {
      payload.paths = Array.from(document.querySelectorAll('[data-large-path]'))
        .filter(box => box.checked)
        .map(box => box.dataset.largePath);
      if (!payload.paths.length) { toast('先勾选要清理的文件'); return; }
    }
    if (action === 'orphans-apply') {
      payload.paths = Array.from(document.querySelectorAll('[data-orphan-path]'))
        .filter(box => box.checked)
        .map(box => box.dataset.orphanPath);
      if (!payload.paths.length) { toast('先勾选要清理的项'); return; }
    }
    if (action === 'confirm') {
      const risk = document.querySelector('[data-confirm-risk]');
      payload.confirmed_risk = !!(risk && risk.checked);
    }
    if (action === 'uninstall-apply') { payload.selected_ids = ids('[data-item-id]'); }
    if (action === 'updates-apply') { payload.ids = ids('[data-update-id]'); }
    // 批量卸载：把勾选的应用交出去（路径只用于定位，执行时内核自己再建计划）
    if (action === 'uninstall-batch') {
      payload.apps = Array.from(document.querySelectorAll('[data-app-path]'))
        .filter(box => box.checked)
        .map(box => ({ path: box.dataset.appPath, bundle_id: box.dataset.appBundle, name: box.dataset.appName }));
      if (!payload.apps.length) { toast('先勾选要卸载的应用'); return; }
    }
    button.disabled = true;
    button.classList.add('is-busy');   // 立刻有反馈：转圈，而不是等下一次刷新
    try { await window.maccleanerAction(action, payload); }
    catch (error) { button.disabled = false; toast(error.message); }
  });
  refreshSelection();
  // ---- 拖拽连选（2026-10-20）：按住行往下拖，区间内的勾选框一起变 ----
  // 与 macOS 列表一致：从"未勾"的行起拖 = 全勾上；从"已勾"的行起拖 = 全取消。
  // 只在移动超过 4px 后才算拖拽，否则点击仍按原语义（打开/勾选）。
  let dragState = null;
  let suppressClick = false;

  function rowsIn(container) {
    return Array.from(container.querySelectorAll('[data-select-row]'))
      .filter(row => {
        const box = row.querySelector('input[type="checkbox"]');
        return box && !box.disabled && row.offsetParent !== null;
      });
  }

  function paintTo(target) {
    if (!dragState) return;
    const rows = rowsIn(dragState.container);
    const from = rows.indexOf(dragState.anchor);
    const to = rows.indexOf(target);
    if (from < 0 || to < 0) return;
    const [start, end] = from <= to ? [from, to] : [to, from];
    for (let index = start; index <= end; index += 1) {
      const box = rows[index].querySelector('input[type="checkbox"]');
      if (box) box.checked = dragState.value;
    }
    dragState.moved = true;
    refreshSelection();
  }

  document.addEventListener('mousedown', (event) => {
    if (event.button !== 0 || event.target.closest('input, button, a')) return;
    const row = event.target.closest('[data-select-row]');
    if (!row) return;
    const box = row.querySelector('input[type="checkbox"]');
    if (!box || box.disabled) return;
    dragState = {
      anchor: row,
      // 整页范围：列表被按字母/来源拆成了多个 `.rows` 容器，拖拽必须能跨组。
      container: document,
      value: !box.checked,
      startX: event.clientX,
      startY: event.clientY,
      moved: false,
    };
  });

  document.addEventListener('mousemove', (event) => {
    if (!dragState) return;
    const dx = Math.abs(event.clientX - dragState.startX);
    const dy = Math.abs(event.clientY - dragState.startY);
    // 真实鼠标用坐标命中最准；合成事件（验收脚本）下 elementFromPoint 可能为空，退回事件目标。
    const under = document.elementFromPoint(event.clientX, event.clientY);
    const row =
      (under && under.closest ? under.closest('[data-select-row]') : null) ||
      (event.target && event.target.closest ? event.target.closest('[data-select-row]') : null);
    if (!row) return;
    // 跨行即算拖拽（合成事件没有坐标差）；同一行内则要求真的移动过 4px。
    if (!dragState.moved && row === dragState.anchor && dx < 4 && dy < 4) return;
    paintTo(row);
  });

  document.addEventListener('mouseup', () => {
    if (dragState && dragState.moved) {
      // 拖完会紧跟一次 click（可能被当成"打开这一行"）：吃掉它。
      suppressClick = true;
      setTimeout(() => { suppressClick = false; }, 0);
    }
    dragState = null;
  });

  // ---- 右键菜单（2026-10-19）：复制路径 / 在 Finder 中显示 ----
  // 只对带 data-reveal-path 的行生效；"在 Finder 中显示"要经过会话白名单校验。
  // 复制路径：安全上下文用剪贴板 API，否则退回隐藏 textarea（file:// 或旧内核）。
  function copyText(text){
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
    const area = document.createElement('textarea');
    area.value = text;
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    try { document.execCommand('copy'); } finally { area.remove(); }
    return Promise.resolve();
  }

  function closeMenu(){
    const el = document.getElementById('mc-menu');
    if (el) el.remove();
  }

  document.addEventListener('contextmenu', (event) => {
    const row = event.target.closest('[data-reveal-path]');
    if (!row) return;
    event.preventDefault();
    closeMenu();
    const path = row.dataset.revealPath;
    const menu = document.createElement('div');
    menu.id = 'mc-menu';
    menu.className = 'ctx';
    menu.innerHTML =
      '<button type="button" data-menu="copy">复制路径</button>' +
      '<button type="button" data-menu="reveal">在 Finder 中显示</button>';
    menu.style.left = Math.min(event.clientX, window.innerWidth - 180) + 'px';
    menu.style.top = Math.min(event.clientY, window.innerHeight - 90) + 'px';
    menu.addEventListener('click', async (click) => {
      const item = click.target.closest('[data-menu]');
      if (!item) return;
      closeMenu();
      if (item.dataset.menu === 'copy') {
        try { await copyText(path); toast('已复制：' + path); }
        catch (error) { toast('复制失败，请手动选择路径'); }
        return;
      }
      window.maccleanerAction('reveal', { path }).catch((error) => toast(error.message));
    });
    document.body.appendChild(menu);
  });

  // ---- 键盘快捷键（2026-10-19）：补回表格的键鼠手感 ----
  // ⌘A 全选（再按一次全不选）、Esc 关闭菜单、Enter 触发主操作。
  // 注意：Esc **不**映射到"取消会话"——误触会丢掉一次已经点好的清理。
  document.addEventListener('keydown', (event) => {
    // 事件可能派发到 document 本身（没有 closest），先归一化到元素再判断。
    const source = event.target instanceof Element ? event.target : document.body;
    const inField = source.closest('input, textarea, select, [contenteditable]');
    if (inField && inField.type !== 'checkbox') return;

    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'a') {
      const boxes = Array.from(document.querySelectorAll(CHECKBOXES)).filter(box => !box.disabled);
      if (!boxes.length) return;
      event.preventDefault();
      const shouldCheck = boxes.some(box => !box.checked);
      boxes.forEach(box => { box.checked = shouldCheck; });
      refreshSelection();
      return;
    }
    if (event.key === 'Enter' && event.target.closest('[data-treemap-path]')) {
      const cell = event.target.closest('[data-treemap-path]');
      window.maccleanerAction('disk-open', { path: cell.dataset.treemapPath })
        .catch((error) => toast(error.message));
      return;
    }
    if (event.key === 'Escape') { closeMenu(); return; }
    if (event.key === 'Enter') {
      const primary = document.querySelector('[data-bridge-action].primary');
      if (primary && !primary.disabled) { event.preventDefault(); primary.click(); }
    }
  });

  // 搜索：按 data-sort-text（小写名字）与文本内容匹配，整组无命中就隐藏该组。
  document.addEventListener('input', (event) => {
    const search = event.target.closest('[data-filter]');
    if (!search) return;
    const needle = search.value.trim().toLowerCase();
    document.querySelectorAll('[data-group]').forEach((group) => {
      let shown = 0;
      const rows = Array.from(group.querySelectorAll('[data-sort-text]'));
      rows.forEach((row) => {
        const text = (row.dataset.sortText || '') + ' ' + (row.textContent || '').toLowerCase();
        const hit = !needle || text.includes(needle);
        row.style.display = hit ? '' : 'none';
        if (hit) shown += 1;
      });
      group.style.display = shown ? '' : 'none';
      if (needle && shown) group.open = true;
      // 组头计数跟着过滤走：显示"命中 / 总数"，否则数字会误导（C 9 个却只看到 3 行）。
      const badge = group.querySelector('summary .meta');
      if (badge) {
        if (!badge.dataset.total) badge.dataset.total = badge.textContent.trim();
        badge.textContent = needle ? (shown + ' / ' + rows.length) : badge.dataset.total;
      }
    });
  });

  document.addEventListener('click', closeMenu);
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeMenu(); });


  // ---- 滚动位置记忆（2026-10-19）：从列表点进详情再返回，回到原位而不是顶部 ----
  // 按 stage 分键：列表页、详情页各自记各自的，不会互相覆盖。
  (function () {
    const scroller = document.querySelector('.app');
    if (!scroller) return;
    const key = 'mc-scroll-' + (document.documentElement.dataset.stage || 'x');
    const saved = Number(sessionStorage.getItem(key) || 0);
    if (saved > 0) requestAnimationFrame(() => { scroller.scrollTop = saved; });
    let pending = false;
    scroller.addEventListener('scroll', () => {
      if (pending) return;
      pending = true;
      requestAnimationFrame(() => {
        sessionStorage.setItem(key, String(scroller.scrollTop));
        pending = false;
        syncAlpha();
      });
    }, { passive: true });
  })();

  // A–Z 索引：点字母跳段；滚动时高亮当前段。
  function syncAlpha() {
    const nav = document.querySelector('.alpha');
    if (!nav) return;
    const groups = Array.from(document.querySelectorAll('[data-group]'));
    if (!groups.length) return;
    // 视口顶端往下 80px 视作"当前段"的分界（工具栏 + 组头吸顶的高度）。
    const line = 80;
    let active = groups[0];
    groups.forEach((group) => {
      if (group.getBoundingClientRect().top <= line) active = group;
    });
    nav.querySelectorAll('[data-jump]').forEach((btn) => {
      btn.classList.toggle('is-on', btn.dataset.jump === active.dataset.letter);
    });
  }

  document.addEventListener('click', (event) => {
    const jump = event.target.closest('[data-jump]');
    if (!jump) return;
    const target = document.querySelector('[data-group][data-letter="' + jump.dataset.jump + '"]');
    if (!target) return;
    const scroller = document.querySelector('.app');
    if (scroller) {
      const top = target.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop - 56;
      scroller.scrollTo({ top: Math.max(0, top), behavior: 'smooth' });
    }
  });

  // 离开进度页（stage 不再是 updating）时清掉计时起点，下次进进度页重新计。
  if (document.documentElement.dataset.stage !== 'updating') {
    sessionStorage.removeItem('mc-progress-start');
  }
  refreshSelection();
  syncAlpha();

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
    hero: str = "",
    toolbar: str = "",
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
    {f'<p class="state-head">{html.escape(body)}</p>' if body else ''}
    {f'<p class="hero">{html.escape(hero)}</p>' if hero else ''}
    {f'<p class="state-msg">{message}</p>' if message else ''}
    {f'<p class="state-detail">{detail}</p>' if detail else ''}
    {f'<div class="toolbar">{toolbar}</div>' if toolbar else ''}
    {ACTIONS_SLOT}
  </section>
</main>
{_RUNTIME_JS if with_nav else ""}
</body>
</html>
"""
    return page.replace(NAV_SLOT, nav_html).replace(ACTIONS_SLOT, actions)


__all__ = ["ACTIONS_SLOT", "NAV_GROUPS", "NAV_SLOT", "NavGroup", "NavItem", "render_nav", "state_page"]
