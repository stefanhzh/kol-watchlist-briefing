#!/usr/bin/env python3
"""Tests for KOL watchlist briefing MVP behavior."""

from __future__ import annotations

from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import sqlite3
from contextlib import redirect_stdout
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.kol_watchlist import cli  # noqa: E402
from scripts.kol_watchlist.config import load_watchlist_config  # noqa: E402
from scripts.kol_watchlist.dedupe import dedupe_items  # noqa: E402
from scripts.kol_watchlist.models import WatchAccount, WatchItem, WatchlistConfig, WatchlistReport  # noqa: E402
from scripts.kol_watchlist.providers.rss import RssProvider  # noqa: E402
from scripts.kol_watchlist.providers.we_mp_rss import WeMpRssProvider  # noqa: E402
from scripts.kol_watchlist.providers.xiaoyuzhou import XiaoyuzhouProvider  # noqa: E402
from scripts.kol_watchlist.providers.youtube import YouTubeProvider  # noqa: E402
from scripts.kol_watchlist.render import render_markdown  # noqa: E402
from scripts.kol_watchlist.scoring import score_items  # noqa: E402
from scripts.kol_watchlist.state import filter_unseen_items, load_state, mark_seen  # noqa: E402


RSS_FIXTURE = """<?xml version="1.0" encoding="UTF-8" ?>
<rss version="2.0">
  <channel>
    <title>Example Feed</title>
    <item>
      <title>New AI agent workflow</title>
      <link>https://example.com/post?utm_source=test</link>
      <guid>post-1</guid>
      <pubDate>Thu, 11 Jun 2026 01:00:00 GMT</pubDate>
      <description>AI agents for daily research work.</description>
    </item>
    <item>
      <title>Old item</title>
      <link>https://example.com/old</link>
      <guid>post-old</guid>
      <pubDate>Mon, 01 Jun 2026 01:00:00 GMT</pubDate>
      <description>Too old.</description>
    </item>
  </channel>
</rss>
"""


YOUTUBE_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns:media="http://search.yahoo.com/mrss/"
      xmlns="http://www.w3.org/2005/Atom">
  <title>Google Developers</title>
  <entry>
    <id>yt:video:abc123</id>
    <yt:videoId>abc123</yt:videoId>
    <yt:channelId>UC_x5XG1OV2P6uZZ5FSM9Ttw</yt:channelId>
    <title>AI developer update</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=abc123"/>
    <published>2026-06-11T02:00:00+00:00</published>
    <updated>2026-06-11T02:00:00+00:00</updated>
    <media:group>
      <media:description>Agents and developer tools.</media:description>
    </media:group>
  </entry>
</feed>
"""


XIAOYUZHOU_PODCAST_FIXTURE = """<!doctype html><html><body>
<script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{"podcast":{"pid":"PODCAST_1","title":"听懂涨声","episodes":[{"eid":"EP_1","pid":"PODCAST_1","title":"SpaceX IPO deep dive","description":"AI and IPO discussion","duration":3484,"playCount":20827,"commentCount":36,"favoriteCount":12,"pubDate":"2026-06-11T02:00:00.000Z"}]}}}}</script>
</body></html>"""


XIAOYUZHOU_EPISODE_FIXTURE = """<!doctype html><html><body>
<script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{"episode":{"eid":"EP_1","pid":"PODCAST_1","title":"SpaceX IPO deep dive","description":"Episode description","shownotes":"<p>重点一：SpaceX IPO。</p><p>重点二：AI 巨头上市。</p>","duration":3484,"playCount":20827,"commentCount":36,"favoriteCount":12,"pubDate":"2026-06-11T02:00:00.000Z","podcast":{"pid":"PODCAST_1","title":"听懂涨声"}},"comments":[{"text":"评论一"},{"text":"评论二"}]}}}</script>
</body></html>"""


class KolWatchlistTest(unittest.TestCase):
    def test_load_watchlist_config_from_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "watchlist.yaml"
            path.write_text(
                """
