"""
Polymarket API client.

Strategy:
  1. negRisk events  - fetch ALL active negRisk events from Gamma /events.
     Each event groups mutually-exclusive binary markets (e.g. "Who wins the
     Stanley Cup?").  We extract the YES token from every market in the event
     and check Î£ ask(YES_i) < 1.0 for event-group arb.

  2. Binary markets  - fetch all active YES/NO binary markets sorted by
     competitive score and evaluate intra-market/cross-venue opportunities.

Both passes fetch CLOB order books concurrently for accurate bid/ask/sizes.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
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

_metadata_cache: list[NormalizedContract] = []
_metadata_refreshed_at: Optional[datetime] = None
_TEMPORAL_LADDER_SPLIT_RE = re.compile(
    r"\b(on or before|at or before|before|by)\b",
    re.IGNORECASE,
)


def get_venue_status() -> VenueStatus:
    return _venue_status


async def fetch_markets() -> list[NormalizedContract]:
    """
    Main entry point. Returns a flat list of NormalizedContract, one per
    outcome token, combining negRisk event YES-legs and binary market legs.
    """
    global _venue_status, _metadata_cache, _metadata_refreshed_at
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30)
        ) as session:
            now = datetime.utcnow()
            refresh_needed = (
                _metadata_refreshed_at is None
                or not _metadata_cache
                or (now - _metadata_refreshed_at).total_seconds() >= settings.metadata_refresh_interval_s
            )

            if refresh_needed:
                event_task = asyncio.create_task(_fetch_neg_risk_event_contracts(session))
                binary_task = asyncio.create_task(_fetch_binary_market_contracts(session))
                event_contracts, binary_contracts = await asyncio.gather(event_task, binary_task)
                _metadata_cache = event_contracts + binary_contracts
                _metadata_refreshed_at = now
                logger.info(
                    "Metadata refresh complete: %d contracts (events=%d, binary=%d)",
                    len(_metadata_cache),
                    len(event_contracts),
                    len(binary_contracts),
                )
            else:
                cache_age = (now - _metadata_refreshed_at).total_seconds() if _metadata_refreshed_at else 0.0
                logger.info(
                    "Metadata cache hit: %d contracts (age=%.1fs)",
                    len(_metadata_cache),
                    cache_age,
                )

            if not _metadata_cache:
                _venue_status = VenueStatus(
                    connected=True,
                    last_update=datetime.utcnow(),
                    stale=False,
                    market_count=0,
                )
                return []

            all_contracts = [c.model_copy() for c in _metadata_cache]
            token_ids = list(dict.fromkeys(c.outcome_id for c in all_contracts))
            books = await _fetch_order_books(session, token_ids)
            all_contracts = _apply_order_books(all_contracts, books)

        snapshot_time = datetime.utcnow()
        event_ids = {c.event_id for c in all_contracts if c.event_id}
        market_ids = {c.market_id for c in all_contracts if not c.event_id}
        event_contract_count = sum(1 for c in all_contracts if c.event_id)
        binary_contract_count = len(all_contracts) - event_contract_count
        logger.info(
            "Fetch complete: %d event-group contracts (%d events) + %d binary contracts (%d markets)",
            event_contract_count,
            len(event_ids),
            binary_contract_count,
            len(market_ids),
        )
        _venue_status = VenueStatus(
            connected=True,
            last_update=snapshot_time,
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


# â”€â”€â”€ negRisk event pipeline â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

async def _fetch_neg_risk_event_contracts(
    session: aiohttp.ClientSession,
) -> list[NormalizedContract]:
    """Fetch negRisk events and return one YES-token contract per active market."""
    raw_events = await _fetch_gamma_events(session)
    contracts = _parse_neg_risk_events(raw_events)
    logger.info(
        "negRisk pipeline: %d events â†’ %d YES-token contracts",
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
      - outcomes[0] = "Yes"  â†’ clobTokenIds[0] = YES token ID
      - All markets are mutually exclusive; exactly one resolves to $1
    """
    now = datetime.utcnow()
    contracts: list[NormalizedContract] = []

    for event in raw_events:
        # Gamma's negRisk query filter is not reliable by itself.
        # Keep only events explicitly flagged as negRisk/exclusive.
        if not event.get("negRisk"):
            continue

        event_id = str(event.get("id") or event.get("slug", ""))
        if not event_id:
            continue

        event_title = event.get("title") or event.get("question") or "Unknown Event"
        markets = event.get("markets") or []

        # Keep only open markets that are tradable and explicitly negRisk.
        active = []
        for m in markets:
            if m.get("closed"):
                continue
            if not m.get("acceptingOrders"):
                continue
            if m.get("negRisk") is False:
                continue
            active.append(m)

        if len(active) < 2:
            continue  # need at least 2 outcomes for event-group arb

        # Temporal ladders ("by Jan", "by Feb", "by Mar") are overlapping YES
        # predicates and cannot be treated as a guaranteed one-pays-$1 basket.
        if _is_temporal_ladder(active):
            logger.info(
                "Skipping overlapping temporal ladder event: %s (%s)",
                event_title,
                event_id,
            )
            continue

        for m in active:
            market_id = m.get("conditionId") or m.get("id", "")
            if not market_id:
                continue

            market_title = m.get("question") or m.get("title") or event_title
            market_url = _build_market_url(m)

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
                    market_url=market_url,
                    event_id=event_id,
                    event_title=event_title,
                )
            )

    return contracts


