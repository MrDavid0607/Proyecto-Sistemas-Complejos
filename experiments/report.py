"""Genera el informe experimental (Markdown + gráficas) a partir de los resultados.

    python experiments/report.py                       # usa la corrida más reciente
    python experiments/report.py experiments/results/20261125-153000
"""

import csv
import json
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RESULTS = os.path.join(ROOT, "experiments", "results")
DOCS = os.path.join(ROOT, "docs", "pruebas")
FIGS = os.path.join(DOCS, "figuras")

STRATEGY_NAMES = {
    "weighted": "F(i,j) del diseño",
    "weighted_load": "F(i,j) + carga",
    "least_loaded": "Menos cargado",
    "lowest_latency": "Menor latencia",
    "round_robin": "Round-robin",
    "random": "Aleatoria",
}
COLORS = ["#2b6cb0", "#2f9e6f", "#d69e2e", "#c05621", "#805ad5", "#718096"]


def latest_run():
    runs = sorted(d for d in os.listdir(RESULTS)
                  if os.path.isdir(os.path.join(RESULTS, d)) and os.path.exists(
                      os.path.join(RESULTS, d, "meta.json")))
    if not runs:
        sys.exit("No hay resultados en experiments/results/")
    return os.path.join(RESULTS, runs[-1])


