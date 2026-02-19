"""Rule-based CRITICAL/WARNING evaluators for pump predictor (ISO 10816-3, Operating Instruction).

Trip logic vs. shutdown logic
-----------------------------
This module is the single source of truth for *why* a state is CRITICAL/WARNING.
Each rule may set:
  - status / reason / display_prob – for human-readable diagnostics
  - trip_cause – primary structured trip code (DEBRIS_IMPACT, CAVITATION, CHOKED_DISCHARGE, OVERTEMP, VIB_INTERLOCK, ...)
  - alarm_causes – all active alarm-level cause codes on this step

simulate_failure.py then maps trip_cause + reason to specific shutdown actions
(DEBRIS_IMPACT_SHUTDOWN, CAVITATION_SHUTDOWN, CHOKED_DISCHARGE_SHUTDOWN, OVERTEMPERATURE_SHUTDOWN, VIBRATION_INTERLOCK),
so that priority of physical causes is defined here and shutdown behaviour is kept in the simulator.
"""
from dataclasses import dataclass, field
from typing import Any

from config.config import Config
from config.utils import config_float


class TripCause:
    """Canonical trip cause codes used by rules and simulator."""

    DEBRIS_IMPACT = "DEBRIS_IMPACT"
    CAVITATION = "CAVITATION"
    CHOKED_DISCHARGE = "CHOKED_DISCHARGE"
    OVERTEMP = "OVERTEMP"
    VIB_INTERLOCK = "VIB_INTERLOCK"


class AlarmCause:
    """Canonical alarm cause codes (includes trip causes where applicable)."""

    # Trip-level causes are also alarm causes
    DEBRIS_IMPACT = TripCause.DEBRIS_IMPACT
    CAVITATION = TripCause.CAVITATION
    CHOKED_DISCHARGE = TripCause.CHOKED_DISCHARGE
    OVERTEMP = TripCause.OVERTEMP
    VIB_INTERLOCK = TripCause.VIB_INTERLOCK

    # Additional alarm-only causes
    VIB_ZONE_D = "VIB_ZONE_D"
    VIB_ZONE_C = "VIB_ZONE_C"
    OVERTEMP_WARNING = "OVERTEMP_WARNING"


def _mechanical_message() -> str:
    """Return mechanical/debris alert message (single source for MechanicalRule and VibrationZoneRule)."""
    return getattr(Config, "MECHANICAL_DAMAGE_ALERT_MESSAGE", None) or getattr(
        Config, "DEBRIS_IMPACT_ALERT_MESSAGE", ""
    )


@dataclass
class RuleContext:
    """Immutable inputs and mutable outputs for rule evaluation (single step)."""

    # Smoothed (batch mean)
    vib_rms: float
    vib_crest: float
    current: float
    pressure: float
    temp: float
    # Latest sample (or first row if no latest_telemetry)
    latest_vib: float
    latest_crest: float
    latest_current: float
    latest_pressure: float
    latest_temp: float
    smoothed_prob: float
    prev_reason: str | None
    last_status: str | None
    debris_flag: bool
    # Mutable – main decision outputs
    status: str = "HEALTHY"
    reason: str | None = None
    display_prob: float = 0.0
    critical_low_vib_steps: int = 0  # in/out for hysteresis
    # Trip/Alarm metadata (for downstream consumers: simulator, notifier, etc.)
    trip_cause: str | None = None  # Primary trip cause code, e.g. "DEBRIS_IMPACT", "CAVITATION", "CHOKED_DISCHARGE"
    alarm_causes: list[str] = field(
        default_factory=list
    )  # All active alarm-level cause codes


class Rule:
    """Base for one rule; evaluate(ctx) may update ctx.status, ctx.reason, ctx.display_prob."""

    def evaluate(self, ctx: RuleContext) -> None:
        """Override: if rule applies, set ctx.status, ctx.reason, ctx.display_prob."""
        raise NotImplementedError


