"""
PdM: Monitoring visualization: telemetry vs time with ISO 10816-3 zones and parameter relationships.
Plots vibration with zone bands (B/C/D), risk score, process parameters, and 2D relationship views.
"""
import pandas as pd
import matplotlib.pyplot as plt
from config.config import Config


# ISO 10816-3 Group 1 zone colors (alpha for bands)
ZONE_B_COLOR = (0.2, 0.7, 0.3, 0.25)  # Green: acceptable
ZONE_C_COLOR = (0.95, 0.85, 0.2, 0.3)  # Yellow: restricted
ZONE_D_COLOR = (0.9, 0.25, 0.2, 0.35)  # Red: unacceptable
VIBRATION_INTERLOCK_COLOR = (
    0.5,
    0.0,
    0.0,
    0.4,
)  # Dark red: vibration interlock (Zone D trip)


def load_telemetry(limit_rows: int | None = None) -> pd.DataFrame:
    """Load telemetry_history.csv and parse timestamp."""
    df = pd.read_csv(Config.TELEMETRY_LOG_PATH)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    if limit_rows:
        df = df.tail(limit_rows)
    return df


def add_vibration_iso_bands(ax: plt.Axes) -> None:
    """Draw ISO 10816-3 zone bands on a vibration (mm/s) y-axis."""
    vb = Config.VIBRATION_WARNING_MMPS  # 4.5 Zone C start
    vc = Config.VIBRATION_CRITICAL_MMPS  # 7.1 Zone D
    vint = Config.VIBRATION_INTERLOCK_MMPS  # 7.1 Zone D
    y_max = max(ax.get_ylim()[1], vint * 1.1)
    ax.set_ylim(0, y_max)

    ax.axhspan(0, vb, facecolor=ZONE_B_COLOR, label="Zone B (acceptable)")
    ax.axhspan(vb, vc, facecolor=ZONE_C_COLOR, label="Zone C (restricted)")
    ax.axhspan(vc, vint, facecolor=ZONE_D_COLOR, label="Zone D (unacceptable)")
    ax.axhspan(
        vint, y_max, facecolor=VIBRATION_INTERLOCK_COLOR, label="Vibration interlock"
    )
    ax.axhline(vb, color="orange", linestyle="--", linewidth=1.2, alpha=0.9)
    ax.axhline(vc, color="red", linestyle="--", linewidth=1.2, alpha=0.9)
    ax.axhline(vint, color="darkred", linestyle="-", linewidth=1, alpha=0.8)


def plot_time_series(df: pd.DataFrame, figsize: tuple[float, float] = (14, 12)) -> None:
    """Time series: vibration (with ISO bands), risk, current/pressure, temp."""
    fig, axes = plt.subplots(
        4,
        1,
        figsize=figsize,
        sharex=True,
        gridspec_kw={"height_ratios": [1.2, 1, 1, 0.8]},
    )

    # --- 1) Vibration with ISO 10816-3 zones ---
    ax1 = axes[0]
    add_vibration_iso_bands(ax1)
    ax1.plot(
        df["timestamp"],
        df["vib_rms"],
        color="navy",
        linewidth=1.5,
        label="vib_rms (mm/s)",
        zorder=5,
    )
    ax1.set_ylabel("Vibration, mm/s")
    ax1.set_title(f"{Config.PUMP_ID} — ISO 10816-3 Group 1 zones")
    ax1.legend(loc="upper right", ncol=2, fontsize=8)
    ax1.grid(True, alpha=0.3)
    ax1.set_xlim(df["timestamp"].min(), df["timestamp"].max())

    # --- 2) Risk score and thresholds ---
    ax2 = axes[1]
    ax2.fill_between(df["timestamp"], 0, df["risk_score"], color="steelblue", alpha=0.4)
    ax2.plot(
        df["timestamp"],
        df["risk_score"],
        color="blue",
        linewidth=1.2,
        label="Risk score",
    )
    ax2.axhline(
        Config.PROB_WARNING,
        color="orange",
        linestyle="--",
        linewidth=1.2,
        label="WARNING",
    )
    ax2.axhline(
        Config.PROB_CRITICAL,
        color="red",
        linestyle="--",
        linewidth=1.2,
        label="CRITICAL",
    )
    ax2.set_ylabel("Risk score")
    ax2.set_ylim(0, 1.05)
    ax2.legend(loc="upper right", fontsize=8)
    ax2.grid(True, alpha=0.3)

    # --- 3) Current & Pressure (process) ---
    ax3 = axes[2]
    ax3.plot(
        df["timestamp"],
        df["current"],
        color="green",
        linewidth=1,
        label="Current (A)",
        alpha=0.9,
    )
    ax3.axhline(
        Config.CAVITATION_CURRENT_MIN_AMP,
        color="purple",
        linestyle=":",
        alpha=0.7,
        label="Cavitation I min",
    )
    ax3.axhline(
        Config.DEGRADATION_CURRENT_MAX_AMP,
        color="brown",
        linestyle=":",
        alpha=0.7,
        label="Degradation I max",
    )
    ax3.set_ylabel("Current, A")
    ax3.legend(loc="upper left", fontsize=7)
    ax3.grid(True, alpha=0.3)

    ax3p = ax3.twinx()
    ax3p.plot(
        df["timestamp"],
        df["pressure"],
        color="teal",
        linewidth=1,
        label="Pressure (bar)",
        alpha=0.9,
    )
    ax3p.axhline(
        Config.CAVITATION_PRESSURE_MAX_BAR, color="purple", linestyle=":", alpha=0.5
    )
    ax3p.axhline(
        Config.DEGRADATION_PRESSURE_MAX_BAR, color="brown", linestyle=":", alpha=0.5
    )
    ax3p.axhline(
        Config.CHOKED_PRESSURE_MIN_BAR,
        color="darkred",
        linestyle=":",
        alpha=0.5,
        label="Choked P min",
    )
    ax3p.set_ylabel("Pressure, bar")
    ax3p.legend(loc="upper right", fontsize=7)

    # --- 4) Temperature ---
    ax4 = axes[3]
    ax4.plot(
        df["timestamp"], df["temp"], color="darkorange", linewidth=1, label="Temp (°C)"
    )
    ax4.axhline(
        Config.CHOKED_TEMP_MIN_C,
        color="darkred",
        linestyle=":",
        alpha=0.7,
        label="Choked T min",
    )
    ax4.set_ylabel("Temp, °C")
    ax4.set_xlabel("Time")
    ax4.legend(loc="upper right", fontsize=7)
    ax4.grid(True, alpha=0.3)

    plt.gcf().autofmt_xdate()
    plt.tight_layout()
    return fig


