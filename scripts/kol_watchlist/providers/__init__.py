"""Provider registry for KOL watchlist sources."""

from __future__ import annotations

from .base import BaseProvider
from .rss import RssProvider
from .we_mp_rss import WeMpRssProvider
from .xiaoyuzhou import XiaoyuzhouProvider
from .youtube import YouTubeProvider


PROVIDERS: dict[str, type[BaseProvider]] = {
    "rss": RssProvider,
    "xiaoyuzhou": XiaoyuzhouProvider,
    "podcast": RssProvider,
    "we_mp_rss": WeMpRssProvider,
    "wechat": WeMpRssProvider,
    "youtube": YouTubeProvider,
}


def provider_for(platform: str) -> BaseProvider | None:
    provider_cls = PROVIDERS.get(platform.lower())
    return provider_cls() if provider_cls else None
