#!/usr/bin/env python3
"""Utility helpers for KOL watchlist briefings."""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0 Safari/537.36"
)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return now_utc().isoformat()


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value or "")).strip()


def clean_html_text(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value or "")
    return clean_text(without_tags)


def title_key(value: str) -> str:
    normalized = (value or "").lower()
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"[^a-z0-9\u4e00-\u9fff ]+", "", normalized)
    return normalized.strip()


def stable_id(*parts: str) -> str:
    raw = "|".join(part or "" for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return digest


def canonicalize_url(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = urlsplit(value.strip())
    except Exception:
        return value.strip()
    hostname = (parsed.hostname or "").lower().removeprefix("www.")
    netloc = hostname
    if parsed.port:
        netloc = f"{hostname}:{parsed.port}"
    query_pairs = [
        (key, val)
        for key, val in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid"}
    ]
    path = parsed.path.rstrip("/") or parsed.path
    return urlunsplit((parsed.scheme.lower(), netloc, path, urlencode(query_pairs), ""))


def parse_datetime(value: str) -> datetime | None:
    raw = clean_text(value)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(raw)
        except Exception:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def request_text(url: str, *, timeout: int = 20, user_agent: str = DEFAULT_USER_AGENT) -> str:
    request = Request(url, headers={"User-Agent": user_agent})
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")
