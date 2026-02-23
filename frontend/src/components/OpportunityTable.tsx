import { useState } from "react";
import { formatDistanceToNow, formatDuration, intervalToDuration } from "date-fns";
import type { Opportunity } from "../types";

type SortKey = "edge_pct" | "max_size" | "time_to_close_s" | "updated_at";
type SortDir = "asc" | "desc";

interface Props {
  opportunities: Opportunity[];
  onSelect: (opp: Opportunity) => void;
  selectedId: string | null;
}

function fmtPct(v: number) {
  return `${(v * 100).toFixed(2)}%`;
}

function fmtSize(v: number) {
  return v >= 1000 ? `${(v / 1000).toFixed(1)}k` : v.toFixed(0);
}

function fmtTime(seconds: number | null) {
  if (seconds === null) return "-";
  if (seconds < 0) return "expired";
  const d = intervalToDuration({ start: 0, end: seconds * 1000 });
  if (seconds > 86400) return `${d.days}d`;
  if (seconds > 3600) return `${d.hours}h ${d.minutes}m`;
  if (seconds > 60) return `${d.minutes}m ${d.seconds}s`;
  return `${Math.round(seconds)}s`;
}

export default function OpportunityTable({ opportunities, onSelect, selectedId }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>("edge_pct");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  function handleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir((d) => (d === "desc" ? "asc" : "desc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  }

  const sorted = [...opportunities].sort((a, b) => {
    let av: number, bv: number;
    if (sortKey === "edge_pct") {
      av = a.edge_pct; bv = b.edge_pct;
    } else if (sortKey === "max_size") {
      av = a.max_size; bv = b.max_size;
    } else if (sortKey === "time_to_close_s") {
      av = a.time_to_close_s ?? Infinity;
      bv = b.time_to_close_s ?? Infinity;
    } else {
      av = new Date(a.updated_at).getTime();
      bv = new Date(b.updated_at).getTime();
    }
    return sortDir === "desc" ? bv - av : av - bv;
  });

  function SortIcon({ k }: { k: SortKey }) {
    if (k !== sortKey) return <span className="opacity-20">↕</span>;
    return <span>{sortDir === "desc" ? "↓" : "↑"}</span>;
  }

  if (opportunities.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-slate-500">
        <span className="text-4xl mb-3">🔍</span>
        <p className="text-sm">No arbitrage opportunities detected.</p>
        <p className="text-xs mt-1">Scanner is running - check venue status above.</p>
      </div>
    );
  }

  return (
    <div className="overflow-auto">
      <table className="w-full">
        <thead className="bg-surface-1 sticky top-0 z-10">
          <tr>
            <th className="th">Type</th>
            <th className="th">Market</th>
            <th className="th">Venues</th>
            <th className="th cursor-pointer" onClick={() => handleSort("edge_pct")}>
              Edge % <SortIcon k="edge_pct" />
            </th>
            <th className="th cursor-pointer" onClick={() => handleSort("max_size")}>
              Max Size <SortIcon k="max_size" />
            </th>
            <th className="th cursor-pointer" onClick={() => handleSort("time_to_close_s")}>
              Closes In <SortIcon k="time_to_close_s" />
            </th>
            <th className="th cursor-pointer" onClick={() => handleSort("updated_at")}>
              Updated <SortIcon k="updated_at" />
            </th>
            <th className="th"></th>
          </tr>
        </thead>
        <tbody className="divide-y divide-surface-2">
          {sorted.map((opp) => (
            <tr
              key={opp.id}
              onClick={() => onSelect(opp)}
              className={`transition-colors cursor-pointer ${
                selectedId === opp.id
                  ? "bg-surface-3"
                  : "hover:bg-surface-2"
              }`}
            >
              <td className="td">
                <span className="badge bg-surface-2 text-slate-300">
                  {opp.type === "intra" ? "Intra" : "Cross"}
                </span>
              </td>
              <td className="td max-w-xs">
                <span className="truncate block" title={opp.event_title}>
                  {opp.event_title}
                </span>
              </td>
              <td className="td text-slate-400">
                {opp.venues.join(" / ")}
              </td>
              <td className="td">
                <span
                  className={`font-semibold ${
                    opp.edge_pct >= 0.02
                      ? "text-accent-green"
                      : opp.edge_pct >= 0.005
                      ? "text-accent-yellow"
                      : "text-slate-300"
                  }`}
                >
                  {fmtPct(opp.edge_pct)}
                </span>
              </td>
              <td className="td text-slate-300">${fmtSize(opp.max_size)}</td>
              <td className="td text-slate-400">{fmtTime(opp.time_to_close_s)}</td>
              <td className="td text-slate-500 text-xs">
                {formatDistanceToNow(new Date(opp.updated_at), { addSuffix: true })}
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
