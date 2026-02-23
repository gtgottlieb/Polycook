import { formatDistanceToNow } from "date-fns";
import type { VenueStatusMap } from "../types";

interface Props {
  venueStatus: VenueStatusMap;
  wsConnected: boolean;
  lastUpdate: Date | null;
}

export default function VenueStatus({ venueStatus, wsConnected, lastUpdate }: Props) {
  const poly = venueStatus.polymarket;

  return (
    <div className="flex items-center gap-4 px-4 py-2 bg-surface-1 border-b border-surface-3 text-xs">
      {/* WebSocket */}
      <div className="flex items-center gap-1.5">
        <span
          className={`w-1.5 h-1.5 rounded-full ${
            wsConnected ? "bg-accent-green" : "bg-accent-red animate-pulse"
          }`}
        />
        <span className="text-slate-400">WS:</span>
        <span className={wsConnected ? "text-accent-green" : "text-accent-red"}>
          {wsConnected ? "connected" : "disconnected"}
        </span>
      </div>

      <span className="text-surface-3">|</span>

      {/* Polymarket */}
      <div className="flex items-center gap-1.5">
        <span
          className={`w-1.5 h-1.5 rounded-full ${
            poly.connected && !poly.stale
              ? "bg-accent-green"
              : poly.connected && poly.stale
              ? "bg-accent-yellow animate-pulse"
              : "bg-accent-red animate-pulse"
          }`}
        />
        <span className="text-slate-400">Polymarket:</span>
        {poly.connected ? (
          <>
            <span className={poly.stale ? "text-accent-yellow" : "text-accent-green"}>
              {poly.stale ? "stale" : "live"}
            </span>
            <span className="text-slate-500">
              {poly.market_count} markets
            </span>
            {poly.last_update && (
              <span className="text-slate-600">
                · {formatDistanceToNow(new Date(poly.last_update), { addSuffix: true })}
              </span>
            )}
          </>
        ) : (
          <span className="text-accent-red">
            {poly.error ? `error: ${poly.error.slice(0, 60)}` : "disconnected"}
          </span>
        )}
      </div>

      {lastUpdate && (
        <>
          <span className="text-surface-3">|</span>
          <span className="text-slate-600">
            refreshed {formatDistanceToNow(lastUpdate, { addSuffix: true })}
          </span>
        </>
      )}
    </div>
  );
}
