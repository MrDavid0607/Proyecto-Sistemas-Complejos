"""Monitor del nodo: tabla en terminal y servidor HTTP (panel web + API)."""

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ..tasks import Task

DASHBOARD = os.path.join(os.path.dirname(__file__), "dashboard.html")


def format_status(node):
    status = node.status()
    lines = [
        "",
        f"========== {node.node_id} | Lamport {status['lamport']} | "
        f"estrategia {status['strategy']} ==========",
        "PEER TABLE",
    ]
    if not status["peers"]:
        lines.append("  (sin vecinos descubiertos)")
    for p in status["peers"]:
        latency = (
            f"{p['latency_ms']:.1f} ms" if p["latency_ms"] is not None else "n/d"
        )
        lines.append(
            f"  {p['node_id']:<10} {p['ip']}:{p['port']:<5} {p['status']:<7} "
            f"CPU libre {p['cpu_free_pct']:>5.1f}% | RAM libre "
            f"{p['ram_free_mb']:>8.0f} MB | BW {p['bandwidth_mbps']:>5.0f} Mbps | "
            f"lat {latency:>8} | rep {p['reputation']:.2f} | "
            f"tareas {p['active_tasks']}"
        )
    metrics = status["metrics"]
    lines.append(
        "TAREAS  enviadas={tasks_submitted} completadas={tasks_completed} "
        "falladas={tasks_failed} reasignadas={tasks_reassigned}".format(**metrics)
    )
    lines.append(
        f"MÉTRICAS  latencia media={metrics['avg_latency_ms']} ms | "
        f"asignación={metrics['avg_assignment_time_ms']} ms | "
        f"recuperación={metrics['avg_recovery_time_sec']} s | "
        f"fallos detectados={metrics['failures_detected']}"
    )
    lines.append("=" * 60)
    return "\n".join(lines)


class TerminalMonitor:

    def __init__(self, node, interval=10.0):
        self.node = node
        self.interval = interval
        self._thread = None
        self._running = False

    def start(self):
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="terminal-monitor"
        )
        self._thread.start()

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            time.sleep(self.interval)
            if self._running and self.node.running:
                print(format_status(self.node), flush=True)


class StatusServer:
    """Panel web y API HTTP de un nodo.

    GET  /                panel del clúster (HTML)
    GET  /status          estado completo del nodo (JSON)
    GET  /events          últimos eventos
    GET  /tasks/<id>      estado de una tarea
    POST /tasks           {"name","parameters","requirements","allow_local"} -> envía una tarea
    POST /admin/fail      {"seconds": N} simula una caída del nodo durante N segundos
    POST /admin/strategy  {"strategy": "..."} cambia la estrategia de asignación

    Los endpoints /admin son para el laboratorio (experimentos); no tienen autenticación.
    """

    def __init__(self, node, port=8000, host="0.0.0.0"):
        self.node = node
        server_node = node

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, code, body, content_type="application/json"):
                data = body if isinstance(body, bytes) else body.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", content_type + "; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(data)

            def _json_body(self):
                length = int(self.headers.get("Content-Length", 0))
                return json.loads(self.rfile.read(length) or b"{}")

            def do_GET(self):
                if self.path == "/status":
                    self._send(200, json.dumps(server_node.status()))
                elif self.path == "/events":
                    self._send(200, json.dumps(server_node.log.recent(100)))
                elif self.path.startswith("/tasks/"):
                    task = server_node.tasks.tasks.get(self.path.split("/")[-1])
                    if task is None:
                        self._send(404, json.dumps({"error": "tarea no encontrada"}))
                    else:
                        self._send(200, json.dumps(task.to_dict()))
                elif self.path in ("/", "/index.html"):
                    with open(DASHBOARD, "rb") as handle:
                        self._send(200, handle.read(), "text/html")
                else:
                    self._send(404, json.dumps({"error": "ruta no encontrada"}))

            def do_POST(self):
                try:
                    body = self._json_body()
                    if self.path == "/tasks":
                        task = Task(
                            body["name"],
                            body.get("parameters"),
                            body.get("requirements"),
                        )
                        server_node.submit(
                            task,
                            allow_local=bool(body.get("allow_local", True)),
                            wait=False,
                        )
                        self._send(202, json.dumps({"task_id": task.task_id}))
                    elif self.path == "/admin/fail":
                        server_node.simulate_failure(float(body.get("seconds", 10)))
                        self._send(200, json.dumps({"ok": True}))
                    elif self.path == "/admin/strategy":
                        server_node.set_strategy(body["strategy"])
                        self._send(200, json.dumps({"ok": True}))
                    else:
                        self._send(404, json.dumps({"error": "ruta no encontrada"}))
                except (KeyError, ValueError) as error:
                    self._send(400, json.dumps({"error": f"petición inválida: {error}"}))

        self._server = ThreadingHTTPServer((host, port), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True, name="status-http"
        )

    def start(self):
        self._thread.start()

    def stop(self):
        self._server.shutdown()
        self._server.server_close()
