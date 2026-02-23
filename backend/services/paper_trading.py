"""
Paper trading engine.

Handles trade creation, mark-to-market P&L, and trade closing.
All monetary values are in USD.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models import (
    NormalizedContract,
    Opportunity,
    PaperTrade,
    Portfolio,
    TradeLeg,
    TradeOut,
)

logger = logging.getLogger(__name__)


# ─── Portfolio helpers ─────────────────────────────────────────────────────────

async def get_or_create_portfolio(db: AsyncSession) -> Portfolio:
    result = await db.execute(select(Portfolio).where(Portfolio.id == 1))
    portfolio = result.scalar_one_or_none()
    if portfolio is None:
        portfolio = Portfolio(id=1, balance=settings.starting_balance, realized_pnl=0.0)
        db.add(portfolio)
        await db.commit()
        await db.refresh(portfolio)
    return portfolio


async def reset_portfolio(db: AsyncSession) -> Portfolio:
    """Reset balance, close all open trades, clear realized P&L."""
    portfolio = await get_or_create_portfolio(db)
    portfolio.balance = settings.starting_balance
    portfolio.realized_pnl = 0.0

    # Mark all open trades as closed with 0 realized P&L
    result = await db.execute(
        select(PaperTrade).where(PaperTrade.status == "open")
    )
    open_trades = result.scalars().all()
    for trade in open_trades:
        trade.status = "closed"
        trade.realized_pnl = 0.0
        trade.closed_at = datetime.utcnow()

    await db.commit()
    await db.refresh(portfolio)
    return portfolio


# ─── Trade creation ────────────────────────────────────────────────────────────

async def create_paper_trade(
    db: AsyncSession,
    opportunity: Opportunity,
    size: float,
) -> TradeOut:
    """
    Simulate entering all legs of an arbitrage opportunity at current ask prices.
    Deducts entry_cost from portfolio balance.

    FR-20: size cannot exceed max_size.
    """
    if size > opportunity.max_size:
        raise ValueError(
            f"Requested size {size} exceeds max executable size {opportunity.max_size:.2f}"
        )

    legs = [
        TradeLeg(
            outcome_id=leg.outcome_id,
            market_id=leg.market_id,
            label=leg.label,
            venue=leg.venue,
            entry_price=leg.ask,
            current_bid=leg.bid,
            current_ask=leg.ask,
            size=size,
        )
        for leg in opportunity.legs
    ]

    entry_cost = sum(leg.entry_price * size for leg in legs)
    locked_in_payoff = size * 1.0  # one outcome always pays $1

    opp_snapshot = {
        "id": opportunity.id,
        "event_title": opportunity.event_title,
        "edge_pct": opportunity.edge_pct,
        "total_ask": sum(l.ask for l in opportunity.legs),
        "legs": [l.model_dump() for l in opportunity.legs],
        "captured_at": datetime.utcnow().isoformat(),
    }

    trade = PaperTrade(
        opportunity_snapshot=json.dumps(opp_snapshot),
        legs_json=json.dumps([l.model_dump() for l in legs]),
        entry_cost=entry_cost,
        locked_in_payoff=locked_in_payoff,
        size=size,
        status="open",
    )
    db.add(trade)

    portfolio = await get_or_create_portfolio(db)
    portfolio.balance -= entry_cost

    await db.commit()
    await db.refresh(trade)

    unrealized_pnl = _compute_unrealized_pnl(legs, entry_cost)
    return TradeOut.from_db(trade, unrealized_pnl=unrealized_pnl)


# ─── Mark-to-market ────────────────────────────────────────────────────────────

def compute_unrealized_pnl(
    trade: PaperTrade,
    contracts_by_token: dict[str, NormalizedContract],
) -> float:
    """
    Computes unrealized P&L for an open trade using current market bids.

    unrealized_pnl = Σ(current_bid_i × size) - entry_cost
    """
    legs = [TradeLeg(**l) for l in json.loads(trade.legs_json)]
    current_value = 0.0
    for leg in legs:
        contract = contracts_by_token.get(leg.outcome_id)
        if contract and contract.bid is not None and not contract.is_stale:
            current_value += contract.bid * leg.size
        else:
            # If price unavailable, use entry price as fallback
            current_value += leg.entry_price * leg.size

    return current_value - trade.entry_cost


def _compute_unrealized_pnl(legs: list[TradeLeg], entry_cost: float) -> float:
    """Quick computation at trade creation time using current bid."""
    current_value = sum(
        (leg.current_bid or leg.entry_price) * leg.size for leg in legs
    )
    return current_value - entry_cost


# ─── Trade closing ─────────────────────────────────────────────────────────────

async def close_paper_trade(
    db: AsyncSession,
    trade_id: str,
    contracts_by_token: dict[str, NormalizedContract],
) -> TradeOut:
    """
    Simulate exiting all legs at current bid prices.
    Adds proceeds back to portfolio balance and records realized P&L.

    FR-26: close at current bid for long positions.
    """
    result = await db.execute(
        select(PaperTrade).where(PaperTrade.id == trade_id)
    )
    trade = result.scalar_one_or_none()
    if trade is None:
        raise ValueError(f"Trade {trade_id} not found")
    if trade.status != "open":
        raise ValueError(f"Trade {trade_id} is already closed")

    legs = [TradeLeg(**l) for l in json.loads(trade.legs_json)]
    close_proceeds = 0.0

    updated_legs = []
    for leg in legs:
        contract = contracts_by_token.get(leg.outcome_id)
        close_price = (
            contract.bid
            if contract and contract.bid is not None and not contract.is_stale
            else leg.entry_price
        )
        close_proceeds += close_price * leg.size
        updated_legs.append(
            leg.model_copy(update={"current_bid": close_price})
        )

    realized_pnl = close_proceeds - trade.entry_cost

    trade.status = "closed"
    trade.realized_pnl = realized_pnl
    trade.closed_at = datetime.utcnow()
    trade.legs_json = json.dumps([l.model_dump() for l in updated_legs])

    portfolio = await get_or_create_portfolio(db)
    portfolio.balance += close_proceeds  # return proceeds (entry_cost was already deducted)
    portfolio.realized_pnl += realized_pnl

    await db.commit()
    await db.refresh(trade)
    return TradeOut.from_db(trade, unrealized_pnl=None)


# ─── Portfolio summary ─────────────────────────────────────────────────────────

async def get_portfolio_summary(
    db: AsyncSession,
    contracts_by_token: dict[str, NormalizedContract],
) -> dict:
    portfolio = await get_or_create_portfolio(db)

    result = await db.execute(
        select(PaperTrade).where(PaperTrade.status == "open")
    )
    open_trades = result.scalars().all()

    total_unrealized = sum(
        compute_unrealized_pnl(t, contracts_by_token) for t in open_trades
    )

    return {
        "balance": portfolio.balance,
        "realized_pnl": portfolio.realized_pnl,
        "unrealized_pnl": total_unrealized,
        "total_pnl": portfolio.realized_pnl + total_unrealized,
        "open_trade_count": len(open_trades),
    }
