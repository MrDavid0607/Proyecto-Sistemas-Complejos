"""Node: integra todos los servicios y expone la API de alto nivel.

    from complexnet import Node, Task

    node = Node("nodo-01", port=9999, broadcast_address="172.30.77.255")
    node.connect()
    result = node.submit(Task("regresion_lineal", {"n_samples": 5000}))
"""

import socket
import threading
import time
from dataclasses import dataclass, field

from .communication import (
    PING,
    PONG,
    RESOURCE_BEACON,
    TASK_ACK,
    TASK_RESULT,
    TASK_SUBMIT,
    Message,
    UDPCommunication,
)
from .discovery import DiscoveryService, PeerTable
from .failure_detection import FailureDetector
from .monitoring import EventLogger, Metrics
from .resources import ResourceManager
from .scheduler import Candidate, DistributedScheduler
from .synchronization import LamportClock
from .tasks import TaskManager
from .tasks.recovery import RecoveryManager

BEACON_INTERVAL = 2.0
NODE_TIMEOUT = 5.0


def get_local_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("10.255.255.255", 1))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


@dataclass
class NodeConfig:
    port: int = 9999
    broadcast_address: str = None
    seed_peers: list = field(default_factory=list)
    bandwidth_mbps: float = 100.0
    beacon_interval: float = BEACON_INTERVAL
    node_timeout: float = NODE_TIMEOUT
    ack_timeout: float = NODE_TIMEOUT
    exec_timeout: float = 60.0
    queue_timeout: float = 30.0
    max_attempts: int = 3
    log_dir: str = None
    console_log: bool = True
    ip_address: str = None


class Node:

    def __init__(self, node_id, config=None, **overrides):
        self.node_id = node_id
        self.config = config or NodeConfig()
        for key, value in overrides.items():
            setattr(self.config, key, value)
        cfg = self.config

        self.port = cfg.port
        self.ip_address = cfg.ip_address or get_local_ip()
        self.started_at = time.time()
        self.running = False

        self.clock = LamportClock()
        self.log = EventLogger(
            node_id, self.clock, log_dir=cfg.log_dir, console=cfg.console_log
        )
        self.metrics = Metrics()
        self.peers = PeerTable()
        self.resources = ResourceManager(cfg.bandwidth_mbps)
        self.scheduler = DistributedScheduler()

        self.comm = UDPCommunication(
            cfg.port,
            on_error=lambda text: self.log.event("COMM_ERROR", detail=text),
            on_send=self._count_sent,
        )
        self.discovery = DiscoveryService(
            self,
            beacon_interval=cfg.beacon_interval,
            broadcast_address=cfg.broadcast_address,
            seed_peers=[tuple(p) for p in cfg.seed_peers],
        )
        self.tasks = TaskManager(
            self,
            ack_timeout=cfg.ack_timeout,
            exec_timeout=cfg.exec_timeout,
            queue_timeout=cfg.queue_timeout,
            max_attempts=cfg.max_attempts,
        )
        self.detector = FailureDetector(
            self.peers, timeout=cfg.node_timeout, on_log=self._log_failure
        )
        self.recovery = RecoveryManager(self.tasks, self.detector)

        self._handlers = {
            RESOURCE_BEACON: self.discovery.handle_beacon,
            PING: self.discovery.handle_ping,
            PONG: self.discovery.handle_pong,
            TASK_SUBMIT: self.tasks.handle_submit,
            TASK_ACK: self.tasks.handle_ack,
            TASK_RESULT: self.tasks.handle_result,
        }

    # ----------------------------------------------------------- API

    def connect(self):
        """Une el nodo a la red: empieza a escuchar, anunciarse y vigilar."""
        self.running = True
        self.started_at = time.time()
        self.comm.start(self._on_message)
        self.tasks.start()
        self.detector.start()
        self.discovery.start()
        self.log.event(
            "NODE_STARTED",
            ip=self.ip_address,
            port=self.port,
            broadcast=self.config.broadcast_address,
            seeds=len(self.config.seed_peers),
        )
        return self

    def disconnect(self):
        if not self.running:
            return
        self.log.event("NODE_STOPPED")
        self.running = False
        self.discovery.stop()
        self.detector.stop()
        self.tasks.stop()
        self.comm.stop()
        self.log.close()

    def submit(self, task, allow_local=True, wait=True, timeout=None):
        """Envía una tarea a la red; el planificador elige el nodo ejecutor."""
        return self.tasks.submit(
            task, allow_local=allow_local, wait=wait, timeout=timeout
        )

    def broadcast(self, message_type, payload):
        """Difunde un mensaje a todos los vecinos activos."""
        for peer in self.peers.active():
            self.send(message_type, payload, peer.address)

    def wait_for_peers(self, count, timeout=15.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if len(self.peers.active()) >= count:
                return True
            time.sleep(0.1)
        return False

    # ------------------------------------------------------ internos

    def send(self, message_type, payload, address):
        self.comm.send(
            Message(
                type=message_type,
                sender_id=self.node_id,
                payload=payload,
                lamport=self.clock.tick(),
            ),
            address,
        )

    def candidates(self, allow_local=True, exclude=()):
        """V(t) como lista de candidatos para el planificador."""
        peers = [p for p in self.peers.active() if p.node_id not in exclude]
        known = [p.latency_ms for p in peers if p.latency_ms is not None]
        default_latency = sum(known) / len(known) if known else 0.0
        result = [
            Candidate(
                node_id=p.node_id,
                cpu=p.cpu_free_pct,
                memory=p.ram_free_mb,
                bandwidth=p.bandwidth_mbps,
                reputation=p.reputation,
                latency=p.latency_ms if p.latency_ms is not None else default_latency,
            )
            for p in peers
        ]
        if allow_local and self.node_id not in exclude:
            state = self.resources.state()
            result.append(
                Candidate(
                    node_id=self.node_id,
                    cpu=state["cpu_free_pct"],
                    memory=state["ram_free_mb"],
                    bandwidth=state["bandwidth_mbps"],
                    reputation=1.0,
                    latency=0.0,
                )
            )
        return result

    def status(self):
        return {
            "node_id": self.node_id,
            "ip": self.ip_address,
            "port": self.port,
            "lamport": self.clock.time,
            "resources": self.resources.state(),
            "peers": self.peers.snapshot(),
            "tasks": [t.to_dict() for t in list(self.tasks.tasks.values())[-20:]],
            "metrics": self.metrics.snapshot(),
        }

    def _on_message(self, message, address):
        self.clock.update(message.lamport)
        if message.sender_id == self.node_id:
            return
        # Cualquier mensaje de un vecino conocido demuestra que sigue vivo.
        self.peers.touch(message.sender_id)
        handler = self._handlers.get(message.type)
        if handler is not None:
            handler(message, address)

    def _count_sent(self, message, address):
        self.metrics.incr("messages_sent")
        self.metrics.incr("bytes_sent", len(str(message.to_dict())))

    def _log_failure(self, event, **fields):
        self.metrics.incr("failures_detected")
        self.log.event(event, **fields)
