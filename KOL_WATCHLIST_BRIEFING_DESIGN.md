# KOL Watchlist Briefing Design

## 1. Goal

`kol-watchlist-briefing` is a new account-driven monitoring workflow for
regularly summarizing updates from configured KOLs, accounts, channels,
authors, repositories, communities, podcasts, and feeds.

The product answers:

> Among the people and sources I explicitly follow, what changed recently, and
> what should I read first?

It should not behave like a broad news scan or a keyword-only cross-platform
search. The watchlist is the source of truth. Platform fetchers collect recent
updates, the pipeline normalizes them into a shared item model, optional
enrichment adds text/transcripts/comments where allowed, then scoring ranks by
importance instead of raw chronology.

Development mode should be manual-trigger first. Periodic scheduling can be
added after the CLI and state model are stable.

## 2. Product Boundaries

### 2.1 Difference From Daily Newsletter

`daily-newsletter` is event-driven and investor-news driven. It scans broad
sources, clusters public developments, maps them into fixed investment boards,
and renders a daily market/news briefing.

`kol-watchlist-briefing` is account-driven. It starts from explicit watchlist
entries such as a YouTube channel, subreddit, GitHub repository, podcast RSS
feed, X handle, or WeChat account. Its output can mention investment relevance,
but it should not force every item into the daily newsletter's seven-category
taxonomy.

### 2.2 Difference From Cross-Platform Search

`cross-platform-search` is query-driven research. It asks: "For this company,
event, product, person, or claim, what evidence exists across platforms?"

`kol-watchlist-briefing` is subscription-driven monitoring. It asks: "For this
fixed list of sources, what did they publish recently, what is new, and what
matters most?"

Cross-platform search can remain a companion tool for follow-up investigation.
The watchlist workflow should reuse lower-level platform and enrichment code
where appropriate, but its CLI, config, state, and ranking should be separate.

## 3. MVP Definition

MVP means the smallest version that proves the core workflow end to end:

1. A configurable watchlist file.
2. Manual CLI trigger.
3. Stable platform providers only.
4. Normalized item model.
5. Local dedupe and last-seen state.
6. Importance-ranked Chinese Markdown report.
7. Source diagnostics for skipped or failed accounts.

MVP platforms:

- YouTube channel RSS.
- Reddit subreddit/user feeds via official API where available.
- GitHub repository/user activity via REST API.
- Generic RSS feeds, including podcast and Xiaoyuzhou feeds.
- Xiaoyuzhou public podcast pages.
- We-MP-RSS local SQLite databases for WeChat public accounts.
- Public Telegram/Discord-like feeds only when exposed as RSS or ordinary web
  pages.

Non-MVP but planned:

- X.
- TikTok.
- Zhihu account pages.
- Xiaohongshu accounts/search.
- WeChat public accounts.
- Bilibili UP owner feeds.
- Telegram channel history through Bot API or user API.
- Discord server/channel messages through bot permissions.

## 4. Watchlist Config

Use YAML for the user-facing config because people will edit it directly.
Runtime can load YAML and convert to dict/dataclass objects.

Suggested path:

```text
config/kol_watchlist.yaml
```

Suggested schema:

```yaml
version: 1
timezone: Asia/Shanghai
default_lookback_hours: 24

defaults:
  fetch_limit: 10
  include_replies: false
  include_comments: false
  enrichment_level: metadata
  min_priority: low

ranking:
  account_priority_weight: 0.24
  topic_match_weight: 0.22
  recency_weight: 0.16
  engagement_weight: 0.14
  content_type_weight: 0.10
  enrichment_weight: 0.08
  reliability_weight: 0.06

accounts:
  - platform: youtube
    account_id: UC_x5XG1OV2P6uZZ5FSM9Ttw
    handle: GoogleDevelopers
    display_name: Google Developers
    priority: high
    topics: [ai, cloud, developer-tools]
    fetch_limit: 8
    include_replies: false
    include_comments: false
    enrichment_level: transcript
    source_mode: rss

  - platform: reddit
    account_id: LocalLLaMA
    display_name: r/LocalLLaMA
    priority: medium
    topics: [open-source-ai, inference]
    fetch_limit: 15
    include_comments: true
    enrichment_level: comments
    source_mode: oauth_api

  - platform: github
    account_id: openai/codex
    display_name: openai/codex
    priority: high
    topics: [agents, developer-tools]
    fetch_limit: 10
    include_comments: false
    enrichment_level: metadata
    watch_types: [releases, issues, pull_requests]

  - platform: rss
    feed_url: https://example.com/feed.xml
    display_name: Example Feed
    priority: medium
    topics: [ai, investing]
    fetch_limit: 10
    enrichment_level: fulltext
```

