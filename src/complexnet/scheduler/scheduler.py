"""Distributed Scheduler: selecciona el nodo más apto para una tarea.

Implementa el modelo de asignación del diseño (sección 9):

    V_cand = { i | A_i  y  C_i >= C_req  y  M_i >= M_req }
    X'_i   = (X_i - X_min) / (X_max - X_min)         X en {C, M, B}
    L'_i   = (L_max - L_i) / (L_max - L_min)
    F(i,j) = w1*C' + w2*M' + w3*B' + w4*R - w5*(1 - L')
    i*     = argmax F(i,j)    (desempate: menor latencia, luego mayor reputación)
"""

from dataclasses import dataclass

DEFAULT_WEIGHTS = {
    "cpu": 0.40,
    "memory": 0.40,
    "bandwidth": 0.10,
    "reputation": 0.05,
    "latency": 0.05,
}

TIE_EPSILON = 1e-9


@dataclass
class Candidate:
    node_id: str
    cpu: float          # C_i: CPU libre (%)
    memory: float       # M_i: memoria libre (MB)
    bandwidth: float    # B_i: ancho de banda estimado (Mbps)
    reputation: float   # R_i en [0, 1]
    latency: float      # L_i: latencia (ms)
    available: bool = True  # A_i


def normalize(values, inverse=False):
    """Min-max a [0,1]. Con `inverse`, el menor valor obtiene 1 (latencia).

    Si todos los valores son iguales no hay diferencia entre candidatos y todos
    reciben 1.0 (para la latencia: sin penalización).
    """
    lowest, highest = min(values), max(values)
    if highest == lowest:
        return [1.0 for _ in values]
    if inverse:
        return [(highest - v) / (highest - lowest) for v in values]
    return [(v - lowest) / (highest - lowest) for v in values]


def filter_candidates(nodes, cpu_required=0.0, memory_required=0.0):
    return [
        n
        for n in nodes
        if n.available and n.cpu >= cpu_required and n.memory >= memory_required
    ]


def score_candidates(candidates, weights=None):
    """Devuelve {node_id: F(i,j)} calculado sobre `candidates` ya filtrados."""
    w = weights or DEFAULT_WEIGHTS
    if not candidates:
        return {}
    c_norm = normalize([n.cpu for n in candidates])
    m_norm = normalize([n.memory for n in candidates])
    b_norm = normalize([n.bandwidth for n in candidates])
    l_norm = normalize([n.latency for n in candidates], inverse=True)
    scores = {}
    for i, node in enumerate(candidates):
        scores[node.node_id] = (
            w["cpu"] * c_norm[i]
            + w["memory"] * m_norm[i]
            + w["bandwidth"] * b_norm[i]
            + w["reputation"] * node.reputation
            - w["latency"] * (1.0 - l_norm[i])
        )
    return scores


def _break_tie(a, b):
    if a.latency != b.latency:
        return a if a.latency < b.latency else b
    return a if a.reputation >= b.reputation else b


class DistributedScheduler:

    def __init__(self, weights=None):
        self.weights = dict(weights or DEFAULT_WEIGHTS)
        total = sum(self.weights.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"los pesos deben sumar 1 (suman {total})")

    def select_node(self, nodes, cpu_required=0.0, memory_required=0.0):
        """Devuelve (mejor_candidato | None, {node_id: score}).

        Si no hay candidatos aptos devuelve (None, {}): la tarea se encola y se
        reintenta en el siguiente ciclo.
        """
        candidates = filter_candidates(nodes, cpu_required, memory_required)
        if not candidates:
            return None, {}
        scores = score_candidates(candidates, self.weights)
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
