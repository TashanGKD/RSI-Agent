"""Regression coverage for the evening public-feed window and message format."""
from datetime import date, datetime
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from scripts import astro_news_digest as digest
from scripts.astro_news_digest import BEIJING, feed_items, render, window


def picture(fmt="PNG", frames=1):
    out = io.BytesIO()
    first = Image.new("RGB", (8, 8), "navy")
    if frames > 1:
        first.save(out, fmt, save_all=True, append_images=[Image.new("RGB", (8, 8), "gold")])
    else:
        first.save(out, fmt)
    return out.getvalue()


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

    def test_remote_program_compiles(self):
        compile(digest.REMOTE, "astro-news-remote", "exec")

    def test_cover_is_static_frozen_once_and_sent_before_text(self):
        day = date(2026, 11, 19)
        now = datetime(2026, 11, 19, 21, tzinfo=BEIJING)
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder)
            gif = state / "moving.gif"
            gif.write_bytes(picture("GIF", 2))
            with self.assertRaises(ValueError):
                digest.cover_asset(gif, state, day)
            png = state / "top.png"
            png.write_bytes(picture())
            sha = hashlib.sha256(png.read_bytes()).hexdigest()
            calls = []

            def remote(settings, mode, key, parts, cover=None):
                calls.append((mode, cover))
                if mode == "status" and len(calls) == 1:
                    return {"receipts": [{"group": "G", "part": i, "state": "not_submitted"} for i in (0, 1)]}
                rows = [{"group": "G", "part": 0, "state": "sent", "sha256": sha},
                        {"group": "G", "part": 1, "state": "sent", "text": parts[0]}]
                return {"receipts": rows}

            settings = {"groups": [{"name": "G", "peer": "g@chatroom"}]}
            with patch.object(digest, "remote", remote), \
                    patch.object(digest, "feed_items", return_value=[]), \
                    patch.object(digest, "render", return_value=["晚报正文"]):
                result = digest.run(settings, state, "run", day, now, png)
            self.assertEqual(result["state"], "sent")
            frozen = json.loads((state / "evening-2026-11-19-dispatch.json").read_text(encoding="utf-8"))
            self.assertEqual(frozen["cover"], {"name": "evening-2026-11-19-cover.png", "sha256": sha,
                                               "bytes": png.stat().st_size})
            self.assertEqual([mode for mode, _ in calls], ["status", "send", "status"])
            self.assertTrue(all(cover["sha256"] == sha and cover["data"] for _, cover in calls))
            other = state / "other.png"
            other.write_bytes(picture("JPEG"))
            with patch.object(digest, "remote", remote):
                with self.assertRaises(ValueError):
                    digest.run(settings, state, "run", day, now, other)

    def test_unproven_cover_receipt_keeps_the_day_unsettled(self):
        day = date(2026, 11, 19)
        now = datetime(2026, 11, 19, 21, tzinfo=BEIJING)
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder)
            png = state / "top.png"
            png.write_bytes(picture())

            def remote(settings, mode, key, parts, cover=None):
                return {"receipts": [{"group": "G", "part": 0, "state": "sent", "sha256": "0" * 64},
                                     {"group": "G", "part": 1, "state": "sent", "text": parts[0]}]}

            settings = {"groups": [{"name": "G", "peer": "g@chatroom"}]}
            with patch.object(digest, "remote", remote), \
                    patch.object(digest, "feed_items", return_value=[]), \
                    patch.object(digest, "render", return_value=["晚报正文"]):
                self.assertEqual(digest.run(settings, state, "run", day, now, png)["state"], "unsettled")


if __name__ == "__main__":
    unittest.main()
