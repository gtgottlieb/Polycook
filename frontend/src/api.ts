import axios from "axios";
import type { Opportunity, Portfolio, Settings, Trade } from "./types";

const http = axios.create({ baseURL: "/api" });

// ─── Opportunities ─────────────────────────────────────────────────────────────

export const fetchOpportunities = (): Promise<Opportunity[]> =>
  http.get<Opportunity[]>("/opportunities").then((r) => r.data);

export const fetchOpportunity = (id: string): Promise<Opportunity> =>
  http.get<Opportunity>(`/opportunities/${id}`).then((r) => r.data);

// ─── Trades ────────────────────────────────────────────────────────────────────

export const fetchTrades = (): Promise<Trade[]> =>
  http.get<Trade[]>("/trades").then((r) => r.data);

export const createTrade = (opportunity_id: string, size: number): Promise<Trade> =>
  http.post<Trade>("/trades", { opportunity_id, size }).then((r) => r.data);

export const closeTrade = (tradeId: string): Promise<Trade> =>
  http.put<Trade>(`/trades/${tradeId}/close`).then((r) => r.data);

// ─── Portfolio ─────────────────────────────────────────────────────────────────

export const fetchPortfolio = (): Promise<Portfolio> =>
  http.get<Portfolio>("/portfolio").then((r) => r.data);

export const resetPortfolio = (): Promise<Portfolio> =>
  http.post<Portfolio>("/portfolio/reset").then((r) => r.data);

// ─── Settings ──────────────────────────────────────────────────────────────────

export const fetchSettings = (): Promise<Settings> =>
  http.get<Settings>("/settings").then((r) => r.data);

export const updateSettings = (patch: Partial<Settings>): Promise<Settings> =>
  http.put<Settings>("/settings", patch).then((r) => r.data);
