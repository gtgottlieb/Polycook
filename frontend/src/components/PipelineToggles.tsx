import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchSettings, updateSettings } from "../api";
import type { PipelineStatusMap, Settings } from "../types";

interface Props {
  pipelineStatus: PipelineStatusMap;
}

export default function PipelineToggles({ pipelineStatus }: Props) {
  const queryClient = useQueryClient();
  const { data: runtimeSettings } = useQuery({
    queryKey: ["settings"],
    queryFn: fetchSettings,
    staleTime: 5_000,
  });

  const mutation = useMutation({
    mutationFn: (patch: Partial<Settings>) => updateSettings(patch),
    onSuccess: (next) => {
      queryClient.setQueryData(["settings"], next);
    },
  });

  function toggleArbitrage() {
    if (!runtimeSettings || mutation.isPending) return;
    mutation.mutate({ enable_arb_pipeline: !runtimeSettings.enable_arb_pipeline });
  }

  function toggleAnomalies() {
    if (!runtimeSettings || mutation.isPending) return;
    mutation.mutate({
      enable_anomaly_pipeline: !runtimeSettings.enable_anomaly_pipeline,
    });
  }

  function buttonClass(enabled: boolean) {
    return enabled
      ? "bg-accent-green/15 text-accent-green border border-accent-green/30"
      : "bg-surface-2 text-slate-400 border border-surface-3";
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <button
        onClick={toggleArbitrage}
        disabled={!runtimeSettings || mutation.isPending}
        className={`px-3 py-1.5 rounded text-xs font-medium transition-colors ${buttonClass(
          pipelineStatus.arbitrage.enabled
        )}`}
      >
        Arbitrage: {pipelineStatus.arbitrage.enabled ? "On" : "Off"}
      </button>
      <button
        onClick={toggleAnomalies}
        disabled={!runtimeSettings || mutation.isPending}
        className={`px-3 py-1.5 rounded text-xs font-medium transition-colors ${buttonClass(
          pipelineStatus.aberrant_orders.enabled
        )}`}
      >
        Aberrant Orders: {pipelineStatus.aberrant_orders.enabled ? "On" : "Off"}
      </button>
    </div>
  );
}
