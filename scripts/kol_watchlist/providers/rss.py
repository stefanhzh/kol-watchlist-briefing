#!/usr/bin/env python3
"""Generic RSS/Atom provider for KOL watchlist sources."""

from __future__ import annotations

from datetime import timezone
import xml.etree.ElementTree as ET

from .base import BaseProvider
from ..models import ProviderResult, WatchAccount, WatchItem
from ..utils import canonicalize_url, clean_html_text, clean_text, iso_now, parse_datetime, stable_id


class RssProvider(BaseProvider):
    platform = "rss"

    def fetch(self, account: WatchAccount, *, lookback_hours: int) -> ProviderResult:
        if not account.feed_url:
            return ProviderResult(account=account, status="skipped", error="Missing feed_url.")
        try:
            xml_text = self.request_text(account.feed_url, timeout=25)
            items = self._parse_feed(account, xml_text, lookback_hours)
        except Exception as exc:  # noqa: BLE001
            return ProviderResult(account=account, status="failed", error=f"{exc.__class__.__name__}: {exc}")
        return ProviderResult(account=account, items=items, status="ok")

    def _parse_feed(self, account: WatchAccount, xml_text: str, lookback_hours: int) -> list[WatchItem]:
        root = ET.fromstring(xml_text)
        if root.tag.endswith("feed"):
            return self._parse_atom(account, root, lookback_hours)
        return self._parse_rss(account, root, lookback_hours)

    def _parse_rss(self, account: WatchAccount, root: ET.Element, lookback_hours: int) -> list[WatchItem]:
        channel_title = clean_text(root.findtext("./channel/title", default="")) or account.display_name
        items: list[WatchItem] = []
        for node in root.findall("./channel/item")[: account.fetch_limit * 2]:
            title = clean_text(node.findtext("title", default=""))
            link = clean_text(node.findtext("link", default=""))
            guid = clean_text(node.findtext("guid", default=""))
            pub_date = clean_text(node.findtext("pubDate", default=""))
            description = clean_html_text(node.findtext("description", default=""))
            published_at = self._published_iso(pub_date)
            if not title or not link:
                continue
            if published_at and not self.within_lookback(published_at, lookback_hours):
                continue
            items.append(self._item(account, title, link, guid or link, published_at, description, channel_title))
            if len(items) >= account.fetch_limit:
                break
        return items

    def _parse_atom(self, account: WatchAccount, root: ET.Element, lookback_hours: int) -> list[WatchItem]:
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        feed_title = clean_text(root.findtext("atom:title", default="", namespaces=ns)) or account.display_name
        entries = root.findall("atom:entry", ns)
        items: list[WatchItem] = []
        for entry in entries[: account.fetch_limit * 2]:
            title = clean_text(entry.findtext("atom:title", default="", namespaces=ns))
            link_node = entry.find("atom:link", ns)
            link = clean_text(link_node.attrib.get("href", "")) if link_node is not None else ""
            content_id = clean_text(entry.findtext("atom:id", default="", namespaces=ns)) or link
            published_raw = (
                clean_text(entry.findtext("atom:published", default="", namespaces=ns))
                or clean_text(entry.findtext("atom:updated", default="", namespaces=ns))
            )
            media_description = ""
            media_group = entry.find("{http://search.yahoo.com/mrss/}group")
            if media_group is not None:
                media_description = clean_html_text(
                    media_group.findtext("{http://search.yahoo.com/mrss/}description", default="")
                )
            summary = (
                clean_html_text(entry.findtext("atom:summary", default="", namespaces=ns))
                or clean_html_text(entry.findtext("atom:content", default="", namespaces=ns))
                or media_description
            )
            published_at = self._published_iso(published_raw)
            if not title or not link:
                continue
            if published_at and not self.within_lookback(published_at, lookback_hours):
                continue
            items.append(self._item(account, title, link, content_id, published_at, summary, feed_title))
            if len(items) >= account.fetch_limit:
                break
        return items

    def _published_iso(self, raw_value: str) -> str:
        parsed = parse_datetime(raw_value)
        if parsed is None:
            return ""
        return parsed.astimezone(timezone.utc).isoformat()

    def _item(
        self,
        account: WatchAccount,
        title: str,
        link: str,
        content_id: str,
        published_at: str,
        summary: str,
        author: str,
    ) -> WatchItem:
        canonical = canonicalize_url(link)
        item_id = f"{account.platform}:{stable_id(account.key, content_id or canonical, title)}"
        state_key = account.key
        return WatchItem(
            id=item_id,
            platform=account.platform,
            account_id=account.account_id or account.feed_url,
            account_display_name=account.display_name,
            account_priority=account.priority,
            content_id=content_id or canonical,
            content_type="podcast_episode" if account.platform in {"xiaoyuzhou", "podcast"} else "article",
            title=title,
            text=summary,
            url=link,
            canonical_url=canonical,
            published_at=published_at,
            fetched_at=iso_now(),
            author_name=author,
            topics_configured=list(account.topics),
            source_method=account.source_mode or "rss",
            source_reliability="public_rss",
            enrichment_status=account.enrichment_level,
            dedupe_key=canonical or content_id,
            state_key=state_key,
        )
