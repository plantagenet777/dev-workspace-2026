import os
from pathlib import Path
from dotenv import load_dotenv

# Load variables from .env file when present (config package)
load_dotenv()


class _ConfigMeta(type):
    """Metaclass: environment-dependent attributes are evaluated on each access."""

    @property
    def PUMP_ID(cls) -> str:
        return os.getenv("PUMP_ID", "PUMP_01")

    @property
    def SECTION_ID(cls) -> str:
        return os.getenv("SECTION_ID", "PLANT_SECTION_01")

    @property
    def TOPIC_TELEMETRY(cls) -> str:
        return f"pump/monitor/{cls.PUMP_ID}/telemetry"

    @property
    def TOPIC_ALERTS(cls) -> str:
        return f"pump/monitor/{cls.PUMP_ID}/alerts"

    @property
    def TOPIC_STATUS(cls) -> str:
        return f"pump/monitor/{cls.PUMP_ID}/status"

    @property
    def MQTT_BROKER(cls) -> str:
        return os.getenv("MQTT_BROKER", "10.20.30.45")

    @property
    def MQTT_PORT(cls) -> int:
        return int(os.getenv("MQTT_PORT", "8883"))

    @property
    def MQTT_USE_TLS(cls) -> bool:
        return os.getenv("MQTT_USE_TLS", "true").lower() in ("true", "1", "yes")

    @property
    def MQTT_TLS_INSECURE(cls) -> bool:
        """Disable TLS hostname verification. Must be False in production."""
        return os.getenv("MQTT_TLS_INSECURE", "false").lower() in ("true", "1", "yes")

    @property
    def MQTT_KEEPALIVE(cls) -> int:
        return 60

    # MQTT resilience: reconnect with exponential backoff; alert if no telemetry for N seconds
    MQTT_RECONNECT_BACKOFF_BASE_SEC = 1.0
    MQTT_RECONNECT_MAX_BACKOFF_SEC = 60.0
    MQTT_DISCONNECT_ALERT_SEC = 90  # Warn if no message received for this long

    @property
    def TELEGRAM_TOKEN(cls) -> str:
        return os.getenv("TG_TOKEN", "")

    @property
    def TELEGRAM_CHAT_ID(cls) -> str:
        return os.getenv("TG_CHAT_ID", "")

    @property
    def CERT_DIR(cls) -> str:
        return os.getenv("CERT_DIR", str(cls.BASE_DIR / "certs"))

    @property
    def CA_CERT(cls) -> str:
        return os.path.join(cls.CERT_DIR, "ca.crt")

    @property
    def CLIENT_CERT(cls) -> str:
        return os.path.join(cls.CERT_DIR, "client.crt")

    @property
    def CLIENT_KEY(cls) -> str:
        return os.path.join(cls.CERT_DIR, "client.key")

    @property
    def LOG_DIR(cls) -> str:
        return os.getenv("LOG_DIR", str(cls.BASE_DIR / "logs"))

    @property
    def TELEMETRY_LOG_PATH(cls) -> str:
        return os.path.join(cls.LOG_DIR, "telemetry_history.csv")

    @property
    def ALERTS_LOG_PATH(cls) -> str:
        return os.path.join(cls.LOG_DIR, "alerts_history.csv")

    @property
    def APP_STATUS_PATH(cls) -> str:
        return os.path.join(cls.LOG_DIR, "app_status.log")

    @property
    def MODEL_VERSION(cls) -> str:
        """Model artifact version (e.g. v1, v2); set via env MODEL_VERSION."""
        return os.getenv("MODEL_VERSION", "v1")

    @property
    def MODEL_PATH(cls) -> str:
        return str(cls.BASE_DIR / "models" / f"pump_rf_{cls.MODEL_VERSION}.joblib")

    @property
    def SCALER_PATH(cls) -> str:
        return str(cls.BASE_DIR / "models" / f"scaler_{cls.MODEL_VERSION}.joblib")


