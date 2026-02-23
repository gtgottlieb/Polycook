import { format } from "date-fns";
import type { Opportunity } from "../types";

interface Props {
  opportunity: Opportunity;
  onTrade: () => void;
  onClose: () => void;
}

export default function OpportunityDetail({ opportunity, onTrade, onClose }: Props) {
  const opp = opportunity;
  const totalAsk = opp.legs.reduce((s, l) => s + l.ask, 0);
  const edgePct = (opp.edge_pct * 100).toFixed(3);
  const lockedPayoff = 1.0;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
      <div className="card w-full max-w-lg max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-start justify-between p-4 border-b border-surface-3">
          <div>
            <h2 className="font-semibold text-white text-sm leading-snug max-w-sm">
              {opp.event_title}
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">
              {opp.type === "intra" ? "Intra-Market" : "Cross-Market"} ·{" "}
              {opp.venues.join(" / ")}
            </p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white ml-4 text-xl leading-none">
            ×
          </button>
        </div>

        {/* Summary */}
        <div className="grid grid-cols-3 gap-3 p-4 border-b border-surface-3">
          <div className="text-center">
            <p className="text-xs text-slate-500 mb-1">Edge</p>
            <p className="text-lg font-bold text-accent-green">{edgePct}%</p>
          </div>
          <div className="text-center">
            <p className="text-xs text-slate-500 mb-1">Max Size</p>
            <p className="text-lg font-bold text-white">${opp.max_size.toFixed(0)}</p>
          </div>
          <div className="text-center">
            <p className="text-xs text-slate-500 mb-1">Locked Payoff</p>
            <p className="text-lg font-bold text-white">${lockedPayoff.toFixed(2)}/unit</p>
          </div>
        </div>

        {/* Calculation */}
        <div className="p-4 border-b border-surface-3">
          <h3 className="text-xs text-slate-500 uppercase tracking-wider mb-3">
            Calculation
          </h3>
          <div className="space-y-2">
            {opp.legs.map((leg) => (
              <div key={leg.outcome_id} className="flex items-center justify-between text-xs gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="badge bg-surface-2 text-slate-300">{leg.label}</span>
                    <span className="text-slate-400 capitalize">{leg.venue}</span>
                  </div>
                  <p className="text-slate-300 mt-1 truncate" title={leg.market_title}>
                    {leg.market_title}
                  </p>
                </div>
                <div className="flex items-center gap-4 text-right">
                  <div>
                    <span className="text-slate-500">bid </span>
                    <span className="text-slate-300">{leg.bid.toFixed(3)}</span>
                  </div>
                  <div>
                    <span className="text-slate-500">ask </span>
                    <span className="text-white font-medium">{leg.ask.toFixed(3)}</span>
                  </div>
                  <div>
                    <span className="text-slate-500">avail </span>
                    <span className="text-slate-300">${leg.ask_size.toFixed(0)}</span>
                  </div>
                </div>
              </div>
            ))}

            <div className="border-t border-surface-3 pt-2 mt-2 flex justify-between text-xs font-medium">
              <span className="text-slate-400">Total ask (cost per unit)</span>
              <span className="text-white">{totalAsk.toFixed(4)}</span>
            </div>
            <div className="flex justify-between text-xs font-medium">
              <span className="text-slate-400">Locked-in profit per unit</span>
              <span className="text-accent-green">{(1 - totalAsk).toFixed(4)}</span>
            </div>
            <div className="flex justify-between text-xs font-medium">
              <span className="text-slate-400">Max executable size</span>
              <span className="text-white">
                ${opp.max_size.toFixed(2)}
              </span>
            </div>
            <div className="flex justify-between text-xs font-medium">
              <span className="text-slate-400">Max locked-in profit</span>
              <span className="text-accent-green">
                ${((1 - totalAsk) * opp.max_size).toFixed(2)}
              </span>
            </div>
          </div>
        </div>

        {/* Metadata */}
        <div className="p-4 border-b border-surface-3 text-xs text-slate-500 space-y-1">
          <div className="flex justify-between">
            <span>Opportunity ID</span>
            <span className="font-mono">{opp.id}</span>
          </div>
          {opp.close_time && (
            <div className="flex justify-between">
              <span>Market closes</span>
              <span>{format(new Date(opp.close_time), "MMM d, yyyy HH:mm 'UTC'")}</span>
            </div>
          )}
          <div className="flex justify-between">
            <span>Last updated</span>
            <span>{format(new Date(opp.updated_at), "HH:mm:ss")}</span>
          </div>
        </div>

        {/* Action */}
        <div className="p-4 flex justify-end gap-2">
          <button onClick={onClose} className="btn-ghost">Cancel</button>
          <button onClick={onTrade} className="btn-success">
            Paper Trade This →
          </button>
        </div>
      </div>
    </div>
  );
}
