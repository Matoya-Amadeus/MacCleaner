"""配色与基础样式（2026-10-19 按设计 token 重做）。

只有一套来源：页面里任何颜色都必须引用这里的变量（`var(--accent)` 等）。
上一版界面曾把深色值硬编码进某个页面，导致"调品牌色时有一页不跟着变"——这里用单点定义避免重演。

**深色为主**（清理工具多在暗环境用），浅色是同结构的变体，只改变量。
所有尺寸/字号也走 token：上一版 11/14/26 这类"手感值"散落在各处，改一处对不齐另一处。
"""
from __future__ import annotations

STYLE = """
:root{
  color-scheme:dark light;

  /* 层次：bg < surface < surface-2，靠发丝线分隔，而不是靠深灰硬堆 */
  --bg:#0A0E0D; --surface:#101614; --surface-2:#151C1A;
  --line:rgba(255,255,255,.07); --line-strong:rgba(255,255,255,.14);

  /* 文字三级 */
  --text:#E9F1ED; --text-2:#A8B7B0; --muted:#7C8C85;

  /* 品牌色只做强调，不做大面积填充（否则数值对比度必掉） */
  --accent:#35D0A1; --accent-soft:rgba(53,208,161,.14);
  --on-accent:#04120D; --warn:#F5C05A; --danger:#FF8A7A;

  /* 阴影两级 */
  --e1:0 1px 0 rgba(0,0,0,.35);
  --e2:0 10px 28px rgba(0,0,0,.35);

  /* 形状与间距 token */
  --r-control:6px; --r-row:10px; --r-card:14px;
  --sp-1:4px; --sp-2:8px; --sp-3:12px; --sp-4:16px; --sp-5:24px; --sp-6:32px;

  /* 字阶 */
  --fs-title-xl:28px; --fs-title-l:22px; --fs-title-m:17px;
  --fs-body:14px; --fs-meta:12px; --fs-label:11px;
  --font:-apple-system,BlinkMacSystemFont,"SF Pro Text","PingFang SC",system-ui,sans-serif;
}
@media(prefers-color-scheme:light){
  :root{
    --bg:#F6F8F7; --surface:#FFFFFF; --surface-2:#F1F5F2;
    --line:rgba(16,24,20,.08); --line-strong:rgba(16,24,20,.16);
    --text:#101815; --text-2:#3D4B45; --muted:#6B7C74;
    --accent:#0E8A62; --accent-soft:rgba(14,138,98,.10);
    --on-accent:#FFFFFF; --warn:#9A6500; --danger:#B42318;
    --e1:0 1px 0 rgba(16,24,20,.06);
    --e2:0 8px 24px rgba(16,24,20,.08);
  }
}

*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
  font:400 var(--fs-body)/1.5 var(--font);-webkit-font-smoothing:antialiased}
body.has-nav{display:grid;grid-template-columns:208px minmax(0,1fr);min-height:100vh}

/* ---- 侧栏：玻璃层，只放真能点的入口 ---- */
.side{border-right:1px solid var(--line);padding:var(--sp-4) var(--sp-3);
  display:flex;flex-direction:column;gap:2px;background:var(--surface)}
.side-group{margin:var(--sp-4) var(--sp-2) var(--sp-1);font-size:var(--fs-label);font-weight:600;
  letter-spacing:.02em;color:var(--muted)}
.side-item{display:flex;justify-content:space-between;align-items:center;gap:var(--sp-2);
  min-height:32px;padding:0 10px;border:0;border-radius:var(--r-control);
  background:transparent;color:var(--text-2);font:inherit;text-align:left;cursor:pointer;
  transition:background 120ms ease,color 120ms ease}
.side-item:hover{background:var(--surface-2);color:var(--text)}
.side-item.is-current{background:var(--accent-soft);color:var(--accent);font-weight:600}
.side-item[disabled]{color:var(--muted);cursor:not-allowed;opacity:.6}
.side-badge{font-size:var(--fs-label);border-radius:999px;padding:1px 7px;
  background:var(--surface-2);color:var(--muted)}

/* ---- 内容区：单列、限宽、居中 ---- */
.app{padding:var(--sp-5) var(--sp-5) 72px;width:100%;max-width:960px;margin:0 auto}

/* ---- 页头：标题 + 副标题 + 右侧元信息（数据时间/数量） ---- */
.topbar{display:flex;align-items:flex-start;justify-content:space-between;gap:var(--sp-3);
  margin-bottom:var(--sp-4)}
.topbar .brand{display:flex;align-items:center;gap:10px;min-width:0}
.mark{width:26px;height:26px;border-radius:8px;background:var(--accent-soft);color:var(--accent);
  display:grid;place-items:center;font-weight:700;font-size:13px;flex:none}
.topbar h1{font-size:var(--fs-title-l);font-weight:600;letter-spacing:-.01em;margin:0;line-height:1.25}
.topbar .subtitle{color:var(--muted);font-size:var(--fs-meta);margin:2px 0 0}
.topbar .topmeta{color:var(--muted);font-size:var(--fs-meta);white-space:nowrap;padding-top:2px}

/* ---- 卡片与状态区 ---- */
.card{background:var(--surface);border:1px solid var(--line);border-radius:var(--r-card);box-shadow:var(--e1)}
.state{padding:var(--sp-5)}
.state-head{font-size:var(--fs-title-m);font-weight:600;line-height:1.3;margin:0 0 6px}
.state-msg{color:var(--text-2);margin:0}
.state-detail{color:var(--muted);font-size:var(--fs-meta);margin:8px 0 0}
.hero{font-size:34px;font-weight:700;letter-spacing:-.02em;margin:6px 0 0;color:var(--accent);
  font-variant-numeric:tabular-nums}

/* ---- 按钮：三级（primary / 默认 secondary / ghost 由透明底表达） ---- */
.actions{display:flex;gap:var(--sp-2);margin-top:var(--sp-5);flex-wrap:wrap}
.button{min-height:32px;padding:0 12px;border:1px solid var(--line-strong);border-radius:var(--r-control);
  background:var(--surface-2);color:var(--text);font:inherit;cursor:pointer;
  transition:background 120ms ease,border-color 120ms ease}
.button:hover{background:var(--surface);border-color:var(--accent)}
.button.primary{background:var(--accent);border-color:var(--accent);color:var(--on-accent);font-weight:600}
.button.primary:hover{filter:brightness(1.06)}
.button:focus-visible,.side-item:focus-visible,label.row.opt:focus-within{
  outline:2px solid var(--accent);outline-offset:2px}

/* 圆钮只用在落地页那一个"唯一动作"上；常与 primary 叠用，
   所以必须**显式重设字色**（primary 的字色在浅底上不可读，2026-10-18 快照发现过）。 */
.button.round{width:120px;height:120px;border-radius:999px;font-size:var(--fs-title-m);font-weight:600;
  background:var(--surface);color:var(--text);border:1.5px solid var(--accent);
  box-shadow:0 0 0 8px var(--accent-soft)}
.button.round:hover{color:var(--accent)}

/* 三级按钮的第三级：用于"退出/稍后"这类不该抢注意力的动作 */
.button.ghost{background:transparent;border-color:transparent;color:var(--text-2)}
.button.ghost:hover{background:var(--surface-2);color:var(--text);border-color:transparent}
.button[disabled]{opacity:.55;cursor:not-allowed}

/* 空状态：一句结论 + 一句下一步；不要只留一行灰字 */
.empty{display:flex;flex-direction:column;align-items:center;gap:10px;padding:36px 12px 8px;text-align:center}
.empty svg{width:44px;height:44px;color:var(--muted);opacity:.9}
.empty .empty-title{font-size:var(--fs-title-m);font-weight:600;margin:0}
.empty .empty-text{color:var(--muted);font-size:var(--fs-meta);margin:0;max-width:44ch}

/* 完成页的三格数据（可恢复/失败/跳过） */
.stats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:var(--sp-2);margin-top:var(--sp-4)}
.stat{background:var(--surface-2);border-radius:var(--r-row);padding:10px 12px}
.stat .k{color:var(--muted);font-size:var(--fs-label)}
.stat .v{font-size:var(--fs-title-m);font-weight:600;font-variant-numeric:tabular-nums;margin-top:2px}

/* Toast：替代 alert()——原生弹窗会打断操作、也不跟随主题 */
.toast{position:fixed;left:50%;bottom:24px;transform:translateX(-50%) translateY(8px);opacity:0;
  background:var(--surface-2);border:1px solid var(--line-strong);border-radius:10px;
  padding:10px 14px;font-size:var(--fs-body);box-shadow:var(--e2);z-index:50;max-width:72vw;
  transition:opacity .18s ease,transform .18s ease;pointer-events:none}
.toast.is-on{opacity:1;transform:translateX(-50%) translateY(0)}
.toast.is-error{border-color:var(--danger);color:var(--danger)}

/* ---- 列表行：44px、hover 有反馈、数值用等宽数字 ---- */
.row{display:flex;justify-content:space-between;gap:var(--sp-3);align-items:center;
  min-height:44px;padding:8px 0;border-top:1px solid var(--line)}
.row:first-of-type{border-top:0}
.row:hover{background:transparent}
.row .meta{color:var(--muted);font-size:var(--fs-meta)}
.row .value{font-variant-numeric:tabular-nums}
/* `.row` 是两端对齐（"名称…数值"），但勾选行里它是**错的**：复选框会被顶到最左、名称甩到最右。
   勾选行单独左对齐，并让文字块占满剩余宽度。 */
label.row.opt{display:flex;align-items:center;gap:10px;justify-content:flex-start;cursor:pointer;
  border-radius:var(--r-row);padding:8px 6px;margin:0 -6px}
label.row.opt:hover{background:var(--surface-2)}
label.row.opt > div{flex:1;min-width:0}
label.row.opt input{margin:0;flex:0 0 auto;accent-color:var(--accent)}

.pill{display:inline-flex;align-items:center;height:20px;padding:0 8px;border-radius:999px;
  font-size:var(--fs-label);white-space:nowrap;background:var(--surface-2);color:var(--muted)}
.pill.ok{background:var(--accent-soft);color:var(--accent)}
.muted{color:var(--muted);font-size:var(--fs-meta)}
.group-title{margin:var(--sp-4) 0 var(--sp-1);font-size:var(--fs-label);font-weight:600;
  letter-spacing:.02em;color:var(--muted)}
details summary{cursor:pointer;color:var(--muted);font-size:13px}

/* ---- 加载态 ---- */
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
.loading-title{font-size:var(--fs-body);font-weight:600}
.skeleton-stack{margin:var(--sp-5) 0 2px}

/* 骨架：告诉用户"内容在路上"，而不是让他盯着一行静止的字。 */
.skeleton{height:12px;border-radius:6px;background:var(--surface-2);position:relative;overflow:hidden}
.skeleton + .skeleton{margin-top:10px}
.skeleton::after{content:"";position:absolute;inset:0;transform:translateX(-100%);
  background:linear-gradient(90deg, transparent, var(--line), transparent);
  animation:mc-sheen 1.2s ease-in-out infinite}
.skeleton.row{height:44px;border-radius:var(--r-row)}
.skeleton.w40{width:40%} .skeleton.w65{width:65%} .skeleton.w85{width:85%}
@keyframes mc-sheen{to{transform:translateX(100%)}}

/* 按钮忙碌态：点击后立刻有反馈，不用等下一次刷新。 */
.button.is-busy{position:relative;color:transparent}
.button.is-busy::after{content:"";position:absolute;inset:0;margin:auto;width:14px;height:14px;
  border-radius:999px;border:2px solid var(--line-strong);border-top-color:var(--accent);
  animation:mc-spin 700ms linear infinite}

/* 尊重系统"减少动态效果"。 */
@media (prefers-reduced-motion: reduce){
  .loader,.skeleton::after,.button.is-busy::after{animation:none}
  .skeleton::after{display:none}
}
"""

__all__ = ["STYLE"]
