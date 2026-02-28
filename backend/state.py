"""
Shared in-memory state for the running application.
Mutated by the background polling task and read by routers/WebSocket.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from models import (
    NormalizedContract,
    Opportunity,
    OrderAnomaly,
    PipelineStatus,
    PipelineStatusMap,
)


@dataclass
class AppState:
    opportunities: list[Opportunity] = field(default_factory=list)
    contracts: list[NormalizedContract] = field(default_factory=list)
    anomalies: list[OrderAnomaly] = field(default_factory=list)
    anomaly_snapshot: dict[str, Any] = field(default_factory=dict)
    pipeline_status: PipelineStatusMap = field(
        default_factory=lambda: PipelineStatusMap(
            arbitrage=PipelineStatus(enabled=True, running=False),
            aberrant_orders=PipelineStatus(enabled=True, running=False),
        )
    )

    @property
    def contracts_by_token(self) -> dict[str, NormalizedContract]:
        return {c.outcome_id: c for c in self.contracts}


app_state = AppState()