class MechanicalRule(Rule):
    """Debris impact / mechanical damage (stone hit): CRITICAL."""

    def evaluate(self, ctx: RuleContext) -> None:
        mechanical_msg = _mechanical_message()
        debris_crest_min = config_float(
            Config, "DEBRIS_IMPACT_CREST_MIN", Config.DEBRIS_IMPACT_CREST_MIN
        )
        vib_critical_mmps = config_float(
            Config, "VIBRATION_CRITICAL_MMPS", Config.VIBRATION_CRITICAL_MMPS
        )
        high_crest = (
            ctx.latest_crest >= debris_crest_min or ctx.vib_crest >= debris_crest_min
        )
        zone_d = ctx.vib_rms >= vib_critical_mmps or ctx.latest_vib >= vib_critical_mmps
        mechanical_hysteresis = ctx.prev_reason == mechanical_msg and zone_d
        if ctx.debris_flag:
            ctx.status = "CRITICAL"
            ctx.display_prob = max(ctx.display_prob, 0.95)
            ctx.reason = mechanical_msg
            ctx.trip_cause = ctx.trip_cause or TripCause.DEBRIS_IMPACT
            if AlarmCause.DEBRIS_IMPACT not in ctx.alarm_causes:
                ctx.alarm_causes.append(AlarmCause.DEBRIS_IMPACT)
        elif (
            high_crest and (ctx.status == "CRITICAL" or zone_d)
        ) or mechanical_hysteresis:
            ctx.status = "CRITICAL"
            ctx.display_prob = max(ctx.display_prob, 0.95)
            ctx.reason = mechanical_msg
            ctx.trip_cause = ctx.trip_cause or TripCause.DEBRIS_IMPACT
            if AlarmCause.DEBRIS_IMPACT not in ctx.alarm_causes:
                ctx.alarm_causes.append(AlarmCause.DEBRIS_IMPACT)


class CavitationRule(Rule):
    """Cavitation: high current, low pressure, high vib -> CRITICAL (uses Config.CAVITATION_* thresholds)."""

    def evaluate(self, ctx: RuleContext) -> None:
        if ctx.reason is not None:
            return
        cav_current_min = config_float(
            Config,
            "CAVITATION_CURRENT_MIN_AMP",
            Config.CAVITATION_CURRENT_MIN_AMP,
        )
        cav_pressure_max = config_float(
            Config,
            "CAVITATION_PRESSURE_MAX_BAR",
            Config.CAVITATION_PRESSURE_MAX_BAR,
        )
        cav_vib_min = config_float(
            Config,
            "CAVITATION_VIBRATION_MIN_MMPS",
            Config.CAVITATION_VIBRATION_MIN_MMPS,
        )
        smoothed = (
            ctx.current >= cav_current_min
            and ctx.pressure <= cav_pressure_max
            and ctx.vib_rms >= cav_vib_min
        )
        latest = (
            ctx.latest_current >= cav_current_min
            and ctx.latest_pressure <= cav_pressure_max
            and ctx.latest_vib >= cav_vib_min
        )
        exit_bar = config_float(
            Config,
            "CAVITATION_HYSTERESIS_EXIT_PRESSURE_BAR",
            Config.CAVITATION_HYSTERESIS_EXIT_PRESSURE_BAR,
        )
        hysteresis = (
            ctx.prev_reason == Config.CAVITATION_ALERT_MESSAGE
            and ctx.pressure <= exit_bar
            and ctx.latest_pressure <= exit_bar
            and (ctx.vib_rms >= cav_vib_min or ctx.latest_vib >= cav_vib_min)
            and (
                ctx.current >= cav_current_min or ctx.latest_current >= cav_current_min
            )
        )
        if smoothed or latest or hysteresis:
            ctx.status = "CRITICAL"
            ctx.display_prob = max(ctx.display_prob, 0.95)
            ctx.reason = Config.CAVITATION_ALERT_MESSAGE
            ctx.trip_cause = ctx.trip_cause or TripCause.CAVITATION
            if AlarmCause.CAVITATION not in ctx.alarm_causes:
                ctx.alarm_causes.append(AlarmCause.CAVITATION)


