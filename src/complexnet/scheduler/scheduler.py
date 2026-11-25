"""Distributed Scheduler: selecciona el nodo más apto para una tarea.

Estrategia por defecto del diseño ("weighted", sección 9):

    V_cand = { i | A_i  y  C_i >= C_req  y  M_i >= M_req }
    X'_i   = (X_i - X_min) / (X_max - X_min)         X en {C, M, B}
    L'_i   = (L_max - L_i) / (L_max - L_min)
    F(i,j) = w1*C' + w2*M' + w3*B' + w4*R - w5*(1 - L')
    i*     = argmax F(i,j)    (desempate: menor latencia, luego mayor reputación)

Fase 3: el scheduler admite varias estrategias intercambiables para poder
compararlas experimentalmente:

    weighted       F(i,j) del diseño (no mira la carga actual)
    weighted_load  F(i,j) con un término de penalización por carga actual L_i
                   (el término de carga de la formulación original del taller) y
                   normalización robusta (rango mínimo significativo por métrica)
    least_loaded   menor número de tareas en curso (desempate: más CPU libre)
    lowest_latency menor latencia medida
    round_robin    reparto cíclico entre candidatos aptos
    random         candidato apto al azar
"""

import random
from dataclasses import dataclass

DEFAULT_WEIGHTS = {
    "cpu": 0.40,
    "memory": 0.40,
    "bandwidth": 0.10,
    "reputation": 0.05,
    "latency": 0.05,
}

LOAD_WEIGHTS = {
    "cpu": 0.25,
    "memory": 0.25,
    "bandwidth": 0.10,
    "reputation": 0.05,
    "latency": 0.05,
    "load": 0.30,
}

STRATEGIES = (
    "weighted",
    "weighted_load",
    "least_loaded",
    "lowest_latency",
    "round_robin",
    "random",
)

TIE_EPSILON = 1e-9

# Rangos mínimos significativos para la normalización robusta (weighted_load):
MIN_RANGE_CPU = 20.0        # puntos porcentuales de CPU libre
MIN_RANGE_FRACTION = 0.20   # fracción del mayor valor (memoria y ancho de banda)
MIN_RANGE_LATENCY = 5.0     # milisegundos


@dataclass
class Candidate:
    node_id: str
    cpu: float          # C_i: CPU libre (%)
    memory: float       # M_i: memoria libre (MB)
    bandwidth: float    # B_i: ancho de banda estimado (Mbps)
    reputation: float   # R_i en [0, 1]
    latency: float      # L_i: latencia (ms)
    available: bool = True  # A_i
    load: float = 0.0   # tareas en curso en el nodo (incluye las enviadas por mí)


def normalize(values, inverse=False, min_range=0.0):
    """Min-max a [0,1]. Con `inverse`, el menor valor obtiene 1 (latencia).

    Si todos los valores son iguales no hay diferencia entre candidatos y todos
    reciben 1.0 (para la latencia: sin penalización).

    `min_range` (Fase 3, normalización robusta): si el rango observado es menor que
    este valor, se divide por `min_range` en vez de por el rango. Así, diferencias
    insignificantes entre nodos casi idénticos (p. ej. 97 % y 95 % de CPU libre) no se
    amplifican hasta ocupar todo el intervalo [0,1].
    """
    lowest, highest = min(values), max(values)
    span = highest - lowest
    if span == 0:
        return [1.0 for _ in values]
    denominator = max(span, min_range)
    if inverse:
        return [(highest - v) / denominator for v in values]
    return [(v - lowest) / denominator for v in values]


def filter_candidates(nodes, cpu_required=0.0, memory_required=0.0):
    return [
        n
        for n in nodes
        if n.available and n.cpu >= cpu_required and n.memory >= memory_required
    ]


