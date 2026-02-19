"""
Simulate Warman-type pump operation in industrial conditions.
Aligned with ISO 10816-3; zone thresholds (e.g. VIBRATION_WARNING_MMPS, VIBRATION_CRITICAL_MMPS)
are defined in config.config.Config.

Includes: gradual wear (drift + small steps) and rare "stone hit" (debris impact)
as a sharp health jump.
"""
import csv
import os
import subprocess
import sys
import pandas as pd
import numpy as np
import warnings
import time
import random
from config.config import Config
from app.data_processor import DataProcessor
from app.predictor import PumpPredictor
from app.rules import TripCause, AlarmCause

warnings.filterwarnings("ignore", category=UserWarning)

STATUS_DISPLAY = {
    "CRITICAL": "🚨 CRITICAL",
    "WARNING": "⚠️ WARNING",
    "HEALTHY": "✅ HEALTHY",
    "ERROR": "❌ ERROR",
    "UNKNOWN (No Model)": "❌ UNKNOWN (No Model)",
}

# Plain ASCII status labels for fixed-width alignment (used for tabular console output).
STATUS_TEXT = {
    "CRITICAL": "CRITICAL",
    "WARNING": "WARNING",
    "HEALTHY": "HEALTHY",
    "ERROR": "ERROR",
    "UNKNOWN (No Model)": "UNKNOWN",
}

STATUS_EMOJI = {
    "CRITICAL": "🚨",
    "WARNING": "🔔",
    "HEALTHY": "✅",
    "ERROR": "❌",
    "UNKNOWN (No Model)": "❌",
}

BANNER_WIDTH = 85
SHUTDOWN_LOG_FIELDNAMES = ["timestamp", "risk_score", "status"] + Config.FEATURE_NAMES


def _shutdown_row(
    ts_full: str,
    status: str,
    v_mean: float,
    p_mean: float,
    t_mean: float,
    current_display: float,
    data: pd.DataFrame,
    *,
    vib_rms_override: float | None = None,
    features_df: pd.DataFrame | None = None,
) -> dict:
    """Build a shutdown audit row with real sensor means (no artificial zeros).

    Optional vib_rms_override: use for vib_rms (e.g. display value for VIBRATION_INTERLOCK).
    Optional features_df: use iloc[0] for vib_crest, vib_kurtosis, cavitation_index, temp_delta.
    """
    if features_df is not None:
        row0 = features_df.iloc[0]
        vib_crest = float(row0["vib_crest"])
        vib_kurtosis = float(row0["vib_kurtosis"])
        cavitation_index = float(row0["cavitation_index"])
        temp_delta = float(row0["temp_delta"])
    else:
        vib_crest = float(data["vib_crest"].mean())
        vib_kurtosis = float(data["vib_kurtosis"].mean())
        cavitation_index = float(data["cavitation_index"].mean())
        temp_delta = 0.0
    vib_rms = vib_rms_override if vib_rms_override is not None else v_mean
    return {
        "timestamp": ts_full,
        "risk_score": 1.0,
        "status": status,
        "vib_rms": vib_rms,
        "vib_crest": vib_crest,
        "vib_kurtosis": vib_kurtosis,
        "current": current_display,
        "pressure": p_mean,
        "cavitation_index": cavitation_index,
        "temp": t_mean,
        "temp_delta": temp_delta,
    }


def _append_shutdown_log(row: dict) -> None:
    """Append one shutdown audit row to telemetry CSV (makedirs, writeheader if new file)."""
    try:
        log_path = Config.TELEMETRY_LOG_PATH
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        file_exists = os.path.isfile(log_path)
        with open(log_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=SHUTDOWN_LOG_FIELDNAMES)
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
    except (OSError, PermissionError):
        pass


def _handle_debris_shutdown(
    predictor: PumpPredictor,
    ts: str,
    v_mean: float,
    p_mean: float,
    t_mean: float,
    current_display: float,
    data: pd.DataFrame,
) -> None:
    """Print debris-impact shutdown banner, log row and common post-shutdown steps."""
    ts_full = time.strftime("%Y-%m-%d %H:%M:%S")
    print("\n" + "!" * BANNER_WIDTH)
    print(f"[{ts}] 🚨 [DEBRIS IMPACT SHUTDOWN] {Config.DEBRIS_IMPACT_SHUTDOWN_MESSAGE}")
    print(f"[{ts}] 🛠️  [REPAIR] {Config.DEBRIS_IMPACT_REPAIR_MESSAGE}")
    trip_cause = getattr(predictor, "last_trip_cause", None)
    alarm_causes = getattr(predictor, "last_alarm_causes", []) or []
    print(
        f"[{ts}] ℹ️  Trip cause: {trip_cause or 'N/A'}; "
        f"Active alarms: {', '.join(alarm_causes) if alarm_causes else 'none'}"
    )
    print(f"[{ts}] ⚠️  {Config.DEBRIS_IMPACT_MANUAL_CLEARANCE_MESSAGE}")
    row = _shutdown_row(
        ts_full,
        "DEBRIS_IMPACT_SHUTDOWN",
        v_mean,
        p_mean,
        t_mean,
        current_display,
        data,
    )
    _append_shutdown_log(row)
    _after_shutdown(
        predictor,
        ts,
        print_restart=True,
        print_banner=True,
        sleep_after_banner=3,
    )


