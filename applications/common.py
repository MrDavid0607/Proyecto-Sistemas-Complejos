"""Utilidades compartidas por las aplicaciones de demostración.

Cada aplicación es un nodo más de la red: arranca un `Node` de ComplexNet (con el
panel HTTP opcional) y usa la API de alto nivel para repartir su trabajo.
"""

import argparse
import os
import sys
import time

HOLD_SECONDS = 0.0
HOLD_PORT = 8000

ROOT =os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

from complexnet import Node, NodeConfig  # noqa: E402
from complexnet.monitoring import StatusServer  # noqa: E402
from complexnet.scheduler import STRATEGIES  # noqa: E402


def add_node_arguments(parser):
    parser.add_argument("--id", required=True, help="identificador del nodo, p. ej. nodo-01")
    parser.add_argument("--port", type=int, default=9999)
    parser.add_argument("--ip", default=None, help="IP de este equipo (por defecto se detecta)")
    parser.add_argument("--broadcast", default="auto",
                        help="dirección de broadcast de la subred, 'auto' (por defecto) "
                             "o 'none' para desactivarlo")
    parser.add_argument("--peers", default="",
                        help="IPs o host:puerto de los otros nodos, separados por coma "
                             "(si la red bloquea el broadcast)")
    parser.add_argument("--bandwidth", type=float, default=100.0)
    parser.add_argument("--strategy", default="weighted_load", choices=STRATEGIES)
    parser.add_argument("--slots", type=int, default=2,
                        help="tareas que este nodo ejecuta a la vez")
    parser.add_argument("--http-port", type=int, default=8000,
                        help="puerto del panel web de este nodo (0 = sin panel)")
    parser.add_argument("--expected-peers", type=int, default=2,
                        help="vecinos que se esperan antes de empezar")
    parser.add_argument("--log-dir", default=os.path.join(ROOT, "logs"))
    parser.add_argument("--hold", type=float, default=0.0,
                        help="segundos que el nodo y su panel siguen activos al terminar "
                             "(para mostrar la tabla de tareas)")
    return parser


def parse_peers(text, default_port):
    peers = []
    for item in text.split(","):
        item = item.strip()
        if not item:
            continue
        if ":" in item:
            host, _, port = item.rpartition(":")
            peers.append((host, int(port)))
        else:
            peers.append((item, default_port))
    return peers


def start_node(args, console_log=True):
    """Crea y conecta el nodo de la aplicación; espera a los vecinos esperados."""
    global HOLD_SECONDS, HOLD_PORT
    HOLD_SECONDS = getattr(args, "hold", 0.0) or 0.0
    HOLD_PORT = args.http_port or 8000
    broadcast = None if args.broadcast.lower() in ("", "none", "no") else args.broadcast
    config = NodeConfig(
        port=args.port,
        broadcast_address=broadcast,
        seed_peers=parse_peers(args.peers, args.port),
        bandwidth_mbps=args.bandwidth,
        strategy=args.strategy,
        slots=args.slots,
        log_dir=args.log_dir,
        ip_address=args.ip,
        console_log=console_log,
    )
    node = Node(args.id, config).connect()
    server = None
    if args.http_port:
        server = StatusServer(node, args.http_port)
        server.start()
        print(f"Panel del nodo: http://{node.ip_address}:{args.http_port}")
    print(f"Esperando {args.expected_peers} vecinos...", flush=True)
    if not node.wait_for_peers(args.expected_peers, timeout=60):
        print("No se descubrieron los vecinos esperados; se continúa con los disponibles.")
    names = ", ".join(sorted(p.node_id for p in node.peers.active())) or "ninguno"
    print(f"Vecinos activos: {names}", flush=True)
    return node, server


def stop_node(node, server):
    # --hold: mantiene el nodo y el panel vivos al terminar para poder mostrar las tareas.
    if HOLD_SECONDS > 0 and server:
        print(f"\nTrabajo terminado. El panel sigue activo {HOLD_SECONDS:g} s "
              f"(http://localhost:{HOLD_PORT}); "
              "Ctrl+C para cerrar antes.", flush=True)
        try:
            time.sleep(HOLD_SECONDS)
        except KeyboardInterrupt:
            pass
    if server:
        server.stop()
    node.disconnect()


def tasks_per_node(tasks):
    """{nodo: cantidad de tareas completadas} a partir de una lista de Task."""
    counts = {}
    for task in tasks:
        if task.state == "COMPLETED":
            counts[task.executed_by] = counts.get(task.executed_by, 0) + 1
    return dict(sorted(counts.items()))
