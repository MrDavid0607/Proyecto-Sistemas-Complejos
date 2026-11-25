"""Pruebas de la Fase 3: estrategias, API de alto nivel, alertas, fallo simulado y apps."""

import time

import numpy as np
import pytest

from complexnet import Node, Task
from complexnet.scheduler import (
    STRATEGIES,
    Candidate,
    DistributedScheduler,
    normalize,
    score_candidates,
)
from complexnet.node import detect_broadcast
from complexnet.tasks import executors

from test_integration import make_network, wait_until


def idle_nodes(loads):
    """Tres nodos casi idénticos (CPU/RAM con ruido mínimo) y cargas dadas."""
    return [
        Candidate("A", cpu=97.5, memory=4500, bandwidth=100, reputation=1, latency=0.3, load=loads[0]),
        Candidate("B", cpu=96.1, memory=4490, bandwidth=100, reputation=1, latency=0.3, load=loads[1]),
        Candidate("C", cpu=97.0, memory=4495, bandwidth=100, reputation=1, latency=0.3, load=loads[2]),
    ]


# ------------------------------------------------------------ estrategias

def test_todas_las_estrategias_existen_y_eligen_un_candidato():
    for strategy in STRATEGIES:
        best, scores = DistributedScheduler(strategy=strategy, seed=1).select_node(idle_nodes([0, 0, 0]))
        assert best.node_id in {"A", "B", "C"}
        assert best.node_id in scores


def test_estrategia_desconocida_se_rechaza():
    with pytest.raises(ValueError):
        DistributedScheduler(strategy="inventada")


def test_round_robin_reparte_de_forma_cclica():
    scheduler = DistributedScheduler(strategy="round_robin")
    chosen = [scheduler.select_node(idle_nodes([0, 0, 0]))[0].node_id for _ in range(6)]
    assert chosen == ["A", "B", "C", "A", "B", "C"]


def test_least_loaded_elige_el_nodo_con_menos_tareas():
    best, _ = DistributedScheduler(strategy="least_loaded").select_node(idle_nodes([3, 0, 2]))
    assert best.node_id == "B"


def test_lowest_latency_elige_la_menor_latencia():
    nodes = idle_nodes([0, 0, 0])
    nodes[2].latency = 0.1
    best, _ = DistributedScheduler(strategy="lowest_latency").select_node(nodes)
    assert best.node_id == "C"


def test_estrategias_respetan_el_filtro_de_recursos():
    for strategy in STRATEGIES:
        best, _ = DistributedScheduler(strategy=strategy, seed=1).select_node(
            idle_nodes([0, 0, 0]), cpu_required=99)
        assert best is None


def test_normalizacion_robusta_no_amplifica_diferencias_minimas():
    # CPU libre 97.5 vs 96.1: con min-max puro la diferencia ocuparía todo [0,1]
    assert normalize([97.5, 96.1]) == pytest.approx([1.0, 0.0])
    robust = normalize([97.5, 96.1], min_range=20.0)
    assert robust[0] - robust[1] < 0.1


def test_weighted_load_prefiere_el_nodo_menos_cargado_entre_nodos_equivalentes():
    scheduler = DistributedScheduler(strategy="weighted_load")
    best, _ = scheduler.select_node(idle_nodes([4, 0, 4]))   # B está libre
    assert best.node_id == "B"


def test_weighted_del_diseno_ignora_la_carga():
    best, _ = DistributedScheduler(strategy="weighted").select_node(idle_nodes([9, 9, 0]))
    assert best.node_id == "A"          # gana por el ruido de CPU/RAM, sin mirar la carga


def test_el_ejemplo_del_diseno_no_cambia_con_la_normalizacion_estandar():
    nodes = [
        Candidate("N1", 80, 4096, 50, 0.9, 20),
        Candidate("N2", 60, 8192, 100, 0.7, 10),
        Candidate("N3", 90, 2048, 30, 0.8, 40),
    ]
    scores = score_candidates(nodes)
    assert max(scores, key=scores.get) == "N2"


# ------------------------------------------------------------- ejecutores

def test_normal_equations_suma_de_fragmentos_equivale_a_regresion_total():
    base = {"n_samples": 4000, "n_features": 4, "model_seed": 5, "data_seed": 11, "noise": 0.3}
    parts = [executors.normal_equations({**base, "shard": s}) for s in range(5)]
    xtx = sum(np.array(p["xtx"]) for p in parts)
    xty = sum(np.array(p["xty"]) for p in parts)
    weights = np.linalg.solve(xtx, xty)
    true = executors._model_weights(4, 5)
    assert np.max(np.abs(weights - true)) < 0.05


def test_evaluate_model_da_r2_alto_con_los_pesos_correctos():
    base = {"n_samples": 3000, "n_features": 3, "model_seed": 9, "data_seed": 1, "noise": 0.2}
    true = executors._model_weights(3, 9)
    result = executors.execute("evaluate_model", {**base, "shard": 50, "weights": true.tolist()})
    assert result["r2"] > 0.98


