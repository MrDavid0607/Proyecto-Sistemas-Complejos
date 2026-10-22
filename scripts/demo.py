"""Demostración sobre la red Docker (3 nodos). Requiere `docker compose up -d`.

    python scripts/demo.py normal     # operación normal: tareas repartidas
    python scripts/demo.py carga      # incremento progresivo de la carga
    python scripts/demo.py fallo      # un nodo cae durante una tarea
    python scripts/demo.py ingreso    # un nodo sale y vuelve a entrar
    python scripts/demo.py todo
"""

import json
import subprocess
import sys
import time
import urllib.request

NODES = {"nodo-01": 8001, "nodo-02": 8002, "nodo-03": 8003}
CONTAINER = "complexnet-{}"


def http(port, path, body=None):
    url = f"http://localhost:{port}{path}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read())


def status(node):
    return http(NODES[node], "/status")


def wait_for_network(expected=2, timeout=40):
    print(f"Esperando a que nodo-01 descubra {expected} vecinos...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            peers = [p for p in status("nodo-01")["peers"] if p["status"] == "ONLINE"]
            if len(peers) >= expected:
                print("  vecinos:", ", ".join(sorted(p["node_id"] for p in peers)))
                return
        except OSError:
            pass
        time.sleep(1)
    sys.exit("La red no se formó a tiempo. ¿Está corriendo docker compose up?")


def submit(node, name="regresion_lineal", parameters=None, allow_local=False):
    body = {
        "name": name,
        "parameters": parameters or {},
        "requirements": {"cpu": 1, "memory": 64},
        "allow_local": allow_local,
    }
    return http(NODES[node], "/tasks", body)["task_id"]


def wait_task(node, task_id, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = http(NODES[node], f"/tasks/{task_id}")
        if task["state"] in ("COMPLETED", "FAILED"):
            return task
        time.sleep(0.5)
    raise TimeoutError(task_id)


def show(task):
    result = task["result"] or task["error"]
    print(
        f"  {task['task_id']}: {task['state']} en {task['executed_by']} "
        f"(intentos={task['attempts']}, reasignaciones={task['reassignments']}) "
        f"{result}"
    )


def docker(*args):
    subprocess.run(["docker", *args], check=True, capture_output=True)


def normal():
    print("\n== Escenario 1: operación normal ==")
    ids = [
        submit("nodo-01", parameters={"n_samples": 20000, "seed": s}) for s in range(5)
    ]
    for task_id in ids:
        show(wait_task("nodo-01", task_id))
    print("  métricas:", json.dumps(status("nodo-01")["metrics"]))


def carga():
    print("\n== Escenario 2: incremento progresivo de la carga ==")
    for batch in (2, 6, 12):
        started = time.time()
        ids = [
            submit("nodo-01", parameters={"n_samples": 50000, "seed": i,
                                          "simulate_seconds": 0.5})
            for i in range(batch)
        ]
        tasks = [wait_task("nodo-01", i) for i in ids]
        executors = sorted({t["executed_by"] for t in tasks})
        print(f"  {batch:>2} tareas en {time.time() - started:5.2f}s "
              f"repartidas entre {executors}")


def fallo():
    print("\n== Escenario 3: caída de un nodo durante una tarea ==")
    task_id = submit("nodo-01", parameters={"n_samples": 5000, "simulate_seconds": 20})
    time.sleep(2)
    task = http(NODES["nodo-01"], f"/tasks/{task_id}")
    victim = task["assigned_node"]
    print(f"  la tarea fue asignada a {victim}; se detiene su contenedor")
    docker("stop", CONTAINER.format(victim))
    started = time.time()
    task = wait_task("nodo-01", task_id, timeout=90)
    show(task)
    print(f"  recuperación completa en {time.time() - started:.1f}s tras la caída")
    docker("start", CONTAINER.format(victim))
    print(f"  {victim} reiniciado")
    time.sleep(6)


def ingreso():
    print("\n== Escenario 4: salida y entrada de un nodo ==")
    docker("stop", CONTAINER.format("nodo-03"))
    time.sleep(8)
    peers = {p["node_id"]: p["status"] for p in status("nodo-01")["peers"]}
    print("  tras detener nodo-03:", peers)
    docker("start", CONTAINER.format("nodo-03"))
    time.sleep(8)
    peers = {p["node_id"]: p["status"] for p in status("nodo-01")["peers"]}
    print("  tras reiniciarlo:    ", peers)


SCENARIOS = {"normal": normal, "carga": carga, "fallo": fallo, "ingreso": ingreso}


if __name__ == "__main__":
    choice = sys.argv[1] if len(sys.argv) > 1 else "todo"
    wait_for_network()
    for name in (SCENARIOS if choice == "todo" else [choice]):
        SCENARIOS[name]()
