#!/usr/bin/env python3
"""On-demand long-content deep dive helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
import json
from pathlib import Path
import re
import sqlite3
from typing import Any
from urllib.parse import urlparse

from .config import load_watchlist_config
from .enrichers.crawl4ai_fulltext import enrich_items_with_crawl4ai
from .models import WatchAccount, WatchItem
from .providers.we_mp_rss import WeMpRssProvider
from .providers.xiaoyuzhou import XIAOYUZHOU_BASE, _next_data
from .utils import canonicalize_url, clean_html_text, clean_text, iso_now, request_text, stable_id, title_key


@dataclass
class DeepDiveReport:
    query: str
    platform: str
    title: str = ""
    url: str = ""
    account: str = ""
    source_status: str = "ok"
    source_methods: list[str] = field(default_factory=list)
    summary_seed: str = ""
    fulltext: str = ""
    transcript: str = ""
    comments: list[str] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    generated_at: str = field(default_factory=iso_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def deep_dive(
    query: str,
    *,
    config_path: Path,
    latest_report: Path | None = None,
    max_chars: int = 50000,
    use_crawl4ai: bool = True,
) -> DeepDiveReport:
    query = query.strip()
    if not query:
        raise ValueError("deep-dive query cannot be empty.")
    matched = _match_latest_report(query, latest_report)
    target = matched.get("url") or query
    platform = matched.get("platform") or _guess_platform(target)
    if not _looks_like_url(target):
        report = _deep_dive_wechat(target, config_path=config_path, max_chars=max_chars)
        if report.source_status not in {"not_configured", "not_found"}:
            report.query = query
            return report
    if platform == "xiaoyuzhou" or "xiaoyuzhoufm.com" in target:
        report = _deep_dive_xiaoyuzhou(target, max_chars=max_chars)
    elif platform in {"we_mp_rss", "wechat"} or "mp.weixin.qq.com" in target:
        report = _deep_dive_wechat(target, config_path=config_path, max_chars=max_chars)
    elif platform == "bilibili" or "bilibili.com" in target or "b23.tv" in target:
        report = _deep_dive_bilibili(target, max_chars=max_chars, use_crawl4ai=use_crawl4ai)
    else:
        report = _deep_dive_generic_web(target, max_chars=max_chars, use_crawl4ai=use_crawl4ai)
    if matched and not report.title:
        report.title = matched.get("title", "")
    if matched and not report.account:
        report.account = matched.get("account", "")
    report.query = query
    return report


def write_deep_dive_outputs(output_dir: Path, report: DeepDiveReport) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "deep_dive.json"
    md_path = output_dir / "deep_dive.md"
    json_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_deep_dive_markdown(report), encoding="utf-8")
    return {"json": str(json_path), "md": str(md_path)}


def render_deep_dive_markdown(report: DeepDiveReport) -> str:
    lines = [
        f"# Long Content Deep Dive - {report.title or report.query}",
        "",
        f"- Generated: `{report.generated_at}`",
        f"- Platform: `{report.platform}`",
        f"- Account: `{report.account or '-'}`",
        f"- URL: {report.url or '-'}",
        f"- Status: `{report.source_status}`",
        f"- Methods: `{', '.join(report.source_methods) or '-'}`",
        "",
        "## Summary Seed",
        "",
        report.summary_seed or "No summary seed available.",
        "",
    ]
    if report.transcript:
        lines.extend(["## Transcript", "", _truncate(report.transcript, 12000), ""])
    if report.fulltext:
        lines.extend(["## Fulltext / Notes", "", _truncate(report.fulltext, 12000), ""])
    if report.comments:
        lines.extend(["## Comments", ""])
        for comment in report.comments[:10]:
            lines.append(f"- {comment}")
        lines.append("")
    if report.diagnostics:
        lines.extend(["## Diagnostics", ""])
        for note in report.diagnostics:
            lines.append(f"- {note}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _deep_dive_xiaoyuzhou(url: str, *, max_chars: int) -> DeepDiveReport:
    report = DeepDiveReport(query=url, platform="xiaoyuzhou", url=url, source_methods=["xiaoyuzhou_public_next_data"])
    try:
        html = request_text(url, timeout=25)
        payload = _next_data(html)
    except Exception as exc:  # noqa: BLE001
        report.source_status = "failed"
        report.diagnostics.append(f"xiaoyuzhou fetch failed: {exc.__class__.__name__}: {exc}")
        return report
    page = payload.get("props", {}).get("pageProps", {})
    episode = page.get("episode") or {}
    if not episode and "/podcast/" in url:
        report.source_status = "needs_episode"
        report.diagnostics.append("Podcast pages list episodes. Provide a single episode URL for deep dive.")
        podcast = page.get("podcast") or {}
        report.title = clean_text(podcast.get("title") or "")
        report.account = report.title
        return report
    podcast = episode.get("podcast") or {}
    report.title = clean_text(episode.get("title") or "")
    report.account = clean_text(podcast.get("title") or "")
    eid = clean_text(episode.get("eid") or "")
    if eid and not report.url:
        report.url = f"{XIAOYUZHOU_BASE}/episode/{eid}"
    notes = clean_html_text(episode.get("shownotes") or episode.get("description") or "")
    transcript = episode.get("transcript")
    report.fulltext = _truncate(notes, max_chars)
    if isinstance(transcript, str):
        report.transcript = _truncate(clean_html_text(transcript), max_chars)
    comments = page.get("comments") or []
    if isinstance(comments, list):
        for comment in comments[:20]:
            if isinstance(comment, dict):
                text = clean_html_text(comment.get("text") or comment.get("content") or "")
                if text:
                    report.comments.append(text)
    report.summary_seed = _summary_seed(report.transcript or report.fulltext)
    if report.transcript:
        report.source_methods.append("public_transcript")
    if report.comments:
        report.source_methods.append("public_comments")
    if not report.fulltext and not report.transcript:
        report.source_status = "metadata_only"
        report.diagnostics.append("No public shownotes or transcript found on the episode page.")
    return report


def _deep_dive_wechat(query: str, *, config_path: Path, max_chars: int) -> DeepDiveReport:
    report = DeepDiveReport(query=query, platform="we_mp_rss", url=query, source_methods=["local_we_mp_rss_sqlite"])
    try:
        config = load_watchlist_config(config_path)
    except Exception as exc:  # noqa: BLE001
        report.source_status = "failed"
        report.diagnostics.append(f"Could not load watchlist config: {exc.__class__.__name__}: {exc}")
        return report
    provider = WeMpRssProvider()
    accounts = [account for account in config.accounts if account.platform in {"we_mp_rss", "wechat"}]
    if not accounts:
        report.source_status = "not_configured"
        report.diagnostics.append("No we_mp_rss account is configured. Add a local We-MP-RSS database first.")
        return report
    for account in accounts:
        for db_path in provider._resolve_db_paths(account):  # noqa: SLF001
            row = _find_wechat_row(db_path, query)
            if not row:
                continue
            item = provider._row_to_item(account, row)  # noqa: SLF001
            if item is None:
                continue
            report.title = item.title
            report.url = item.url
            report.account = item.account_display_name
            report.fulltext = _truncate(item.enriched_text or item.text, max_chars)
            report.summary_seed = _summary_seed(report.fulltext)
            if not item.enriched_text:
                report.source_status = "metadata_only"
                report.diagnostics.append("Matched the article, but this local database row has no stored full content.")
            return report
    report.source_status = "not_found"
    report.diagnostics.append("No matching We-MP-RSS article found by URL or title in configured local databases.")
    return report


def _deep_dive_bilibili(url: str, *, max_chars: int, use_crawl4ai: bool) -> DeepDiveReport:
    report = DeepDiveReport(query=url, platform="bilibili", url=url, source_methods=["bilibili_page_probe"])
    report.diagnostics.append("Bilibili transcript/subtitle extraction is not implemented yet. This command only probes public page text or optional Crawl4AI output.")
    if use_crawl4ai:
        item = _web_item(url, platform="bilibili")
        item.enrichment_status = "crawl4ai"
        summary = enrich_items_with_crawl4ai([item], max_items=1, max_chars=max_chars)
        report.diagnostics.extend(summary.to_diagnostics())
        if item.enriched_text:
            report.fulltext = item.enriched_text
            report.title = item.title or url
            report.summary_seed = _summary_seed(report.fulltext)
            report.source_methods.append("crawl4ai")
            return report
    try:
        html = request_text(url, timeout=20)
        report.title = _html_title(html) or url
        report.fulltext = _truncate(clean_html_text(html), min(max_chars, 5000))
        report.summary_seed = _summary_seed(report.fulltext)
    except Exception as exc:  # noqa: BLE001
        report.source_status = "metadata_only"
        report.diagnostics.append(f"Bilibili page probe failed: {exc.__class__.__name__}: {exc}")
    return report


def _deep_dive_generic_web(url: str, *, max_chars: int, use_crawl4ai: bool) -> DeepDiveReport:
    report = DeepDiveReport(query=url, platform=_guess_platform(url), url=url, source_methods=["generic_web"])
    if use_crawl4ai:
        item = _web_item(url, platform=report.platform)
        item.enrichment_status = "crawl4ai"
        summary = enrich_items_with_crawl4ai([item], max_items=1, max_chars=max_chars)
        report.diagnostics.extend(summary.to_diagnostics())
        if item.enriched_text:
            report.title = item.title or url
            report.fulltext = item.enriched_text
            report.summary_seed = _summary_seed(report.fulltext)
            report.source_methods.append("crawl4ai")
            return report
    try:
        html = request_text(url, timeout=20)
        report.title = _html_title(html) or url
        report.fulltext = _truncate(clean_html_text(html), max_chars)
        report.summary_seed = _summary_seed(report.fulltext)
    except Exception as exc:  # noqa: BLE001
        report.source_status = "failed"
        report.diagnostics.append(f"Generic page fetch failed: {exc.__class__.__name__}: {exc}")
    return report


def _find_wechat_row(db_path: Path, query: str) -> dict[str, Any] | None:
    canonical = canonicalize_url(query)
    by_url = "mp.weixin.qq.com" in query
    title_like = f"%{query.strip()}%"
    sql = """
        SELECT a.id, a.mp_id, a.title, a.url, a.description, a.publish_time,
               a.status, a.has_content, a.content, a.content_html, f.mp_name
        FROM articles a
        LEFT JOIN feeds f ON f.id = a.mp_id
        WHERE a.status = 1 AND (a.url = ? OR a.url = ? OR a.title LIKE ?)
        ORDER BY COALESCE(a.publish_time, 0) DESC
        LIMIT 1
    """
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        connection.row_factory = sqlite3.Row
        row = connection.execute(sql, [query, canonical if by_url else query, title_like]).fetchone()
        return dict(row) if row else None
    finally:
        connection.close()


def _match_latest_report(query: str, latest_report: Path | None) -> dict[str, str]:
    if latest_report is None or not latest_report.exists():
        return {}
    try:
        payload = json.loads(latest_report.read_text(encoding="utf-8"))
    except Exception:
        return {}
    items = payload.get("items") or []
    normalized = title_key(query)
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "")
        url = str(item.get("canonical_url") or item.get("url") or "")
        if query in url or normalized and normalized in title_key(title):
            return {
                "title": title,
                "url": url,
                "platform": str(item.get("platform") or ""),
                "account": str(item.get("account_display_name") or ""),
            }
    return {}


def _web_item(url: str, *, platform: str) -> WatchItem:
    return WatchItem(
        id=f"{platform}:{stable_id(url)}",
        platform=platform,
        account_id=url,
        account_display_name=platform,
        account_priority="medium",
        content_id=url,
        content_type="web_page",
        title=url,
        url=url,
        canonical_url=canonicalize_url(url),
        enrichment_status="crawl4ai",
    )


def _guess_platform(value: str) -> str:
    host = urlparse(value).netloc.lower()
    if "xiaoyuzhoufm.com" in host:
        return "xiaoyuzhou"
    if "mp.weixin.qq.com" in host:
        return "we_mp_rss"
    if "bilibili.com" in host or "b23.tv" in host:
        return "bilibili"
    return "web"


def _looks_like_url(value: str) -> bool:
    return bool(urlparse(value).scheme and urlparse(value).netloc)


def _html_title(html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.I | re.S)
    return clean_html_text(match.group(1)) if match else ""


def _summary_seed(text: str, *, max_sentences: int = 8) -> str:
    cleaned = clean_text(text)
    if not cleaned:
        return ""
    parts = re.split(r"(?<=[。！？!?])\s+|(?<=[。！？!?])", cleaned)
    selected = [part.strip() for part in parts if part.strip()][:max_sentences]
    return "\n".join(f"- {part}" for part in selected)


def _truncate(text: str, max_chars: int) -> str:
    cleaned = clean_text(text)
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[:max_chars].rstrip() + "\n\n[truncated]"
