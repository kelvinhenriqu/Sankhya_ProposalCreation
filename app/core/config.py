from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    sankhya_base_url: str = "https://api.sankhya.com.br"
    sankhya_client_id: str = Field(min_length=1)
    sankhya_client_secret: str = Field(min_length=1)
    sankhya_x_token: str = Field(min_length=1)

    sankhya_connect_timeout: float = Field(default=10.0, gt=0)
    sankhya_read_timeout: float = Field(default=60.0, gt=0)
    sankhya_write_timeout: float = Field(default=30.0, gt=0)
    sankhya_pool_timeout: float = Field(default=10.0, gt=0)
    sankhya_max_retries: int = Field(default=3, ge=0, le=10)
    sankhya_retry_base_delay: float = Field(default=0.5, gt=0, le=30)

    log_level: str = "INFO"
    templates_dir: Path = Path("Templates")
    pdf_converter: Literal["word", "libreoffice"] = "libreoffice"
    libreoffice_executable: Path | None = None
    pdf_conversion_timeout: int = Field(default=120, ge=10, le=600)

    @field_validator("sankhya_base_url")
    @classmethod
    def normalize_base_url(cls, value: str) -> str:
        return value.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()
