"""Monitor del nodo: tabla en terminal y endpoint HTTP de estado/tareas."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ..tasks import Task


def format_status(node):
    status = node.status()
    lines = [
        "",
        f"========== {node.node_id} | Lamport {status['lamport']} ==========",
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


_PAGE = """<!doctype html><meta charset="utf-8"><title>{node}</title>
<meta http-equiv="refresh" content="3">
<style>body{{font-family:monospace;margin:1.5rem}}table{{border-collapse:collapse}}
td,th{{border:1px solid #888;padding:2px 8px}}.OFFLINE{{color:#b00}}</style>
<h2>{node} <small>Lamport {lamport}</small></h2>
<h3>PeerTable</h3><table><tr><th>nodo</th><th>dirección</th><th>estado</th>
<th>CPU libre %</th><th>RAM libre MB</th><th>BW Mbps</th><th>latencia ms</th>
<th>reputación</th><th>tareas</th></tr>{peers}</table>
<h3>Tareas recientes</h3><table><tr><th>id</th><th>nombre</th><th>estado</th>
<th>nodo</th><th>intentos</th><th>reasignaciones</th></tr>{tasks}</table>
<h3>Métricas</h3><pre>{metrics}</pre>
<h3>Eventos</h3><pre>{events}</pre>"""


def _render_page(node):
    status = node.status()
    peers = "".join(
        f"<tr class='{p['status']}'><td>{p['node_id']}</td>"
        f"<td>{p['ip']}:{p['port']}</td><td>{p['status']}</td>"
        f"<td>{p['cpu_free_pct']:.1f}</td><td>{p['ram_free_mb']:.0f}</td>"
        f"<td>{p['bandwidth_mbps']:.0f}</td>"
        f"<td>{'' if p['latency_ms'] is None else round(p['latency_ms'], 1)}</td>"
        f"<td>{p['reputation']:.2f}</td><td>{p['active_tasks']}</td></tr>"
        for p in status["peers"]
    )
    tasks = "".join(
        f"<tr><td>{t['task_id']}</td><td>{t['name']}</td><td>{t['state']}</td>"
        f"<td>{t['executed_by'] or t['assigned_node'] or ''}</td>"
        f"<td>{t['attempts']}</td><td>{t['reassignments']}</td></tr>"
        for t in status["tasks"]
    )
    events = "\n".join(
        json.dumps(e, ensure_ascii=False) for e in node.log.recent(15)
    )
    return _PAGE.format(
        node=node.node_id,
        lamport=status["lamport"],
        peers=peers,
        tasks=tasks,
        metrics=json.dumps(status["metrics"], indent=2),
        events=events,
    )


class StatusServer:
    """GET /status, /events, /tasks/<id>, / (HTML) y POST /tasks."""

    def __init__(self, node, port=8000, host="0.0.0.0"):
        self.node = node
        server_node = node

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, code, body, content_type="application/json"):
                data = (
                    body if isinstance(body, bytes) else body.encode("utf-8")
                )
                self.send_response(code)
                self.send_header("Content-Type", content_type + "; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

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
                    self._send(200, _render_page(server_node), "text/html")
                else:
                    self._send(404, json.dumps({"error": "ruta no encontrada"}))

            def do_POST(self):
                if self.path != "/tasks":
                    self._send(404, json.dumps({"error": "ruta no encontrada"}))
                    return
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = json.loads(self.rfile.read(length) or b"{}")
                    task = Task(
                        body["name"],
                        body.get("parameters"),
                        body.get("requirements"),
                    )
                except (KeyError, ValueError) as error:
                    self._send(400, json.dumps({"error": f"petición inválida: {error}"}))
                    return
                server_node.submit(
                    task, allow_local=bool(body.get("allow_local", True)), wait=False
                )
                self._send(202, json.dumps({"task_id": task.task_id}))

        self._server = ThreadingHTTPServer((host, port), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True, name="status-http"
        )

    def start(self):
        self._thread.start()

    def stop(self):
        self._server.shutdown()
        self._server.server_close()
