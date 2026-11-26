"""Genera el informe experimental (Markdown + gráficas) a partir de los resultados.

    python experiments/report.py                       # usa la corrida más reciente
    python experiments/report.py experiments/results/20261125-153000
"""

import csv
import json
import os
import shutil
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RESULTS = os.path.join(ROOT, "experiments", "results")
DOCS = os.path.join(ROOT, "docs", "pruebas")
FIGS = os.path.join(DOCS, "figuras")
INFORME = os.path.join(ROOT, "docs", "informe")          # sección LaTeX del informe
INFORME_FIGS = os.path.join(INFORME, "figuras")

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
    os.makedirs(INFORME_FIGS, exist_ok=True)       # copia para el documento LaTeX
    shutil.copyfile(os.path.join(FIGS, name), os.path.join(INFORME_FIGS, name))
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
        ok_times = [num(r["seconds"]) for r in discovery if r["complete"] == "1"]
        if ok_times and complete < len(discovery):
            add(f"Descubrimiento completo en {complete}/{len(discovery)} intentos. En los {len(ok_times)} intentos "
                f"completos tardó **{sum(ok_times) / len(ok_times):.2f} s** de media (mín {min(ok_times):.2f} s, "
                f"máx {max(ok_times):.2f} s). En los {len(discovery) - complete} restantes se agotó el límite de "
                f"{max(times):.0f} s sin encontrar a todos los vecinos: el *broadcast* UDP no tiene garantía de "
                "entrega y en una red Wi-Fi puede perderse; por eso el sistema también admite vecinos semilla "
                "por IP (`--peers`).\n")
        else:
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


# ---------------------------------------------------------------------------
# Salida LaTeX (docs/informe/fase3_resultados.tex). Solo usa LaTeX estándar y graphicx.
# ---------------------------------------------------------------------------

class Raw(str):
    """Texto que ya es LaTeX y no debe escaparse."""


TEX_MAP = {
    "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_",
    "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
    "×": r"$\times$", "σ": r"$\sigma$", "±": r"$\pm$", "≤": r"$\leq$", "π": r"$\pi$",
    "½": "1/2", "−": "-", "—": "---", "–": "--",
}

STRATEGY_TEX = {
    "weighted": Raw("$F(i,j)$ del diseño"),
    "weighted_load": Raw("$F(i,j)$ + carga"),
    "least_loaded": "Menos cargado",
    "lowest_latency": "Menor latencia",
    "round_robin": "Round-robin",
    "random": "Aleatoria",
}


def tex(value):
    if isinstance(value, Raw):
        return str(value)
    return "".join(TEX_MAP.get(ch, ch) for ch in str(value))


def strategy_tex(key):
    return STRATEGY_TEX.get(key, key)


def ltable(header, rows, caption, label):
    cols = "|" + "c|" * len(header)
    head = " & ".join(f"\\textbf{{{tex(h)}}}" for h in header) + " \\\\ \\hline"
    body = "\n".join(" & ".join(tex(c) for c in row) + " \\\\ \\hline" for row in rows)
    return (
        "\\begin{table}[htbp]\n\\centering\n\\small\n"
        "\\resizebox{\\ifdim\\width>\\linewidth\\linewidth\\else\\width\\fi}{!}{%\n"
        f"\\begin{{tabular}}{{{cols}}}\n\\hline\n{head}\n{body}\n\\end{{tabular}}}}\n"
        f"\\caption{{{tex(caption)}}}\n\\label{{tab:{label}}}\n\\end{{table}}\n"
    )


def lfig(name, caption, label, width="0.9"):
    return (
        "\\begin{figure}[htbp]\n\\centering\n"
        f"\\includegraphics[width={width}\\textwidth]{{figuras/{name}}}\n"
        f"\\caption{{{tex(caption)}}}\n\\label{{fig:{label}}}\n\\end{{figure}}\n"
    )