class Config(metaclass=_ConfigMeta):
    """Centralized configuration for the pump predictive maintenance engine.

    Attributes that depend on PUMP_ID and environment variables (topics, paths,
    MQTT, TLS, etc.) are computed on each access, so multiple pumps and ID
    changes work correctly without restart.
    """

    # --- PATHS (static) ---
    BASE_DIR = Path(__file__).resolve().parent.parent

    # --- MODEL PARAMETERS (static) ---
    FEATURE_NAMES = [
        "vib_rms",
        "vib_crest",
        "vib_kurtosis",
        "current",
        "pressure",
        "cavitation_index",
        "temp",
        "temp_delta",
    ]

    # --- PUMP PROFILE & THRESHOLDS (static) ---
    # PUMP_PROFILE allows selecting a set of thresholds for a given pump type without
    # changing the protection logic. Defaults are tuned for Warman-type slurry pumps.
    PUMP_PROFILE = os.getenv("PUMP_PROFILE", "WARMAN_SLURRY")
    PROB_CRITICAL = 0.85
    PROB_WARNING = 0.60
    # Exit WARNING only when smoothed risk drops below this (avoids HEALTHY after one step at 55% -> 13%).
    PROB_HYSTERESIS_EXIT_WARNING = 0.25
    # During startup/transient phase use higher bar for CRITICAL to reduce false positives.
    STARTUP_ITERATIONS = 3
    PROB_CRITICAL_STARTUP = 0.90
    # Rolling window: number of last feature vectors to average before inference (reduces jitter).
    SMOOTHING_WINDOW_SIZE = 3
    # Number of last risk values averaged for final smoothed probability (faster decay when increased).
    RISK_HISTORY_SIZE = 3
    # Asymmetric smoothing: alpha when risk rises (fast response) / falls (faster decay = exit WARNING sooner).
    SMOOTH_ALPHA_RISING = 0.7
    SMOOTH_ALPHA_FALLING = 0.65
    # When instant risk is already high, use higher alpha so smoothed value can reach 95–100%.
    SMOOTH_ALPHA_VERY_HIGH = 0.92
    SMOOTH_HIGH_RISK_THRESHOLD = 0.70
    # ISO 10816-3 (Group 1, rigid support): Zone B/C = 4.5, Zone C/D = 7.1 mm/s RMS.
    # vib_rms is assumed to be velocity (mm/s) from bearing housing or equivalent non-rotating part.
    # Boundary 7.1 belongs to Zone D only: Zone C = 4.5 <= V < 7.1, Zone D = V >= 7.1 (industrial practice).
    VIBRATION_WARNING_MMPS = (
        4.5  # Zone C start (B/C boundary); exit WARNING when V < 4.5
    )
    # Enter WARNING from vibration only when both smoothed and latest >= this (avoids flicker at 4.5–5.0).
    # ISO 10816-3 Zone C starts at 4.5; we use 5.5 as operational entry + PROB_MIN for stability.
    VIBRATION_WARNING_ENTRY_MMPS = 5.5  # Clearly in Zone C; exit WARNING when vib < 4.5
    PROB_MIN_FOR_VIBRATION_WARNING = (
        0.15  # Avoid WARNING from vibration when risk < 15%
    )
    VIBRATION_CRITICAL_MMPS = (
        7.1  # Zone D start (ISO 10816-3 C/D boundary): CRITICAL, unacceptable
    )
    VIBRATION_HYSTERESIS_EXIT_CRITICAL_MMPS = (
        6.0  # Stay CRITICAL until vib < this (dead zone below 7.1)
    )
    CRITICAL_EXIT_MIN_LOW_VIB_STEPS = 5  # Consecutive steps with low vib before allowing CRITICAL -> WARNING (avoids brief dip 7.9→4.2→8.1)
    VIBRATION_HYSTERESIS_EXIT_WARNING_MMPS = (
        4.5  # Stay WARNING until vib < 4.5 (back in Zone B)
    )
    # Vibration interlock is intentionally set ABOVE the Zone D entry (7.1 mm/s),
    # so that 7.1–INTERLOCK is a CRITICAL alarm range and only higher vibration
    # produces an automatic trip. For Warman slurry machines we use 9.0 mm/s.
    VIBRATION_INTERLOCK_MMPS = 9.0
    VIBRATION_ZONE_D_ALERT_MESSAGE = " VIBRATION (Zone D): ≥7.1 mm/s unacceptable; reduce load or stop for inspection."
    VIBRATION_ZONE_C_ALERT_MESSAGE = (
        " VIBRATION (Zone C): plan maintenance; monitor trend."
    )
    VIBRATION_INTERLOCK_ALERT_MESSAGE = (
        " VIBRATION INTERLOCK: limit exceeded; stop and inspect."
    )
    ELEVATED_RISK_ALERT_MESSAGE = "Elevated risk (model): continue monitoring."
    # High-risk model output is **advisory only**: it never triggers an automatic shutdown by itself.
    # All automatic trips are driven by physical/engineering causes (vibration, cavitation, choked, overtemp, debris).
    HIGH_RISK_CRITICAL_ALERT_MESSAGE = "High risk (model): inspect equipment."
    # Cavitation protocol: vibration RMS > 9.0 and pressure < 4.0 bar (Operating Instruction).
    CAVITATION_CURRENT_MIN_AMP = (
        54.0  # Flow proxy: current above normal (healthy 44–48 A)
    )
    CAVITATION_PRESSURE_MAX_BAR = 4.0  # Inlet pressure dropped (risk of vapor pressure)
    CAVITATION_HYSTERESIS_EXIT_PRESSURE_BAR = 4.5
    CAVITATION_VIBRATION_MIN_MMPS = (
        9.0  # Operating Instruction: exceeds 9.0 mm/s for cavitation
    )
    # Operating Instruction: healthy cavitation_index < 0.8 (reference for logging/analytics).
    CAVITATION_INDEX_MAX_HEALTHY = 0.8
    CAVITATION_ALERT_MESSAGE = " CAVITATION (Zone D): check inlet valve / sump level."
    # Debris impact / mechanical damage (Warman slurry): Zone D – recommend inspect impeller, liner, wear parts.
    MECHANICAL_DAMAGE_ALERT_MESSAGE = " DEBRIS IMPACT (Zone D): inspect impeller, wear plate and liner; do not restart without inspection if damage suspected."
    DEBRIS_IMPACT_ALERT_MESSAGE = " DEBRIS IMPACT (Zone D): mechanical shock; inspect impeller and wear parts (Warman slurry service)."
    DEBRIS_IMPACT_CREST_MIN = 6.0  # Crest factor above this with high vib suggests impact rather than sustained cavitation
    # Auto shutdown after this many seconds of sustained cavitation (simulate_failure only).
    CAVITATION_AUTO_SHUTDOWN_SEC = 10
    # Simulation: probability per iteration to start a cavitation scenario (I≥54, P≤4, V≥9).
    CAVITATION_SCENARIO_PROB = 0.022  # Higher so cavitation block triggers more often
    CAVITATION_SCENARIO_STEPS = (
        5  # Duration in 3s steps (~15 s), so sustained ≥10 s reliably triggers shutdown
    )
    # Operating Instruction: Underload < 40 A; low pressure < 5.2 bar. Degradation / maintenance Zone C.
    DEGRADATION_CURRENT_MAX_AMP = 40.0  # Underload: inspect for dry run
    DEGRADATION_PRESSURE_MAX_BAR = 5.2  # Low pressure: check intake
    # {pressure} and {current} are filled in predictor with actual values that triggered the alert.
    DEGRADATION_ALERT_MESSAGE = " MAINTENANCE (Zone C): P={pressure:.1f} bar, I={current:.1f} A — inspect impeller & wear plate, assess on shutdown."
    # Hysteresis: stay WARNING until current/pressure clearly above zone (avoids HEALTHY/WARNING flicker).
    DEGRADATION_HYSTERESIS_CURRENT_AMP = (
        2.0  # Exit WARNING only when current > DEGRADATION_CURRENT_MAX_AMP + this
    )
    DEGRADATION_HYSTERESIS_PRESSURE_BAR = (
        0.3  # Exit WARNING only when pressure > DEGRADATION_PRESSURE_MAX_BAR + this
    )
    # Operating Instruction: Choked = Current < 38 A and Pressure > 7 bar. Do not restart until temp < 50°C.
    CHOKED_CURRENT_MAX_AMP = 38.0  # Current drop (blockage / closed valve)
    CHOKED_PRESSURE_MIN_BAR = 7.0  # Discharge pressure surge
    CHOKED_TEMP_MIN_C = 70.0  # Overheating at gland seal / casing
    CHOKED_RESTART_TEMP_MAX_C = 50.0  # Do not restart until temp drops below this
    # {pressure}, {temp}, {current} are filled in predictor with values that triggered the alert.
    CHOKED_ALERT_MESSAGE = " CHOKED DISCHARGE: P={pressure:.1f} bar, T={temp:.1f}°C, I={current:.1f} A — low flow + high P/T. Overheat risk. Immediate stop."
    # Operating Instruction (not ISO 10816-3): Temperature Warning > 60°C, Critical > 75°C.
    TEMP_WARNING_C = 60.0
    TEMP_CRITICAL_C = 75.0
    # Zone C/D by analogy to ISO 10816-3 severity. {temp} is filled with actual value in predictor.
    TEMP_WARNING_ALERT_MESSAGE = (
        " HIGH TEMPERATURE (Zone C): {temp:.1f}°C — inspect cooling and flow rate."
    )
    TEMP_ALERT_MESSAGE = (
        " HIGH TEMPERATURE (Zone D): {temp:.1f}°C — inspect cooling and flow rate."
    )
    # Auto shutdown when critical temperature sustained (simulate_failure); do not restart until T < this.
    TEMP_CRITICAL_AUTO_SHUTDOWN_SEC = (
        10  # Shutdown after this many seconds of T >= TEMP_CRITICAL_C
    )
    TEMP_CRITICAL_RESTART_TEMP_MAX_C = (
        50.0  # Do not restart until temp drops below this (same as choked practice)
    )
    # Operating Instruction (not ISO 10816-3): Current > 50 A = overload (motor strain). < 40 A = underload.
    OVERLOAD_CURRENT_MIN_AMP = 50.0
    OVERLOAD_ALERT_MESSAGE = "Motor overload: inspect for motor strain."
    # Operating Instruction (not ISO 10816-3): Pressure > 7.0 bar with normal flow = check discharge valves.
    PRESSURE_HIGH_WARNING_BAR = 7.0
    PRESSURE_HIGH_ALERT_MESSAGE = "High discharge pressure: check discharge valves."
    # Air ingestion (vortex in sump): impulsive vibration + high vib = fluctuating P/flow, axial impacts risk.
    AIR_INGESTION_VIB_CREST_MIN = 5.5  # Crest factor: impulsive / peaky vibration
    AIR_INGESTION_VIB_RMS_MIN_MMPS = (
        4.5  # At least Zone C (ISO 10816-3) for air ingestion WARNING
    )
    AIR_INGESTION_ALERT_MESSAGE = " AIR INGESTION: check sump level, reduce speed."
    # Reference sensor means per zone (ISO 10816-3); shared by train_and_save and simulate_failure.
    # v: Zone A/B boundary 2.8, Zone C typical 5–6, Zone D >7.1
    HEALTHY_MEANS = {"v": 2.8, "p": 6.0, "t": 42.0}  # Zone B
    WARNING_MEANS = {"v": 5.8, "p": 5.2, "t": 68.0}  # Zone C
    CRITICAL_MEANS = {"v": 12.5, "p": 2.5, "t": 88.0}  # Zone D
    # Telemetry window size for feature computation (kurtosis, RMS, etc.); 30 records for stable metrics.
    FEATURE_WINDOW_SIZE = 30
    # Run inference pipeline every N new MQTT messages (when buffer is full).
    MQTT_BATCH_SIZE = 5

    # --- SIMULATION SCENARIO PROBABILITIES / DURATIONS (simulate_failure.py) ---
    # Central place for digital-twin scenario tuning; simulate_failure.py reads these via Config.
    DEGRADATION_SCENARIO_PROB = 0.008
    DEGRADATION_SCENARIO_STEPS = 3
    CHOKED_SCENARIO_PROB = 0.003
    CHOKED_SCENARIO_STEPS = 3
    AIR_INGESTION_SCENARIO_PROB = 0.008
    AIR_INGESTION_SCENARIO_STEPS = 3
    DEBRIS_IMPACT_SCENARIO_PROB = 0.002

    # --- SIMULATION SHUTDOWN MESSAGES (simulate_failure.py) ---
    # Single source for shutdown/repair/manual texts; use .format() for placeholders where noted.
    DEBRIS_IMPACT_SHUTDOWN_MESSAGE = (
        "Debris impact (stone hit, Zone D). Immediate stop."
    )
    DEBRIS_IMPACT_REPAIR_MESSAGE = "Inspect impeller, wear plate and liner; clear suction. Do not restart without inspection."
    DEBRIS_IMPACT_MANUAL_CLEARANCE_MESSAGE = (
        "Restart only after manual inspection and operator clearance."
    )
    CHOKED_DISCHARGE_SHUTDOWN_MESSAGE = (
        "Choked discharge (low flow + high P/T). Overheat risk. Immediate stop."
    )
    CHOKED_DISCHARGE_REPAIR_MESSAGE = (
        "Check discharge valve / line. Cool down before restart."
    )
    CAVITATION_SHUTDOWN_MESSAGE = (
        "Cavitation sustained {shutdown_sec} s. Check inlet valve / sump level."
    )
    CAVITATION_REPAIR_MESSAGE = (
        "Check inlet valve / sump level. Replacing impeller if damaged."
    )
    VIBRATION_INTERLOCK_SHUTDOWN_MESSAGE = "Vibration interlock (Zone D). Vibration {vib_display:.2f} mm/s — limit exceeded."
    VIBRATION_INTERLOCK_REPAIR_MESSAGE = (
        "Damage detected. Replacing impeller & bearings..."
    )
    OVERTEMPERATURE_SHUTDOWN_MESSAGE = "Elevated temperature — overtemperature (T >= 75°C sustained {temp_shutdown_sec} s)."
    OVERTEMPERATURE_REPAIR_MESSAGE = (
        "Inspect cooling and flow. Do not restart until T < {restart_temp_max:.0f}°C."
    )
    OVERTEMPERATURE_AND_VIBRATION_SHUTDOWN_MESSAGE = (
        "Elevated temperature and vibration interlock (Zone D) — "
        "T >= 75°C sustained {temp_shutdown_sec} s. Vibration {vib_display:.2f} mm/s — limit exceeded."
    )
    OVERTEMPERATURE_AND_VIBRATION_REPAIR_MESSAGE = (
        "Inspect cooling and flow; check for damage (impeller, bearings). "
        "Do not restart until T < {restart_temp_max:.0f}°C."
    )

    # Fallback when CRITICAL but reason is empty (e.g. mock in tests, missing config).
    # Printed every tick; no automatic block is executed.
    UNKNOWN_CRITICAL_FALLBACK_MESSAGE = (
        "No reason set; automatic block skipped. Check rules/config."
    )

    # --- INFERENCE RETRY (static) ---
    INFERENCE_RETRY_ATTEMPTS = 3  # Retries on transient inference failure
    INFERENCE_RETRY_DELAY_SEC = 0.5  # Base delay between attempts (exponential backoff)

    # --- TELEMETRY VALIDATION (static) ---
    # Min/max allowed raw values before DSP/ML; out-of-range records are rejected (INVALID_RANGE).
    TELEMETRY_VIB_RMS_MIN = 0.0
    TELEMETRY_VIB_RMS_MAX = 25.0
    TELEMETRY_PRESSURE_MIN = 0.0
    TELEMETRY_PRESSURE_MAX = 15.0
    TELEMETRY_TEMP_MIN = -20.0
    TELEMETRY_TEMP_MAX = 120.0
    TELEMETRY_CURRENT_MIN = 0.0
    TELEMETRY_CURRENT_MAX = 80.0
    TELEMETRY_CAVITATION_INDEX_MIN = 0.0
    TELEMETRY_CAVITATION_INDEX_MAX = 50.0

    # --- SIGNAL PROCESSING (static) ---
    # Zone decisions (ISO 10816-3) use overall RMS over the feature window. For strict ISO alignment,
    # set USE_ISO_BAND_FOR_ZONES True to use RMS in 10–1000 Hz band for zone/shutdown decisions.
    SAMPLE_RATE_HZ = 1000
    BUTTER_ORDER = 3
    # Filter cutoff: normalized Wn in (0, 1), where 1 = Nyquist (fs/2). E.g. 0.1 at fs=1000 Hz → 50 Hz.
    BUTTER_CUTOFF = 0.1
    # Optional: use 10–1000 Hz band RMS for zone and shutdown (ISO 10816-3). When False, overall RMS is used.
    USE_ISO_BAND_FOR_ZONES = False
    ISO_BAND_LOW_HZ = 10.0
    ISO_BAND_HIGH_HZ = 1000.0  # Capped at Nyquist (fs/2) in code

    @staticmethod
    def get_info() -> str:
        return (
            f"--- Config loaded for {Config.PUMP_ID} (Broker: {Config.MQTT_BROKER}) ---"
        )
