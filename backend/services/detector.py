"""
Arbitrage detection engine.

For each Polymarket market, groups contracts by conditionId and checks
whether buying all outcomes costs less than $1.00.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from typing import Optional

from config import settings
from models import NormalizedContract, Opportunity, OpportunityLeg

logger = logging.getLogger(__name__)


def detect_opportunities(
    contracts: list[NormalizedContract],
    min_edge_pct: Optional[float] = None,
) -> list[Opportunity]:
    """
    Given a list of NormalizedContracts, detect all intra-market arbitrage
    opportunities and return them sorted by edge descending.
    """
    if min_edge_pct is None:
        min_edge_pct = settings.min_edge_pct

    grouped = _group_by_market(contracts)
    opportunities: list[Opportunity] = []
    candidates: list[tuple[float, str, str]] = []  # (edge, title, reason_skipped)

    for market_id, legs in grouped.items():
        opp, skip_reason = _check_market_verbose(market_id, legs, min_edge_pct)
        if opp:
            opportunities.append(opp)
        elif skip_reason:
            candidates.append(skip_reason)

    opportunities.sort(key=lambda o: o.edge_pct, reverse=True)

    # Log top candidates even if below threshold (helps calibrate min_edge_pct)
    candidates.sort(key=lambda x: x[0], reverse=True)
    if candidates:
        logger.info(
            "Top near-arb markets (below %.1f%% threshold):",
            min_edge_pct * 100,
        )
        for edge, title, reason in candidates[:5]:
            logger.info("  edge=%.4f  %-55s  [%s]", edge, title[:55], reason)

    logger.info(
        "Detection: %d markets scanned, %d opportunities found (min_edge=%.3f%%)",
        len(grouped),
        len(opportunities),
        min_edge_pct * 100,
    )
    return opportunities


def _group_by_market(
    contracts: list[NormalizedContract],
) -> dict[str, list[NormalizedContract]]:
    groups: dict[str, list[NormalizedContract]] = {}
    for c in contracts:
        groups.setdefault(c.market_id, []).append(c)
    return groups


def _check_market_verbose(
    market_id: str,
    contracts: list[NormalizedContract],
    min_edge_pct: float,
) -> tuple[Optional[Opportunity], Optional[tuple[float, str, str]]]:
    """
    Returns (Opportunity, None) on success, or (None, (edge, title, reason))
    when skipped — so callers can log near-misses.
    """
    title = contracts[0].market_title if contracts else market_id

    if len(contracts) < 2:
        return None, None  # single-token markets, not worth logging

    if any(c.is_stale for c in contracts):
        return None, None  # stale, skip silently

    # FR-32: no missing prices — log as no-price if all asks are None
    missing = [c for c in contracts if c.ask is None or c.ask_size is None or c.ask <= 0]
    if missing:
        return None, None  # no price data yet, skip silently

    total_ask = sum(c.ask for c in contracts)  # type: ignore[arg-type]

    if total_ask >= 1.0:
        # Over-round market (no arb) — log as near-miss if close
        edge = 1.0 - total_ask  # negative
        if edge > -0.05:  # within 5 cents of par — worth logging
            return None, (edge, title, f"over-round total={total_ask:.4f}")
        return None, None

    edge_pct = 1.0 - total_ask

    max_size = min(c.ask_size for c in contracts)  # type: ignore[arg-type]
    if max_size <= 0:
        return None, (edge_pct, title, "max_size=0")

    if edge_pct < min_edge_pct:
        return None, (edge_pct, title, f"below threshold ({edge_pct*100:.3f}%)")

    legs = [
        OpportunityLeg(
            outcome_id=c.outcome_id,
            market_id=c.market_id,
            label=c.label,
            venue=c.venue,
            ask=c.ask,
            ask_size=c.ask_size,
            bid=c.bid or 0.0,
        )
        for c in contracts
    ]

    opp_id = hashlib.md5(market_id.encode()).hexdigest()[:16]

    return Opportunity(
        id=opp_id,
        type="intra",
        event_title=title,
        venues=["polymarket"],
        legs=legs,
        edge_pct=edge_pct,
        max_size=max_size,
        close_time=contracts[0].close_time,
        updated_at=datetime.utcnow(),
    ), None
