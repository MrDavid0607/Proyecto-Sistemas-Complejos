"""Experimentos de la Fase 3: latencia, descubrimiento, escalabilidad, estrategias de
asignación, tolerancia a fallos y disponibilidad.

Se ejecuta en UNO de los computadores (el nodo-01); los demás solo corren el nodo
(`scripts/start_node.ps1`). Este script crea su propio nodo, descubre al resto y lanza
las cargas de trabajo.

    python experiments/run_experiments.py --id nodo-01                 # todos
    python experiments/run_experiments.py --id nodo-01 --only strategies,fault
    python experiments/run_experiments.py --id nodo-01 --quick          # versión corta

Los resultados (CSV, JSON y gráficas) quedan en experiments/results/<fecha>/ y el informe
se genera con `python experiments/report.py`.
"""

import argparse
import csv
import json
import os
import platform
import random
import socket
import statistics
import sys
import threading
import time
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "applications"))

import common  # noqa: E402

from complexnet import Node, NodeConfig, Task  # noqa: E402
from complexnet.scheduler import STRATEGIES  # noqa: E402

REQ = {"cpu": 1, "memory": 64}


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def pct(values, p):
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(p / 100 * (len(ordered) - 1))))
    return ordered[index]


def mean(values):
    return statistics.fmean(values) if values else None


def stdev(values):
    return statistics.pstdev(values) if len(values) > 1 else 0.0


def write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    print(f"    -> {os.path.relpath(path, ROOT)}")


class Sampler:
    """Muestrea CPU/RAM de cada nodo (según los beacons) mientras corre una carga."""

    def __init__(self, node, interval=0.5):
        self.node, self.interval = node, interval
        self.cpu_used = {}
        self.ram_used = {}
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop.is_set():
            state = self.node.resources.state()
            self.cpu_used.setdefault(self.node.node_id, []).append(100 - state["cpu_free_pct"])
            for peer in self.node.peers.active():
                self.cpu_used.setdefault(peer.node_id, []).append(100 - peer.cpu_free_pct)
            self._stop.wait(self.interval)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(timeout=2)

    def mean_cpu(self):
        return {n: round(mean(v), 1) for n, v in self.cpu_used.items()}


def run_workload(node, params_list, name="monte_carlo_pi", requirements=None,
                 allow_local=True, timeout=300):
    """Lanza un lote de tareas y devuelve métricas del lote."""
    before = dict(node.metrics.counters)
    started = time.perf_counter()
    with Sampler(node) as sampler:
        tasks = node.map_tasks(name, params_list, requirements or REQ,
                               allow_local=allow_local, timeout=timeout)
        makespan = time.perf_counter() - started
    after = node.metrics.counters
    done = [t for t in tasks if t.state == "COMPLETED"]
    latencies = [t.completed_at - t.created_at for t in done]
    counts = common.tasks_per_node(tasks)
    return {
        "tasks": len(tasks),
        "completed": len(done),
        "makespan_sec": makespan,
        "throughput_tps": len(done) / makespan if makespan else 0.0,
        "latency_mean_sec": mean(latencies),
        "latency_p95_sec": pct(latencies, 95),
        "per_node": counts,
        "reassignments": sum(t.reassignments for t in tasks),
        "cpu_used_mean": sampler.mean_cpu(),
        "kb_sent_per_sec": (after["bytes_sent"] - before["bytes_sent"]) / 1024 / makespan,
        "kb_received_per_sec": (after["bytes_received"] - before["bytes_received"]) / 1024 / makespan,
    }


def imbalance(per_node, nodes):
    """Coeficiente de variación del reparto de tareas (0 = reparto perfecto)."""
    counts = [per_node.get(n, 0) for n in nodes]
    avg = mean(counts)
    return stdev(counts) / avg if avg else 0.0


def admin_post(url, path, body):
    request = urllib.request.Request(
        url + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read())