def score_candidates(candidates, weights=None, robust=False):
    """Devuelve {node_id: F(i,j)} calculado sobre `candidates` ya filtrados.

    Si `weights` incluye la clave "load", se resta w_load * carga normalizada
    (0 cuando todos los candidatos tienen la misma carga). Con `robust=True` la
    normalización usa un rango mínimo significativo por métrica (ver `normalize`).
    """
    w = weights or DEFAULT_WEIGHTS
    if not candidates:
        return {}
    cpu = [n.cpu for n in candidates]
    mem = [n.memory for n in candidates]
    bw = [n.bandwidth for n in candidates]
    lat = [n.latency for n in candidates]
    if robust:
        c_norm = normalize(cpu, min_range=MIN_RANGE_CPU)
        m_norm = normalize(mem, min_range=MIN_RANGE_FRACTION * max(mem))
        b_norm = normalize(bw, min_range=MIN_RANGE_FRACTION * max(bw))
        l_norm = normalize(lat, inverse=True, min_range=MIN_RANGE_LATENCY)
    else:
        c_norm = normalize(cpu)
        m_norm = normalize(mem)
        b_norm = normalize(bw)
        l_norm = normalize(lat, inverse=True)
    loads = [n.load for n in candidates]
    if "load" in w and max(loads) != min(loads):
        load_norm = [(v - min(loads)) / (max(loads) - min(loads)) for v in loads]
    else:
        load_norm = [0.0 for _ in loads]
    scores = {}
    for i, node in enumerate(candidates):
        score = (
            w["cpu"] * c_norm[i]
            + w["memory"] * m_norm[i]
            + w["bandwidth"] * b_norm[i]
            + w["reputation"] * node.reputation
            - w["latency"] * (1.0 - l_norm[i])
        )
        if "load" in w:
            score -= w["load"] * load_norm[i]
        scores[node.node_id] = score
    return scores


def _break_tie(a, b):
    if a.latency != b.latency:
        return a if a.latency < b.latency else b
    return a if a.reputation >= b.reputation else b


class DistributedScheduler:

    def __init__(self, weights=None, strategy="weighted", seed=None):
        if strategy not in STRATEGIES:
            raise ValueError(f"estrategia desconocida: {strategy!r}")
        self.strategy = strategy
        self.weights = dict(weights or DEFAULT_WEIGHTS)
        self.load_weights = dict(LOAD_WEIGHTS)
        for name, table in (("weights", self.weights),
                            ("load_weights", self.load_weights)):
            total = sum(table.values())
            if abs(total - 1.0) > 1e-6:
                raise ValueError(f"los pesos deben sumar 1 (suman {total})")
        self._rr_index = 0
        self._rng = random.Random(seed)

    def select_node(self, nodes, cpu_required=0.0, memory_required=0.0):
        """Devuelve (mejor_candidato | None, {node_id: score}).

        Si no hay candidatos aptos devuelve (None, {}): la tarea se encola y se
        reintenta en el siguiente ciclo.
        """
        candidates = filter_candidates(nodes, cpu_required, memory_required)
        if not candidates:
            return None, {}
        if self.strategy == "weighted":
            return self._argmax(candidates, score_candidates(candidates, self.weights))
        if self.strategy == "weighted_load":
            return self._argmax(
                candidates,
                score_candidates(candidates, self.load_weights, robust=True),
            )
        if self.strategy == "least_loaded":
            best = min(candidates, key=lambda n: (n.load, -n.cpu, n.node_id))
        elif self.strategy == "lowest_latency":
            best = min(candidates, key=lambda n: (n.latency, n.node_id))
        elif self.strategy == "round_robin":
            ordered = sorted(candidates, key=lambda n: n.node_id)
            best = ordered[self._rr_index % len(ordered)]
            self._rr_index += 1
        else:  # random
            best = self._rng.choice(candidates)
        return best, {best.node_id: 0.0}

    @staticmethod
    def _argmax(candidates, scores):
        best = None
        for node in candidates:
            if best is None:
                best = node
                continue
            diff = scores[node.node_id] - scores[best.node_id]
            if diff > TIE_EPSILON:
                best = node
            elif abs(diff) <= TIE_EPSILON:
                best = _break_tie(best, node)
        return best, scores