def _is_temporal_ladder(markets: list[dict]) -> bool:
    """
    Detect overlapping time-threshold market sets like:
      "Will X happen by Jan 31?"
      "Will X happen by Feb 28?"
    These YES outcomes can resolve true simultaneously.
    """
    stems: list[str] = []
    for m in markets:
        question = (m.get("question") or m.get("title") or "").strip()
        if not question:
            return False
        stem = _extract_temporal_stem(question)
        if stem is None:
            return False
        stems.append(stem)

    return len(stems) >= 2 and len(set(stems)) == 1


def _extract_temporal_stem(question: str) -> Optional[str]:
    q = " ".join(question.lower().split()).strip(" ?")
    match = _TEMPORAL_LADDER_SPLIT_RE.search(q)
    if match is None:
        return None

    stem = q[:match.start()].strip()
    if stem.startswith("will "):
        stem = stem[5:].strip()
    return stem or None


# â”€â”€â”€ Binary market pipeline â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

async def _fetch_binary_market_contracts(
    session: aiohttp.ClientSession,
) -> list[NormalizedContract]:
    """
    Fetch all active binary markets and return YES+NO contracts for
    intra-market and cross-venue arb detection.
    """
    raw_markets = await _fetch_gamma_markets_binary(session)
    contracts = _parse_gamma_markets(raw_markets)
    logger.info(
        "Binary pipeline: %d markets â†’ %d contracts",
        len(raw_markets), len(contracts),
    )
    return contracts


async def _fetch_gamma_markets_binary(session: aiohttp.ClientSession) -> list[dict]:
    """
    Fetch all active binary markets sorted by competitive score ascending.
    """
    markets: list[dict] = []
    limit = 100
    offset = 0

    while True:
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

        yes_no_page = [m for m in data if _is_yes_no_market(m)]
        markets.extend(yes_no_page)
        if len(data) < limit:
            break
        offset += limit

    return markets


def _is_yes_no_market(market: dict) -> bool:
    outcomes_raw = market.get("outcomes")
    outcomes = (
        json.loads(outcomes_raw)
        if isinstance(outcomes_raw, str)
        else (outcomes_raw or [])
    )
    if not isinstance(outcomes, list) or len(outcomes) != 2:
        return False
    labels = {str(x).strip().lower() for x in outcomes}
    return labels == {"yes", "no"}


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
        market_url = _build_market_url(m)
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
                    market_url=market_url,
                    # event_id intentionally None â€” these are standalone binary markets
                )
            )

    return contracts


# â”€â”€â”€ CLOB order books â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

