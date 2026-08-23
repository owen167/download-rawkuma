from __future__ import annotations

import logging

from rawkuma_bot.commands.discord_bot import RawkumaBot
from rawkuma_bot.config.settings import settings
from rawkuma_bot.database.schema import create_schema
from rawkuma_bot.utils.logging_setup import setup_logging


RELEASE = "v29"


def run() -> None:
    settings.prepare_directories()
    setup_logging(settings.log_dir)
    log = logging.getLogger(__name__)
    log.info("Starting Rawkuma Discord Bot release=%s", RELEASE)
    if not settings.discord_token:
        log.error("DISCORD_TOKEN is missing")
        raise SystemExit("DISCORD_TOKEN is required")
    create_schema(settings.database_url)
    log.info("Database schema ready")
    bot = RawkumaBot(settings)
    bot.run(settings.discord_token, log_handler=None)


if __name__ == "__main__":
    run()
