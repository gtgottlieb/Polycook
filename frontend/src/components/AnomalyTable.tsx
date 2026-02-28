import { useState } from "react";
import { formatDistanceToNow } from "date-fns";
import type { OrderAnomaly } from "../types";

type SortKey = "severity" | "size_multiple" | "observed_size" | "detected_at";
type SortDir = "asc" | "desc";

interface Props {
  anomalies: OrderAnomaly[];
  onSelect: (anomaly: OrderAnomaly) => void;
  selectedId: string | null;
  enabled: boolean;
}

function severityRank(severity: OrderAnomaly["severity"]) {
  return { medium: 1, high: 2, critical: 3 }[severity];
}

function severityColor(severity: OrderAnomaly["severity"]) {
  if (severity === "critical") return "text-accent-red";
  if (severity === "high") return "text-accent-yellow";
  return "text-accent-green";
}

export default function AnomalyTable({ anomalies, onSelect, selectedId, enabled }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>("severity");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  function handleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir((current) => (current === "desc" ? "asc" : "desc"));
      return;
    }
    setSortKey(key);
    setSortDir("desc");
  }

  const sorted = [...anomalies].sort((a, b) => {
    let av: number;
    let bv: number;
    if (sortKey === "severity") {
      av = severityRank(a.severity);
      bv = severityRank(b.severity);
    } else if (sortKey === "size_multiple") {
      av = a.size_multiple;
      bv = b.size_multiple;
    } else if (sortKey === "observed_size") {
      av = a.observed_size;
      bv = b.observed_size;
    } else {
      av = new Date(a.detected_at).getTime();
      bv = new Date(b.detected_at).getTime();
    }
    return sortDir === "desc" ? bv - av : av - bv;
  });

  function SortIcon({ k }: { k: SortKey }) {
    if (k !== sortKey) return <span className="opacity-20">↕</span>;
    return <span>{sortDir === "desc" ? "↓" : "↑"}</span>;
  }

  if (!enabled) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-slate-500">
        <p className="text-sm">Suspicious bet detection is disabled.</p>
      </div>
    );
  }

  if (anomalies.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-slate-500">
        <p className="text-sm">No suspicious bet activity detected.</p>
        <p className="text-xs mt-1">The detector is monitoring Polymarket book changes.</p>
      </div>
    );
  }

  return (
    <div className="overflow-auto">
      <table className="w-full">
        <thead className="bg-surface-1 sticky top-0 z-10">
          <tr>
            <th className="th cursor-pointer" onClick={() => handleSort("severity")}>
              Severity <SortIcon k="severity" />
            </th>
            <th className="th">Market</th>
            <th className="th">Side</th>
            <th className="th">Price</th>
            <th className="th cursor-pointer" onClick={() => handleSort("observed_size")}>
              Signal Size <SortIcon k="observed_size" />
            </th>
            <th className="th">Baseline</th>
            <th className="th cursor-pointer" onClick={() => handleSort("size_multiple")}>
              Multiple <SortIcon k="size_multiple" />
            </th>
            <th className="th cursor-pointer" onClick={() => handleSort("detected_at")}>
              Detected <SortIcon k="detected_at" />
            </th>
            <th className="th"></th>
          </tr>
        </thead>
        <tbody className="divide-y divide-surface-2">
          {sorted.map((anomaly) => (
            <tr
              key={anomaly.id}
              onClick={() => onSelect(anomaly)}
              className={`transition-colors cursor-pointer ${
                selectedId === anomaly.id ? "bg-surface-3" : "hover:bg-surface-2"
              }`}
            >
              <td className={`td font-semibold uppercase ${severityColor(anomaly.severity)}`}>
                {anomaly.severity}
              </td>
              <td className="td max-w-xs">
                <span className="truncate block" title={anomaly.market_title}>
                  {anomaly.market_title}
                </span>
              </td>
              <td className="td text-slate-400">
                {anomaly.outcome_label} {anomaly.side}
              </td>
              <td className="td text-slate-300">{anomaly.price.toFixed(3)}</td>
              <td className="td text-white">${anomaly.observed_size.toFixed(0)}</td>
              <td className="td text-slate-400">${anomaly.baseline_size.toFixed(0)}</td>
              <td className="td text-accent-yellow">{anomaly.size_multiple.toFixed(1)}x</td>
              <td className="td text-slate-500 text-xs">
                {formatDistanceToNow(new Date(anomaly.detected_at), { addSuffix: true })}
              </td>
              <td className="td">
                <span className="text-accent-blue text-xs hover:underline">Details →</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