def _handle_choked_shutdown(
    predictor: PumpPredictor,
    ts: str,
    v_mean: float,
    p_mean: float,
    t_mean: float,
    current_display: float,
    data: pd.DataFrame,
) -> None:
    """Print choked-discharge shutdown banner, log row and common post-shutdown steps."""
    ts_full = time.strftime("%Y-%m-%d %H:%M:%S")
    print("\n" + "!" * BANNER_WIDTH)
    print(
        f"[{ts}] 🚨 [CHOKED DISCHARGE SHUTDOWN] {Config.CHOKED_DISCHARGE_SHUTDOWN_MESSAGE}"
    )
    print(f"[{ts}] 🛠️  [REPAIR] {Config.CHOKED_DISCHARGE_REPAIR_MESSAGE}")
    trip_cause = getattr(predictor, "last_trip_cause", None)
    alarm_causes = getattr(predictor, "last_alarm_causes", []) or []
    print(
        f"[{ts}] ℹ️  Trip cause: {trip_cause or 'N/A'}; "
        f"Active alarms: {', '.join(alarm_causes) if alarm_causes else 'none'}"
    )
    row = _shutdown_row(
        ts_full,
        "CHOKED_DISCHARGE_SHUTDOWN",
        v_mean,
        p_mean,
        t_mean,
        current_display,
        data,
    )
    _append_shutdown_log(row)
    _after_shutdown(
        predictor,
        ts,
        print_restart=False,
        print_banner=False,
    )


def _handle_cavitation_shutdown(
    predictor: PumpPredictor,
    ts: str,
    shutdown_sec: float,
    v_mean: float,
    p_mean: float,
    t_mean: float,
    current_display: float,
    data: pd.DataFrame,
) -> None:
    """Print cavitation shutdown banner, log row and common post-shutdown steps."""
    ts_full = time.strftime("%Y-%m-%d %H:%M:%S")
    print("\n" + "!" * BANNER_WIDTH)
    print(
        f"[{ts}] 🚨 [CAVITATION SHUTDOWN] "
        f"{Config.CAVITATION_SHUTDOWN_MESSAGE.format(shutdown_sec=shutdown_sec)}"
    )
    print(f"[{ts}] 🛠️  [REPAIR] {Config.CAVITATION_REPAIR_MESSAGE}")
    trip_cause = getattr(predictor, "last_trip_cause", None)
    alarm_causes = getattr(predictor, "last_alarm_causes", []) or []
    print(
        f"[{ts}] ℹ️  Trip cause: {trip_cause or 'N/A'}; "
        f"Active alarms: {', '.join(alarm_causes) if alarm_causes else 'none'}"
    )
    row = _shutdown_row(
        ts_full,
        "CAVITATION_SHUTDOWN",
        v_mean,
        p_mean,
        t_mean,
        current_display,
        data,
    )
    _append_shutdown_log(row)
    _after_shutdown(
        predictor,
        ts,
        print_restart=True,
        print_banner=True,
        sleep_after_banner=3,
    )


def _handle_vibration_interlock_shutdown(
    predictor: PumpPredictor,
    ts: str,
    vib_display: float,
    v_mean: float,
    p_mean: float,
    t_mean: float,
    current_display: float,
    data: pd.DataFrame,
    features_df: pd.DataFrame,
) -> None:
    """Print vibration-interlock shutdown banner, log row and common post-shutdown steps."""
    ts_full = time.strftime("%Y-%m-%d %H:%M:%S")
    print("\n" + "!" * BANNER_WIDTH)
    print(
        f"[{ts}] 🚨 [VIBRATION INTERLOCK] "
        f"{Config.VIBRATION_INTERLOCK_SHUTDOWN_MESSAGE.format(vib_display=vib_display)}"
    )
    print(f"[{ts}] 🛠️  [REPAIR] {Config.VIBRATION_INTERLOCK_REPAIR_MESSAGE}")
    trip_cause = getattr(predictor, "last_trip_cause", None)
    alarm_causes = getattr(predictor, "last_alarm_causes", []) or []
    print(
        f"[{ts}] ℹ️  Trip cause: {trip_cause or 'N/A'}; "
        f"Active alarms: {', '.join(alarm_causes) if alarm_causes else 'none'}"
    )
    row = _shutdown_row(
        ts_full,
        "VIBRATION_INTERLOCK",
        v_mean,
        p_mean,
        t_mean,
        current_display,
        data,
        vib_rms_override=vib_display,
        features_df=features_df,
    )
    _append_shutdown_log(row)
    _after_shutdown(
        predictor,
        ts,
        print_restart=True,
        print_banner=True,
        sleep_after_banner=3,
    )


