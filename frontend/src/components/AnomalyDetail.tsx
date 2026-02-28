import { format } from "date-fns";
import type { OrderAnomaly } from "../types";

interface Props {
  anomaly: OrderAnomaly;
  onClose: () => void;
}

function severityColor(severity: OrderAnomaly["severity"]) {
  if (severity === "critical") return "text-accent-red";
  if (severity === "high") return "text-accent-yellow";
  return "text-accent-green";
}

export default function AnomalyDetail({ anomaly, onClose }: Props) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
      <div className="card w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div className="flex items-start justify-between p-4 border-b border-surface-3">
          <div>
            <h2 className="font-semibold text-white text-sm leading-snug max-w-sm">
              {anomaly.market_title}
            </h2>
            <p className={`text-xs mt-0.5 uppercase ${severityColor(anomaly.severity)}`}>
              {anomaly.severity} suspicious-bet alert
            </p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white ml-4 text-xl leading-none">
            ×
          </button>
        </div>

        <div className="grid grid-cols-3 gap-3 p-4 border-b border-surface-3">
          <div className="text-center">
            <p className="text-xs text-slate-500 mb-1">Signal Size</p>
            <p className="text-lg font-bold text-white">${anomaly.observed_size.toFixed(0)}</p>
          </div>
          <div className="text-center">
            <p className="text-xs text-slate-500 mb-1">Baseline</p>
            <p className="text-lg font-bold text-slate-300">${anomaly.baseline_size.toFixed(0)}</p>
          </div>
          <div className="text-center">
            <p className="text-xs text-slate-500 mb-1">Multiple</p>
            <p className="text-lg font-bold text-accent-yellow">{anomaly.size_multiple.toFixed(1)}x</p>
          </div>
        </div>

        <div className="p-4 border-b border-surface-3 space-y-3 text-xs">
          <div className="flex justify-between">
            <span className="text-slate-400">Outcome / Side</span>
            <span className="text-white">
              {anomaly.outcome_label} {anomaly.side}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-400">Price</span>
            <span className="text-white">{anomaly.price.toFixed(3)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-400">Robust z</span>
            <span className="text-white">{anomaly.robust_z.toFixed(2)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-400">Depth impact</span>
            <span className="text-white">{(anomaly.book_dominance * 100).toFixed(1)}%</span>
          </div>
          <div className="rounded bg-surface-2 p-3 text-slate-300 leading-relaxed">
            {anomaly.summary}
          </div>
          {anomaly.market_url && (
            <a
              href={anomaly.market_url}
              target="_blank"
              rel="noreferrer"
              className="inline-block text-accent-blue hover:underline"
            >
              Open market
            </a>
          )}
        </div>

        <div className="p-4 border-b border-surface-3 text-xs text-slate-500 space-y-1">
          <div className="flex justify-between">
            <span>Alert ID</span>
            <span className="font-mono">{anomaly.id}</span>
          </div>
          <div className="flex justify-between">
            <span>Detected</span>
            <span>{format(new Date(anomaly.detected_at), "MMM d, yyyy HH:mm:ss 'UTC'")}</span>
          </div>
          <div className="flex justify-between">
            <span>Updated</span>
            <span>{format(new Date(anomaly.updated_at), "HH:mm:ss")}</span>
          </div>
        </div>

        <div className="p-4 flex justify-end">
          <button onClick={onClose} className="btn-ghost">Close</button>
        </div>
      </div>
    </div>
  );
}
