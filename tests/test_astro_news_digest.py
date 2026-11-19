"""Regression coverage for the evening public-feed window and message format."""
from datetime import date, datetime
import unittest

from scripts.astro_news_digest import BEIJING, feed_items, render, window


class AstronomyDigestTests(unittest.TestCase):
    def test_reads_the_full_evening_window_and_follows_cursor(self):
        calls = []

        def item(stamp, link):
            return {"discoveredAt": stamp, "links": {"original": link}}

        def fetch(params):
            calls.append(params)
            return ({"items": [item("2026-11-19T12:30:00Z", "https://example.org/late"),
                               item("2026-11-18T12:29:59Z", "https://example.org/early")],
                     "page": {"hasMore": True, "nextCursor": "next"}} if len(calls) == 1
                    else {"items": [item("2026-11-18T12:30:00Z", "https://example.org/first"),
                                    item("2026-11-19T01:00:00Z", "https://example.org/first")],
                          "page": {"hasMore": False, "nextCursor": None}})

        start, end = window(date(2026, 11, 19))
        self.assertEqual(end, datetime(2026, 11, 19, 20, 30, tzinfo=BEIJING))
        self.assertEqual([row["links"]["original"] for row in feed_items(fetch, start, end)],
                         ["https://example.org/first"])
        self.assertEqual(calls[1]["cursor"], "next")

    def test_keeps_every_item_with_its_link_and_skips_duplicate_titles(self):
        item = {"title": "新望远镜", "source": {"name": "机构 · 新闻（转载）"},
                "summary": "已经开始观测。", "publishedAt": "2026-11-19T02:00:00Z",
                "links": {"original": "https://example.org/observatory"}}
        repeat = dict(item, links={"original": "https://example.org/reprint"})
        bare = {"title": "另一条", "source": {"name": "期刊"}, "summary": "",
                "links": {"original": "https://example.org/paper"}}

        parts = render([item, repeat, bare], date(2026, 11, 19))

        self.assertEqual(parts, [
            "天文科技晚报｜11 月 19 日（2 条）\n\n新望远镜\n机构｜11-19\n已经开始观测。\nhttps://example.org/observatory",
            "另一条\n期刊\nhttps://example.org/paper",
        ])


if __name__ == "__main__":
    unittest.main()