def _handle_overtemp_shutdown(
    predictor: PumpPredictor,
    ts: str,
    trigger_sec: float,
    vib_display: float,
    v_mean: float,
    p_mean: float,
    t_mean: float,
    current_display: float,
    data: pd.DataFrame,
) -> None:
    """Print overtemperature (with optional vibration) shutdown banner, log row and post-shutdown steps."""
    ts_full = time.strftime("%Y-%m-%d %H:%M:%S")
    also_vibration = vib_display >= Config.VIBRATION_INTERLOCK_MMPS
    print("\n" + "!" * BANNER_WIDTH)
    restart_temp_max = getattr(Config, "TEMP_CRITICAL_RESTART_TEMP_MAX_C", 50.0)
    if also_vibration:
        print(
            f"[{ts}] 🚨 [OVERTEMPERATURE SHUTDOWN] "
            f"{Config.OVERTEMPERATURE_AND_VIBRATION_SHUTDOWN_MESSAGE.format(temp_shutdown_sec=trigger_sec, vib_display=vib_display)}"
        )
        print(
            f"[{ts}] 🛠️  [REPAIR] "
            f"{Config.OVERTEMPERATURE_AND_VIBRATION_REPAIR_MESSAGE.format(restart_temp_max=restart_temp_max)}"
        )
    else:
        print(
            f"[{ts}] 🚨 [OVERTEMPERATURE SHUTDOWN] "
            f"{Config.OVERTEMPERATURE_SHUTDOWN_MESSAGE.format(temp_shutdown_sec=trigger_sec)}"
        )
        print(
            f"[{ts}] 🛠️  [REPAIR] "
            f"{Config.OVERTEMPERATURE_REPAIR_MESSAGE.format(restart_temp_max=restart_temp_max)}"
        )
    trip_cause = getattr(predictor, "last_trip_cause", None)
    alarm_causes = getattr(predictor, "last_alarm_causes", []) or []
    print(
        f"[{ts}] ℹ️  Trip cause: {trip_cause or 'N/A'}; "
        f"Active alarms: {', '.join(alarm_causes) if alarm_causes else 'none'}"
    )
    row = _shutdown_row(
        ts_full,
        "OVERTEMPERATURE_SHUTDOWN",
        v_mean,
        p_mean,
        t_mean,
        current_display,
        data,
    )
    _append_shutdown_log(row)
    _after_shutdown(
        predictor,
        ts,
        print_restart=False,
        print_banner=False,
        sleep_after_banner=0,
    )


def _after_shutdown(
    predictor: PumpPredictor,
    ts: str,
    *,
    print_restart: bool = True,
    print_banner: bool = False,
    sleep_after_banner: float = 0,
) -> None:
    """Common post-shutdown: reset predictor, optional RESTART line, optional banner and sleep."""
    if hasattr(predictor, "reset_smoothing"):
        predictor.reset_smoothing()
    else:
        predictor.current_smoothed_risk = 0.0
    if print_restart:
        print(f"[{ts}] ✅ [RESTART] Pump {Config.PUMP_ID} is back online.")
    if print_banner:
        print("!" * BANNER_WIDTH + "\n")
    if sleep_after_banner > 0:
        time.sleep(sleep_after_banner)


def degradation_to_means(health: float) -> tuple[float, float, float]:
    """Map degradation level H [0, 1] to physical means (v, p, t) using Config zone constants."""
    h = Config.HEALTHY_MEANS
    w = Config.WARNING_MEANS
    c = Config.CRITICAL_MEANS
    if health <= 0.35:
        t = health / 0.35
        v = h["v"] + t * (w["v"] - h["v"])
        p = h["p"] - t * (h["p"] - w["p"])
        temp = h["t"] + t * (w["t"] - h["t"])
    else:
        t = (health - 0.35) / 0.65
        v = w["v"] + t * (c["v"] - w["v"])
        p = w["p"] - t * (w["p"] - c["p"])
        temp = w["t"] + t * (c["t"] - w["t"])
    return v, p, temp


