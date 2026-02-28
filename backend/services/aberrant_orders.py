"""
Polymarket suspicious-bet detector.

This pipeline is sweep-first: it watches consecutive order-book snapshots for
large visible depth being consumed and price stepping through the book. The
older resting-wall detector remains available as an optional secondary signal.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Literal, Optional
from urllib.parse import quote

import aiohttp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models import OrderAnomaly, OrderAnomalyEvent, OrderSizeBaseline

logger = logging.getLogger(__name__)

_market_cache: list["_WatchToken"] = []
_market_cache_refreshed_at: Optional[datetime] = None
_baseline_cache_loaded = False
_baseline_cache: dict[tuple[str, str], "_BaselineState"] = {}
_cooldown_cache: dict[tuple[str, str], "_CooldownState"] = {}
_book_snapshot_cache: dict[str, "_BookSnapshot"] = {}

_SIDE_LEVELS = {
    "bid": "bids",
    "ask": "asks",
}


@dataclass(frozen=True)
class _WatchToken:
    market_id: str
    market_title: str
    market_url: Optional[str]
    token_id: str
    outcome_label: str
    relevance: float


@dataclass
class _BaselineState:
    token_id: str
    side: str
    market_id: str
    market_title: str
    market_url: Optional[str]
    sample_count: int = 0
    ema_size: float = 0.0
    ema_abs_dev: float = 0.0
    last_observed_size: Optional[float] = None
    last_observed_price: Optional[float] = None
    last_seen_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @property
    def warm(self) -> bool:
        return self.sample_count >= settings.anomaly_min_samples


@dataclass
class _CooldownState:
    detected_at: datetime
    observed_size: float
    price: float
    severity_rank: int


@dataclass(frozen=True)
class _BookSnapshot:
    bid_price: Optional[float]
    bid_size: Optional[float]
    ask_price: Optional[float]
    ask_size: Optional[float]
    bid_depth: float
    ask_depth: float
    spread: Optional[float]


@dataclass(frozen=True)
class _Candidate:
    signal_kind: Literal["sweep", "wall"]
    token: _WatchToken
    side: str
    price: float
    observed_size: float
    baseline_size: float
    baseline_dev: float
    baseline_sample_count: int
    fast_score: float
    levels: list[dict]
    spread: Optional[float]
    price_move: float = 0.0
    depth_ratio: float = 0.0


async def detect_aberrant_orders(db: AsyncSession) -> tuple[list[OrderAnomaly], dict[str, float]]:
    await _ensure_baseline_cache(db)

    cycle_started = datetime.utcnow()
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        watch_t0 = datetime.utcnow()
        watch_tokens = await _get_watch_tokens(session)
        books = await _fetch_raw_books(session, [t.token_id for t in watch_tokens])
        book_fetch_ms = (datetime.utcnow() - watch_t0).total_seconds() * 1000.0

    candidates: list[_Candidate] = []
    dirty_baselines: dict[tuple[str, str], _BaselineState] = {}
    token_sides_scanned = 0
    sweep_candidates = 0
    wall_candidates = 0

    for token in watch_tokens:
        raw_book = books.get(token.token_id)
        if raw_book is None:
            continue

        snapshot = _build_book_snapshot(raw_book)
        previous = _book_snapshot_cache.get(token.token_id)

        for side in ("bid", "ask"):
            token_sides_scanned += 1
            current_price = _side_price(snapshot, side)
            reference_price = current_price
            if reference_price is None and previous is not None:
                reference_price = _side_price(previous, side)
            if reference_price is None or not _is_price_in_band(reference_price):
                continue

            key = (token.token_id, side)
            baseline = _baseline_cache.get(key) or _BaselineState(
                token_id=token.token_id,
                side=side,
                market_id=token.market_id,
                market_title=token.market_title,
                market_url=token.market_url,
            )

            if settings.anomaly_enable_sweep_detection and previous is not None:
                sweep_candidate = _build_sweep_candidate(
                    token=token,
                    side=side,
                    baseline=baseline,
                    current=snapshot,
                    previous=previous,
                    current_levels=raw_book.get(_SIDE_LEVELS[side]) or [],
                )
                if sweep_candidate is not None:
                    candidates.append(sweep_candidate)
                    sweep_candidates += 1

            if settings.anomaly_enable_wall_detection and current_price is not None:
                current_size = _side_size(snapshot, side)
                if current_size is not None:
                    wall_candidate = _build_wall_candidate(
                        token=token,
                        side=side,
                        baseline=baseline,
                        price=current_price,
                        observed_size=current_size,
                        levels=raw_book.get(_SIDE_LEVELS[side]) or [],
                        spread=snapshot.spread,
                    )
                    if wall_candidate is not None:
                        candidates.append(wall_candidate)
                        wall_candidates += 1

            current_size = _side_size(snapshot, side)
            if current_price is None or current_size is None or current_size <= 0:
                continue

            updated = _update_baseline_state(
                baseline=baseline,
                observed_size=current_size,
                price=current_price,
                token=token,
                side=side,
                now=cycle_started,
            )
            _baseline_cache[key] = updated
            dirty_baselines[key] = updated

        _book_snapshot_cache[token.token_id] = snapshot

    candidates.sort(key=lambda c: (c.fast_score, c.observed_size, c.token.market_id), reverse=True)
    if len(candidates) > settings.anomaly_max_candidates_per_cycle:
        dropped = len(candidates) - settings.anomaly_max_candidates_per_cycle
        logger.info("Aberrant orders: dropping %d excess candidates", dropped)
        candidates = candidates[:settings.anomaly_max_candidates_per_cycle]

    anomalies: list[OrderAnomaly] = []
    emitted_events: list[OrderAnomalyEvent] = []
    suppressed = 0
    for candidate in candidates:
        if candidate.signal_kind == "sweep":
            anomaly = _score_sweep_candidate(candidate, now=cycle_started)
        else:
            anomaly = _score_wall_candidate(candidate, now=cycle_started)
        if anomaly is None:
            continue
        if _is_suppressed_by_cooldown(anomaly):
            suppressed += 1
            continue

        anomalies.append(anomaly)
        emitted_events.append(_event_from_anomaly(anomaly))
        _cooldown_cache[(anomaly.token_id, anomaly.side)] = _CooldownState(
            detected_at=anomaly.detected_at,
            observed_size=anomaly.observed_size,
            price=anomaly.price,
            severity_rank=_severity_rank(anomaly.severity),
        )

    await _flush_baselines(db, dirty_baselines.values())
    if emitted_events:
        db.add_all(emitted_events)
        await db.commit()

    total_ms = (datetime.utcnow() - cycle_started).total_seconds() * 1000.0
    metrics = {
        "watch_tokens": float(len(watch_tokens)),
        "token_sides_scanned": float(token_sides_scanned),
        "candidate_count": float(len(candidates)),
        "sweep_candidates": float(sweep_candidates),
        "wall_candidates": float(wall_candidates),
        "alerts_emitted": float(len(anomalies)),
        "alerts_suppressed": float(suppressed),
        "baselines_updated": float(len(dirty_baselines)),
        "book_fetch_ms": book_fetch_ms,
        "total_ms": total_ms,
    }
    logger.info(
        "Aberrant orders: tokens=%d sides=%d candidates=%d sweep=%d wall=%d alerts=%d suppressed=%d baselines=%d total=%.1fms",
        len(watch_tokens),
        token_sides_scanned,
        len(candidates),
        sweep_candidates,
        wall_candidates,
        len(anomalies),
        suppressed,
        len(dirty_baselines),
        total_ms,
    )
    return anomalies, metrics


async def list_recent_events(db: AsyncSession, limit: int = 100) -> list[OrderAnomalyEvent]:
    result = await db.execute(
        select(OrderAnomalyEvent)
        .order_by(OrderAnomalyEvent.detected_at.desc())
        .limit(max(1, min(500, limit)))
    )
    return list(result.scalars().all())


async def get_event_by_id(db: AsyncSession, anomaly_id: str) -> Optional[OrderAnomalyEvent]:
    result = await db.execute(
        select(OrderAnomalyEvent).where(OrderAnomalyEvent.id == anomaly_id).limit(1)
    )
    return result.scalar_one_or_none()


async def _ensure_baseline_cache(db: AsyncSession) -> None:
    global _baseline_cache_loaded
    if _baseline_cache_loaded:
        return

    result = await db.execute(select(OrderSizeBaseline))
    rows = result.scalars().all()
    for row in rows:
        _baseline_cache[(row.token_id, row.side)] = _BaselineState(
            token_id=row.token_id,
            side=row.side,
            market_id=row.market_id,
            market_title=row.market_title,
            market_url=row.market_url,
            sample_count=row.sample_count,
            ema_size=row.ema_size,
            ema_abs_dev=row.ema_abs_dev,
            last_observed_size=row.last_observed_size,
            last_observed_price=row.last_observed_price,
            last_seen_at=row.last_seen_at,
            updated_at=row.updated_at,
        )
    _baseline_cache_loaded = True


async def _get_watch_tokens(session: aiohttp.ClientSession) -> list[_WatchToken]:
    global _market_cache, _market_cache_refreshed_at
    now = datetime.utcnow()
    refresh_needed = (
        _market_cache_refreshed_at is None
        or not _market_cache
        or (now - _market_cache_refreshed_at).total_seconds() >= settings.metadata_refresh_interval_s
    )
    if refresh_needed:
        raw_markets = await _fetch_gamma_markets_binary(session)
        _market_cache = _parse_watch_tokens(raw_markets)
        _market_cache_refreshed_at = now
    return _market_cache[: settings.anomaly_max_markets]


async def _fetch_gamma_markets_binary(session: aiohttp.ClientSession) -> list[dict]:
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
                logger.warning("Gamma /markets (anomaly) returned %s", resp.status)
                break
            data = await resp.json(content_type=None)

        if not data:
            break

        markets.extend([m for m in data if _is_yes_no_market(m)])
        if len(data) < limit:
            break
        offset += limit

    return markets


def _parse_watch_tokens(raw_markets: list[dict]) -> list[_WatchToken]:
    tokens: list[_WatchToken] = []
    for market in raw_markets:
        market_id = str(market.get("conditionId") or market.get("id") or "")
        if not market_id:
            continue

        market_title = market.get("question") or market.get("title") or "Unknown Market"
        market_url = _build_market_url(market)
        token_pairs = _extract_token_pairs(market)
        if not token_pairs:
            continue

        relevance = _market_relevance(market)
        for token_id, outcome_label in token_pairs:
            tokens.append(
                _WatchToken(
                    market_id=market_id,
                    market_title=market_title,
                    market_url=market_url,
                    token_id=token_id,
                    outcome_label=outcome_label,
                    relevance=relevance,
                )
            )

    tokens.sort(key=lambda t: (t.relevance, t.market_id, t.token_id), reverse=True)
    return tokens


async def _fetch_raw_books(
    session: aiohttp.ClientSession,
    token_ids: list[str],
) -> dict[str, dict]:
    if not token_ids:
        return {}

    batch_size = max(25, min(1000, settings.clob_books_batch_size))
    batch_sem = asyncio.Semaphore(8)
    batch_url = f"{settings.clob_base_url}/books"

    async def fetch_batch(batch_ids: list[str]) -> dict[str, dict]:
        payload = [{"token_id": tid} for tid in batch_ids]
        async with batch_sem:
            try:
                async with session.post(batch_url, json=payload) as resp:
                    if resp.status != 200:
                        return {}
                    data = await resp.json(content_type=None)
            except Exception:
                return {}

        results: dict[str, dict] = {}
        if not isinstance(data, list):
            return results
        for raw in data:
            if not isinstance(raw, dict):
                continue
            token_id = str(raw.get("asset_id") or raw.get("token_id") or "")
            if token_id:
                results[token_id] = raw
        return results

    chunks = [token_ids[i : i + batch_size] for i in range(0, len(token_ids), batch_size)]
    chunk_results = await asyncio.gather(*[fetch_batch(chunk) for chunk in chunks])

    results: dict[str, dict] = {}
    for item in chunk_results:
        results.update(item)

    missing_ids = [tid for tid in token_ids if tid not in results][:400]
    if missing_ids:
        fallback_results = await asyncio.gather(
            *[_fetch_single_book(session, tid) for tid in missing_ids]
        )
        for token_id, data in zip(missing_ids, fallback_results):
            if data is not None:
                results[token_id] = data

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
            return await resp.json(content_type=None)
    except Exception:
        return None


def _build_book_snapshot(raw_book: dict) -> _BookSnapshot:
    bids = raw_book.get("bids") or []
    asks = raw_book.get("asks") or []

    bid_price, bid_size = _best_level(bids, side="bid")
    ask_price, ask_size = _best_level(asks, side="ask")

    spread = None
    if bid_price is not None and ask_price is not None:
        spread = max(0.0, ask_price - bid_price)

    return _BookSnapshot(
        bid_price=bid_price,
        bid_size=bid_size,
        ask_price=ask_price,
        ask_size=ask_size,
        bid_depth=_sum_top_n(bids, 3),
        ask_depth=_sum_top_n(asks, 3),
        spread=spread,
    )


def _build_sweep_candidate(
    token: _WatchToken,
    side: str,
    baseline: _BaselineState,
    current: _BookSnapshot,
    previous: _BookSnapshot,
    current_levels: list[dict],
) -> Optional[_Candidate]:
    previous_price = _side_price(previous, side)
    if previous_price is None:
        return None

    current_price = _side_price(current, side)
    effective_price = current_price
    if effective_price is None:
        effective_price = 0.0 if side == "bid" else 1.0

    spread = current.spread if current.spread is not None else previous.spread
    if spread is None or spread > settings.anomaly_max_spread:
        return None

    previous_size = _side_size(previous, side) or 0.0
    current_size = _side_size(current, side) or 0.0
    if previous_size <= 0:
        return None

    previous_depth = _side_depth(previous, side)
    current_depth = _side_depth(current, side)
    estimated_fill = max(previous_size - current_size, previous_depth - current_depth, 0.0)
    if estimated_fill < settings.anomaly_min_sweep_fill_size:
        return None

    if side == "ask":
        price_move = effective_price - previous_price
    else:
        price_move = previous_price - effective_price
    if price_move < settings.anomaly_min_sweep_price_move:
        return None

    depth_ratio = estimated_fill / max(previous_depth, 1.0)
    if depth_ratio < settings.anomaly_min_sweep_depth_ratio:
        return None

    baseline_floor = max(
        baseline.ema_size,
        settings.anomaly_min_sweep_fill_size,
        1.0,
    )
    fast_score = (
        (estimated_fill / baseline_floor)
        + (price_move * 20.0)
        + (depth_ratio * 8.0)
    )

    return _Candidate(
        signal_kind="sweep",
        token=token,
        side=side,
        price=effective_price,
        observed_size=estimated_fill,
        baseline_size=baseline.ema_size,
        baseline_dev=baseline.ema_abs_dev,
        baseline_sample_count=baseline.sample_count,
        fast_score=fast_score,
        levels=current_levels,
        spread=spread,
        price_move=price_move,
        depth_ratio=depth_ratio,
    )


def _build_wall_candidate(
    token: _WatchToken,
    side: str,
    baseline: _BaselineState,
    price: float,
    observed_size: float,
    levels: list[dict],
    spread: Optional[float],
) -> Optional[_Candidate]:
    fast_score = _candidate_fast_score(observed_size=observed_size, baseline=baseline)
    if fast_score is None:
        return None

    return _Candidate(
        signal_kind="wall",
        token=token,
        side=side,
        price=price,
        observed_size=observed_size,
        baseline_size=baseline.ema_size,
        baseline_dev=baseline.ema_abs_dev,
        baseline_sample_count=baseline.sample_count,
        fast_score=fast_score,
        levels=levels,
        spread=spread,
    )


def _candidate_fast_score(observed_size: float, baseline: _BaselineState) -> Optional[float]:
    if observed_size <= 0 or observed_size < settings.anomaly_candidate_min_size:
        return None

    if baseline.warm:
        threshold = max(
            baseline.ema_size * settings.anomaly_candidate_multiplier,
            baseline.ema_size + settings.anomaly_candidate_abs_excess,
        )
        if observed_size < threshold:
            return None
        baseline_floor = max(baseline.ema_size, 1.0)
        return max(
            observed_size / baseline_floor,
            (observed_size - baseline.ema_size)
            / max(1.0, baseline.ema_abs_dev, settings.anomaly_candidate_abs_excess / 2.0),
        )

    if (
        baseline.sample_count >= settings.anomaly_bootstrap_min_samples
        and observed_size >= settings.anomaly_absolute_min_wall_size
    ):
        return observed_size / max(settings.anomaly_absolute_min_wall_size, 1.0)
    return None


def _update_baseline_state(
    baseline: _BaselineState,
    observed_size: float,
    price: float,
    token: _WatchToken,
    side: str,
    now: datetime,
) -> _BaselineState:
    prev_ema = baseline.ema_size
    alpha = settings.anomaly_alpha
    if baseline.sample_count == 0:
        ema_size = observed_size
        ema_abs_dev = 0.0
    else:
        ema_size = (alpha * observed_size) + ((1.0 - alpha) * baseline.ema_size)
        ema_abs_dev = (alpha * abs(observed_size - prev_ema)) + (
            (1.0 - alpha) * baseline.ema_abs_dev
        )

    return _BaselineState(
        token_id=baseline.token_id,
        side=side,
        market_id=token.market_id,
        market_title=token.market_title,
        market_url=token.market_url,
        sample_count=baseline.sample_count + 1,
        ema_size=ema_size,
        ema_abs_dev=ema_abs_dev,
        last_observed_size=observed_size,
        last_observed_price=price,
        last_seen_at=now,
        updated_at=now,
    )


def _score_sweep_candidate(candidate: _Candidate, now: datetime) -> Optional[OrderAnomaly]:
    baseline_size = max(candidate.baseline_size, 1.0)
    baseline_dev = max(candidate.baseline_dev, 1.0)
    size_multiple = candidate.observed_size / baseline_size
    robust_z = (candidate.observed_size - candidate.baseline_size) / baseline_dev
    book_dominance = min(1.0, candidate.depth_ratio)

    if candidate.baseline_sample_count < settings.anomaly_min_samples:
        if (
            candidate.baseline_sample_count < settings.anomaly_bootstrap_min_samples
            and candidate.observed_size < settings.anomaly_absolute_min_wall_size
        ):
            return None
        robust_z = max(robust_z, settings.anomaly_alert_robust_z)
        size_multiple = max(
            size_multiple,
            candidate.observed_size / max(settings.anomaly_absolute_min_wall_size, 1.0),
        )

    if (
        size_multiple < settings.anomaly_alert_size_multiple
        or robust_z < settings.anomaly_alert_robust_z
        or candidate.observed_size < settings.anomaly_min_sweep_fill_size
    ):
        return None

    spread_bonus = 0.0
    if candidate.spread is not None:
        spread_bonus = max(0.0, settings.anomaly_max_spread - candidate.spread) * 20.0
    score = (
        (size_multiple * 0.35)
        + (robust_z * 0.20)
        + (book_dominance * 4.0)
        + min(candidate.observed_size / 2_000.0, 3.5)
        + min(candidate.price_move * 24.0, 5.0)
        + spread_bonus
    )
    severity = _severity_from_score(score)

    direction = "aggressive buy" if candidate.side == "ask" else "aggressive sell"
    summary = (
        f"{severity.upper()} {direction}: est. {candidate.observed_size:,.0f} swept "
        f"through {candidate.side}s, {candidate.side} moved {candidate.price_move:.3f} "
        f"to {candidate.price:.3f} ({size_multiple:.1f}x normal, z={robust_z:.1f})"
    )

    return OrderAnomaly(
        id=_build_anomaly_id(candidate, now),
        market_id=candidate.token.market_id,
        token_id=candidate.token.token_id,
        market_title=candidate.token.market_title,
        market_url=candidate.token.market_url,
        outcome_label=candidate.token.outcome_label,
        side=candidate.side,  # type: ignore[arg-type]
        price=candidate.price,
        observed_size=candidate.observed_size,
        baseline_size=candidate.baseline_size,
        size_multiple=size_multiple,
        robust_z=robust_z,
        book_dominance=book_dominance,
        severity=severity,
        summary=summary,
        detected_at=now,
        updated_at=now,
    )


def _score_wall_candidate(candidate: _Candidate, now: datetime) -> Optional[OrderAnomaly]:
    baseline_size = max(candidate.baseline_size, 1.0)
    baseline_dev = max(candidate.baseline_dev, 1.0)
    size_multiple = candidate.observed_size / baseline_size
    robust_z = (candidate.observed_size - candidate.baseline_size) / baseline_dev
    top_three_same_side = _sum_top_n(candidate.levels, 3)
    book_dominance = candidate.observed_size / max(top_three_same_side, candidate.observed_size)

    if candidate.baseline_sample_count < settings.anomaly_min_samples:
        if (
            candidate.baseline_sample_count < settings.anomaly_bootstrap_min_samples
            or candidate.observed_size < settings.anomaly_absolute_min_wall_size
        ):
            return None
        robust_z = max(robust_z, settings.anomaly_alert_robust_z)
        size_multiple = max(
            size_multiple,
            candidate.observed_size / max(settings.anomaly_absolute_min_wall_size, 1.0),
        )

    if (
        size_multiple < settings.anomaly_alert_size_multiple
        or robust_z < settings.anomaly_alert_robust_z
        or candidate.observed_size < 500.0
    ):
        return None

    spread_bonus = 0.0
    if candidate.spread is not None:
        spread_bonus = max(0.0, settings.anomaly_max_spread - candidate.spread) * 16.0
    score = (
        (size_multiple * 0.45)
        + (robust_z * 0.30)
        + (book_dominance * 2.5)
        + min(candidate.observed_size / 2_000.0, 3.0)
        + spread_bonus
    )
    severity = _severity_from_score(score)

    summary = (
        f"{severity.upper()} resting wall: {candidate.observed_size:,.0f} @ "
        f"{candidate.price:.3f} vs baseline {candidate.baseline_size:,.0f} "
        f"({size_multiple:.1f}x, z={robust_z:.1f})"
    )

    return OrderAnomaly(
        id=_build_anomaly_id(candidate, now),
        market_id=candidate.token.market_id,
        token_id=candidate.token.token_id,
        market_title=candidate.token.market_title,
        market_url=candidate.token.market_url,
        outcome_label=candidate.token.outcome_label,
        side=candidate.side,  # type: ignore[arg-type]
        price=candidate.price,
        observed_size=candidate.observed_size,
        baseline_size=candidate.baseline_size,
        size_multiple=size_multiple,
        robust_z=robust_z,
        book_dominance=book_dominance,
        severity=severity,
        summary=summary,
        detected_at=now,
        updated_at=now,
    )


def _build_anomaly_id(candidate: _Candidate, now: datetime) -> str:
    return hashlib.md5(
        f"{candidate.signal_kind}:{candidate.token.token_id}:{candidate.side}:{now.isoformat()}".encode()
    ).hexdigest()[:16]


def _is_suppressed_by_cooldown(anomaly: OrderAnomaly) -> bool:
    state = _cooldown_cache.get((anomaly.token_id, anomaly.side))
    if state is None:
        return False
    if (anomaly.detected_at - state.detected_at).total_seconds() > settings.anomaly_cooldown_s:
        return False

    size_ratio = anomaly.observed_size / max(state.observed_size, 1.0)
    size_close = 0.8 <= size_ratio <= 1.2
    price_close = abs(anomaly.price - state.price) <= 0.01
    if not (size_close and price_close):
        return False

    return _severity_rank(anomaly.severity) <= state.severity_rank


async def _flush_baselines(
    db: AsyncSession,
    baselines: Iterable[_BaselineState],
) -> None:
    rows = list(baselines)
    if not rows:
        return

    for baseline in rows:
        await db.merge(
            OrderSizeBaseline(
                token_id=baseline.token_id,
                side=baseline.side,
                market_id=baseline.market_id,
                market_title=baseline.market_title,
                market_url=baseline.market_url,
                venue="polymarket",
                sample_count=baseline.sample_count,
                ema_size=baseline.ema_size,
                ema_abs_dev=baseline.ema_abs_dev,
                last_observed_size=baseline.last_observed_size,
                last_observed_price=baseline.last_observed_price,
                last_seen_at=baseline.last_seen_at or datetime.utcnow(),
                updated_at=baseline.updated_at or datetime.utcnow(),
            )
        )
    await db.commit()


def _event_from_anomaly(anomaly: OrderAnomaly) -> OrderAnomalyEvent:
    return OrderAnomalyEvent(
        id=anomaly.id,
        token_id=anomaly.token_id,
        market_id=anomaly.market_id,
        market_title=anomaly.market_title,
        market_url=anomaly.market_url,
        side=anomaly.side,
        price=anomaly.price,
        observed_size=anomaly.observed_size,
        baseline_size=anomaly.baseline_size,
        size_multiple=anomaly.size_multiple,
        robust_z=anomaly.robust_z,
        book_dominance=anomaly.book_dominance,
        severity=anomaly.severity,
        outcome_label=anomaly.outcome_label,
        summary=anomaly.summary,
        detected_at=anomaly.detected_at,
        expires_at=anomaly.detected_at + timedelta(seconds=settings.anomaly_cooldown_s),
        acknowledged=False,
    )


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

        if size <= 0:
            continue

        if side == "bid":
            better = best_price is None or price > best_price
        else:
            better = best_price is None or price < best_price

        if better:
            best_price = price
            best_size = size

    return best_price, best_size


def _sum_top_n(levels: list, count: int) -> float:
    sizes: list[float] = []
    for level in levels:
        if not isinstance(level, dict):
            continue
        try:
            size = float(level.get("size"))
        except (TypeError, ValueError):
            continue
        if size > 0:
            sizes.append(size)
        if len(sizes) >= count:
            break
    return float(sum(sizes))


def _side_price(snapshot: _BookSnapshot, side: str) -> Optional[float]:
    return snapshot.bid_price if side == "bid" else snapshot.ask_price


def _side_size(snapshot: _BookSnapshot, side: str) -> Optional[float]:
    return snapshot.bid_size if side == "bid" else snapshot.ask_size


def _side_depth(snapshot: _BookSnapshot, side: str) -> float:
    return snapshot.bid_depth if side == "bid" else snapshot.ask_depth


def _severity_from_score(score: float) -> Literal["medium", "high", "critical"]:
    if score >= 12.0:
        return "critical"
    if score >= 8.0:
        return "high"
    return "medium"


def _severity_rank(severity: str) -> int:
    return {"medium": 1, "high": 2, "critical": 3}.get(severity, 0)


def _is_price_in_band(price: float) -> bool:
    return settings.anomaly_min_price <= price <= settings.anomaly_max_price


def _extract_token_pairs(market: dict) -> list[tuple[str, str]]:
    token_pairs: list[tuple[str, str]] = []
    tokens_raw = market.get("tokens") or []
    if isinstance(tokens_raw, list):
        for token in tokens_raw:
            if not isinstance(token, dict):
                continue
            token_id = token.get("token_id") or token.get("tokenId") or ""
            label = token.get("outcome") or token.get("label") or ""
            if token_id and label:
                token_pairs.append((str(token_id), str(label)))

    if token_pairs:
        return token_pairs

    clob_ids_raw = market.get("clobTokenIds")
    if not clob_ids_raw:
        return []
    try:
        ids = json.loads(clob_ids_raw) if isinstance(clob_ids_raw, str) else clob_ids_raw
        outcomes_raw = market.get("outcomes")
        outcomes = (
            json.loads(outcomes_raw)
            if isinstance(outcomes_raw, str)
            else (outcomes_raw or [])
        )
    except Exception:
        return []

    if not isinstance(ids, list):
        return []

    for idx, token_id in enumerate(ids):
        label = outcomes[idx] if idx < len(outcomes) else f"Outcome {idx + 1}"
        token_pairs.append((str(token_id), str(label)))
    return token_pairs


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


def _market_relevance(market: dict) -> float:
    def _f(value: object) -> float:
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0

    liquidity = max(
        _f(market.get("liquidity")),
        _f(market.get("liquidityNum")),
        _f(market.get("liquidityClob")),
        _f(market.get("liquidityAmm")),
    )
    volume = max(
        _f(market.get("volume")),
        _f(market.get("volume24hr")),
        _f(market.get("volume24hrClob")),
        _f(market.get("volume24hrAmm")),
    )
    return liquidity + (volume * 0.5)


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
