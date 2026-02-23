import { format } from "date-fns";
import type { Trade } from "../types";

interface Props {
  trades: Trade[];
}

function pnlColor(v: number | null) {
  if (v === null) return "text-slate-400";
  if (v > 0) return "text-accent-green";
  if (v < 0) return "text-accent-red";
  return "text-slate-300";
}

function fmtPnl(v: number | null) {
  if (v === null) return "-";
  const sign = v >= 0 ? "+" : "";
  return `${sign}$${v.toFixed(2)}`;
}

export function TradeHistory({ trades }: Props) {
  const closed = trades.filter((t) => t.status === "closed");

  if (closed.length === 0) {
    return (
      <div className="card p-8 text-center text-slate-500 text-sm">
        No closed trades yet.
      </div>
    );
  }

  const totalRealized = closed.reduce((s, t) => s + (t.realized_pnl ?? 0), 0);

  return (
    <div className="space-y-2">
      <div className="flex justify-between items-center">
        <p className="text-xs text-slate-500">{closed.length} closed trade{closed.length !== 1 ? "s" : ""}</p>
        <p className={`text-xs font-medium ${pnlColor(totalRealized)}`}>
          Total realized: {fmtPnl(totalRealized)}
        </p>
      </div>

      <div className="card overflow-auto">
        <table className="w-full">
          <thead className="bg-surface-1">
            <tr>
              <th className="th">Market</th>
              <th className="th">Legs</th>
              <th className="th">Size</th>
              <th className="th">Entry Cost</th>
              <th className="th">Realized P&L</th>
              <th className="th">Entered</th>
              <th className="th">Closed</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-surface-2">
            {closed.map((trade) => (
              <tr key={trade.id} className="hover:bg-surface-2 transition-colors">
                <td className="td max-w-xs">
                  <span className="truncate block text-xs" title={trade.opportunity_snapshot.event_title}>
                    {trade.opportunity_snapshot.event_title}
                  </span>
                </td>
                <td className="td">
                  <div className="flex flex-wrap gap-1">
                    {trade.legs.map((leg) => (
                      <span key={leg.outcome_id} className="badge bg-surface-2 text-slate-400">
                        {leg.label}
                      </span>
                    ))}
                  </div>
                </td>
                <td className="td text-slate-400">${trade.size.toFixed(0)}</td>
                <td className="td text-slate-400">${trade.entry_cost.toFixed(2)}</td>
                <td className={`td font-medium ${pnlColor(trade.realized_pnl)}`}>
                  {fmtPnl(trade.realized_pnl)}
                </td>
                <td className="td text-slate-500 text-xs">
                  {format(new Date(trade.created_at), "MMM d HH:mm")}
                </td>
                <td className="td text-slate-500 text-xs">
                  {trade.closed_at
                    ? format(new Date(trade.closed_at), "MMM d HH:mm")
                    : "-"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
