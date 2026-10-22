"""Node Discovery: anuncia el nodo (RESOURCE_BEACON) y mide latencia (PING/PONG)."""

import threading
import time

from ..communication import PING, PONG, RESOURCE_BEACON, Message


class DiscoveryService:
    """Emite beacons periódicos y registra los de otros nodos en la PeerTable.

    Los beacons se envían por broadcast (si hay dirección configurada) y por
    unicast a los `seed_peers`, útil cuando el broadcast no está disponible
    (pruebas en localhost, redes que filtran difusión).
    """

    def __init__(
        self,
        node,
        beacon_interval=2.0,
        broadcast_address=None,
        seed_peers=(),
    ):
        self.node = node
        self.beacon_interval = beacon_interval
        self.broadcast_address = broadcast_address
        self.seed_peers = list(seed_peers)
        self._thread = None
        self._running = False
        self._pending_pings = {}
        self._lock = threading.Lock()

    def start(self):
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name=f"discovery-{self.node.node_id}"
        )
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2)

    # ---------------------------------------------------------- emisión

    def _loop(self):
        while self._running:
            self.send_beacon()
            self.ping_peers()
            time.sleep(self.beacon_interval)

    def send_beacon(self):
        node = self.node
        payload = {"ip_address": node.ip_address, "port": node.port}
        payload.update(node.resources.state())
        message = Message(
            type=RESOURCE_BEACON,
            sender_id=node.node_id,
            payload=payload,
            lamport=node.clock.tick(),
        )
        if self.broadcast_address:
            node.comm.broadcast(message, (self.broadcast_address, node.port))
        for address in self.seed_peers:
            node.comm.send(message, address)

    def ping_peers(self):
        node = self.node
        for peer in node.peers.active():
            message = Message(
                type=PING,
                sender_id=node.node_id,
                payload={"sent_at": time.time()},
                lamport=node.clock.tick(),
            )
            node.comm.send(message, peer.address)

    # -------------------------------------------------------- recepción

    def handle_beacon(self, message, address):
        node = self.node
        if message.sender_id == node.node_id:
            return
        # La IP real es la de origen del datagrama (válida dentro de Docker/LAN).
        peer, event = node.peers.update_from_beacon(
            message.sender_id, address[0], message.payload
        )
        if event == "new":
            elapsed = time.time() - node.started_at
            node.metrics.incr("nodes_discovered")
            node.metrics.record("discovery_times", elapsed)
            node.log.event(
                "DISCOVERY",
                peer=peer.node_id,
                address=f"{peer.ip}:{peer.port}",
                after_sec=round(elapsed, 2),
            )
            # Medición inmediata para no esperar al siguiente ciclo.
            self._ping_one(peer)
        elif event == "recovered":
            node.log.event("RECOVERY", peer=peer.node_id, status="ONLINE")
            self._ping_one(peer)

    def _ping_one(self, peer):
        node = self.node
        node.comm.send(
            Message(
                type=PING,
                sender_id=node.node_id,
                payload={"sent_at": time.time()},
                lamport=node.clock.tick(),
            ),
            peer.address,
        )

    def handle_ping(self, message, address):
        node = self.node
        node.comm.send(
            Message(
                type=PONG,
                sender_id=node.node_id,
                payload={"sent_at": message.payload.get("sent_at")},
                lamport=node.clock.tick(),
            ),
            address,
        )

    def handle_pong(self, message, address):
        sent_at = message.payload.get("sent_at")
        if sent_at is None:
            return
        rtt_ms = (time.time() - float(sent_at)) * 1000
        if self.node.peers.update_latency(message.sender_id, rtt_ms) is not None:
            self.node.metrics.record("latencies", rtt_ms)
