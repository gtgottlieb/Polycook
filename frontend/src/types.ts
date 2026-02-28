// ─── Market / Opportunity ──────────────────────────────────────────────────────

export interface OpportunityLeg {
  outcome_id: string;
  market_id: string;
  market_title: string;
  market_url?: string | null;
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

export interface OrderAnomaly {
  id: string;
  market_id: string;
  token_id: string;
  market_title: string;
  market_url?: string | null;
  outcome_label: string;
  side: "bid" | "ask";
  price: number;
  observed_size: number;
  baseline_size: number;
  size_multiple: number;
  robust_z: number;
  book_dominance: number;
  severity: "medium" | "high" | "critical";
  summary: string;
  detected_at: string;
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

export interface PipelineStatus {
  enabled: boolean;
  running: boolean;
  last_update: string | null;
  last_duration_ms: number | null;
  item_count: number;
  error: string | null;
}

export interface PipelineStatusMap {
  arbitrage: PipelineStatus;
  aberrant_orders: PipelineStatus;
}

// ─── Settings ──────────────────────────────────────────────────────────────────

export interface Settings {
  refresh_interval_s: number;
  arb_refresh_interval_s: number;
  anomaly_refresh_interval_s: number;
  stale_threshold_s: number;
  max_markets: number;
  anomaly_max_markets: number;
  min_edge_pct: number;
  min_max_size: number;
  enable_arb_pipeline: boolean;
  enable_anomaly_pipeline: boolean;
  anomaly_enable_sweep_detection: boolean;
  anomaly_enable_wall_detection: boolean;
  anomaly_candidate_min_size: number;
  anomaly_candidate_multiplier: number;
  anomaly_candidate_abs_excess: number;
  anomaly_min_sweep_price_move: number;
  anomaly_min_sweep_fill_size: number;
  anomaly_min_sweep_depth_ratio: number;
  anomaly_max_spread: number;
  anomaly_min_samples: number;
  anomaly_bootstrap_min_samples: number;
  anomaly_alpha: number;
  anomaly_alert_size_multiple: number;
  anomaly_alert_robust_z: number;
  anomaly_absolute_min_wall_size: number;
  anomaly_min_price: number;
  anomaly_max_price: number;
  anomaly_cooldown_s: number;
  anomaly_max_candidates_per_cycle: number;
  starting_balance: number;
}

// ─── WebSocket ─────────────────────────────────────────────────────────────────

export interface WsUpdatePayload {
  type: "update";
  data: {
    opportunities: Opportunity[];
    anomalies: OrderAnomaly[];
    venue_status: VenueStatusMap;
    pipeline_status: PipelineStatusMap;
    portfolio: Portfolio;
  };
}
