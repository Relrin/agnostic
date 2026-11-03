"""Where git hosts post webhooks: the public URL people reach Agnostic at."""

from __future__ import annotations

from agnostic_kernel.settings import Settings
from agnostic_sources.settings import SourcesSettings


class PublicWebhookUrls:
    def __init__(self, settings: Settings, sources: SourcesSettings) -> None:
        self._public = sources.webhook_base_url or settings.http.public_url

    def url(self, provider: str) -> str | None:
        """``None`` without an explicit public URL: a git host couldn't reach a default local address anyway."""
        if not self._public:
            return None
        return f"{self._public.rstrip('/')}/hooks/{provider}"
