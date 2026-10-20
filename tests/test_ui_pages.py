"""本地界面（2026-10-18 迁入）：外壳契约与落地页。

界面测试只断言**可核对的契约**（stage、动作、插槽、无硬编码色值、无假入口），
不断言像素或具体文案措辞——否则改个措辞就红，久而久之没人再看它。
"""
from __future__ import annotations

import unittest

from maccleaner.ui.pages import render_landing_html
from maccleaner.ui.shell import ACTIONS_SLOT, NAV_SLOT, NAV_GROUPS, render_nav, state_page


class LandingPageTests(unittest.TestCase):
    def test_landing_is_idle_and_offers_one_big_button(self) -> None:
        page = render_landing_html({"history": {"total_runs": 2, "total_freed_bytes": 2048}})
        self.assertIn('data-stage="idle"', page)
        self.assertIn('data-bridge-action="start"', page, "唯一主按钮要发 start 动作")
        self.assertIn('class="button round primary"', page, "圆形主按钮")
        self.assertIn("不会改动或删除", page, "必须说清扫描只读")

    def test_landing_shows_history_summary(self) -> None:
        page = render_landing_html({"history": {"total_runs": 3, "total_freed_bytes": 1024 * 1024}})
        self.assertIn("已清理 3 次", page)
        self.assertIn("清空废纸篓后才真正释放", page, "回收量口径必须与清理侧一致")

    def test_landing_without_history_says_so(self) -> None:
        page = render_landing_html({})
        self.assertIn("还没有清理记录", page)

    def test_static_preview_has_no_action_button(self) -> None:
        page = render_landing_html({}, interactive=False)
        # 注意：运行时脚本里含 `[data-bridge-action]` 选择器，所以这里查的是**按钮本身**，
        # 不是那个属性名——否则命中脚本注释、误红一次（本批就误红过一次）。
        self.assertNotIn('data-bridge-action="start"', page)
        self.assertNotIn('class="button round primary"', page)

    def test_runtime_binds_nav_buttons_too(self) -> None:
        """侧栏按钮是 `data-nav-action`，正文按钮是 `data-bridge-action`——两者都必须被监听。

        2026-10-18 真机双击发现：只监听后者，导致**四个侧栏入口点了完全没反应**。
        """
        page = render_landing_html({})
        self.assertIn("[data-nav-action]", page, "点击处理器要包含侧栏选择器")
        self.assertIn("dataset.navAction", page, "要能从按钮上取出侧栏动作名")

    def test_round_button_sets_its_own_text_colour(self) -> None:
        """圆钮会与 `primary` 叠用：`primary` 的字色在圆钮背景上不可读，必须显式重设。

        2026-10-18：用户看到的是"按钮几乎看不见"——深色字压在深色底上。
        """
        from maccleaner.ui.theme import STYLE

        segment = STYLE.split(".button.round{", 1)[1].split("}", 1)[0]
        self.assertIn("color:var(--text)", segment, "圆钮必须自己指定字色，不能继承 primary 的 --on-accent")

    def test_checkbox_rows_override_space_between(self) -> None:
        """勾选行必须左对齐：`.row` 的 space-between 会把复选框和名称甩到两头（2026-10-18 快照可见）。"""
        from maccleaner.ui.theme import STYLE

        segment = STYLE.split("label.row.opt{", 1)[1].split("}", 1)[0]
        self.assertIn("justify-content:flex-start", segment)
        self.assertIn("flex:1", STYLE, "文字块要占满剩余宽度")

    def test_progress_page_has_a_loading_animation(self) -> None:
        """进度页要有加载动画与骨架（2026-10-19 用户要求），且对读屏/减动效友好。"""
        from maccleaner.ui.pages import render_progress_html
        from maccleaner.ui.theme import STYLE

        page = render_progress_html({"message": "正在读取应用列表"})
        self.assertIn('class="loader lg"', page, "要有转圈")
        self.assertIn('role="status"', page, "读屏要知道正在忙")
        self.assertIn('aria-live="polite"', page)
        self.assertGreaterEqual(page.count("skeleton"), 3, "骨架行告诉用户内容在路上")
        self.assertIn("@keyframes mc-spin", STYLE)
        self.assertIn("prefers-reduced-motion", STYLE, "要尊重系统减少动效的设置")

    def test_empty_review_uses_empty_state_block(self) -> None:
        """空结果不能只剩一行灰字：要有结论 + 下一步（2026-10-19 组件精修）。"""
        from maccleaner.ui.pages import render_review_html

        page = render_review_html({"candidates": []})
        self.assertIn('class="empty"', page)
        self.assertIn("没有找到可清理的内容", page)
        self.assertIn("data-bridge-action=\"rescan\"", page, "空结果要给下一步")

    def test_completion_shows_three_stats(self) -> None:
        from maccleaner.ui.pages import render_completion_html

        page = render_completion_html(
            {"recoverable_bytes": 4096, "actual_freed_bytes": 0, "failed_count": 1, "skipped_count": 2}
        )
        self.assertEqual(page.count('class="stat"'), 3, "可恢复/失败/跳过三格")
        self.assertIn("4 KiB", page)
        self.assertIn(">1<", page)
        self.assertIn(">2<", page)

    def test_recovery_keeps_the_promise_visible(self) -> None:
        from maccleaner.ui.pages import render_recovery_html

        page = render_recovery_html({"detail": "ValueError: boom"})
        self.assertIn('class="empty"', page)
        self.assertIn("没有删除任何东西", page, "出错时第一眼要看到这句承诺")
        self.assertIn("boom", page, "原因要可见")

    def test_runtime_uses_toast_not_alert(self) -> None:
        from maccleaner.ui.pages import render_landing_html

        page = render_landing_html({})
        self.assertIn("function toast", page, "用页面内 toast 代替原生弹窗")
        self.assertNotIn("alert(error", page, "不该再走 alert()")
        self.assertIn(".toast{", __import__("maccleaner.ui.theme", fromlist=["STYLE"]).STYLE)

    def test_button_has_ghost_and_disabled_states(self) -> None:
        from maccleaner.ui.theme import STYLE

        self.assertIn(".button.ghost{", STYLE)
        self.assertIn(".button[disabled]{", STYLE)

    def test_sidebar_is_a_glass_layer(self) -> None:
        """侧栏用 backdrop-filter 做玻璃层（2026-10-19 P4）。

        注意：玻璃需要有"背后有东西"，所以 body 上必须同时有光晕，
        否则 blur 在纯色背景上等于没有效果——两件事要一起存在。
        """
        from maccleaner.ui.theme import STYLE

        self.assertIn("backdrop-filter:blur(", STYLE)
        self.assertIn("-webkit-backdrop-filter:blur(", STYLE, "WKWebView 需要前缀")
        self.assertIn("radial-gradient", STYLE, "没有背景层，玻璃看不出层次")

    def test_review_rows_are_unchecked_by_default_and_risky_are_disabled(self) -> None:
        """审阅页默认**不勾**，高风险项连勾选框都不给（2026-10-19 用户要求）。

        之前默认全勾，`~/Downloads` 与 Docker 数据（high risk，内核要求 confirm_targets）
        一键就能删——这是危险的默认值。
        """
        from maccleaner.ui.pages import render_review_html

        page = render_review_html({"candidates": [
            {"name": "Home caches", "path": "/Users/x/Library/Caches", "kind": "cache",
             "allocated_bytes": 1024, "target_id": "home-caches", "risk": "low"},
            {"name": "Downloads", "path": "/Users/x/Downloads", "kind": "user-files",
             "allocated_bytes": 2048, "target_id": "downloads", "risk": "high",
             "requires_confirmation": True},
        ]})
        self.assertEqual(page.count('data-target-id="home-caches"'), 1)
        self.assertNotRegex(page, r'data-target-id="[^"]+"[^>]*checked', "默认不该勾选")
        self.assertIn('data-risk="1"', page, "高风险项要禁用勾选")
        self.assertNotIn('data-target-id="downloads"', page, "高风险项要留到确认页")
        self.assertIn("确认页单独确认", page)

    def test_sidebar_clean_entry_is_navigation_not_scan(self) -> None:
        """侧栏"Mac 清理"只是回落地页；扫描必须由落地页按钮触发（2026-10-19 用户报的 bug）。"""
        from maccleaner.ui.shell import NAV_GROUPS

        actions = [item.action for group in NAV_GROUPS for item in group.items]
        self.assertIn("home", actions)
        self.assertNotIn("start", actions, "侧栏不该直接等于\"开始扫描\"")

    def test_disk_page_shows_capacity_and_sections(self) -> None:
        """磁盘页：整体占比 + 每个目录一条容量条（2026-10-19 对齐 Mole 的磁盘概览）。"""
        from maccleaner.ui.pages import render_disk_html

        page = render_disk_html({
            "total": 1000, "used": 230, "free": 770, "percent": 23.0,
            "sections": [{"name": "Downloads", "bytes": 500}, {"name": "Music", "bytes": 100}],
        })
        self.assertIn('data-stage="disk"', page)
        self.assertIn("23%", page)
        self.assertEqual(page.count('class="meter"'), 3, "整体一条 + 每个目录一条")
        self.assertIn("Downloads", page)
        self.assertIn("data-bridge-action=\"disk-open\"", page, "要有刷新")

    def test_system_page_shows_load_memory_and_processes(self) -> None:
        from maccleaner.ui.pages import render_system_html

        page = render_system_html({
            "load": [1.5, 1.2, 0.9], "cpu_count": 10,
            "memory_total": 8589934592, "memory_used": 4294967296,
            "processes": [{"cpu": 12.5, "rss": 1024, "name": "python3"}],
        })
        self.assertIn('data-stage="system"', page)
        # 3 个基础格（负载/内存/CPU）+ 电池（未检测到）+ 节流（正常）
        self.assertEqual(page.count('class="stat"'), 5)
        self.assertIn("12.5%", page)
        self.assertIn("python3", page)
        self.assertIn("风扇转速不做", page, "要说明为什么没有风扇")

    def test_sidebar_has_disk_and_system_entries(self) -> None:
        from maccleaner.ui.shell import NAV_GROUPS

        actions = [item.action for group in NAV_GROUPS for item in group.items]
        self.assertIn("disk-open", actions)
        self.assertIn("system-open", actions)

    def test_uninstall_list_has_batch_selection(self) -> None:
        from maccleaner.ui.pages import render_uninstall_list_html

        page = render_uninstall_list_html({"apps": [
            {"name": "A", "bundle_id": "com.a", "path": "/Applications/A.app"},
        ]})
        self.assertIn("data-app-path", page, "每行要有勾选框")
        self.assertIn('data-bridge-action="uninstall-batch"', page)
        self.assertIn("mc-selected-count", page, "要有\"已选 N 个\"")

    def test_batch_confirm_and_done_pages(self) -> None:
        from maccleaner.ui.pages import (
            render_uninstall_batch_confirm_html,
            render_uninstall_batch_done_html,
        )

        confirm = render_uninstall_batch_confirm_html({
            "apps": [{"name": "A", "bundle_id": "com.a", "count": 3, "bytes": 2048}],
            "total_items": 3, "total_bytes": 2048,
        })
        self.assertIn('data-stage="uninstall-batch-confirm"', confirm)
        self.assertIn("1 个应用", confirm)
        self.assertIn("3 项残留", confirm)
        self.assertIn('data-bridge-action="uninstall-batch-apply"', confirm)

        done = render_uninstall_batch_done_html({"apps": [{"name": "A", "moved": 3, "bytes": 2048}]})
        self.assertIn('data-stage="uninstall-batch-done"', done)
        self.assertIn("已移入废纸篓 3 项", done)

    def test_lists_are_sortable_by_size_and_name(self) -> None:
        """列表可排序（2026-10-19）：行要带排序键、页面上要有排序条、运行时要有重排逻辑。

        为什么用前端排序：排序是纯展示，不该为一次点击重发页面或重扫磁盘。
        """
        from maccleaner.ui.pages import render_disk_html, render_review_html, render_uninstall_list_html

        uninstall = render_uninstall_list_html({"apps": [
            {"name": "Z", "bundle_id": "z", "path": "/Z", "allocated_bytes": 10},
            {"name": "A", "bundle_id": "a", "path": "/A", "allocated_bytes": 900},
        ]})
        self.assertIn('data-sort="bytes"', uninstall)
        self.assertIn("data-sortable", uninstall)
        self.assertEqual(uninstall.count("data-sort-bytes"), 2, "每行都要有排序键")

        review = render_review_html({"candidates": [
            {"name": "Big", "path": "~/x", "kind": "cache", "allocated_bytes": 500, "target_id": "t1"},
        ]})
        self.assertIn("data-sort-bytes", review)

        disk = render_disk_html({"total": 100, "used": 50, "free": 50, "percent": 50.0,
                                 "sections": [{"name": "Downloads", "bytes": 40}]})
        self.assertIn("data-sort-bytes", disk)

        self.assertIn("data-sort", uninstall)  # 排序条按钮
        self.assertIn("localeCompare", uninstall, "名称排序要走本地化比较")

    def test_rows_expose_reveal_path_for_the_context_menu(self) -> None:
        """右键菜单靠 `data-reveal-path` 定位；没有它的行不应弹菜单。"""
        from maccleaner.ui.pages import render_review_html, render_uninstall_list_html, render_landing_html

        review = render_review_html({"candidates": [
            {"name": "Big", "path": "~/Library/Caches/X", "kind": "cache",
             "allocated_bytes": 5, "target_id": "t1"},
        ]})
        self.assertIn('data-reveal-path="~/Library/Caches/X"', review)
        self.assertIn("mc-menu", review, "运行时要有右键菜单")

        uninstall = render_uninstall_list_html({"apps": [
            {"name": "A", "bundle_id": "a", "path": "/Applications/A.app"},
        ]})
        self.assertIn('data-reveal-path="/Applications/A.app"', uninstall)

        landing = render_landing_html({})
        # 注意：JS 里也有选择器字符串 `[data-reveal-path]`，所以只查"属性写法"。
        self.assertNotIn('data-reveal-path="', landing, "落地页没有可 reveal 的行")

    def test_context_menu_offers_copy_and_reveal(self) -> None:
        from maccleaner.ui.pages import render_review_html
        from maccleaner.ui.theme import STYLE

        page = render_review_html({"candidates": []})
        self.assertIn("复制路径", page)
        self.assertIn("在 Finder 中显示", page)
        self.assertIn("navigator.clipboard.writeText", page)
        self.assertIn(".ctx{", STYLE)


    def test_long_lists_are_grouped_with_sticky_toolbar(self) -> None:
        """长列表按格式塔分组（2026-10-19 用户：50 项/79 项平铺，往下拉太费劲）。"""
        from maccleaner.ui.pages import render_uninstall_list_html, render_updates_list_html

        uninstall = render_uninstall_list_html({"apps": [
            {"name": "Alpha", "bundle_id": "com.a", "path": "/A"},
            {"name": "Beta", "bundle_id": "com.b", "path": "/B"},
            {"name": "微信读书", "bundle_id": "com.w", "path": "/W"},
        ]})
        self.assertGreaterEqual(uninstall.count('class="group"'), 3, "按首字母分组（中文归 #）")
        self.assertIn('class="toolbar"', uninstall, "工具条要 sticky 在内容顶部")
        self.assertIn("data-filter", uninstall, "50 项要有搜索")
        self.assertIn("data-select-all-apps", uninstall)

        updates = render_updates_list_html({"items": [
            {"name": "aom", "manager": "brew", "kind": "formula", "installed": "1", "available": "2"},
            {"name": "Logic Pro", "manager": "mas", "kind": "app-store", "installed": "11.2", "available": "12.4"},
            {"name": "ts", "manager": "npm", "kind": "npm-global", "installed": "5", "available": "6"},
        ]})
        for label in ("Homebrew formula", "App Store", "npm 全局包"):
            self.assertIn(label, updates, f"更新要按来源分组：{label}")
        self.assertIn("data-select-group", updates, "组头要能全选该组")

    def test_clicking_a_row_does_not_toggle_its_checkbox(self) -> None:
        """点行 = 打开残留预览；只有左侧小方框才改勾选（整行 label 会误触）。"""
        from maccleaner.ui.pages import render_uninstall_list_html

        page = render_uninstall_list_html({"apps": [
            {"name": "Alpha", "bundle_id": "com.a", "path": "/Applications/Alpha.app"},
        ]})
        self.assertIn("data-row", page)
        self.assertIn("checkbox-only", page)
        self.assertNotIn('<label class="row opt" data-sort-text', page, "行不能整体是 label")



    def test_updates_page_lists_sparkle_apps_first_class(self) -> None:
        """自带 Sparkle 的应用单独成组，给「在应用内更新」；可疑的更新源要标出来。"""
        from maccleaner.ui.pages import render_updates_list_html

        page = render_updates_list_html({
            "items": [{"name": "Logic Pro", "manager": "mas", "kind": "app-store",
                       "installed": "11.2", "available": "12.4"}],
            "sparkle": [
                {"name": "ChatGPT", "path": "/Applications/ChatGPT.app", "version": "26.1", "feed": ""},
                {"name": "ima.copilot", "path": "/Applications/ima.copilot.app", "version": "143",
                 "feed": "http://0.0.0.0:8000/MacApp.xml"},
            ],
        })
        self.assertIn("自带更新（Sparkle）", page)
        self.assertEqual(page.count('data-bridge-action="open-app"'), 2)
        self.assertIn("在应用内更新", page)
        self.assertIn("更新源可疑", page, "指向 0.0.0.0 的 feed 要标出来")
        self.assertIn("在应用内更新", page)

    def test_orphan_page_lists_items_unchecked_by_default(self) -> None:
        """孤儿残留页：默认不勾、显示路径与体积、按钮走 orphans-apply。"""
        from maccleaner.ui.pages import render_orphans_html

        page = render_orphans_html({
            "items": [
                {"name": "com.gone.app", "path": "/Users/x/Library/Caches/com.gone.app",
                 "bytes": 4096, "modified": "2026-09-01"},
            ],
            "total": 1, "bytes": 4096, "installed": 78,
        })
        self.assertIn('data-stage="orphans"', page)
        self.assertIn("data-orphan-path", page)
        self.assertNotRegex(page, r'data-orphan-path="[^"]+"[^>]*checked', "默认不该勾选")
        self.assertIn("orphans-apply", page)
        self.assertIn("已装 78 个应用", page)
        self.assertIn("com.gone.app", page)

    def test_orphan_empty_state_explains_what_was_scanned(self) -> None:
        from maccleaner.ui.pages import render_orphans_html

        page = render_orphans_html({"items": [], "total": 0, "bytes": 0, "installed": 78})
        self.assertIn("没有发现孤儿残留", page)
        self.assertIn("Containers", page, "空态要说明扫过哪些位置")

    def test_disk_treemap_areas_are_proportional(self) -> None:
        """treemap 布局：面积严格按体积占比、不越界、不重叠（几何要能验）。"""
        from maccleaner.ui.treemap import squarify

        values = [50, 25, 12, 8, 5]
        rects = squarify(values, 1000, 400)
        total = sum(w * h for _, _, w, h in rects)
        self.assertAlmostEqual(total, 1000 * 400, delta=1)
        for (_, _, w, h), value in zip(rects, values):
            self.assertAlmostEqual((w * h) / total, value / sum(values), places=3)
        for x, y, w, h in rects:
            self.assertGreaterEqual(x, -0.01)
            self.assertGreaterEqual(y, -0.01)
            self.assertLessEqual(x + w, 1000.01)
            self.assertLessEqual(y + h, 400.01)
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                ax, ay, aw, ah = rects[i]
                bx, by, bw, bh = rects[j]
                overlap = ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah
                self.assertFalse(overlap, f"第 {i} 与第 {j} 个矩形重叠")

    def test_disk_page_renders_treemap_with_clickable_dirs(self) -> None:
        from maccleaner.ui.pages import render_disk_browse_html

        page = render_disk_browse_html({
            "path": "/Users/x/Downloads", "display": "~/Downloads", "parent": "/Users/x",
            "total": 4096,
            "entries": [
                {"name": "big", "path": "/Users/x/Downloads/big", "bytes": 3072, "is_dir": True},
                {"name": "a.zip", "path": "/Users/x/Downloads/a.zip", "bytes": 1024, "is_dir": False},
            ],
        })
        self.assertIn("<svg", page)
        self.assertIn('data-treemap-path="/Users/x/Downloads/big"', page)
        self.assertNotIn('data-treemap-path="/Users/x/Downloads/a.zip"', page, "文件不该可点")

    def test_selectable_lists_mark_rows_for_drag_selection(self) -> None:
        """四类可选列表的行都要带 `data-select-row`，否则拖拽连选不生效（2026-10-20）。"""
        from maccleaner.ui.pages import (
            render_orphans_html, render_review_html, render_uninstall_list_html, render_updates_list_html,
        )

        pages = {
            "review": render_review_html({"candidates": [
                {"name": "C", "path": "/x", "kind": "cache", "allocated_bytes": 1, "target_id": "t1"}]}),
            "uninstall": render_uninstall_list_html({"apps": [
                {"name": "A", "bundle_id": "a.b", "path": "/A"}]}),
            "updates": render_updates_list_html({"items": [
                {"name": "x", "manager": "brew", "kind": "formula", "installed": "1", "available": "2"}]}),
            "orphans": render_orphans_html({"items": [
                {"name": "com.gone.app", "path": "/x/com.gone.app", "bytes": 1}], "total": 1, "bytes": 1}),
        }
        for name, page in pages.items():
            self.assertIn("data-select-row", page, f"{name} 页缺少拖拽标记")

    def test_system_page_shows_battery_health_and_throttle(self) -> None:
        """电池/循环/节流要能显示（2026-10-20：免 sudo 读 pmset/ioreg）。"""
        from maccleaner.ui.pages import render_system_html

        page = render_system_html({
            "load": [1, 2, 3], "cpu_count": 10, "memory_total": 1024, "memory_used": 512,
            "processes": [],
            "power": {"source": "电池", "percent": 79, "state": "discharging", "remaining": "3:04",
                      "cycles": 986, "health_percent": 80, "design_mah": 8694},
            "thermal": {"speed_limit": None, "throttled": False},
        })
        self.assertIn("79%", page)
        self.assertIn("986 / 80%", page)
        self.assertIn("未触发限制", page)

        hot = render_system_html({
            "load": [1, 2, 3], "cpu_count": 10, "memory_total": 1024, "memory_used": 512,
            "processes": [], "power": {}, "thermal": {"speed_limit": 70, "throttled": True},
        })
        self.assertIn("70%", hot)
        self.assertIn("CPU 速度上限", hot)

    def test_uninstall_preview_warns_about_homebrew_cask(self) -> None:
        """cask 装的 app：预览页要提示并给"改用 brew 卸载"，避免 brew 记录不一致。"""
        from maccleaner.ui.pages import render_uninstall_preview_html

        plan = {
            "app": {"path": "/Applications/Ollama.app", "name": "Ollama"},
            "cask": "ollama-app",
            "items": [{"id": "a", "kind": "app-bundle", "path": "/Applications/Ollama.app", "bytes": 100}],
        }
        page = render_uninstall_preview_html(plan)
        self.assertIn("Homebrew cask", page)
        self.assertIn("ollama-app", page)
        self.assertIn("uninstall-cask", page)

        plain = render_uninstall_preview_html({"app": {"path": "/A.app", "name": "A"}, "items": []})
        self.assertNotIn("uninstall-cask", plain, "非 cask 应用不该出现这个按钮")

    def test_large_files_page_lists_items_unchecked(self) -> None:
        from maccleaner.ui.pages import render_large_files_html

        page = render_large_files_html({
            "items": [{"name": "big.bin", "path": "/Users/x/Downloads/big.bin",
                       "bytes": 2 * 2**30, "modified": "2026-10-01"}],
            "bytes": 2 * 2**30, "roots": ["~/Downloads"], "min_bytes": 500 * 2**20,
        })
        self.assertIn('data-stage="large"', page)
        self.assertIn("data-large-path", page)
        self.assertIn("2.00 GiB", page)
        self.assertNotRegex(page, r'data-large-path="[^"]+"[^>]*checked', "默认不该勾选")

    def test_disk_page_offers_admin_measurement_but_not_deletion(self) -> None:
        """系统级目录：给一次性授权测量，**不提供**任何删除按钮。"""
        from maccleaner.ui.pages import render_disk_html

        page = render_disk_html({"total": 100, "used": 50, "free": 50, "percent": 50,
                                 "sections": [], "system": {}})
        self.assertIn("系统级目录", page)
        self.assertIn("system-sizes", page)
        block = page.split("系统级目录")[1][:400]
        self.assertNotIn("移入废纸篓", block, "系统级目录不该出现删除动作")
        self.assertNotIn('data-bridge-action="clean', block)

    def test_review_page_groups_by_producer_and_keeps_browser_unchecked(self) -> None:
        """审阅页按"谁产生"分组（2026-10-20）；浏览器/系统数据默认不勾。"""
        from maccleaner.ui.pages import render_review_html

        page = render_review_html({
            "candidates": [
                {"name": "Home caches", "path": "/Users/x/Library/Caches", "kind": "cache",
                 "allocated_bytes": 100, "target_id": "home-caches"},
                {"name": "浏览器缓存", "path": "/Users/x/Library/Caches/Firefox", "kind": "browser",
                 "allocated_bytes": 200, "target_id": "browser-caches"},
                {"name": "Xcode DerivedData", "path": "/Users/x/Library/Developer/Xcode/DerivedData",
                 "kind": "xcode", "allocated_bytes": 300, "target_id": "xcode-derived-data"},
                {"name": "Docker prune", "path": "/Users/x/Library/Containers/com.docker.docker",
                 "kind": "docker", "allocated_bytes": 400, "target_id": "docker-prune",
                 "risk": "high", "requires_confirmation": True},
            ],
            "system": {"admin": False, "sizes": {"/Library/Logs": 1024}},
        })
        self.assertIn('data-group-key="browser"', page)
        self.assertIn('data-group-key="system"', page)
        self.assertIn('data-group-key="dev"', page)
        self.assertIn('data-group-key="containers"', page)
        # 系统数据组默认折叠且没有勾选框
        system_block = page.split('data-group-key="system"')[1].split("</details>")[0]
        self.assertNotIn("data-target-id", system_block, "系统数据只读，不能勾选")
        # 浏览器默认不勾
        self.assertNotRegex(page, r'data-target-id="browser-caches"[^>]*checked')
        # 顶部口径：目录占用 vs 可勾选
        self.assertIn("目录占用", page)
        self.assertIn("可勾选", page)

    def test_review_uses_filter_chips_not_sort_bar(self) -> None:
        """审阅页用「筛选」而不是排序（2026-10-20 用户要求：排序没用）。

        同时确认副标题与右上角计数已移除——那两句对判断"该不该清"没有帮助。
        """
        from maccleaner.ui.pages import render_review_html

        page = render_review_html({"candidates": [
            {"name": "Home caches", "path": "/x", "kind": "cache", "allocated_bytes": 1,
             "target_id": "home-caches"},
            {"name": "浏览器缓存", "path": "/y", "kind": "browser", "allocated_bytes": 2,
             "target_id": "browser-caches"},
        ]})
        self.assertIn('data-filter-group="all"', page)
        self.assertIn('data-filter-group="browser"', page)
        self.assertNotIn('data-sort="', page, "排序按钮应已移除")
        self.assertNotIn("只读预览", page)
        self.assertNotIn("组 · 可勾选", page)