def read(run, name):
    path = os.path.join(run, name)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def num(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def table(header, rows):
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def save(fig, name):
    os.makedirs(FIGS, exist_ok=True)
    fig.tight_layout()
    fig.savefig(os.path.join(FIGS, name), dpi=130)
    plt.close(fig)
    return f"figuras/{name}"


def build(run):
    meta = json.load(open(os.path.join(run, "meta.json"), encoding="utf-8"))
    out = []
    add = out.append
    nodes = ", ".join(f"{n['id']} ({n['ip']})" for n in meta["nodes"])

    add("# Informe experimental — ComplexNet API (Fase 3)\n")
    add("Este informe se genera automáticamente con `experiments/report.py` a partir de los "
        "resultados de `experiments/run_experiments.py`. Los datos crudos (CSV) están en "
        f"`experiments/results/{os.path.basename(run)}/`.\n")
    add("## 1. Entorno\n")
    add(table(["Dato", "Valor"], [
        ["Fecha", meta["date"]],
        ["Entorno", meta["environment"]],
        ["Nodos", nodes],
        ["Equipo que ejecutó los experimentos", f"{meta['host']} ({meta['platform']})"],
        ["CPU / RAM de ese equipo", f"{meta['cpu_count']} hilos / {meta['ram_gb']} GB"],
        ["Python", meta["python"]],
        ["Estrategia por defecto", meta["strategy_default"]],
        ["Tamaño de tarea (puntos Monte Carlo)", f"{int(meta['task_points']):,}"],
        ["Modo", "rápido (reducido)" if meta["quick"] else "completo"],
    ]))
    add("")
    add("**Metodología.** Cada nodo es un proceso independiente que se comunica por UDP/JSON. "
        "Las cargas de trabajo son tareas CPU-bound de Monte Carlo (estimación de π) que se "
        "reparten con el planificador distribuido. Cada medición se repite varias veces y se "
        "reporta la media y la desviación estándar. Las fallas se inyectan con el endpoint "
        "`/admin/fail` del nodo víctima, que deja de enviar y recibir mensajes durante unos segundos "
        "(equivale a una caída o desconexión de la red).\n")

    # ---- 2. Latencia ----------------------------------------------------
    latency = read(run, "latency.csv")
    if latency:
        add("## 2. Latencia de comunicación\n")
        add(table(["Nodo", "Ping medio (ms)", "Ping mín (ms)", "Ping máx (ms)",
                   "Tarea mínima p50 (ms)", "Tarea mínima p95 (ms)"],
                  [[r["node"], r["ping_mean_ms"], r["ping_min_ms"], r["ping_max_ms"],
                    r["task_rtt_p50_ms"], r["task_rtt_p95_ms"]] for r in latency]))
        add("")
        add("*Ping* es el RTT de los mensajes `PING/PONG` que cada nodo mide a sus vecinos. "
            "*Tarea mínima* es el tiempo completo de una tarea `echo` (asignación, envío, "
            "ejecución y respuesta).\n")
        fig, ax = plt.subplots(figsize=(6, 3.2))
        x = range(len(latency))
        ax.bar([i - 0.2 for i in x], [num(r["ping_mean_ms"], 0) for r in latency], 0.4,
               label="Ping medio", color=COLORS[0])
        ax.bar([i + 0.2 for i in x], [num(r["task_rtt_p50_ms"], 0) for r in latency], 0.4,
               label="Tarea mínima (p50)", color=COLORS[1])
        ax.set_xticks(list(x), [r["node"] for r in latency])
        ax.set_ylabel("ms")
        ax.set_title("Latencia hacia cada nodo")
        ax.legend()
        add(f"![Latencia]({save(fig, 'latencia.png')})\n")

    # ---- 3. Descubrimiento -----------------------------------------------
    discovery = read(run, "discovery.csv")
    if discovery:
        times = [num(r["seconds"]) for r in discovery]
        complete = sum(int(r["complete"]) for r in discovery)
        add("## 3. Tiempo de descubrimiento\n")
        add("Se arranca un nodo nuevo (sin conocer a nadie) y se mide el tiempo hasta que "
            "descubre a todos los demás nodos.\n")
        add(table(["Intento", "Segundos", "Vecinos encontrados", "Completo"],
                  [[r["trial"], r["seconds"], r["peers_found"], "sí" if r["complete"] == "1" else "no"]
                   for r in discovery]))
        add("")
        add(f"Media: **{sum(times) / len(times):.2f} s** (mín {min(times):.2f} s, máx {max(times):.2f} s); "
            f"descubrimiento completo en {complete}/{len(discovery)} intentos. El intervalo de "
            "los beacons es de 2 s, que acota el peor caso.\n")

    # ---- 4. Escalabilidad ------------------------------------------------
    scal = read(run, "scalability_nodes.csv")
    load = read(run, "scalability_load.csv")
    if scal:
        add("## 4. Escalabilidad\n")
        add("### 4.1 Más nodos, misma carga\n")
        add(f"Se ejecuta el mismo lote de {scal[0]['tasks']} tareas restringiendo el número de nodos "
            "disponibles.\n")
        add(table(["Nodos", "Tiempo total (s)", "± σ", "Tareas/s", "Aceleración"],
                  [[r["nodes"], r["makespan_sec"], r["makespan_std"], r["throughput_tps"], f"{r['speedup']}×"]
                   for r in scal]))
        add("")
        fig, ax = plt.subplots(1, 2, figsize=(8, 3.2))
        ks = [int(r["nodes"]) for r in scal]
        ax[0].plot(ks, [num(r["makespan_sec"]) for r in scal], "o-", color=COLORS[0])
        ax[0].set_xlabel("nodos")
        ax[0].set_ylabel("tiempo total (s)")
        ax[0].set_title("Tiempo total")
        ax[0].set_xticks(ks)
        ax[1].plot(ks, [num(r["speedup"]) for r in scal], "o-", color=COLORS[1], label="medida")
        ax[1].plot(ks, ks, "--", color="gray", label="ideal")
        ax[1].set_xlabel("nodos")
        ax[1].set_ylabel("aceleración")
        ax[1].set_title("Aceleración")
        ax[1].set_xticks(ks)
        ax[1].legend()
        add(f"![Escalabilidad]({save(fig, 'escalabilidad_nodos.png')})\n")
        best = scal[-1]
        add(f"Con {best['nodes']} nodos la aceleración fue **{best['speedup']}×** "
            f"(ideal: {best['nodes']}×). La diferencia con el ideal se debe a la sobrecarga de "
            "coordinación (mensajes, ACK), a que las tareas se reparten en bloques discretos y a "
            "las diferencias de capacidad entre equipos.\n")
    if load:
        add("### 4.2 Incremento progresivo de la carga\n")
        add(table(["Tareas", "Tiempo total (s)", "Tareas/s", "Latencia media (s)", "p95 (s)",
                   "Tráfico enviado (KB/s)", "CPU usada media (%)"],
                  [[r["tasks"], r["makespan_sec"], r["throughput_tps"], r["latency_mean_sec"],
                    r["latency_p95_sec"], r["kb_sent_per_sec"],
                    ", ".join(f"{k}: {v}" for k, v in json.loads(r["cpu_used_mean_pct"]).items())]
                   for r in load]))
        add("")
        fig, ax = plt.subplots(1, 2, figsize=(8, 3.2))
        xs = [int(r["tasks"]) for r in load]
        ax[0].plot(xs, [num(r["makespan_sec"]) for r in load], "o-", color=COLORS[0])
        ax[0].set_xlabel("tareas")
        ax[0].set_ylabel("tiempo total (s)")
        ax[0].set_title("Tiempo total vs. carga")
        ax[1].plot(xs, [num(r["latency_mean_sec"]) for r in load], "o-", color=COLORS[2], label="media")
        ax[1].plot(xs, [num(r["latency_p95_sec"]) for r in load], "s--", color=COLORS[3], label="p95")
        ax[1].set_xlabel("tareas")
        ax[1].set_ylabel("latencia de tarea (s)")
        ax[1].set_title("Tiempo de respuesta")
        ax[1].legend()
        add(f"![Carga]({save(fig, 'carga_progresiva.png')})\n")
        first, last = load[0], load[-1]
        load_ratio = int(last["tasks"]) / int(first["tasks"])
        time_ratio = num(last["makespan_sec"]) / num(first["makespan_sec"])
        add(f"Al multiplicar la carga por {load_ratio:.0f} (de {first['tasks']} a {last['tasks']} tareas) el "
            f"tiempo total se multiplicó por {time_ratio:.1f} y el rendimiento pasó de "
            f"{first['throughput_tps']} a {last['throughput_tps']} tareas/s. "
            f"El tráfico de control fue de {last['kb_sent_per_sec']} KB/s con la mayor carga.\n")

    # ---- 5. Estrategias --------------------------------------------------
    strat = read(run, "strategies.csv")
    if strat:
        add("## 5. Comparación de estrategias de asignación\n")
        add(f"Mismo lote de {strat[0]['tasks']} tareas de tamaño heterogéneo (½×, 1× y 2×) con cada "
            "estrategia. *Desbalance* es el coeficiente de variación del número de tareas por nodo "
            "(0 = reparto perfecto).\n")
        add(table(["Estrategia", "Tiempo total (s)", "± σ", "Latencia media (s)", "p95 (s)",
                   "Desbalance", "Tareas por nodo"],
                  [[STRATEGY_NAMES.get(r["strategy"], r["strategy"]), r["makespan_sec"], r["makespan_std"],
                    r["latency_mean_sec"], r["latency_p95_sec"], r["imbalance_cv"],
                    ", ".join(f"{k}: {v}" for k, v in json.loads(r["tasks_per_node"]).items())]
                   for r in strat]))
        add("")
        fig, ax = plt.subplots(1, 2, figsize=(9, 3.4))
        names = [STRATEGY_NAMES.get(r["strategy"], r["strategy"]) for r in strat]
        ax[0].barh(names, [num(r["makespan_sec"]) for r in strat], color=COLORS[:len(strat)])
        ax[0].set_xlabel("tiempo total (s)")
        ax[0].set_title("Tiempo total (menor es mejor)")
        ax[0].invert_yaxis()
        ax[1].barh(names, [num(r["imbalance_cv"]) for r in strat], color=COLORS[:len(strat)])
        ax[1].set_xlabel("desbalance (CV)")
        ax[1].set_title("Equidad del reparto")
        ax[1].invert_yaxis()
        add(f"![Estrategias]({save(fig, 'estrategias.png')})\n")
        best = min(strat, key=lambda r: num(r["makespan_sec"]))
        worst = max(strat, key=lambda r: num(r["makespan_sec"]))
        design = next((r for r in strat if r["strategy"] == "weighted"), None)
        add(f"La estrategia con menor tiempo total fue **{STRATEGY_NAMES.get(best['strategy'], best['strategy'])}** "
            f"({best['makespan_sec']} s) y la de mayor tiempo **{STRATEGY_NAMES.get(worst['strategy'], worst['strategy'])}** "
            f"({worst['makespan_sec']} s).")
        improved = next((r for r in strat if r["strategy"] == "weighted_load"), None)
        if design:
            add(f"La función F(i,j) del diseño original tardó {design['makespan_sec']} s con un desbalance de "
                f"{design['imbalance_cv']}. Esa función no considera la carga actual, y la normalización min-max "
                "convierte diferencias mínimas de CPU y memoria entre nodos desocupados en diferencias de 0 a 1, "
                "por lo que puede concentrar tareas en pocos nodos.")
        if design and improved:
            better = (num(improved["makespan_sec"]) < num(design["makespan_sec"])
                      and num(improved["imbalance_cv"]) <= num(design["imbalance_cv"]))
            if better:
                gain = (1 - num(improved["makespan_sec"]) / num(design["makespan_sec"])) * 100
                add(f"La variante `weighted_load` (término de carga y normalización robusta) redujo el tiempo "
                    f"total en {gain:.0f} % y el desbalance de {design['imbalance_cv']} a "
                    f"{improved['imbalance_cv']}, conservando el criterio multicriterio.")
            else:
                add("En esta corrida la variante `weighted_load` no mejoró a la función del diseño; ver las "
                    "tablas para el detalle.")
        if num(strat[0]["makespan_std"]) == 0:
            add("\n*Nota: σ = 0 porque en el modo rápido cada medición se hizo una sola vez.*")
        add("")

    # ---- 6. Tolerancia a fallos ------------------------------------------
    fault = read(run, "fault_tolerance.csv")
    if fault:
        add("## 6. Tolerancia a fallos\n")
        add("Un nodo cae 2 s después de empezar un lote de tareas (deja de enviar y recibir durante 25 s).\n")
        add(table(["Intento", "Nodo caído", "Tareas", "Completadas", "% completado", "Reasignadas",
                   "Detección (s)", "Recuperación (s)", "Tiempo total (s)"],
                  [[r["trial"], r["victim"], r["tasks"], r["completed"], r["completion_pct"], r["reassigned"],
                    r["detection_sec"], r["recovery_sec"], r["makespan_sec"]] for r in fault]))
        add("")
        detections = [num(r["detection_sec"]) for r in fault if num(r["detection_sec"]) is not None]
        pcts = [num(r["completion_pct"]) for r in fault]
        if detections:
            add(f"- Detección de la caída: media **{sum(detections) / len(detections):.2f} s** "
                f"(requisito: ≤ 5 s de silencio; la detección corre cada 0.5 s).")
        add(f"- Tareas completadas pese a la caída: **{sum(pcts) / len(pcts):.0f} %** (sin intervención manual).")
        add("- La *recuperación* es el tiempo desde la primera reasignación hasta que la tarea reasignada "
            "termina (incluye volver a ejecutarla).\n")
        fig, ax = plt.subplots(figsize=(6, 3.2))
        ax.bar([r["trial"] for r in fault], [num(r["detection_sec"], 0) for r in fault],
               color=COLORS[3], label="detección")
        ax.axhline(5, ls="--", color="gray", label="límite 5 s")
        ax.set_xlabel("intento")
        ax.set_ylabel("segundos")
        ax.set_title("Tiempo de detección de la caída")
        ax.legend()
        add(f"![Fallos]({save(fig, 'tolerancia_fallos.png')})\n")

    # ---- 7. Disponibilidad -----------------------------------------------
    availability = read(run, "availability.csv")
    summary_path = os.path.join(run, "availability_summary.json")
    if availability and os.path.exists(summary_path):
        summary = json.load(open(summary_path, encoding="utf-8"))
        add("## 7. Disponibilidad del servicio\n")
        add(f"Cada 0.5 s se envía una tarea de sondeo mientras {summary['victim']} falla entre "
            f"t = {summary['fail_at_sec']} s y t = {summary['fail_at_sec'] + summary['fail_seconds']} s.\n")
        add(table(["Métrica", "Valor"], [
            ["Sondas enviadas", summary["probes"]],
            ["Completadas", f"{summary['completed_pct']} %"],
            [f"Completadas en ≤ {summary['sla_sec']:g} s", f"{summary['within_sla_pct']} %"],
        ]))
        add("")
        fig, ax = plt.subplots(figsize=(8, 3.2))
        sent = [num(r["sent_at_sec"]) for r in availability]
        lat = [num(r["latency_sec"], 0) for r in availability]
        ax.scatter(sent, lat, s=10, color=COLORS[0])
        ax.axvspan(summary["fail_at_sec"], summary["fail_at_sec"] + summary["fail_seconds"],
                   color="#feb2b2", alpha=0.4, label="nodo caído")
        ax.axhline(summary["sla_sec"], ls="--", color="gray", label=f"{summary['sla_sec']:g} s")
        ax.set_xlabel("instante de envío (s)")
        ax.set_ylabel("tiempo de respuesta (s)")
        ax.set_title("Tiempo de respuesta de las sondas durante la falla")
        ax.legend()
        add(f"![Disponibilidad]({save(fig, 'disponibilidad.png')})\n")
        add("Las sondas enviadas al nodo caído no reciben `TASK_ACK`; tras el timeout se reasignan a otro "
            "nodo y se completan, por eso la disponibilidad es alta pero algunas respuestas tardan "
            "alrededor del timeout de 5 s.\n")

    # ---- 8. Recursos -----------------------------------------------------
    metrics_path = os.path.join(run, "node_metrics.json")
    if os.path.exists(metrics_path):
        m = json.load(open(metrics_path, encoding="utf-8"))
        add("## 8. Consumo de recursos del nodo coordinador\n")
        add(table(["Métrica", "Valor"], [
            ["Mensajes enviados / recibidos", f"{m['messages_sent']} / {m['messages_received']}"],
            ["Tráfico enviado / recibido", f"{m['bytes_sent'] / 1024:.0f} KB / {m['bytes_received'] / 1024:.0f} KB"],
            ["Duración", f"{m['uptime_sec']:.0f} s"],
            ["Tráfico medio enviado", f"{m['bytes_sent'] / 1024 / max(m['uptime_sec'], 1):.2f} KB/s"],
            ["Tareas enviadas / completadas / reasignadas / fallidas",
             f"{m['tasks_submitted']} / {m['tasks_completed']} / {m['tasks_reassigned']} / {m['tasks_failed']}"],
        ]))
        add("")
        add("El uso de CPU por nodo durante cada carga se reporta en las secciones 4.2 y 5.\n")

    # ---- 9. Conclusiones -------------------------------------------------
    add("## 9. Conclusiones y limitaciones\n")
    add("- El sistema se **autoorganiza**: los nodos se descubren solos, reparten el trabajo con reglas locales "
        "y se recuperan de caídas sin coordinador central.")
    add("- La **escalabilidad** depende de que las tareas sean lo bastante grandes como para amortizar la "
        "comunicación; con tareas muy pequeñas la coordinación domina.")
    if strat:
        best_s = min(strat, key=lambda r: num(r["makespan_sec"]))
        add(f"- **Estrategias:** en esta corrida la de menor tiempo total fue "
            f"{STRATEGY_NAMES.get(best_s['strategy'], best_s['strategy'])} ({best_s['makespan_sec']} s); "
            "el reparto equitativo importa porque cada nodo ejecuta pocas tareas a la vez y el resto espera en cola.")
    add("- La **tolerancia a fallos** se apoya en detección por silencio (≤ 5 s) y reasignación; una tarea no se "
        "pierde mientras exista al menos un nodo activo.")
    add("- **Limitaciones:** el ancho de banda de cada nodo es un valor declarado, no medido; UDP no garantiza entrega "
        "(se compensa con ACK, timeout y reasignación); el coordinador (nodo que envía la tarea) es un punto único "
        "para *sus* tareas: si cae, pierde su estado; no hay persistencia.")
    if meta.get("environment", "").lower().startswith("1 pc"):
        add("- **Importante:** estos resultados se obtuvieron en un solo computador (procesos independientes), "
            "por lo que los nodos compiten por la misma CPU y la latencia de red es de *loopback*. Deben "
            "repetirse en los 3 computadores para el informe final.")
    return "\n".join(out) + "\n"


def main():
    run = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else latest_run()
    os.makedirs(DOCS, exist_ok=True)
    text = build(run)
    target = os.path.join(DOCS, "INFORME_EXPERIMENTAL.md")
    with open(target, "w", encoding="utf-8") as handle:
        handle.write(text)
    print(f"Informe generado: {target}\nCorrida: {run}")


if __name__ == "__main__":
    main()
