import pytest

from complexnet.scheduler import (
    DEFAULT_WEIGHTS,
    Candidate,
    DistributedScheduler,
    filter_candidates,
    normalize,
    score_candidates,
)


def example_nodes():
    """Tabla de ejemplo de la sección 9.7 del diseño (CPU %, memoria MB, Mbps)."""
    return [
        Candidate("N1", cpu=80, memory=4096, bandwidth=50, reputation=0.9, latency=20),
        Candidate("N2", cpu=60, memory=8192, bandwidth=100, reputation=0.7, latency=10),
        Candidate("N3", cpu=90, memory=2048, bandwidth=30, reputation=0.8, latency=40),
    ]


def test_los_pesos_por_defecto_suman_uno():
    assert sum(DEFAULT_WEIGHTS.values()) == pytest.approx(1.0)


def test_pesos_invalidos_se_rechazan():
    with pytest.raises(ValueError):
        DistributedScheduler({**DEFAULT_WEIGHTS, "cpu": 0.9})


def test_normalizacion_directa_min_max():
    assert normalize([60, 80, 90]) == pytest.approx([0.0, 20 / 30, 1.0])


def test_normalizacion_inversa_para_latencia():
    assert normalize([20, 10, 40], inverse=True) == pytest.approx(
        [20 / 30, 1.0, 0.0]
    )


def test_normalizacion_con_valores_iguales_no_divide_por_cero():
    assert normalize([5, 5, 5]) == [1.0, 1.0, 1.0]
    assert normalize([5, 5], inverse=True) == [1.0, 1.0]


def test_ejemplo_numerico_del_diseno():
    scores = score_candidates(example_nodes())
    assert scores["N1"] == pytest.approx(0.4575, abs=0.005)  # ≈ 0.46
    assert scores["N2"] == pytest.approx(0.5350, abs=0.005)  # ≈ 0.54
    assert scores["N3"] == pytest.approx(0.3900, abs=0.005)  # ≈ 0.39


def test_selecciona_n2_en_el_ejemplo_del_diseno():
    best, _ = DistributedScheduler().select_node(example_nodes())
    assert best.node_id == "N2"


def test_filtra_nodos_no_disponibles_y_sin_recursos():
    nodes = example_nodes()
    nodes[1].available = False
    kept = filter_candidates(nodes, cpu_required=70, memory_required=1024)
    assert [n.node_id for n in kept] == ["N1", "N3"]
    best, _ = DistributedScheduler().select_node(
        nodes, cpu_required=70, memory_required=1024
    )
    assert best.node_id in {"N1", "N3"}


def test_sin_candidatos_devuelve_none():
    best, scores = DistributedScheduler().select_node(
        example_nodes(), cpu_required=99
    )
    assert best is None and scores == {}


def test_desempate_por_menor_latencia():
    a = Candidate("A", 50, 1000, 100, 0.5, latency=30)
    b = Candidate("B", 50, 1000, 100, 0.5, latency=10)
    # Puntaje distinto solo por latencia; igualamos anulando su peso.
    scheduler = DistributedScheduler(
        {"cpu": 0.4, "memory": 0.4, "bandwidth": 0.2, "reputation": 0.0, "latency": 0.0}
    )
    best, _ = scheduler.select_node([a, b])
    assert best.node_id == "B"


def test_desempate_por_mayor_reputacion_si_latencia_igual():
    a = Candidate("A", 50, 1000, 100, 0.2, latency=10)
    b = Candidate("B", 50, 1000, 100, 0.9, latency=10)
    scheduler = DistributedScheduler(
        {"cpu": 0.4, "memory": 0.4, "bandwidth": 0.2, "reputation": 0.0, "latency": 0.0}
    )
    best, _ = scheduler.select_node([a, b])
    assert best.node_id == "B"


def test_un_unico_candidato_se_selecciona():
    only = Candidate("solo", 10, 100, 10, 1.0, 0)
    best, _ = DistributedScheduler().select_node([only])
    assert best is only
