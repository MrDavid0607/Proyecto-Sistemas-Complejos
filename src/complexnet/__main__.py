"""Ejecuta un nodo ComplexNet:  python -m complexnet --id nodo-01 ..."""

import argparse
import os
import time

from .monitoring import StatusServer, TerminalMonitor
from .node import Node, NodeConfig
from .scheduler import STRATEGIES


def parse_peer(text):
    host, _, port = text.rpartition(":")
    return (host, int(port))


def build_parser():
    env = os.environ.get
    parser = argparse.ArgumentParser(
        prog="complexnet", description="Nodo de ComplexNet API"
    )
    parser.add_argument("--id", default=env("NODE_ID"), required=env("NODE_ID") is None)
    parser.add_argument("--port", type=int, default=int(env("NODE_PORT", 9999)))
    parser.add_argument(
        "--broadcast", default=env("BROADCAST_ADDRESS"),
        help="dirección de broadcast de la subred (p. ej. 192.168.1.255) o 'auto' "
             "para detectarla",
    )
    parser.add_argument(
        "--peers", default=env("SEED_PEERS", ""),
        help="vecinos conocidos host:puerto separados por coma (útil si la red "
             "bloquea el broadcast); también se acepta solo la IP",
    )
    parser.add_argument(
        "--bandwidth", type=float, default=float(env("BANDWIDTH_MBPS", 100))
    )
    parser.add_argument("--beacon-interval", type=float,
                        default=float(env("BEACON_INTERVAL", 2)))
    parser.add_argument("--timeout", type=float, default=float(env("NODE_TIMEOUT", 5)))
    parser.add_argument("--slots", type=int, default=int(env("SLOTS", 2)),
                        help="tareas que el nodo ejecuta a la vez (el resto espera en cola)")
    parser.add_argument("--strategy", default=env("STRATEGY", "weighted_load"),
                        choices=STRATEGIES, help="estrategia de asignación de tareas")
    parser.add_argument("--http-port", type=int, default=int(env("HTTP_PORT", 0)),
                        help="puerto del panel HTTP de monitoreo (0 = desactivado)")
    parser.add_argument("--log-dir", default=env("LOG_DIR"))
    parser.add_argument("--ip", default=env("NODE_IP"),
                        help="IP de este equipo (por defecto se detecta)")
    parser.add_argument("--monitor-interval", type=float, default=10.0)
    return parser


def main():
    args = build_parser().parse_args()
    peers = []
    for item in args.peers.split(","):
        item = item.strip()
        if not item:
            continue
        peers.append(parse_peer(item) if ":" in item else (item, args.port))
    config = NodeConfig(
        port=args.port,
        broadcast_address=args.broadcast,
        seed_peers=peers,
        bandwidth_mbps=args.bandwidth,
        beacon_interval=args.beacon_interval,
        node_timeout=args.timeout,
        ack_timeout=args.timeout,
        strategy=args.strategy,
        slots=args.slots,
        log_dir=args.log_dir,
        ip_address=args.ip,
    )
    node = Node(args.id, config).connect()
    monitor = TerminalMonitor(node, args.monitor_interval)
    monitor.start()
    server = None
    if args.http_port:
        server = StatusServer(node, args.http_port)
        server.start()
        node.log.event("HTTP_STARTED", url=f"http://{node.ip_address}:{args.http_port}")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        monitor.stop()
        if server:
            server.stop()
        node.disconnect()


if __name__ == "__main__":
    main()
