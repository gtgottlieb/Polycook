import { useQuery } from "@tanstack/react-query";
import { fetchTrades } from "../api";
import type { LiveState } from "../hooks/useWebSocket";
import PortfolioStats from "../components/PortfolioStats";
import { PositionsTable } from "../components/PositionsTable";
import { TradeHistory } from "../components/TradeHistory";
import VenueStatus from "../components/VenueStatus";

interface Props {
  liveState: LiveState;
}

export default function Portfolio({ liveState }: Props) {
  const { portfolio, venueStatus, connected, lastUpdate } = liveState;

  const { data: trades = [], isLoading } = useQuery({
    queryKey: ["trades"],
    queryFn: fetchTrades,
    refetchInterval: 10_000,
  });

  const openTrades = trades.filter((t) => t.status === "open");
  const closedTrades = trades.filter((t) => t.status === "closed");

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <VenueStatus
        venueStatus={venueStatus}
        wsConnected={connected}
        lastUpdate={lastUpdate}
      />

      <div className="flex-1 overflow-auto p-4 space-y-6">
        {/* Stats */}
        <section>
          <h2 className="text-xs text-slate-500 uppercase tracking-wider mb-3">
            Account Summary
          </h2>
          <PortfolioStats portfolio={portfolio} />
        </section>

        {/* Open positions */}
        <section>
          <h2 className="text-xs text-slate-500 uppercase tracking-wider mb-3">
            Open Positions ({openTrades.length})
          </h2>
          {isLoading ? (
            <div className="card p-8 text-center text-slate-500 text-sm animate-pulse">
              Loading…
            </div>
          ) : (
            <PositionsTable trades={trades} />
          )}
        </section>

        {/* Trade history */}
        <section>
          <h2 className="text-xs text-slate-500 uppercase tracking-wider mb-3">
            Trade History ({closedTrades.length})
          </h2>
          {isLoading ? (
            <div className="card p-8 text-center text-slate-500 text-sm animate-pulse">
              Loading…
            </div>
          ) : (
            <TradeHistory trades={trades} />
          )}
        </section>
      </div>
    </div>
  );
}
