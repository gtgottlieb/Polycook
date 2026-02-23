"""
Arbitrage detection engine.

Two detection passes per cycle:

  1. EVENT-GROUP (negRisk)
     Group YES tokens by event_id.  If Σ ask(YES_i) < 1.0 across all
     active markets in a negRisk event, there is an arb opportunity:
     buy every YES token, one pays out $1 at resolution.

  2. INTRA-MARKET (binary)
     Group YES+NO tokens by market_id.  If ask(YES) + ask(NO) < 1.0
     there is a classical intra-market arb (rare; included for completeness).
"""
from __future__ import annotations

import hashlib
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
    Run both detection passes and return all opportunities sorted by
    edge descending.
    """
    if min_edge_pct is None:
        min_edge_pct = settings.min_edge_pct

    opportunities: list[Opportunity] = []
    near_misses: list[tuple[float, str, str]] = []  # (edge, title, reason)

    # ── Pass 1: event-group arb (negRisk YES tokens grouped by event_id) ──
    event_contracts = [c for c in contracts if c.event_id]
    grouped_events = _group_by_event(event_contracts)
    for event_id, legs in grouped_events.items():
        opp, miss = _check_group(
            group_id=event_id,
            contracts=legs,
            min_edge_pct=min_edge_pct,
            opp_type="event",
            title=legs[0].event_title or event_id,
        )
        if opp:
            opportunities.append(opp)
        elif miss:
            near_misses.append(miss)

    # ── Pass 2: intra-market arb (binary YES+NO grouped by market_id) ──
    binary_contracts = [c for c in contracts if not c.event_id]
    grouped_markets = _group_by_market(binary_contracts)
    for market_id, legs in grouped_markets.items():
        opp, miss = _check_group(
            group_id=market_id,
            contracts=legs,
            min_edge_pct=min_edge_pct,
            opp_type="intra",
            title=legs[0].market_title if legs else market_id,
        )
        if opp:
            opportunities.append(opp)
        elif miss:
            near_misses.append(miss)

    opportunities.sort(key=lambda o: o.edge_pct, reverse=True)

    # Log top near-misses (helps calibrate threshold and spot almost-arbs)
    near_misses.sort(key=lambda x: x[0], reverse=True)
    if near_misses:
        logger.info(
            "Top near-arb groups (below %.2f%% threshold):",
            min_edge_pct * 100,
        )
        for edge, title, reason in near_misses[:10]:
            logger.info("  edge=%+.4f  %-55s  [%s]", edge, title[:55], reason)

    logger.info(
        "Detection: %d event groups + %d binary markets scanned → %d opportunities (min_edge=%.3f%%)",
        len(grouped_events),
        len(grouped_markets),
        len(opportunities),
        min_edge_pct * 100,
    )
    return opportunities


# ─── Grouping helpers ──────────────────────────────────────────────────────────

def _group_by_event(
    contracts: list[NormalizedContract],
) -> dict[str, list[NormalizedContract]]:
    groups: dict[str, list[NormalizedContract]] = {}
    for c in contracts:
        if c.event_id:
            groups.setdefault(c.event_id, []).append(c)
    return groups


def _group_by_market(
    contracts: list[NormalizedContract],
) -> dict[str, list[NormalizedContract]]:
    groups: dict[str, list[NormalizedContract]] = {}
    for c in contracts:
        groups.setdefault(c.market_id, []).append(c)
    return groups


# ─── Core arb check ───────────────────────────────────────────────────────────

def _check_group(
    group_id: str,
    contracts: list[NormalizedContract],
    min_edge_pct: float,
    opp_type: str,
    title: str,
) -> tuple[Optional[Opportunity], Optional[tuple[float, str, str]]]:
    """
    Check whether a group of contracts (either a negRisk event's YES tokens
    or a binary market's YES+NO tokens) has an arb opportunity.

    Returns (Opportunity, None) on success, (None, near_miss_tuple) when
    skipped but close, or (None, None) when silently skipped.
    """
    if len(contracts) < 2:
        return None, None  # need at least 2 outcomes

    if any(c.is_stale for c in contracts):
        return None, None  # stale data, skip silently

    missing = [c for c in contracts if c.ask is None or c.ask_size is None or c.ask <= 0]
    if missing:
        return None, None  # no price data yet

    total_ask = sum(c.ask for c in contracts)  # type: ignore[arg-type]

    if total_ask >= 1.0:
        edge = 1.0 - total_ask  # negative when over-round
        if edge > -0.05:  # within 5 cents of par — worth logging
            return None, (edge, title, f"over-round total={total_ask:.4f} ({len(contracts)} legs)")
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
            market_title=c.market_title,
            label=c.label,
            venue=c.venue,
            ask=c.ask,
            ask_size=c.ask_size,
            bid=c.bid or 0.0,
        )
        for c in contracts
    ]

    opp_id = hashlib.md5(group_id.encode()).hexdigest()[:16]

    # For event-group arb, use event_title; for intra-market, use market_title
    return Opportunity(
        id=opp_id,
        type=opp_type,
        event_title=title,
        venues=list({c.venue for c in contracts}),
        legs=legs,
        edge_pct=edge_pct,
        max_size=max_size,
        close_time=min(
            (c.close_time for c in contracts if c.close_time),
            default=None,
        ),
        updated_at=datetime.utcnow(),
    ), None
