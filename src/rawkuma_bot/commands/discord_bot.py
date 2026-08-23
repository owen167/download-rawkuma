from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from rawkuma_bot.downloaders.models import Chapter, DownloadJob, JobStatus, MangaInfo
from rawkuma_bot.downloaders.rawkuma.downloader import RawkumaDownloader
from rawkuma_bot.downloaders.rawkuma.errors import RawkumaError
from rawkuma_bot.services.manager import DownloadManager

if TYPE_CHECKING:
    from rawkuma_bot.config.settings import Settings

log = logging.getLogger(__name__)
PAGE_SIZE = 20


def info_embed(info: MangaInfo, chapters: list[Chapter]) -> discord.Embed:
    embed = discord.Embed(title=f"📚 {info.title}", colour=discord.Colour.blurple(), url=info.url)
    if info.cover_url:
        embed.set_thumbnail(url=info.cover_url)
    embed.add_field(name="🌐 Source", value="Rawkuma", inline=True)
    embed.add_field(name="📖 Chapters", value=str(len(chapters)), inline=True)
    embed.add_field(name="📌 Status", value=info.status or "Unknown", inline=True)
    if info.description:
        embed.description = info.description[:1000]
    embed.set_footer(text="Select up to 20 chapters from the menu to start downloading")
    return embed


def job_embed(job: DownloadJob) -> discord.Embed:
    progress = job.progress
    filled = int(16 * progress.percent / 100) if progress.total else 0
    bar = "█" * filled + "░" * (16 - filled)
    if job.status == JobStatus.COMPLETED:
        title, colour = "✅ Download Completed", discord.Colour.green()
    elif job.status == JobStatus.FAILED:
        title, colour = "❌ Download Failed", discord.Colour.red()
    else:
        title, colour = "📥 Downloading Chapter", discord.Colour.blurple()
    embed = discord.Embed(title=title, colour=colour)
    embed.add_field(name="📚 Manga", value=job.manga.title, inline=True)
    embed.add_field(name="📖 Chapter", value=f"{job.chapter.number:g}", inline=True)
    embed.add_field(name="🖼️ Images", value=f"{progress.current} / {progress.total or '?'}", inline=True)
    embed.add_field(name="📊 Progress", value=f"{bar} {progress.percent:.0f}%", inline=False)
    embed.add_field(name="⏱️ Time", value=f"{progress.elapsed_seconds:.0f}s", inline=True)
    embed.add_field(name="⚡ Speed", value=f"{progress.speed_bps / 1024 / 1024:.2f} MB/s", inline=True)
    embed.add_field(name="Status", value=job.status.value, inline=True)
    if job.error:
        embed.add_field(name="Error", value=job.error, inline=False)
    return embed


class ChapterSelect(discord.ui.Select):
    def __init__(self, browser: "ChapterBrowser") -> None:
        self.browser = browser
        options = [
            discord.SelectOption(label=f"Chapter {chapter.number:g}"[:100], description=chapter.title[:100], value=str(index), emoji="📖")
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
        await self.browser.bot.enqueue(interaction, self.browser.info, chapters)


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
    def __init__(self, bot: "RawkumaBot", info: MangaInfo, chapters: list[Chapter]) -> None:
        super().__init__(timeout=900)
        self.bot, self.info = bot, info
        self.chapters = sorted(chapters, key=lambda chapter: chapter.number, reverse=True)
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
        self.manager = DownloadManager(settings, self.downloader, self.on_progress)
        self.job_messages: dict[str, discord.Message] = {}
        self.job_channels: dict[str, discord.abc.Messageable] = {}
        self._guild_cleanup_done = False

    async def setup_hook(self) -> None:
        log.info("Discord setup started; clearing old global commands")
        await self.manager.start()
        self.tree.clear_commands(guild=None)
        self.tree.add_command(self.download)
        await self.tree.sync()
        log.info("Global command sync completed; registered commands=download")

    async def on_ready(self) -> None:
        if self._guild_cleanup_done:
            return
        log.info("Discord ready; clearing old guild commands guild_count=%d", len(self.guilds))
        for guild in self.guilds:
            guild_object = discord.Object(id=guild.id)
            self.tree.clear_commands(guild=guild_object)
            self.tree.copy_global_to(guild=guild_object)
            await self.tree.sync(guild=guild_object)
            log.info("Guild command sync completed guild_id=%s registered=download", guild.id)
        self._guild_cleanup_done = True

    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        log.error("Slash command failed name=%s", getattr(interaction.command, "qualified_name", "unknown"), exc_info=(type(error), error, error.__traceback__))
        message = "❌ The command failed. Check the bot logs for details."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            log.exception("Could not send slash command error response")

    async def close(self) -> None:
        log.info("Shutting down Rawkuma Discord Bot")
        await self.manager.stop()
        await super().close()

    async def on_progress(self, job: DownloadJob) -> None:
        message = self.job_messages.get(job.job_id)
        if message and job.status != JobStatus.COMPLETED:
            try:
                await message.edit(embed=job_embed(job))
            except discord.HTTPException:
                log.debug("Could not update job %s", job.job_id)
        if job.status == JobStatus.COMPLETED and job.archive_path:
            log.info("Publishing completed job id=%s", job.job_id)
            archive = job.archive_path
            try:
                channel = self.job_channels.get(job.job_id)
                if archive.stat().st_size > self.settings.discord_max_file_mb * 1024 * 1024:
                    job.status = JobStatus.FAILED
                    job.error = "File Too Large"
                    if message:
                        await message.edit(embed=job_embed(job))
                elif channel:
                    await channel.send(file=discord.File(archive, filename=archive.name), embed=job_embed(job))
            except Exception:
                log.exception("Could not publish job %s", job.job_id)
            finally:
                archive.unlink(missing_ok=True)
                job.archive_path = None

    async def enqueue(self, interaction: discord.Interaction, info: MangaInfo, chapters: list[Chapter]) -> None:
        chapters = chapters[: self.settings.max_chapters_per_job]
        text = f"⏳ Added {len(chapters)} chapter(s) to the download queue."
        log.info("Enqueue request user=%s guild=%s chapters=%d", interaction.user.id, interaction.guild_id or 0, len(chapters))
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=True)
        else:
            await interaction.response.send_message(text, ephemeral=True)
        for chapter in chapters:
            job = await self.manager.submit(interaction.user.id, interaction.guild_id or 0, info, chapter)
            message = await interaction.followup.send(embed=job_embed(job), wait=True)
            self.job_messages[job.job_id] = message
            self.job_channels[job.job_id] = interaction.channel

    @app_commands.command(name="download", description="Browse a Rawkuma manga, select chapters, and download them")
    @app_commands.describe(url="A Rawkuma manga or chapter URL")
    async def download(self, interaction: discord.Interaction, url: str) -> None:
        log.info("Download command received user=%s guild=%s", interaction.user.id, interaction.guild_id or 0)
        await interaction.response.defer()
        try:
            if not self.downloader.supports(url):
                raise RawkumaError("❌ Invalid Rawkuma URL")
            info = await self.downloader.get_manga_info(url)
            if "/chapter" in url.lower():
                await self.enqueue(interaction, info, [await self.downloader.get_chapter(url)])
                return
            chapters = await self.downloader.get_chapters(url)
            await interaction.followup.send(embed=info_embed(info, chapters), view=ChapterBrowser(self, info, chapters))
        except RawkumaError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
        except Exception:
            log.exception("Rawkuma /download failed")
            await interaction.followup.send("❌ Source Unavailable", ephemeral=True)
