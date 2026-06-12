#!/usr/bin/env python3
"""Xiaoyuzhou podcast provider from public podcast or episode pages."""

from __future__ import annotations

from datetime import timezone
import json
import re
from typing import Any

from .base import BaseProvider
from .rss import RssProvider
from ..models import ProviderResult, WatchAccount, WatchItem
from ..utils import canonicalize_url, clean_html_text, clean_text, iso_now, parse_datetime, stable_id


XIAOYUZHOU_BASE = "https://www.xiaoyuzhoufm.com"


class XiaoyuzhouProvider(BaseProvider):
    platform = "xiaoyuzhou"

    def fetch(self, account: WatchAccount, *, lookback_hours: int) -> ProviderResult:
        if account.feed_url:
            result = RssProvider().fetch(account, lookback_hours=lookback_hours)
            for item in result.items:
                item.platform = "xiaoyuzhou"
                item.content_type = "podcast_episode"
                item.source_method = "podcast_rss"
                item.source_reliability = "public_rss"
            return result

        try:
            podcast_url = account.podcast_url
            if not podcast_url and account.episode_url:
                podcast_url = self._resolve_podcast_url_from_episode(account.episode_url)
            if not podcast_url:
                return ProviderResult(
                    account=account,
                    status="skipped",
                    error="Missing podcast_url, episode_url, or feed_url.",
                )
            html = self.request_text(podcast_url, timeout=25)
            payload = _next_data(html)
            podcast = payload.get("props", {}).get("pageProps", {}).get("podcast") or {}
            items = self._podcast_to_items(account, podcast, lookback_hours)
        except Exception as exc:  # noqa: BLE001
            return ProviderResult(account=account, status="failed", error=f"{exc.__class__.__name__}: {exc}")

        return ProviderResult(account=account, items=items, status="ok")

    def _resolve_podcast_url_from_episode(self, episode_url: str) -> str:
        html = self.request_text(episode_url, timeout=25)
        payload = _next_data(html)
        episode = payload.get("props", {}).get("pageProps", {}).get("episode") or {}
        podcast = episode.get("podcast") or {}
        pid = clean_text(podcast.get("pid") or episode.get("pid") or "")
        if not pid:
            raise ValueError("Could not resolve podcast id from episode page.")
        return f"{XIAOYUZHOU_BASE}/podcast/{pid}"

    def _podcast_to_items(self, account: WatchAccount, podcast: dict[str, Any], lookback_hours: int) -> list[WatchItem]:
        pid = clean_text(podcast.get("pid") or account.account_id or "")
        podcast_title = clean_text(podcast.get("title") or account.display_name)
        episodes = podcast.get("episodes") or []
        items: list[WatchItem] = []
        for raw in episodes[: account.fetch_limit * 2]:
            if not isinstance(raw, dict):
                continue
            item = self._episode_to_item(account, raw, pid=pid, podcast_title=podcast_title)
            if item is None:
                continue
            if item.published_at and not self.within_lookback(item.published_at, lookback_hours):
                continue
            if account.enrichment_level in {"episode_notes", "fulltext", "deep"}:
                self._enrich_episode_notes(item)
            items.append(item)
            if len(items) >= account.fetch_limit:
                break
        return items

    def _episode_to_item(
        self,
        account: WatchAccount,
        episode: dict[str, Any],
        *,
        pid: str,
        podcast_title: str,
    ) -> WatchItem | None:
        eid = clean_text(episode.get("eid") or "")
        title = clean_text(episode.get("title") or "")
        if not eid or not title:
            return None
        url = f"{XIAOYUZHOU_BASE}/episode/{eid}"
        published_at = _published_iso(episode.get("pubDate"))
        description = clean_html_text(episode.get("description") or episode.get("shownotes") or "")
        item_id = f"xiaoyuzhou:episode:{eid}"
        metrics = {
            "duration_seconds": episode.get("duration") or 0,
            "play_count": episode.get("playCount") or 0,
            "comments": episode.get("commentCount") or 0,
            "favorites": episode.get("favoriteCount") or 0,
        }
        metrics = {key: value for key, value in metrics.items() if value}
        return WatchItem(
            id=item_id,
            platform="xiaoyuzhou",
            account_id=pid or account.account_id or account.podcast_url,
            account_display_name=podcast_title,
            account_priority=account.priority,
            content_id=eid,
            content_type="podcast_episode",
            title=title,
            text=description,
            url=url,
            canonical_url=canonicalize_url(url),
            published_at=published_at,
            fetched_at=iso_now(),
            author_name=podcast_title,
            topics_configured=list(account.topics),
            metrics=metrics,
            source_method="xiaoyuzhou_public_next_data",
            source_reliability="public_page",
            raw={"pid": pid, "eid": eid},
            enrichment_status=account.enrichment_level if account.enrichment_level else "metadata",
            dedupe_key=eid,
            state_key=f"xiaoyuzhou:{pid or podcast_title}",
        )

    def _enrich_episode_notes(self, item: WatchItem) -> None:
        try:
            html = self.request_text(item.url, timeout=25)
            payload = _next_data(html)
            episode = payload.get("props", {}).get("pageProps", {}).get("episode") or {}
        except Exception:
            return
        notes = clean_html_text(episode.get("shownotes") or "")
        transcript = episode.get("transcript")
        if notes:
            item.enriched_text = notes
            item.text = notes[:1200]
            item.enrichment_status = "episode_notes"
        if isinstance(transcript, str) and transcript.strip():
            item.transcript_text = clean_html_text(transcript)
            if item.transcript_text:
                item.enrichment_status = "transcript"
        comments = payload.get("props", {}).get("pageProps", {}).get("comments") or []
        if isinstance(comments, list) and comments:
            snippets = []
            for comment in comments[:5]:
                if not isinstance(comment, dict):
                    continue
                text = clean_html_text(comment.get("text") or comment.get("content") or "")
                if text:
                    snippets.append(text)
            item.comments_summary = " | ".join(snippets[:3])


def _next_data(html: str) -> dict[str, Any]:
    match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html)
    if not match:
        raise ValueError("Could not find __NEXT_DATA__ in Xiaoyuzhou page.")
    return json.loads(match.group(1))


def _published_iso(value: Any) -> str:
    parsed = parse_datetime(str(value or ""))
    if parsed is None:
        return ""
    return parsed.astimezone(timezone.utc).isoformat()
