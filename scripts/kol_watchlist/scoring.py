#!/usr/bin/env python3
"""Deterministic importance scoring for KOL watchlist items."""

from __future__ import annotations

from datetime import datetime, timezone
import math

from .models import WatchItem, WatchlistConfig
from .utils import parse_datetime


PRIORITY_SCORE = {
    "critical": 1.0,
    "high": 0.82,
    "medium": 0.55,
    "low": 0.25,
}

CONTENT_TYPE_SCORE = {
    "release": 1.0,
    "issue": 0.82,
    "pull_request": 0.76,
    "podcast_episode": 0.72,
    "video": 0.70,
    "article": 0.68,
    "comment_thread": 0.58,
    "post": 0.48,
    "commit": 0.42,
}

RELIABILITY_SCORE = {
    "official_api": 1.0,
    "official_rss": 0.95,
    "public_rss": 0.82,
    "local_database": 0.82,
    "public_page": 0.68,
    "browser_session": 0.55,
    "reader_mirror": 0.48,
    "third_party_api": 0.45,
    "manual_export": 0.40,
}

ENRICHMENT_SCORE = {
    "deep": 1.0,
    "episode_notes": 0.86,
    "comments": 0.84,
    "transcript": 0.80,
    "browser_fulltext": 0.72,
    "fulltext": 0.65,
    "metadata": 0.30,
}


def _recency_score(published_at: str, now: datetime, lookback_hours: int) -> float:
    parsed = parse_datetime(published_at)
    if parsed is None:
        return 0.35
    age_hours = max(0.0, (now - parsed).total_seconds() / 3600)
    if age_hours <= 6:
        return 1.0
    if age_hours <= 24:
        return 0.78
    if age_hours <= lookback_hours:
        return 0.55
    return 0.22


def _engagement_score(metrics: dict[str, object]) -> float:
    total = 0.0
    for key in ("comments", "comment_count", "likes", "like_count", "views", "stars", "score"):
        value = metrics.get(key)
        if isinstance(value, (int, float)):
            total += max(0.0, float(value))
    if total <= 0:
        return 0.0
    return min(1.0, math.log10(total + 1) / 6)


def _topic_score(item: WatchItem) -> float:
    haystack = f"{item.title} {item.text}".lower()
    matched = [topic for topic in item.topics_configured if topic.lower() in haystack]
    item.topics_matched = matched
    if matched:
        return min(1.0, 0.55 + 0.15 * len(matched))
    if item.topics_configured:
        return 0.18
    return 0.0


def score_items(
    items: list[WatchItem],
    config: WatchlistConfig,
    *,
    now: datetime | None = None,
    lookback_hours: int | None = None,
) -> list[WatchItem]:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    hours = lookback_hours or config.default_lookback_hours
    weights = config.ranking

    for item in items:
        components = {
            "account_priority_weight": PRIORITY_SCORE.get(item.account_priority, 0.45),
            "topic_match_weight": _topic_score(item),
            "recency_weight": _recency_score(item.published_at, current, hours),
            "engagement_weight": _engagement_score(item.metrics),
            "content_type_weight": CONTENT_TYPE_SCORE.get(item.content_type, 0.45),
            "enrichment_weight": ENRICHMENT_SCORE.get(item.enrichment_status, 0.30),
            "reliability_weight": RELIABILITY_SCORE.get(item.source_reliability, 0.45),
        }
        weighted = sum(weights.get(name, 0.0) * score for name, score in components.items())
        denominator = sum(weights.get(name, 0.0) for name in components)
        item.importance_score = round((weighted / denominator) * 100, 2) if denominator else 0.0
        reasons: list[str] = []
        if item.account_priority in {"critical", "high"}:
            reasons.append(f"{item.account_priority}-priority account")
        if item.topics_matched:
            reasons.append("matched topics: " + ", ".join(item.topics_matched[:3]))
        if components["recency_weight"] >= 0.78:
            reasons.append("fresh update")
        if components["engagement_weight"] >= 0.35:
            reasons.append("meaningful engagement signal")
        if item.source_reliability in {"official_api", "official_rss", "public_rss"}:
            reasons.append(item.source_reliability.replace("_", " "))
        item.importance_reasons = reasons

    return sorted(items, key=lambda item: (item.importance_score, item.published_at, item.title), reverse=True)
