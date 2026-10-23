"""三条"更新源"契约（2026-10-23 补缺陷时加）。

1. Sparkle 必须**按构建号优先**比对：appcast 允许营销版本相同而 `sparkle:version` 递增，
   只比营销版本会把新版判成"已是最新"。
2. App Store 走 `itunes.apple.com/lookup`（免登录）：**查不到是 HTTP 200 + 空数组**，
   不能靠状态码判断，也不能假装"已是最新"。
3. 已装列表不能静默截断（原来 limit=60，应用多的机器会少一半）。
"""

from __future__ import annotations

import json
import unittest

from maccleaner.deps import _sparkle_is_newer, appstore_check, list_applications, sparkle_latest_item

APPCAST = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle">
  <channel>
    <item>
      <enclosure url="a.zip" sparkle:version="100" sparkle:shortVersionString="1.2.3"/>
    </item>
    <item>
      <enclosure url="b.zip" sparkle:version="101" sparkle:shortVersionString="1.2.3"/>
    </item>
    <item>
      <enclosure url="c.zip" sparkle:version="99" sparkle:shortVersionString="1.2.4"/>
    </item>
  </channel>
</rss>
"""


class SparkleBuildNumberTests(unittest.TestCase):
    def test_picks_highest_build_not_highest_marketing_version(self) -> None:
        item = sparkle_latest_item(APPCAST)
        # 按构建号，101 最高；若按营销版本会误取 1.2.4（build 99）
        self.assertEqual(item["build"], "101")
        self.assertEqual(item["short"], "1.2.3")

    def test_same_marketing_version_but_higher_build_is_an_update(self) -> None:
        self.assertTrue(_sparkle_is_newer(
            latest_build="101", latest_short="1.2.3",
            installed_build="100", installed_short="1.2.3",
        ))

    def test_same_build_is_not_an_update(self) -> None:
        self.assertFalse(_sparkle_is_newer(
            latest_build="101", latest_short="1.2.3",
            installed_build="101", installed_short="1.2.3",
        ))

    def test_falls_back_to_marketing_version_without_builds(self) -> None:
        self.assertTrue(_sparkle_is_newer(
            latest_build="", latest_short="1.3.0",
            installed_build="", installed_short="1.2.9",
        ))


class AppStoreLookupTests(unittest.TestCase):
    def _app(self) -> dict[str, str]:
        return {"name": "Logic Pro", "bundle_id": "com.apple.logic10",
                "version": "11.2", "path": "/Applications/Logic Pro.app"}

    def test_reports_update_when_store_version_is_newer(self) -> None:
        def fetcher(_url: str) -> str:
            return json.dumps({"resultCount": 1, "results": [{"version": "12.4"}]})

        result = appstore_check([self._app()], fetcher=fetcher)[0]
        self.assertTrue(result["update_available"])
        self.assertEqual(result["latest"], "12.4")

    def test_empty_results_is_unknown_not_latest(self) -> None:
        # 200 + 空数组是"商店上查不到"，不是"已是最新"。
        def fetcher(_url: str) -> str:
            return json.dumps({"resultCount": 0, "results": []})

        result = appstore_check([self._app()], fetcher=fetcher)[0]
        self.assertFalse(result["update_available"])
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["reason"], "商店上查不到")

    def test_network_error_is_unknown(self) -> None:
        def fetcher(_url: str) -> str:
            raise TimeoutError("boom")

        result = appstore_check([self._app()], fetcher=fetcher)[0]
        self.assertFalse(result["update_available"])
        self.assertIn("查询失败", result["reason"])


class ApplicationListTests(unittest.TestCase):
    def test_default_limit_does_not_truncate_typical_machine(self) -> None:
        # 本机 50 个；以前默认 60 是"看起来够用"，装到 60 个以上就静默少列。
        apps = list_applications()
        self.assertLessEqual(len(apps), 500)
        self.assertGreater(len(apps), 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