version: 1
timezone: Asia/Shanghai
default_lookback_hours: 24
defaults:
  fetch_limit: 3
accounts:
  - platform: rss
    feed_url: https://example.com/feed.xml
    display_name: Example
    priority: high
    topics: [ai]
""",
                encoding="utf-8",
            )
            config = load_watchlist_config(path)
        self.assertEqual(config.accounts[0].fetch_limit, 3)
        self.assertEqual(config.accounts[0].priority, "high")
        self.assertEqual(config.accounts[0].topics, ["ai"])

    def test_rss_provider_normalizes_recent_items(self) -> None:
        account = WatchAccount(
            platform="rss",
            display_name="Example",
            feed_url="https://example.com/feed.xml",
            priority="high",
            topics=["ai"],
            fetch_limit=10,
        )
        provider = RssProvider()
        with patch.object(provider, "request_text", return_value=RSS_FIXTURE):
            result = provider.fetch(account, lookback_hours=48)
        self.assertEqual(result.status, "ok")
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0].title, "New AI agent workflow")
        self.assertEqual(result.items[0].canonical_url, "https://example.com/post")
        self.assertEqual(result.items[0].source_reliability, "public_rss")

    def test_youtube_provider_builds_feed_url_and_video_items(self) -> None:
        account = WatchAccount(
            platform="youtube",
            account_id="UC_x5XG1OV2P6uZZ5FSM9Ttw",
            display_name="Google Developers",
            priority="high",
            topics=["developer"],
            fetch_limit=5,
        )
        provider = YouTubeProvider()
        with patch.object(provider, "request_text", return_value=YOUTUBE_FIXTURE):
            result = provider.fetch(account, lookback_hours=48)
        self.assertEqual(len(result.items), 1)
        item = result.items[0]
        self.assertEqual(item.platform, "youtube")
        self.assertEqual(item.content_type, "video")
        self.assertEqual(item.content_id, "abc123")
        self.assertEqual(item.source_reliability, "official_rss")

    def test_dedupe_and_state_filter_seen_items(self) -> None:
        item = WatchItem(
            id="rss:1",
            platform="rss",
            account_id="feed",
            account_display_name="Feed",
            account_priority="medium",
            content_id="1",
            content_type="article",
            title="Same",
            url="https://example.com/a?utm_source=x",
            canonical_url="https://example.com/a",
            state_key="rss:feed",
        )
        duplicate = WatchItem(**{**item.to_dict(), "id": "rss:2"})
        deduped = dedupe_items([item, duplicate])
        self.assertEqual(len(deduped), 1)
        state = load_state(Path("missing-state.json"))
        mark_seen(deduped, state)
        self.assertEqual(filter_unseen_items(deduped, state), [])

    def test_scoring_prioritizes_high_priority_topic_match(self) -> None:
        config = WatchlistConfig(
            version=1,
            timezone="Asia/Shanghai",
            default_lookback_hours=24,
            defaults={},
            ranking={
                "account_priority_weight": 0.24,
                "topic_match_weight": 0.22,
                "recency_weight": 0.16,
                "engagement_weight": 0.14,
                "content_type_weight": 0.10,
                "enrichment_weight": 0.08,
                "reliability_weight": 0.06,
            },
            accounts=[],
        )
        high = WatchItem(
            id="1",
            platform="rss",
            account_id="a",
            account_display_name="A",
            account_priority="high",
            content_id="1",
            content_type="article",
            title="AI agent launch",
            text="developer tools",
            url="https://example.com/a",
            canonical_url="https://example.com/a",
            published_at="2026-06-11T01:00:00+00:00",
            topics_configured=["ai"],
            source_reliability="public_rss",
        )
        low = WatchItem(**{**high.to_dict(), "id": "2", "account_priority": "low", "title": "Random update"})
        ranked = score_items(
            [low, high],
            config,
            now=datetime(2026, 6, 11, 3, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(ranked[0].id, "1")
        self.assertIn("matched topics: ai", ranked[0].importance_reasons)

    def test_render_markdown_includes_links_and_diagnostics(self) -> None:
        item = WatchItem(
            id="1",
            platform="rss",
            account_id="feed",
            account_display_name="Feed",
            account_priority="high",
            content_id="1",
            content_type="article",
            title="AI agent launch",
            text="summary",
            url="https://example.com/a",
            canonical_url="https://example.com/a",
            published_at="2026-06-11T01:00:00+00:00",
            importance_score=72.0,
            importance_reasons=["high-priority account"],
        )
        report = WatchlistReport(
            run_meta={"generated_at": "2026-06-11T10:00:00+08:00", "lookback_hours": 24, "account_count": 1},
            source_summaries=[{"platform": "rss", "account": "Feed", "status": "ok", "raw_count": 1}],
            items=[item],
        )
        markdown = render_markdown(report)
        self.assertIn("## 最值得先看", markdown)
        self.assertIn("[AI agent launch](https://example.com/a)", markdown)
        self.assertIn("## 抓取诊断", markdown)

    def test_report_json_omits_raw_private_fields(self) -> None:
        item = WatchItem(
            id="1",
            platform="we_mp_rss",
            account_id="mp",
            account_display_name="Account",
            account_priority="high",
            content_id="1",
            content_type="article",
            title="Private path should not leak",
            url="https://mp.weixin.qq.com/s/example",
            canonical_url="https://mp.weixin.qq.com/s/example",
            raw={"db_path": "C:/private/we_mp_rss.db", "cookie": "secret"},
        )
        report = WatchlistReport(run_meta={"config": "kol_watchlist.yaml"}, source_summaries=[], items=[item])
        payload = report.to_dict()
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("raw", payload["items"][0])
        self.assertNotIn("C:/private/we_mp_rss.db", serialized)
        self.assertNotIn("secret", serialized)

    def test_cli_init_creates_config_and_force_backs_up(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            example = root / "example.yaml"
            config = root / "kol_watchlist.yaml"
            example.write_text(
                """
