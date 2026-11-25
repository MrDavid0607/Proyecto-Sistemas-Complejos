"""Aplicación 1 — Monitoreo distribuido de disponibilidad y recursos con alertas.

    python applications/monitoring_app/app.py --id nodo-01

Este nodo vigila el clúster con la información que ya recibe por los RESOURCE_BEACON y
genera alertas que **difunde a todos los nodos** (mensaje ALERT), de modo que cada nodo
mantiene su propio registro de alertas sin servidor central. Reglas:

  * CRITICAL  un nodo pasa a OFFLINE.
  * INFO      un nodo vuelve a estar ONLINE.
  * WARNING   CPU libre < --cpu-min %  |  RAM libre < --ram-min MB  |  latencia > --latency-max ms

Además guarda una serie de tiempo (CSV) con CPU, RAM y latencia de cada nodo y un registro
de alertas en JSON lines. El panel web del nodo muestra el clúster y las alertas en vivo.
"""

import argparse
import csv
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import common  # noqa: E402


def main():
    parser = common.add_node_arguments(argparse.ArgumentParser(description=__doc__,
                                       formatter_class=argparse.RawDescriptionHelpFormatter))
    parser.add_argument("--cpu-min", type=float, default=15.0)
    parser.add_argument("--ram-min", type=float, default=500.0)
    parser.add_argument("--latency-max", type=float, default=100.0)
    parser.add_argument("--interval", type=float, default=2.0, help="segundos entre muestras")
    parser.add_argument("--cooldown", type=float, default=30.0,
                        help="segundos antes de repetir la misma alerta")
    parser.add_argument("--duration", type=float, default=0,
                        help="segundos a monitorear (0 = hasta Ctrl+C)")
    args = parser.parse_args()

    out_dir = os.path.join(os.path.dirname(__file__), "output")
    os.makedirs(out_dir, exist_ok=True)
    node, server = common.start_node(args)

    last_alert = {}

    def alert(level, key, text, **fields):
        now = time.time()
        if now - last_alert.get(key, 0) < args.cooldown:
            return
        last_alert[key] = now
        node.raise_alert(level, text, **fields)
        with open(os.path.join(out_dir, "alertas.jsonl"), "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"ts": now, "level": level, "text": text, **fields}) + "\n")

    def on_event(record):          # alertas por cambios de disponibilidad
        if record["event"] == "FAILURE":
            alert("critical", f"down:{record['peer']}", f"{record['peer']} está OFFLINE",
                  peer=record["peer"])
        elif record["event"] == "RECOVERY":
            alert("info", f"up:{record['peer']}", f"{record['peer']} volvió a estar ONLINE",
                  peer=record["peer"])

    node.on_event(on_event)

    series = open(os.path.join(out_dir, "metricas.csv"), "w", newline="", encoding="utf-8")
    writer = csv.writer(series)
    writer.writerow(["ts", "node", "status", "cpu_free_pct", "ram_free_mb", "latency_ms"])
    print("\nMonitoreando el clúster (Ctrl+C para terminar)...\n")
    deadline = time.time() + args.duration if args.duration else None
    try:
        while deadline is None or time.time() < deadline:
            now = time.time()
            state = node.resources.state()
            writer.writerow([round(now, 2), node.node_id, "SELF", state["cpu_free_pct"],
                             state["ram_free_mb"], 0])
            for peer in node.peers.all():
                writer.writerow([round(now, 2), peer.node_id, peer.status, peer.cpu_free_pct,
                                 peer.ram_free_mb,
                                 "" if peer.latency_ms is None else round(peer.latency_ms, 2)])
                if peer.status != "ONLINE":
                    continue
                if peer.cpu_free_pct < args.cpu_min:
                    alert("warning", f"cpu:{peer.node_id}",
                          f"CPU libre baja en {peer.node_id}: {peer.cpu_free_pct:.1f}%",
                          peer=peer.node_id)
                if peer.ram_free_mb < args.ram_min:
                    alert("warning", f"ram:{peer.node_id}",
                          f"RAM libre baja en {peer.node_id}: {peer.ram_free_mb:.0f} MB",
                          peer=peer.node_id)
                if peer.latency_ms is not None and peer.latency_ms > args.latency_max:
                    alert("warning", f"lat:{peer.node_id}",
                          f"Latencia alta hacia {peer.node_id}: {peer.latency_ms:.0f} ms",
                          peer=peer.node_id)
            series.flush()
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        series.close()
        print(f"\nSerie de tiempo y alertas guardadas en {out_dir}")
        common.stop_node(node, server)


if __name__ == "__main__":
    main()
