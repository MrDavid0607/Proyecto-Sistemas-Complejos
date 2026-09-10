import argparse
import json
import socket
import threading
import time
import uuid

import psutil


# ---------------------------------------------------------
# Configuración general
# ---------------------------------------------------------

BROADCAST_ADDRESS = "255.255.255.255"

BEACON_INTERVAL = 2
NODE_TIMEOUT = 5


# ---------------------------------------------------------
# Obtener IP local
# ---------------------------------------------------------

def get_local_ip():
    """
    Obtiene la dirección IP local utilizada por el computador.
    """

    sock = socket.socket(
        socket.AF_INET,
        socket.SOCK_DGRAM
    )

    try:
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]

    except Exception:
        ip = socket.gethostbyname(
            socket.gethostname()
        )

    finally:
        sock.close()

    return ip


# ---------------------------------------------------------
# Nodo ComplexNet
# ---------------------------------------------------------

class ComplexNetNode:

    def __init__(
        self,
        node_id,
        port,
        local_test=False,
        peer_port=None
    ):

        self.node_id = node_id
        self.port = port

        self.local_test = local_test
        self.peer_port = peer_port

        self.ip_address = get_local_ip()

        # Tabla local de vecinos
        self.peer_table = {}

        self.running = True


        # -------------------------------------------------
        # Socket receptor
        # -------------------------------------------------

        self.receive_socket = socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM
        )

        self.receive_socket.setsockopt(
            socket.SOL_SOCKET,
            socket.SO_REUSEADDR,
            1
        )

        self.receive_socket.bind(
            ("", self.port)
        )

        self.receive_socket.settimeout(1)


        # -------------------------------------------------
        # Socket emisor
        # -------------------------------------------------

        self.send_socket = socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM
        )

        self.send_socket.setsockopt(
            socket.SOL_SOCKET,
            socket.SO_BROADCAST,
            1
        )


    # -----------------------------------------------------
    # Crear RESOURCE_BEACON
    # -----------------------------------------------------

    def create_resource_beacon(self):

        cpu_used = psutil.cpu_percent(
            interval=None
        )

        cpu_free = 100 - cpu_used

        ram_free = (
            psutil.virtual_memory().available
            / (1024 * 1024)
        )

        beacon = {
            "header": {
                "message_id": str(
                    uuid.uuid4()
                ),
                "sender_id": self.node_id,
                "type": "RESOURCE_BEACON",
                "timestamp": int(
                    time.time() * 1000
                )
            },

            "payload": {
                "ip_address": (
                    "127.0.0.1"
                    if self.local_test
                    else self.ip_address
                ),

                "port": self.port,

                "cpu_free_pct": round(
                    cpu_free,
                    2
                ),

                "ram_free_mb": round(
                    ram_free,
                    2
                ),

                "active_tasks": 0
            }
        }

        return beacon


    # -----------------------------------------------------
    # Determinar destino del beacon
    # -----------------------------------------------------

    def get_beacon_destination(self):

        if self.local_test:

            return (
                "127.0.0.1",
                self.peer_port
            )

        return (
            BROADCAST_ADDRESS,
            self.port
        )


    # -----------------------------------------------------
    # Enviar RESOURCE_BEACON
    # -----------------------------------------------------

    def send_resource_beacons(self):

        destination = (
            self.get_beacon_destination()
        )

        while self.running:

            beacon = (
                self.create_resource_beacon()
            )

            message = json.dumps(
                beacon
            ).encode("utf-8")

            try:

                self.send_socket.sendto(
                    message,
                    destination
                )

                if self.local_test:

                    print(
                        f"[BEACON] {self.node_id} -> "
                        f"localhost:{self.peer_port}"
                    )

                else:

                    print(
                        f"[BEACON] {self.node_id} "
                        f"anunció su presencia "
                        f"por UDP broadcast."
                    )

            except OSError as error:

                if self.running:

                    print(
                        f"[ERROR] No se pudo "
                        f"enviar beacon: {error}"
                    )

            time.sleep(
                BEACON_INTERVAL
            )


    # -----------------------------------------------------
    # Escuchar RESOURCE_BEACON
    # -----------------------------------------------------

    def listen_for_beacons(self):

        while self.running:

            try:

                data, address = (
                    self.receive_socket.recvfrom(
                        65535
                    )
                )

                message = json.loads(
                    data.decode("utf-8")
                )

                header = message.get(
                    "header",
                    {}
                )

                if (
                    header.get("type")
                    == "RESOURCE_BEACON"
                ):

                    self.process_resource_beacon(
                        message,
                        address
                    )

            except socket.timeout:

                continue

            except json.JSONDecodeError:

                print(
                    "[ERROR] Se recibió "
                    "un JSON inválido."
                )

            except OSError as error:

                if self.running:

                    print(
                        f"[ERROR] Error "
                        f"recibiendo mensaje: {error}"
                    )

                continue


    # -----------------------------------------------------
    # Procesar RESOURCE_BEACON
    # -----------------------------------------------------

    def process_resource_beacon(
        self,
        message,
        address
    ):

        header = message["header"]
        payload = message["payload"]

        sender_id = (
            header["sender_id"]
        )

        # Ignorar mensajes propios
        if sender_id == self.node_id:
            return


        is_new_peer = (
            sender_id
            not in self.peer_table
        )


        previous_status = None

        if not is_new_peer:

            previous_status = (
                self.peer_table[
                    sender_id
                ]["status"]
            )


        self.peer_table[
            sender_id
        ] = {

            "ip_address": payload.get(
                "ip_address",
                address[0]
            ),

            "port": payload.get(
                "port"
            ),

            "cpu_free_pct": payload.get(
                "cpu_free_pct"
            ),

            "ram_free_mb": payload.get(
                "ram_free_mb"
            ),

            "active_tasks": payload.get(
                "active_tasks"
            ),

            "last_seen": time.time(),

            "status": "ONLINE"
        }


        if is_new_peer:

            print()
            print(
                "================================"
            )

            print(
                "[DISCOVERY] Nuevo nodo descubierto"
            )

            print(
                f"Node ID: {sender_id}"
            )

            print(
                f"IP: "
                f"{self.peer_table[sender_id]['ip_address']}"
            )

            print(
                f"Puerto: "
                f"{self.peer_table[sender_id]['port']}"
            )

            print(
                "Estado: ONLINE"
            )

            print(
                "================================"
            )
            print()


        elif previous_status == "OFFLINE":

            print()
            print(
                f"[RECOVERY] {sender_id} "
                f"volvió a estar ONLINE."
            )
            print()


    # -----------------------------------------------------
    # Detectar nodos inactivos
    # -----------------------------------------------------

    def check_timeouts(self):

        while self.running:

            current_time = time.time()

            for node_id, peer in list(
                self.peer_table.items()
            ):

                elapsed = (
                    current_time
                    - peer["last_seen"]
                )

                if (
                    elapsed > NODE_TIMEOUT
                    and
                    peer["status"] == "ONLINE"
                ):

                    peer["status"] = "OFFLINE"

                    print()
                    print(
                        f"[FAILURE] {node_id} "
                        f"no responde desde hace "
                        f"más de {NODE_TIMEOUT} segundos."
                    )

                    print(
                        "Estado: OFFLINE"
                    )

                    print()

            time.sleep(1)


    # -----------------------------------------------------
    # Mostrar PeerTable
    # -----------------------------------------------------

    def show_peer_table(self):

        while self.running:

            time.sleep(10)

            print()
            print(
                "========== PEER TABLE =========="
            )

            if not self.peer_table:

                print(
                    "No se han descubierto "
                    "otros nodos."
                )

            else:

                for node_id, peer in (
                    self.peer_table.items()
                ):

                    print(
                        f"{node_id} | "
                        f"{peer['ip_address']}:"
                        f"{peer['port']} | "
                        f"{peer['status']} | "
                        f"CPU libre: "
                        f"{peer['cpu_free_pct']}% | "
                        f"RAM libre: "
                        f"{peer['ram_free_mb']} MB"
                    )

            print(
                "================================"
            )
            print()


    # -----------------------------------------------------
    # Iniciar nodo
    # -----------------------------------------------------

    def start(self):

        print()
        print(
            "======================================"
        )

        print(
            "       ComplexNet API - Node"
        )

        print(
            "======================================"
        )

        print(
            f"Node ID: {self.node_id}"
        )


        if self.local_test:

            print(
                "Modo: PRUEBA LOCAL"
            )

            print(
                f"Puerto local: {self.port}"
            )

            print(
                f"Puerto del nodo destino: "
                f"{self.peer_port}"
            )

        else:

            print(
                "Modo: RED"
            )

            print(
                f"IP local: {self.ip_address}"
            )

            print(
                f"Puerto: {self.port}"
            )


        print(
            f"Beacon interval: "
            f"{BEACON_INTERVAL} segundos"
        )

        print(
            f"Timeout: "
            f"{NODE_TIMEOUT} segundos"
        )

        print(
            "======================================"
        )

        print()
        print(
            "[SYSTEM] Servicio "
            "de discovery iniciado."
        )
        print()


        sender_thread = threading.Thread(
            target=self.send_resource_beacons,
            daemon=True
        )

        listener_thread = threading.Thread(
            target=self.listen_for_beacons,
            daemon=True
        )

        timeout_thread = threading.Thread(
            target=self.check_timeouts,
            daemon=True
        )

        peer_table_thread = threading.Thread(
            target=self.show_peer_table,
            daemon=True
        )


        sender_thread.start()
        listener_thread.start()
        timeout_thread.start()
        peer_table_thread.start()


        try:

            while True:
                time.sleep(1)

        except KeyboardInterrupt:

            print()
            print(
                "[SYSTEM] Cerrando nodo..."
            )

            self.running = False

            self.receive_socket.close()
            self.send_socket.close()

            print(
                "[SYSTEM] Nodo detenido."
            )


# ---------------------------------------------------------
# Main
# ---------------------------------------------------------

if __name__ == "__main__":

    parser = argparse.ArgumentParser(
        description=(
            "ComplexNet API - "
            "Prueba de concepto"
        )
    )


    parser.add_argument(
        "--id",
        required=True,
        help=(
            "Identificador único del nodo. "
            "Ejemplo: nodo-01"
        )
    )


    parser.add_argument(
        "--port",
        type=int,
        default=9999,
        help=(
            "Puerto UDP donde "
            "escuchará el nodo."
        )
    )


    parser.add_argument(
        "--local-test",
        action="store_true",
        help=(
            "Ejecutar dos nodos en "
            "el mismo computador."
        )
    )


    parser.add_argument(
        "--peer-port",
        type=int,
        help=(
            "Puerto del otro nodo "
            "durante la prueba local."
        )
    )


    args = parser.parse_args()


    if (
        args.local_test
        and args.peer_port is None
    ):

        parser.error(
            "--peer-port es obligatorio "
            "cuando se utiliza --local-test"
        )


    node = ComplexNetNode(
        node_id=args.id,
        port=args.port,
        local_test=args.local_test,
        peer_port=args.peer_port
    )

    node.start()