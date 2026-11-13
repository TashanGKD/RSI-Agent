"""Regression coverage for the daily public-feed boundary and message format."""
from datetime import datetime
import unittest

from scripts.astro_news_digest import BEIJING, feed_items, render


class AstronomyDigestTests(unittest.TestCase):
    def test_uses_daily_cutoff_and_follows_cursor(self):
        calls = []

        def fetch(params):
            calls.append(params)
            return ({"items": [{"discoveredAt": "2026-11-13T02:00:00Z"},
                               {"discoveredAt": "2026-11-12T01:59:59Z"}],
                     "page": {"hasMore": True, "nextCursor": "next"}} if len(calls) == 1
                    else {"items": [{"discoveredAt": "2026-11-12T02:00:00Z"}],
                          "page": {"hasMore": False, "nextCursor": None}})

        end = datetime(2026, 11, 13, 10, tzinfo=BEIJING)
        self.assertEqual(list(feed_items(fetch, end)), [{"discoveredAt": "2026-11-12T02:00:00Z"}])
        self.assertEqual(calls[1]["cursor"], "next")

    def test_keeps_link_with_summary_and_skips_duplicate_titles(self):
        item = {"title": "新望远镜", "source": {"name": "机构 · 新闻"},
                "summary": "已经开始观测。第二句。",
                "links": {"original": "https://example.org/observatory"}}
        repeat = dict(item, links={"original": "https://example.org/reprint"})

        parts = render([item, repeat], "2026-11-13")

        self.assertEqual(len(parts), 1)
        self.assertIn("机构｜日期未标注\n已经开始观测。", parts[0])
        self.assertTrue(parts[0].endswith(item["links"]["original"]))
        self.assertNotIn("第二句", parts[0])


if __name__ == "__main__":
    unittest.main()
