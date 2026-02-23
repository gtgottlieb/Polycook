import { useMutation, useQueryClient } from "@tanstack/react-query";
import { resetPortfolio } from "../api";
import type { Portfolio } from "../types";

interface Props {
  portfolio: Portfolio | null;
}

function StatCard({ label, value, sub, color }: {
  label: string;
  value: string;
  sub?: string;
  color?: string;
}) {
  return (
    <div className="card p-4">
      <p className="text-xs text-slate-500 mb-1">{label}</p>
      <p className={`text-xl font-bold ${color ?? "text-white"}`}>{value}</p>
      {sub && <p className="text-xs text-slate-500 mt-0.5">{sub}</p>}
    </div>
  );
}

function pnlColor(v: number) {
  if (v > 0) return "text-accent-green";
  if (v < 0) return "text-accent-red";
  return "text-slate-300";
}

function fmtUsd(v: number) {
  const sign = v >= 0 ? "+" : "";
  return `${sign}$${v.toFixed(2)}`;
}

export default function PortfolioStats({ portfolio }: Props) {
  const queryClient = useQueryClient();

  const resetMutation = useMutation({
    mutationFn: resetPortfolio,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["portfolio"] });
      queryClient.invalidateQueries({ queryKey: ["trades"] });
    },
  });

  if (!portfolio) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="card p-4 animate-pulse h-20" />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard
          label="Paper Balance"
          value={`$${portfolio.balance.toFixed(2)}`}
        />
        <StatCard
          label="Unrealized P&L"
          value={fmtUsd(portfolio.unrealized_pnl)}
          color={pnlColor(portfolio.unrealized_pnl)}
          sub="open positions"
        />
        <StatCard
          label="Realized P&L"
          value={fmtUsd(portfolio.realized_pnl)}
          color={pnlColor(portfolio.realized_pnl)}
          sub="closed trades"
        />
        <StatCard
          label="Total P&L"
          value={fmtUsd(portfolio.total_pnl)}
          color={pnlColor(portfolio.total_pnl)}
          sub={`${portfolio.open_trade_count} open`}
        />
      </div>

      <div className="flex justify-end">
        <button
          onClick={() => {
            if (confirm("Reset paper account? This will close all open positions and reset your balance.")) {
              resetMutation.mutate();
            }
          }}
          disabled={resetMutation.isPending}
          className="btn-danger text-xs"
        >
          {resetMutation.isPending ? "Resetting…" : "Reset Paper Account"}
        </button>
      </div>
    </div>
  );
}
