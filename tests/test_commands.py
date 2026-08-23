import ast
import asyncio
import inspect
from pathlib import Path
from unittest.mock import AsyncMock

import discord

from rawkuma_bot.commands.discord_bot import ChapterBrowser, RawkumaBot, info_embed
from rawkuma_bot.config.settings import Settings
from rawkuma_bot.downloaders.models import Chapter, MangaInfo


def test_all_user_visible_discord_sends_use_embeds():
    source = Path(__file__).parents[1] / "src" / "rawkuma_bot" / "commands" / "discord_bot.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    send_methods = {"send_message", "send", "edit_message", "edit"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in send_methods:
            continue
        assert any(keyword.arg == "embed" for keyword in node.keywords), ast.unparse(node)


def test_command_tree_contains_exactly_the_three_supported_commands(tmp_path):
    bot = RawkumaBot(Settings(temp_dir=tmp_path / "temp", output_dir=tmp_path / "downloads"))
    bot.tree.add_command(bot.download)
    bot.tree.add_command(bot.download_naver)
    bot.tree.add_command(bot.download_kakao)
    assert {command.name for command in bot.tree.get_commands()} == {"download", "download-naver", "download-kakao"}


def test_guild_mode_registers_both_commands_in_one_scope_only(tmp_path):
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
    assert [command.name for command in bot.tree.get_commands(guild=guild)] == ["download", "download-naver", "download-kakao"]
    assert bot.tree.sync.await_count == 2


def test_download_callbacks_have_discord_signatures(tmp_path):
    bot = RawkumaBot(Settings(temp_dir=tmp_path / "temp", output_dir=tmp_path / "downloads"))
    assert list(inspect.signature(bot.download.callback).parameters) == ["interaction", "url"]
    assert list(inspect.signature(bot.download_naver.callback).parameters) == ["interaction", "url"]
    assert list(inspect.signature(bot.download_kakao.callback).parameters) == ["interaction", "url"]
    assert bot.download.binding is None
    assert bot.download_naver.binding is None
    assert bot.download_kakao.binding is None


def test_command_tree_has_direct_error_handler(tmp_path):
    bot = RawkumaBot(Settings(temp_dir=tmp_path / "temp", output_dir=tmp_path / "downloads"))
    assert bot.tree.on_error.__self__ is bot


def test_naver_info_embed_uses_full_cover_image(tmp_path):
    info = MangaInfo("Naver Demo", "https://comic.naver.com/webtoon/list?titleId=807777", source="Naver", cover_url="https://image.naver.com/cover.jpg")
    embed = info_embed(info, [])
    assert embed.image.url == "https://image.naver.com/cover.jpg"
    assert not embed.thumbnail.url


def test_kakao_info_embed_uses_full_cover_image(tmp_path):
    info = MangaInfo("Kakao Demo", "https://webtoon.kakao.com/content/demo/1776", source="Kakao", cover_url="https://cdn.kakao.example/cover.webp")
    embed = info_embed(info, [])
    assert embed.image.url == "https://cdn.kakao.example/cover.webp"
    assert not embed.thumbnail.url


def test_download_view_supports_twenty_chapter_selection(tmp_path):
    bot = RawkumaBot(Settings(temp_dir=tmp_path / "temp", output_dir=tmp_path / "downloads"))
    chapters = [Chapter(str(i), f"Chapter {i}", f"https://rawkuma.net/chapter-{i}") for i in range(1, 101)]
    view = ChapterBrowser(bot, MangaInfo("Demo", "https://rawkuma.net/manga/demo"), chapters, bot.downloader)
    select = view.children[0]
    assert view.page_count == 5
    assert len(select.options) == 20
    assert select.max_values == 20
