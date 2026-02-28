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
from difflib import SequenceMatcher
from datetime import datetime
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
_CROSS_MIN_SHARED_TOKENS = 2
_CROSS_MIN_SHORT_SHARED_TOKENS = 1
_CROSS_MIN_FAST_SCORE = 0.34
_CROSS_MIN_TEXT_SIMILARITY = 0.58
_CROSS_MAX_CLOSE_GAP_S = 30 * 24 * 3600
_CROSS_MAX_CANDIDATES_PER_MARKET = 12
_CROSS_SEED_TOKEN_LIMIT = 3


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
    anchor_tokens: tuple[str, ...]
    numeric_tokens: frozenset[str]


def detect_opportunities(
    contracts: list[NormalizedContract],
    min_edge_pct: Optional[float] = None,
    min_max_size: Optional[float] = None,
) -> list[Opportunity]:
    """
    Run all detection passes and return opportunities sorted by edge descending.
    """
    if min_edge_pct is None:
        min_edge_pct = settings.min_edge_pct
    if min_max_size is None:
        min_max_size = settings.min_max_size

    opportunities: list[Opportunity] = []

    # Pass 1: event-group arb (negRisk YES tokens grouped by event_id)
    event_contracts = [c for c in contracts if c.event_id]
    grouped_events = _group_by_event(event_contracts)
    for event_id, legs in grouped_events.items():
        opp, _ = _check_group(
            group_id=event_id,
            contracts=legs,
            min_edge_pct=min_edge_pct,
            min_max_size=min_max_size,
            opp_type="event",
            title=legs[0].event_title or event_id,
        )
        if opp:
            opportunities.append(opp)

    # Pass 2: intra-market arb (binary YES+NO grouped by market_id)
    binary_contracts = [c for c in contracts if not c.event_id]
    grouped_markets = _group_by_market(binary_contracts)
    for market_id, legs in grouped_markets.items():
        opp, _ = _check_group(
            group_id=market_id,
            contracts=legs,
            min_edge_pct=min_edge_pct,
            min_max_size=min_max_size,
            opp_type="intra",
            title=legs[0].market_title if legs else market_id,
        )
        if opp:
            opportunities.append(opp)

    # Pass 3: cross-venue binary arb (buy YES on one venue, NO on the other)
    cross_opps, cross_pair_count = _detect_cross_venue(
        binary_contracts,
        min_edge_pct=min_edge_pct,
        min_max_size=min_max_size,
    )
    opportunities.extend(cross_opps)

    opportunities.sort(key=lambda o: o.edge_pct, reverse=True)

    if opportunities:
        logger.info("Top opportunities:")
        for rank, opp in enumerate(opportunities[:], start=1):
            logger.info(
                "  #%d edge=%+.4f size=%.2f type=%s legs=%d venues=%s title=%s",
                rank,
                opp.edge_pct,
                opp.max_size,
                opp.type,
                len(opp.legs),
                "/".join(opp.venues),
                (opp.event_title or "")[:80],
            )
    else:
        logger.info("Top opportunities: none")

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
    min_max_size: float,
    opp_type: str,
    title: str,
) -> tuple[Optional[Opportunity], Optional[tuple[float, str, str]]]:
    """
    Check whether a group of contracts (either a negRisk event's YES tokens
    or a binary market's YES+NO tokens) has an arb opportunity.

    Returns an Opportunity when valid and profitable, otherwise None.
    The second tuple value is retained for internal diagnostics.
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
    if max_size < min_max_size:
        return None, (edge_pct, title, f"max_size<{min_max_size:.2f}")

    if edge_pct < min_edge_pct:
        return None, (edge_pct, title, f"below threshold ({edge_pct*100:.3f}%)")

    legs = [
        OpportunityLeg(
            outcome_id=c.outcome_id,
            market_id=c.market_id,
            market_title=c.market_title,
            market_url=c.market_url,
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
    min_max_size: float,
) -> tuple[list[Opportunity], int]:
    opportunities: list[Opportunity] = []

    markets = _build_binary_markets(contracts)
    matched_pairs = _match_cross_venue_pairs(markets)

    for left, right, _score in matched_pairs:
        display_title = _cross_display_title(left.title, right.title)

        for left_leg, right_leg in ((left.yes, right.no), (left.no, right.yes)):
            opp, _ = _check_cross_pair(
                left_leg=left_leg,
                right_leg=right_leg,
                title=display_title,
                min_edge_pct=min_edge_pct,
                min_max_size=min_max_size,
            )
            if opp:
                opportunities.append(opp)

    return opportunities, len(matched_pairs)


def _check_cross_pair(
    left_leg: NormalizedContract,
    right_leg: NormalizedContract,
    title: str,
    min_edge_pct: float,
    min_max_size: float,
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
    if max_size < min_max_size:
        return None, (edge_pct, title, f"cross max_size<{min_max_size:.2f}")

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
            market_url=left_leg.market_url,
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
            market_url=right_leg.market_url,
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
        ordered_tokens = _ordered_title_tokens(title)
        canonical = " ".join(ordered_tokens)
        tokens = set(ordered_tokens)
        if not canonical or len(tokens) < 2:
            continue
        anchor_tokens = _anchor_tokens(tokens)
        numeric_tokens = frozenset(t for t in tokens if _token_has_digits(t))
        if (
            _leg_executable_size(yes) < settings.min_max_size
            and _leg_executable_size(no) < settings.min_max_size
        ):
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
                anchor_tokens=anchor_tokens,
                numeric_tokens=numeric_tokens,
            )
        )

    return markets


def _match_cross_venue_pairs(
    markets: list[_BinaryMarket],
) -> list[tuple[_BinaryMarket, _BinaryMarket, float]]:
    by_venue: dict[str, list[_BinaryMarket]] = {}
    for m in markets:
        by_venue.setdefault(m.venue, []).append(m)

    venue_names = sorted(by_venue.keys())
    if len(venue_names) < 2:
        return []

    all_pairs: list[tuple[_BinaryMarket, _BinaryMarket, float]] = []
    for i, left_venue in enumerate(venue_names):
        for right_venue in venue_names[i + 1:]:
            left_markets = by_venue[left_venue]
            right_markets = by_venue[right_venue]
            all_pairs.extend(_match_venue_pair(left_markets, right_markets))

    all_pairs.sort(
        key=lambda x: (x[2], x[0].market_id, x[1].market_id),
        reverse=True,
    )
    return all_pairs


def _match_venue_pair(
    left_markets: list[_BinaryMarket],
    right_markets: list[_BinaryMarket],
) -> list[tuple[_BinaryMarket, _BinaryMarket, float]]:
    # Build sparse indices once and only run expensive text scoring on a
    # tightly-pruned candidate set per left market.
    exact_title_to_right_idxs: dict[str, list[int]] = {}
    token_to_right_idxs: dict[str, list[int]] = {}
    for idx, market in enumerate(right_markets):
        exact_title_to_right_idxs.setdefault(market.canonical_title, []).append(idx)
        for token in market.tokens:
            token_to_right_idxs.setdefault(token, []).append(idx)

    max_posting_size = max(24, len(right_markets) // 6)
    matches: list[tuple[_BinaryMarket, _BinaryMarket, float]] = []
    for left in left_markets:
        exact_matches = exact_title_to_right_idxs.get(left.canonical_title)
        if exact_matches:
            ranked_candidate_idxs = exact_matches[:]
        else:
            candidate_counts: dict[int, int] = {}
            for token in _seed_tokens(left, token_to_right_idxs, max_posting_size):
                for idx in token_to_right_idxs.get(token, []):
                    candidate_counts[idx] = candidate_counts.get(idx, 0) + 1

            if not candidate_counts:
                continue

            ranked_candidate_idxs = [
                idx
                for idx, _count in sorted(
                    candidate_counts.items(),
                    key=lambda item: (
                        item[1],
                        _candidate_rank(left, right_markets[item[0]]),
                        right_markets[item[0]].market_id,
                    ),
                    reverse=True,
                )[:_CROSS_MAX_CANDIDATES_PER_MARKET]
            ]

        for idx in ranked_candidate_idxs:
            right = right_markets[idx]
            score = _cross_match_score(left, right)
            if score is None:
                continue
            matches.append((left, right, score))

    return _select_best_disjoint_matches(matches)


def _cross_match_score(left: _BinaryMarket, right: _BinaryMarket) -> Optional[float]:
    if left.canonical_title == right.canonical_title:
        base_score = 1.0
    else:
        overlap = left.tokens & right.tokens
        min_shared = (
            _CROSS_MIN_SHORT_SHARED_TOKENS
            if min(len(left.tokens), len(right.tokens)) <= 2
            else _CROSS_MIN_SHARED_TOKENS
        )
        if len(overlap) < min_shared:
            return None
        if left.numeric_tokens and right.numeric_tokens and not (left.numeric_tokens & right.numeric_tokens):
            return None

        union = left.tokens | right.tokens
        if not union:
            return None
        jaccard = len(overlap) / len(union)
        overlap_ratio = len(overlap) / max(len(left.tokens), len(right.tokens))
        anchor_overlap = len(set(left.anchor_tokens) & set(right.anchor_tokens))
        fast_score = max(
            jaccard,
            overlap_ratio,
            min(1.0, (anchor_overlap * 0.20) + overlap_ratio),
        )
        if fast_score < _CROSS_MIN_FAST_SCORE:
            return None

        similarity = SequenceMatcher(
            None,
            left.canonical_title,
            right.canonical_title,
        ).ratio()

        if similarity < _CROSS_MIN_TEXT_SIMILARITY:
            return None
        base_score = max(fast_score, similarity)

    if left.close_time and right.close_time:
        gap_seconds = abs((left.close_time - right.close_time).total_seconds())
        if gap_seconds > _CROSS_MAX_CLOSE_GAP_S:
            return None
        # Keep nearer expiries ranked slightly higher.
        base_score += max(0.0, 0.05 - (gap_seconds / _CROSS_MAX_CLOSE_GAP_S) * 0.05)

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
    return " ".join(_ordered_title_tokens(title))


def _title_tokens(title: str) -> set[str]:
    return set(_ordered_title_tokens(title))


def _ordered_title_tokens(title: str) -> list[str]:
    return [t for t in _TITLE_TOKEN_RE.findall(title.lower()) if t not in _TITLE_STOPWORDS]


def _anchor_tokens(tokens: set[str]) -> tuple[str, ...]:
    return tuple(
        sorted(tokens, key=_token_sort_key, reverse=True)[:_CROSS_SEED_TOKEN_LIMIT]
    )


def _token_sort_key(token: str) -> tuple[int, int, str]:
    return (1 if _token_has_digits(token) else 0, len(token), token)


def _token_has_digits(token: str) -> bool:
    return any(ch.isdigit() for ch in token)


def _seed_tokens(
    market: _BinaryMarket,
    token_to_right_idxs: dict[str, list[int]],
    max_posting_size: int,
) -> list[str]:
    ranked_tokens = list(market.anchor_tokens)
    if len(ranked_tokens) < _CROSS_SEED_TOKEN_LIMIT:
        for token in sorted(market.tokens, key=_token_sort_key, reverse=True):
            if token not in ranked_tokens:
                ranked_tokens.append(token)
            if len(ranked_tokens) >= _CROSS_SEED_TOKEN_LIMIT:
                break

    seeded = [
        token
        for token in ranked_tokens
        if 0 < len(token_to_right_idxs.get(token, ())) <= max_posting_size
    ]
    seeded.sort(
        key=lambda token: (
            len(token_to_right_idxs.get(token, ())),
            -(1 if _token_has_digits(token) else 0),
            -len(token),
            token,
        )
    )
    return seeded[:_CROSS_SEED_TOKEN_LIMIT]


def _candidate_rank(left: _BinaryMarket, right: _BinaryMarket) -> tuple[int, float]:
    overlap = len(left.tokens & right.tokens)
    anchor_overlap = len(set(left.anchor_tokens) & set(right.anchor_tokens))
    return (anchor_overlap, overlap / max(len(left.tokens), len(right.tokens)))


def _select_best_disjoint_matches(
    matches: list[tuple[_BinaryMarket, _BinaryMarket, float]],
) -> list[tuple[_BinaryMarket, _BinaryMarket, float]]:
    matches.sort(
        key=lambda x: (
            x[2],
            x[0].canonical_title == x[1].canonical_title,
            x[0].market_id,
            x[1].market_id,
        ),
        reverse=True,
    )

    used_left: set[tuple[str, str]] = set()
    used_right: set[tuple[str, str]] = set()
    selected: list[tuple[_BinaryMarket, _BinaryMarket, float]] = []

    for left, right, score in matches:
        left_key = (left.venue, left.market_id)
        right_key = (right.venue, right.market_id)
        if left_key in used_left or right_key in used_right:
            continue
        used_left.add(left_key)
        used_right.add(right_key)
        selected.append((left, right, score))

    return selected


def _leg_executable_size(contract: NormalizedContract) -> float:
    if contract.ask is None or contract.ask <= 0:
        return 0.0
    if contract.ask_size is None or contract.ask_size <= 0:
        return 0.0
    return contract.ask_size
