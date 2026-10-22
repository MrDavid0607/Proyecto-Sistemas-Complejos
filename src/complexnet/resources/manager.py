"""Resource Manager: mide y publica el vector de estado del nodo."""

import threading

import psutil


class ResourceManager:

    def __init__(self, bandwidth_mbps=100.0):
        # El ancho de banda no se mide: es un valor declarado por nodo
        # (configurable), documentado como estimación en el modelo.
        self.bandwidth_mbps = float(bandwidth_mbps)
        self._active_tasks = 0
        self._lock = threading.Lock()
        psutil.cpu_percent(interval=None)  # primera lectura de calibración

    @property
    def active_tasks(self):
        with self._lock:
            return self._active_tasks

    def task_started(self):
        with self._lock:
            self._active_tasks += 1

    def task_finished(self):
        with self._lock:
            self._active_tasks = max(0, self._active_tasks - 1)

    def state(self):
        """Vector de recursos locales: C_i, M_i, B_i y tareas activas."""
        return {
            "cpu_free_pct": round(100.0 - psutil.cpu_percent(interval=None), 2),
            "ram_free_mb": round(
                psutil.virtual_memory().available / (1024 * 1024), 2
            ),
            "bandwidth_mbps": self.bandwidth_mbps,
            "active_tasks": self.active_tasks,
        }
