"""Aplicación 3 — Inteligencia artificial: regresión lineal distribuida.

    python applications/ai_application/app.py --id nodo-01 --shards 12

Cómo funciona
  * Distribución de datos: el dataset sintético (y = w·x + b + ruido, con varias
    variables) se parte en fragmentos. Cada fragmento se genera dentro del nodo que
    lo procesa a partir de una semilla; por la red solo viajan parámetros pequeños.
  * Asignación de recursos: cada fragmento es una tarea `normal_equations` que el
    planificador reparte según CPU, memoria, ancho de banda, latencia, reputación y carga.
  * Información intercambiada: cada nodo devuelve los estadísticos suficientes de su
    fragmento (XtX, Xty, n, Σy, Σy²). La suma de los fragmentos es exactamente la
    regresión sobre todo el dataset; el nodo coordinador resuelve (XtX) w = Xty.
  * Evaluación distribuida: el modelo se evalúa en fragmentos nuevos (`evaluate_model`).
  * Si un nodo falla durante el entrenamiento, el gestor de tareas reasigna su
    fragmento a otro nodo y el resultado final no cambia.
  * Métricas: error de los pesos, R², MSE, tiempos y fragmentos por nodo.
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import common  # noqa: E402
import numpy as np  # noqa: E402

from complexnet import Task  # noqa: E402
from complexnet.tasks import executors  # noqa: E402


def solve(results):
    """Suma los estadísticos de todos los fragmentos y resuelve los pesos."""
    xtx = sum(np.array(r["xtx"]) for r in results)
    xty = sum(np.array(r["xty"]) for r in results)
    n = sum(r["n"] for r in results)
    weights = np.linalg.solve(xtx, xty)
    return weights, n


def main():
    parser = common.add_node_arguments(argparse.ArgumentParser(description=__doc__,
                                       formatter_class=argparse.RawDescriptionHelpFormatter))
    parser.add_argument("--shards", type=int, default=12, help="fragmentos de entrenamiento")
    parser.add_argument("--samples", type=int, default=50000, help="muestras por fragmento")
    parser.add_argument("--features", type=int, default=5)
    parser.add_argument("--eval-shards", type=int, default=4)
    parser.add_argument("--simulate-seconds", type=float, default=0.0,
                        help="alarga cada fragmento (emula un entrenamiento pesado)")
    parser.add_argument("--no-local", action="store_true",
                        help="no ejecutar fragmentos en este mismo nodo")
    args = parser.parse_args()

    node, server = common.start_node(args)
    try:
        base = {"n_samples": args.samples, "n_features": args.features,
                "model_seed": 1234, "data_seed": 100, "noise": 0.5}
        requirements = {"cpu": 1, "memory": 128}

        print(f"\nEntrenando con {args.shards} fragmentos × {args.samples} muestras "
              f"({args.shards * args.samples:,} muestras, {args.features} variables)...")
        started = time.time()
        train_params = [{**base, "shard": s, "simulate_seconds": args.simulate_seconds}
                        for s in range(args.shards)]
        tasks = node.map_tasks("normal_equations", train_params, requirements,
                               allow_local=not args.no_local, timeout=300)
        failed = [t.task_id for t in tasks if t.state != "COMPLETED"]
        if failed:
            sys.exit(f"Fragmentos sin completar: {failed}")
        weights, n_total = solve([t.result for t in tasks])
        train_time = time.time() - started

        true_w = executors._model_weights(args.features, base["model_seed"])
        weight_error = float(np.max(np.abs(weights - true_w)))
        reassigned = sum(t.reassignments for t in tasks)

        print(f"  entrenamiento distribuido: {train_time:.2f} s "
              f"(fragmentos por nodo: {common.tasks_per_node(tasks)}, "
              f"reasignaciones: {reassigned})")
        print(f"  pesos verdaderos : {np.round(true_w, 3).tolist()}")
        print(f"  pesos aprendidos : {np.round(weights, 3).tolist()}")
        print(f"  error máximo de los pesos: {weight_error:.4f}")

        eval_params = [{**base, "shard": 10_000 + s, "weights": weights.tolist()}
                       for s in range(args.eval_shards)]
        evaluations = node.map("evaluate_model", eval_params, requirements,
                               allow_local=not args.no_local)
        sse = sum(e["sse"] for e in evaluations)
        sst = sum(e["sst"] for e in evaluations)
        n_eval = sum(e["n"] for e in evaluations)
        r2, mse = 1.0 - sse / sst, sse / n_eval
        print(f"  evaluación distribuida en {args.eval_shards} fragmentos nuevos: "
              f"R² = {r2:.4f}, MSE = {mse:.4f}")

        # Línea base centralizada: todo el entrenamiento en un solo proceso.
        started = time.time()
        local = [executors.normal_equations({**base, "shard": s}) for s in range(args.shards)]
        solve(local)
        central_time = time.time() - started
        print(f"  línea base en un solo nodo: {central_time:.2f} s "
              f"(aceleración {central_time / train_time:.2f}×)")

        os.makedirs(os.path.join(os.path.dirname(__file__), "output"), exist_ok=True)
        out = os.path.join(os.path.dirname(__file__), "output", "resultado.json")
        with open(out, "w", encoding="utf-8") as handle:
            json.dump({
                "shards": args.shards, "samples_per_shard": args.samples,
                "features": args.features, "total_samples": n_total,
                "train_time_sec": round(train_time, 3),
                "centralized_time_sec": round(central_time, 3),
                "shards_per_node": common.tasks_per_node(tasks),
                "reassignments": reassigned,
                "weight_error_max": weight_error, "r2": r2, "mse": mse,
                "metrics": node.metrics.snapshot(),
            }, handle, indent=2)
        print(f"\nResultados guardados en {out}")
    finally:
        common.stop_node(node, server)


if __name__ == "__main__":
    main()
