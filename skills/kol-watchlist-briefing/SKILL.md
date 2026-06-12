---
name: kol-watchlist-briefing
description: Manage and run the daily-newsletter repo's KOL watchlist briefing workflow. Use when the user asks to add, list, diagnose, configure, migrate, or run watchlist sources such as YouTube channels, RSS feeds, Xiaoyuzhou podcasts, We-MP-RSS WeChat accounts, GitHub Atom feeds, RSSHub feeds, or other KOL/account/channel monitoring sources, especially requests like "列出我关注了哪些源", "跑一版 KOL briefing", "新增一个小宇宙 RSS", "把这个 YouTube 频道加到 watchlist", or "检查同事电脑还缺什么配置".
---

# KOL Watchlist Briefing

## Core Rules

- Work from the repo root.
- Prefer `python -X utf8 -m scripts.kol_watchlist.cli ...`.
- Use `config/kol_watchlist.yaml` for the user's real local watchlist.
- If `config/kol_watchlist.yaml` is missing, create it from `config/kol_watchlist.example.yaml`.
- Before any command that overwrites or edits `config/kol_watchlist.yaml`, back it up to `config/kol_watchlist.yaml.bak`.
- Never place cookies, tokens, local browser state, private database contents, or private local paths in chat reports or shared docs.
- Treat `config/kol_watchlist.recipes.yaml` as the copy/paste cookbook for source examples. Do not run it directly.
- Treat Crawl4AI as optional browser fulltext enrichment for web pages. Do not require it for normal runs, and do not describe it as audio/video transcription.

## Quick Commands

Initialize local config:

```bash
python -X utf8 -m scripts.kol_watchlist.cli init
```

List configured sources:

```bash
python -X utf8 -m scripts.kol_watchlist.cli list
```

Add a public RSS feed:

```bash
python -X utf8 -m scripts.kol_watchlist.cli add-rss "https://example.com/feed.xml" --display-name "Example Feed" --topics "ai, markets"
```

Add a YouTube channel:

```bash
python -X utf8 -m scripts.kol_watchlist.cli add-youtube "https://www.youtube.com/channel/CHANNEL_ID" --display-name "Channel Name"
```

Add a Xiaoyuzhou podcast or episode:

```bash
python -X utf8 -m scripts.kol_watchlist.cli add-xiaoyuzhou "https://www.xiaoyuzhoufm.com/podcast/PODCAST_ID" --display-name "Podcast Name"
```

Diagnose setup:

```bash
python -X utf8 -m scripts.kol_watchlist.cli doctor
```

Run a manual briefing:

```bash
python -X utf8 -m scripts.kol_watchlist.cli run --lookback-hours 24 --format md,json --dry-run
```

For a real daily run that marks items as seen, omit `--dry-run`.

## Natural Language Workflow

When the user asks to list current sources, run `list` and summarize the sources in plain Chinese.

When the user asks to check whether a coworker's machine is ready, run `doctor`. Explain missing inputs in simple terms:

- YouTube needs a channel ID or feed URL.
- RSS, GitHub Atom, RSSHub, and podcast feeds need a public feed URL.
- Xiaoyuzhou should use the podcast page URL. An episode URL can be used to resolve the parent podcast.
- We-MP-RSS needs a local database path on that computer, or `WE_MP_RSS_DB_PATH`.
- Private Discord/X/TikTok/OAuth sources need explicit credentials or bots and should stay local.

When the user asks to run a briefing, run `run`. Use `--dry-run` during development unless the user clearly wants state updated.

When the user asks to add a new source, first identify the platform capability:

- Stable: YouTube RSS, generic RSS/Atom, GitHub Atom, local We-MP-RSS, Xiaoyuzhou public podcast pages.
- Best effort: RSSHub feeds such as Bilibili UP dynamics/videos and public Telegram channels.
- Experimental: login-state/browser crawler paths such as Xiaohongshu, Zhihu, Douyin, or X without an official API/feed.
- Manual setup: private Discord, OAuth APIs, paid X/Reddit/TikTok API access.

If the source is RSS, YouTube, or Xiaoyuzhou and the user has supplied the required URL or ID, use `add-rss`, `add-youtube`, or `add-xiaoyuzhou`. These commands create the local config if missing, write `config/kol_watchlist.yaml.bak` before changes, and avoid duplicate sources. Run `list` after adding.

If the source is stable but no add command exists yet, edit `config/kol_watchlist.yaml` after backing it up. If not enough information is supplied, ask only for the missing item needed to configure that platform.

When the user asks for webpage/fulltext extraction for RSS, blogs, newsletters, or GitHub release pages, set `enrichment_level: crawl4ai` or `browser_fulltext` for that source and mention the optional setup:

```bash
pip install -r requirements-optional.txt
```

If Crawl4AI is not installed, the briefing should still run with source metadata and report an enrichment diagnostic.

## Source Inputs

Use these preferred inputs:

- YouTube: `account_id` as channel ID, or `feed_url`.
- RSS: `feed_url`.
- Xiaoyuzhou: `podcast_url`; accept `episode_url` if the user only has an episode link.
- We-MP-RSS: `db_path` or environment variable `WE_MP_RSS_DB_PATH`; optionally `include_mp_names`.
- GitHub releases: `https://github.com/OWNER/REPO/releases.atom` as an RSS source.
- Bilibili via RSSHub: `https://rsshub.app/bilibili/user/dynamic/UID` or `/video/UID`.
- Telegram public channel via RSSHub: `https://rsshub.app/telegram/channel/CHANNEL_USERNAME`.

Use `priority`, `topics`, `fetch_limit`, `include_replies`, `include_comments`, and `enrichment_level` when adding sources. Prefer `priority: high` only for sources the user explicitly says are important.

## Output Expectations

Briefings are written under `reports/kol_watchlist/<timestamp>/`.

The report should rank items by importance, not just time. Explain that the current MVP score uses account priority, topic match, recency, engagement signals when present, content type, enrichment status, and source reliability.

The current MVP summary is extracted from source metadata, RSS descriptions, Xiaoyuzhou show notes, or local We-MP-RSS article text. It is not yet a universal LLM-generated summary unless a later summarizer is added.

## Migration Notes

For coworkers:

1. Clone or copy this repo.
2. Install `requirements.txt`.
3. Run `python -X utf8 -m scripts.kol_watchlist.cli init`.
4. Run `python -X utf8 -m scripts.kol_watchlist.cli doctor`.
5. Add local-only sources to `config/kol_watchlist.yaml`; do not commit that file.
6. Run a dry run before scheduling: `python -X utf8 -m scripts.kol_watchlist.cli run --dry-run`.

Scheduled daily runs can use the Codex app automation/heartbeat system, Windows Task Scheduler, cron, or any existing daily pipeline runner. During development, keep manual trigger as the default.