def run_simulation():
    """Run end-to-end digital twin simulation.

    Predictor+rules decide *why* we are in CRITICAL/WARNING (status, reason, trip_cause).
    This simulator is the single place where trip_cause / reason are mapped to concrete
    shutdown scenarios (debris impact, cavitation, choked discharge, overtemperature,
    vibration interlock) and restart/cooldown behaviour.
    """
    print(f"🚀 Warman pump: {Config.PUMP_ID} – Industrial Digital Twin (ISO 10816-3)")
    print(
        "Interval: 3s | Vib thresholds: Warn≥4.5, Crit≥7.1, Interlock≥9.0 mm/s | Ctrl+C"
    )
    print("-" * BANNER_WIDTH)

    processor = DataProcessor()
    predictor = PumpPredictor()
    iteration = 0
    health = 0.0  # Wear level 0..1
    degradation_remaining = (
        0  # Countdown for "impeller wear" scenario (3 steps for predictor smoothing)
    )
    choked_remaining = 0  # Countdown for "choked discharge / closed valve" scenario (low flow + high P + high T)
    last_choked_p_mean = None  # For smooth blend when leaving choked
    last_choked_t_mean = None
    choked_blend_steps = (
        0  # After choked ends: blend P/T toward nominal over this many steps
    )
    air_ingestion_remaining = (
        0  # Countdown for "air ingestion" scenario (impulsive vib + fluctuating P/flow)
    )
    cavitation_remaining = 0  # Countdown for "cavitation" scenario (high I, low P, moderate-high V -> CavitationRule)
    cavitation_start_time = (
        None  # For auto shutdown after N seconds of sustained cavitation
    )
    vib_interlock_remaining = 0  # Countdown for "pure vibration" scenario (high V with otherwise nominal process)
    temp_critical_start_time = None  # For auto shutdown after N seconds of T >= 75°C
    temp_critical_ticks = (
        0  # Consecutive ticks with T >= 75°C + HIGH TEMPERATURE reason
    )
    temp_cooldown_steps_remaining = (
        0  # After temp critical shutdown: wait N steps before RESTART (T < 50°C)
    )
    last_printed_reason = None  # Only print reason when it changes (avoid spam)
    debris_impact_remaining = (
        0  # After STONE HIT, pass debris_impact to predictor for this many steps
    )
    mechanical_alert_printed = (
        False  # Print Warman-style debris alert once per event; simulation continues
    )
    last_status_print_time = None  # For 3s interval between status lines
    unknown_critical_count = (
        0  # Diagnostics: how many times we hit Unknown CRITICAL fallback
    )

    try:
        while True:
            # Cooldown after OVERTEMPERATURE_SHUTDOWN / CHOKED_DISCHARGE_SHUTDOWN:
            # do not restart until T < 50°C (simulated by N steps with the same 3s interval as status lines).
            restart_temp_max = getattr(Config, "TEMP_CRITICAL_RESTART_TEMP_MAX_C", 50.0)
            if temp_cooldown_steps_remaining > 0:
                # Keep ~3s cadence between cooldown messages, aligned with main loop interval.
                interval_sec = 3.0
                if last_status_print_time is not None:
                    elapsed = time.time() - last_status_print_time
                    time.sleep(max(0.0, interval_sec - elapsed))
                ts = time.strftime("%H:%M:%S")
                if temp_cooldown_steps_remaining == 3:
                    print(
                        f"[{ts}] ⏳ Cooling down... Do not restart until T < {restart_temp_max:.0f}°C."
                    )
                temp_cooldown_steps_remaining -= 1
                if temp_cooldown_steps_remaining == 0:
                    print(f"[{ts}] ✅ [RESTART] Pump {Config.PUMP_ID} is back online.")
                    print("!" * BANNER_WIDTH + "\n")
                last_status_print_time = time.time()
                continue

            # 1. Gradual wear (slightly reduced rate so Zone D vibration appears a bit less often)
            health += random.gauss(0.002, 0.0018)

            if random.random() < 0.008:
                health += random.uniform(0.02, 0.06)
            if random.random() < 0.002:
                health += random.uniform(0.03, 0.08)

            # Rare event: debris impact (mechanical damage – no auto-restart)
            if random.random() < getattr(Config, "DEBRIS_IMPACT_SCENARIO_PROB", 0.002):
                bump = random.uniform(0.25, 0.45)
                health += bump
                debris_impact_remaining = (
                    999  # Keep mechanical-damage diagnosis until shutdown
                )
                print(f"    ⚠️  [STONE HIT] DEBRIS IMPACT: health +{bump:.2f}")

            # --- Scheduled maintenance block ---
            if health > 0.88 and random.random() < 0.06:
                print("\n🔧 [MAINTENANCE] Pump serviced. Resetting health state.")
                health = random.uniform(0.0, 0.05)
                if hasattr(predictor, "reset_smoothing"):
                    predictor.reset_smoothing()
                else:
                    predictor.current_smoothed_risk = 0.0

            health = max(0.0, min(1.0, health))

            # 2. Generate mean values
            v_mean, p_mean, t_mean = degradation_to_means(health)
            nominal_p_mean, nominal_t_mean = (
                p_mean,
                t_mean,
            )  # For smooth blend when leaving choked

            # Smooth transition when leaving choked: blend P/T toward nominal over 3 steps
            if (
                choked_blend_steps > 0
                and last_choked_p_mean is not None
                and last_choked_t_mean is not None
            ):
                alpha = choked_blend_steps / 3.0
                p_mean = alpha * last_choked_p_mean + (1.0 - alpha) * nominal_p_mean
                t_mean = alpha * last_choked_t_mean + (1.0 - alpha) * nominal_t_mean
                choked_blend_steps -= 1

            # Rare "impeller wear" scenario: low flow + low pressure (degradation vs Q-H curve)
            if degradation_remaining <= 0 and random.random() < getattr(
                Config, "DEGRADATION_SCENARIO_PROB", 0.008
            ):  # ~every 125 iter on average
                degradation_remaining = getattr(Config, "DEGRADATION_SCENARIO_STEPS", 3)
            if degradation_remaining > 0:
                degradation_remaining -= 1
                # Override: current 38–42 A, pressure 4.2–4.8 bar (below Q–H)
                current_mean = random.uniform(38.0, 42.0)
                p_mean = random.uniform(4.2, 4.8)
                v_mean = min(v_mean, 4.2)  # moderate vibration in this scenario
                t_mean = (t_mean + 55) / 2  # slight temp rise
                _degradation_current = current_mean
            else:
                _degradation_current = None

            # Rare "choked discharge / closed valve" scenario: low flow + high P + high temp (overheat risk).
            # Keep vibration in low/nominal range so choked trips are driven by process (P/T), not vibration interlock.
            if (
                degradation_remaining <= 0
                and choked_remaining <= 0
                and random.random() < getattr(Config, "CHOKED_SCENARIO_PROB", 0.003)
            ):
                choked_remaining = getattr(Config, "CHOKED_SCENARIO_STEPS", 3)
            if choked_remaining > 0:
                choked_remaining -= 1
                _choked_current = random.uniform(36.0, 40.0)
                p_mean = random.uniform(7.0, 8.5)
                t_mean = random.uniform(72.0, 82.0)
                # Keep RMS vibration below interlock range; choked is a process-driven trip.
                v_mean = min(v_mean, 4.0)
                last_choked_p_mean, last_choked_t_mean = p_mean, t_mean
                if choked_remaining == 0:
                    choked_blend_steps = 3  # Blend P/T toward nominal over next 3 steps
            else:
                _choked_current = None
                if choked_blend_steps <= 0:
                    last_choked_p_mean = last_choked_t_mean = None

            # Rare "air ingestion" scenario: vortex in sump -> impulsive vibration + fluctuating P/flow
            if (
                degradation_remaining <= 0
                and choked_remaining <= 0
                and air_ingestion_remaining <= 0
                and random.random()
                < getattr(Config, "AIR_INGESTION_SCENARIO_PROB", 0.008)
            ):
                air_ingestion_remaining = getattr(
                    Config, "AIR_INGESTION_SCENARIO_STEPS", 3
                )
            if air_ingestion_remaining > 0:
                air_ingestion_remaining -= 1

            # Rare "cavitation" scenario: high current, low inlet pressure, high vibration (CavitationRule)
            cavitation_prob = getattr(Config, "CAVITATION_SCENARIO_PROB", 0.005)
            cavitation_steps = getattr(Config, "CAVITATION_SCENARIO_STEPS", 4)
            if (
                degradation_remaining <= 0
                and choked_remaining <= 0
                and air_ingestion_remaining <= 0
                and cavitation_remaining <= 0
                and vib_interlock_remaining <= 0
                and random.random() < cavitation_prob
            ):
                cavitation_remaining = cavitation_steps
            if cavitation_remaining > 0:
                cavitation_remaining -= 1
                _cavitation_current = random.uniform(
                    54.5, 58.0
                )  # I >= CAVITATION_CURRENT_MIN_AMP
                p_mean = random.uniform(
                    3.0, 3.8
                )  # P <= CAVITATION_PRESSURE_MAX_BAR (4.0)
                # Cavitation should live mostly in ISO Zone D alarm band, but stay below interlock trip.
                # This keeps CAVITATION_SHUTDOWN distinct from pure vibration interlock trips.
                v_mean = random.uniform(7.2, 8.6)
                t_mean = (t_mean + 58) / 2  # Slight temp rise
            else:
                _cavitation_current = None

            # Rare "pure vibration" scenario: high RMS vibration with otherwise nominal process values.
            vib_interlock_prob = getattr(Config, "VIB_INTERLOCK_SCENARIO_PROB", 0.0012)
            vib_interlock_steps = getattr(Config, "VIB_INTERLOCK_SCENARIO_STEPS", 3)
            if (
                degradation_remaining <= 0
                and choked_remaining <= 0
                and air_ingestion_remaining <= 0
                and cavitation_remaining <= 0
                and vib_interlock_remaining <= 0
                and random.random() < vib_interlock_prob
            ):
                vib_interlock_remaining = vib_interlock_steps
            if vib_interlock_remaining > 0:
                vib_interlock_remaining -= 1
                # Drive vibration into interlock range while keeping process variables near nominal.
                v_mean = random.uniform(
                    9.2, 11.0
                )  # Above VIBRATION_INTERLOCK_MMPS (9.0)
                p_mean = random.uniform(5.5, 6.2)
                t_mean = random.uniform(48.0, 58.0)
                _pure_vib_current = random.uniform(45.0, 50.0)
            else:
                _pure_vib_current = None

            # 3. Generate data batch (buffer fill simulation)
            v_noise = random.gauss(0, 0.15)
            p_noise = random.gauss(0, 0.05)

            current_signal = (
                np.random.normal(_choked_current, 1.0, 30)
                if _choked_current is not None
                else (
                    np.random.normal(_cavitation_current, 1.0, 30)
                    if _cavitation_current is not None
                    else (
                        np.random.normal(_pure_vib_current, 1.0, 30)
                        if _pure_vib_current is not None
                        else (
                            np.random.normal(_degradation_current, 1.0, 30)
                            if _degradation_current is not None
                            else np.random.normal(45.0 + (health * 15), 1.5, 30)
                        )
                    )
                )
            )
            # Air ingestion: impulsive vib (high crest) + warning-level vib_rms + more variance in P/flow
            if air_ingestion_remaining > 0:
                _v_mean_ai = 5.2  # Zone C (WARNING)
                _v_crest_ai = 6.2
                vib_rms_signal = np.random.normal(_v_mean_ai, 0.4, 30)
                vib_crest_signal = np.random.normal(_v_crest_ai, 0.4, 30)
                vib_kurtosis_signal = np.random.normal(5.0, 0.6, 30)
            else:
                vib_rms_signal = np.random.normal(v_mean + v_noise, 0.3, 30)
                vib_crest_signal = (
                    np.random.normal(3.0, 0.2, 30)
                    if health < 0.4
                    else np.random.normal(7.5, 1.2, 30)
                )
                vib_kurtosis_signal = (
                    np.random.normal(2.8, 0.1, 30)
                    if health < 0.4
                    else np.random.normal(6.5, 0.8, 30)
                )
            data = pd.DataFrame(
                {
                    "vib_rms": vib_rms_signal,
                    "vib_crest": vib_crest_signal,
                    "vib_kurtosis": vib_kurtosis_signal,
                    "current": current_signal,
                    "pressure": np.random.normal(p_mean + p_noise, 0.15, 30),
                    "cavitation_index": np.random.normal(0.02, 0.01, 30)
                    if health < 0.5
                    else np.random.normal(0.3, 0.1, 30),
                    "temp": np.random.normal(t_mean, 1.2, 30),
                }
            )

            # 4. Convert to features
            raw_records = data.to_dict("records")
            features_array, status, iso_vib_rms = processor.prepare_batch(raw_records)

            if status == "OK":
                features_df = pd.DataFrame(features_array, columns=Config.FEATURE_NAMES)
                is_startup = iteration < Config.STARTUP_ITERATIONS

                # 5. Predict and output (pass debris_impact so predictor shows DEBRIS IMPACT after stone hit)
                latest_telemetry = (
                    {**raw_records[-1], "debris_impact": True}
                    if debris_impact_remaining > 0
                    else None
                )
                verdict, prob = predictor.predict(
                    features_df,
                    is_startup=is_startup,
                    latest_telemetry=latest_telemetry,
                    iso_vib_rms=iso_vib_rms,
                )
                if debris_impact_remaining > 0:
                    debris_impact_remaining -= 1
                verdict_display = STATUS_DISPLAY.get(verdict, verdict)
                # Display the vibration value used by the predictor (zone decisions).
                vib_display = (
                    float(iso_vib_rms)
                    if iso_vib_rms is not None
                    else float(features_df["vib_rms"].iloc[0])
                )

                ts = time.strftime("%H:%M:%S")
                h_pct = health * 100
                current_display = (
                    _choked_current
                    if _choked_current is not None
                    else (
                        _cavitation_current
                        if _cavitation_current is not None
                        else (
                            _degradation_current
                            if _degradation_current is not None
                            else (45.0 + (health * 15))
                        )
                    )
                )
                # Build status columns: emoji (decorator) + fixed-width ASCII status text.
                status_text = STATUS_TEXT.get(verdict, verdict[:10])
                status_emoji = STATUS_EMOJI.get(verdict, " ")
                status_label = f"{status_text:<9}"
                print(
                    f"[{ts}] H:{h_pct:4.0f}% | V:{vib_display:5.2f} P:{p_mean:3.1f} T:{t_mean:4.1f} I:{current_display:4.1f} | "
                    f"{status_emoji} | {status_label} | Risk Score: {prob:>7.2%}"
                )
                last_status_print_time = time.time()
                reason = getattr(predictor, "last_alert_reason", None)
                trip_cause = getattr(predictor, "last_trip_cause", None)
                alarm_causes = getattr(predictor, "last_alarm_causes", []) or []
                # Compare by reason "type" (prefix before ":") so we don't reprint on every P/I/T tick
                reason_base = (
                    reason.split(":")[0].strip() if reason and ":" in reason else reason
                )
                if reason and reason_base != last_printed_reason:
                    # One line; allow up to 110 chars so Zone D / long messages are not cut mid-word
                    msg = (reason[:110] + "..") if len(reason) > 110 else reason
                    print(f"    ⚠️  {msg}")
                    last_printed_reason = reason_base
                if reason is None:
                    last_printed_reason = None

                # Determine whether we already have a hard trip cause selected by the rules engine.
                # For these trip causes we should NEVER skip automatic shutdowns, even if reason is empty.
                hard_trip_causes = {
                    TripCause.DEBRIS_IMPACT,
                    TripCause.CHOKED_DISCHARGE,
                    TripCause.CAVITATION,
                    TripCause.OVERTEMP,
                    TripCause.VIB_INTERLOCK,
                }
                has_hard_trip_cause = trip_cause in hard_trip_causes
                has_hard_alarm = any(
                    cause in hard_trip_causes for cause in alarm_causes
                )
                is_hard_trip = has_hard_trip_cause or has_hard_alarm

                # Empty reason at CRITICAL: no automatic block when no hard trip cause selected.
                # No console message; logic unchanged (skip shutdown, advance time, same cadence).
                if (
                    verdict == "CRITICAL"
                    and not (reason or "").strip()
                    and not is_hard_trip
                ):
                    unknown_critical_count += 1
                    iteration += 1
                    interval_sec = 3.0
                    if last_status_print_time is not None:
                        elapsed = time.time() - last_status_print_time
                        time.sleep(max(0.0, interval_sec - elapsed))
                    else:
                        time.sleep(interval_sec)
                    continue

                # Debris impact (stone hit): check first so we get DEBRIS_IMPACT_SHUTDOWN, not VIBRATION_INTERLOCK
                mechanical_msg = getattr(
                    Config, "MECHANICAL_DAMAGE_ALERT_MESSAGE", None
                ) or getattr(Config, "DEBRIS_IMPACT_ALERT_MESSAGE", "")
                debris_msg = getattr(Config, "DEBRIS_IMPACT_ALERT_MESSAGE", "")
                cause_is_debris = trip_cause == TripCause.DEBRIS_IMPACT
                is_debris_critical = verdict == "CRITICAL" and (
                    cause_is_debris
                    or (reason or "").strip() == (mechanical_msg or "").strip()
                    or (debris_msg and (reason or "").strip() == debris_msg.strip())
                )
                if is_debris_critical:
                    _handle_debris_shutdown(
                        predictor,
                        ts,
                        v_mean,
                        p_mean,
                        t_mean,
                        current_display,
                        data,
                    )
                    health = 0.0
                    debris_impact_remaining = 0
                    mechanical_alert_printed = False
                    last_printed_reason = None
                    continue

                # Shutdown type is determined only by predictor reason (cause); scenario flags do not override.
                is_temp_reason = reason is not None and "HIGH TEMPERATURE" in reason
                is_choked_reason = reason is not None and reason.strip().startswith(
                    "CHOKED DISCHARGE"
                )
                cause_is_choked = trip_cause == TripCause.CHOKED_DISCHARGE

                # Choked discharge: only when cause is CHOKED DISCHARGE (not by scenario flag).
                if verdict == "CRITICAL" and (is_choked_reason or cause_is_choked):
                    _handle_choked_shutdown(
                        predictor,
                        ts,
                        v_mean,
                        p_mean,
                        t_mean,
                        current_display,
                        data,
                    )
                    health = 0.0
                    choked_remaining = (
                        0  # Avoid re-entering choked data on next iteration
                    )
                    last_printed_reason = None
                    temp_cooldown_steps_remaining = 3  # 9 s (3 × 3 s)
                    continue

                # Cavitation auto shutdown: after N seconds of sustained cavitation. Check before vibration.
                shutdown_sec = getattr(Config, "CAVITATION_AUTO_SHUTDOWN_SEC", 10)
                cavitation_msg = getattr(Config, "CAVITATION_ALERT_MESSAGE", "")
                cause_is_cavitation = trip_cause == TripCause.CAVITATION
                if verdict == "CRITICAL" and (
                    cause_is_cavitation
                    or (reason or "").strip() == (cavitation_msg or "").strip()
                ):
                    if cavitation_start_time is None:
                        cavitation_start_time = time.time()
                    elif (time.time() - cavitation_start_time) >= shutdown_sec:
                        _handle_cavitation_shutdown(
                            predictor,
                            ts,
                            shutdown_sec,
                            v_mean,
                            p_mean,
                            t_mean,
                            current_display,
                            data,
                        )
                        health = 0.0
                        cavitation_start_time = None
                        cavitation_remaining = 0
                        last_printed_reason = None
                        continue
                else:
                    cavitation_start_time = None

                # Vibration interlock: only when cause is vibration (Zone D), not cavitation/choked/temp/debris
                is_vibration_reason = reason is None or (
                    reason
                    and "VIBRATION" in reason
                    and ("Zone D" in reason or "7.1" in reason or "INTERLOCK" in reason)
                )
                cause_is_vibration_interlock = trip_cause == TripCause.VIB_INTERLOCK
                if vib_display >= Config.VIBRATION_INTERLOCK_MMPS and (
                    is_vibration_reason or cause_is_vibration_interlock
                ):
                    _handle_vibration_interlock_shutdown(
                        predictor,
                        ts,
                        vib_display,
                        v_mean,
                        p_mean,
                        t_mean,
                        current_display,
                        data,
                        features_df,
                    )
                    health = 0.0
                    debris_impact_remaining = 0
                    mechanical_alert_printed = False
                    cavitation_remaining = 0  # Leave cavitation scenario so next tick uses nominal vib (no double shutdown)
                    last_printed_reason = None
                    continue

                # Temperature critical shutdown: only when cause is HIGH TEMPERATURE and T >= 75°C sustained.
                temp_shutdown_sec = getattr(
                    Config, "TEMP_CRITICAL_AUTO_SHUTDOWN_SEC", 10
                )
                temp_critical_c = getattr(Config, "TEMP_CRITICAL_C", 75.0)
                cause_is_overtemp = trip_cause == TripCause.OVERTEMP
                is_temp_critical_by_sensor = (
                    verdict == "CRITICAL"
                    and (is_temp_reason or cause_is_overtemp)
                    and t_mean >= temp_critical_c
                )
                if is_temp_critical_by_sensor:
                    temp_critical_ticks += 1
                    # Require 2 consecutive ticks (~6 s) so one noisy tick does not reset; cap at wall-clock 10 s
                    if temp_critical_start_time is None:
                        temp_critical_start_time = time.time()
                    elapsed = time.time() - temp_critical_start_time
                    trigger_sec = min(6.0, temp_shutdown_sec)
                    if temp_critical_ticks >= 2 and elapsed >= trigger_sec:
                        _handle_overtemp_shutdown(
                            predictor,
                            ts,
                            trigger_sec,
                            vib_display,
                            v_mean,
                            p_mean,
                            t_mean,
                            current_display,
                            data,
                        )
                        health = 0.0
                        temp_critical_start_time = None
                        temp_critical_ticks = 0
                        last_printed_reason = None
                        # Simulate cooldown: N steps (3 s each) before RESTART
                        temp_cooldown_steps_remaining = 3  # 9 s (3 × 3 s)
                        continue
                else:
                    # Reset timer and tick count when we are no longer in temp-critical by sensor
                    if not is_temp_critical_by_sensor:
                        temp_critical_start_time = None
                        temp_critical_ticks = 0

                iteration += 1

            # Keep ~3s between status lines (sleep remainder after iteration work)
            interval_sec = 3.0
            if last_status_print_time is not None:
                elapsed = time.time() - last_status_print_time
                time.sleep(max(0.0, interval_sec - elapsed))
            else:
                time.sleep(interval_sec)

    except KeyboardInterrupt:
        print("\n" + "-" * BANNER_WIDTH)
        print("🛑 Simulation stopped by operator. Closing Digital Twin.")


def _start_engine_subprocess():
    """Start PdM engine (app.main_app) as subprocess; return Popen instance or None on failure."""
    try:
        root = os.path.dirname(os.path.abspath(__file__))
        proc = subprocess.Popen(
            [sys.executable, "-m", "app.main_app"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            cwd=root,
        )
        return proc
    except Exception as e:
        print(f"⚠️ Failed to start PdM engine: {e}")
        return None


if __name__ == "__main__":
    engine_proc = None
    try:
        engine_proc = _start_engine_subprocess()
        if engine_proc is not None:
            print(
                "📡 PdM engine started (runs with simulation; stops when simulation stops)."
            )
            time.sleep(3)  # allow engine to connect to MQTT and subscribe
        run_simulation()
    except KeyboardInterrupt:
        pass
    finally:
        if engine_proc is not None:
            engine_proc.terminate()
            try:
                engine_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                engine_proc.kill()
                engine_proc.wait()
            print("📴 PdM engine stopped.")
