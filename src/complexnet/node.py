"""Node: integra todos los servicios y expone la API de alto nivel.

    from complexnet import Node, Task

    with Node("nodo-01", port=9999, broadcast_address="auto") as node:
        node.wait_for_peers(2)
        result = node.submit(Task("regresion_lineal", {"n_samples": 5000}))
        results = node.map("monte_carlo_pi", [{"seed": s} for s in range(8)])
"""

import socket
import threading
import time
from dataclasses import dataclass, field

import psutil

from .communication import (
    ALERT,
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
from .tasks import Task, TaskFailed, TaskManager
from .tasks.recovery import RecoveryManager

BEACON_INTERVAL = 2.0
NODE_TIMEOUT = 5.0
MAX_ALERTS = 200


def get_local_ip():
    """IP de la interfaz que sale hacia la red local (sin enviar tráfico)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("10.255.255.255", 1))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def detect_broadcast(ip):
    """Dirección de broadcast de la subred a la que pertenece `ip`."""
    for addresses in psutil.net_if_addrs().values():
        for addr in addresses:
            if addr.family == socket.AF_INET and addr.address == ip:
                if addr.broadcast:
                    return addr.broadcast
                if addr.netmask:
                    ip_bytes = socket.inet_aton(ip)
                    mask = socket.inet_aton(addr.netmask)
                    return socket.inet_ntoa(
                        bytes(i | (~m & 0xFF) for i, m in zip(ip_bytes, mask))
                    )
    return "255.255.255.255"


@dataclass
class NodeConfig:
    port: int = 9999
    broadcast_address: str = None   # "auto" detecta la dirección de la subred
    discovery_port: int = None      # puerto al que se difunden los beacons (def.: port)
    seed_peers: list = field(default_factory=list)
    bandwidth_mbps: float = 100.0
    beacon_interval: float = BEACON_INTERVAL
    node_timeout: float = NODE_TIMEOUT
    ack_timeout: float = NODE_TIMEOUT
    exec_timeout: float = 60.0
    queue_timeout: float = 30.0
    max_attempts: int = 3
    slots: int = 2                  # tareas que el nodo ejecuta a la vez
    strategy: str = "weighted_load"
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
        if cfg.broadcast_address == "auto":
            cfg.broadcast_address = detect_broadcast(self.ip_address)
        self.started_at = time.time()
        self.running = False
        self.alerts = []
        self._alert_lock = threading.Lock()

        self.clock = LamportClock()
        self.log = EventLogger(
            node_id, self.clock, log_dir=cfg.log_dir, console=cfg.console_log
        )
        self.metrics = Metrics()
        self.peers = PeerTable()
        self.resources = ResourceManager(cfg.bandwidth_mbps)
        self.scheduler = DistributedScheduler(strategy=cfg.strategy)

        self.comm = UDPCommunication(
            cfg.port,
            on_error=lambda text: self.log.event("COMM_ERROR", detail=text),
            on_send=self._count_sent,
            on_receive=self._count_received,
        )
        self.discovery = DiscoveryService(
            self,
            beacon_interval=cfg.beacon_interval,
            broadcast_address=cfg.broadcast_address,
            seed_peers=[tuple(p) for p in cfg.seed_peers],
            discovery_port=cfg.discovery_port,
        )
        self.tasks = TaskManager(
            self,
            ack_timeout=cfg.ack_timeout,
            exec_timeout=cfg.exec_timeout,
            queue_timeout=cfg.queue_timeout,
            max_attempts=cfg.max_attempts,
            slots=cfg.slots,
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
            ALERT: self._handle_alert,
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
            strategy=self.config.strategy,
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
        self.resources.close()
        self.log.close()

    stop = disconnect

    def __enter__(self):
        return self.connect()

    def __exit__(self, *exc):
        self.disconnect()

    def submit(self, task, allow_local=True, wait=True, timeout=None):
        """Envía una tarea a la red; el planificador elige el nodo ejecutor.

        Con wait=True devuelve el resultado (o lanza TaskFailed); con
        wait=False devuelve la Task para consultarla o esperarla después.
        """
        return self.tasks.submit(
            task, allow_local=allow_local, wait=wait, timeout=timeout
        )

    def map_tasks(self, name, parameters_list, requirements=None,
                  allow_local=True, timeout=120.0):
        """Lanza una tarea por cada elemento de `parameters_list` y espera a todas.

        Devuelve la lista de Task en el mismo orden (map de un map-reduce).
        """
        tasks = [
            Task(name, dict(p), requirements=requirements)
            for p in parameters_list
        ]
        for task in tasks:
            self.tasks.submit(task, allow_local=allow_local, wait=False)
        deadline = time.time() + timeout
        for task in tasks:
            task.wait(max(0.0, deadline - time.time()))
        return tasks

    def map(self, name, parameters_list, requirements=None, allow_local=True,
            timeout=120.0):
        """Como map_tasks, pero devuelve solo los resultados (lanza TaskFailed)."""
        results = []
        for task in self.map_tasks(
            name, parameters_list, requirements, allow_local, timeout
        ):
            if task.state != "COMPLETED":
                raise TaskFailed(f"{task.task_id}: {task.error or task.state}")
            results.append(task.result)
        return results

    def broadcast(self, message_type, payload):
        """Envía un mensaje a todos los vecinos activos."""
        for peer in self.peers.active():
            self.send(message_type, payload, peer.address)

    def raise_alert(self, level, text, **fields):
        """Registra una alerta local y la difunde a los vecinos (ALERT)."""
        payload = {"level": level, "text": text, "origin": self.node_id, **fields}
        self._store_alert(payload)
        self.metrics.incr("alerts_raised")
        self.log.event("ALERT", level=level, text=text, **fields)
        self.broadcast(ALERT, payload)

    def on_event(self, callback):
        """Registra callback(record) para cada evento del nodo."""
        self.log.subscribe(callback)

    def set_strategy(self, strategy):
        """Cambia la estrategia de asignación en caliente (ver scheduler)."""
        self.scheduler = DistributedScheduler(strategy=strategy)
        self.config.strategy = strategy
        self.log.event("STRATEGY_CHANGED", strategy=strategy)

    def simulate_failure(self, seconds):
        """Simula una caída: el nodo deja de enviar y recibir durante `seconds`."""
        self.comm.mute_until = time.time() + float(seconds)
        self.log.event("FAILURE_SIMULATED", seconds=seconds)

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
                load=max(p.active_tasks, self.tasks.inflight(p.node_id)),
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
                    load=max(state["active_tasks"],
                             self.tasks.inflight(self.node_id)),
                )
            )
        return result

    def status(self):
        resources = self.resources.state()
        return {
            "node_id": self.node_id,
            "ip": self.ip_address,
            "port": self.port,
            "lamport": self.clock.time,
            "strategy": self.config.strategy,
            "muted": self.comm.muted,
            "resources": resources,
            "peers": self.peers.snapshot(),
            "tasks": [t.to_dict() for t in list(self.tasks.tasks.values())[-20:]],
            "alerts": list(self.alerts[-20:]),
            "metrics": self.metrics.snapshot(),
        }

    def _store_alert(self, payload):
        entry = dict(payload)
        entry["ts"] = round(time.time(), 3)
        with self._alert_lock:
            self.alerts.append(entry)
            del self.alerts[:-MAX_ALERTS]

    def _handle_alert(self, message, address):
        self._store_alert(message.payload)
        self.log.event(
            "ALERT_RECEIVED",
            level=message.payload.get("level"),
            text=message.payload.get("text"),
            origin=message.sender_id,
        )

    def _on_message(self, message, address):
        self.clock.update(message.lamport)
        if message.sender_id == self.node_id:
            return
        # Cualquier mensaje de un vecino conocido demuestra que sigue vivo.
        self.peers.touch(message.sender_id)
        handler = self._handlers.get(message.type)
        if handler is not None:
            handler(message, address)

    def _count_sent(self, message, size):
        self.metrics.incr("messages_sent")
        self.metrics.incr("bytes_sent", size)

    def _count_received(self, size):
        self.metrics.incr("messages_received")
        self.metrics.incr("bytes_received", size)

    def _log_failure(self, event, **fields):
        self.metrics.incr("failures_detected")
        self.log.event(event, **fields)
