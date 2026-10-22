"""Logger and Monitor: registro de eventos (JSON lines) y métricas del nodo."""

import json
import os
import threading
import time


class EventLogger:
    """Escribe cada evento como una línea JSON y, opcionalmente, en consola.

    Cada evento lleva el tiempo físico y el reloj de Lamport del nodo, lo que
    permite unir los logs de varios nodos y ordenarlos causalmente.
    """

    def __init__(self, node_id, clock=None, log_dir=None, console=True, keep=500):
        self.node_id = node_id
        self.clock = clock
        self.console = console
        self.keep = keep
        self._events = []
        self._lock = threading.Lock()
        self._file = None
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
            self._file = open(
                os.path.join(log_dir, f"{node_id}.jsonl"), "a", encoding="utf-8"
            )

    def event(self, kind, **fields):
        record = {
            "ts": round(time.time(), 3),
            "lamport": self.clock.time if self.clock else 0,
            "node": self.node_id,
            "event": kind,
        }
        record.update(fields)
        with self._lock:
            self._events.append(record)
            if len(self._events) > self.keep:
                self._events.pop(0)
            if self._file:
                self._file.write(json.dumps(record, ensure_ascii=False) + "\n")
                self._file.flush()
        if self.console:
            details = " ".join(f"{k}={v}" for k, v in fields.items())
            print(
                f"[{time.strftime('%H:%M:%S')}] [L{record['lamport']:>4}] "
                f"{self.node_id} {kind} {details}".rstrip(),
                flush=True,
            )
        return record

    def recent(self, count=50):
        with self._lock:
            return list(self._events[-count:])

    def close(self):
        with self._lock:
            if self._file:
                self._file.close()
                self._file = None


class Metrics:
    """Métricas mínimas del taller, calculadas a partir de los eventos del nodo."""

    def __init__(self):
        self._lock = threading.Lock()
        self.started_at = time.time()
        self.counters = {
            "tasks_submitted": 0,
            "tasks_completed": 0,
            "tasks_failed": 0,
            "tasks_reassigned": 0,
            "nodes_discovered": 0,
            "failures_detected": 0,
            "messages_sent": 0,
            "bytes_sent": 0,
        }
        self.discovery_times = []
        self.assignment_times = []
        self.execution_times = []
        self.total_times = []
        self.recovery_times = []
        self.latencies = []

    def incr(self, name, amount=1):
        with self._lock:
            self.counters[name] = self.counters.get(name, 0) + amount

    def record(self, series, value):
        with self._lock:
            getattr(self, series).append(value)

    @staticmethod
    def _avg(values):
        return round(sum(values) / len(values), 4) if values else None

    def snapshot(self):
        with self._lock:
            submitted = self.counters["tasks_submitted"]
            failed = self.counters["tasks_failed"]
            return {
                "uptime_sec": round(time.time() - self.started_at, 1),
                **self.counters,
                "failure_rate": round(failed / submitted, 4) if submitted else 0.0,
                "avg_discovery_time_sec": self._avg(self.discovery_times),
                "avg_assignment_time_ms": self._avg(
                    [t * 1000 for t in self.assignment_times]
                ),
                "avg_execution_time_sec": self._avg(self.execution_times),
                "avg_total_time_sec": self._avg(self.total_times),
                "avg_recovery_time_sec": self._avg(self.recovery_times),
                "avg_latency_ms": self._avg(self.latencies),
            }