class ShellTests(unittest.TestCase):
    def test_nav_lists_only_real_entries(self) -> None:
        nav = render_nav("clean")
        self.assertEqual(
            nav.count('data-nav-action="'), 9,
            "九个真实入口（清理/卸载/更新/残留体检/磁盘/大文件/系统/历史/技能）",
        )
        self.assertNotIn("待实现", nav, "四项都已实现，不该再有待实现徽标")
        self.assertNotIn("Protection", nav, "不出现我们没有的分类")
        self.assertIn('class="side-item is-current"', nav, "当前项要有选中态")
        self.assertIn('aria-current="page"', nav)

    def test_nav_groups_are_explicit(self) -> None:
        titles = [group.title for group in NAV_GROUPS]
        self.assertEqual(titles, ["清理", "应用", "系统", "技能"])

    def test_state_page_replaces_both_slots(self) -> None:
        page = state_page(
            {"message": "m", "detail": "d"},
            stage="review",
            title="审阅",
            body="清单",
            actions='<button id="x">X</button>',
            current="uninstall",
        )
        self.assertNotIn(NAV_SLOT, page, "导航插槽必须被替换")
        self.assertNotIn(ACTIONS_SLOT, page, "动作插槽必须被替换")
        self.assertIn('data-stage="review"', page)
        self.assertIn('id="x"', page)

    def test_no_hardcoded_colors_outside_the_style_block(self) -> None:
        """色值只允许出现在 `<style>`（也就是 theme.py 的单一来源）里。

        上一版界面曾在某个 *页面* 的样式覆盖里硬编码深紫色，导致"调品牌色时那一页不跟着变"。
        所以规则是：**样式块之外**不许出现色值，页面里一律 `var(--…)`。
        """
        page = render_landing_html({"history": {}})
        body = page.split("</style>", 1)[-1]
        for literal in ("#181530", "#2a2350", "#0e8a62", "#ffffff"):
            self.assertNotIn(literal, body, f"样式块之外不许出现硬编码色值 {literal}")
        self.assertIn('class="button round primary"', body, "页面主体结构仍在")