class Context:
    def __init__(self, args, node, out_dir):
        self.args, self.node, self.out = args, node, out_dir
        self.fast = args.quick
        self.admin_ports = dict(item.split("=") for item in args.admin_ports.split(",") if item)

    def workers(self, include_local=True):
        ids = [p.node_id for p in self.node.peers.active()
               if not p.node_id.startswith("probe-")]
        if include_local:
            ids.append(self.node.node_id)
        return sorted(ids)

    def admin_url(self, node_id):
        peer = self.node.peers.get(node_id)
        port = self.admin_ports.get(node_id, self.args.remote_http_port)
        return f"http://{peer.ip}:{port}"

    def inject_failure(self, node_id, seconds):
        admin_post(self.admin_url(node_id), "/admin/fail", {"seconds": seconds})

    def task_params(self, count, points=None, seed0=0):
        points = points or self.args.task_points
        return [{"n_points": points, "seed": seed0 + i} for i in range(count)]


# ---------------------------------------------------------------------------
# Experimentos
# ---------------------------------------------------------------------------

def exp_latency(ctx):
    """Latencia de red (PING/PONG) y de ida y vuelta de una tarea mínima."""
    print("\n[latency] latencia de comunicación")
    node = ctx.node
    samples = {}
    duration = 6 if ctx.fast else 20
    end = time.time() + duration
    while time.time() < end:
        for peer in node.peers.active():
            if peer.latency_ms is not None:
                samples.setdefault(peer.node_id, []).append(peer.latency_ms)
        time.sleep(0.5)
    rows = []
    for peer_id in ctx.workers(include_local=False):
        rtts = []
        for i in range(15 if ctx.fast else 50):
            task = Task("echo", {"i": i}, requirements={**REQ, "nodes": [peer_id]})
            started = time.perf_counter()
            node.submit(task, allow_local=False, timeout=15)
            rtts.append((time.perf_counter() - started) * 1000)
        ping = samples.get(peer_id, [])
        rows.append([peer_id, round(mean(ping), 3) if ping else "", round(min(ping), 3) if ping else "",
                     round(max(ping), 3) if ping else "", round(mean(rtts), 3),
                     round(pct(rtts, 50), 3), round(pct(rtts, 95), 3)])
        print(f"    {peer_id}: ping medio {rows[-1][1]} ms | tarea echo p50 {rows[-1][5]} ms, p95 {rows[-1][6]} ms")
    write_csv(os.path.join(ctx.out, "latency.csv"),
              ["node", "ping_mean_ms", "ping_min_ms", "ping_max_ms", "task_rtt_mean_ms",
               "task_rtt_p50_ms", "task_rtt_p95_ms"], rows)


def exp_discovery(ctx):
    """Tiempo que tarda un nodo nuevo en descubrir a todos los demás."""
    print("\n[discovery] tiempo de descubrimiento")
    args, node = ctx.args, ctx.node
    expected = len(ctx.workers(include_local=True))
    seeds = common.parse_peers(args.peers, args.port)
    seeds.append((node.ip_address, args.port))   # el nodo del experimento también es vecino
    trials = 3 if ctx.fast else 8
    rows = []
    for i in range(trials):
        cfg = NodeConfig(port=args.probe_port + i, discovery_port=args.port,
                         broadcast_address=None if args.broadcast.lower() == "none" else args.broadcast,
                         seed_peers=seeds, ip_address=args.ip, console_log=False)
        probe = Node(f"probe-{i}", cfg)
        started = time.perf_counter()
        probe.connect()
        ok = probe.wait_for_peers(expected, timeout=30)
        elapsed = time.perf_counter() - started
        probe.disconnect()
        rows.append([i + 1, round(elapsed, 3), len(probe.peers.active()), int(ok)])
        print(f"    intento {i + 1}: {elapsed:.2f} s ({'ok' if ok else 'incompleto'})")
        time.sleep(2.5)  # deja que los demás nodos olviden al sondeo
    # Las sondas detenidas siguen en la tabla hasta que vence el timeout: se espera
    # para que no sean candidatas en los experimentos siguientes.
    time.sleep(node.config.node_timeout + 1.5)
    write_csv(os.path.join(ctx.out, "discovery.csv"),
              ["trial", "seconds", "peers_found", "complete"], rows)


