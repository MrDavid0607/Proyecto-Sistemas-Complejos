"""Ejemplo mínimo de la API: tres nodos en un mismo computador (localhost).

    set PYTHONPATH=src            (PowerShell: $env:PYTHONPATH = "src")
    python examples/basic_usage.py
"""

from complexnet import Node, NodeConfig, Task

PORTS = {"nodo-01": 9201, "nodo-02": 9202, "nodo-03": 9203}


def make_node(name):
    seeds = [("127.0.0.1", p) for n, p in PORTS.items() if n != name]
    config = NodeConfig(
        port=PORTS[name], seed_peers=seeds, ip_address="127.0.0.1",
        bandwidth_mbps=100, console_log=False,
    )
    return Node(name, config)


nodes = [make_node(name).connect() for name in PORTS]
emisor = nodes[0]
emisor.wait_for_peers(2)

task = Task(
    name="regresion_lineal",
    parameters={"n_samples": 10000, "seed": 42},
    requirements={"cpu": 1, "memory": 256},
)
result = emisor.submit(task, allow_local=False, timeout=30)
print(f"Ejecutada en {task.executed_by}: {result}")

for node in nodes:
    node.disconnect()