def plot_parameter_relationships(
    df: pd.DataFrame, figsize: tuple[float, float] = (12, 10)
) -> None:
    """2D plots: relationship between parameters with ISO and fault zones indicated."""
    fig, axes = plt.subplots(2, 2, figsize=figsize)

    # Filter to numeric rows and optional status for coloring
    use = df.dropna(subset=["vib_rms", "current", "pressure", "temp", "risk_score"])

    # --- 1) Vibration vs Risk (ISO zones as vertical bands) ---
    ax1 = axes[0, 0]
    vb, vc, vint = (
        Config.VIBRATION_WARNING_MMPS,
        Config.VIBRATION_CRITICAL_MMPS,
        Config.VIBRATION_INTERLOCK_MMPS,
    )
    ax1.axvspan(0, vb, facecolor=ZONE_B_COLOR)
    ax1.axvspan(vb, vc, facecolor=ZONE_C_COLOR)
    ax1.axvspan(vc, vint, facecolor=ZONE_D_COLOR)
    ax1.axvspan(
        vint, use["vib_rms"].max() * 1.05 or 15, facecolor=VIBRATION_INTERLOCK_COLOR
    )
    ax1.axvline(vb, color="orange", linestyle="--", linewidth=1)
    ax1.axvline(vc, color="red", linestyle="--", linewidth=1)
    ax1.axvline(vint, color="darkred", linestyle="-", linewidth=0.8)
    sc1 = ax1.scatter(
        use["vib_rms"],
        use["risk_score"],
        c=use["risk_score"],
        cmap="RdYlGn_r",
        s=8,
        alpha=0.6,
    )
    ax1.set_xlabel("Vibration (mm/s) — ISO 10816-3")
    ax1.set_ylabel("Risk score")
    ax1.set_title("Risk vs Vibration (zones B/C/D/vibration interlock)")
    ax1.set_xlim(0, None)
    ax1.set_ylim(0, 1.05)
    plt.colorbar(sc1, ax=ax1, label="Risk")

    # --- 2) Current vs Pressure (cavitation / degradation / choked zones) ---
    ax2 = axes[0, 1]
    xlo, xhi = 30, 70
    # Cavitation: I >= 54, P <= 4 (high flow, low pressure)
    ax2.axhspan(
        0,
        Config.CAVITATION_PRESSURE_MAX_BAR,
        xmin=(Config.CAVITATION_CURRENT_MIN_AMP - xlo) / (xhi - xlo),
        facecolor="purple",
        alpha=0.2,
        label="Cavitation (I≥54, P≤4)",
    )
    ax2.axhline(
        Config.CAVITATION_PRESSURE_MAX_BAR, color="purple", linestyle=":", alpha=0.6
    )
    ax2.axvline(
        Config.CAVITATION_CURRENT_MIN_AMP, color="purple", linestyle=":", alpha=0.6
    )
    # Degradation: I <= 42, P <= 5
    ax2.axhspan(
        0,
        Config.DEGRADATION_PRESSURE_MAX_BAR,
        xmax=(Config.DEGRADATION_CURRENT_MAX_AMP - xlo) / (xhi - xlo),
        facecolor="brown",
        alpha=0.2,
        label="Degradation (I≤42, P≤5)",
    )
    ax2.axhline(
        Config.DEGRADATION_PRESSURE_MAX_BAR, color="brown", linestyle=":", alpha=0.6
    )
    ax2.axvline(
        Config.DEGRADATION_CURRENT_MAX_AMP, color="brown", linestyle=":", alpha=0.6
    )
    # Choked: I <= 40, P >= 7
    ax2.axhspan(
        Config.CHOKED_PRESSURE_MIN_BAR,
        10,
        xmax=(Config.CHOKED_CURRENT_MAX_AMP - xlo) / (xhi - xlo),
        facecolor="darkred",
        alpha=0.2,
        label="Choked (I≤40, P≥7)",
    )
    ax2.axhline(
        Config.CHOKED_PRESSURE_MIN_BAR, color="darkred", linestyle=":", alpha=0.6
    )
    ax2.axvline(
        Config.CHOKED_CURRENT_MAX_AMP, color="darkred", linestyle=":", alpha=0.6
    )
    ax2.scatter(
        use["current"],
        use["pressure"],
        c=use["risk_score"],
        cmap="RdYlGn_r",
        s=6,
        alpha=0.5,
    )
    ax2.set_xlabel("Current (A) — flow proxy")
    ax2.set_ylabel("Pressure (bar)")
    ax2.set_title("Current vs Pressure (fault zones)")
    ax2.set_xlim(30, 70)
    ax2.set_ylim(0, 10)
    ax2.legend(loc="upper right", fontsize=6)

    # --- 3) Vibration vs Pressure ---
    ax3 = axes[1, 0]
    ax3.scatter(
        use["pressure"],
        use["vib_rms"],
        c=use["risk_score"],
        cmap="RdYlGn_r",
        s=6,
        alpha=0.5,
    )
    ax3.axhline(vb, color="orange", linestyle="--", alpha=0.7, label="Zone C (4.5)")
    ax3.axhline(vc, color="red", linestyle="--", alpha=0.7, label="Zone D (7.1)")
    ax3.set_xlabel("Pressure (bar)")
    ax3.set_ylabel("Vibration (mm/s)")
    ax3.set_title("Vibration vs Pressure")
    ax3.legend(fontsize=7)
    ax3.set_ylim(0, None)

    # --- 4) Temp vs Vibration ---
    ax4 = axes[1, 1]
    ax4.scatter(
        use["temp"],
        use["vib_rms"],
        c=use["risk_score"],
        cmap="RdYlGn_r",
        s=6,
        alpha=0.5,
    )
    ax4.axhline(vb, color="orange", linestyle="--", alpha=0.7)
    ax4.axhline(vc, color="red", linestyle="--", alpha=0.7)
    ax4.axvline(
        Config.CHOKED_TEMP_MIN_C,
        color="darkred",
        linestyle=":",
        alpha=0.7,
        label="Choked T≥70°C",
    )
    ax4.set_xlabel("Temperature (°C)")
    ax4.set_ylabel("Vibration (mm/s)")
    ax4.set_title("Temperature vs Vibration")
    ax4.legend(fontsize=7)
    ax4.set_ylim(0, None)

    plt.tight_layout()
    return fig


def plot_combined_monitor(limit_rows: int | None = 2000) -> None:
    """Load data and show both time-series and relationship plots."""
    log_path = Config.TELEMETRY_LOG_PATH
    try:
        df = load_telemetry(limit_rows=limit_rows)
        if df.empty:
            print("❌ No data in telemetry log.")
            return
    except Exception as e:
        print(f"❌ Plot error (load): {e}")
        return

    fig1 = plot_time_series(df)
    fig1.suptitle(f"Telemetry vs time (last {len(df)} records)", y=1.02, fontsize=12)
    plt.show(block=False)

    fig2 = plot_parameter_relationships(df)
    fig2.suptitle("Parameter relationships and ISO / fault zones", y=1.02, fontsize=12)
    plt.show()

    print("📊 Plots ready.")


if __name__ == "__main__":
    plot_combined_monitor()
