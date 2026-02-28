from fastapi import APIRouter

from config import settings
from models import SettingsOut, SettingsUpdate

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _settings_out() -> SettingsOut:
    return SettingsOut(
        refresh_interval_s=settings.refresh_interval_s,
        arb_refresh_interval_s=settings.arb_refresh_interval_s,
        anomaly_refresh_interval_s=settings.anomaly_refresh_interval_s,
        stale_threshold_s=settings.stale_threshold_s,
        max_markets=settings.max_markets,
        anomaly_max_markets=settings.anomaly_max_markets,
        min_edge_pct=settings.min_edge_pct,
        min_max_size=settings.min_max_size,
        enable_arb_pipeline=settings.enable_arb_pipeline,
        enable_anomaly_pipeline=settings.enable_anomaly_pipeline,
        anomaly_enable_sweep_detection=settings.anomaly_enable_sweep_detection,
        anomaly_enable_wall_detection=settings.anomaly_enable_wall_detection,
        anomaly_candidate_min_size=settings.anomaly_candidate_min_size,
        anomaly_candidate_multiplier=settings.anomaly_candidate_multiplier,
        anomaly_candidate_abs_excess=settings.anomaly_candidate_abs_excess,
        anomaly_min_sweep_price_move=settings.anomaly_min_sweep_price_move,
        anomaly_min_sweep_fill_size=settings.anomaly_min_sweep_fill_size,
        anomaly_min_sweep_depth_ratio=settings.anomaly_min_sweep_depth_ratio,
        anomaly_max_spread=settings.anomaly_max_spread,
        anomaly_min_samples=settings.anomaly_min_samples,
        anomaly_bootstrap_min_samples=settings.anomaly_bootstrap_min_samples,
        anomaly_alpha=settings.anomaly_alpha,
        anomaly_alert_size_multiple=settings.anomaly_alert_size_multiple,
        anomaly_alert_robust_z=settings.anomaly_alert_robust_z,
        anomaly_absolute_min_wall_size=settings.anomaly_absolute_min_wall_size,
        anomaly_min_price=settings.anomaly_min_price,
        anomaly_max_price=settings.anomaly_max_price,
        anomaly_cooldown_s=settings.anomaly_cooldown_s,
        anomaly_max_candidates_per_cycle=settings.anomaly_max_candidates_per_cycle,
        starting_balance=settings.starting_balance,
    )


@router.get("", response_model=SettingsOut)
async def get_settings():
    return _settings_out()


@router.put("", response_model=SettingsOut)
async def update_settings(body: SettingsUpdate):
    """
    Update runtime settings. Changes take effect on the next relevant cycle.
    """
    if body.refresh_interval_s is not None:
        settings.refresh_interval_s = max(1, min(60, body.refresh_interval_s))
    if body.arb_refresh_interval_s is not None:
        settings.arb_refresh_interval_s = max(1, min(60, body.arb_refresh_interval_s))
    if body.anomaly_refresh_interval_s is not None:
        settings.anomaly_refresh_interval_s = max(1, min(60, body.anomaly_refresh_interval_s))
    if body.stale_threshold_s is not None:
        settings.stale_threshold_s = max(5, min(300, body.stale_threshold_s))
    if body.max_markets is not None:
        settings.max_markets = max(10, min(2000, body.max_markets))
    if body.anomaly_max_markets is not None:
        settings.anomaly_max_markets = max(10, min(4000, body.anomaly_max_markets))
    if body.min_edge_pct is not None:
        settings.min_edge_pct = max(0.0, min(0.5, body.min_edge_pct))
    if body.min_max_size is not None:
        settings.min_max_size = max(0.0, body.min_max_size)
    if body.enable_arb_pipeline is not None:
        settings.enable_arb_pipeline = body.enable_arb_pipeline
    if body.enable_anomaly_pipeline is not None:
        settings.enable_anomaly_pipeline = body.enable_anomaly_pipeline
    if body.anomaly_enable_sweep_detection is not None:
        settings.anomaly_enable_sweep_detection = body.anomaly_enable_sweep_detection
    if body.anomaly_enable_wall_detection is not None:
        settings.anomaly_enable_wall_detection = body.anomaly_enable_wall_detection
    if body.anomaly_candidate_min_size is not None:
        settings.anomaly_candidate_min_size = max(0.0, body.anomaly_candidate_min_size)
    if body.anomaly_candidate_multiplier is not None:
        settings.anomaly_candidate_multiplier = max(1.0, body.anomaly_candidate_multiplier)
    if body.anomaly_candidate_abs_excess is not None:
        settings.anomaly_candidate_abs_excess = max(0.0, body.anomaly_candidate_abs_excess)
    if body.anomaly_min_sweep_price_move is not None:
        settings.anomaly_min_sweep_price_move = max(
            0.0,
            min(1.0, body.anomaly_min_sweep_price_move),
        )
    if body.anomaly_min_sweep_fill_size is not None:
        settings.anomaly_min_sweep_fill_size = max(0.0, body.anomaly_min_sweep_fill_size)
    if body.anomaly_min_sweep_depth_ratio is not None:
        settings.anomaly_min_sweep_depth_ratio = max(
            0.0,
            min(1.0, body.anomaly_min_sweep_depth_ratio),
        )
    if body.anomaly_max_spread is not None:
        settings.anomaly_max_spread = max(0.0, min(1.0, body.anomaly_max_spread))
    if body.anomaly_min_samples is not None:
        settings.anomaly_min_samples = max(1, min(10_000, body.anomaly_min_samples))
    if body.anomaly_bootstrap_min_samples is not None:
        settings.anomaly_bootstrap_min_samples = max(
            1,
            min(settings.anomaly_min_samples, body.anomaly_bootstrap_min_samples),
        )
    if body.anomaly_alpha is not None:
        settings.anomaly_alpha = max(0.001, min(1.0, body.anomaly_alpha))
    if body.anomaly_alert_size_multiple is not None:
        settings.anomaly_alert_size_multiple = max(1.0, body.anomaly_alert_size_multiple)
    if body.anomaly_alert_robust_z is not None:
        settings.anomaly_alert_robust_z = max(0.0, body.anomaly_alert_robust_z)
    if body.anomaly_absolute_min_wall_size is not None:
        settings.anomaly_absolute_min_wall_size = max(0.0, body.anomaly_absolute_min_wall_size)
    if body.anomaly_min_price is not None:
        settings.anomaly_min_price = max(0.0, min(1.0, body.anomaly_min_price))
    if body.anomaly_max_price is not None:
        settings.anomaly_max_price = max(0.0, min(1.0, body.anomaly_max_price))
    if settings.anomaly_min_price > settings.anomaly_max_price:
        settings.anomaly_min_price, settings.anomaly_max_price = (
            settings.anomaly_max_price,
            settings.anomaly_min_price,
        )
    if body.anomaly_cooldown_s is not None:
        settings.anomaly_cooldown_s = max(0, min(86_400, body.anomaly_cooldown_s))
    if body.anomaly_max_candidates_per_cycle is not None:
        settings.anomaly_max_candidates_per_cycle = max(
            1,
            min(1000, body.anomaly_max_candidates_per_cycle),
        )

    return _settings_out()
