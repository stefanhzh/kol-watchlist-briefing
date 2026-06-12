#!/usr/bin/env python3
"""Local We-MP-RSS SQLite provider for WeChat public-account articles."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import re
import sqlite3
from typing import Any

from .base import BaseProvider
from ..models import ProviderResult, WatchAccount, WatchItem
from ..utils import canonicalize_url, clean_html_text, clean_text, iso_now, stable_id


class WeMpRssProvider(BaseProvider):
    platform = "we_mp_rss"

    def fetch(self, account: WatchAccount, *, lookback_hours: int) -> ProviderResult:
        db_paths = self._resolve_db_paths(account)
        if not db_paths:
            return ProviderResult(
                account=account,
                status="not_configured",
                error="Missing or invalid We-MP-RSS db_path/db_paths.",
            )

        rows: list[dict[str, Any]] = []
        errors: list[str] = []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours) if lookback_hours > 0 else None
        for index, db_path in enumerate(db_paths, start=1):
            try:
                rows.extend(self._fetch_db_rows(db_path, account, cutoff=cutoff, limit=max(account.fetch_limit * 3, 20)))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"database[{index}]: {exc.__class__.__name__}: {exc}")

        rows.sort(key=lambda row: int(row.get("publish_time") or 0), reverse=True)
        items: list[WatchItem] = []
        seen_urls: set[str] = set()
        for row in rows:
            item = self._row_to_item(account, row)
            if item is None:
                continue
            if item.canonical_url in seen_urls:
                continue
            seen_urls.add(item.canonical_url)
            items.append(item)
            if len(items) >= account.fetch_limit:
                break

        status = "ok" if items or not errors else "failed"
        if items and errors:
            status = "partial"
        return ProviderResult(account=account, items=items, status=status, error="; ".join(errors))

    def _resolve_db_paths(self, account: WatchAccount) -> list[Path]:
        candidates: list[str] = []
        configured = os.environ.get("WE_MP_RSS_DB_PATHS") or os.environ.get("WE_MP_RSS_DB_PATH") or ""
        if configured:
            candidates.extend(_split_paths(configured))
        if account.db_path:
            candidates.append(account.db_path)
        candidates.extend(account.db_paths)

        output: list[Path] = []
        seen: set[str] = set()
        for candidate in candidates:
            path = Path(os.path.expandvars(os.path.expanduser(candidate))).resolve()
            key = str(path).casefold()
            if key in seen or not path.exists() or not path.is_file():
                continue
            output.append(path)
            seen.add(key)
        return output

    def _fetch_db_rows(
        self,
        db_path: Path,
        account: WatchAccount,
        *,
        cutoff: datetime | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        where = ["a.status = 1", "a.url IS NOT NULL", "a.url != ''", "(f.status IS NULL OR f.status = 1)"]
        params: list[Any] = []
        if cutoff is not None:
            where.append("(a.publish_time IS NULL OR a.publish_time = 0 OR a.publish_time >= ?)")
            params.append(int(cutoff.timestamp()))
        if account.include_mp_names:
            placeholders = ", ".join("?" for _ in account.include_mp_names)
            where.append(f"f.mp_name IN ({placeholders})")
            params.extend(account.include_mp_names)
        if account.include_mp_ids:
            placeholders = ", ".join("?" for _ in account.include_mp_ids)
            where.append(f"a.mp_id IN ({placeholders})")
            params.extend(account.include_mp_ids)

        sql = f"""
            SELECT
                a.id,
                a.mp_id,
                a.title,
                a.url,
                a.description,
                a.publish_time,
                a.status,
                a.has_content,
                a.content,
                a.content_html,
                f.mp_name
            FROM articles a
            LEFT JOIN feeds f ON f.id = a.mp_id
            WHERE {" AND ".join(where)}
            ORDER BY COALESCE(a.publish_time, 0) DESC
            LIMIT ?
        """
        params.append(max(1, int(limit)))
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            connection.row_factory = sqlite3.Row
            rows = [dict(row) for row in connection.execute(sql, params).fetchall()]
        finally:
            connection.close()
        return rows

    def _row_to_item(self, account: WatchAccount, row: dict[str, Any]) -> WatchItem | None:
        title = clean_text(row.get("title") or "")
        url = clean_text(row.get("url") or "")
        if not title or not url:
            return None
        canonical = canonicalize_url(url)
        article_id = clean_text(row.get("id") or "")
        mp_id = clean_text(row.get("mp_id") or "")
        mp_name = clean_text(row.get("mp_name") or "") or account.display_name
        body = clean_html_text(row.get("content") or row.get("content_html") or "")
        description = clean_html_text(row.get("description") or "") or _text_preview(body)
        published_at = _unix_to_iso(row.get("publish_time"))
        item_id = f"we_mp_rss:article:{stable_id(mp_id, article_id or canonical, title)}"
        has_content = bool(row.get("has_content")) and bool(body)
        enrichment_status = "fulltext" if has_content and account.enrichment_level != "metadata" else "metadata"
        return WatchItem(
            id=item_id,
            platform="we_mp_rss",
            account_id=mp_id or account.account_id or account.display_name,
            account_display_name=mp_name,
            account_priority=account.priority,
            content_id=article_id or canonical,
            content_type="article",
            title=title,
            text=description,
            url=url,
            canonical_url=canonical,
            published_at=published_at,
            fetched_at=iso_now(),
            author_name=mp_name,
            topics_configured=list(account.topics),
            metrics={},
            source_method="local_we_mp_rss_sqlite",
            source_reliability="local_database",
            raw={"mp_id": mp_id, "publish_time": row.get("publish_time") or ""},
            enrichment_status=enrichment_status,
            enriched_text=body if enrichment_status == "fulltext" else "",
            dedupe_key=canonical or article_id,
            state_key=f"we_mp_rss:{mp_id or mp_name}",
        )


def _split_paths(value: str) -> list[str]:
    if not value:
        return []
    parts = re.split(r"[;\n]+", value)
    return [part.strip().strip('"') for part in parts if part.strip()]


def _unix_to_iso(value: Any) -> str:
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return ""
    if timestamp <= 0:
        return ""
    try:
        return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return ""


def _text_preview(value: str, max_chars: int = 260) -> str:
    text = clean_text(value)
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."
