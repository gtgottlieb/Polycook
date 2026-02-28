from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # Polling
    refresh_interval_s: int = Field(default=1, ge=1, le=60)
    arb_refresh_interval_s: int = Field(default=1, ge=1, le=60)
    anomaly_refresh_interval_s: int = Field(default=2, ge=1, le=60)
    metadata_refresh_interval_s: int = Field(default=60, ge=5, le=3600)
    stale_threshold_s: int = Field(default=30, ge=1, le=300)

    # Markets
    max_markets: int = Field(default=100, ge=10, le=10000)
    min_edge_pct: float = Field(default=0.001)  # 0.1% min edge to show
    min_max_size: float = Field(default=1.0, ge=0.0)
    anomaly_max_markets: int = Field(default=1000, ge=10, le=4000)

    # Pipeline toggles
    enable_arb_pipeline: bool = False
    enable_anomaly_pipeline: bool = True

    # Aberrant order detector
    anomaly_enable_sweep_detection: bool = True
    anomaly_enable_wall_detection: bool = False
    anomaly_candidate_min_size: float = Field(default=75.0, ge=0.0)
    anomaly_candidate_multiplier: float = Field(default=2.5, ge=1.0)
    anomaly_candidate_abs_excess: float = Field(default=200.0, ge=0.0)
    anomaly_min_sweep_price_move: float = Field(default=0.015, ge=0.0, le=1.0)
    anomaly_min_sweep_fill_size: float = Field(default=100.0, ge=0.0)
    anomaly_min_sweep_depth_ratio: float = Field(default=0.20, ge=0.0, le=1.0)
    anomaly_max_spread: float = Field(default=0.08, ge=0.0, le=1.0)
    anomaly_min_samples: int = Field(default=6, ge=1, le=10_000)
    anomaly_bootstrap_min_samples: int = Field(default=5, ge=1, le=10_000)
    anomaly_alpha: float = Field(default=0.10, gt=0.0, le=1.0)
    anomaly_alert_size_multiple: float = Field(default=2.0, ge=1.0)
    anomaly_alert_robust_z: float = Field(default=1.5, ge=0.0)
    anomaly_absolute_min_wall_size: float = Field(default=1_500.0, ge=0.0)
    anomaly_min_price: float = Field(default=0.05, ge=0.0, le=1.0)
    anomaly_max_price: float = Field(default=0.95, ge=0.0, le=1.0)
    anomaly_cooldown_s: int = Field(default=120, ge=0, le=86_400)
    anomaly_max_candidates_per_cycle: int = Field(default=100, ge=1, le=1000)

    # Paper trading
    starting_balance: float = Field(default=10_000.0)

    # DB
    database_url: str = "sqlite+aiosqlite:///./data/polycook.db"

    # API
    gamma_base_url: str = "https://gamma-api.polymarket.com"
    clob_base_url: str = "https://clob.polymarket.com"
    kalshi_base_url: str = "https://api.elections.kalshi.com/trade-api/v2"
    clob_books_batch_size: int = 400  # tokens per /books POST

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
