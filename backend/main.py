"""
Polycook backend - FastAPI application entry point.
"""
from __future__ import annotations

import asyncio
import json
import logging
import traceback
from contextlib import asynccontextmanager
from datetime import datetime
from time import perf_counter
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from database import AsyncSessionLocal, init_db
from models import OrderAnomalyOut, OpportunityOut
from routers import (
    anomalies,
    opportunities,
    portfolio,
    settings as settings_router,
    trades,
)
from services import aberrant_orders, kalshi, paper_trading, polymarket
from services.detector import detect_opportunities
from state import app_state

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._connections.append(ws)
        logger.info("WS client connected (%d total)", len(self._connections))

    def disconnect(self, ws: WebSocket):
        if ws in self._connections:
            self._connections.remove(ws)
        logger.info("WS client disconnected (%d total)", len(self._connections))

    async def broadcast(self, payload: dict):
        if not self._connections:
            return
        message = json.dumps(payload, default=_json_default)
        dead: list[WebSocket] = []
        for ws in list(self._connections):
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            try:
                self._connections.remove(ws)
            except ValueError:
                pass


def _json_default(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Not serializable: {type(obj)}")


ws_manager = ConnectionManager()


async def arb_poll_loop():
    logger.info("Arbitrage loop started (interval=%ds)", settings.arb_refresh_interval_s)
    while True:
        cycle_started = perf_counter()
        try:
            if settings.enable_arb_pipeline:
                await _run_arb_cycle()
            else:
                await _handle_arb_disabled()
        except Exception:
            app_state.pipeline_status.arbitrage.running = False
            app_state.pipeline_status.arbitrage.error = traceback.format_exc().splitlines()[-1]
            logger.error("Unhandled error in arbitrage cycle:\n%s", traceback.format_exc())

        elapsed = perf_counter() - cycle_started
        sleep_for = max(0.0, settings.arb_refresh_interval_s - elapsed)
        if sleep_for > 0:
            await asyncio.sleep(sleep_for)


async def anomaly_poll_loop():
    logger.info("Aberrant order loop started (interval=%ds)", settings.anomaly_refresh_interval_s)
    while True:
        cycle_started = perf_counter()
        try:
            if settings.enable_anomaly_pipeline:
                await _run_anomaly_cycle()
            else:
                await _handle_anomaly_disabled()
        except Exception:
            app_state.pipeline_status.aberrant_orders.running = False
            app_state.pipeline_status.aberrant_orders.error = traceback.format_exc().splitlines()[-1]
            logger.error("Unhandled error in aberrant-order cycle:\n%s", traceback.format_exc())

        elapsed = perf_counter() - cycle_started
        sleep_for = max(0.0, settings.anomaly_refresh_interval_s - elapsed)
        if sleep_for > 0:
            await asyncio.sleep(sleep_for)


async def _run_arb_cycle():
    cycle_t0 = perf_counter()
    status = app_state.pipeline_status.arbitrage
    status.enabled = True
    status.running = True
    status.error = None

    fetch_t0 = perf_counter()
    poly_task = asyncio.create_task(polymarket.fetch_markets())
    kalshi_task = asyncio.create_task(kalshi.fetch_markets())
    poly_contracts, kalshi_contracts = await asyncio.gather(poly_task, kalshi_task)
    contracts = poly_contracts + kalshi_contracts
    fetch_s = perf_counter() - fetch_t0

    stale_t0 = perf_counter()
    contracts = polymarket.mark_stale(contracts, settings.stale_threshold_s)
    stale_s = perf_counter() - stale_t0

    app_state.contracts = contracts

    detect_t0 = perf_counter()
    opportunities_found = detect_opportunities(
        contracts,
        settings.min_edge_pct,
        settings.min_max_size,
    )
    app_state.opportunities = opportunities_found
    detect_s = perf_counter() - detect_t0

    status.running = False
    status.last_update = datetime.utcnow()
    status.last_duration_ms = (perf_counter() - cycle_t0) * 1000.0
    status.item_count = len(opportunities_found)

    await _broadcast_current_state()

    analyzed_markets = {(c.venue, c.market_id) for c in contracts}
    by_venue: dict[str, int] = {}
    for venue, _market_id in analyzed_markets:
        by_venue[venue] = by_venue.get(venue, 0) + 1

    logger.info(
        "Arbitrage cycle: total=%.2fs fetch=%.2fs stale=%.2fs detect=%.2fs contracts=%d markets=%d by_venue=[%s] opportunities=%d",
        status.last_duration_ms / 1000.0,
        fetch_s,
        stale_s,
        detect_s,
        len(contracts),
        len(analyzed_markets),
        ", ".join(f"{venue}:{count}" for venue, count in sorted(by_venue.items())),
        len(opportunities_found),
    )


async def _run_anomaly_cycle():
    cycle_t0 = perf_counter()
    status = app_state.pipeline_status.aberrant_orders
    status.enabled = True
    status.running = True
    status.error = None

    async with AsyncSessionLocal() as db:
        anomalies_found, metrics = await aberrant_orders.detect_aberrant_orders(db)

    app_state.anomalies = anomalies_found
    app_state.anomaly_snapshot = {
        f"{a.token_id}:{a.side}": a.model_dump()
        for a in anomalies_found
    }

    status.running = False
    status.last_update = datetime.utcnow()
    status.last_duration_ms = (perf_counter() - cycle_t0) * 1000.0
    status.item_count = len(anomalies_found)

    await _broadcast_current_state()

    logger.info(
        "Aberrant-order cycle: total=%.1fms books=%.1fms tokens=%d sides=%d candidates=%d sweep=%d wall=%d alerts=%d suppressed=%d baselines=%d",
        status.last_duration_ms or 0.0,
        metrics.get("book_fetch_ms", 0.0),
        int(metrics.get("watch_tokens", 0.0)),
        int(metrics.get("token_sides_scanned", 0.0)),
        int(metrics.get("candidate_count", 0.0)),
        int(metrics.get("sweep_candidates", 0.0)),
        int(metrics.get("wall_candidates", 0.0)),
        int(metrics.get("alerts_emitted", 0.0)),
        int(metrics.get("alerts_suppressed", 0.0)),
        int(metrics.get("baselines_updated", 0.0)),
    )


async def _handle_arb_disabled():
    status = app_state.pipeline_status.arbitrage
    status.enabled = False
    status.running = False
    status.error = None
    status.item_count = 0
    status.last_update = datetime.utcnow()
    status.last_duration_ms = 0.0
    if app_state.opportunities or app_state.contracts:
        app_state.opportunities = []
        app_state.contracts = []
        await _broadcast_current_state()


async def _handle_anomaly_disabled():
    status = app_state.pipeline_status.aberrant_orders
    status.enabled = False
    status.running = False
    status.error = None
    status.item_count = 0
    status.last_update = datetime.utcnow()
    status.last_duration_ms = 0.0
    if app_state.anomalies or app_state.anomaly_snapshot:
        app_state.anomalies = []
        app_state.anomaly_snapshot = {}
        await _broadcast_current_state()


def _venue_status_payload() -> dict[str, dict[str, Any]]:
    poly_status = polymarket.get_venue_status()
    kalshi_status = kalshi.get_venue_status()
    return {
        "polymarket": {
            "connected": poly_status.connected,
            "last_update": poly_status.last_update,
            "stale": poly_status.stale,
            "market_count": poly_status.market_count,
            "error": poly_status.error,
        },
        "kalshi": {
            "connected": kalshi_status.connected,
            "last_update": kalshi_status.last_update,
            "stale": kalshi_status.stale,
            "market_count": kalshi_status.market_count,
            "error": kalshi_status.error,
        },
    }


async def _build_broadcast_payload() -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        portfolio_summary = await paper_trading.get_portfolio_summary(
            db, app_state.contracts_by_token
        )

    return {
        "type": "update",
        "data": {
            "opportunities": [
                OpportunityOut.from_opportunity(o).model_dump()
                for o in app_state.opportunities
            ],
            "anomalies": [
                OrderAnomalyOut.from_anomaly(a).model_dump()
                for a in app_state.anomalies
            ],
            "venue_status": _venue_status_payload(),
            "pipeline_status": app_state.pipeline_status.model_dump(),
            "portfolio": portfolio_summary,
        },
    }


async def _broadcast_current_state():
    if not ws_manager._connections:
        return
    payload = await _build_broadcast_payload()
    await ws_manager.broadcast(payload)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    arb_task = asyncio.create_task(arb_poll_loop())
    anomaly_task = asyncio.create_task(anomaly_poll_loop())
    yield
    for task in (arb_task, anomaly_task):
        task.cancel()
    for task in (arb_task, anomaly_task):
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Polycook", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(opportunities.router)
app.include_router(anomalies.router)
app.include_router(trades.router)
app.include_router(portfolio.router)
app.include_router(settings_router.router)


@app.get("/api/status")
async def status():
    return {
        "venue_status": _venue_status_payload(),
        "pipeline_status": app_state.pipeline_status.model_dump(),
        "opportunity_count": len(app_state.opportunities),
        "anomaly_count": len(app_state.anomalies),
    }


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws_manager.connect(ws)
    try:
        await ws.send_text(json.dumps(await _build_broadcast_payload(), default=_json_default))
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        ws_manager.disconnect(ws)
