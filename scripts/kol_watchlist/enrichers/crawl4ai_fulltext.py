#!/usr/bin/env python3
"""Optional Crawl4AI fulltext enrichment for web articles."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from ..models import WatchItem
from ..utils import clean_text


CRAWL4AI_LEVELS = {"crawl4ai", "browser_fulltext"}
DEFAULT_MAX_CHARS = 12000


@dataclass
class Crawl4AIEnrichmentSummary:
    attempted: int = 0
    enriched: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def to_diagnostics(self) -> list[str]:
        diagnostics = [
            f"crawl4ai attempted={self.attempted}",
            f"crawl4ai enriched={self.enriched}",
            f"crawl4ai skipped={self.skipped}",
        ]
        diagnostics.extend(self.errors[:5])
        return diagnostics


def needs_crawl4ai(item: WatchItem) -> bool:
    return item.enrichment_status.lower() in CRAWL4AI_LEVELS and bool(item.canonical_url or item.url)


def enrich_items_with_crawl4ai(
    items: list[WatchItem],
    *,
    max_items: int = 5,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> Crawl4AIEnrichmentSummary:
    """Enrich eligible items with Crawl4AI markdown.

    Crawl4AI is optional. If it is not installed or browser setup is missing, the
    caller receives diagnostics and the original items remain usable.
    """
    eligible = [item for item in items if needs_crawl4ai(item)]
    summary = Crawl4AIEnrichmentSummary(skipped=max(0, len(eligible) - max_items))
    targets = eligible[:max_items]
    if not targets:
        return summary
    try:
        asyncio.run(_enrich_async(targets, summary=summary, max_chars=max_chars))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_enrich_async(targets, summary=summary, max_chars=max_chars))
        finally:
            loop.close()
    return summary


async def _enrich_async(
    items: list[WatchItem],
    *,
    summary: Crawl4AIEnrichmentSummary,
    max_chars: int,
) -> None:
    try:
        from crawl4ai import AsyncWebCrawler  # type: ignore
    except Exception as exc:  # noqa: BLE001
        summary.errors.append(f"crawl4ai unavailable: {exc.__class__.__name__}")
        summary.skipped += len(items)
        return

    try:
        async with AsyncWebCrawler() as crawler:
            for item in items:
                summary.attempted += 1
                await _enrich_one(crawler, item, summary=summary, max_chars=max_chars)
    except Exception as exc:  # noqa: BLE001
        summary.errors.append(f"crawl4ai session failed: {exc.__class__.__name__}: {exc}")


async def _enrich_one(
    crawler: Any,
    item: WatchItem,
    *,
    summary: Crawl4AIEnrichmentSummary,
    max_chars: int,
) -> None:
    url = item.canonical_url or item.url
    try:
        result = await crawler.arun(url)
    except Exception as exc:  # noqa: BLE001
        summary.errors.append(f"crawl4ai failed for {item.title[:60]}: {exc.__class__.__name__}")
        return
    markdown = _extract_markdown(result)
    if not markdown:
        summary.errors.append(f"crawl4ai empty result for {item.title[:60]}")
        return
    item.enriched_text = markdown[:max_chars].rstrip()
    if item.enriched_text and len(markdown) > max_chars:
        item.enriched_text += "\n\n[truncated]"
    item.text = clean_text(item.enriched_text[:1200]) or item.text
    item.enrichment_status = "crawl4ai_fulltext"
    item.source_method = f"{item.source_method}+crawl4ai" if item.source_method else "crawl4ai"
    summary.enriched += 1


def _extract_markdown(result: Any) -> str:
    markdown = getattr(result, "markdown", "")
    candidates: list[Any] = []
    if isinstance(markdown, str):
        candidates.append(markdown)
    else:
        candidates.extend(
            [
                getattr(markdown, "fit_markdown", ""),
                getattr(markdown, "raw_markdown", ""),
                str(markdown) if markdown else "",
            ]
        )
    candidates.extend([getattr(result, "fit_markdown", ""), getattr(result, "raw_markdown", "")])
    for candidate in candidates:
        text = clean_text(candidate)
        if text:
            return text
    return ""