class ChokedRule(Rule):
    """Choked discharge: low current, high P, high T -> CRITICAL (uses Config.CHOKED_* thresholds)."""

    def evaluate(self, ctx: RuleContext) -> None:
        if ctx.reason is not None:
            return
        choked_cur_max = config_float(
            Config, "CHOKED_CURRENT_MAX_AMP", Config.CHOKED_CURRENT_MAX_AMP
        )
        choked_p_min = config_float(
            Config, "CHOKED_PRESSURE_MIN_BAR", Config.CHOKED_PRESSURE_MIN_BAR
        )
        choked_temp_min = config_float(
            Config, "CHOKED_TEMP_MIN_C", Config.CHOKED_TEMP_MIN_C
        )
        smoothed = (
            ctx.current <= choked_cur_max
            and ctx.pressure >= choked_p_min
            and ctx.temp >= choked_temp_min
        )
        latest = (
            ctx.latest_current <= choked_cur_max
            and ctx.latest_pressure >= choked_p_min
            and ctx.latest_temp >= choked_temp_min
        )
        if smoothed or latest:
            ctx.status = "CRITICAL"
            ctx.display_prob = max(ctx.display_prob, 0.95)
            _chk_msg = Config.CHOKED_ALERT_MESSAGE
            ctx.reason = (
                _chk_msg.format(
                    pressure=ctx.latest_pressure,
                    temp=ctx.latest_temp,
                    current=ctx.latest_current,
                )
                if "{pressure" in _chk_msg
                or "{temp" in _chk_msg
                or "{current" in _chk_msg
                else _chk_msg
            )
            ctx.trip_cause = ctx.trip_cause or TripCause.CHOKED_DISCHARGE
            if AlarmCause.CHOKED_DISCHARGE not in ctx.alarm_causes:
                ctx.alarm_causes.append(AlarmCause.CHOKED_DISCHARGE)


class DegradationRule(Rule):
    """Impeller wear / degradation: low current + low pressure -> WARNING (Zone C) per Config.DEGRADATION_*."""

    def evaluate(self, ctx: RuleContext) -> None:
        if ctx.reason is not None or ctx.status == "CRITICAL":
            return
        deg_current_max = config_float(
            Config,
            "DEGRADATION_CURRENT_MAX_AMP",
            Config.DEGRADATION_CURRENT_MAX_AMP,
        )
        deg_pressure_max = config_float(
            Config,
            "DEGRADATION_PRESSURE_MAX_BAR",
            Config.DEGRADATION_PRESSURE_MAX_BAR,
        )
        smoothed = ctx.current <= deg_current_max and ctx.pressure <= deg_pressure_max
        latest = (
            ctx.latest_current <= deg_current_max
            and ctx.latest_pressure <= deg_pressure_max
        )
        if smoothed and latest:
            ctx.status = "WARNING"
            ctx.display_prob = max(ctx.display_prob, 0.55)
            _deg_msg = Config.DEGRADATION_ALERT_MESSAGE
            ctx.reason = (
                _deg_msg.format(
                    pressure=ctx.latest_pressure, current=ctx.latest_current
                )
                if "{pressure" in _deg_msg or "{current" in _deg_msg
                else _deg_msg
            )


class DegradationHysteresisRule(Rule):
    """Stay WARNING until current/pressure above exit zone."""

    def evaluate(self, ctx: RuleContext) -> None:
        if ctx.last_status != "WARNING" or ctx.status != "HEALTHY":
            return
        deg_current_max = config_float(
            Config,
            "DEGRADATION_CURRENT_MAX_AMP",
            Config.DEGRADATION_CURRENT_MAX_AMP,
        )
        deg_pressure_max = config_float(
            Config,
            "DEGRADATION_PRESSURE_MAX_BAR",
            Config.DEGRADATION_PRESSURE_MAX_BAR,
        )
        exit_current = deg_current_max + config_float(
            Config,
            "DEGRADATION_HYSTERESIS_CURRENT_AMP",
            Config.DEGRADATION_HYSTERESIS_CURRENT_AMP,
        )
        exit_pressure = deg_pressure_max + config_float(
            Config,
            "DEGRADATION_HYSTERESIS_PRESSURE_BAR",
            Config.DEGRADATION_HYSTERESIS_PRESSURE_BAR,
        )
        if (
            ctx.current <= exit_current
            or ctx.pressure <= exit_pressure
            or ctx.latest_current <= exit_current
            or ctx.latest_pressure <= exit_pressure
        ):
            ctx.status = "WARNING"
            ctx.display_prob = max(ctx.display_prob, 0.55)
            _deg_msg = Config.DEGRADATION_ALERT_MESSAGE
            ctx.reason = (
                _deg_msg.format(
                    pressure=ctx.latest_pressure, current=ctx.latest_current
                )
                if "{pressure" in _deg_msg or "{current" in _deg_msg
                else _deg_msg
            )


