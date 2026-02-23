"""
Polycook backend - FastAPI application entry point.

Responsibilities:
  - Mount all REST routers
  - WebSocket broadcast endpoint
  - Background polling task (market data → arb detection → WS broadcast)
"""
from __future__ import annotations

import asyncio
import json
import logging
import traceback
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from database import init_db, AsyncSessionLocal
from models import OpportunityOut
from routers import opportunities, trades, portfolio, settings as settings_router
from services import polymarket
from services.detector import detect_opportunities
from services import paper_trading
from state import app_state

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ─── WebSocket connection manager ─────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._connections.append(ws)
        logger.info("WS client connected (%d total)", len(self._connections))

    def disconnect(self, ws: WebSocket):
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


# ─── Background poller ─────────────────────────────────────────────────────────

async def poll_loop():
    """Continuously fetch market data, detect arb, update state, broadcast."""
    logger.info("Poll loop started (interval=%ds)", settings.refresh_interval_s)
    while True:
        try:
            await _run_poll_cycle()
        except Exception:
            logger.error("Unhandled error in poll cycle:\n%s", traceback.format_exc())
        await asyncio.sleep(settings.refresh_interval_s)


async def _run_poll_cycle():
    # 1. Fetch market data
    contracts = await polymarket.fetch_markets()

    # 2. Mark stale
    from services.polymarket import mark_stale
    contracts = mark_stale(contracts, settings.stale_threshold_s)

    # 3. Update global state
    app_state.contracts = contracts

    # 4. Detect arbitrage
    opportunities = detect_opportunities(contracts, settings.min_edge_pct)
    app_state.opportunities = opportunities

    # 5. Compute portfolio summary with updated prices
    async with AsyncSessionLocal() as db:
        portfolio_summary = await paper_trading.get_portfolio_summary(
            db, app_state.contracts_by_token
        )

    # 6. Build broadcast payload
    venue_status = polymarket.get_venue_status()
    payload = {
        "type": "update",
        "data": {
            "opportunities": [
                OpportunityOut.from_opportunity(o).model_dump()
                for o in opportunities
            ],
            "venue_status": {
                "polymarket": {
                    "connected": venue_status.connected,
                    "last_update": venue_status.last_update,
                    "stale": venue_status.stale,
                    "market_count": venue_status.market_count,
                    "error": venue_status.error,
                }
            },
            "portfolio": portfolio_summary,
        },
    }

    await ws_manager.broadcast(payload)

    logger.info(
        "Cycle: %d contracts, %d opportunities, %d WS clients",
        len(contracts),
        len(opportunities),
        len(ws_manager._connections),
    )


# ─── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    task = asyncio.create_task(poll_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


# ─── App setup ─────────────────────────────────────────────────────────────────

app = FastAPI(title="Polycook", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(opportunities.router)
app.include_router(trades.router)
app.include_router(portfolio.router)
app.include_router(settings_router.router)


@app.get("/api/status")
async def status():
    vs = polymarket.get_venue_status()
    return {
        "venue_status": {
            "polymarket": {
                "connected": vs.connected,
                "last_update": vs.last_update,
                "stale": vs.stale,
                "market_count": vs.market_count,
                "error": vs.error,
            }
        },
        "opportunity_count": len(app_state.opportunities),
    }


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws_manager.connect(ws)
    try:
        # Send current state immediately on connect
        if app_state.contracts:
            async with AsyncSessionLocal() as db:
                portfolio_summary = await paper_trading.get_portfolio_summary(
                    db, app_state.contracts_by_token
                )
            vs = polymarket.get_venue_status()
            await ws.send_text(
                json.dumps(
                    {
                        "type": "update",
                        "data": {
                            "opportunities": [
                                OpportunityOut.from_opportunity(o).model_dump()
                                for o in app_state.opportunities
                            ],
                            "venue_status": {
                                "polymarket": {
                                    "connected": vs.connected,
                                    "last_update": vs.last_update,
                                    "stale": vs.stale,
                                    "market_count": vs.market_count,
                                    "error": vs.error,
                                }
                            },
                            "portfolio": portfolio_summary,
                        },
                    },
                    default=_json_default,
                )
            )
        # Keep alive - client drives disconnection
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        ws_manager.disconnect(ws)
