#!/usr/bin/env python3
"""PdM: Pump telemetry emulator: publish data to MQTT for local sandbox.

Uses Config (MQTT_BROKER, MQTT_PORT, TOPIC_TELEMETRY). When running on host
with docker-compose up, set in .env: MQTT_BROKER=localhost, MQTT_PORT=1883.
"""
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import paho.mqtt.client as mqtt

from config.config import Config

BROKER = Config.MQTT_BROKER
PORT = Config.MQTT_PORT
TOPIC = Config.TOPIC_TELEMETRY

client = mqtt.Client()
client.connect(BROKER, PORT)

print(f"🚀 Emulator started. Publishing to {TOPIC} (broker {BROKER}:{PORT})...")

try:
    while True:
        data = {
            "vib_rms": round(random.uniform(1.5, 2.8), 2),
            "vib_crest": round(random.uniform(2.5, 3.5), 2),
            "vib_kurtosis": round(random.uniform(3.0, 4.0), 2),
            "current": round(random.uniform(140.0, 155.0), 2),
            "pressure": round(random.uniform(3.8, 4.5), 2),
            "cavitation_index": round(random.uniform(0.01, 0.08), 2),
            "temp": round(random.uniform(48.0, 55.0), 2),
        }

        if random.random() > 0.9:
            data["vib_rms"] += 3.0
            data["temp"] += 15.0
            print("⚠️ Anomalous load sent!")

        client.publish(TOPIC, json.dumps(data))
        print(f"📤 Sent: {data['vib_rms']} mm/s, {data['temp']}°C")

        time.sleep(60)
except KeyboardInterrupt:
    print("🛑 Emulator stopped")
    client.disconnect()
