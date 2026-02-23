import { useState } from "react";
import type { LiveState } from "../hooks/useWebSocket";
import type { Opportunity } from "../types";
import VenueStatus from "../components/VenueStatus";
import OpportunityTable from "../components/OpportunityTable";
import OpportunityDetail from "../components/OpportunityDetail";
import TradeModal from "../components/TradeModal";

interface Props {
  liveState: LiveState;
}

type Modal = { type: "detail"; opp: Opportunity } | { type: "trade"; opp: Opportunity } | null;

export default function Dashboard({ liveState }: Props) {
  const { opportunities, venueStatus, connected, lastUpdate } = liveState;
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [modal, setModal] = useState<Modal>(null);

  function handleSelectOpp(opp: Opportunity) {
    setSelectedId(opp.id);
    setModal({ type: "detail", opp });
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <VenueStatus
        venueStatus={venueStatus}
        wsConnected={connected}
        lastUpdate={lastUpdate}
      />

      {/* Header bar */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-surface-3">
        <div>
          <h1 className="text-sm font-semibold text-white">Arbitrage Scanner</h1>
          <p className="text-xs text-slate-500">
            {opportunities.length > 0
              ? `${opportunities.length} opportunit${opportunities.length === 1 ? "y" : "ies"} detected`
              : "Scanning for intra-market arbitrage…"}
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <span>Polymarket intra-market only</span>
          {connected && (
            <span className="badge bg-surface-2 text-accent-green">● Live</span>
          )}
        </div>
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto">
        <OpportunityTable
          opportunities={opportunities}
          onSelect={handleSelectOpp}
          selectedId={selectedId}
        />
      </div>

      {/* Modals */}
      {modal?.type === "detail" && (
        <OpportunityDetail
          opportunity={modal.opp}
          onClose={() => {
            setModal(null);
            setSelectedId(null);
          }}
          onTrade={() => setModal({ type: "trade", opp: modal.opp })}
        />
      )}

      {modal?.type === "trade" && (
        <TradeModal
          opportunity={modal.opp}
          onClose={() => {
            setModal(null);
            setSelectedId(null);
          }}
          onSuccess={() => {
            setModal(null);
            setSelectedId(null);
          }}
        />
      )}
    </div>
  );
}
