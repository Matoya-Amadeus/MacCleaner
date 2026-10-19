"""配色与基础样式（2026-10-18 迁入）。

只有一套来源：页面里任何颜色都必须引用这里的变量（`var(--accent)` 等）。
上一版界面曾把深色值硬编码进某个页面，导致"调品牌色时有一页不跟着变"——这里用单点定义避免重演。
浅色为主，`prefers-color-scheme:dark` 时切深色变体；两套都只改变量。
"""
from __future__ import annotations

STYLE = """
:root{
  color-scheme:light dark;
  --bg:#f4f8f5; --surface:#ffffff; --surface-muted:#eaf1ec;
  --text:#142019; --muted:#5c7265; --line:#d7e3da;
  --accent:#0e8a62; --accent-soft:#e0f4ea; --warn:#9a6500; --danger:#b42318;
  --shadow:0 8px 24px rgba(16,42,32,.08); --on-accent:#ffffff;
  font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text",system-ui,sans-serif;
}
@media(prefers-color-scheme:dark){
  :root{
    --bg:#0c1210; --surface:#141b18; --surface-muted:#1c2622;
    --text:#e8f2ec; --muted:#93a69c; --line:#253028;
    --accent:#3ecf9a; --accent-soft:#15352b; --warn:#f3bd58; --danger:#ff9c91;
    --shadow:0 10px 28px rgba(0,0,0,.32); --on-accent:#0a1410;
  }
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font-size:14px;line-height:1.5}
body.has-nav{display:grid;grid-template-columns:236px minmax(0,1fr);min-height:100vh}
.side{border-right:1px solid var(--line);padding:18px 12px;display:flex;flex-direction:column;gap:4px}
.side-group{margin:14px 8px 6px;font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
.side-item{display:flex;justify-content:space-between;gap:8px;border:1px solid transparent;border-radius:8px;
  padding:9px 10px;background:transparent;color:var(--text);font:inherit;text-align:left;cursor:pointer}
.side-item:hover{border-color:var(--line);background:var(--surface-muted)}
.side-item.is-current{background:var(--accent-soft);color:var(--accent);font-weight:650}
.side-item[disabled]{color:var(--muted);cursor:not-allowed;opacity:.6}
.side-badge{font-size:11px;border-radius:999px;padding:1px 7px;background:var(--surface-muted);color:var(--muted)}
.app{padding:22px 24px 60px;max-width:1100px}
.topbar{display:flex;align-items:center;gap:11px;margin-bottom:18px}
.mark{width:32px;height:32px;border-radius:9px;background:var(--accent);color:var(--on-accent);
  display:grid;place-items:center;font-weight:800}
.topbar h1{font-size:20px;margin:0}
.card{background:var(--surface);border:1px solid var(--line);border-radius:12px;box-shadow:var(--shadow)}
.state{padding:26px}
.state-head{font-size:26px;line-height:1.2;margin:0 0 8px}
.state-msg{color:var(--muted);margin:0}
.state-detail{color:var(--muted);font-size:12px;margin:10px 0 0}
.actions{display:flex;gap:10px;margin-top:22px}
.button{border:1px solid var(--line);border-radius:8px;padding:9px 14px;background:var(--surface);
  color:var(--text);font:inherit;cursor:pointer}
.button:hover{border-color:var(--accent)}
.button.primary{background:var(--accent);border-color:var(--accent);color:var(--on-accent)}
/* 圆钮常与 `primary` 叠用：`primary` 把字色设成 `--on-accent`（深色），这里又把背景换成 `--surface`
   （深色）→ 深字压深底，按钮几乎看不见（2026-10-18 看快照才发现）。所以必须**显式重设字色**。 */
.button.round{width:132px;height:132px;border-radius:999px;font-size:17px;font-weight:650;
  background:var(--surface);color:var(--text);
  border:1.5px solid var(--accent);box-shadow:0 0 0 10px var(--surface-muted),var(--shadow)}
.button.round:hover{border-color:var(--accent);color:var(--accent)}
.row{display:flex;justify-content:space-between;gap:12px;align-items:center;padding:11px 14px;border-top:1px solid var(--line)}
.row:first-of-type{border-top:0}
.row .meta{color:var(--muted);font-size:12px}
.pill{font-size:11px;border-radius:999px;padding:2px 8px;white-space:nowrap;
  background:var(--surface-muted);color:var(--muted)}
.pill.ok{background:var(--accent-soft);color:var(--accent)}
.muted{color:var(--muted);font-size:12px}
.hero{font-size:40px;font-weight:700;letter-spacing:-.02em;margin:6px 0 0;color:var(--accent)}
.group-title{margin:18px 0 6px;font-size:12px;letter-spacing:.04em;color:var(--muted)}
/* `.row` 是 space-between（用于"名称…数值"两端对齐），但勾选行里它是**错的**：
   复选框会被顶到最左、名称甩到最右（2026-10-18 看原生快照发现）。勾选行改成左对齐 + 文字占满。 */
label.row.opt{display:flex;align-items:center;gap:10px;justify-content:flex-start;cursor:pointer}
label.row.opt > div{flex:1;min-width:0}
label.row.opt input{margin:0;flex:0 0 auto}
details summary{cursor:pointer;color:var(--muted);font-size:13px}

/* ---- 加载态（2026-10-19）---- */
/* 用 conic-gradient + mask 画旋转环：不引入图片、不改布局、任何尺寸都能复用。 */
.loader{width:22px;height:22px;border-radius:999px;flex:none;
  background:conic-gradient(from 0deg, transparent 0 25%, var(--accent) 75% 100%);
  -webkit-mask:radial-gradient(farthest-side, transparent calc(100% - 3px), #000 calc(100% - 2px));
  mask:radial-gradient(farthest-side, transparent calc(100% - 3px), #000 calc(100% - 2px));
  animation:mc-spin 900ms linear infinite}
.loader.lg{width:34px;height:34px}
@keyframes mc-spin{to{transform:rotate(360deg)}}

/* 加载头：转圈 + 两行说明，左对齐（不要复用 `.row`，那是 space-between）。 */
.loading-head{display:flex;align-items:center;gap:14px;margin:6px 0 0}
.loading-title{font-size:14px;font-weight:600}
.skeleton-stack{margin:20px 0 2px}

/* 骨架：告诉用户"内容在路上"，而不是让他盯着一行静止的字。 */
.skeleton{height:12px;border-radius:6px;background:var(--surface-muted);position:relative;overflow:hidden}
.skeleton + .skeleton{margin-top:10px}
.skeleton::after{content:"";position:absolute;inset:0;transform:translateX(-100%);
  background:linear-gradient(90deg, transparent, var(--line), transparent);animation:mc-sheen 1.2s ease-in-out infinite}
.skeleton.row{height:44px;border-radius:10px}
.skeleton.w40{width:40%} .skeleton.w65{width:65%} .skeleton.w85{width:85%}
@keyframes mc-sheen{to{transform:translateX(100%)}}

/* 按钮忙碌态：点击后立刻有反馈，不用等下一次刷新。 */
.button.is-busy{position:relative;color:transparent}
.button.is-busy::after{content:"";position:absolute;inset:0;margin:auto;width:14px;height:14px;
  border-radius:999px;border:2px solid var(--line);border-top-color:var(--accent);
  animation:mc-spin 700ms linear infinite}

/* 尊重系统"减少动态效果"。 */
@media (prefers-reduced-motion: reduce){
  .loader,.skeleton::after,.button.is-busy::after{animation:none}
  .skeleton::after{display:none}
}
"""

__all__ = ["STYLE"]
