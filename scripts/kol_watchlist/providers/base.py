#!/usr/bin/env python3
"""Provider base class for KOL watchlist sources."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..models import ProviderResult, WatchAccount
from ..utils import request_text


class BaseProvider:
    platform = ""

    def request_text(self, url: str, *, timeout: int = 20) -> str:
        return request_text(url, timeout=timeout)

    def fetch(self, account: WatchAccount, *, lookback_hours: int) -> ProviderResult:
        raise NotImplementedError

    def within_lookback(self, published_at: str, lookback_hours: int) -> bool:
        try:
            parsed = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        except ValueError:
            return True
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc) >= datetime.now(timezone.utc) - timedelta(hours=lookback_hours)

