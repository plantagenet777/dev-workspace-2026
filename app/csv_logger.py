"""CSV write queue with retry: telemetry_history and alerts_history to avoid data loss on transient I/O errors."""
import csv
import logging
import os
import queue
import threading
import time
from pathlib import Path
from typing import Any

from config.config import Config

logger = logging.getLogger("pump_engine")

MAX_RETRIES = 3
RETRY_DELAY_SEC = 0.5
QUEUE_MAX_SIZE = 1000


def _write_with_retry(write_fn: callable) -> bool:
    """Execute write_fn(); retry on OSError up to MAX_RETRIES. Returns True if written."""
    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            write_fn()
            return True
        except (OSError, PermissionError) as e:
            last_err = e
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY_SEC * (2**attempt))
    logger.warning("CSV write failed after %s retries: %s", MAX_RETRIES, last_err)
    return False


def _do_append_alert(path: str, payload: dict[str, Any]) -> None:
    file_exists = Path(path).exists()
    with open(path, "a", encoding="utf-8") as f:
        if not file_exists:
            f.write("timestamp,pump_id,status,anomaly_probability,sensor_status\n")
        f.write(
            f"{payload['timestamp']},{payload['pump_id']},{payload['status']},"
            f"{payload['prob']},{payload['sensor_status']}\n"
        )


def _do_append_telemetry(path: str, payload: dict[str, Any]) -> None:
    fieldnames = payload["fieldnames"]
    row = payload["row"]
    file_exists = Path(path).exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


class _CSVWorker(threading.Thread):
    """Background thread: consume queue and write CSV rows with retry."""

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self._q: queue.Queue = queue.Queue(maxsize=QUEUE_MAX_SIZE)
        self._stop = threading.Event()

    def put_alert(
        self, timestamp: str, pump_id: str, status: str, prob: float, sensor_status: str
    ) -> None:
        try:
            self._q.put_nowait(
                (
                    "alert",
                    {
                        "timestamp": timestamp,
                        "pump_id": pump_id,
                        "status": status,
                        "prob": prob,
                        "sensor_status": sensor_status,
                    },
                )
            )
        except queue.Full:
            logger.warning("CSV alert queue full; dropping one alert record.")

    def put_telemetry(self, fieldnames: list[str], row: dict[str, Any]) -> None:
        try:
            self._q.put_nowait(("telemetry", {"fieldnames": fieldnames, "row": row}))
        except queue.Full:
            logger.warning("CSV telemetry queue full; dropping one telemetry record.")

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                kind, payload = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            if kind == "alert":
                path = Config.ALERTS_LOG_PATH
                os.makedirs(os.path.dirname(path), exist_ok=True)
                _write_with_retry(lambda: _do_append_alert(path, payload))
            elif kind == "telemetry":
                path = Config.TELEMETRY_LOG_PATH
                os.makedirs(os.path.dirname(path), exist_ok=True)
                _write_with_retry(lambda: _do_append_telemetry(path, payload))
            self._q.task_done()


_worker: _CSVWorker | None = None
_lock = threading.Lock()


def get_csv_worker() -> _CSVWorker:
    """Singleton CSV worker; start thread on first use."""
    global _worker
    with _lock:
        if _worker is None:
            _worker = _CSVWorker()
            _worker.start()
        return _worker


def append_alert(
    timestamp: str, pump_id: str, status: str, prob: float, sensor_status: str
) -> None:
    """Queue one alert row for writing (with retry in background)."""
    get_csv_worker().put_alert(timestamp, pump_id, status, prob, sensor_status)


def append_telemetry(fieldnames: list[str], row: dict[str, Any]) -> None:
    """Queue one telemetry row for writing (with retry in background)."""
    get_csv_worker().put_telemetry(fieldnames, row)
