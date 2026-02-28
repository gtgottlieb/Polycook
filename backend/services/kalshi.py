"""
Kalshi public market data client.

This module fetches open Kalshi markets from the public Trade API and
normalizes them into YES/NO contracts compatible with the existing detector.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional
from urllib.parse import quote

import aiohttp

from config import settings
from models import NormalizedContract, VenueStatus

logger = logging.getLogger(__name__)

_venue_status = VenueStatus(
    connected=False,
    last_update=None,
    stale=True,
    market_count=0,
)

_KALSHI_MARKET_CAP = 2000


def get_venue_status() -> VenueStatus:
    return _venue_status


async def fetch_markets() -> list[NormalizedContract]:
    """
    Fetch active Kalshi markets and emit YES/NO normalized contracts.
    """
    global _venue_status
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=60)
        ) as session:
            raw_markets = await _fetch_kalshi_markets(session)
            contracts = _parse_kalshi_markets(raw_markets)

        now = datetime.utcnow()
        _venue_status = VenueStatus(
            connected=True,
            last_update=now,
            stale=False,
            market_count=len(raw_markets),
        )
        logger.info(
            "Kalshi fetch complete: %d markets -> %d contracts",
            len(raw_markets),
            len(contracts),
        )
        return contracts
    except Exception as exc:
        logger.error("Failed to fetch Kalshi data: %s", exc)
        _venue_status = VenueStatus(
            connected=False,
            last_update=_venue_status.last_update,
            stale=True,
            market_count=_venue_status.market_count,
            error=str(exc),
        )
        return []


async def _fetch_kalshi_markets(session: aiohttp.ClientSession) -> list[dict]:
    markets: list[dict] = []
    cursor: Optional[str] = None
    per_page = 200
    target = min(settings.max_markets, _KALSHI_MARKET_CAP)
    base_url = f"{settings.kalshi_base_url}/markets"

    while len(markets) < target:
        params: dict[str, str | int] = {
            "limit": per_page,
            "status": "open",
        }
        if cursor:
            params["cursor"] = cursor

        async with session.get(base_url, params=params) as resp:
            if resp.status != 200:
                logger.warning("Kalshi /markets returned %s", resp.status)
                break
            data = await resp.json(content_type=None)

        page = data.get("markets") or []
        if not page:
            break

        markets.extend(page)
        cursor = data.get("cursor")
        if not cursor:
            break

    return markets[:target]


def _parse_kalshi_markets(raw_markets: list[dict]) -> list[NormalizedContract]:
    now = datetime.utcnow()
    contracts: list[NormalizedContract] = []

    for m in raw_markets:
        market_id = m.get("ticker")
        if not market_id:
            continue
        event_ticker = str(m.get("event_ticker") or "").strip()

        title = (m.get("title") or m.get("subtitle") or market_id).strip()
        close_time = _parse_dt(
            m.get("close_time")
            or m.get("expiration_time")
            or m.get("expected_expiration_time")
        )
        if close_time and close_time < now:
            continue

        yes_bid = _parse_price(m.get("yes_bid_dollars"), m.get("yes_bid"))
        yes_ask = _parse_price(m.get("yes_ask_dollars"), m.get("yes_ask"))
        no_bid = _parse_price(m.get("no_bid_dollars"), m.get("no_bid"))
        no_ask = _parse_price(m.get("no_ask_dollars"), m.get("no_ask"))

        size_hint = _first_positive(
            _to_float(m.get("liquidity_dollars")),
            _to_float(m.get("open_interest")),
            _to_float(m.get("volume_24h")),
            _to_float(m.get("volume")),
        )

        if yes_bid is None and yes_ask is None and no_bid is None and no_ask is None:
            continue
        if size_hint is None or size_hint < settings.min_max_size:
            continue

        market_url = _build_market_url(
            event_ticker=event_ticker or None,
            market_id=market_id,
        )

        contracts.append(
            NormalizedContract(
                venue="kalshi",
                market_id=market_id,
                outcome_id=f"{market_id}:YES",
                label="Yes",
                bid=yes_bid,
                ask=yes_ask,
                bid_size=size_hint,
                ask_size=size_hint,
                close_time=close_time,
                updated_at=now,
                market_title=title,
                market_url=market_url,
            )
        )
        contracts.append(
            NormalizedContract(
                venue="kalshi",
                market_id=market_id,
                outcome_id=f"{market_id}:NO",
                label="No",
                bid=no_bid,
                ask=no_ask,
                bid_size=size_hint,
                ask_size=size_hint,
                close_time=close_time,
                updated_at=now,
                market_title=title,
                market_url=market_url,
            )
        )

    return contracts


def _parse_dt(value: object) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    raw = str(value)
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _parse_price(dollars: object, raw: object) -> Optional[float]:
    value = _to_float(dollars)
    if value is None:
        value = _to_float(raw)
        if value is not None and value > 1.0:
            value /= 100.0

    if value is None:
        return None
    if value <= 0.0:
        return None
    if value >= 1.0:
        return None
    return float(value)


def _to_float(value: object) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_positive(*values: Optional[float]) -> Optional[float]:
    for v in values:
        if v is not None and v > 0:
            return float(v)
    return None


def _build_market_url(event_ticker: Optional[str], market_id: str) -> str:
    # Kalshi's web app is event-centric. Linking to the event page is more
    # reliable than linking to the raw market ticker route, which may not
    # resolve for all contract sub-markets.
    target = event_ticker or market_id
    return f"https://kalshi.com/markets/{quote(target, safe='')}"
