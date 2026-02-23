// ─── Market / Opportunity ──────────────────────────────────────────────────────

export interface OpportunityLeg {
  outcome_id: string;
  market_id: string;
  market_title: string;
  label: string;
  venue: string;
  ask: number;
  ask_size: number;
  bid: number;
}

export interface Opportunity {
  id: string;
  type: "intra" | "cross";
  event_title: string;
  venues: string[];
  legs: OpportunityLeg[];
  edge_pct: number;
  max_size: number;
  close_time: string | null;
  time_to_close_s: number | null;
  updated_at: string;
}

// ─── Trades ────────────────────────────────────────────────────────────────────

export interface TradeLeg {
  outcome_id: string;
  market_id: string;
  label: string;
  venue: string;
  entry_price: number;
  current_bid: number | null;
  current_ask: number | null;
  size: number;
}

export interface Trade {
  id: string;
  opportunity_snapshot: {
    id: string;
    event_title: string;
    edge_pct: number;
    total_ask: number;
    legs: OpportunityLeg[];
    captured_at: string;
  };
  legs: TradeLeg[];
  entry_cost: number;
  locked_in_payoff: number;
  size: number;
  status: "open" | "closed";
  unrealized_pnl: number | null;
  realized_pnl: number | null;
  created_at: string;
  closed_at: string | null;
}

// ─── Portfolio ─────────────────────────────────────────────────────────────────

export interface Portfolio {
  balance: number;
  realized_pnl: number;
  unrealized_pnl: number;
  total_pnl: number;
  open_trade_count: number;
}

// ─── Venue / Status ────────────────────────────────────────────────────────────

export interface VenueInfo {
  connected: boolean;
  last_update: string | null;
  stale: boolean;
  market_count: number;
  error: string | null;
}

export interface VenueStatusMap {
  polymarket: VenueInfo;
  kalshi?: VenueInfo;
}

// ─── Settings ──────────────────────────────────────────────────────────────────

export interface Settings {
  refresh_interval_s: number;
  stale_threshold_s: number;
  max_markets: number;
  min_edge_pct: number;
  starting_balance: number;
}

// ─── WebSocket ─────────────────────────────────────────────────────────────────

export interface WsUpdatePayload {
  type: "update";
  data: {
    opportunities: Opportunity[];
    venue_status: VenueStatusMap;
    portfolio: Portfolio;
  };
}
