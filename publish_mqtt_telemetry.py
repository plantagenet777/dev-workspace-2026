#!/usr/bin/env python3
"""
PdM: MQTT Telemetry Simulator: publish test pump telemetry to the broker.
Usage: PYTHONPATH=. python publish_mqtt_telemetry.py [--mode normal|failure]
"""
import argparse
import json
import random
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import paho.mqtt.client as mqtt
from config.config import Config


def generate_telemetry(mode: str = "normal") -> dict:
    """Generate one telemetry record."""
    if mode == "failure":
        vib_rms = random.gauss(8.5, 1.5)
        current = random.gauss(56, 5)
        pressure = random.gauss(3.5, 0.8)
        temp = random.gauss(72, 8)
    else:
        vib_rms = random.gauss(2.5, 0.4)
        current = random.gauss(45, 2)
        pressure = random.gauss(6.0, 0.3)
        temp = random.gauss(38, 3)

    # Simple synthetic higher-order vibration metrics and cavitation index so that
    # DataProcessor.prepare_batch / FeatureExtractor and rules can operate without
    # special cases. These values are plausible but not derived from a full waveform.
    vib_crest = max(2.0, abs(vib_rms) * random.uniform(1.5, 2.5))
    vib_kurtosis = (
        random.uniform(2.5, 4.5) if abs(vib_rms) < 5.0 else random.uniform(3.5, 6.5)
    )

    # Cavitation index proxy: higher when pressure drops and current rises.
    base_index = max(0.0, 1.0 + (45.0 - pressure) * 0.2 + (current - 45.0) * 0.02)
    cavitation_index = round(max(0.0, base_index), 3)

    return {
        "vib_rms": vib_rms,
        "vib_crest": vib_crest,
        "vib_kurtosis": vib_kurtosis,
        "current": current,
        "pressure": pressure,
        "temp": temp,
        "cavitation_index": cavitation_index,
    }


def main():
    parser = argparse.ArgumentParser(description="MQTT Telemetry Simulator")
    parser.add_argument(
        "--mode",
        choices=["normal", "failure"],
        default="normal",
        help="Simulation mode: normal (healthy) or failure (anomaly)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Publish interval in seconds (default 1 Hz)",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=0,
        help="Number of messages (0 = infinite)",
    )
    args = parser.parse_args()

    client = mqtt.Client(client_id=f"{Config.PUMP_ID}_simulator", clean_session=True)

    if Config.MQTT_USE_TLS:
        try:
            import ssl

            client.tls_set(
                ca_certs=Config.CA_CERT,
                certfile=Config.CLIENT_CERT,
                keyfile=Config.CLIENT_KEY,
                tls_version=ssl.PROTOCOL_TLSv1_2,
            )
            client.tls_insecure_set(Config.MQTT_TLS_INSECURE)
        except Exception as e:
            print(f"[FATAL] TLS Error: {e}")
            sys.exit(1)

    def on_connect(c, userdata, flags, rc):
        if rc == 0:
            print(f"✅ Connected to {Config.MQTT_BROKER}:{Config.MQTT_PORT}")
        else:
            print(f"❌ Connection failed: {rc}")

    client.on_connect = on_connect
    client.connect(Config.MQTT_BROKER, Config.MQTT_PORT, Config.MQTT_KEEPALIVE)
    client.loop_start()

    print(f"📤 Publishing telemetry (mode={args.mode}, interval={args.interval}s)...")
    print(f"   Topic: {Config.TOPIC_TELEMETRY}")
    print("   Press Ctrl+C to stop.\n")

    sent = 0
    try:
        while args.count == 0 or sent < args.count:
            payload = generate_telemetry(args.mode)
            client.publish(Config.TOPIC_TELEMETRY, json.dumps(payload), qos=1)
            sent += 1
            if sent <= 3 or sent % 10 == 0:
                print(f"   Sent #{sent}: {payload}")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass

    client.loop_stop()
    client.disconnect()
    print(f"\n✅ Published {sent} messages.")


if __name__ == "__main__":
    main()
