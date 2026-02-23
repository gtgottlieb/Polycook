import { formatDistanceToNow } from "date-fns";
import type { VenueInfo, VenueStatusMap } from "../types";

interface Props {
  venueStatus: VenueStatusMap;
  wsConnected: boolean;
  lastUpdate: Date | null;
}

function VenueChip({ name, info }: { name: string; info: VenueInfo }) {
  return (
    <div className="flex items-center gap-1.5">
      <span
        className={`w-1.5 h-1.5 rounded-full ${
          info.connected && !info.stale
            ? "bg-accent-green"
            : info.connected && info.stale
            ? "bg-accent-yellow animate-pulse"
            : "bg-accent-red animate-pulse"
        }`}
      />
      <span className="text-slate-400">{name}:</span>
      {info.connected ? (
        <>
          <span className={info.stale ? "text-accent-yellow" : "text-accent-green"}>
            {info.stale ? "stale" : "live"}
          </span>
          <span className="text-slate-500">{info.market_count} markets</span>
          {info.last_update && (
            <span className="text-slate-600">
              . {formatDistanceToNow(new Date(info.last_update), { addSuffix: true })}
            </span>
          )}
        </>
      ) : (
        <span className="text-accent-red">
          {info.error ? `error: ${info.error.slice(0, 60)}` : "disconnected"}
        </span>
      )}
    </div>
  );
}

export default function VenueStatus({ venueStatus, wsConnected, lastUpdate }: Props) {
  const poly = venueStatus.polymarket;
  const kalshi = venueStatus.kalshi;

  return (
    <div className="flex items-center gap-4 px-4 py-2 bg-surface-1 border-b border-surface-3 text-xs">
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
      <VenueChip name="Polymarket" info={poly} />

      {kalshi && (
        <>
          <span className="text-surface-3">|</span>
          <VenueChip name="Kalshi" info={kalshi} />
        </>
      )}

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
