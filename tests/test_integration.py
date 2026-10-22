"""Pruebas de integración: 3 nodos reales (UDP en localhost) en un mismo proceso."""

import socket
import time

import pytest

from complexnet import Node, NodeConfig, Task
from complexnet.tasks import COMPLETED, FAILED


def free_udp_ports(count):
    socks, ports = [], []
    for _ in range(count):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(("", 0))
        socks.append(s)
        ports.append(s.getsockname()[1])
    for s in socks:
        s.close()
    return ports


def wait_until(condition, timeout=10.0, step=0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(step)
    return False


def make_network(names, bandwidths=None, **overrides):
    ports = dict(zip(names, free_udp_ports(len(names))))
    nodes = []
    for name in names:
        seeds = [("127.0.0.1", ports[o]) for o in names if o != name]
        cfg = NodeConfig(
            port=ports[name],
            seed_peers=seeds,
            ip_address="127.0.0.1",
            beacon_interval=0.3,
            node_timeout=1.5,
            ack_timeout=1.5,
            bandwidth_mbps=(bandwidths or {}).get(name, 100.0),
            console_log=False,
        )
        for key, value in overrides.items():
            setattr(cfg, key, value)
        nodes.append(Node(name, cfg))
    for node in nodes:
        node.connect()
    return nodes


@pytest.fixture
def network():
    nodes = make_network(
        ["nodo-01", "nodo-02", "nodo-03"],
        bandwidths={"nodo-01": 100, "nodo-02": 50, "nodo-03": 200},
    )
    yield nodes
    for node in nodes:
        node.disconnect()


def test_descubrimiento_automatico_de_tres_nodos(network):
    assert all(n.wait_for_peers(2, timeout=8) for n in network)
    for node in network:
        ids = {p.node_id for p in node.peers.active()}
        assert ids == {n.node_id for n in network} - {node.node_id}
    assert network[0].metrics.snapshot()["avg_discovery_time_sec"] is not None


def test_mide_latencia_entre_nodos(network):
    network[0].wait_for_peers(2, timeout=8)
    assert wait_until(
        lambda: all(p.latency_ms is not None for p in network[0].peers.active())
    )


def test_tarea_ml_se_ejecuta_en_otro_nodo(network):
    emisor = network[0]
    assert emisor.wait_for_peers(2, timeout=8)
    task = Task(
        "regresion_lineal",
        {"n_samples": 2000, "seed": 7, "true_slope": 2.35, "true_intercept": 0.81},
        requirements={"cpu": 1, "memory": 64},
    )
    result = emisor.submit(task, allow_local=False, timeout=10)
    assert task.state == COMPLETED
    assert task.executed_by in {"nodo-02", "nodo-03"}
    assert abs(result["slope"] - 2.35) < 0.1
    assert abs(result["intercept"] - 0.81) < 0.3
    assert emisor.metrics.snapshot()["tasks_completed"] == 1


def test_candidatos_remotos_excluyen_al_nodo_local(network):
    emisor = network[0]
    assert emisor.wait_for_peers(2, timeout=8)
    candidates = emisor.candidates(allow_local=False)
    best, scores = emisor.scheduler.select_node(candidates)
    assert best is not None and set(scores) == {"nodo-02", "nodo-03"}


def test_ejecucion_local_cuando_se_permite(network):
    emisor = network[0]
    task = Task("echo", {"x": 1})
    assert emisor.submit(task, allow_local=True, timeout=5) == {"echo": {"x": 1}}


def test_reasigna_tarea_cuando_el_nodo_ejecutor_cae(network):
    emisor = network[0]
    assert emisor.wait_for_peers(2, timeout=8)
    task = Task(
        "regresion_lineal", {"n_samples": 500, "simulate_seconds": 4.0}
    )
    emisor.submit(task, allow_local=False, wait=False)
    assert wait_until(lambda: task.assigned_node is not None, timeout=3)
    victim = task.assigned_node
    first_worker = next(n for n in network if n.node_id == victim)
    assert wait_until(lambda: task.acked, timeout=3)

    first_worker.disconnect()  # el nodo cae a mitad de la tarea

    assert task.wait(timeout=15), "la tarea debía reasignarse y terminar"
    assert task.state == COMPLETED
    survivor = ({"nodo-02", "nodo-03"} - {victim}).pop()
    assert task.executed_by == survivor
    assert task.reassignments >= 1
    snapshot = emisor.metrics.snapshot()
    assert snapshot["tasks_reassigned"] >= 1
    assert snapshot["failures_detected"] >= 1
    assert snapshot["avg_recovery_time_sec"] is not None
    assert emisor.peers.get(victim).status == "OFFLINE"


def test_nodo_que_vuelve_se_reincorpora(network):
    emisor = network[0]
    assert emisor.wait_for_peers(2, timeout=8)
    victim = network[1]
    port = victim.port
    victim.disconnect()
    assert wait_until(
        lambda: emisor.peers.get("nodo-02").status == "OFFLINE", timeout=6
    )
    reborn = Node(
        "nodo-02",
        NodeConfig(
            port=port,
            seed_peers=[("127.0.0.1", emisor.port)],
            ip_address="127.0.0.1",
            beacon_interval=0.3,
            node_timeout=1.5,
            console_log=False,
        ),
    ).connect()
    try:
        assert wait_until(
            lambda: emisor.peers.get("nodo-02").status == "ONLINE", timeout=6
        )
    finally:
        reborn.disconnect()


def test_tarea_sin_candidatos_falla_tras_el_tiempo_de_espera():
    nodes = make_network(["solo"], queue_timeout=1.0)
    try:
        task = Task("echo", {}, requirements={"memory": 10**9})
        nodes[0].submit(task, allow_local=True, wait=False)
        assert task.wait(timeout=6)
        assert task.state == FAILED
    finally:
        nodes[0].disconnect()


def test_relojes_de_lamport_avanzan_con_la_comunicacion(network):
    assert network[0].wait_for_peers(2, timeout=8)
    assert all(n.clock.time > 0 for n in network)