def test_monte_carlo_pi_es_reproducible_y_cercano_a_pi():
    result = executors.execute("monte_carlo_pi", {"n_points": 500_000, "seed": 3})
    assert result == executors.execute("monte_carlo_pi", {"n_points": 500_000, "seed": 3})
    assert 4 * result["inside"] / result["total"] == pytest.approx(3.1416, abs=0.02)


def test_word_count_cuenta_palabras_largas():
    result = executors.execute("word_count", {"text": "nodo nodo red tarea tarea tarea"})
    assert result["counts"] == {"nodo": 2, "tarea": 3}


# --------------------------------------------------- red de 3 nodos (UDP)

@pytest.fixture
def network():
    nodes = make_network(["nodo-01", "nodo-02", "nodo-03"])
    yield nodes
    for node in nodes:
        node.disconnect()


def test_map_reparte_tareas_y_devuelve_resultados_en_orden(network):
    emisor = network[0]
    assert emisor.wait_for_peers(2, timeout=8)
    results = emisor.map("echo", [{"i": i} for i in range(9)], allow_local=False, timeout=20)
    assert [r["echo"]["i"] for r in results] == list(range(9))


def test_las_tareas_se_reparten_entre_los_nodos_con_weighted_load(network):
    emisor = network[0]
    assert emisor.wait_for_peers(2, timeout=8)
    tasks = emisor.map_tasks("monte_carlo_pi", [{"n_points": 800_000, "seed": i} for i in range(12)],
                             allow_local=True, timeout=60)
    executors_used = {t.executed_by for t in tasks}
    assert all(t.state == "COMPLETED" for t in tasks)
    assert len(executors_used) >= 2


def test_requisito_nodes_restringe_los_candidatos(network):
    emisor = network[0]
    assert emisor.wait_for_peers(2, timeout=8)
    tasks = emisor.map_tasks("echo", [{} for _ in range(6)],
                             requirements={"nodes": ["nodo-03"]}, allow_local=False, timeout=20)
    assert {t.executed_by for t in tasks} == {"nodo-03"}


def test_alerta_se_difunde_a_los_demas_nodos(network):
    emisor = network[0]
    assert all(n.wait_for_peers(2, timeout=8) for n in network)
    emisor.raise_alert("warning", "CPU alta en nodo-01", peer="nodo-01")
    assert wait_until(lambda: all(len(n.alerts) == 1 for n in network), timeout=5)
    assert network[1].alerts[0]["origin"] == "nodo-01"
    assert emisor.metrics.snapshot()["alerts_raised"] == 1


def test_simular_fallo_hace_que_los_demas_lo_marquen_offline_y_luego_se_recupera(network):
    emisor, victima = network[0], network[1]
    assert emisor.wait_for_peers(2, timeout=8)
    victima.simulate_failure(3.0)
    assert wait_until(lambda: emisor.peers.get("nodo-02").status == "OFFLINE", timeout=6)
    assert wait_until(lambda: emisor.peers.get("nodo-02").status == "ONLINE", timeout=8)


def test_tarea_en_nodo_con_fallo_simulado_se_reasigna(network):
    emisor, victima = network[0], network[1]
    assert emisor.wait_for_peers(2, timeout=8)
    task = Task("echo", {}, requirements={"nodes": ["nodo-02", "nodo-03"]})
    victima.simulate_failure(8.0)
    time.sleep(0.2)
    emisor.submit(task, allow_local=False, wait=False)
    assert task.wait(timeout=20)
    assert task.state == "COMPLETED"
    assert task.executed_by == "nodo-03"


def test_on_event_recibe_los_eventos_del_nodo(network):
    emisor = network[0]
    seen = []
    emisor.on_event(lambda record: seen.append(record["event"]))
    emisor.wait_for_peers(2, timeout=8)
    emisor.submit(Task("echo", {}), allow_local=True, timeout=5)
    assert "TASK_COMPLETED" in seen


def test_las_ranuras_limitan_la_ejecucion_simultanea():
    nodes = make_network(["solo"], slots=1)
    try:
        node = nodes[0]
        started = time.time()
        tasks = node.map_tasks("echo", [{"simulate_seconds": 0.4} for _ in range(3)],
                               allow_local=True, timeout=10)
        assert all(t.state == "COMPLETED" for t in tasks)
        assert time.time() - started >= 1.1          # 3 tareas de 0.4 s en serie
    finally:
        nodes[0].disconnect()


def test_cambiar_estrategia_en_caliente(network):
    emisor = network[0]
    emisor.set_strategy("round_robin")
    assert emisor.scheduler.strategy == "round_robin"
    assert emisor.config.strategy == "round_robin"


def test_detect_broadcast_calcula_la_direccion_de_la_subred():
    import psutil
    import socket
    for addrs in psutil.net_if_addrs().values():
        for addr in addrs:
            if addr.family == socket.AF_INET and addr.netmask == "255.255.255.0" \
                    and not addr.address.startswith("127."):
                prefix = addr.address.rsplit(".", 1)[0]
                assert detect_broadcast(addr.address) == f"{prefix}.255"
                return
    pytest.skip("no hay una interfaz /24 para probar")