async def _fetch_order_books(
    session: aiohttp.ClientSession,
    token_ids: list[str],
) -> dict[str, dict]:
    """
    Fetch order books using CLOB /books batched POSTs with single-token
    fallback for misses. Returns map token_id -> price/size data.
    """
    if not token_ids:
        return {}

    batch_size = max(25, min(1000, settings.clob_books_batch_size))
    batch_sem = asyncio.Semaphore(8)
    batch_url = f"{settings.clob_base_url}/books"

    async def fetch_batch(batch_ids: list[str]) -> dict[str, dict]:
        payload = [{"token_id": tid} for tid in batch_ids]
        results: dict[str, dict] = {}

        async with batch_sem:
            try:
                async with session.post(batch_url, json=payload) as resp:
                    if resp.status != 200:
                        return {}
                    data = await resp.json(content_type=None)
            except Exception:
                return {}

        if not isinstance(data, list):
            return {}

        for raw in data:
            if not isinstance(raw, dict):
                continue
            token_id = str(raw.get("asset_id") or raw.get("token_id") or "")
            if not token_id:
                continue
            parsed = _parse_book_snapshot(raw)
            if parsed is not None:
                results[token_id] = parsed

        return results

    chunks = [token_ids[i:i + batch_size] for i in range(0, len(token_ids), batch_size)]
    chunk_results = await asyncio.gather(*[fetch_batch(chunk) for chunk in chunks])

    results: dict[str, dict] = {}
    for item in chunk_results:
        results.update(item)

    missing_ids = [tid for tid in token_ids if tid not in results]
    if missing_ids:
        # Keep fallback bounded so a partially-throttled batch call does not
        # stall an entire cycle on thousands of single-token requests.
        fallback_ids = missing_ids[:400]
        fallback_results = await asyncio.gather(*[
            _fetch_single_book(session, tid) for tid in fallback_ids
        ])
        for token_id, data in zip(fallback_ids, fallback_results):
            if data is not None:
                results[token_id] = data

    logger.info("CLOB books fetched: %d/%d tokens got prices", len(results), len(token_ids))
    return results


async def _fetch_single_book(
    session: aiohttp.ClientSession,
    token_id: str,
) -> Optional[dict]:
    url = f"{settings.clob_base_url}/book?token_id={token_id}"
    try:
        async with session.get(url) as resp:
            if resp.status != 200:
                return None
            book = await resp.json(content_type=None)
            return _parse_book_snapshot(book)
    except Exception as exc:
        logger.debug("CLOB /book error for %s: %s", token_id[:12], exc)
        return None


def _parse_book_snapshot(book: dict) -> Optional[dict]:
    bids = book.get("bids") or []
    asks = book.get("asks") or []
    best_bid, bid_size = _best_level(bids, side="bid")
    best_ask, ask_size = _best_level(asks, side="ask")

    if best_bid is None and best_ask is None:
        return None

    return {
        "best_bid": best_bid,
        "bid_size": bid_size,
        "best_ask": best_ask,
        "ask_size": ask_size,
    }


def _best_level(levels: list, side: str) -> tuple[Optional[float], Optional[float]]:
    best_price: Optional[float] = None
    best_size: Optional[float] = None

    for level in levels:
        if not isinstance(level, dict):
            continue
        try:
            price = float(level.get("price"))
            size = float(level.get("size"))
        except (TypeError, ValueError):
            continue

        if side == "bid":
            better = best_price is None or price > best_price
        else:
            better = best_price is None or price < best_price

        if better:
            best_price = price
            best_size = size

    return best_price, best_size

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


def _build_market_url(market: dict) -> Optional[str]:
    market_slug = market.get("market_slug") or market.get("slug")

    events = market.get("events") or []
    event_slug: Optional[str] = None
    if isinstance(events, list):
        for event in events:
            if not isinstance(event, dict):
                continue
            raw_event_slug = event.get("slug") or event.get("event_slug")
            if raw_event_slug:
                event_slug = str(raw_event_slug)
                break

    if market_slug:
        market_slug = str(market_slug)
        if event_slug and event_slug != market_slug:
            return (
                "https://polymarket.com/event/"
                f"{quote(event_slug, safe='')}/{quote(market_slug, safe='')}"
            )
        return f"https://polymarket.com/market/{quote(market_slug, safe='')}"

    if event_slug:
        return f"https://polymarket.com/event/{quote(event_slug, safe='')}"

    return None


