"""Reloj lógico de Lamport (Synchronization Service).

Cada nodo mantiene un contador que se incrementa con cada evento local y se
ajusta con el valor recibido en cada mensaje. Así se puede ordenar causalmente
los eventos de nodos distintos sin depender de relojes físicos sincronizados.
"""

import threading


class LamportClock:

    def __init__(self):
        self._time = 0
        self._lock = threading.Lock()

    @property
    def time(self):
        with self._lock:
            return self._time

    def tick(self):
        """Evento local o envío de mensaje: incrementa y devuelve el reloj."""
        with self._lock:
            self._time += 1
            return self._time

    def update(self, received):
        """Recepción de mensaje: reloj = max(local, recibido) + 1."""
        with self._lock:
            self._time = max(self._time, int(received)) + 1
            return self._time
