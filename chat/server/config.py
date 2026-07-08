"""Server configuration loaded from environment."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

from chat.shared.utils import parse_size


class ServerConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    username: str = "server"
    password: str
    database_path: str = "chat.db"
    upload_dir: str = "chat/server/uploads"
    max_file_size: str = "500MB"
    log_level: str = "INFO"

    @property
    def max_file_size_bytes(self) -> int:
        return parse_size(self.max_file_size)


config = ServerConfig()  # type: ignore[call-arg]
