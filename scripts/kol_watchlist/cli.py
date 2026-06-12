#!/usr/bin/env python3
"""CLI for KOL watchlist briefings."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import sys
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.kol_watchlist.config import (  # noqa: E402
    append_account_to_config,
    backup_config,
    ensure_config_from_example,
    load_watchlist_config,
)
from scripts.kol_watchlist.utils import request_text  # noqa: E402
from scripts.kol_watchlist.dedupe import dedupe_items  # noqa: E402
from scripts.kol_watchlist.deep_dive import deep_dive, write_deep_dive_outputs  # noqa: E402
from scripts.kol_watchlist.enrichers.crawl4ai_fulltext import (  # noqa: E402
    CRAWL4AI_LEVELS,
    enrich_items_with_crawl4ai,
)
from scripts.kol_watchlist.models import WatchAccount, WatchItem, WatchlistReport  # noqa: E402
from scripts.kol_watchlist.providers import provider_for  # noqa: E402
from scripts.kol_watchlist.render import write_outputs  # noqa: E402
from scripts.kol_watchlist.scoring import score_items  # noqa: E402
from scripts.kol_watchlist.state import filter_unseen_items, load_state, mark_seen, save_state  # noqa: E402


REPORTS_DIR = ROOT / "reports" / "kol_watchlist"
DEEP_DIVE_DIR = ROOT / "reports" / "kol_watchlist_deep_dive"
DEFAULT_CONFIG_PATH = ROOT / "config" / "kol_watchlist.yaml"
EXAMPLE_CONFIG_PATH = ROOT / "config" / "kol_watchlist.example.yaml"
RECIPES_PATH = ROOT / "config" / "kol_watchlist.recipes.yaml"
DEFAULT_STATE_PATH = ROOT / "data" / "kol_watchlist" / "state.json"
COMMANDS = {"init", "list", "doctor", "run", "add-rss", "add-youtube", "add-xiaoyuzhou", "deep-dive"}


def default_output_dir() -> Path:
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d_%H-%M-%S")
    return REPORTS_DIR / stamp


def default_deep_dive_output_dir() -> Path:
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d_%H-%M-%S")
    return DEEP_DIVE_DIR / stamp


def parse_formats(value: str) -> set[str]:
    formats = {part.strip().lower() for part in value.split(",") if part.strip()}
    allowed = {"md", "json", "html"}
    invalid = formats - allowed
    if invalid:
        raise argparse.ArgumentTypeError(f"Unsupported format(s): {', '.join(sorted(invalid))}")
    return formats or {"md", "json"}


def init_config(args: argparse.Namespace) -> None:
    config_path = args.config
    example_path = args.example
    if config_path.exists() and not args.force:
        print(f"config_exists={_display_path(config_path)}")
        print("status=unchanged")
        print("hint=Use --force to regenerate from the example after a backup.")
        return
    backup_path = backup_config(config_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(example_path.read_text(encoding="utf-8"), encoding="utf-8")
    if backup_path:
        print(f"backup={_display_path(backup_path)}")
    print(f"config={_display_path(config_path)}")
    print("status=created" if not backup_path else "status=regenerated")


def list_accounts(args: argparse.Namespace) -> None:
    _ensure_default_config(args)
    config = load_watchlist_config(args.config)
    print(f"config={_display_path(args.config)}")
    print(f"accounts={len(config.accounts)}")
    for index, account in enumerate(config.accounts, start=1):
        source_hint = _source_hint(account)
        topics = ", ".join(account.topics) if account.topics else "-"
        print(
            f"{index}. {account.platform} | {account.display_name} | "
            f"priority={account.priority} | source={source_hint} | "
            f"topics={topics} | fetch_limit={account.fetch_limit} | "
            f"enrichment={account.enrichment_level}"
        )


def doctor(args: argparse.Namespace) -> None:
    created = _ensure_default_config(args)
    print(f"config={_display_path(args.config)}")
    if created:
        print("config_status=created_from_example")
    config = load_watchlist_config(args.config)
    print(f"accounts={len(config.accounts)}")
    print(f"recipes={_display_path(RECIPES_PATH) if RECIPES_PATH.exists() else 'missing'}")
    print("")
    print("Provider checks:")
    crawl4ai_requested = False
    for index, account in enumerate(config.accounts, start=1):
        status, message = _doctor_account(account)
        print(f"{index}. [{status}] {account.platform} / {account.display_name}: {message}")
        if account.enrichment_level in CRAWL4AI_LEVELS:
            crawl4ai_requested = True
    if crawl4ai_requested:
        status = "ok" if _crawl4ai_installed() else "needs_optional_install"
        message = "crawl4ai is installed." if status == "ok" else "Install crawl4ai and its browser runtime before using browser fulltext."
        print(f"- [{status}] enrichment / crawl4ai: {message}")
    print("")
    print("What coworkers need to configure:")
    print("- YouTube: provide a channel_id or a feed_url.")
    print("- RSS/podcast/GitHub Atom/RSSHub: provide a public feed_url.")
    print("- Xiaoyuzhou: provide a podcast_url; an episode_url can be used to resolve the podcast.")
    print("- We-MP-RSS: install/run We-MP-RSS locally, then provide db_path or WE_MP_RSS_DB_PATH.")
    print("- Private Discord/X/TikTok/Reddit OAuth sources need explicit tokens or bots; keep those local.")
    print("- Crawl4AI fulltext is optional. Use enrichment_level=crawl4ai or browser_fulltext, then install crawl4ai locally.")
    print("- Never commit config/kol_watchlist.yaml, cookies, tokens, browser state, or local databases.")


def add_rss(args: argparse.Namespace) -> None:
    account = _base_account_from_args(args, platform="rss")
    account["feed_url"] = args.feed_url.strip()
    account["source_mode"] = args.source_mode or "rss"
    _append_account(args, account)


def add_youtube(args: argparse.Namespace) -> None:
    account = _base_account_from_args(args, platform="youtube")
    source = (args.source or "").strip()
    channel_id = args.channel_id.strip() if args.channel_id else ""
    feed_url = args.feed_url.strip() if args.feed_url else ""
    handle = args.handle.strip().lstrip("@") if args.handle else ""

    if source:
        parsed = _parse_youtube_source(source)
        channel_id = channel_id or parsed.get("channel_id", "")
        feed_url = feed_url or parsed.get("feed_url", "")
        handle = handle or parsed.get("handle", "")
        if not channel_id and not feed_url and source.startswith("http"):
            channel_id = _resolve_youtube_channel_id(source)

    if not channel_id and not feed_url:
        raise SystemExit("add-youtube needs --channel-id, --feed-url, or a YouTube channel URL that exposes a channel ID.")

    if channel_id:
        account["account_id"] = channel_id
    if feed_url:
        account["feed_url"] = feed_url
    if handle:
        account["handle"] = handle
    account["source_mode"] = args.source_mode or "rss"
    _append_account(args, account)


def add_xiaoyuzhou(args: argparse.Namespace) -> None:
    account = _base_account_from_args(args, platform="xiaoyuzhou")
    source = args.source.strip()
    if "/episode/" in source:
        account["episode_url"] = source
    elif "/podcast/" in source:
        account["podcast_url"] = source
    elif source.endswith(".xml") or "rss" in source.lower():
        account["feed_url"] = source
    else:
        raise SystemExit("add-xiaoyuzhou needs a Xiaoyuzhou podcast URL, episode URL, or RSS feed URL.")
    account["source_mode"] = args.source_mode or ("public_page" if not account.get("feed_url") else "rss")
    if not args.enrichment_level:
        account["enrichment_level"] = "episode_notes"
    _append_account(args, account)


def run_deep_dive(args: argparse.Namespace) -> tuple[object, dict[str, str]]:
    _ensure_default_config(args)
    report = deep_dive(
        args.query,
        config_path=args.config,
        latest_report=args.latest_report,
        max_chars=args.max_chars,
        use_crawl4ai=not args.no_crawl4ai,
    )
    output_dir = args.output_dir or default_deep_dive_output_dir()
    written = write_deep_dive_outputs(output_dir, report)
    return report, written


def run(args: argparse.Namespace) -> tuple[WatchlistReport, dict[str, str]]:
    _ensure_default_config(args)
    config = load_watchlist_config(args.config)
    lookback_hours = args.lookback_hours or config.default_lookback_hours
    fetched_items: list[WatchItem] = []
    source_summaries: list[dict[str, object]] = []

    for account in config.accounts:
        provider = provider_for(account.platform)
        if provider is None:
            source_summaries.append(
                {
                    "platform": account.platform,
                    "account": account.display_name,
                    "account_key": f"{account.platform}:{account.display_name}",
                    "status": "missing_provider",
                    "raw_count": 0,
                    "error": "No provider registered for this platform.",
                    "diagnostics": [],
                }
            )
            continue
        result = provider.fetch(account, lookback_hours=lookback_hours)
        fetched_items.extend(result.items)
        source_summaries.append(result.to_summary_dict())

    deduped = dedupe_items(fetched_items)
    crawl4ai_summary = enrich_items_with_crawl4ai(deduped)
    if crawl4ai_summary.attempted or crawl4ai_summary.skipped or crawl4ai_summary.errors:
        source_summaries.append(
            {
                "platform": "enrichment",
                "account": "crawl4ai",
                "account_key": "enrichment:crawl4ai",
                "status": "ok" if crawl4ai_summary.enriched else "skipped",
                "raw_count": crawl4ai_summary.enriched,
                "error": "",
                "diagnostics": crawl4ai_summary.to_diagnostics(),
            }
        )
    state = load_state(args.state)
    unseen = filter_unseen_items(deduped, state) if not args.include_seen else deduped
    ranked = score_items(unseen, config, lookback_hours=lookback_hours)
    if not args.dry_run:
        mark_seen(ranked, state)
        save_state(args.state, state)

    report = WatchlistReport(
        run_meta={
            "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "config": args.config.name,
            "lookback_hours": lookback_hours,
            "account_count": len(config.accounts),
            "raw_items": len(fetched_items),
            "deduped_items": len(deduped),
            "included_seen": args.include_seen,
            "dry_run": args.dry_run,
        },
        source_summaries=source_summaries,
        items=ranked,
    )
    output_dir = args.output_dir or default_output_dir()
    written = write_outputs(output_dir, report, args.formats)
    return report, written


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    argv = list(argv or sys.argv[1:])
    if not argv or argv[0] not in COMMANDS:
        parser = _run_parser("Build a KOL watchlist briefing from configured accounts.")
        args = parser.parse_args(argv)
        args.command = "run"
        return args

    parser = argparse.ArgumentParser(description="Manage and run KOL watchlist briefings.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create config/kol_watchlist.yaml from the example.")
    _add_config_args(init_parser)
    init_parser.add_argument("--force", action="store_true", help="Regenerate config after writing a .bak backup.")

    list_parser = subparsers.add_parser("list", help="List configured watchlist sources.")
    _add_config_args(list_parser)

    doctor_parser = subparsers.add_parser("doctor", help="Check local watchlist setup and required inputs.")
    _add_config_args(doctor_parser)

    run_parser = subparsers.add_parser("run", help="Run a KOL watchlist briefing.")
    _add_run_args(run_parser)

    add_rss_parser = subparsers.add_parser("add-rss", help="Add a public RSS/Atom feed.")
    _add_add_args(add_rss_parser)
    add_rss_parser.add_argument("feed_url")
    add_rss_parser.add_argument("--source-mode", default="rss")

    add_youtube_parser = subparsers.add_parser("add-youtube", help="Add a YouTube channel via official RSS.")
    _add_add_args(add_youtube_parser)
    add_youtube_parser.add_argument("source", nargs="?", help="Channel ID, feed URL, or channel URL.")
    add_youtube_parser.add_argument("--channel-id", default="")
    add_youtube_parser.add_argument("--feed-url", default="")
    add_youtube_parser.add_argument("--handle", default="")
    add_youtube_parser.add_argument("--source-mode", default="rss")

    add_xiaoyuzhou_parser = subparsers.add_parser("add-xiaoyuzhou", help="Add a Xiaoyuzhou podcast or episode URL.")
    _add_add_args(add_xiaoyuzhou_parser, default_enrichment="")
    add_xiaoyuzhou_parser.add_argument("source")
    add_xiaoyuzhou_parser.add_argument("--source-mode", default="")

    deep_dive_parser = subparsers.add_parser("deep-dive", help="Build an on-demand long-content material pack.")
    _add_config_args(deep_dive_parser)
    deep_dive_parser.add_argument("query", help="Episode/article/video URL, or a title from a recent report.")
    deep_dive_parser.add_argument("--latest-report", type=Path, help="Optional report.json to resolve a title to URL.")
    deep_dive_parser.add_argument("--output-dir", type=Path)
    deep_dive_parser.add_argument("--max-chars", type=int, default=50000)
    deep_dive_parser.add_argument("--no-crawl4ai", action="store_true", help="Disable optional Crawl4AI page probing.")

    return parser.parse_args(argv)


def _run_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    _add_run_args(parser)
    return parser


def _add_config_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--example", type=Path, default=EXAMPLE_CONFIG_PATH)


def _add_run_args(parser: argparse.ArgumentParser) -> None:
    _add_config_args(parser)
    parser.add_argument("--lookback-hours", type=int)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--format", dest="formats", type=parse_formats, default={"md", "json"})
    parser.add_argument("--include-seen", action="store_true", help="Include items already present in local state.")
    parser.add_argument("--dry-run", action="store_true", help="Do not update local last-seen state.")


def _add_add_args(parser: argparse.ArgumentParser, *, default_enrichment: str = "metadata") -> None:
    _add_config_args(parser)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--priority", default="medium", choices=["low", "medium", "high"])
    parser.add_argument("--topics", default="", help="Comma-separated topic tags.")
    parser.add_argument("--fetch-limit", type=int, default=10)
    parser.add_argument("--enrichment-level", default=default_enrichment)
    parser.add_argument("--include-replies", action="store_true")
    parser.add_argument("--include-comments", action="store_true")


def _ensure_default_config(args: argparse.Namespace) -> bool:
    return ensure_config_from_example(args.config, args.example)


def _base_account_from_args(args: argparse.Namespace, *, platform: str) -> dict[str, object]:
    account: dict[str, object] = {
        "platform": platform,
        "display_name": args.display_name.strip(),
        "priority": args.priority,
        "topics": _split_csv(args.topics),
        "fetch_limit": max(1, args.fetch_limit),
        "include_replies": bool(args.include_replies),
        "include_comments": bool(args.include_comments),
    }
    if args.enrichment_level:
        account["enrichment_level"] = args.enrichment_level
    return account


def _append_account(args: argparse.Namespace, account: dict[str, object]) -> None:
    _ensure_default_config(args)
    added = append_account_to_config(args.config, account)
    print(f"config={_display_path(args.config)}")
    if added:
        print("status=added")
        print(f"backup={_display_path(args.config.with_name(args.config.name + '.bak'))}")
    else:
        print("status=already_exists")
    print(f"source={account.get('platform')} / {account.get('display_name')}")


def _split_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _parse_youtube_source(source: str) -> dict[str, str]:
    value = source.strip()
    if value.startswith("UC") and len(value) >= 20 and "/" not in value:
        return {"channel_id": value}
    if value.startswith("@"):
        return {"handle": value.lstrip("@")}
    parsed = urlparse(value)
    if "youtube.com" not in parsed.netloc and "youtu.be" not in parsed.netloc:
        return {}
    query = parse_qs(parsed.query)
    if query.get("channel_id"):
        return {"channel_id": query["channel_id"][0], "feed_url": value}
    if "/feeds/videos.xml" in parsed.path:
        return {"feed_url": value}
    channel_match = re.search(r"/channel/([^/?#]+)", parsed.path)
    if channel_match:
        return {"channel_id": channel_match.group(1)}
    handle_match = re.search(r"/@([^/?#]+)", parsed.path)
    if handle_match:
        return {"handle": handle_match.group(1)}
    return {}


def _resolve_youtube_channel_id(url: str) -> str:
    try:
        html = request_text(url, timeout=20)
    except Exception:
        return ""
    patterns = [
        r'"channelId"\s*:\s*"([^"]+)"',
        r'"externalId"\s*:\s*"([^"]+)"',
        r'<meta itemprop="channelId" content="([^"]+)"',
    ]
    for pattern in patterns:
        match = re.search(pattern, html)
        if match:
            return match.group(1)
    return ""


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return path.name


def _source_hint(account: WatchAccount) -> str:
    if account.platform == "youtube":
        return "channel_id" if account.account_id else "feed_url"
    if account.platform in {"rss", "podcast"}:
        return "feed_url"
    if account.platform == "xiaoyuzhou":
        if account.podcast_url:
            return "podcast_url"
        if account.episode_url:
            return "episode_url"
        return "feed_url"
    if account.platform in {"we_mp_rss", "wechat"}:
        selected = len(account.include_mp_names) + len(account.include_mp_ids)
        return "local_db" + (f", selected_accounts={selected}" if selected else "")
    return account.source_mode or "custom"


def _doctor_account(account: WatchAccount) -> tuple[str, str]:
    if provider_for(account.platform) is None:
        return "needs_provider", "No provider is registered yet. Check recipes or add an adapter first."
    if account.platform == "youtube":
        if account.account_id or account.feed_url:
            return "ok", "Ready. Uses official YouTube RSS."
        return "needs_input", "Add channel_id or feed_url."
    if account.platform in {"rss", "podcast"}:
        if account.feed_url:
            return "ok", "Ready if the feed is public and reachable."
        return "needs_input", "Add feed_url."
    if account.platform == "xiaoyuzhou":
        if account.podcast_url or account.episode_url or account.feed_url:
            return "ok", "Ready. Podcast URL is preferred; episode URL can resolve the podcast."
        return "needs_input", "Add podcast_url, episode_url, or feed_url."
    if account.platform in {"we_mp_rss", "wechat"}:
        db_paths = _configured_db_paths(account)
        if not db_paths:
            return "needs_input", "Add db_path or set WE_MP_RSS_DB_PATH."
        if any(path.exists() and path.is_file() for path in db_paths):
            return "ok", "Ready. Local database file is accessible."
        return "needs_local_file", "A local database is configured but not accessible on this computer."
    return "ok", "Provider is registered. Check platform-specific credentials if needed."


def _configured_db_paths(account: WatchAccount) -> list[Path]:
    values: list[str] = []
    env_value = os.environ.get("WE_MP_RSS_DB_PATHS") or os.environ.get("WE_MP_RSS_DB_PATH") or ""
    if env_value:
        values.extend(part.strip().strip('"') for part in env_value.split(";") if part.strip())
    if account.db_path:
        values.append(account.db_path)
    values.extend(account.db_paths)
    return [Path(os.path.expandvars(os.path.expanduser(value))).resolve() for value in values if value]


def _crawl4ai_installed() -> bool:
    try:
        import crawl4ai  # noqa: F401
    except Exception:
        return False
    return True


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if args.command == "init":
        init_config(args)
        return
    if args.command == "list":
        list_accounts(args)
        return
    if args.command == "doctor":
        doctor(args)
        return
    if args.command == "add-rss":
        add_rss(args)
        return
    if args.command == "add-youtube":
        add_youtube(args)
        return
    if args.command == "add-xiaoyuzhou":
        add_xiaoyuzhou(args)
        return
    if args.command == "deep-dive":
        report, written = run_deep_dive(args)
        for kind, path in written.items():
            print(f"{kind}={path}")
        print(f"platform={getattr(report, 'platform', '')}")
        print(f"status={getattr(report, 'source_status', '')}")
        return
    report, written = run(args)
    for kind, path in written.items():
        print(f"{kind}={path}")
    print(f"items={len(report.items)}")


if __name__ == "__main__":
    main()