version: 1
accounts:
  - platform: rss
    feed_url: https://example.com/feed.xml
    display_name: Example
""",
                encoding="utf-8",
            )
            with redirect_stdout(io.StringIO()):
                cli.main(["init", "--config", str(config), "--example", str(example)])
            self.assertTrue(config.exists())
            config.write_text("version: 1\naccounts: []\n", encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                cli.main(["init", "--config", str(config), "--example", str(example), "--force"])
            self.assertTrue(config.with_name(config.name + ".bak").exists())

    def test_cli_doctor_does_not_print_private_db_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "we_mp_rss.db"
            self._create_we_mp_rss_db(db_path)
            config = root / "kol_watchlist.yaml"
            config.write_text(
                f"""
version: 1
accounts:
  - platform: we_mp_rss
    display_name: Local WeChat
    db_path: {db_path.as_posix()}
    fetch_limit: 5
""",
                encoding="utf-8",
            )
            output = io.StringIO()
            with redirect_stdout(output):
                cli.main(["doctor", "--config", str(config), "--example", str(config)])
            self.assertIn("Local database file is accessible", output.getvalue())
            self.assertNotIn(db_path.as_posix(), output.getvalue())

    def test_cli_legacy_args_parse_as_run(self) -> None:
        args = cli.parse_args(["--config", "config/kol_watchlist.example.yaml", "--dry-run"])
        self.assertEqual(args.command, "run")
        self.assertTrue(args.dry_run)

    def test_cli_add_rss_appends_source_and_backs_up(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, example = self._create_empty_watchlist_config(Path(tmp))
            with redirect_stdout(io.StringIO()):
                cli.main(
                    [
                        "add-rss",
                        "https://example.com/feed.xml",
                        "--display-name",
                        "Example Feed",
                        "--priority",
                        "high",
                        "--topics",
                        "ai, markets",
                        "--config",
                        str(config),
                        "--example",
                        str(example),
                    ]
                )
            loaded = load_watchlist_config(config)
            self.assertEqual(len(loaded.accounts), 1)
            self.assertEqual(loaded.accounts[0].feed_url, "https://example.com/feed.xml")
            self.assertEqual(loaded.accounts[0].topics, ["ai", "markets"])
            self.assertTrue(config.with_name(config.name + ".bak").exists())

    def test_cli_add_rss_dedupes_same_feed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, example = self._create_empty_watchlist_config(Path(tmp))
            command = [
                "add-rss",
                "https://example.com/feed.xml",
                "--display-name",
                "Example Feed",
                "--config",
                str(config),
                "--example",
                str(example),
            ]
            with redirect_stdout(io.StringIO()):
                cli.main(command)
                cli.main(command)
            loaded = load_watchlist_config(config)
            self.assertEqual(len(loaded.accounts), 1)

    def test_cli_add_youtube_parses_channel_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, example = self._create_empty_watchlist_config(Path(tmp))
            with redirect_stdout(io.StringIO()):
                cli.main(
                    [
                        "add-youtube",
                        "https://www.youtube.com/channel/UC_x5XG1OV2P6uZZ5FSM9Ttw",
                        "--display-name",
                        "Google Developers",
                        "--config",
                        str(config),
                        "--example",
                        str(example),
                    ]
                )
            loaded = load_watchlist_config(config)
            self.assertEqual(loaded.accounts[0].platform, "youtube")
            self.assertEqual(loaded.accounts[0].account_id, "UC_x5XG1OV2P6uZZ5FSM9Ttw")

    def test_cli_add_xiaoyuzhou_episode_defaults_to_episode_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, example = self._create_empty_watchlist_config(Path(tmp))
            with redirect_stdout(io.StringIO()):
                cli.main(
                    [
                        "add-xiaoyuzhou",
                        "https://www.xiaoyuzhoufm.com/episode/EP_1",
                        "--display-name",
                        "听懂涨声",
                        "--config",
                        str(config),
                        "--example",
                        str(example),
                    ]
                )
            loaded = load_watchlist_config(config)
            self.assertEqual(loaded.accounts[0].episode_url, "https://www.xiaoyuzhoufm.com/episode/EP_1")
            self.assertEqual(loaded.accounts[0].enrichment_level, "episode_notes")

    def test_we_mp_rss_provider_reads_local_sqlite_articles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "we_mp_rss.db"
            self._create_we_mp_rss_db(db_path)
            account = WatchAccount(
                platform="we_mp_rss",
                display_name="WeChat Public Accounts",
                db_path=str(db_path),
                priority="high",
                topics=["openai"],
                fetch_limit=5,
                enrichment_level="fulltext",
            )
            result = WeMpRssProvider().fetch(account, lookback_hours=24 * 30)
        self.assertEqual(result.status, "ok")
        self.assertEqual(len(result.items), 1)
        item = result.items[0]
        self.assertEqual(item.platform, "we_mp_rss")
        self.assertEqual(item.account_display_name, "Example Account")
        self.assertEqual(item.source_reliability, "local_database")
        self.assertEqual(item.enrichment_status, "fulltext")
        self.assertIn("Full local article body", item.enriched_text)

    def test_we_mp_rss_provider_filters_selected_accounts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "we_mp_rss.db"
            self._create_we_mp_rss_db(db_path)
            account = WatchAccount(
                platform="we_mp_rss",
                display_name="Selected",
                db_path=str(db_path),
                include_mp_names=["Other Account"],
                fetch_limit=5,
            )
            result = WeMpRssProvider().fetch(account, lookback_hours=24 * 30)
        self.assertEqual(result.items, [])

    def test_xiaoyuzhou_provider_reads_podcast_page_and_episode_notes(self) -> None:
        account = WatchAccount(
            platform="xiaoyuzhou",
            display_name="听懂涨声",
            podcast_url="https://www.xiaoyuzhoufm.com/podcast/PODCAST_1",
            priority="high",
            topics=["IPO", "AI"],
            fetch_limit=5,
            enrichment_level="episode_notes",
        )
        provider = XiaoyuzhouProvider()

        def fake_request(url: str, *, timeout: int = 20) -> str:
            if "/episode/" in url:
                return XIAOYUZHOU_EPISODE_FIXTURE
            return XIAOYUZHOU_PODCAST_FIXTURE

        with patch.object(provider, "request_text", side_effect=fake_request):
            result = provider.fetch(account, lookback_hours=48)

        self.assertEqual(result.status, "ok")
        self.assertEqual(len(result.items), 1)
        item = result.items[0]
        self.assertEqual(item.platform, "xiaoyuzhou")
        self.assertEqual(item.account_display_name, "听懂涨声")
        self.assertEqual(item.content_type, "podcast_episode")
        self.assertEqual(item.enrichment_status, "episode_notes")
        self.assertIn("SpaceX IPO", item.enriched_text)
        self.assertIn("评论一", item.comments_summary)

    def test_xiaoyuzhou_provider_resolves_episode_url_to_podcast(self) -> None:
        account = WatchAccount(
            platform="xiaoyuzhou",
            display_name="听懂涨声",
            episode_url="https://www.xiaoyuzhoufm.com/episode/EP_1",
            fetch_limit=5,
        )
        provider = XiaoyuzhouProvider()
        seen_urls: list[str] = []

        def fake_request(url: str, *, timeout: int = 20) -> str:
            seen_urls.append(url)
            if "/episode/" in url:
                return XIAOYUZHOU_EPISODE_FIXTURE
            return XIAOYUZHOU_PODCAST_FIXTURE

        with patch.object(provider, "request_text", side_effect=fake_request):
            result = provider.fetch(account, lookback_hours=48)

        self.assertEqual(len(result.items), 1)
        self.assertIn("https://www.xiaoyuzhoufm.com/podcast/PODCAST_1", seen_urls)

    def _create_we_mp_rss_db(self, db_path: Path) -> None:
        published_at = datetime(2026, 6, 11, 1, 0, tzinfo=timezone.utc)
        connection = sqlite3.connect(db_path)
        try:
            connection.executescript(
                """
                CREATE TABLE feeds (
                    id TEXT PRIMARY KEY,
                    mp_name TEXT,
                    mp_cover TEXT,
                    mp_intro TEXT,
                    status INTEGER
                );
                CREATE TABLE articles (
                    id TEXT PRIMARY KEY,
                    mp_id TEXT,
                    title TEXT,
                    url TEXT,
                    description TEXT,
                    publish_time INTEGER,
                    status INTEGER,
                    has_content INTEGER,
                    content TEXT,
                    content_html TEXT
                );
                """
            )
            connection.execute(
                "INSERT INTO feeds (id, mp_name, status) VALUES (?, ?, ?)",
                ("MP_TEST", "Example Account", 1),
            )
            connection.execute(
                """
                INSERT INTO articles (
                    id, mp_id, title, url, description, publish_time,
                    status, has_content, content, content_html
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "ARTICLE_1",
                    "MP_TEST",
                    "OpenAI phone plans surface",
                    "https://mp.weixin.qq.com/s/example",
                    "A local WeChat article about OpenAI hardware.",
                    int(published_at.timestamp()),
                    1,
                    1,
                    "Full local article body mentioning OpenAI and phone.",
                    "<p>Full local article body mentioning OpenAI and phone.</p>",
                ),
            )
            connection.commit()
        finally:
            connection.close()

    def _create_empty_watchlist_config(self, root: Path) -> tuple[Path, Path]:
        example = root / "example.yaml"
        config = root / "kol_watchlist.yaml"
        text = "version: 1\ntimezone: Asia/Shanghai\naccounts: []\n"
        example.write_text(text, encoding="utf-8")
        config.write_text(text, encoding="utf-8")
        return config, example


if __name__ == "__main__":
    unittest.main()
