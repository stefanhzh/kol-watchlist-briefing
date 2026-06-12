#!/usr/bin/env python3
"""Markdown/HTML rendering for KOL watchlist reports."""

from __future__ import annotations

from collections import defaultdict
from html import escape
import json
from pathlib import Path
from typing import Any

from .models import WatchItem, WatchlistReport


def _md(value: object) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ").strip()


def render_markdown(report: WatchlistReport) -> str:
    generated_at = report.run_meta.get("generated_at", "")
    lines = [
        f"# KOL Watchlist Briefing - {generated_at[:10]}",
        "",
        f"- Generated: `{generated_at}`",
        f"- Lookback: `{report.run_meta.get('lookback_hours')}h`",
        f"- Accounts: `{report.run_meta.get('account_count')}`",
        f"- Items: `{len(report.items)}`",
        "",
        "## 最值得先看",
        "",
    ]
    if not report.items:
        lines.append("No new watchlist items found in this run.")
    for index, item in enumerate(report.items[:10], start=1):
        lines.extend(_render_item(index, item))

    by_platform: dict[str, list[WatchItem]] = defaultdict(list)
    by_account: dict[str, list[WatchItem]] = defaultdict(list)
    for item in report.items:
        by_platform[item.platform].append(item)
        by_account[item.account_display_name].append(item)

    lines.extend(["", "## 按平台", ""])
    for platform in sorted(by_platform):
        lines.extend([f"### {platform}", ""])
        for index, item in enumerate(by_platform[platform][:8], start=1):
            lines.extend(_render_item(index, item, compact=True))

    lines.extend(["", "## 按账号", ""])
    for account in sorted(by_account):
        lines.extend([f"### {account}", ""])
        for index, item in enumerate(by_account[account][:8], start=1):
            lines.extend(_render_item(index, item, compact=True))

    lines.extend(["", "## 抓取诊断", ""])
    for summary in report.source_summaries:
        note = summary.get("error") or "; ".join(summary.get("diagnostics") or [])
        lines.append(
            "- {platform} / {account}: {status}, {count} items{note}".format(
                platform=_md(summary.get("platform")),
                account=_md(summary.get("account")),
                status=_md(summary.get("status")),
                count=summary.get("raw_count", 0),
                note=f" - {_md(note)}" if note else "",
            )
        )
    return "\n".join(lines).rstrip() + "\n"


def _render_item(index: int, item: WatchItem, *, compact: bool = False) -> list[str]:
    title = _md(item.title) or "(untitled)"
    url = item.canonical_url or item.url
    reasons = "; ".join(item.importance_reasons[:3])
    meta = " | ".join(
        part
        for part in [
            item.account_display_name,
            item.platform,
            item.published_at,
            f"score {item.importance_score:.1f}",
        ]
        if part
    )
    lines = [f"{index}. [{title}]({url})", f"   - {meta}"]
    if item.text and not compact:
        summary = item.text[:260].rstrip()
        if len(item.text) > 260:
            summary += "..."
        lines.append(f"   - Summary: {_md(summary)}")
    if reasons:
        lines.append(f"   - Why: {_md(reasons)}")
    lines.append("")
    return lines


def render_html(report: WatchlistReport) -> str:
    body = render_markdown(report)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>KOL Watchlist Briefing</title>
  <style>
    body {{ font-family: "Segoe UI", "Noto Sans SC", sans-serif; line-height: 1.6; margin: 40px; color: #17211b; }}
    pre {{ white-space: pre-wrap; background: #f7f7f4; padding: 20px; border: 1px solid #ddd; }}
  </style>
</head>
<body>
  <pre>{escape(body)}</pre>
</body>
</html>
"""


def write_outputs(output_dir: Path, report: WatchlistReport, formats: set[str]) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}
    if "json" in formats:
        path = output_dir / "report.json"
        path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        written["json"] = str(path)
    if "md" in formats:
        path = output_dir / "report.md"
        path.write_text(render_markdown(report), encoding="utf-8")
        written["md"] = str(path)
    if "html" in formats:
        path = output_dir / "index.html"
        path.write_text(render_html(report), encoding="utf-8")
        written["html"] = str(path)
    summary_path = output_dir / "source_summary.json"
    summary_path.write_text(
        json.dumps(report.source_summaries, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    written["source_summary"] = str(summary_path)
    return written

