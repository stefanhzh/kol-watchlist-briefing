#!/usr/bin/env python3
"""Dedupe helpers for KOL watchlist items."""

from __future__ import annotations

from .models import WatchItem
from .utils import canonicalize_url, title_key


def dedupe_items(items: list[WatchItem]) -> list[WatchItem]:
    seen: set[str] = set()
    deduped: list[WatchItem] = []
    for item in items:
        canonical = canonicalize_url(item.canonical_url or item.url)
        keys = [
            item.dedupe_key,
            f"{item.platform}:{item.content_id}" if item.content_id else "",
            canonical,
            f"{item.platform}:{item.account_id}:{title_key(item.title)}",
        ]
        key = next((candidate for candidate in keys if candidate), "")
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped

