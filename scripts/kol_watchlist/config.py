#!/usr/bin/env python3
"""Config loading for KOL watchlist briefings."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
from typing import Any

from .models import WatchAccount, WatchlistConfig


DEFAULTS: dict[str, Any] = {
    "fetch_limit": 10,
    "include_replies": False,
    "include_comments": False,
    "enrichment_level": "metadata",
    "priority": "medium",
}

DEFAULT_RANKING: dict[str, float] = {
    "account_priority_weight": 0.24,
    "topic_match_weight": 0.22,
    "recency_weight": 0.16,
    "engagement_weight": 0.14,
    "content_type_weight": 0.10,
    "enrichment_weight": 0.08,
    "reliability_weight": 0.06,
}


def backup_config(path: Path) -> Path | None:
    """Back up a local watchlist config before overwriting it."""
    if not path.exists():
        return None
    backup_path = path.with_name(path.name + ".bak")
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, backup_path)
    return backup_path


def ensure_config_from_example(path: Path, example_path: Path) -> bool:
    """Create a local watchlist config from the public example if it is missing."""
    if path.exists():
        return False
    if not example_path.exists():
        raise FileNotFoundError(f"Example config not found: {example_path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(example_path, path)
    return True


def _load_raw_config(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(text)
    try:
        import yaml
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("YAML config requires PyYAML. Use JSON or install PyYAML.") from exc
    loaded = yaml.safe_load(text) or {}
    if not isinstance(loaded, dict):
        raise ValueError("Watchlist config must be a mapping.")
    return loaded


def load_raw_config(path: Path) -> dict[str, Any]:
    return _load_raw_config(path)


def write_raw_config(path: Path, raw: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".json":
        path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        return
    try:
        import yaml
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("YAML config requires PyYAML. Use JSON or install PyYAML.") from exc
    path.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")


def append_account_to_config(path: Path, account: dict[str, Any]) -> bool:
    """Append an account entry after backing up the local config.

    Returns True when an account was added, or False when the same source is
    already present.
    """
    raw = load_raw_config(path)
    accounts = raw.setdefault("accounts", [])
    if not isinstance(accounts, list):
        raise ValueError("watchlist config field 'accounts' must be a list.")
    if any(_account_identity(existing) == _account_identity(account) for existing in accounts if isinstance(existing, dict)):
        return False
    backup_config(path)
    accounts.append(account)
    write_raw_config(path, raw)
    return True


def _account_identity(account: dict[str, Any]) -> tuple[str, str]:
    platform = str(account.get("platform", "")).strip().lower()
    identifier = (
        account.get("feed_url")
        or account.get("podcast_url")
        or account.get("episode_url")
        or account.get("account_id")
        or account.get("handle")
        or account.get("display_name")
        or ""
    )
    return platform, str(identifier).strip().rstrip("/").lower()


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _account_from_raw(raw: dict[str, Any], defaults: dict[str, Any]) -> WatchAccount:
    merged = {**defaults, **raw}
    platform = str(merged.get("platform", "")).strip().lower()
    display_name = str(merged.get("display_name") or merged.get("handle") or merged.get("account_id") or "").strip()
    if not platform:
        raise ValueError("Watchlist account is missing platform.")
    if not display_name:
        raise ValueError(f"Watchlist account for platform {platform} is missing display_name.")
    return WatchAccount(
        platform=platform,
        display_name=display_name,
        account_id=str(merged.get("account_id", "")).strip(),
        handle=str(merged.get("handle", "")).strip().lstrip("@"),
        feed_url=str(merged.get("feed_url", "")).strip(),
        podcast_url=str(merged.get("podcast_url", "")).strip(),
        episode_url=str(merged.get("episode_url", "")).strip(),
        priority=str(merged.get("priority", "medium")).strip().lower(),
        topics=_as_list(merged.get("topics")),
        fetch_limit=max(1, int(merged.get("fetch_limit", 10))),
        include_replies=bool(merged.get("include_replies", False)),
        include_comments=bool(merged.get("include_comments", False)),
        enrichment_level=str(merged.get("enrichment_level", "metadata")).strip().lower(),
        source_mode=str(merged.get("source_mode", "")).strip().lower(),
        watch_types=_as_list(merged.get("watch_types")),
        db_path=str(merged.get("db_path", "")).strip(),
        db_paths=_as_list(merged.get("db_paths")),
        include_mp_names=_as_list(merged.get("include_mp_names")),
        include_mp_ids=_as_list(merged.get("include_mp_ids")),
        raw=dict(raw),
    )


def load_watchlist_config(path: Path) -> WatchlistConfig:
    raw = _load_raw_config(path)
    defaults = {**DEFAULTS, **(raw.get("defaults") or {})}
    ranking = {**DEFAULT_RANKING, **(raw.get("ranking") or {})}
    accounts_raw = raw.get("accounts") or []
    if not isinstance(accounts_raw, list):
        raise ValueError("watchlist config field 'accounts' must be a list.")
    accounts = [_account_from_raw(account, defaults) for account in accounts_raw]
    return WatchlistConfig(
        version=int(raw.get("version", 1)),
        timezone=str(raw.get("timezone", "Asia/Shanghai")),
        default_lookback_hours=int(raw.get("default_lookback_hours", 24)),
        defaults=defaults,
        ranking={key: float(value) for key, value in ranking.items()},
        accounts=accounts,
    )
