from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from models import SettingsOut, SettingsUpdate

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=SettingsOut)
async def get_settings():
    return SettingsOut(
        refresh_interval_s=settings.refresh_interval_s,
        stale_threshold_s=settings.stale_threshold_s,
        max_markets=settings.max_markets,
        min_edge_pct=settings.min_edge_pct,
        starting_balance=settings.starting_balance,
    )


@router.put("", response_model=SettingsOut)
async def update_settings(body: SettingsUpdate):
    """
    Update runtime settings. Changes take effect on next poll cycle.
    Note: starting_balance only affects future resets, not current balance.
    """
    if body.refresh_interval_s is not None:
        settings.refresh_interval_s = max(2, min(60, body.refresh_interval_s))
    if body.stale_threshold_s is not None:
        settings.stale_threshold_s = max(5, min(300, body.stale_threshold_s))
    if body.max_markets is not None:
        settings.max_markets = max(10, min(2000, body.max_markets))
    if body.min_edge_pct is not None:
        settings.min_edge_pct = max(0.0, min(0.5, body.min_edge_pct))

    return SettingsOut(
        refresh_interval_s=settings.refresh_interval_s,
        stale_threshold_s=settings.stale_threshold_s,
        max_markets=settings.max_markets,
        min_edge_pct=settings.min_edge_pct,
        starting_balance=settings.starting_balance,
    )
