import asyncio
from unittest.mock import AsyncMock

import discord

from rawkuma_bot.commands.discord_bot import ChapterBrowser, RawkumaBot
from rawkuma_bot.config.settings import Settings
from rawkuma_bot.downloaders.models import Chapter, MangaInfo


def test_command_tree_contains_only_download(tmp_path):
    bot = RawkumaBot(Settings(temp_dir=tmp_path / "temp", output_dir=tmp_path / "downloads"))
    bot.tree.add_command(bot.download)
    assert {command.name for command in bot.tree.get_commands()} == {"download"}


def test_guild_mode_registers_download_in_one_scope_only(tmp_path):
    bot = RawkumaBot(
        Settings(
            temp_dir=tmp_path / "temp",
            output_dir=tmp_path / "downloads",
            discord_guild_id=123456789,
        )
    )
    bot.manager.start = AsyncMock()
    bot.tree.sync = AsyncMock()

    asyncio.run(bot.setup_hook())

    guild = discord.Object(id=123456789)
    assert [command.name for command in bot.tree.get_commands()] == []
    assert [command.name for command in bot.tree.get_commands(guild=guild)] == ["download"]
    assert bot.tree.sync.await_count == 2


def test_command_tree_has_direct_error_handler(tmp_path):
    bot = RawkumaBot(Settings(temp_dir=tmp_path / "temp", output_dir=tmp_path / "downloads"))
    assert bot.tree.on_error.__self__ is bot


def test_download_view_supports_twenty_chapter_selection(tmp_path):
    bot = RawkumaBot(Settings(temp_dir=tmp_path / "temp", output_dir=tmp_path / "downloads"))
    chapters = [Chapter(float(i), f"Chapter {i}", f"https://rawkuma.net/chapter-{i}") for i in range(1, 101)]
    view = ChapterBrowser(bot, MangaInfo("Demo", "https://rawkuma.net/manga/demo"), chapters)
    select = view.children[0]
    assert view.page_count == 5
    assert len(select.options) == 20
    assert select.max_values == 20