def build_tex(run):
    meta = json.load(open(os.path.join(run, "meta.json"), encoding="utf-8"))
    out = []
    add = out.append
    nodes = ", ".join(f"{n['id']} ({n['ip']})" for n in meta["nodes"])
    one_pc = meta.get("environment", "").lower().startswith("1 pc")

    add("% ARCHIVO GENERADO por experiments/report.py -- no editar a mano.")
    add(f"% Corrida: {os.path.basename(run)}\n")
    add("\\subsubsection{Entorno}\n")
    add(ltable(["Dato", "Valor"], [
        ["Fecha", meta["date"]],
        ["Entorno", meta["environment"]],
        ["Nodos", nodes],
        ["Equipo que ejecutó los experimentos", f"{meta['host']} ({meta['platform']})"],
        ["CPU / RAM de ese equipo", f"{meta['cpu_count']} hilos / {meta['ram_gb']} GB"],
        ["Python", meta["python"]],
        ["Estrategia por defecto", meta["strategy_default"]],
        ["Tamaño de tarea (puntos Monte Carlo)", f"{int(meta['task_points']):,}"],
        ["Modo", "rápido (reducido)" if meta["quick"] else "completo"],
    ], "Entorno de la corrida experimental.", "entorno"))
    if one_pc:
        add("\\textbf{Nota:} esta corrida se hizo en un solo computador (tres procesos independientes "
            "en \\texttt{localhost}): los nodos compiten por la misma CPU y la latencia es la de "
            "\\emph{loopback}. Los experimentos se repiten en los tres computadores físicos para "
            "obtener los valores definitivos.\n")
    else:
        add("Los experimentos se ejecutaron en \\textbf{tres computadores físicos} conectados a la misma "
            "red local, un nodo por computador.\n")

    latency = read(run, "latency.csv")
    if latency:
        add("\\subsubsection{Latencia de comunicación}\n")
        add(ltable(["Nodo", "Ping medio (ms)", "Ping mín (ms)", "Ping máx (ms)",
                    "Tarea mínima p50 (ms)", "Tarea mínima p95 (ms)"],
                   [[r["node"], r["ping_mean_ms"], r["ping_min_ms"], r["ping_max_ms"],
                     r["task_rtt_p50_ms"], r["task_rtt_p95_ms"]] for r in latency],
                   "Latencia hacia cada nodo.", "latencia"))
        add("\\emph{Ping} es el RTT de los mensajes \\texttt{PING}/\\texttt{PONG} que cada nodo mide a "
            "sus vecinos. \\emph{Tarea mínima} es el tiempo completo de una tarea \\texttt{echo} "
            "(asignación, envío, ejecución y respuesta).\n")
        add(lfig("latencia.png", "Latencia hacia cada nodo.", "latencia", "0.7"))

    discovery = read(run, "discovery.csv")
    if discovery:
        times = [num(r["seconds"]) for r in discovery]
        complete = sum(int(r["complete"]) for r in discovery)
        add("\\subsubsection{Tiempo de descubrimiento}\n")
        add("Se arranca un nodo nuevo, sin conocer a nadie, y se mide el tiempo hasta que descubre a "
            "todos los demás.\n")
        add(ltable(["Intento", "Segundos", "Vecinos encontrados", "Completo"],
                   [[r["trial"], r["seconds"], r["peers_found"], "sí" if r["complete"] == "1" else "no"]
                    for r in discovery], "Tiempo de descubrimiento de un nodo nuevo.", "descubrimiento"))
        ok_times = [num(r["seconds"]) for r in discovery if r["complete"] == "1"]
        if ok_times and complete < len(discovery):
            add(f"Descubrimiento completo en {complete}/{len(discovery)} intentos. En los {len(ok_times)} intentos "
                f"completos tardó \\textbf{{{sum(ok_times) / len(ok_times):.2f} s}} de media (mín "
                f"{min(ok_times):.2f} s, máx {max(ok_times):.2f} s). En los {len(discovery) - complete} restantes "
                f"se agotó el límite de {max(times):.0f} s sin encontrar a todos los vecinos: el "
                "\\emph{broadcast} UDP no tiene garantía de entrega y en una red Wi-Fi puede perderse; por eso el "
                "sistema también admite vecinos semilla por IP (\\texttt{--peers}).\n")
        else:
            add(f"Media: \\textbf{{{sum(times) / len(times):.2f} s}} (mín {min(times):.2f} s, máx "
                f"{max(times):.2f} s); descubrimiento completo en {complete}/{len(discovery)} intentos. "
                "El intervalo de los \\emph{beacons} es de 2 s, que acota el peor caso.\n")

    scal = read(run, "scalability_nodes.csv")
    load = read(run, "scalability_load.csv")
    if scal:
        add("\\subsubsection{Escalabilidad}\n")
        add(f"\\paragraph{{Más nodos, misma carga.}} Se ejecuta el mismo lote de {scal[0]['tasks']} "
            "tareas restringiendo el número de nodos disponibles.\n")
        add(ltable(["Nodos", "Tiempo total (s)", "± σ", "Tareas/s", "Aceleración"],
                   [[r["nodes"], r["makespan_sec"], r["makespan_std"], r["throughput_tps"],
                     f"{r['speedup']}×"] for r in scal],
                   "Escalabilidad al aumentar el número de nodos.", "escal-nodos"))
        add(lfig("escalabilidad_nodos.png", "Tiempo total y aceleración según el número de nodos.",
                 "escal-nodos"))
        best = scal[-1]
        add(f"Con {tex(best['nodes'])} nodos la aceleración fue \\textbf{{{tex(best['speedup'])}$\\times$}} "
            f"(ideal: {tex(best['nodes'])}$\\times$). La diferencia con el ideal se debe a la sobrecarga de "
            "coordinación (mensajes, ACK), a que las tareas se reparten en bloques discretos y a las "
            "diferencias de capacidad entre equipos.\n")
    if load:
        add("\\paragraph{Incremento progresivo de la carga.}\n")
        add(ltable(["Tareas", "Tiempo total (s)", "Tareas/s", "Latencia media (s)", "p95 (s)",
                    "Tráfico enviado (KB/s)", "CPU usada media (%)"],
                   [[r["tasks"], r["makespan_sec"], r["throughput_tps"], r["latency_mean_sec"],
                     r["latency_p95_sec"], r["kb_sent_per_sec"],
                     ", ".join(f"{k}: {v}" for k, v in json.loads(r["cpu_used_mean_pct"]).items())]
                    for r in load], "Respuesta del sistema al aumentar la carga.", "escal-carga"))
        add(lfig("carga_progresiva.png", "Tiempo total y tiempo de respuesta según la carga.",
                 "escal-carga"))
        first, last = load[0], load[-1]
        load_ratio = int(last["tasks"]) / int(first["tasks"])
        time_ratio = num(last["makespan_sec"]) / num(first["makespan_sec"])
        add(f"Al multiplicar la carga por {load_ratio:.0f} (de {tex(first['tasks'])} a {tex(last['tasks'])} "
            f"tareas) el tiempo total se multiplicó por {time_ratio:.1f} y el rendimiento pasó de "
            f"{tex(first['throughput_tps'])} a {tex(last['throughput_tps'])} tareas/s. El tráfico de "
            f"control fue de {tex(last['kb_sent_per_sec'])} KB/s con la mayor carga.\n")

    strat = read(run, "strategies.csv")
    if strat:
        add("\\subsubsection{Comparación de estrategias de asignación}\n")
        add(f"Mismo lote de {strat[0]['tasks']} tareas de tamaño heterogéneo (0.5$\\times$, 1$\\times$ y "
            "2$\\times$) con cada estrategia. \\emph{Desbalance} es el coeficiente de variación del número "
            "de tareas por nodo (0 = reparto perfecto).\n")
        add(ltable(["Estrategia", "Tiempo total (s)", "± σ", "Latencia media (s)", "p95 (s)",
                    "Desbalance", "Tareas por nodo"],
                   [[strategy_tex(r["strategy"]), r["makespan_sec"], r["makespan_std"],
                     r["latency_mean_sec"], r["latency_p95_sec"], r["imbalance_cv"],
                     ", ".join(f"{k}: {v}" for k, v in json.loads(r["tasks_per_node"]).items())]
                    for r in strat], "Comparación de las seis estrategias de asignación.", "estrategias"))
        add(lfig("estrategias.png", "Tiempo total y equidad del reparto por estrategia.", "estrategias"))
        best = min(strat, key=lambda r: num(r["makespan_sec"]))
        worst = max(strat, key=lambda r: num(r["makespan_sec"]))
        design = next((r for r in strat if r["strategy"] == "weighted"), None)
        improved = next((r for r in strat if r["strategy"] == "weighted_load"), None)
        text = (f"La estrategia con menor tiempo total fue \\textbf{{{tex(strategy_tex(best['strategy']))}}} "
                f"({tex(best['makespan_sec'])} s) y la de mayor tiempo \\textbf{{"
                f"{tex(strategy_tex(worst['strategy']))}}} ({tex(worst['makespan_sec'])} s). ")
        if design:
            text += (f"La función $F(i,j)$ del diseño original tardó {tex(design['makespan_sec'])} s con un "
                     f"desbalance de {tex(design['imbalance_cv'])}. Esa función no considera la carga actual y "
                     "la normalización min-max convierte diferencias mínimas de CPU y memoria entre nodos "
                     "desocupados en diferencias de 0 a 1, por lo que puede concentrar tareas en pocos nodos. ")
        if design and improved:
            if (num(improved["makespan_sec"]) < num(design["makespan_sec"])
                    and num(improved["imbalance_cv"]) <= num(design["imbalance_cv"])):
                gain = (1 - num(improved["makespan_sec"]) / num(design["makespan_sec"])) * 100
                text += (f"La variante \\texttt{{weighted\\_load}} (término de carga y normalización robusta) "
                         f"redujo el tiempo total en {gain:.0f}\\,\\% y el desbalance de "
                         f"{tex(design['imbalance_cv'])} a {tex(improved['imbalance_cv'])}, conservando el "
                         "criterio multicriterio.")
            else:
                text += ("En esta corrida la variante \\texttt{weighted\\_load} no mejoró a la función del "
                         "diseño; ver la tabla para el detalle.")
        add(text + "\n")
        if num(strat[0]["makespan_std"]) == 0:
            add("\\emph{Nota: $\\sigma = 0$ porque en el modo rápido cada medición se hizo una sola vez.}\n")

    fault = read(run, "fault_tolerance.csv")
    if fault:
        add("\\subsubsection{Tolerancia a fallos}\n")
        add("Un nodo cae 2 s después de empezar un lote de tareas (deja de enviar y recibir durante 25 s).\n")
        add(ltable(["Intento", "Nodo caído", "Tareas", "Completadas", "% completado", "Reasignadas",
                    "Detección (s)", "Recuperación (s)", "Tiempo total (s)"],
                   [[r["trial"], r["victim"], r["tasks"], r["completed"], r["completion_pct"],
                     r["reassigned"], r["detection_sec"], r["recovery_sec"], r["makespan_sec"]]
                    for r in fault], "Caída de un nodo durante la ejecución de un lote.", "fallos"))
        detections = [num(r["detection_sec"]) for r in fault if num(r["detection_sec"]) is not None]
        pcts = [num(r["completion_pct"]) for r in fault]
        add("\\begin{itemize}")
        if detections:
            add(f"\\item Detección de la caída: media \\textbf{{{sum(detections) / len(detections):.2f} s}} "
                "(requisito: $\\leq$ 5 s de silencio; la detección corre cada 0.5 s).")
        add(f"\\item Tareas completadas pese a la caída: \\textbf{{{sum(pcts) / len(pcts):.0f}\\,\\%}} "
            "(sin intervención manual).")
        add("\\item La \\emph{recuperación} es el tiempo desde la primera reasignación hasta que la tarea "
            "reasignada termina (incluye volver a ejecutarla).")
        add("\\end{itemize}\n")
        add(lfig("tolerancia_fallos.png", "Tiempo de detección de la caída en cada intento.", "fallos", "0.7"))

    availability = read(run, "availability.csv")
    summary_path = os.path.join(run, "availability_summary.json")
    if availability and os.path.exists(summary_path):
        summary = json.load(open(summary_path, encoding="utf-8"))
        add("\\subsubsection{Disponibilidad del servicio}\n")
        add(f"Cada 0.5 s se envía una tarea de sondeo mientras {tex(summary['victim'])} falla entre "
            f"$t = {summary['fail_at_sec']}$ s y $t = {summary['fail_at_sec'] + summary['fail_seconds']}$ s.\n")
        add(ltable(["Métrica", "Valor"], [
            ["Sondas enviadas", summary["probes"]],
            ["Completadas", f"{summary['completed_pct']} %"],
            [f"Completadas en ≤ {summary['sla_sec']:g} s", f"{summary['within_sla_pct']} %"],
        ], "Disponibilidad del servicio durante la falla de un nodo.", "disponibilidad"))
        add(lfig("disponibilidad.png", "Tiempo de respuesta de las sondas durante la falla.",
                 "disponibilidad"))
        add("Las sondas enviadas al nodo caído no reciben \\texttt{TASK\\_ACK}; tras el \\emph{timeout} "
            "se reasignan a otro nodo y se completan, por eso la disponibilidad es alta pero algunas "
            "respuestas tardan alrededor del \\emph{timeout} de 5 s.\n")

    metrics_path = os.path.join(run, "node_metrics.json")
    if os.path.exists(metrics_path):
        m = json.load(open(metrics_path, encoding="utf-8"))
        add("\\subsubsection{Consumo de recursos del nodo coordinador}\n")
        add(ltable(["Métrica", "Valor"], [
            ["Mensajes enviados / recibidos", f"{m['messages_sent']} / {m['messages_received']}"],
            ["Tráfico enviado / recibido", f"{m['bytes_sent'] / 1024:.0f} KB / {m['bytes_received'] / 1024:.0f} KB"],
            ["Duración", f"{m['uptime_sec']:.0f} s"],
            ["Tráfico medio enviado", f"{m['bytes_sent'] / 1024 / max(m['uptime_sec'], 1):.2f} KB/s"],
            ["Tareas enviadas / completadas / reasignadas / fallidas",
             f"{m['tasks_submitted']} / {m['tasks_completed']} / {m['tasks_reassigned']} / {m['tasks_failed']}"],
        ], "Consumo del nodo que coordinó los experimentos.", "recursos"))

    add("\\subsubsection{Síntesis de los resultados}\n")
    add("\\begin{itemize}")
    if discovery:
        good = [t for t, r in zip(times, discovery) if r["complete"] == "1"] or times
        add(f"\\item \\textbf{{Descubrimiento:}} los nodos se encuentran solos en {sum(good) / len(good):.2f} s "
            f"de media en {complete}/{len(discovery)} intentos, sin configuración manual.")
    if scal:
        add(f"\\item \\textbf{{Escalabilidad:}} con {tex(scal[-1]['nodes'])} nodos la aceleración fue "
            f"{tex(scal[-1]['speedup'])}$\\times$ respecto a un solo nodo.")
    if strat:
        add(f"\\item \\textbf{{Estrategias:}} la de menor tiempo total fue "
            f"{tex(strategy_tex(min(strat, key=lambda r: num(r['makespan_sec']))['strategy']))}.")
    if fault and detections:
        add(f"\\item \\textbf{{Fallos:}} la caída se detectó en {sum(detections) / len(detections):.2f} s de "
            f"media y se completó el {sum(pcts) / len(pcts):.0f}\\,\\% de las tareas.")
    if availability and os.path.exists(summary_path):
        add(f"\\item \\textbf{{Disponibilidad:}} se completó el {tex(summary['completed_pct'])}\\,\\% de las "
            "sondas durante la falla de un nodo.")
    add("\\end{itemize}")
    return "\n".join(out) + "\n"