if __name__ == "__main__":
    unittest.main()


class RemainingPagesTests(unittest.TestCase):
    """其余页面（2026-10-18）：每页只钉"这一屏必须说清什么"。"""

    def test_review_lists_candidates_and_offers_approval(self) -> None:
        from maccleaner.ui.pages import render_review_html

        page = render_review_html({"candidates": [
            {"path": "/Users/x/Library/Caches/a", "kind": "caches", "allocated_bytes": 2048},
        ]})
        self.assertIn('data-stage="review"', page)
        self.assertIn("data-bridge-action=\"approval\"", page)
        self.assertIn("废纸篓", page, "要说明可恢复")

    def test_review_without_candidates_says_so(self) -> None:
        from maccleaner.ui.pages import render_review_html

        page = render_review_html({"candidates": []})
        self.assertIn("没有找到可清理的内容", page)
        self.assertIn("data-bridge-action=\"rescan\"", page, "空结果要能重扫")

    def test_confirmation_restates_count_and_size(self) -> None:
        from maccleaner.ui.pages import render_confirmation_html

        page = render_confirmation_html({"selected_count": 3, "selected_bytes": 3 * 1024 * 1024})
        self.assertIn('data-stage="confirming"', page)
        self.assertIn("3 组", page)
        self.assertIn("3.00 MiB", page)
        self.assertIn("data-bridge-action=\"confirm\"", page)
        self.assertIn("data-bridge-action=\"back\"", page)

    def test_completion_hero_prefers_recoverable_and_explains_trash(self) -> None:
        from maccleaner.ui.pages import render_completion_html

        page = render_completion_html({"recoverable_bytes": 4096, "actual_freed_bytes": 0, "receipt_path": "/r.json"})
        self.assertIn('data-stage="complete"', page)
        self.assertIn("4 KiB", page, "头条数字必须是可恢复字节，而不是 0")
        self.assertIn("清空废纸篓后释放", page)
        self.assertIn("/r.json", page, "回执路径要可见")

    def test_completion_real_delete_shows_actual_freed(self) -> None:
        from maccleaner.ui.pages import render_completion_html

        page = render_completion_html({"recoverable_bytes": 0, "actual_freed_bytes": 1024 * 1024})
        self.assertIn("实际释放", page)
        self.assertNotIn("清空废纸篓后释放", page, "真删路径不该出现废纸篓说明")

    def test_recovery_page_offers_retry_not_a_dead_end(self) -> None:
        from maccleaner.ui.pages import render_recovery_html

        page = render_recovery_html({"detail": "ValueError: boom"})
        self.assertIn('data-stage="error"', page)
        self.assertIn("data-bridge-action=\"start\"", page, "必须能重试")
        self.assertIn("没有删除任何东西", page)

    def test_uninstall_preview_marks_bundle_as_required_and_guessed_unchecked(self) -> None:
        from maccleaner.ui.pages import render_uninstall_preview_html

        plan = {
            "app": {"name": "Example App", "bundle_id": "com.example.app"},
            "items": [
                {"id": "aaa", "path": "/Applications/Example.app", "kind": "app-bundle", "confidence": "exact",
                 "allocated_bytes": 10},
                {"id": "bbb", "path": "/Users/x/Library/Caches/com.example.app", "kind": "caches",
                 "confidence": "exact", "allocated_bytes": 20},
                {"id": "ccc", "path": "/Users/x/Library/Logs/Example App", "kind": "log-name",
                 "confidence": "name-match", "allocated_bytes": 30},
            ],
            "user_total_bytes": 60,
        }
        page = render_uninstall_preview_html(plan)
        self.assertIn('data-stage="uninstall-preview"', page)
        self.assertIn("必选", page)
        self.assertNotIn('data-item-id="aaa"', page, "本体不提供勾选框")
        self.assertIn('data-item-id="bbb" checked', page, "确定项默认勾选")
        self.assertIn('data-item-id="ccc"', page)
        self.assertNotIn('data-item-id="ccc" checked', page, "名称匹配默认不勾")
        self.assertIn("默认不勾", page)

    def test_uninstall_complete_hides_admin_button_when_nothing_left(self) -> None:
        from maccleaner.ui.pages import render_uninstall_complete_html

        clean = render_uninstall_complete_html({"moved_count": 3, "remaining": {"system_count": 0}})
        self.assertIn('data-stage="uninstall-complete"', clean)
        self.assertNotIn("uninstall-system", clean, "没剩余就不显示管理员按钮")

        leftover = render_uninstall_complete_html({"moved_count": 1, "remaining": {"system_count": 2}})
        self.assertIn("uninstall-system", leftover)
        self.assertIn("2 项", leftover)

    def test_updates_list_marks_scope_and_checkboxes(self) -> None:
        from maccleaner.ui.pages import render_updates_list_html

        page = render_updates_list_html({"items": [
            {"name": "aom", "manager": "brew", "kind": "formula", "installed": "1", "available": "2"},
        ], "notes": ["未安装 mas：跳过 App Store 检查"]})
        self.assertIn('data-stage="updates"', page)
        self.assertIn("data-update-id=\"0\"", page)
        self.assertIn("macOS 系统更新不在此列", page, "范围必须写明")
        self.assertIn("未安装 mas", page)

    def test_updates_result_shows_exit_codes(self) -> None:
        from maccleaner.ui.pages import render_updates_result_html

        page = render_updates_result_html({"status": "partial", "ok_count": 1, "total": 2, "groups": [
            {"command": "brew upgrade aom", "exit_code": 0, "ok": True},
            {"command": "mas upgrade 1", "exit_code": 1, "ok": False, "stderr_tail": "boom"},
        ]})
        self.assertIn('data-stage="updates-result"', page)
        self.assertIn("部分更新完成", page)
        self.assertIn("exit 1", page)
        self.assertIn("boom", page)

    def test_skills_page_folds_details(self) -> None:
        from maccleaner.ui.pages import render_skills_html

        page = render_skills_html()
        self.assertIn('data-stage="skills"', page)
        self.assertIn("<details", page, "细节要收进折叠菜单")
        self.assertIn("触发词", page)
