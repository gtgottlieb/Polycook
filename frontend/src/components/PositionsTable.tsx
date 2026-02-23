import { useMutation, useQueryClient } from "@tanstack/react-query";
import { format } from "date-fns";
import { closeTrade } from "../api";
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

export function PositionsTable({ trades }: Props) {
  const open = trades.filter((t) => t.status === "open");
  const queryClient = useQueryClient();

  const closeMutation = useMutation({
    mutationFn: (id: string) => closeTrade(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["trades"] });
      queryClient.invalidateQueries({ queryKey: ["portfolio"] });
    },
  });

  if (open.length === 0) {
    return (
      <div className="card p-8 text-center text-slate-500 text-sm">
        No open positions.
      </div>
    );
  }

  return (
    <div className="card overflow-auto">
      <table className="w-full">
        <thead className="bg-surface-1">
          <tr>
            <th className="th">Market</th>
            <th className="th">Legs</th>
            <th className="th">Size</th>
            <th className="th">Entry Cost</th>
            <th className="th">Locked Payoff</th>
            <th className="th">Unrealized P&L</th>
            <th className="th">Entered</th>
            <th className="th"></th>
          </tr>
        </thead>
        <tbody className="divide-y divide-surface-2">
          {open.map((trade) => (
            <tr key={trade.id} className="hover:bg-surface-2 transition-colors">
              <td className="td max-w-xs">
                <span className="truncate block text-xs" title={trade.opportunity_snapshot.event_title}>
                  {trade.opportunity_snapshot.event_title}
                </span>
                <span className="text-slate-600 text-xs font-mono">{trade.id.slice(0, 8)}</span>
              </td>
              <td className="td">
                <div className="flex flex-wrap gap-1">
                  {trade.legs.map((leg) => (
                    <span key={leg.outcome_id} className="badge bg-surface-2 text-slate-300">
                      {leg.label} @{leg.entry_price.toFixed(3)}
                    </span>
                  ))}
                </div>
              </td>
              <td className="td text-slate-300">${trade.size.toFixed(0)}</td>
              <td className="td text-slate-300">${trade.entry_cost.toFixed(2)}</td>
              <td className="td text-slate-300">${trade.locked_in_payoff.toFixed(2)}</td>
              <td className={`td font-medium ${pnlColor(trade.unrealized_pnl)}`}>
                {fmtPnl(trade.unrealized_pnl)}
              </td>
              <td className="td text-slate-500 text-xs">
                {format(new Date(trade.created_at), "MMM d HH:mm")}
              </td>
              <td className="td">
                <button
                  onClick={() => closeMutation.mutate(trade.id)}
                  disabled={closeMutation.isPending}
                  className="btn-danger text-xs"
                >
                  Close
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
