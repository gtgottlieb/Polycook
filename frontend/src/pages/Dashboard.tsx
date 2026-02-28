import { useEffect, useState } from "react";
import type { LiveState } from "../hooks/useWebSocket";
import type { Opportunity, OrderAnomaly } from "../types";
import VenueStatus from "../components/VenueStatus";
import OpportunityTable from "../components/OpportunityTable";
import OpportunityDetail from "../components/OpportunityDetail";
import TradeModal from "../components/TradeModal";
import PipelineToggles from "../components/PipelineToggles";
import AnomalyTable from "../components/AnomalyTable";
import AnomalyDetail from "../components/AnomalyDetail";

interface Props {
  liveState: LiveState;
}

type TabKey = "arbitrage" | "anomalies";
type Modal =
  | { type: "opp-detail"; opp: Opportunity }
  | { type: "opp-trade"; opp: Opportunity }
  | { type: "anomaly-detail"; anomaly: OrderAnomaly }
  | null;

export default function Dashboard({ liveState }: Props) {
  const { opportunities, anomalies, pipelineStatus, venueStatus, connected, lastUpdate } = liveState;
  const [activeTab, setActiveTab] = useState<TabKey>(
    pipelineStatus.arbitrage.enabled ? "arbitrage" : "anomalies"
  );
  const [selectedOppId, setSelectedOppId] = useState<string | null>(null);
  const [selectedAnomalyId, setSelectedAnomalyId] = useState<string | null>(null);
  const [modal, setModal] = useState<Modal>(null);

  useEffect(() => {
    if (activeTab === "arbitrage" && pipelineStatus.arbitrage.enabled) return;
    if (activeTab === "anomalies" && pipelineStatus.aberrant_orders.enabled) return;
    if (pipelineStatus.arbitrage.enabled) {
      setActiveTab("arbitrage");
    } else if (pipelineStatus.aberrant_orders.enabled) {
      setActiveTab("anomalies");
    }
  }, [activeTab, pipelineStatus]);

  function handleSelectOpp(opp: Opportunity) {
    setSelectedOppId(opp.id);
    setModal({ type: "opp-detail", opp });
  }

  function handleSelectAnomaly(anomaly: OrderAnomaly) {
    setSelectedAnomalyId(anomaly.id);
    setModal({ type: "anomaly-detail", anomaly });
  }

  const activeCount = activeTab === "arbitrage" ? opportunities.length : anomalies.length;
  const headerText =
    activeTab === "arbitrage"
      ? pipelineStatus.arbitrage.enabled
        ? activeCount > 0
          ? `${activeCount} arbitrage opportunit${activeCount === 1 ? "y" : "ies"} detected`
          : "Scanning Polymarket and Kalshi for arbitrage…"
        : "Arbitrage pipeline disabled"
      : pipelineStatus.aberrant_orders.enabled
      ? activeCount > 0
        ? `${activeCount} suspicious order alert${activeCount === 1 ? "" : "s"} detected`
        : "Scanning Polymarket for aberrant resting orders…"
      : "Aberrant order pipeline disabled";

  function tabClass(tab: TabKey) {
    const isActive = activeTab === tab;
    return `px-3 py-1.5 rounded text-xs font-medium transition-colors ${
      isActive ? "bg-surface-2 text-white" : "text-slate-400 hover:text-slate-200 hover:bg-surface-2"
    }`;
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <VenueStatus
        venueStatus={venueStatus}
        wsConnected={connected}
        lastUpdate={lastUpdate}
      />

      <div className="flex flex-col gap-3 px-4 py-3 border-b border-surface-3">
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
          <div>
            <h1 className="text-sm font-semibold text-white">Scanners</h1>
            <p className="text-xs text-slate-500">{headerText}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
            <PipelineToggles pipelineStatus={pipelineStatus} />
            {connected && (
              <span className="badge bg-surface-2 text-accent-green">● Live</span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button onClick={() => setActiveTab("arbitrage")} className={tabClass("arbitrage")}>
            Arbitrage ({pipelineStatus.arbitrage.item_count})
          </button>
          <button onClick={() => setActiveTab("anomalies")} className={tabClass("anomalies")}>
            Aberrant Orders ({pipelineStatus.aberrant_orders.item_count})
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-auto">
        {activeTab === "arbitrage" ? (
          pipelineStatus.arbitrage.enabled ? (
            <OpportunityTable
              opportunities={opportunities}
              onSelect={handleSelectOpp}
              selectedId={selectedOppId}
            />
          ) : (
            <div className="flex flex-col items-center justify-center py-20 text-slate-500">
              <p className="text-sm">Arbitrage detection is disabled.</p>
            </div>
          )
        ) : (
          <AnomalyTable
            anomalies={anomalies}
            onSelect={handleSelectAnomaly}
            selectedId={selectedAnomalyId}
            enabled={pipelineStatus.aberrant_orders.enabled}
          />
        )}
      </div>

      {modal?.type === "opp-detail" && (
        <OpportunityDetail
          opportunity={modal.opp}
          onClose={() => {
            setModal(null);
            setSelectedOppId(null);
          }}
          onTrade={() => setModal({ type: "opp-trade", opp: modal.opp })}
        />
      )}

      {modal?.type === "opp-trade" && (
        <TradeModal
          opportunity={modal.opp}
          onClose={() => {
            setModal(null);
            setSelectedOppId(null);
          }}
          onSuccess={() => {
            setModal(null);
            setSelectedOppId(null);
          }}
        />
      )}

      {modal?.type === "anomaly-detail" && (
        <AnomalyDetail
          anomaly={modal.anomaly}
          onClose={() => {
            setModal(null);
            setSelectedAnomalyId(null);
          }}
        />
      )}
    </div>
  );
}