Important fields:

- `platform`: provider key.
- `account_id`: stable platform identifier when available.
- `handle`: human-friendly account name, optional.
- `display_name`: user-facing source name.
- `priority`: `critical`, `high`, `medium`, `low`.
- `topics`: user intent labels used for ranking and grouping.
- `fetch_limit`: max recent items to inspect per source.
- `include_replies`: whether replies/comments/reposts should be fetched.
- `include_comments`: whether downstream comment enrichment is allowed.
- `enrichment_level`: `metadata`, `fulltext`, `browser_fulltext`,
  `transcript`, `comments`, or `deep`.
- `source_mode`: RSS/API/browser/third-party route choice.

## 5. Data Model

Use a watchlist-specific normalized model instead of reusing `IngestedItem`
directly. Conversion to `IngestedItem` can be added later when an item needs
existing full-text tooling.

Proposed `WatchItem` fields:

```text
id
platform
account_id
account_display_name
account_priority
content_id
content_type
title
text
url
canonical_url
published_at
fetched_at
author_name
topics_configured
topics_matched
metrics
source_method
source_reliability
raw
enrichment_status
enriched_text
transcript_text
comments_summary
importance_score
importance_reasons
dedupe_key
state_key
```

`content_type` examples:

- `post`
- `article`
- `video`
- `podcast_episode`
- `release`
- `issue`
- `pull_request`
- `commit`
- `comment_thread`

`source_reliability` examples:

- `official_api`
- `official_rss`
- `public_rss`
- `public_page`
- `browser_session`
- `reader_mirror`
- `third_party_api`
- `manual_export`

## 6. Data Flow

```text
watchlist config
  -> load and validate accounts
  -> resolve account IDs or feed URLs
  -> platform fetch
  -> normalize to WatchItem
  -> dedupe and last-seen filtering
  -> optional enrichment
  -> topic and importance scoring
  -> grouping
  -> brief rendering
  -> state update
```

### 6.1 Fetch

Each provider should implement a small contract:

```text
provider.fetch(account_config, runtime_context) -> ProviderResult
```

`ProviderResult` contains:

- `items`.
- `status`: `ok`, `partial`, `skipped`, `failed`, `not_configured`.
- `error`.
- `diagnostics`.

### 6.2 Normalize

Provider-specific payloads should be normalized immediately. The rest of the
pipeline should never need to know whether an item came from RSS XML, YouTube
RSS, GitHub JSON, or Reddit JSON.

### 6.3 Dedupe

Dedupe should use:

1. Stable platform content ID when available.
2. Canonical URL.
3. Normalized title + account ID.
4. Optional fuzzy title match for reposted links.

State should record seen items separately from per-run dedupe:

```text
data/kol_watchlist/state.json
```

State shape:

```json
{
  "version": 1,
  "accounts": {
    "youtube:UC_x5XG1OV2P6uZZ5FSM9Ttw": {
      "last_run_at": "2026-06-11T00:00:00+08:00",
      "seen_item_ids": ["youtube:video:abc123"],
      "last_seen_published_at": "2026-06-10T19:00:00+00:00"
    }
  }
}
```

Use SQLite later if state grows large or scheduling needs richer history.

## 7. Enrichment

Enrichment is optional and should be top-N capped.

Recommended levels:

- `metadata`: no extra fetch beyond provider result.
- `fulltext`: use existing lightweight article extraction.
- `browser_fulltext`: use Crawl4AI for dynamic pages or difficult article pages.
- `transcript`: fetch video/podcast transcript if available.
- `comments`: fetch top comments or discussion summary.
- `deep`: combine fulltext/transcript/comments and generate an LLM summary.

### 7.1 Existing Full-Text Tools

Reuse `scripts/ingest/fulltext_tools.py` first for ordinary article URLs. It is
lightweight, source-aware, and already integrated into the repository.

### 7.2 Crawl4AI

`unclecode/crawl4ai` should be treated as a browser-grade fallback enrichment
tool, not a platform fetcher.

Useful cases:

- KOL shares an article URL and the lightweight extractor fails.
- Dynamic pages require Playwright rendering.
- Clean Markdown is needed for downstream LLM summarization.
- Link/media extraction is useful for context.

Not useful as the primary solution for:

- X timeline discovery.
- TikTok profile monitoring.
- Xiaohongshu or WeChat account monitoring.
- Bypassing paywalls, login, anti-bot systems, or platform terms.
- YouTube subtitles, podcast transcription, or comment trees.

Suggested implementation later:

```text
FullTextEnricher
  -> existing fulltext_tools
  -> Crawl4AIEnricher fallback when enrichment_level >= browser_fulltext
```

Keep Crawl4AI optional so the MVP does not require a heavier Playwright-based
dependency.

### 7.3 Transcripts and Comments

For YouTube:

- First use existing channel RSS for discovery.
- For transcripts, consider `yt-dlp` or a transcript-specific library.
- Comments should be top-N and opt-in only.

For podcasts:

- Prefer transcript links from RSS metadata when present.
- Later add audio download + transcription only for selected top items.

For Reddit:

- Comments are often core content, but should be capped by score and depth.

## 8. Ranking

The output should answer "what should I look at first?"

Proposed score dimensions:

| Dimension | Purpose |
| --- | --- |
| Account priority | User explicitly says which sources matter more. |
| Topic match | Item matches configured topics or watch keywords. |
| Recency | Newer items get a boost, with low-frequency feed exceptions. |
| Engagement | Platform-normalized reactions, comments, views, stars, issue activity. |
| Content type | Releases, deep posts, videos, podcasts, and high-signal threads can outrank light posts. |
| Enrichment quality | Fulltext/transcript/comment availability improves confidence. |
| Source reliability | Official API/RSS outranks mirrors and browser scraping. |
| Novelty | Penalize duplicates, reposts, boilerplate, pure ads, and old resurfaced content. |

Initial deterministic score is enough for MVP. LLM-assisted ranking can be a
later optional pass, using deterministic score and reasons as context.

Example importance reasons:

```text
- high-priority account
- matched topics: agents, developer-tools
- release item with active discussion
- transcript available
- high comment velocity relative to source baseline
```

## 9. Output

Default output language: Chinese.

Recommended Markdown structure:

```markdown
# KOL Watchlist Briefing - YYYY-MM-DD

## 最值得先看
1. ...

## 按平台
### YouTube
...

### GitHub
...

## 按账号
### Account Name
...

## 主题聚合
### AI agents
...

## 抓取诊断
- YouTube: 6 accounts ok, 1 failed
- GitHub: token missing, public mode used
```

Each item should include:

- Title.
- Account/source.
- Platform.
- URL.
- Published time in Beijing time.
- One-line summary.
- Why it matters.
- Enrichment note when used.

Avoid dumping a plain timeline unless the user asks for it.

## 10. MVP Implementation Plan

Suggested new files:

```text
scripts/kol_watchlist/
  __init__.py
  cli.py
  config.py
  models.py
  state.py
  dedupe.py
  scoring.py
  render.py
  providers/
    __init__.py
    base.py
    rss.py
    youtube.py
    reddit.py
    github.py
  enrichers/
    __init__.py
    article_fulltext.py
    crawl4ai_fulltext.py

config/kol_watchlist.example.yaml
tests/test_kol_watchlist_*.py
```

