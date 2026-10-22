"""Failure Detector: marca OFFLINE a los vecinos que dejan de dar señales."""

import threading
import time


class FailureDetector:
    """Un vecino ONLINE sin mensajes por más de `timeout` segundos pasa a OFFLINE.

    Cualquier mensaje recibido (beacon, PONG, resultado de tarea) renueva
    `last_seen`; el detector solo mira el tiempo transcurrido, por lo que es
    puramente local. Los observadores (p. ej. el Recovery Manager) se notifican
    con callback(node_id).
    """

    def __init__(self, peers, timeout=5.0, check_interval=0.5, on_log=None):
        self.peers = peers
        self.timeout = timeout
        self.check_interval = check_interval
        self.on_log = on_log or (lambda event, **fields: None)
        self._observers = []
        self._thread = None
        self._running = False

    def subscribe(self, callback):
        self._observers.append(callback)

    def start(self):
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="failure-detector"
        )
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2)

    def check_once(self):
        failed = []
        for peer in self.peers.expired(self.timeout):
            if self.peers.mark_offline(peer.node_id):
                failed.append(peer.node_id)
                self.on_log(
                    "FAILURE",
                    peer=peer.node_id,
                    silent_sec=round(time.time() - peer.last_seen, 1),
                    status="OFFLINE",
                )
                for observer in self._observers:
                    observer(peer.node_id)
        return failed

    def _loop(self):
        while self._running:
            self.check_once()
            time.sleep(self.check_interval)
