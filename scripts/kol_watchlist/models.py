#!/usr/bin/env python3
"""Shared models for KOL watchlist briefings."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class WatchAccount:
    platform: str
    display_name: str
    account_id: str = ""
    handle: str = ""
    feed_url: str = ""
    podcast_url: str = ""
    episode_url: str = ""
    priority: str = "medium"
    topics: list[str] = field(default_factory=list)
    fetch_limit: int = 10
    include_replies: bool = False
    include_comments: bool = False
    enrichment_level: str = "metadata"
    source_mode: str = ""
    watch_types: list[str] = field(default_factory=list)
    db_path: str = ""
    db_paths: list[str] = field(default_factory=list)
    include_mp_names: list[str] = field(default_factory=list)
    include_mp_ids: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        identifier = self.account_id or self.handle or self.feed_url or self.display_name
        return f"{self.platform}:{identifier}"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("raw", None)
        return data


@dataclass
class WatchItem:
    id: str
    platform: str
    account_id: str
    account_display_name: str
    account_priority: str
    content_id: str
    content_type: str
    title: str
    url: str
    canonical_url: str
    published_at: str = ""
    fetched_at: str = ""
    author_name: str = ""
    text: str = ""
    topics_configured: list[str] = field(default_factory=list)
    topics_matched: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    source_method: str = ""
    source_reliability: str = ""
    raw: dict[str, Any] = field(default_factory=dict)
    enrichment_status: str = "metadata"
    enriched_text: str = ""
    transcript_text: str = ""
    comments_summary: str = ""
    importance_score: float = 0.0
    importance_reasons: list[str] = field(default_factory=list)
    dedupe_key: str = ""
    state_key: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("raw", None)
        return data


@dataclass
class ProviderResult:
    account: WatchAccount
    items: list[WatchItem] = field(default_factory=list)
    status: str = "ok"
    error: str = ""
    diagnostics: list[str] = field(default_factory=list)

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "platform": self.account.platform,
            "account": self.account.display_name,
            "account_key": f"{self.account.platform}:{self.account.display_name}",
            "status": self.status,
            "raw_count": len(self.items),
            "error": self.error,
            "diagnostics": self.diagnostics,
        }


@dataclass
class WatchlistConfig:
    version: int
    timezone: str
    default_lookback_hours: int
    defaults: dict[str, Any]
    ranking: dict[str, float]
    accounts: list[WatchAccount]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "timezone": self.timezone,
            "default_lookback_hours": self.default_lookback_hours,
            "defaults": self.defaults,
            "ranking": self.ranking,
            "accounts": [account.to_dict() for account in self.accounts],
        }


@dataclass
class WatchlistReport:
    run_meta: dict[str, Any]
    source_summaries: list[dict[str, Any]]
    items: list[WatchItem]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_meta": self.run_meta,
            "source_summaries": self.source_summaries,
            "items": [item.to_dict() for item in self.items],
        }
