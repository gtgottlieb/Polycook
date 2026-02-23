"""
Polymarket API client.

Strategy:
  1. negRisk events  – fetch ALL active negRisk events from Gamma /events.
     Each event groups mutually-exclusive binary markets (e.g. "Who wins the
     Stanley Cup?").  We extract the YES token from every market in the event
     and check Σ ask(YES_i) < 1.0 for event-group arb.

  2. Binary markets  – small set of the *least-competitive* binary markets
     (competitive score ascending) where intra-market arb is theoretically
     possible (ask_YES + ask_NO < 1.0).  High-volume markets are always
     efficiently priced at ~1.001 so we skip them.

Both passes fetch CLOB order books concurrently for accurate bid/ask/sizes.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional

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

# Hard cap on binary markets to scan (they rarely have arb; save CLOB budget)
_BINARY_MARKET_CAP = 100


def get_venue_status() -> VenueStatus:
    return _venue_status


async def fetch_markets() -> list[NormalizedContract]:
    """
    Main entry point. Returns a flat list of NormalizedContract, one per
    outcome token, combining negRisk event YES-legs and binary market legs.
    """
    global _venue_status
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30)
        ) as session:
            # Fetch both sources concurrently
            event_task = asyncio.create_task(_fetch_neg_risk_event_contracts(session))
            binary_task = asyncio.create_task(_fetch_binary_market_contracts(session))
            event_contracts, binary_contracts = await asyncio.gather(event_task, binary_task)

            all_contracts = event_contracts + binary_contracts
            if not all_contracts:
                _venue_status = VenueStatus(
                    connected=True,
                    last_update=datetime.utcnow(),
                    stale=False,
                    market_count=0,
                )
                return []

            token_ids = [c.outcome_id for c in all_contracts]
            books = await _fetch_order_books(session, token_ids)
            all_contracts = _apply_order_books(all_contracts, books)

        now = datetime.utcnow()
        event_ids = {c.event_id for c in all_contracts if c.event_id}
        market_ids = {c.market_id for c in all_contracts if not c.event_id}
        logger.info(
            "Fetch complete: %d event-group contracts (%d events) + %d binary contracts (%d markets)",
            len(event_contracts), len(event_ids),
            len(binary_contracts), len(market_ids),
        )
        _venue_status = VenueStatus(
            connected=True,
            last_update=now,
            stale=False,
            market_count=len(event_ids) + len(market_ids),
        )
        return all_contracts

    except Exception as exc:
        logger.error("Failed to fetch Polymarket data: %s", exc)
        _venue_status = VenueStatus(
            connected=False,
            last_update=_venue_status.last_update,
            stale=True,
            market_count=_venue_status.market_count,
            error=str(exc),
        )
        return []


# ─── negRisk event pipeline ────────────────────────────────────────────────────

async def _fetch_neg_risk_event_contracts(
    session: aiohttp.ClientSession,
) -> list[NormalizedContract]:
    """Fetch negRisk events and return one YES-token contract per active market."""
    raw_events = await _fetch_gamma_events(session)
    contracts = _parse_neg_risk_events(raw_events)
    logger.info(
        "negRisk pipeline: %d events → %d YES-token contracts",
        len(raw_events), len(contracts),
    )
    return contracts


async def _fetch_gamma_events(session: aiohttp.ClientSession) -> list[dict]:
    """Fetch all active negRisk events from the Gamma API."""
    events: list[dict] = []
    limit = 100
    offset = 0

    while True:
        url = (
            f"{settings.gamma_base_url}/events"
            f"?active=true&closed=false&limit={limit}&offset={offset}"
            f"&negRisk=true"
        )
        async with session.get(url) as resp:
            if resp.status != 200:
                logger.warning("Gamma /events returned %s", resp.status)
                break
            data = await resp.json(content_type=None)

        if not data:
            break

        events.extend(data)
        if len(data) < limit:
            break
        offset += limit

    logger.info("Fetched %d negRisk events from Gamma", len(events))
    return events


def _parse_neg_risk_events(raw_events: list[dict]) -> list[NormalizedContract]:
    """
    For each negRisk event, extract the YES token from every active market
    and return one NormalizedContract per YES token.

    In Polymarket negRisk events:
      - outcomes[0] = "Yes"  → clobTokenIds[0] = YES token ID
      - All markets are mutually exclusive; exactly one resolves to $1
    """
    now = datetime.utcnow()
    contracts: list[NormalizedContract] = []

    for event in raw_events:
        event_id = str(event.get("id") or event.get("slug", ""))
        if not event_id:
            continue

        event_title = event.get("title") or event.get("question") or "Unknown Event"
        markets = event.get("markets") or []

        # Keep only markets that are actively accepting orders
        active = [
            m for m in markets
            if m.get("acceptingOrders") and not m.get("closed")
        ]
        if len(active) < 2:
            continue  # need at least 2 outcomes for event-group arb

        for m in active:
            market_id = m.get("conditionId") or m.get("id", "")
            if not market_id:
                continue

            market_title = m.get("question") or m.get("title") or event_title

            end_date_raw = m.get("endDate") or m.get("end_date_iso") or m.get("endDateIso")
            close_time: Optional[datetime] = None
            if end_date_raw:
                try:
                    close_time = datetime.fromisoformat(
                        end_date_raw.replace("Z", "+00:00")
                    ).replace(tzinfo=None)
                except ValueError:
                    pass

            if close_time and close_time < now:
                continue

            # Extract YES token ID (index 0 in negRisk markets)
            clob_ids_raw = m.get("clobTokenIds")
            if not clob_ids_raw:
                continue
            try:
                ids = json.loads(clob_ids_raw) if isinstance(clob_ids_raw, str) else clob_ids_raw
                if not ids:
                    continue
                yes_token_id = ids[0]
            except Exception:
                continue

            contracts.append(
                NormalizedContract(
                    venue="polymarket",
                    market_id=market_id,
                    outcome_id=yes_token_id,
                    label="Yes",
                    close_time=close_time,
                    updated_at=now,
                    market_title=market_title,
                    event_id=event_id,
                    event_title=event_title,
                )
            )

    return contracts


# ─── Binary market pipeline ────────────────────────────────────────────────────

async def _fetch_binary_market_contracts(
    session: aiohttp.ClientSession,
) -> list[NormalizedContract]:
    """
    Fetch the least-competitive binary markets (most likely to be mis-priced)
    and return YES+NO contracts for intra-market arb detection.
    """
    raw_markets = await _fetch_gamma_markets_binary(session)
    contracts = _parse_gamma_markets(raw_markets)
    logger.info(
        "Binary pipeline: %d markets → %d contracts",
        len(raw_markets), len(contracts),
    )
    return contracts


async def _fetch_gamma_markets_binary(session: aiohttp.ClientSession) -> list[dict]:
    """
    Fetch binary markets sorted by competitive score ascending (least
    efficient / most mis-priced markets first) up to _BINARY_MARKET_CAP.
    """
    markets: list[dict] = []
    limit = 100
    offset = 0
    target = min(_BINARY_MARKET_CAP, settings.max_markets)

    while len(markets) < target:
        url = (
            f"{settings.gamma_base_url}/markets"
            f"?active=true&closed=false&limit={limit}&offset={offset}"
            f"&order=competitive&ascending=true"
        )
        async with session.get(url) as resp:
            if resp.status != 200:
                logger.warning("Gamma /markets (binary) returned %s", resp.status)
                break
            data = await resp.json(content_type=None)

        if not data:
            break

        markets.extend(data)
        if len(data) < limit:
            break
        offset += limit

    return markets[:target]


def _parse_gamma_markets(raw: list[dict]) -> list[NormalizedContract]:
    """
    Turn Gamma API market objects into NormalizedContract stubs (no prices yet).
    Handles both YES/NO binary and multi-outcome formats.
    """
    now = datetime.utcnow()
    contracts: list[NormalizedContract] = []

    for m in raw:
        market_id = m.get("conditionId") or m.get("id", "")
        if not market_id:
            continue

        title = m.get("question") or m.get("title") or "Unknown Market"
        end_date_raw = m.get("endDate") or m.get("end_date_iso") or m.get("endDateIso")
        close_time: Optional[datetime] = None
        if end_date_raw:
            try:
                close_time = datetime.fromisoformat(
                    end_date_raw.replace("Z", "+00:00")
                ).replace(tzinfo=None)
            except ValueError:
                pass

        if close_time and close_time < now:
            continue

        token_pairs: list[tuple[str, str]] = []

        clob_ids_raw = m.get("clobTokenIds")
        tokens_raw = m.get("tokens") or []

        if tokens_raw and isinstance(tokens_raw, list):
            for tok in tokens_raw:
                if isinstance(tok, dict):
                    tid = tok.get("token_id") or tok.get("tokenId") or ""
                    outcome = tok.get("outcome") or tok.get("label") or ""
                    if tid and outcome:
                        token_pairs.append((tid, outcome))

        if not token_pairs and clob_ids_raw:
            try:
                ids = json.loads(clob_ids_raw) if isinstance(clob_ids_raw, str) else clob_ids_raw
                outcomes_raw = m.get("outcomes")
                outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else (outcomes_raw or [])
                for i, tid in enumerate(ids):
                    label = outcomes[i] if i < len(outcomes) else f"Outcome {i+1}"
                    token_pairs.append((tid, label))
            except Exception:
                pass

        if not token_pairs:
            continue

        for token_id, outcome in token_pairs:
            contracts.append(
                NormalizedContract(
                    venue="polymarket",
                    market_id=market_id,
                    outcome_id=token_id,
                    label=outcome,
                    close_time=close_time,
                    updated_at=now,
                    market_title=title,
                    # event_id intentionally None — these are standalone binary markets
                )
            )

    return contracts


# ─── CLOB order books ─────────────────────────────────────────────────────────

async def _fetch_order_books(
    session: aiohttp.ClientSession,
    token_ids: list[str],
) -> dict[str, dict]:
    """
    Fetch order books concurrently. Returns map token_id → price/size data.

    CLOB sort order quirk: bids ascending (best bid = bids[-1]),
    asks descending (best ask = asks[-1]).
    """
    sem = asyncio.Semaphore(50)

    async def fetch_one(token_id: str) -> tuple[str, dict | None]:
        url = f"{settings.clob_base_url}/book?token_id={token_id}"
        async with sem:
            try:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        return token_id, None
                    book = await resp.json(content_type=None)
                    bids = book.get("bids") or []
                    asks = book.get("asks") or []
                    return token_id, {
                        "best_bid": float(bids[-1]["price"]) if bids else None,
                        "bid_size": float(bids[-1]["size"]) if bids else None,
                        "best_ask": float(asks[-1]["price"]) if asks else None,
                        "ask_size": float(asks[-1]["size"]) if asks else None,
                    }
            except Exception as exc:
                logger.debug("CLOB /book error for %s: %s", token_id[:12], exc)
                return token_id, None

    results_list = await asyncio.gather(*[fetch_one(tid) for tid in token_ids])
    results: dict[str, dict] = {}
    for token_id, data in results_list:
        if data is not None:
            results[token_id] = data

    logger.info("CLOB books fetched: %d/%d tokens got prices", len(results), len(token_ids))
    return results


def _apply_order_books(
    contracts: list[NormalizedContract],
    books: dict[str, dict],
) -> list[NormalizedContract]:
    """Merge order book prices into NormalizedContract list."""
    now = datetime.utcnow()
    updated = []
    for c in contracts:
        book = books.get(c.outcome_id)
        if book:
            updated.append(
                c.model_copy(
                    update={
                        "bid": book["best_bid"],
                        "ask": book["best_ask"],
                        "bid_size": book["bid_size"],
                        "ask_size": book["ask_size"],
                        "updated_at": now,
                    }
                )
            )
        else:
            updated.append(c)
    return updated


def mark_stale(
    contracts: list[NormalizedContract],
    stale_threshold_s: int,
) -> list[NormalizedContract]:
    """Mark contracts whose update is older than the stale threshold."""
    now = datetime.utcnow()
    result = []
    for c in contracts:
        age = (now - c.updated_at).total_seconds()
        result.append(c.model_copy(update={"is_stale": age > stale_threshold_s}))
    return result