class TemperatureRule(Rule):
    """Temperature rule: CRITICAL/WARNING based on Config.TEMP_CRITICAL_C and Config.TEMP_WARNING_C."""

    def evaluate(self, ctx: RuleContext) -> None:
        if ctx.reason is not None:
            return
        temp_critical_c = config_float(
            Config, "TEMP_CRITICAL_C", Config.TEMP_CRITICAL_C
        )
        temp_warning_c = config_float(Config, "TEMP_WARNING_C", Config.TEMP_WARNING_C)
        if ctx.temp >= temp_critical_c or ctx.latest_temp >= temp_critical_c:
            ctx.status = "CRITICAL"
            ctx.display_prob = max(ctx.display_prob, 0.85)
            _msg = getattr(
                Config,
                "TEMP_ALERT_MESSAGE",
                "HIGH TEMPERATURE (Zone D): {temp:.1f}°C — inspect cooling and flow rate.",
            )
            ctx.reason = _msg.format(temp=ctx.latest_temp) if "{temp" in _msg else _msg
            ctx.trip_cause = ctx.trip_cause or TripCause.OVERTEMP
            if AlarmCause.OVERTEMP not in ctx.alarm_causes:
                ctx.alarm_causes.append(AlarmCause.OVERTEMP)
        elif (
            ctx.status != "CRITICAL"
            and (ctx.temp >= temp_warning_c or ctx.latest_temp >= temp_warning_c)
            and ctx.status == "HEALTHY"
        ):
            ctx.status = "WARNING"
            ctx.display_prob = max(ctx.display_prob, 0.55)
            _msg = getattr(
                Config,
                "TEMP_WARNING_ALERT_MESSAGE",
                "HIGH TEMPERATURE (Zone C): {temp:.1f}°C — inspect cooling and flow rate.",
            )
            ctx.reason = _msg.format(temp=ctx.latest_temp) if "{temp" in _msg else _msg
            if AlarmCause.OVERTEMP_WARNING not in ctx.alarm_causes:
                ctx.alarm_causes.append(AlarmCause.OVERTEMP_WARNING)


class OverloadRule(Rule):
    """Motor overload: current >= Config.OVERLOAD_CURRENT_MIN_AMP -> WARNING."""

    def evaluate(self, ctx: RuleContext) -> None:
        if ctx.reason is not None or ctx.status != "HEALTHY":
            return
        overload_amp = config_float(
            Config,
            "OVERLOAD_CURRENT_MIN_AMP",
            Config.OVERLOAD_CURRENT_MIN_AMP,
        )
        if ctx.current >= overload_amp or ctx.latest_current >= overload_amp:
            ctx.status = "WARNING"
            ctx.display_prob = max(ctx.display_prob, 0.55)
            ctx.reason = getattr(
                Config,
                "OVERLOAD_ALERT_MESSAGE",
                "Motor overload: inspect for motor strain.",
            )


class HighPressureRule(Rule):
    """High discharge pressure with normal flow (not choked) -> WARNING per Config.PRESSURE_HIGH_WARNING_BAR."""

    def evaluate(self, ctx: RuleContext) -> None:
        if ctx.reason is not None or ctx.status != "HEALTHY":
            return
        high_p_bar = config_float(
            Config,
            "PRESSURE_HIGH_WARNING_BAR",
            Config.PRESSURE_HIGH_WARNING_BAR,
        )
        choked_current_max = config_float(
            Config, "CHOKED_CURRENT_MAX_AMP", Config.CHOKED_CURRENT_MAX_AMP
        )
        not_choked = (
            ctx.current > choked_current_max and ctx.latest_current > choked_current_max
        )
        if (
            ctx.pressure >= high_p_bar or ctx.latest_pressure >= high_p_bar
        ) and not_choked:
            ctx.status = "WARNING"
            ctx.display_prob = max(ctx.display_prob, 0.55)
            ctx.reason = getattr(Config, "PRESSURE_HIGH_ALERT_MESSAGE", "")


