"""
Arbitrage detection engine.

Three detection passes per cycle:

  1. EVENT-GROUP (negRisk)
     Group YES tokens by event_id. If sum(ask(YES_i)) < 1.0 across all
     active markets in a negRisk event, there is an arb opportunity:
     buy every YES token, one pays out $1 at resolution.

  2. INTRA-MARKET (binary)
     Group YES+NO tokens by market_id. If ask(YES) + ask(NO) < 1.0
     there is a classical intra-market arb (rare; included for completeness).

  3. CROSS-VENUE (binary)
     Match equivalent YES/NO questions across venues and check:
     ask(YES @ venue A) + ask(NO @ venue B) < 1.0 (and the inverse).
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from itertools import combinations
from typing import Optional

from config import settings
from models import NormalizedContract, Opportunity, OpportunityLeg

logger = logging.getLogger(__name__)

_TITLE_TOKEN_RE = re.compile(r"[a-z0-9]+")
_TITLE_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "of",
    "on",
    "or",
    "the",
    "to",
    "will",
    "with",
}


@dataclass(frozen=True)
class _BinaryMarket:
    venue: str
    market_id: str
    title: str
    close_time: Optional[datetime]
    yes: NormalizedContract
    no: NormalizedContract
    canonical_title: str
    tokens: set[str]


def detect_opportunities(
    contracts: list[NormalizedContract],
    min_edge_pct: Optional[float] = None,
) -> list[Opportunity]:
    """
    Run all detection passes and return opportunities sorted by edge descending.
    """
    if min_edge_pct is None:
        min_edge_pct = settings.min_edge_pct

    opportunities: list[Opportunity] = []
    near_misses: list[tuple[float, str, str]] = []  # (edge, title, reason)

    # Pass 1: event-group arb (negRisk YES tokens grouped by event_id)
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

    # Pass 2: intra-market arb (binary YES+NO grouped by market_id)
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

    # Pass 3: cross-venue binary arb (buy YES on one venue, NO on the other)
    cross_opps, cross_misses, cross_pair_count = _detect_cross_venue(
        binary_contracts,
        min_edge_pct=min_edge_pct,
    )
    opportunities.extend(cross_opps)
    near_misses.extend(cross_misses)

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
        "Detection: %d event groups + %d binary markets + %d cross-venue pairs scanned -> %d opportunities (min_edge=%.3f%%)",
        len(grouped_events),
        len(grouped_markets),
        cross_pair_count,
        len(opportunities),
        min_edge_pct * 100,
    )
    return opportunities


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
        return None, None

    if any(c.is_stale for c in contracts):
        return None, None

    missing = [c for c in contracts if c.ask is None or c.ask_size is None or c.ask <= 0]
    if missing:
        return None, None

    total_ask = sum(c.ask for c in contracts)  # type: ignore[arg-type]

    if total_ask >= 1.0:
        edge = 1.0 - total_ask
        if edge > -0.05:
            return None, (
                edge,
                title,
                f"over-round total={total_ask:.4f} ({len(contracts)} legs)",
            )
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


def _detect_cross_venue(
    contracts: list[NormalizedContract],
    min_edge_pct: float,
) -> tuple[list[Opportunity], list[tuple[float, str, str]], int]:
    opportunities: list[Opportunity] = []
    near_misses: list[tuple[float, str, str]] = []

    markets = _build_binary_markets(contracts)
    matched_pairs = _match_cross_venue_pairs(markets)

    for left, right, _score in matched_pairs:
        display_title = _cross_display_title(left.title, right.title)

        for left_leg, right_leg in ((left.yes, right.no), (left.no, right.yes)):
            opp, miss = _check_cross_pair(
                left_leg=left_leg,
                right_leg=right_leg,
                title=display_title,
                min_edge_pct=min_edge_pct,
            )
            if opp:
                opportunities.append(opp)
            elif miss:
                near_misses.append(miss)

    return opportunities, near_misses, len(matched_pairs)


def _check_cross_pair(
    left_leg: NormalizedContract,
    right_leg: NormalizedContract,
    title: str,
    min_edge_pct: float,
) -> tuple[Optional[Opportunity], Optional[tuple[float, str, str]]]:
    if left_leg.venue == right_leg.venue:
        return None, None
    if left_leg.is_stale or right_leg.is_stale:
        return None, None

    if (
        left_leg.ask is None
        or right_leg.ask is None
        or left_leg.ask_size is None
        or right_leg.ask_size is None
        or left_leg.ask <= 0
        or right_leg.ask <= 0
    ):
        return None, None

    total_ask = left_leg.ask + right_leg.ask
    edge_pct = 1.0 - total_ask
    max_size = min(left_leg.ask_size, right_leg.ask_size)

    if total_ask >= 1.0:
        if edge_pct > -0.05:
            return None, (
                edge_pct,
                title,
                f"cross over-round total={total_ask:.4f} ({left_leg.label}+{right_leg.label})",
            )
        return None, None

    if max_size <= 0:
        return None, (edge_pct, title, "cross max_size=0")

    if edge_pct < min_edge_pct:
        return None, (
            edge_pct,
            title,
            f"cross below threshold ({edge_pct*100:.3f}%)",
        )

    legs = [
        OpportunityLeg(
            outcome_id=left_leg.outcome_id,
            market_id=left_leg.market_id,
            market_title=left_leg.market_title,
            label=left_leg.label,
            venue=left_leg.venue,
            ask=left_leg.ask,
            ask_size=left_leg.ask_size,
            bid=left_leg.bid or 0.0,
        ),
        OpportunityLeg(
            outcome_id=right_leg.outcome_id,
            market_id=right_leg.market_id,
            market_title=right_leg.market_title,
            label=right_leg.label,
            venue=right_leg.venue,
            ask=right_leg.ask,
            ask_size=right_leg.ask_size,
            bid=right_leg.bid or 0.0,
        ),
    ]

    opp_seed = (
        f"cross:{left_leg.market_id}:{left_leg.label.lower()}:"
        f"{right_leg.market_id}:{right_leg.label.lower()}"
    )
    opp_id = hashlib.md5(opp_seed.encode()).hexdigest()[:16]

    close_time = min(
        (t for t in (left_leg.close_time, right_leg.close_time) if t),
        default=None,
    )
    venues = list(dict.fromkeys([left_leg.venue, right_leg.venue]))

    return Opportunity(
        id=opp_id,
        type="cross",
        event_title=title,
        venues=venues,
        legs=legs,
        edge_pct=edge_pct,
        max_size=max_size,
        close_time=close_time,
        updated_at=datetime.utcnow(),
    ), None


def _build_binary_markets(contracts: list[NormalizedContract]) -> list[_BinaryMarket]:
    grouped: dict[tuple[str, str], list[NormalizedContract]] = {}
    for c in contracts:
        if c.event_id:
            continue
        grouped.setdefault((c.venue, c.market_id), []).append(c)

    markets: list[_BinaryMarket] = []
    for (venue, market_id), legs in grouped.items():
        yes = next((c for c in legs if _is_yes_label(c.label)), None)
        no = next((c for c in legs if _is_no_label(c.label)), None)
        if yes is None or no is None:
            continue

        title = yes.market_title or no.market_title
        canonical = _canonicalize_title(title)
        tokens = _title_tokens(title)
        if not canonical or len(tokens) < 3:
            continue

        close_time = min(
            (t for t in (yes.close_time, no.close_time) if t),
            default=None,
        )

        markets.append(
            _BinaryMarket(
                venue=venue,
                market_id=market_id,
                title=title,
                close_time=close_time,
                yes=yes,
                no=no,
                canonical_title=canonical,
                tokens=tokens,
            )
        )

    return markets


def _match_cross_venue_pairs(
    markets: list[_BinaryMarket],
) -> list[tuple[_BinaryMarket, _BinaryMarket, float]]:
    candidates: list[tuple[float, _BinaryMarket, _BinaryMarket]] = []
    for left, right in combinations(markets, 2):
        if left.venue == right.venue:
            continue
        score = _cross_match_score(left, right)
        if score is None:
            continue
        candidates.append((score, left, right))

    candidates.sort(
        key=lambda x: (x[0], x[1].market_id, x[2].market_id),
        reverse=True,
    )

    selected: list[tuple[_BinaryMarket, _BinaryMarket, float]] = []
    used_market_keys: set[str] = set()
    for score, left, right in candidates:
        left_key = f"{left.venue}:{left.market_id}"
        right_key = f"{right.venue}:{right.market_id}"
        if left_key in used_market_keys or right_key in used_market_keys:
            continue
        used_market_keys.add(left_key)
        used_market_keys.add(right_key)
        selected.append((left, right, score))

    return selected


def _cross_match_score(left: _BinaryMarket, right: _BinaryMarket) -> Optional[float]:
    if left.canonical_title == right.canonical_title:
        base_score = 1.0
    else:
        overlap = left.tokens & right.tokens
        if len(overlap) < 4:
            return None
        union = left.tokens | right.tokens
        if not union:
            return None
        jaccard = len(overlap) / len(union)
        if jaccard < 0.72:
            return None
        base_score = jaccard

    if left.close_time and right.close_time:
        gap_seconds = abs((left.close_time - right.close_time).total_seconds())
        if gap_seconds > 2 * 24 * 3600:
            return None
        # Small bonus for close expiries, keeps tie-breaking deterministic.
        base_score += max(0.0, 0.02 - (gap_seconds / (2 * 24 * 3600)) * 0.02)

    return base_score


def _cross_display_title(left_title: str, right_title: str) -> str:
    if _canonicalize_title(left_title) == _canonicalize_title(right_title):
        return left_title
    return f"{left_title} / {right_title}"


def _is_yes_label(label: str) -> bool:
    return label.strip().lower() == "yes"


def _is_no_label(label: str) -> bool:
    return label.strip().lower() == "no"


def _canonicalize_title(title: str) -> str:
    tokens = [t for t in _TITLE_TOKEN_RE.findall(title.lower()) if t not in _TITLE_STOPWORDS]
    return " ".join(tokens)


def _title_tokens(title: str) -> set[str]:
    return {t for t in _TITLE_TOKEN_RE.findall(title.lower()) if t not in _TITLE_STOPWORDS}

