#!/usr/bin/env python3
"""Local state for KOL watchlist runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import WatchItem
from .utils import iso_now


EMPTY_STATE = {"version": 1, "accounts": {}}


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return json.loads(json.dumps(EMPTY_STATE))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return json.loads(json.dumps(EMPTY_STATE))
    if not isinstance(data, dict):
        return json.loads(json.dumps(EMPTY_STATE))
    data.setdefault("version", 1)
    data.setdefault("accounts", {})
    return data


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def filter_unseen_items(items: list[WatchItem], state: dict[str, Any]) -> list[WatchItem]:
    accounts = state.setdefault("accounts", {})
    kept: list[WatchItem] = []
    for item in items:
        account_state = accounts.get(item.state_key, {})
        seen = set(account_state.get("seen_item_ids") or [])
        if item.id in seen:
            continue
        kept.append(item)
    return kept


def mark_seen(items: list[WatchItem], state: dict[str, Any]) -> None:
    accounts = state.setdefault("accounts", {})
    for item in items:
        account_state = accounts.setdefault(
            item.state_key,
            {"last_run_at": "", "seen_item_ids": [], "last_seen_published_at": ""},
        )
        seen = list(account_state.get("seen_item_ids") or [])
        if item.id not in seen:
            seen.append(item.id)
        account_state["seen_item_ids"] = seen[-500:]
        account_state["last_run_at"] = iso_now()
        if item.published_at:
            last_seen = account_state.get("last_seen_published_at") or ""
            account_state["last_seen_published_at"] = max(last_seen, item.published_at)

