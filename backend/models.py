"""
SQLAlchemy ORM models and Pydantic schemas for Polycook.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, field_validator
from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


# ─── ORM Models ────────────────────────────────────────────────────────────────

class PaperTrade(Base):
    __tablename__ = "paper_trades"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    opportunity_snapshot: Mapped[str] = mapped_column(Text)  # JSON snapshot of opportunity at entry
    legs_json: Mapped[str] = mapped_column(Text)             # JSON list of TradeLeg dicts
    entry_cost: Mapped[float] = mapped_column(Float)
    locked_in_payoff: Mapped[float] = mapped_column(Float)   # size × 1.0
    size: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String, default="open")  # open | closed
    realized_pnl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class Portfolio(Base):
    __tablename__ = "portfolio"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    balance: Mapped[float] = mapped_column(Float)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)


class AppSetting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text)  # JSON-encoded


class OrderSizeBaseline(Base):
    __tablename__ = "order_size_baselines"

    token_id: Mapped[str] = mapped_column(String, primary_key=True)
    side: Mapped[str] = mapped_column(String, primary_key=True)
    market_id: Mapped[str] = mapped_column(String, index=True)
    market_title: Mapped[str] = mapped_column(Text)
    market_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    venue: Mapped[str] = mapped_column(String, default="polymarket")
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    ema_size: Mapped[float] = mapped_column(Float, default=0.0)
    ema_abs_dev: Mapped[float] = mapped_column(Float, default=0.0)
    last_observed_size: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_observed_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class OrderAnomalyEvent(Base):
    __tablename__ = "order_anomaly_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    token_id: Mapped[str] = mapped_column(String, index=True)
    market_id: Mapped[str] = mapped_column(String, index=True)
    market_title: Mapped[str] = mapped_column(Text)
    market_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    side: Mapped[str] = mapped_column(String)
    price: Mapped[float] = mapped_column(Float)
    observed_size: Mapped[float] = mapped_column(Float)
    baseline_size: Mapped[float] = mapped_column(Float)
    size_multiple: Mapped[float] = mapped_column(Float)
    robust_z: Mapped[float] = mapped_column(Float)
    book_dominance: Mapped[float] = mapped_column(Float)
    severity: Mapped[str] = mapped_column(String)
    outcome_label: Mapped[str] = mapped_column(String)
    summary: Mapped[str] = mapped_column(Text)
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)


# ─── In-Memory Data Structures ────────────────────────────────────────────────

class NormalizedContract(BaseModel):
    venue: str = "polymarket"
    market_id: str            # conditionId
    outcome_id: str           # tokenId
    label: str                # YES / NO / outcome name
    bid: Optional[float] = None
    ask: Optional[float] = None
    bid_size: Optional[float] = None
    ask_size: Optional[float] = None
    close_time: Optional[datetime] = None
    updated_at: datetime
    market_title: str
    market_url: Optional[str] = None
    is_stale: bool = False
    event_id: Optional[str] = None    # negRisk event ID (set for event-group YES legs)
    event_title: Optional[str] = None  # e.g. "2026 FIFA World Cup Winner"


class TradeLeg(BaseModel):
    outcome_id: str    # tokenId
    market_id: str
    label: str
    venue: str = "polymarket"
    entry_price: float
    current_bid: Optional[float] = None
    current_ask: Optional[float] = None
    size: float


class OpportunityLeg(BaseModel):
    outcome_id: str
    market_id: str
    market_title: str
    market_url: Optional[str] = None
    label: str
    venue: str = "polymarket"
    ask: float
    ask_size: float
    bid: float


class Opportunity(BaseModel):
    id: str
    type: str = "intra"
    event_title: str
    venues: list[str] = ["polymarket"]
    legs: list[OpportunityLeg]
    edge_pct: float
    max_size: float
    close_time: Optional[datetime]
    updated_at: datetime

    @property
    def time_to_close_s(self) -> Optional[float]:
        if self.close_time is None:
            return None
        delta = (self.close_time - datetime.utcnow()).total_seconds()
        return max(0.0, delta)


class OrderAnomaly(BaseModel):
    id: str
    market_id: str
    token_id: str
    market_title: str
    market_url: Optional[str] = None
    outcome_label: str
    side: Literal["bid", "ask"]
    price: float
    observed_size: float
    baseline_size: float
    size_multiple: float
    robust_z: float
    book_dominance: float
    severity: Literal["medium", "high", "critical"]
    summary: str
    detected_at: datetime
    updated_at: datetime


class PipelineStatus(BaseModel):
    enabled: bool
    running: bool
    last_update: Optional[datetime] = None
    last_duration_ms: Optional[float] = None
    item_count: int = 0
    error: Optional[str] = None


class PipelineStatusMap(BaseModel):
    arbitrage: PipelineStatus
    aberrant_orders: PipelineStatus


# ─── Pydantic Schemas (API I/O) ────────────────────────────────────────────────

class OpportunityOut(BaseModel):
    id: str
    type: str
    event_title: str
    venues: list[str]
    legs: list[OpportunityLeg]
    edge_pct: float
    max_size: float
    close_time: Optional[datetime]
    time_to_close_s: Optional[float]
    updated_at: datetime

    @classmethod
    def from_opportunity(cls, opp: Opportunity) -> "OpportunityOut":
        return cls(
            id=opp.id,
            type=opp.type,
            event_title=opp.event_title,
            venues=opp.venues,
            legs=opp.legs,
            edge_pct=opp.edge_pct,
            max_size=opp.max_size,
            close_time=opp.close_time,
            time_to_close_s=opp.time_to_close_s,
            updated_at=opp.updated_at,
        )


class OrderAnomalyOut(BaseModel):
    id: str
    market_id: str
    token_id: str
    market_title: str
    market_url: Optional[str] = None
    outcome_label: str
    side: Literal["bid", "ask"]
    price: float
    observed_size: float
    baseline_size: float
    size_multiple: float
    robust_z: float
    book_dominance: float
    severity: Literal["medium", "high", "critical"]
    summary: str
    detected_at: datetime
    updated_at: datetime

    @classmethod
    def from_anomaly(cls, anomaly: OrderAnomaly) -> "OrderAnomalyOut":
        return cls(**anomaly.model_dump())

    @classmethod
    def from_event(cls, event: OrderAnomalyEvent) -> "OrderAnomalyOut":
        return cls(
            id=event.id,
            market_id=event.market_id,
            token_id=event.token_id,
            market_title=event.market_title,
            market_url=event.market_url,
            outcome_label=event.outcome_label,
            side=event.side,  # type: ignore[arg-type]
            price=event.price,
            observed_size=event.observed_size,
            baseline_size=event.baseline_size,
            size_multiple=event.size_multiple,
            robust_z=event.robust_z,
            book_dominance=event.book_dominance,
            severity=event.severity,  # type: ignore[arg-type]
            summary=event.summary,
            detected_at=event.detected_at,
            updated_at=event.detected_at,
        )


class TradeCreate(BaseModel):
    opportunity_id: str
    size: float

    @field_validator("size")
    @classmethod
    def size_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("size must be positive")
        return v


class TradeOut(BaseModel):
    id: str
    opportunity_snapshot: dict
    legs: list[TradeLeg]
    entry_cost: float
    locked_in_payoff: float
    size: float
    status: str
    unrealized_pnl: Optional[float] = None
    realized_pnl: Optional[float] = None
    created_at: datetime
    closed_at: Optional[datetime]

    @classmethod
    def from_db(cls, trade: PaperTrade, unrealized_pnl: Optional[float] = None) -> "TradeOut":
        legs = [TradeLeg(**l) for l in json.loads(trade.legs_json)]
        snapshot = json.loads(trade.opportunity_snapshot)
        return cls(
            id=trade.id,
            opportunity_snapshot=snapshot,
            legs=legs,
            entry_cost=trade.entry_cost,
            locked_in_payoff=trade.locked_in_payoff,
            size=trade.size,
            status=trade.status,
            unrealized_pnl=unrealized_pnl,
            realized_pnl=trade.realized_pnl,
            created_at=trade.created_at,
            closed_at=trade.closed_at,
        )


class PortfolioOut(BaseModel):
    balance: float
    realized_pnl: float
    unrealized_pnl: float
    total_pnl: float
    open_trade_count: int


class VenueStatus(BaseModel):
    connected: bool
    last_update: Optional[datetime]
    stale: bool
    market_count: int
    error: Optional[str] = None


class SettingsOut(BaseModel):
    refresh_interval_s: int
    arb_refresh_interval_s: int
    anomaly_refresh_interval_s: int
    stale_threshold_s: int
    max_markets: int
    anomaly_max_markets: int
    min_edge_pct: float
    min_max_size: float
    enable_arb_pipeline: bool
    enable_anomaly_pipeline: bool
    anomaly_enable_sweep_detection: bool
    anomaly_enable_wall_detection: bool
    anomaly_candidate_min_size: float
    anomaly_candidate_multiplier: float
    anomaly_candidate_abs_excess: float
    anomaly_min_sweep_price_move: float
    anomaly_min_sweep_fill_size: float
    anomaly_min_sweep_depth_ratio: float
    anomaly_max_spread: float
    anomaly_min_samples: int
    anomaly_bootstrap_min_samples: int
    anomaly_alpha: float
    anomaly_alert_size_multiple: float
    anomaly_alert_robust_z: float
    anomaly_absolute_min_wall_size: float
    anomaly_min_price: float
    anomaly_max_price: float
    anomaly_cooldown_s: int
    anomaly_max_candidates_per_cycle: int
    starting_balance: float


class SettingsUpdate(BaseModel):
    refresh_interval_s: Optional[int] = None
    arb_refresh_interval_s: Optional[int] = None
    anomaly_refresh_interval_s: Optional[int] = None
    stale_threshold_s: Optional[int] = None
    max_markets: Optional[int] = None
    anomaly_max_markets: Optional[int] = None
    min_edge_pct: Optional[float] = None
    min_max_size: Optional[float] = None
    enable_arb_pipeline: Optional[bool] = None
    enable_anomaly_pipeline: Optional[bool] = None
    anomaly_enable_sweep_detection: Optional[bool] = None
    anomaly_enable_wall_detection: Optional[bool] = None
    anomaly_candidate_min_size: Optional[float] = None
    anomaly_candidate_multiplier: Optional[float] = None
    anomaly_candidate_abs_excess: Optional[float] = None
    anomaly_min_sweep_price_move: Optional[float] = None
    anomaly_min_sweep_fill_size: Optional[float] = None
    anomaly_min_sweep_depth_ratio: Optional[float] = None
    anomaly_max_spread: Optional[float] = None
    anomaly_min_samples: Optional[int] = None
    anomaly_bootstrap_min_samples: Optional[int] = None
    anomaly_alpha: Optional[float] = None
    anomaly_alert_size_multiple: Optional[float] = None
    anomaly_alert_robust_z: Optional[float] = None
    anomaly_absolute_min_wall_size: Optional[float] = None
    anomaly_min_price: Optional[float] = None
    anomaly_max_price: Optional[float] = None
    anomaly_cooldown_s: Optional[int] = None
    anomaly_max_candidates_per_cycle: Optional[int] = None
