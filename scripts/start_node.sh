#!/usr/bin/env bash
# Arranca un nodo ComplexNet en este computador (Linux / macOS).
#
#   ./scripts/start_node.sh nodo-02
#   ./scripts/start_node.sh nodo-02 192.168.1.5,192.168.1.7     # si el broadcast no funciona
set -e
ID="${1:?Uso: ./scripts/start_node.sh <id-del-nodo> [ips-de-los-otros-nodos]}"
PEERS="${2:-}"
cd "$(dirname "$0")/.."

[ -d .venv ] || python3 -m venv .venv
.venv/bin/python -c "import psutil, numpy" 2>/dev/null || .venv/bin/pip install -q -r requirements.txt

IP=$(.venv/bin/python -c "import sys; sys.path.insert(0,'src'); from complexnet.node import get_local_ip; print(get_local_ip())")
echo "Nodo: $ID | IP detectada: $IP | Panel: http://localhost:8000"

PYTHONPATH=src exec .venv/bin/python -m complexnet --id "$ID" --broadcast auto --peers "$PEERS" \
    --http-port 8000 --log-dir logs