def to_html(markdown_text):
    """Convierte el informe (Markdown simple) en una página HTML autocontenida (imágenes incrustadas)."""
    import base64
    import html as htmllib
    import re

    def inline(text):
        text = htmllib.escape(text, quote=False)
        text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
        text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
        text = re.sub(r"\*([^*]+)\*", r"<i>\1</i>", text)
        return text

    def image(match):
        alt, path = match.group(1), match.group(2)
        full = os.path.join(DOCS, path)
        if not os.path.exists(full):
            return ""
        data = base64.b64encode(open(full, "rb").read()).decode("ascii")
        return f'<figure><img alt="{htmllib.escape(alt)}" src="data:image/png;base64,{data}"></figure>'

    out, lines, i = [], markdown_text.split("\n"), 0
    in_list = False
    while i < len(lines):
        line = lines[i].rstrip()
        if in_list and not line.startswith("- "):
            out.append("</ul>")
            in_list = False
        if not line:
            i += 1
            continue
        m = re.match(r"!\[([^\]]*)\]\(([^)]+)\)$", line)
        if m:
            out.append(image(m))
        elif line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            head, body = rows[0], rows[2:]
            out.append("<div class='tw'><table><thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in head)
                       + "</tr></thead><tbody>"
                       + "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in body)
                       + "</tbody></table></div>")
            continue
        elif line.startswith("# "):
            out.append(f"<h1>{inline(line[2:])}</h1>")
        elif line.startswith("## "):
            out.append(f"<h2>{inline(line[3:])}</h2>")
        elif line.startswith("### "):
            out.append(f"<h3>{inline(line[4:])}</h3>")
        elif line.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(line[2:])}</li>")
        else:
            out.append(f"<p>{inline(line)}</p>")
        i += 1
    if in_list:
        out.append("</ul>")
    css = (":root{--bg:#f4f6fa;--card:#fff;--ink:#172033;--muted:#5b667a;--line:#dfe4ee;--accent:#2563eb}"
           "@media(prefers-color-scheme:dark){:root{--bg:#0b1020;--card:#131a2e;--ink:#e6ebf5;--muted:#9aa6bd;"
           "--line:#25304a;--accent:#5b8cff}}"
           "body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 system-ui,Segoe UI,sans-serif}"
           "main{max-width:980px;margin:0 auto;padding:24px 16px 60px}"
           "h1{font-size:1.7rem}h2{margin-top:34px;padding-top:14px;border-top:1px solid var(--line);color:var(--accent)}"
           "h3{margin-top:22px}.tw{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:.9rem;"
           "background:var(--card);border:1px solid var(--line);border-radius:8px}"
           "th,td{border-bottom:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top}"
           "th{color:var(--muted);font-size:.78rem;text-transform:uppercase;letter-spacing:.04em}"
           "figure{margin:14px 0;text-align:center}img{max-width:100%;background:#fff;border-radius:8px;"
           "border:1px solid var(--line)}code{background:var(--card);border:1px solid var(--line);border-radius:5px;"
           "padding:0 5px;font-size:.88em}")
    return ("<!doctype html><html lang='es'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>Informe experimental - ComplexNet API</title><style>" + css + "</style></head><body><main>"
            + "\n".join(out) + "</main></body></html>")


