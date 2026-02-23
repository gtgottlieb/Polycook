"""
Polymarket API client.

Fetches active markets from the Gamma API, then retrieves order books
from the CLOB API concurrently (one /book call per token) to get best
bid/ask and sizes per token.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
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


def get_venue_status() -> VenueStatus:
    return _venue_status


async def fetch_markets() -> list[NormalizedContract]:
    """
    Main entry point. Returns a flat list of NormalizedContract, one per
    outcome token across all active Polymarket markets.
    """
    global _venue_status
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=20)
        ) as session:
            raw_markets = await _fetch_gamma_markets(session)
            if not raw_markets:
                _venue_status = VenueStatus(
                    connected=True,
                    last_update=datetime.utcnow(),
                    stale=False,
                    market_count=0,
                )
                return []

            contracts = _parse_gamma_markets(raw_markets)
            if not contracts:
                return []

            token_ids = [c.outcome_id for c in contracts]
            books = await _fetch_order_books(session, token_ids)

            contracts = _apply_order_books(contracts, books)

        now = datetime.utcnow()
        _venue_status = VenueStatus(
            connected=True,
            last_update=now,
            stale=False,
            market_count=len({c.market_id for c in contracts}),
        )
        return contracts

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


async def _fetch_gamma_markets(session: aiohttp.ClientSession) -> list[dict]:
    """Fetch active markets from Gamma API with pagination."""
    markets: list[dict] = []
    limit = 100
    offset = 0
    target = settings.max_markets

    while len(markets) < target:
        url = (
            f"{settings.gamma_base_url}/markets"
            f"?active=true&closed=false&limit={limit}&offset={offset}"
            f"&order=volume24hrClob&ascending=false"
        )
        async with session.get(url) as resp:
            if resp.status != 200:
                logger.warning("Gamma API returned %s", resp.status)
                break
            data = await resp.json(content_type=None)

        if not data:
            break

        markets.extend(data)
        if len(data) < limit:
            break  # last page
        offset += limit

    return markets[:target]


def _parse_gamma_markets(raw: list[dict]) -> list[NormalizedContract]:
    """
    Turn Gamma API market objects into NormalizedContract stubs (no prices yet).

    Gamma market fields we use:
      - conditionId   (str)  – market identifier
      - question      (str)  – market title
      - endDate       (str)  – ISO 8601 close time
      - clobTokenIds  (str)  – JSON-encoded list of token ID strings
      - tokens        (list) – [{tokenId, outcome}]  (optional fallback)
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
                ).replace(tzinfo=None)  # store as naive UTC
            except ValueError:
                pass

        # Skip markets that have already closed
        if close_time and close_time < now:
            continue

        # Get token IDs and outcome labels
        token_pairs: list[tuple[str, str]] = []  # (token_id, outcome_label)

        clob_ids_raw = m.get("clobTokenIds")
        tokens_raw = m.get("tokens") or []

        # Prefer the tokens array as it has both id and outcome label
        if tokens_raw and isinstance(tokens_raw, list):
            for tok in tokens_raw:
                if isinstance(tok, dict):
                    tid = tok.get("token_id") or tok.get("tokenId") or ""
                    outcome = tok.get("outcome") or tok.get("label") or ""
                    if tid and outcome:
                        token_pairs.append((tid, outcome))

        # Fallback: clobTokenIds array + outcomes list
        if not token_pairs and clob_ids_raw:
            try:
                import json
                if isinstance(clob_ids_raw, str):
                    ids = json.loads(clob_ids_raw)
                else:
                    ids = clob_ids_raw
                outcomes_raw = m.get("outcomes")
                if isinstance(outcomes_raw, str):
                    outcomes = json.loads(outcomes_raw)
                else:
                    outcomes = outcomes_raw or []
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
                )
            )

    return contracts


async def _fetch_order_books(
    session: aiohttp.ClientSession,
    token_ids: list[str],
) -> dict[str, dict]:
    """
    Fetch order books concurrently from CLOB API using individual /book calls.
    The batch /books endpoint is not functional; concurrent singles are fast
    and well within the 1500 req/10s rate limit.

    Returns map token_id → {best_bid, best_ask, bid_size, ask_size}.
    """
    results: dict[str, dict] = {}
    sem = asyncio.Semaphore(50)  # max 50 in-flight at once

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
                    # Polymarket CLOB sorts bids ascending and asks descending,
                    # so best bid = bids[-1] (highest) and best ask = asks[-1] (lowest).
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
