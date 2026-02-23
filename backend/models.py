"""
SQLAlchemy ORM models and Pydantic schemas for Polycook.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, field_validator
from sqlalchemy import String, Float, Text, DateTime, Integer
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
    is_stale: bool = False


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
    stale_threshold_s: int
    max_markets: int
    min_edge_pct: float
    starting_balance: float


class SettingsUpdate(BaseModel):
    refresh_interval_s: Optional[int] = None
    stale_threshold_s: Optional[int] = None
    max_markets: Optional[int] = None
    min_edge_pct: Optional[float] = None