def exp_scalability(ctx):
    """Tiempo total y aceleración al aumentar el número de nodos y la carga."""
    print("\n[scalability] escalabilidad")
    node = ctx.node
    workers = ctx.workers()
    total = 12 if ctx.fast else 24
    trials = 1 if ctx.fast else 3
    rows = []
    base = None
    for k in range(1, len(workers) + 1):
        subset = workers[:k]
        makespans, throughputs = [], []
        for t in range(trials):
            result = run_workload(node, ctx.task_params(total, seed0=100 * t),
                                  requirements={**REQ, "nodes": subset})
            makespans.append(result["makespan_sec"])
            throughputs.append(result["throughput_tps"])
        avg = mean(makespans)
        base = base or avg
        rows.append([k, ",".join(subset), total, round(avg, 3), round(stdev(makespans), 3),
                     round(mean(throughputs), 2), round(base / avg, 2)])
        print(f"    {k} nodo(s): {avg:.2f} s | {mean(throughputs):.1f} tareas/s | "
              f"aceleración {base / avg:.2f}x")
    write_csv(os.path.join(ctx.out, "scalability_nodes.csv"),
              ["nodes", "which", "tasks", "makespan_sec", "makespan_std", "throughput_tps", "speedup"], rows)

    print("    incremento progresivo de la carga (todos los nodos)")
    rows = []
    for load in ([4, 8, 16] if ctx.fast else [4, 8, 16, 32, 64]):
        result = run_workload(node, ctx.task_params(load, seed0=1000))
        rows.append([load, round(result["makespan_sec"], 3), round(result["throughput_tps"], 2),
                     round(result["latency_mean_sec"], 3), round(result["latency_p95_sec"], 3),
                     result["completed"], round(result["kb_sent_per_sec"], 2),
                     round(result["kb_received_per_sec"], 2),
                     json.dumps(result["cpu_used_mean"])])
        print(f"    {load:>3} tareas: {rows[-1][1]} s | {rows[-1][2]} t/s | latencia media "
              f"{rows[-1][3]} s | p95 {rows[-1][4]} s | CPU {result['cpu_used_mean']}")
    write_csv(os.path.join(ctx.out, "scalability_load.csv"),
              ["tasks", "makespan_sec", "throughput_tps", "latency_mean_sec", "latency_p95_sec",
               "completed", "kb_sent_per_sec", "kb_received_per_sec", "cpu_used_mean_pct"], rows)


