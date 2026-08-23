from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from rawkuma_bot.downloaders.models import Chapter, DownloadJob, JobStatus, MangaInfo
from rawkuma_bot.downloaders.rawkuma.downloader import RawkumaDownloader
from rawkuma_bot.downloaders.rawkuma.errors import RawkumaError
from rawkuma_bot.downloaders.naver.downloader import NaverDownloader
from rawkuma_bot.downloaders.naver.errors import NaverError
from rawkuma_bot.downloaders.kakao.downloader import KakaoDownloader
from rawkuma_bot.downloaders.kakao.errors import KakaoError
from rawkuma_bot.services.manager import ChapterDownloader, DownloadManager
from rawkuma_bot.storage.gofile import GoFileStorage

if TYPE_CHECKING:
    from rawkuma_bot.config.settings import Settings

log = logging.getLogger(__name__)
PAGE_SIZE = 20


def info_embed(info: MangaInfo, chapters: list[Chapter]) -> discord.Embed:
    embed = discord.Embed(title=f"📚 {info.title}", colour=discord.Colour.blurple(), url=info.url)
    if info.cover_url:
        if info.source in {"Naver", "Kakao"}:
            embed.set_image(url=info.cover_url)
        else:
            embed.set_thumbnail(url=info.cover_url)
    embed.add_field(name="🌐 Source", value=info.source, inline=True)
    embed.add_field(name="📖 Chapters", value=str(len(chapters)), inline=True)
    embed.add_field(name="📌 Status", value=info.status or "Unknown", inline=True)
    if info.description:
        embed.description = info.description[:1000]
    embed.set_footer(text="Select up to 20 chapters from the menu to start downloading")
    return embed


@app_commands.command(name="download", description="Browse a Rawkuma manga, select chapters, and download them")
@app_commands.describe(url="A Rawkuma manga or chapter URL")
async def download_command(interaction: discord.Interaction, url: str) -> None:
    handler = getattr(interaction.client, "handle_download", None)
    if handler is None:
        raise RuntimeError("Download command is not attached to the Rawkuma bot")
    await handler(interaction, url)


@app_commands.command(name="download-kakao", description="Browse a Kakao Webtoon, select chapters, and download them")
@app_commands.describe(url="A Kakao Webtoon content URL")
async def download_kakao_command(interaction: discord.Interaction, url: str) -> None:
    handler = getattr(interaction.client, "handle_download_kakao", None)
    if handler is None:
        raise RuntimeError("Kakao download command is not attached to the bot")
    await handler(interaction, url)


@app_commands.command(name="download-naver", description="Browse a Naver Webtoon, select chapters, and download them")
@app_commands.describe(url="A Naver Webtoon manga or chapter URL")
async def download_naver_command(interaction: discord.Interaction, url: str) -> None:
    handler = getattr(interaction.client, "handle_download_naver", None)
    if handler is None:
        raise RuntimeError("Naver download command is not attached to the bot")
    await handler(interaction, url)


def status_embed(title: str, description: str, colour: discord.Colour) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, colour=colour)
    embed.set_footer(text="Manga Download Bot")
    return embed


def job_embed(job: DownloadJob) -> discord.Embed:
    progress = job.progress
    filled = int(16 * progress.percent / 100) if progress.total else 0
    bar = "█" * filled + "░" * (16 - filled)
    if job.status == JobStatus.COMPLETED:
        title, colour = "✅ Download Completed", discord.Colour.green()
    elif job.status == JobStatus.FAILED:
        title, colour = "❌ Download Failed", discord.Colour.red()
    elif job.status == JobStatus.QUEUED:
        title, colour = "⏳ Queued for Download", discord.Colour.gold()
    elif job.status == JobStatus.UPLOADING:
        title, colour = "☁️ Uploading to GoFile", discord.Colour.orange()
    else:
        title, colour = "📥 Downloading Chapter", discord.Colour.blurple()
    embed = discord.Embed(title=title, colour=colour)
    embed.add_field(name="📚 Manga", value=job.manga.title, inline=True)
    embed.add_field(name="📖 Chapter", value=job.chapter.number, inline=True)
    embed.add_field(name="🖼️ Images", value=f"{progress.current} / {progress.total or '?'}", inline=True)
    embed.add_field(name="📊 Progress", value=f"{bar} {progress.percent:.0f}%", inline=False)
    embed.add_field(name="⏱️ Time", value=f"{progress.elapsed_seconds:.0f}s", inline=True)
    embed.add_field(name="⚡ Speed", value=f"{progress.speed_bps / 1024 / 1024:.2f} MB/s", inline=True)
    embed.add_field(name="Status", value=job.status.value, inline=True)
    if job.error:
        embed.add_field(name="Error", value=job.error, inline=False)
    return embed


