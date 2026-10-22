"""PeerTable: visión local de los nodos conocidos (TablaPares del UML)."""

import threading
import time
from dataclasses import asdict, dataclass

ONLINE = "ONLINE"
OFFLINE = "OFFLINE"

EMA_ALPHA = 0.3


@dataclass
class Peer:
    node_id: str
    ip: str
    port: int
    cpu_free_pct: float = 0.0
    ram_free_mb: float = 0.0
    bandwidth_mbps: float = 0.0
    active_tasks: int = 0
    latency_ms: float = None
    reputation: float = 1.0
    last_seen: float = 0.0
    status: str = ONLINE

    @property
    def address(self):
        return (self.ip, self.port)

    def to_dict(self):
        data = asdict(self)
        data["last_seen_ago_sec"] = round(time.time() - self.last_seen, 1)
        return data


class PeerTable:

    def __init__(self, clock=time.time):
        self._peers = {}
        self._lock = threading.RLock()
        self._clock = clock

    def update_from_beacon(self, node_id, ip, payload):
        """Registra o actualiza un vecino a partir de un RESOURCE_BEACON.

        Devuelve (peer, evento) con evento en {"new", "recovered", "update"}.
        """
        with self._lock:
            peer = self._peers.get(node_id)
            if peer is None:
                event = "new"
                peer = Peer(node_id=node_id, ip=ip, port=int(payload["port"]))
                self._peers[node_id] = peer
            elif peer.status == OFFLINE:
                event = "recovered"
            else:
                event = "update"
            peer.ip = ip
            peer.port = int(payload["port"])
            peer.cpu_free_pct = float(payload.get("cpu_free_pct", 0.0))
            peer.ram_free_mb = float(payload.get("ram_free_mb", 0.0))
            peer.bandwidth_mbps = float(payload.get("bandwidth_mbps", 0.0))
            peer.active_tasks = int(payload.get("active_tasks", 0))
            peer.last_seen = self._clock()
            peer.status = ONLINE
            return peer, event

    def get(self, node_id):
        with self._lock:
            return self._peers.get(node_id)

    def all(self):
        with self._lock:
            return list(self._peers.values())

    def active(self):
        """V(t): vecinos actualmente ONLINE."""
        with self._lock:
            return [p for p in self._peers.values() if p.status == ONLINE]

    def mark_offline(self, node_id):
        with self._lock:
            peer = self._peers.get(node_id)
            if peer and peer.status == ONLINE:
                peer.status = OFFLINE
                return True
            return False

    def expired(self, timeout):
        """Vecinos ONLINE sin mensajes desde hace más de `timeout` segundos."""
        now = self._clock()
        with self._lock:
            return [
                p
                for p in self._peers.values()
                if p.status == ONLINE and now - p.last_seen > timeout
            ]

    def touch(self, node_id):
        """Cualquier mensaje recibido demuestra que el vecino está vivo."""
        with self._lock:
            peer = self._peers.get(node_id)
            if peer:
                peer.last_seen = self._clock()
                return True
            return False

    def update_latency(self, node_id, rtt_ms):
        with self._lock:
            peer = self._peers.get(node_id)
            if peer is None:
                return None
            if peer.latency_ms is None:
                peer.latency_ms = rtt_ms
            else:
                peer.latency_ms = (
                    EMA_ALPHA * rtt_ms + (1 - EMA_ALPHA) * peer.latency_ms
                )
            return peer.latency_ms

    def adjust_reputation(self, node_id, delta):
        with self._lock:
            peer = self._peers.get(node_id)
            if peer is None:
                return None
            peer.reputation = min(1.0, max(0.0, peer.reputation + delta))
            return peer.reputation

    def snapshot(self):
        with self._lock:
            return [p.to_dict() for p in self._peers.values()]
