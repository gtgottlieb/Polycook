from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import OrderAnomalyOut
from services import aberrant_orders
from state import app_state

router = APIRouter(prefix="/api/anomalies", tags=["anomalies"])


@router.get("", response_model=list[OrderAnomalyOut])
async def list_anomalies():
    return [OrderAnomalyOut.from_anomaly(a) for a in app_state.anomalies]


@router.get("/history", response_model=list[OrderAnomalyOut])
async def anomaly_history(
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    events = await aberrant_orders.list_recent_events(db, limit=limit)
    return [OrderAnomalyOut.from_event(e) for e in events]


@router.get("/{anomaly_id}", response_model=OrderAnomalyOut)
async def get_anomaly(
    anomaly_id: str,
    db: AsyncSession = Depends(get_db),
):
    for anomaly in app_state.anomalies:
        if anomaly.id == anomaly_id:
            return OrderAnomalyOut.from_anomaly(anomaly)

    event = await aberrant_orders.get_event_by_id(db, anomaly_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Anomaly not found")
    return OrderAnomalyOut.from_event(event)
