"""Resource Manager: mide y publica el vector de estado del nodo."""

import threading

import psutil


class ResourceManager:

    def __init__(self, bandwidth_mbps=100.0, cpu_interval=1.0):
        # El ancho de banda no se mide: es un valor declarado por nodo
        # (configurable), documentado como estimación en el modelo.
        self.bandwidth_mbps = float(bandwidth_mbps)
        self._active_tasks = 0
        self._lock = threading.Lock()
        # La CPU se mide en un hilo aparte con una ventana fija: varias lecturas
        # seguidas de psutil.cpu_percent(None) se pisan entre sí y dan valores falsos.
        self._cpu_used = psutil.cpu_percent(interval=None)
        self._cpu_interval = cpu_interval
        self._stop = threading.Event()
        threading.Thread(
            target=self._sample_cpu, daemon=True, name="cpu-sampler"
        ).start()

    def _sample_cpu(self):
        while not self._stop.is_set():
            self._cpu_used = psutil.cpu_percent(interval=self._cpu_interval)

    def close(self):
        self._stop.set()

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
            "cpu_free_pct": round(100.0 - self._cpu_used, 2),
            "ram_free_mb": round(
                psutil.virtual_memory().available / (1024 * 1024), 2
            ),
            "bandwidth_mbps": self.bandwidth_mbps,
            "active_tasks": self.active_tasks,
        }