class AirIngestionRule(Rule):
    """Air ingestion: high crest + Zone C vib -> WARNING per Config.AIR_INGESTION_*."""

    def evaluate(self, ctx: RuleContext) -> None:
        if ctx.reason is not None or ctx.status != "HEALTHY":
            return
        air_crest_min = config_float(
            Config,
            "AIR_INGESTION_VIB_CREST_MIN",
            Config.AIR_INGESTION_VIB_CREST_MIN,
        )
        air_vib_min = config_float(
            Config,
            "AIR_INGESTION_VIB_RMS_MIN_MMPS",
            Config.AIR_INGESTION_VIB_RMS_MIN_MMPS,
        )
        air_ingestion = (
            ctx.vib_crest >= air_crest_min or ctx.latest_crest >= air_crest_min
        ) and (ctx.vib_rms >= air_vib_min or ctx.latest_vib >= air_vib_min)
        if air_ingestion:
            ctx.status = "WARNING"
            ctx.display_prob = max(ctx.display_prob, 0.55)
            ctx.reason = Config.AIR_INGESTION_ALERT_MESSAGE


class VibrationZoneRule(Rule):
    """ISO 10816-3: Zone D (>= 7.1) -> CRITICAL; Zone C (>= 5.5 + risk) -> WARNING."""

    def evaluate(self, ctx: RuleContext) -> None:
        vib_critical_mmps = config_float(
            Config, "VIBRATION_CRITICAL_MMPS", Config.VIBRATION_CRITICAL_MMPS
        )
        mechanical_msg = _mechanical_message()
        if ctx.vib_rms >= vib_critical_mmps or ctx.latest_vib >= vib_critical_mmps:
            ctx.status = "CRITICAL"
            ctx.display_prob = max(ctx.display_prob, 0.85)
            is_choked = ctx.reason and ctx.reason.strip().startswith("CHOKED DISCHARGE")
            is_temp = ctx.reason is not None and "HIGH TEMPERATURE" in ctx.reason
            if (
                ctx.reason not in (mechanical_msg, Config.CAVITATION_ALERT_MESSAGE)
                and not is_choked
                and not is_temp
            ):
                ctx.reason = getattr(Config, "VIBRATION_ZONE_D_ALERT_MESSAGE", "")
            # Zone D vibration is always treated as at least an ALARM-level cause
            if AlarmCause.VIB_ZONE_D not in ctx.alarm_causes:
                ctx.alarm_causes.append(AlarmCause.VIB_ZONE_D)
        else:
            vib_warning_entry = config_float(
                Config,
                "VIBRATION_WARNING_ENTRY_MMPS",
                Config.VIBRATION_WARNING_ENTRY_MMPS,
            )
            prob_min = config_float(
                Config,
                "PROB_MIN_FOR_VIBRATION_WARNING",
                Config.PROB_MIN_FOR_VIBRATION_WARNING,
            )
            if (
                ctx.vib_rms >= vib_warning_entry
                and ctx.latest_vib >= vib_warning_entry
                and ctx.smoothed_prob >= prob_min
                and ctx.status == "HEALTHY"
            ):
                ctx.status = "WARNING"
                ctx.reason = getattr(Config, "VIBRATION_ZONE_C_ALERT_MESSAGE", "")
                if AlarmCause.VIB_ZONE_C not in ctx.alarm_causes:
                    ctx.alarm_causes.append(AlarmCause.VIB_ZONE_C)


class VibrationHysteresisRule(Rule):
    """Stay WARNING until vib < 4.5; stay CRITICAL until N low-vib steps."""

    def evaluate(self, ctx: RuleContext) -> None:
        hysteresis_warning_exit = config_float(
            Config,
            "VIBRATION_HYSTERESIS_EXIT_WARNING_MMPS",
            Config.VIBRATION_HYSTERESIS_EXIT_WARNING_MMPS,
        )
        if (
            ctx.last_status == "WARNING"
            and ctx.status == "HEALTHY"
            and (
                ctx.vib_rms >= hysteresis_warning_exit
                or ctx.latest_vib >= hysteresis_warning_exit
            )
        ):
            ctx.status = "WARNING"
            if ctx.reason is None:
                ctx.reason = getattr(Config, "VIBRATION_ZONE_C_ALERT_MESSAGE", "")
        hysteresis_exit = config_float(
            Config,
            "VIBRATION_HYSTERESIS_EXIT_CRITICAL_MMPS",
            Config.VIBRATION_HYSTERESIS_EXIT_CRITICAL_MMPS,
        )
        min_low_steps = int(
            config_float(
                Config,
                "CRITICAL_EXIT_MIN_LOW_VIB_STEPS",
                Config.CRITICAL_EXIT_MIN_LOW_VIB_STEPS,
            )
        )
        if ctx.last_status == "CRITICAL" and ctx.status == "WARNING":
            if ctx.vib_rms >= hysteresis_exit or ctx.latest_vib >= hysteresis_exit:
                ctx.status = "CRITICAL"
                ctx.critical_low_vib_steps = 0
            else:
                ctx.critical_low_vib_steps += 1
                if ctx.critical_low_vib_steps < min_low_steps:
                    ctx.status = "CRITICAL"
                else:
                    ctx.critical_low_vib_steps = 0