def exp_strategies(ctx):
    """Compara las estrategias de asignación sobre la misma carga."""
    print("\n[strategies] comparación de estrategias de asignación")
    node = ctx.node
    workers = ctx.workers()
    total = 18 if ctx.fast else 36
    trials = 1 if ctx.fast else 3
    rng = random.Random(7)
    sizes = [rng.choice([ctx.args.task_points // 2, ctx.args.task_points, ctx.args.task_points * 2])
             for _ in range(total)]          # tareas de tamaño distinto (carga heterogénea)
    rows = []
    original = node.config.strategy
    for strategy in STRATEGIES:
        node.set_strategy(strategy)
        agg = {"makespan": [], "lat_mean": [], "lat_p95": [], "imb": [], "per": {}}
        for t in range(trials):
            params = [{"n_points": s, "seed": 500 * t + i} for i, s in enumerate(sizes)]
            result = run_workload(node, params)
            agg["makespan"].append(result["makespan_sec"])
            agg["lat_mean"].append(result["latency_mean_sec"])
            agg["lat_p95"].append(result["latency_p95_sec"])
            agg["imb"].append(imbalance(result["per_node"], workers))
            for n, c in result["per_node"].items():
                agg["per"][n] = agg["per"].get(n, 0) + c
        distribution = {n: round(agg["per"].get(n, 0) / trials, 1) for n in workers}
        rows.append([strategy, total, round(mean(agg["makespan"]), 3), round(stdev(agg["makespan"]), 3),
                     round(mean(agg["lat_mean"]), 3), round(mean(agg["lat_p95"]), 3),
                     round(mean(agg["imb"]), 3), json.dumps(distribution)])
        print(f"    {strategy:<15} tiempo total {rows[-1][2]} s | latencia media {rows[-1][4]} s | "
              f"desbalance {rows[-1][6]} | reparto {distribution}")
    node.set_strategy(original)
    write_csv(os.path.join(ctx.out, "strategies.csv"),
              ["strategy", "tasks", "makespan_sec", "makespan_std", "latency_mean_sec",
               "latency_p95_sec", "imbalance_cv", "tasks_per_node"], rows)


def exp_fault(ctx):
    """Un nodo cae durante una carga: detección, reasignación y recuperación."""
    print("\n[fault] tolerancia a fallos")
    node = ctx.node
    victims = ctx.workers(include_local=False)
    trials = 2 if ctx.fast else 4
    total = 12 if ctx.fast else 20
    rows = []
    for t in range(trials):
        victim = victims[t % len(victims)]
        events = []
        node.on_event(lambda r: events.append(r) if r["event"] in (
            "FAILURE", "TASK_REASSIGN", "RECOVERY") else None)
        before = dict(node.metrics.counters)
        recov_before = len(node.metrics.recovery_times)
        started = time.time()
        params = [{"n_points": ctx.args.task_points, "seed": i, "simulate_seconds": 1.0}
                  for i in range(total)]
        threading.Timer(2.0, ctx.inject_failure, args=(victim, 25)).start()
        injected_at = started + 2.0
        tasks = node.map_tasks("monte_carlo_pi", params, REQ, allow_local=True, timeout=240)
        makespan = time.time() - started
        completed = sum(1 for x in tasks if x.state == "COMPLETED")
        detect = next((e["ts"] - injected_at for e in events
                       if e["event"] == "FAILURE" and e.get("peer") == victim), None)
        recoveries = node.metrics.recovery_times[recov_before:]
        reassigned = sum(x.reassignments for x in tasks)
        rows.append([t + 1, victim, total, completed, round(completed / total * 100, 1), reassigned,
                     round(detect, 2) if detect is not None else "",
                     round(max(recoveries), 2) if recoveries else "", round(makespan, 2)])
        print(f"    intento {t + 1}: cae {victim} | completadas {completed}/{total} | "
              f"reasignadas {reassigned} | detección {rows[-1][6]} s | recuperación {rows[-1][7]} s")
        time.sleep(28)   # el nodo "caído" vuelve y se reincorpora antes del siguiente intento
        node.log._subscribers.clear()
    write_csv(os.path.join(ctx.out, "fault_tolerance.csv"),
              ["trial", "victim", "tasks", "completed", "completion_pct", "reassigned",
               "detection_sec", "recovery_sec", "makespan_sec"], rows)


def exp_availability(ctx):
    """Disponibilidad del servicio con una caída: sondas periódicas durante la falla."""
    print("\n[availability] disponibilidad del servicio")
    node = ctx.node
    victim = ctx.workers(include_local=False)[0]
    original = node.config.strategy
    node.set_strategy("round_robin")     # todas las sondas reparten entre todos los nodos
    duration, fail_at, fail_len = (30, 8, 10) if ctx.fast else (70, 15, 20)
    interval, sla = 0.5, 3.0
    probes = []
    lock = threading.Lock()

    def probe(index, sent):
        task = Task("echo", {"probe": index}, requirements=REQ)
        node.submit(task, allow_local=False, wait=False)
        task.wait(30)
        with lock:
            probes.append((sent, task.state == "COMPLETED",
                           (task.completed_at - task.created_at) if task.completed_at else None,
                           task.reassignments))

    start = time.time()
    threading.Timer(fail_at, ctx.inject_failure, args=(victim, fail_len)).start()
    threads, index = [], 0
    while time.time() - start < duration:
        sent = time.time() - start
        thread = threading.Thread(target=probe, args=(index, sent), daemon=True)
        thread.start()
        threads.append(thread)
        index += 1
        time.sleep(interval)
    for thread in threads:
        thread.join(timeout=40)
    node.set_strategy(original)
    probes.sort()
    ok = sum(1 for _, done, _, _ in probes if done)
    within = sum(1 for _, done, lat, _ in probes if done and lat is not None and lat <= sla)
    availability = ok / len(probes) * 100
    sla_pct = within / len(probes) * 100
    print(f"    sondas: {len(probes)} | completadas {availability:.1f}% | dentro de {sla:g} s: {sla_pct:.1f}% "
          f"(falla de {victim} entre t={fail_at}s y t={fail_at + fail_len}s)")
    write_csv(os.path.join(ctx.out, "availability.csv"),
              ["sent_at_sec", "completed", "latency_sec", "reassignments"],
              [[round(s, 2), int(d), "" if lat is None else round(lat, 3), r] for s, d, lat, r in probes])
    with open(os.path.join(ctx.out, "availability_summary.json"), "w", encoding="utf-8") as handle:
        json.dump({"victim": victim, "fail_at_sec": fail_at, "fail_seconds": fail_len,
                   "probes": len(probes), "completed_pct": round(availability, 2),
                   "within_sla_pct": round(sla_pct, 2), "sla_sec": sla}, handle, indent=2)


EXPERIMENTS = {
    "latency": exp_latency,
    "discovery": exp_discovery,
    "scalability": exp_scalability,
    "strategies": exp_strategies,
    "fault": exp_fault,
    "availability": exp_availability,
}


def collect_metadata(ctx):
    import psutil
    node = ctx.node
    meta = {
        "date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "host": socket.gethostname(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cpu_count": psutil.cpu_count(),
        "ram_gb": round(psutil.virtual_memory().total / 2**30, 1),
        "experiment_node": node.node_id,
        "nodes": [{"id": node.node_id, "ip": node.ip_address}] + [
            {"id": p.node_id, "ip": p.ip, "bandwidth_mbps": p.bandwidth_mbps}
            for p in node.peers.active()],
        "strategy_default": node.config.strategy,
        "task_points": ctx.args.task_points,
        "quick": ctx.args.quick,
        "environment": ctx.args.environment,
    }
    return meta


def main():
    parser = common.add_node_arguments(argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter))
    parser.add_argument("--only", default=",".join(EXPERIMENTS),
                        help=f"experimentos a correr: {','.join(EXPERIMENTS)}")
    parser.add_argument("--quick", action="store_true", help="versión corta (prueba rápida)")
    parser.add_argument("--task-points", type=int, default=12_000_000,
                        help="puntos Monte Carlo por tarea (define la duración de cada tarea)")
    parser.add_argument("--probe-port", type=int, default=9970)
    parser.add_argument("--remote-http-port", type=int, default=8000,
                        help="puerto del panel HTTP de los demás nodos (para inyectar fallos)")
    parser.add_argument("--admin-ports", default="",
                        help="puertos HTTP por nodo si difieren: nodo-02=8302,nodo-03=8303")
    parser.add_argument("--environment", default="3 computadores en red local",
                        help="descripción del entorno para el informe")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    args.http_port = args.http_port or 0

    out_dir = args.out or os.path.join(ROOT, "experiments", "results", time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(out_dir, exist_ok=True)

    node, server = common.start_node(args, console_log=False)
    ctx = Context(args, node, out_dir)
    try:
        print(f"Nodos en el clúster: {ctx.workers()}")
        meta = collect_metadata(ctx)
        with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8") as handle:
            json.dump(meta, handle, indent=2)
        for name in args.only.split(","):
            name = name.strip()
            if name not in EXPERIMENTS:
                sys.exit(f"experimento desconocido: {name}")
            EXPERIMENTS[name](ctx)
        with open(os.path.join(out_dir, "node_metrics.json"), "w", encoding="utf-8") as handle:
            json.dump(node.metrics.snapshot(), handle, indent=2)
        print(f"\nListo. Resultados en {out_dir}")
        print("Genera el informe con:  python experiments/report.py")
    finally:
        common.stop_node(node, server)


if __name__ == "__main__":
    main()
