# Polycook - Arbitrage Tracker & Paper Trading Engine

A live arbitrage scanner that continuously detects Polymarket intra-market mispricings, displays them in a clean dashboard, and allows realistic paper trading with real-time P&L tracking.

**No real trades are ever executed.**

---

## Features (v0)

- **Live Arbitrage Scanner** - detects when `ask(YES) + ask(NO) < 1.0` on Polymarket binary markets, and `Σ ask(i) < 1.0` for multi-outcome markets
- **Kalshi Integration** - ingests open Kalshi YES/NO markets each cycle
- **Cross-Platform Arb Checks** - checks `ask(YES @ Venue A) + ask(NO @ Venue B) < 1.0` for matched markets across venues
- **Real-time Updates** - WebSocket push from backend on every poll cycle
- **Paper Trading** - simulate entering and closing arbitrage positions with locked-in profit tracking
- **Live P&L** - positions marked to market continuously with live bid prices
- **Portfolio View** - balance, realized P&L, unrealized P&L, trade history

---

## Stack

| Layer | Tech |
|---|---|
| Backend | Python 3.11 · FastAPI · SQLite (SQLAlchemy async) |
| Real-time | FastAPI WebSocket |
| Frontend | React 18 · TypeScript · Vite · Tailwind CSS |

---

## Setup & Run

### Requirements
- Python 3.11+
- Node.js 18+

### Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

The backend starts polling Polymarket and Kalshi immediately. SQLite database is created at `backend/data/polycook.db`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**. Vite proxies `/api` and `/ws` to the backend on port 8000.

---

## Configuration

Settings can be adjusted at runtime via the backend API (`PUT /api/settings`) or by editing environment variables / `.env` file in `backend/`:

| Setting | Default | Description |
|---|---|---|
| `REFRESH_INTERVAL_S` | `8` | Seconds between market data polls |
| `STALE_THRESHOLD_S` | `30` | Seconds before a quote is marked stale |
| `MAX_MARKETS` | `300` | Max markets fetched per cycle |
| `MIN_EDGE_PCT` | `0.001` | Minimum edge (0.1%) to surface an opportunity |
| `STARTING_BALANCE` | `10000` | Starting paper balance in USD |

---

## API

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/opportunities` | Current arbitrage opportunities |
| `GET` | `/api/status` | Venue connection status |
| `GET` | `/api/trades` | All paper trades |
| `POST` | `/api/trades` | Create paper trade `{opportunity_id, size}` |
| `PUT` | `/api/trades/{id}/close` | Close paper trade |
| `GET` | `/api/portfolio` | Portfolio summary |
| `POST` | `/api/portfolio/reset` | Reset paper account |
| `GET` | `/api/settings` | Current settings |
| `PUT` | `/api/settings` | Update settings |
| `WS` | `/ws` | Real-time broadcast |

---

## Architecture

```
Every N seconds:
  Gamma API → market listings (title, tokens, close time)
  CLOB API  → batch order books (best bid/ask/size per token)
  Detector  → ask_YES + ask_NO < 1.0?
  Engine    → update open trade P&L
  WebSocket → broadcast to all connected clients
```

Data flow is read-only with respect to the exchanges. The app never sends orders, connects trading credentials, or signs transactions.

---

## Arbitrage Math

For a binary Polymarket market:
- **Entry**: Buy YES @ ask(YES) + Buy NO @ ask(NO)
- **Cost**: ask(YES) + ask(NO) < $1.00
- **Payoff**: exactly $1.00 at resolution (one pays $1, other $0)
- **Edge**: `1 - (ask(YES) + ask(NO))`

For multi-outcome markets the same logic extends to all outcomes.
