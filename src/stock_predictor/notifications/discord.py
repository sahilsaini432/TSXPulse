from __future__ import annotations

import logging
import os
from typing import Iterable

from discord_webhook import DiscordEmbed, DiscordWebhook

from TSXPulse.config import AppConfig, load_env


log = logging.getLogger(__name__)


class DiscordNotifier:
    """Thin wrapper around discord-webhook. Gracefully no-ops when disabled or URL missing."""

    def __init__(self, cfg: AppConfig):
        load_env()
        self.enabled = cfg.discord.enabled
        self.webhook_url = os.getenv(cfg.discord.webhook_url_env)
        if self.enabled and not self.webhook_url:
            log.warning(
                "Discord enabled but %s is unset. Messages will be logged only.",
                cfg.discord.webhook_url_env,
            )

    def _send(self, embeds: Iterable[DiscordEmbed], content: str | None = None) -> bool:
        embeds = list(embeds)
        if not self.enabled or not self.webhook_url:
            for e in embeds:
                log.info("[discord:dry-run] %s", getattr(e, "title", "(no title)"))
            return False
        try:
            webhook = DiscordWebhook(url=self.webhook_url, content=content)
            for e in embeds:
                webhook.add_embed(e)
            resp = webhook.execute()
            ok = bool(resp and getattr(resp, "status_code", 0) in (200, 204))
            if not ok:
                log.warning("Discord POST failed: status=%s", getattr(resp, "status_code", "n/a"))
            return ok
        except Exception as e:
            log.exception("Discord POST raised: %s", e)
            return False

    def send_embed(self, embed: DiscordEmbed, content: str | None = None) -> bool:
        return self._send([embed], content=content)

    def send_embeds(self, embeds: list[DiscordEmbed]) -> bool:
        return self._send(embeds)
