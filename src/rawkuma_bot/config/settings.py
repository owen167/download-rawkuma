from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    discord_token: str = Field(default="", validation_alias="DISCORD_TOKEN")
    discord_guild_id: int | None = Field(default=None, validation_alias="DISCORD_GUILD_ID")
    gofile_token: str = Field(default="", validation_alias="GOFILE_TOKEN")
    database_url: str = Field(default="sqlite+aiosqlite:///./data/rawkuma_bot.db", validation_alias="DATABASE_URL")
    temp_dir: Path = Field(default=Path("./temp"), validation_alias="TEMP_DIR")
    output_dir: Path = Field(default=Path("./downloads"), validation_alias="OUTPUT_DIR")
    log_dir: Path = Field(default=Path("./logs"), validation_alias="LOG_DIR")
    max_concurrent_downloads: int = Field(default=2, validation_alias="MAX_CONCURRENT_DOWNLOADS", ge=1, le=10)
    max_concurrent_pages: int = Field(default=6, validation_alias="MAX_CONCURRENT_PAGES", ge=1, le=20)
    max_chapters_per_job: int = Field(default=20, validation_alias="MAX_CHAPTERS_PER_JOB", ge=1, le=20)
    retry_attempts: int = Field(default=3, validation_alias="RETRY_ATTEMPTS", ge=1, le=5)
    retry_backoff_seconds: float = Field(default=1.0, validation_alias="RETRY_BACKOFF_SECONDS", gt=0)
    request_timeout_seconds: float = Field(default=30.0, validation_alias="REQUEST_TIMEOUT_SECONDS", gt=0)
    gofile_upload_timeout_seconds: float = Field(default=300.0, validation_alias="GOFILE_UPLOAD_TIMEOUT_SECONDS", gt=0)
    discord_max_file_mb: int = Field(default=25, validation_alias="DISCORD_MAX_FILE_MB", gt=0)
    user_agent: str = Field(default="RawkumaDiscordBot/1.0 (+https://rawkuma.net/)", validation_alias="USER_AGENT")
    kakao_browser_timeout_seconds: float = Field(default=45.0, validation_alias="KAKAO_BROWSER_TIMEOUT_SECONDS", gt=0)
    kakao_browser_executable: str = Field(default="", validation_alias="KAKAO_BROWSER_EXECUTABLE")

    def prepare_directories(self) -> None:
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        if self.database_url.startswith("sqlite"):
            db_part = self.database_url.split("///", 1)[-1]
            if db_part and db_part != ":memory:":
                db_path = Path(db_part)
                if not db_path.is_absolute():
                    db_path = Path.cwd() / db_path
                db_path.parent.mkdir(parents=True, exist_ok=True)


settings = Settings()