def chapter_ready_embed(job: DownloadJob) -> discord.Embed:
    size_mb = job.archive_size_bytes / 1024 / 1024
    embed = discord.Embed(
        title="✅ Chapter Ready",
        description=f"[Download {job.chapter.title} on GoFile]({job.upload_url})",
        colour=discord.Colour.green(),
    )
    embed.add_field(name="📖 Chapter", value=job.chapter.title, inline=True)
    embed.add_field(name="🖼️ Images", value=str(job.image_count), inline=True)
    embed.add_field(name="📦 Size", value=f"{size_mb:.2f} MB", inline=True)
    embed.add_field(name="🔗 Download Link", value=f"[Open on GoFile]({job.upload_url})", inline=False)
    embed.set_footer(text="Manga Download Bot")
    return embed


class ChapterSelect(discord.ui.Select):
    def __init__(self, browser: "ChapterBrowser") -> None:
        self.browser = browser
        options = [
            discord.SelectOption(label=f"Chapter {chapter.number}"[:100], description=chapter.title[:100], value=str(index), emoji="📖")
            for index, chapter in enumerate(browser.page_chapters)
        ]
        super().__init__(
            placeholder=f"Select up to 20 chapters — Page {browser.page + 1}/{browser.page_count}",
            options=options,
            min_values=1,
            max_values=min(PAGE_SIZE, len(options)),
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        chapters = [self.browser.page_chapters[int(value)] for value in self.values]
        await self.browser.bot.enqueue(interaction, self.browser.info, chapters, self.browser.downloader)


class NewerButton(discord.ui.Button):
    def __init__(self, browser: "ChapterBrowser") -> None:
        super().__init__(label="Newer Chapters", style=discord.ButtonStyle.secondary, disabled=browser.page == 0)
        self.browser = browser

    async def callback(self, interaction: discord.Interaction) -> None:
        self.browser.page -= 1
        await self.browser.refresh(interaction)


class OlderButton(discord.ui.Button):
    def __init__(self, browser: "ChapterBrowser") -> None:
        super().__init__(label="Older Chapters", style=discord.ButtonStyle.secondary, disabled=browser.page >= browser.page_count - 1)
        self.browser = browser

    async def callback(self, interaction: discord.Interaction) -> None:
        self.browser.page += 1
        await self.browser.refresh(interaction)


class ChapterBrowser(discord.ui.View):
    def __init__(
        self,
        bot: "RawkumaBot",
        info: MangaInfo,
        chapters: list[Chapter],
        downloader: ChapterDownloader,
    ) -> None:
        super().__init__(timeout=900)
        self.bot, self.info, self.downloader = bot, info, downloader
        self.chapters = sorted(chapters, key=lambda chapter: chapter.sort_key, reverse=True)
        self.page = 0
        self.rebuild()

    @property
    def page_count(self) -> int:
        return max(1, (len(self.chapters) + PAGE_SIZE - 1) // PAGE_SIZE)

    @property
    def page_chapters(self) -> list[Chapter]:
        start = self.page * PAGE_SIZE
        return self.chapters[start:start + PAGE_SIZE]

    def rebuild(self) -> None:
        self.clear_items()
        self.add_item(ChapterSelect(self))
        self.add_item(NewerButton(self))
        self.add_item(OlderButton(self))

    async def refresh(self, interaction: discord.Interaction) -> None:
        self.rebuild()
        await interaction.response.edit_message(embed=info_embed(self.info, self.chapters), view=self)


class RawkumaBot(commands.Bot):
    def __init__(self, settings: "Settings") -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        super().__init__(command_prefix="!", intents=intents)
        self.settings = settings
        self.downloader = RawkumaDownloader(settings)
        self.naver_downloader = NaverDownloader(settings)
        self.kakao_downloader = KakaoDownloader(settings)
        self.manager = DownloadManager(settings, self.downloader, self.on_progress, storage=GoFileStorage(settings))
        self.job_messages: dict[str, discord.Message] = {}
        self.job_channels: dict[str, discord.abc.Messageable] = {}
        self._command_cleanup_done = False
        self.download = download_command
        self.download_naver = download_naver_command
        self.download_kakao = download_kakao_command
        # CommandTree does not automatically use a Bot method named on_app_command_error.
        # Bind the handler explicitly so signature/sync errors receive an English response.
        self.tree.on_error = self.on_app_command_error

    def _configured_guild(self) -> discord.Object | None:
        if self.settings.discord_guild_id is None:
            return None
        return discord.Object(id=self.settings.discord_guild_id)

    async def setup_hook(self) -> None:
        await self.manager.start()
        configured_guild = self._configured_guild()
        if configured_guild is None:
            # Global-only mode: clear any stale global commands, then register both supported commands globally.
            log.info("Discord setup started; using global command scope only")
            self.tree.clear_commands(guild=None)
            self.tree.add_command(self.download)
            self.tree.add_command(self.download_naver)
            self.tree.add_command(self.download_kakao)
            await self.tree.sync()
            log.info("Global command sync completed; registered commands=download,download-naver,download-kakao")
            return

        # Guild-only mode: clear global commands first so Discord cannot show a duplicate.
        log.info("Discord setup started; using guild-only command scope guild_id=%s", configured_guild.id)
        self.tree.clear_commands(guild=None)
        await self.tree.sync()
        self.tree.clear_commands(guild=configured_guild)
        self.tree.add_command(self.download, guild=configured_guild)
        self.tree.add_command(self.download_naver, guild=configured_guild)
        self.tree.add_command(self.download_kakao, guild=configured_guild)
        await self.tree.sync(guild=configured_guild)
        log.info("Guild command sync completed guild_id=%s registered=download,download-naver,download-kakao", configured_guild.id)

    async def on_ready(self) -> None:
        if self._command_cleanup_done:
            return
        configured_guild_id = self.settings.discord_guild_id
        log.info(
            "Discord ready; enforcing one command scope bot_user_id=%s guild_count=%d configured_guild_id=%s",
            self.user.id if self.user else "unknown",
            len(self.guilds),
            configured_guild_id,
        )
        for guild in self.guilds:
            guild_object = discord.Object(id=guild.id)
            self.tree.clear_commands(guild=guild_object)
            if configured_guild_id is not None and guild.id == configured_guild_id:
                self.tree.add_command(self.download, guild=guild_object)
                self.tree.add_command(self.download_naver, guild=guild_object)
                self.tree.add_command(self.download_kakao, guild=guild_object)
            await self.tree.sync(guild=guild_object)
            registered = "download,download-naver,download-kakao" if configured_guild_id is not None and guild.id == configured_guild_id else "none"
            log.info("Guild command sync completed guild_id=%s registered=%s", guild.id, registered)
        self._command_cleanup_done = True

    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        log.error("Slash command failed name=%s", getattr(interaction.command, "qualified_name", "unknown"), exc_info=(type(error), error, error.__traceback__))
        if isinstance(error, app_commands.CommandSignatureMismatch):
            embed = status_embed(
                "Command Registration Error",
                "This command registration is outdated. Please restart the bot with the latest version.",
                discord.Colour.red(),
            )
        else:
            embed = status_embed(
                "Command Error",
                "The command failed. Please check the bot logs for details.",
                discord.Colour.red(),
            )
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
        except discord.HTTPException:
            log.exception("Could not send slash command error response")

    async def close(self) -> None:
        log.info("Shutting down Rawkuma Discord Bot")
        await self.manager.stop()
        await self.kakao_downloader.close()
        await super().close()

    async def on_progress(self, job: DownloadJob) -> None:
        message = self.job_messages.get(job.job_id)
        if job.status != JobStatus.COMPLETED:
            if message:
                try:
                    await message.edit(embed=job_embed(job))
                except discord.HTTPException:
                    log.debug("Could not update job %s", job.job_id)
            return

        if not job.upload_url:
            job.status = JobStatus.FAILED
            job.error = "GoFile did not return a share link"
            if message:
                await message.edit(embed=job_embed(job))
            return

        channel = self.job_channels.get(job.job_id)
        if not channel:
            log.error("Could not publish GoFile link; channel missing job_id=%s", job.job_id)
            return

        log.info("Publishing GoFile link id=%s chapter=%s", job.job_id, job.chapter.number)
        await channel.send(embed=chapter_ready_embed(job))
        if message:
            try:
                await message.delete()
            except discord.HTTPException:
                log.debug("Could not delete progress Embed job=%s", job.job_id)
        self.job_messages.pop(job.job_id, None)
        self.job_channels.pop(job.job_id, None)
        self.manager.forget_job_record(job.job_id)
        log.info("Progress Embed deleted and job record forgotten id=%s", job.job_id)

    async def enqueue(
        self,
        interaction: discord.Interaction,
        info: MangaInfo,
        chapters: list[Chapter],
        downloader: ChapterDownloader,
    ) -> None:
        chapters = chapters[: self.settings.max_chapters_per_job]
        queued_embed = status_embed(
            "Added to Download Queue",
            f"{len(chapters)} chapter(s) have been added to the download queue.",
            discord.Colour.gold(),
        )
        log.info("Enqueue request user=%s guild=%s chapters=%d", interaction.user.id, interaction.guild_id or 0, len(chapters))
        if interaction.response.is_done():
            await interaction.followup.send(embed=queued_embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=queued_embed, ephemeral=True)
        for position, chapter in enumerate(chapters, start=1):
            job = await self.manager.submit(interaction.user.id, interaction.guild_id or 0, info, chapter, downloader=downloader)
            message = await interaction.followup.send(embed=job_embed(job), wait=True)
            self.job_messages[job.job_id] = message
            self.job_channels[job.job_id] = interaction.channel
            # The worker can start between submit() and message creation; refresh now
            # so the user sees the current status and image total immediately.
            await self.on_progress(job)
            log.info(
                "Sequential chapter started position=%d total=%d chapter=%s",
                position,
                len(chapters),
                chapter.number,
            )
            await self.manager.wait_for_completion(job)
            log.info(
                "Sequential chapter finished position=%d total=%d chapter=%s status=%s",
                position,
                len(chapters),
                chapter.number,
                job.status,
            )

    async def handle_download(self, interaction: discord.Interaction, url: str) -> None:
        log.info("Rawkuma download command received user=%s guild=%s", interaction.user.id, interaction.guild_id or 0)
        await interaction.response.defer()
        try:
            if not self.downloader.supports(url):
                raise RawkumaError("Invalid Rawkuma URL")
            info = await self.downloader.get_manga_info(url)
            if "/chapter" in url.lower():
                await self.enqueue(interaction, info, [await self.downloader.get_chapter(url)], self.downloader)
                return
            chapters = await self.downloader.get_chapters(url)
            await interaction.followup.send(
                embed=info_embed(info, chapters),
                view=ChapterBrowser(self, info, chapters, self.downloader),
            )
        except RawkumaError as exc:
            await interaction.followup.send(
                embed=status_embed("Download Request Error", str(exc), discord.Colour.red()),
                ephemeral=True,
            )
        except Exception:
            log.exception("Rawkuma /download failed")
            await interaction.followup.send(
                embed=status_embed(
                    "Source Unavailable",
                    "Rawkuma could not be reached or the page could not be read. Please try again later.",
                    discord.Colour.red(),
                ),
                ephemeral=True,
            )

    async def handle_download_naver(self, interaction: discord.Interaction, url: str) -> None:
        log.info("Naver download command received user=%s guild=%s", interaction.user.id, interaction.guild_id or 0)
        await interaction.response.defer()
        try:
            if not self.naver_downloader.supports(url):
                raise NaverError("Invalid Naver Webtoon URL")
            info = await self.naver_downloader.get_manga_info(url)
            if self.naver_downloader.is_chapter_url(url):
                await self.enqueue(interaction, info, [await self.naver_downloader.get_chapter(url)], self.naver_downloader)
                return
            if not self.naver_downloader.is_manga_url(url):
                raise NaverError("Use a Naver Webtoon list or chapter URL")
            chapters = await self.naver_downloader.get_chapters(url)
            await interaction.followup.send(
                embed=info_embed(info, chapters),
                view=ChapterBrowser(self, info, chapters, self.naver_downloader),
            )
        except NaverError as exc:
            await interaction.followup.send(
                embed=status_embed("Download Request Error", str(exc), discord.Colour.red()),
                ephemeral=True,
            )
        except Exception:
            log.exception("Naver /download-naver failed")
            await interaction.followup.send(
                embed=status_embed(
                    "Source Unavailable",
                    "Naver Webtoon could not be reached or the page could not be read. Please try again later.",
                    discord.Colour.red(),
                ),
                ephemeral=True,
            )


    async def handle_download_kakao(self, interaction: discord.Interaction, url: str) -> None:
        log.info("Kakao download command received user=%s guild=%s", interaction.user.id, interaction.guild_id or 0)
        await interaction.response.defer()
        try:
            if not self.kakao_downloader.supports(url) or not self.kakao_downloader.is_manga_url(url):
                raise KakaoError("Use a Kakao Webtoon content URL")
            info = await self.kakao_downloader.get_manga_info(url)
            chapters = await self.kakao_downloader.get_chapters(url)
            await interaction.followup.send(
                embed=info_embed(info, chapters),
                view=ChapterBrowser(self, info, chapters, self.kakao_downloader),
            )
        except KakaoError as exc:
            await interaction.followup.send(
                embed=status_embed("Download Request Error", str(exc), discord.Colour.red()),
                ephemeral=True,
            )
        except Exception:
            log.exception("Kakao /download-kakao failed")
            await interaction.followup.send(
                embed=status_embed(
                    "Source Unavailable",
                    "Kakao could not be reached or did not expose readable chapters. Please try again later.",
                    discord.Colour.red(),
                ),
                ephemeral=True,
            )
