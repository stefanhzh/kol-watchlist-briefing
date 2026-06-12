#!/usr/bin/env python3
"""YouTube channel RSS provider for KOL watchlist sources."""

from __future__ import annotations

from .rss import RssProvider
from ..models import ProviderResult, WatchAccount


class YouTubeProvider(RssProvider):
    platform = "youtube"

    def fetch(self, account: WatchAccount, *, lookback_hours: int) -> ProviderResult:
        if not account.feed_url:
            if account.account_id:
                account.feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={account.account_id}"
            else:
                return ProviderResult(account=account, status="skipped", error="Missing account_id or feed_url.")
        result = super().fetch(account, lookback_hours=lookback_hours)
        for item in result.items:
            item.platform = "youtube"
            item.content_type = "video"
            item.source_method = "youtube_channel_rss"
            item.source_reliability = "official_rss"
            item.account_id = account.account_id or account.handle or account.feed_url
            if item.url and "watch?v=" in item.url:
                item.content_id = item.url.rsplit("watch?v=", 1)[-1].split("&", 1)[0]
                item.id = f"youtube:video:{item.content_id}"
        return result

