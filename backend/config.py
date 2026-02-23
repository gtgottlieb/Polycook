from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # Polling
    refresh_interval_s: int = Field(default=1, ge=1, le=60)
    stale_threshold_s: int = Field(default=30, ge=1, le=300)

    # Markets
    max_markets: int = Field(default=300, ge=10, le=2000)
    min_edge_pct: float = Field(default=0.001)  # 0.1% min edge to show

    # Paper trading
    starting_balance: float = Field(default=10_000.0)

    # DB
    database_url: str = "sqlite+aiosqlite:///./data/polycook.db"

    # API
    gamma_base_url: str = "https://gamma-api.polymarket.com"
    clob_base_url: str = "https://clob.polymarket.com"
    clob_books_batch_size: int = 400  # tokens per /books POST

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