MVP CLI:

```powershell
python -X utf8 -m scripts.kol_watchlist.cli --config config/kol_watchlist.yaml --lookback-hours 24 --format md,json,html
```

Outputs:

```text
reports/kol_watchlist/<timestamp>/
  report.md
  report.json
  index.html
  source_summary.json
```

Initial tests:

- Config loading and defaults.
- Provider result normalization fixtures.
- Dedupe by content ID and URL.
- State filters previously seen items.
- Score ordering respects priority, topics, recency, and engagement.
- Markdown report includes URLs and diagnostics.

## 11. Reuse Map

Directly reusable:

- `scripts/ingest/base.py` helpers such as user agent, RSS parsing, text cleanup.
- `scripts/ingest/fulltext_tools.py` for article enrichment.
- `scripts/news_ingest.py` report output ideas and source diagnostics pattern.
- `scripts/cross_platform_search/render.py` concepts for JSON/Markdown/HTML outputs.
- `last30days` scoring ideas for engagement and watchlist persistence.
- `last30days-cn` Chinese platform feasibility notes and crawler bridges.
- `daily-media-briefing` editorial style and Chinese summary discipline.

Reference only:

- `x_account_posts.py`: useful as an X weak-signal fallback, not a stable core.
- `tiktok_profile_signals.py`: weak-signal model and caveats.
- `xiaohongshu_search.py`: Playwright XHR approach, not account monitoring.
- `wechat_search.py`: search fallback only.
- `bilibili_popular.py`, `zhihu_hot.py`: hot-list patterns, not watchlist fetchers.

## 12. Platform Roadmap

### Capability Tiers

The skill should not pretend that every platform has the same reliability.
User-facing prompts, `doctor`, and `watch add` should classify sources into
these tiers:

| Tier | Meaning | Examples | User promise |
| --- | --- | --- | --- |
| `stable_incremental` | RSS, official API, or local database with stable item IDs. | YouTube RSS, generic RSS, podcast RSS, GitHub Atom/API, We-MP-RSS SQLite. | Suitable for daily monitoring with local state and dedupe. |
| `stable_public_page` | Public page exposes structured data without login, but not a formal feed. | Xiaoyuzhou podcast pages. | Suitable for daily monitoring, but page schema changes may require maintenance. |
| `best_effort_rsshub` | RSSHub or RSS-Bridge route converts a platform into RSS. | Bilibili UP dynamic/video, public Telegram channel. | Often useful, but route availability and anti-scraping can fail. |
| `experimental_probe` | Login-state browser crawler or fragile public endpoint. | Xiaohongshu, Douyin, Weibo, Zhihu via MediaCrawler. | Low-frequency discovery only; cannot guarantee complete coverage. |
| `manual_setup_required` | Requires bot/server permissions, API review, OAuth, or paid quota. | Discord private channels, X API, TikTok Research API. | Do not add until the user has configured credentials and permissions. |
| `manual_source` | User export or manually supplied data. | OPML exports, CSV/Markdown exports, copied links. | Stable as an input, but not automatically updated. |

### Source Discovery Guidance

For user-facing skill prompts:

- If the user provides a normal RSS or Atom URL, add it as `platform: rss`.
- If the user provides a Xiaoyuzhou podcast URL, add it as
  `platform: xiaoyuzhou` with `podcast_url`.
- If the user provides a Xiaoyuzhou episode URL, try to resolve the parent
  podcast and save the podcast, not the single episode.
- If the user provides a Bilibili UID, suggest RSSHub dynamic feed first:
  `/bilibili/user/dynamic/<uid>`. Video feed can be a secondary option.
- If the user wants WeChat public accounts, ask for a local We-MP-RSS SQLite
  database path or tell them to first follow accounts in We-MP-RSS.
- If the user wants Xiaohongshu, Douyin, Weibo, or Zhihu, explain that the
  current path is experimental MediaCrawler or a user-provided RSS/API/export.
- If the user wants Discord private channels, require an approved bot setup;
  never suggest user-account automation.
