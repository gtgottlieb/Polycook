import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { createTrade } from "../api";
import type { Opportunity } from "../types";

interface Props {
  opportunity: Opportunity;
  onClose: () => void;
  onSuccess: () => void;
}

export default function TradeModal({ opportunity, onClose, onSuccess }: Props) {
  const opp = opportunity;
  const maxSize = opp.max_size;
  const [size, setSize] = useState<string>(Math.min(maxSize, 100).toFixed(0));
  const queryClient = useQueryClient();

  const sizeNum = parseFloat(size) || 0;
  const totalAsk = opp.legs.reduce((s, l) => s + l.ask, 0);
  const entryCost = totalAsk * sizeNum;
  const lockedProfit = (1 - totalAsk) * sizeNum;

  const mutation = useMutation({
    mutationFn: () => createTrade(opp.id, sizeNum),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["trades"] });
      queryClient.invalidateQueries({ queryKey: ["portfolio"] });
      onSuccess();
    },
  });

  const isValid = sizeNum > 0 && sizeNum <= maxSize;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
      <div className="card w-full max-w-sm">
        <div className="flex items-center justify-between p-4 border-b border-surface-3">
          <h2 className="font-semibold text-sm text-white">Paper Trade</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-white text-xl leading-none">
            ×
          </button>
        </div>

        <div className="p-4 space-y-4">
          <p className="text-xs text-slate-400 leading-relaxed">
            {opp.event_title}
          </p>

          {/* Leg summary */}
          <div className="bg-surface-2 rounded p-3 space-y-1">
            {opp.legs.map((leg) => (
              <div key={leg.outcome_id} className="flex justify-between text-xs">
                <span className="text-slate-400">
                  Buy {leg.label} ({leg.venue})
                </span>
                <span className="text-white">@ {leg.ask.toFixed(4)}</span>
              </div>
            ))}
            <div className="border-t border-surface-3 pt-1 mt-1 flex justify-between text-xs font-medium">
              <span className="text-slate-400">Total cost per unit</span>
              <span className="text-white">{totalAsk.toFixed(4)}</span>
            </div>
          </div>

          {/* Size input */}
          <div>
            <label className="block text-xs text-slate-400 mb-1">
              Size (max ${maxSize.toFixed(2)})
            </label>
            <div className="flex items-center gap-2">
              <input
                type="number"
                min="1"
                max={maxSize}
                step="1"
                value={size}
                onChange={(e) => setSize(e.target.value)}
                className="flex-1 bg-surface-2 border border-surface-3 rounded px-3 py-2 text-sm text-white
                           focus:outline-none focus:border-accent-blue"
              />
              <button
                className="btn-ghost text-xs"
                onClick={() => setSize(maxSize.toFixed(0))}
              >
                Max
              </button>
            </div>
            {sizeNum > maxSize && (
              <p className="text-xs text-accent-red mt-1">
                Exceeds max size of ${maxSize.toFixed(2)}
              </p>
            )}
          </div>

          {/* P&L preview */}
          <div className="bg-surface-2 rounded p-3 space-y-1 text-xs">
            <div className="flex justify-between">
              <span className="text-slate-400">Entry cost (deducted)</span>
              <span className="text-white">${entryCost.toFixed(2)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-400">Locked-in payoff</span>
              <span className="text-white">${(sizeNum * 1.0).toFixed(2)}</span>
            </div>
            <div className="flex justify-between font-medium">
              <span className="text-slate-300">Locked-in profit</span>
              <span className="text-accent-green">${lockedProfit.toFixed(2)}</span>
            </div>
          </div>

          {mutation.isError && (
            <p className="text-xs text-accent-red">
              {(mutation.error as Error).message}
            </p>
          )}
        </div>

        <div className="p-4 flex justify-end gap-2 border-t border-surface-3">
          <button onClick={onClose} className="btn-ghost" disabled={mutation.isPending}>
            Cancel
          </button>
          <button
            onClick={() => mutation.mutate()}
            disabled={!isValid || mutation.isPending}
            className="btn-success"
          >
            {mutation.isPending ? "Entering…" : `Enter Trade ($${entryCost.toFixed(2)})`}
          </button>
        </div>
      </div>
    </div>
  );
}