def main():
    run = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else latest_run()
    os.makedirs(DOCS, exist_ok=True)
    text = build(run)
    target = os.path.join(DOCS, "INFORME_EXPERIMENTAL.md")
    with open(target, "w", encoding="utf-8") as handle:
        handle.write(text)
    with open(os.path.join(DOCS, "INFORME_EXPERIMENTAL.html"), "w", encoding="utf-8") as handle:
        handle.write(to_html(text))
    os.makedirs(INFORME, exist_ok=True)
    tex_target = os.path.join(INFORME, "fase3_resultados.tex")
    with open(tex_target, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(build_tex(run))
    # Bloque único para pegar antes de \end{document}: sección + resultados, figuras en images/
    section_path = os.path.join(INFORME, "seccion_fase3.tex")
    paste_target = os.path.join(INFORME, "fase3_para_pegar.tex")
    with open(section_path, encoding="utf-8") as handle:
        section = handle.read()
    with open(tex_target, encoding="utf-8") as handle:
        results = handle.read()
    block = section.replace("\\input{fase3_resultados}", results).replace("{figuras/", "{images/")
    with open(paste_target, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(block)
    print(f"Informe generado: {target}\nSección LaTeX: {tex_target}\nBloque para pegar: {paste_target}\n"
          f"Corrida: {run}")


if __name__ == "__main__":
    main()