- If the user wants X, require an official API or reliable external feed; do not
  silently add an unstable mirror as a stable source.

### Config Files

Use three config layers:

```text
config/kol_watchlist.example.yaml
config/kol_watchlist.recipes.yaml
config/kol_watchlist.yaml
```

- `example.yaml`: safe public sample that can be committed.
- `recipes.yaml`: copy/paste platform recipes and user guidance. It contains
  placeholders, not private credentials or local paths.
- `kol_watchlist.yaml`: the local user's real watchlist. It should be private
  and ignored by git.

When the skill edits the real local config, it should:

1. Create `config/kol_watchlist.yaml` from the example if missing.
2. Back up the current config before writing.
3. Validate the config after writing.
4. Run a light dry-run or list command.
5. Avoid writing tokens, cookies, or local secret paths into reports.

### Phase 1 - Stable MVP

- YouTube RSS.
- Generic RSS / podcast RSS / Xiaoyuzhou RSS.
- Xiaoyuzhou public podcast pages and episode-page-to-podcast resolution.
- We-MP-RSS local SQLite.
- GitHub REST public mode.
- Reddit official API when token is present.
- Lightweight fulltext enrichment.

### Phase 2 - Better Enrichment

- YouTube transcripts.
- Reddit top comments.
- Crawl4AI browser fulltext fallback.
- GitHub release/issue body and comment summaries.
- HTML report with grouping controls.

### Phase 3 - More Platforms

- Bilibili UP owner feed, preferably via RSSHub or stable public API.
- Telegram public channel feeds or Bot API mode.
- Discord bot/channel message mode.
- X official API mode.

### Phase 4 - Fragile/High-Value CN Platforms

- WeChat public account via user export, third-party API, or RSS conversion.
- Zhihu author/activity mode.
- Xiaohongshu account mode with local browser state or MediaCrawler.
- TikTok official/third-party mode.

### Phase 5 - Automation

- Scheduled runs.
- Notion archive.
- Email/Markdown export.
- Historical trend tracking.
- Cross-account identity graph for the same KOL across platforms.

## 13. Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Anti-scraping | Fetch failures and unstable data | Prefer official RSS/API; mark browser and mirror modes as fallback. |
| Login state expiry | Fragile social platforms fail silently | Keep auth local, emit diagnostics, never commit cookies. |
| API limits and cost | X, YouTube, Reddit, GitHub quotas | Cap fetch limits, cache state, prefer RSS where possible. |
| Platform ToS | Legal/compliance risk | Use official APIs/RSS/user-provided exports first; avoid bypassing access controls. |
| Noisy engagement metrics | Bad ranking | Normalize per platform and combine with account priority/topic match. |
| Enrichment latency | Slow runs | Enrich only top N and only when config allows. |
| KOL claims are not facts | Misleading summaries | Label KOL content as signals; verify material claims separately. |
| Cross-platform identity ambiguity | Duplicate or missed updates | Start with explicit entries; add identity linking later. |

## 14. Open Questions

1. Should watchlist entries support saved keyword searches in addition to
   accounts, or should MVP stay account/feed-only?
2. Should low-frequency feeds use a 7-day default lookback even when the global
   lookback is 24 hours?
3. Should the first user-facing report show only top-ranked items, or include a
   complete appendix grouped by source?
4. Should state be JSON for MVP, then SQLite later, or start with SQLite to make
   historical trend analysis easier?
5. Should `kol-watchlist-briefing` publish to Notion from day one, or only after
   CLI output stabilizes?

## 15. Recommended Next Step

Implement Phase 1 as a separate module under `scripts/kol_watchlist/` without
changing the existing daily newsletter pipeline.

The first development slice should be:

1. Add `WatchAccount`, `WatchItem`, `ProviderResult`, and config loading.
2. Add generic RSS and YouTube RSS providers.
3. Add deterministic dedupe and JSON state.
4. Add a simple score function.
5. Render Markdown and JSON reports.

Only after that slice works should GitHub and Reddit providers be added.
