import { useEffect, useRef, useState, useCallback } from "react";
import type { Opportunity, Portfolio, VenueStatusMap, WsUpdatePayload } from "../types";

export interface LiveState {
  opportunities: Opportunity[];
  venueStatus: VenueStatusMap;
  portfolio: Portfolio | null;
  connected: boolean;
  lastUpdate: Date | null;
}

const DEFAULT_VENUE_STATUS: VenueStatusMap = {
  polymarket: {
    connected: false,
    last_update: null,
    stale: true,
    market_count: 0,
    error: null,
  },
};

export function useWebSocket(): LiveState {
  const [state, setState] = useState<LiveState>({
    opportunities: [],
    venueStatus: DEFAULT_VENUE_STATUS,
    portfolio: null,
    connected: false,
    lastUpdate: null,
  });

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);

  const connect = useCallback(() => {
    if (!mountedRef.current) return;

    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const wsUrl = `${protocol}://${window.location.host}/ws`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      if (!mountedRef.current) return;
      setState((prev) => ({ ...prev, connected: true }));
    };

    ws.onmessage = (event: MessageEvent) => {
      if (!mountedRef.current) return;
      try {
        const msg: WsUpdatePayload = JSON.parse(event.data as string);
        if (msg.type === "update") {
          setState({
            opportunities: msg.data.opportunities,
            venueStatus: msg.data.venue_status,
            portfolio: msg.data.portfolio,
            connected: true,
            lastUpdate: new Date(),
          });
        }
      } catch {
        // ignore parse errors
      }
    };

    ws.onerror = () => {
      ws.close();
    };

    ws.onclose = () => {
      if (!mountedRef.current) return;
      setState((prev) => ({ ...prev, connected: false }));
      // Reconnect after 3 seconds
      reconnectTimer.current = setTimeout(() => {
        if (mountedRef.current) connect();
      }, 3_000);
    };
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    connect();
    return () => {
      mountedRef.current = false;
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return state;
}
