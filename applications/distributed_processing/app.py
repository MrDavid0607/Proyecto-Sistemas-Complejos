"""Aplicación 2 — Procesamiento distribuido.

    python applications/distributed_processing/app.py --id nodo-01 --corpus docs

Dos trabajos de tipo map-reduce repartidos por la red:

  1. Análisis de archivos: se leen los archivos de texto de una carpeta, se parten en
     fragmentos, cada nodo cuenta las palabras de su fragmento (map) y este nodo
     combina los conteos (reduce).
  2. Cálculo colaborativo: estimación de π por Monte Carlo; cada nodo cuenta los puntos
     que caen dentro del círculo unidad en su fragmento.

Si un nodo cae durante el trabajo, sus fragmentos se reasignan automáticamente.
"""

import argparse
import math
import os
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import common  # noqa: E402

from complexnet.tasks import executors  # noqa: E402


def read_chunks(folder, chunk_chars):
    chunks, files = [], 0
    for root, _, names in os.walk(folder):
        if any(part in root for part in (".venv", ".git", "__pycache__", "logs", "output")):
            continue
        for name in sorted(names):
            if not name.lower().endswith((".md", ".txt", ".py")):
                continue
            try:
                with open(os.path.join(root, name), encoding="utf-8") as handle:
                    text = handle.read()
            except (OSError, UnicodeDecodeError):
                continue
            files += 1
            for i in range(0, len(text), chunk_chars):
                chunks.append(text[i:i + chunk_chars])
    return chunks, files


def word_count_job(node, args):
    folder = os.path.abspath(args.corpus)
    chunks, files = read_chunks(folder, args.chunk)
    if not chunks:
        sys.exit(f"No se encontró texto en {folder}")
    print(f"\n[1] Conteo de palabras: {files} archivos, {len(chunks)} fragmentos de "
          f"{args.chunk} caracteres")

    started = time.time()
    tasks = node.map_tasks("word_count", [{"text": c, "top": 400} for c in chunks],
                           {"cpu": 1, "memory": 64}, allow_local=not args.no_local,
                           timeout=300)
    failed = [t.task_id for t in tasks if t.state != "COMPLETED"]
    if failed:
        sys.exit(f"Fragmentos sin completar: {failed}")
    total = Counter()
    for task in tasks:                              # reduce
        total.update(task.result["counts"])
    distributed_time = time.time() - started

    started = time.time()                           # línea base en un solo proceso
    baseline = Counter()
    for chunk in chunks:
        baseline.update(executors.word_count({"text": chunk, "top": 400})["counts"])
    central_time = time.time() - started

    print(f"    tiempo distribuido {distributed_time:.2f} s | un solo nodo {central_time:.2f} s "
          f"| fragmentos por nodo {common.tasks_per_node(tasks)}")
    print(f"    reasignaciones: {sum(t.reassignments for t in tasks)} | "
          f"resultado idéntico a la línea base: {total == baseline}")
    print("    10 palabras más frecuentes:", ", ".join(f"{w} ({c})" for w, c in total.most_common(10)))


def pi_job(node, args):
    parts, per_part = args.pi_tasks, args.pi_points
    print(f"\n[2] Monte Carlo: π con {parts} tareas × {per_part:,} puntos")
    started = time.time()
    results = node.map("monte_carlo_pi",
                       [{"n_points": per_part, "seed": s} for s in range(parts)],
                       {"cpu": 1, "memory": 64}, allow_local=not args.no_local, timeout=300)
    inside = sum(r["inside"] for r in results)
    total = sum(r["total"] for r in results)
    estimate = 4.0 * inside / total
    print(f"    π ≈ {estimate:.6f} (error {abs(estimate - math.pi):.6f}) en "
          f"{time.time() - started:.2f} s")


def main():
    parser = common.add_node_arguments(argparse.ArgumentParser(description=__doc__,
                                       formatter_class=argparse.RawDescriptionHelpFormatter))
    parser.add_argument("--corpus", default=os.path.join(common.ROOT, "docs"),
                        help="carpeta con archivos .md/.txt/.py a analizar")
    parser.add_argument("--chunk", type=int, default=6000, help="caracteres por fragmento")
    parser.add_argument("--pi-tasks", type=int, default=12)
    parser.add_argument("--pi-points", type=int, default=3_000_000)
    parser.add_argument("--no-local", action="store_true")
    args = parser.parse_args()

    node, server = common.start_node(args)
    try:
        word_count_job(node, args)
        pi_job(node, args)
    finally:
        common.stop_node(node, server)


if __name__ == "__main__":
    main()