class InterlockRule(Rule):
    """Vibration >= interlock limit (9.0 mm/s) -> CRITICAL 99.9%."""

    def evaluate(self, ctx: RuleContext) -> None:
        vib_interlock_mmps = config_float(
            Config,
            "VIBRATION_INTERLOCK_MMPS",
            Config.VIBRATION_INTERLOCK_MMPS,
        )
        vib_critical_mmps = config_float(
            Config, "VIBRATION_CRITICAL_MMPS", Config.VIBRATION_CRITICAL_MMPS
        )
        if ctx.vib_rms >= vib_interlock_mmps:
            ctx.status = "CRITICAL"
            ctx.display_prob = 0.999
            # Do not overwrite cavitation or temperature: keep cause so shutdown type is correct
            if (
                ctx.reason is None or "HIGH TEMPERATURE" not in ctx.reason
            ) and ctx.reason != Config.CAVITATION_ALERT_MESSAGE:
                ctx.reason = getattr(Config, "VIBRATION_INTERLOCK_ALERT_MESSAGE", "")
            # Trip on vibration interlock only if no higher-priority trip_cause has been set yet
            if ctx.trip_cause is None:
                ctx.trip_cause = TripCause.VIB_INTERLOCK
            if AlarmCause.VIB_INTERLOCK not in ctx.alarm_causes:
                ctx.alarm_causes.append(AlarmCause.VIB_INTERLOCK)
        elif (
            ctx.status in ("CRITICAL", "WARNING")
            and vib_critical_mmps <= ctx.vib_rms < vib_interlock_mmps
            and vib_interlock_mmps > vib_critical_mmps
        ):
            denom = vib_interlock_mmps - vib_critical_mmps
            ramp = (ctx.vib_rms - vib_critical_mmps) / denom if denom > 0 else 0.0
            ctx.display_prob = max(ctx.display_prob, 0.85 + ramp * 0.15)
            ctx.display_prob = min(1.0, ctx.display_prob)


class FinalCleanupRule(Rule):
    """CRITICAL min display 0.85; replace MAINTENANCE reason when CRITICAL; risk hysteresis."""

    def evaluate(self, ctx: RuleContext) -> None:
        if ctx.status == "CRITICAL":
            ctx.display_prob = max(ctx.display_prob, 0.85)
            if ctx.reason and ctx.reason.strip().startswith("MAINTENANCE (Zone C)"):
                ctx.reason = getattr(Config, "HIGH_RISK_CRITICAL_ALERT_MESSAGE", "")
        prob_hyst = config_float(
            Config,
            "PROB_HYSTERESIS_EXIT_WARNING",
            Config.PROB_HYSTERESIS_EXIT_WARNING,
        )
        if (
            ctx.last_status == "WARNING"
            and ctx.status == "HEALTHY"
            and ctx.smoothed_prob >= prob_hyst
        ):
            ctx.status = "WARNING"
            if ctx.reason is None:
                ctx.reason = getattr(Config, "ELEVATED_RISK_ALERT_MESSAGE", "")


# Order defines priority (first rule that sets status/reason wins where applicable)
RULES: list[Rule] = [
    MechanicalRule(),
    CavitationRule(),
    ChokedRule(),
    DegradationRule(),
    DegradationHysteresisRule(),
    TemperatureRule(),
    OverloadRule(),
    HighPressureRule(),
    AirIngestionRule(),
    VibrationZoneRule(),
    VibrationHysteresisRule(),
    InterlockRule(),
    FinalCleanupRule(),
]
